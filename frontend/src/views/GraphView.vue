<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import G6 from '@antv/g6'
import { getMergedGraph, listTextbooks } from '../api'
import BioDecor from '../components/BioDecor.vue'

const emit = defineEmits(['back'])
const container = ref(null)
const detail = ref(null)
const loading = ref(true)
const viewMode = ref('force')
const editNode = ref(null)
const editDraft = ref({ name: '', definition: '' })
const stats = ref({ nodes: 0, edges: 0 })

// 高阶交互：搜索 + 按教材筛选
const searchQuery = ref('')
const filterTextbook = ref('all')
const textbookOptions = ref([]) // [{id, title}]

let graph = null
let rawData = { nodes: [], edges: [] }
const nodePositions = new Map()

const REL_COLOR = {
  prerequisite: '#6f9584',
  parallel: '#a8b4ad',
  contains: '#87a999',
  applies_to: '#9a8f75',
}

// category → 形状映射（C 可视化加分项）
const CATEGORY_SHAPE = {
  '核心概念': 'circle',
  '定理': 'rect',
  '方法': 'ellipse',
  '现象': 'diamond',
  '图像区块': 'rect',
}

function nodeStyle(node) {
  const radius = 18 + Math.min(node.frequency || 1, 6) * 4
  const isVisual = node.category === '图像区块'
  const shape = CATEGORY_SHAPE[node.category] || 'circle'
  const sizeScalar = isVisual ? 26 : radius
  // 矩形/菱形/椭圆需要 [w, h]
  const sized = (shape === 'rect' || shape === 'diamond' || shape === 'ellipse')
    ? { type: shape, size: [sizeScalar * 2.2, sizeScalar * 1.1] }
    : { type: shape, size: sizeScalar }
  return {
    ...sized,
    style: {
      fill: isVisual ? '#f7fbf8' : '#ffffff',
      stroke: isVisual ? '#9a8f75' : '#6f9584',
      lineWidth: 1.5,
      opacity: 1,
    },
  }
}

function graphDataFromMerged(merged) {
  return {
    nodes: (merged.nodes || []).map((node, index) => {
      const saved = nodePositions.get(node.id)
      const angle = (index / Math.max((merged.nodes || []).length, 1)) * Math.PI * 2
      return {
        id: node.id,
        label: node.name,
        x: saved?.x ?? 520 + Math.cos(angle) * 240,
        y: saved?.y ?? 320 + Math.sin(angle) * 160,
        ...nodeStyle(node),
        raw: node,
      }
    }),
    edges: (merged.edges || []).map(edge => ({
      source: edge.source,
      target: edge.target,
      label: edge.relation_type,
      style: {
        stroke: REL_COLOR[edge.relation_type] || '#d8dfda',
        lineDash: edge.relation_type === 'parallel' ? [4, 4] : null,
        endArrow: true,
      },
      raw: edge,
    })),
  }
}

function toTreeData(data) {
  const nodes = new Map(data.nodes.map(node => [node.id, { ...node, children: [] }]))
  const incoming = new Set()
  const preferred = data.edges.filter(edge => ['contains', 'prerequisite'].includes(edge.raw?.relation_type || edge.label))
  for (const edge of preferred) {
    const source = nodes.get(edge.source)
    const target = nodes.get(edge.target)
    if (source && target && source.id !== target.id && !incoming.has(target.id)) {
      source.children.push(target)
      incoming.add(target.id)
    }
  }
  const roots = [...nodes.values()].filter(node => !incoming.has(node.id))
  return {
    id: 'root',
    label: '知识树',
    raw: { name: '知识树', definition: '由知识图谱关系自动整理的树状视图' },
    children: roots.length ? roots : [...nodes.values()],
  }
}

function rememberPositions() {
  if (!graph || viewMode.value === 'tree') return
  graph.getNodes().forEach(item => {
    const model = item.getModel()
    nodePositions.set(model.id, { x: model.x, y: model.y })
  })
}

function destroyGraph() {
  if (graph) {
    rememberPositions()
    graph.destroy()
    graph = null
  }
}

function baseConfig() {
  return {
    container: container.value,
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    fitView: true,
    fitViewPadding: 56,
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    defaultNode: {
      type: 'circle',
      size: 30,
      style: { fill: '#fff', stroke: '#6f9584', lineWidth: 1.5, shadowColor: 'rgba(66, 91, 80, .12)', shadowBlur: 14 },
      labelCfg: { position: 'bottom', offset: 8, style: { fontSize: 11, fill: '#34433c' } },
    },
    defaultEdge: {
      type: 'line',
      style: { stroke: '#d8dfda', endArrow: { path: G6.Arrow.triangle(6, 8), fill: '#d8dfda' } },
      labelCfg: {
        autoRotate: true,
        style: {
          fontSize: 9,
          fill: '#7f8c86',
          background: { fill: '#fff', padding: [2, 4, 2, 4], radius: 2 },
        },
      },
    },
    nodeStateStyles: {
      active: { stroke: '#4f7f6a', lineWidth: 2.5, shadowBlur: 18 },
      inactive: { opacity: 0.25 },
    },
    edgeStateStyles: {
      active: { stroke: '#4f7f6a', lineWidth: 2 },
      inactive: { opacity: 0.18 },
    },
  }
}

function bindEvents() {
  graph.on('node:click', event => {
    detail.value = event.item.getModel().raw
  })
  graph.on('node:dblclick', event => {
    const raw = event.item.getModel().raw
    editNode.value = event.item
    editDraft.value = { name: raw.name || '', definition: raw.definition || '' }
  })
  graph.on('node:dragend', event => {
    const model = event.item.getModel()
    nodePositions.set(model.id, { x: model.x, y: model.y })
  })
  graph.on('node:mouseenter', event => {
    const item = event.item
    graph.setItemState(item, 'active', true)
    const edges = item.getEdges?.() || []
    edges.forEach(edge => graph.setItemState(edge, 'active', true))
  })
  graph.on('node:mouseleave', event => {
    const item = event.item
    graph.setItemState(item, 'active', false)
    const edges = item.getEdges?.() || []
    edges.forEach(edge => graph.setItemState(edge, 'active', false))
  })
  graph.on('canvas:click', () => {
    detail.value = null
  })
}

function renderGraph() {
  if (!container.value) return
  destroyGraph()
  if (!rawData.nodes.length) return
  if (viewMode.value === 'tree') {
    graph = new G6.TreeGraph({
      ...baseConfig(),
      modes: { default: ['drag-canvas', 'zoom-canvas', 'collapse-expand'] },
      layout: {
        type: 'compactBox',
        direction: 'LR',
        getId: d => d.id,
        getHeight: () => 34,
        getWidth: () => 130,
        getVGap: () => 18,
        getHGap: () => 48,
      },
      defaultNode: {
        type: 'rect',
        size: [128, 34],
        style: { radius: 6, fill: '#fff', stroke: '#cddbd4', lineWidth: 1.2 },
        labelCfg: { style: { fontSize: 11, fill: '#34433c' } },
      },
    })
    graph.data(toTreeData(rawData))
    graph.render()
  } else {
    graph = new G6.Graph({
      ...baseConfig(),
      layout: viewMode.value === 'force'
        ? { type: 'force', preventOverlap: true, linkDistance: 124, nodeStrength: -72 }
        : { type: 'preset' },
    })
    graph.data(rawData)
    graph.render()
  }
  bindEvents()
  graph.fitView(56)
}

async function load() {
  loading.value = true
  try {
    const [merged, books] = await Promise.all([
      getMergedGraph(),
      listTextbooks().catch(() => []),
    ])
    rawData = graphDataFromMerged(merged)
    stats.value = { nodes: rawData.nodes.length, edges: rawData.edges.length }
    // 教材筛选选项：同时收集图谱节点中出现的 textbook_id（可能为逗号分隔的多本）
    const titleMap = new Map((books || []).map(b => [b.textbook_id, b.title]))
    const set = new Set()
    rawData.nodes.forEach(n => {
      const ids = String(n.raw?.textbook_id || '').split(',').map(s => s.trim()).filter(Boolean)
      ids.forEach(id => set.add(id))
    })
    textbookOptions.value = [...set].map(id => ({ id, title: titleMap.get(id) || id }))
    await nextTick()
    renderGraph()
    applyHighlight()
  } catch (error) {
    console.error(error)
  } finally {
    loading.value = false
  }
}

function switchMode(mode) {
  viewMode.value = mode
  nextTick(() => {
    renderGraph()
    applyHighlight()
  })
}

// ----- 高阶交互：搜索 + 筛选 -----
function nodeMatches(rawNode) {
  const q = searchQuery.value.trim().toLowerCase()
  const tb = filterTextbook.value
  if (!rawNode) return true
  // 教材筛选
  if (tb && tb !== 'all') {
    const ids = String(rawNode.textbook_id || '').split(',').map(s => s.trim()).filter(Boolean)
    if (!ids.includes(tb)) return false
  }
  // 搜索匹配：名称 / 定义 / 章节
  if (q) {
    const hay = `${rawNode.name || ''} ${rawNode.definition || ''} ${rawNode.chapter || ''}`.toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}

function applyHighlight() {
  if (!graph) return
  const hasFilter = searchQuery.value.trim() || filterTextbook.value !== 'all'
  graph.getNodes().forEach(item => {
    const model = item.getModel()
    const raw = model.raw || {}
    const ok = nodeMatches(raw)
    graph.updateItem(item, {
      style: {
        ...(model.style || {}),
        opacity: ok ? 1 : 0.2,
        lineWidth: ok && hasFilter && searchQuery.value.trim() ? 2.4 : 1.5,
        stroke: ok && hasFilter && searchQuery.value.trim() ? '#4f7f6a' : (model.style?.stroke || '#6f9584'),
      },
      labelCfg: { style: { opacity: ok ? 1 : 0.25 } },
    })
  })
  graph.getEdges().forEach(item => {
    const m = item.getModel()
    const sNode = graph.findById(m.source)
    const tNode = graph.findById(m.target)
    const sOk = sNode && nodeMatches(sNode.getModel().raw)
    const tOk = tNode && nodeMatches(tNode.getModel().raw)
    graph.updateItem(item, {
      style: { ...(m.style || {}), opacity: (sOk && tOk) ? 1 : 0.12 },
    })
  })
}

watch([searchQuery, filterTextbook], () => applyHighlight())

function saveNodeEdit() {
  if (!editNode.value) return
  const model = editNode.value.getModel()
  model.label = editDraft.value.name
  model.raw = { ...model.raw, name: editDraft.value.name, definition: editDraft.value.definition }
  graph.updateItem(editNode.value, model)
  const source = rawData.nodes.find(node => node.id === model.id)
  if (source) {
    source.label = editDraft.value.name
    source.raw = model.raw
  }
  detail.value = model.raw
  editNode.value = null
}

function resize() {
  if (graph && container.value) {
    graph.changeSize(container.value.clientWidth, container.value.clientHeight)
    graph.fitView(56)
  }
}

onMounted(() => {
  load()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  destroyGraph()
})
</script>

<template>
  <section class="graph-shell">
    <header class="app-topbar graph-topbar">
      <div class="topbar-left">
        <button class="icon-button" @click="emit('back')" title="回到工作台">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        </button>
        <div>
          <div class="topbar-title">融合知识图谱</div>
          <div class="topbar-subtitle">{{ stats.nodes }} 个节点 · {{ stats.edges }} 条关系</div>
        </div>
      </div>
      <div class="graph-toolbar">
        <div class="graph-filter">
          <input v-model="searchQuery" class="input filter-input" type="search" placeholder="搜索节点名/定义/章节…" />
          <select v-model="filterTextbook" class="input filter-select">
            <option value="all">全部教材</option>
            <option v-for="opt in textbookOptions" :key="opt.id" :value="opt.id">{{ opt.title }}</option>
          </select>
        </div>
        <div class="segmented-control mini">
          <button :class="{ active: viewMode === 'force' }" @click="switchMode('force')">漫游图</button>
          <button :class="{ active: viewMode === 'tree' }" @click="switchMode('tree')">知识树</button>
          <button :class="{ active: viewMode === 'canvas' }" @click="switchMode('canvas')">自由画布</button>
        </div>
        <div class="legend">
          <div v-for="(label, key) in { prerequisite: '前置依赖', parallel: '并列', contains: '包含', applies_to: '应用' }" :key="key">
            <span :style="{ background: REL_COLOR[key] }"></span>{{ label }}
          </div>
          <div class="legend-shapes" title="形状表示节点类别">
            <span class="shape circle"></span>概念
            <span class="shape rect"></span>定理
            <span class="shape ellipse"></span>方法
            <span class="shape diamond"></span>现象
          </div>
        </div>
      </div>
    </header>

    <BioDecor
      kind="dna"
      :size="280"
      color="#8cad9d"
      extraClass="absolute right-10 bottom-10 opacity-[0.07] drift-slow pointer-events-none"
    />
    <div class="graph-grid" aria-hidden="true"></div>
    <div ref="container" class="graph-canvas"></div>

    <div v-if="loading" class="graph-overlay">
      <div class="loading-card">载入图谱中…</div>
    </div>

    <div v-if="!loading && stats.nodes === 0" class="graph-overlay">
      <div class="empty-state graph-empty">
        <BioDecor kind="cell" :size="120" color="#9fb8ab" extraClass="mx-auto opacity-50" />
        <p>还没有融合图谱</p>
        <small>请先回工作台运行整合模式</small>
      </div>
    </div>

    <transition name="fade">
      <aside v-if="detail" class="detail-drawer">
        <button class="icon-button close-button" @click="detail = null" title="关闭">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
        <span class="eyebrow">{{ detail.category || 'Concept' }}</span>
        <h2>{{ detail.name }}</h2>
        <p>{{ detail.definition || '暂无定义' }}</p>
        <div class="detail-meta">
          <div><span>章节</span><strong>{{ detail.chapter || '-' }}</strong></div>
          <div><span>页码</span><strong>第 {{ detail.page || '-' }} 页</strong></div>
          <div><span>来源</span><strong>{{ detail.textbook_id || '-' }}</strong></div>
          <div><span>坐标</span><strong>{{ detail.bbox?.length ? detail.bbox.join(', ') : '-' }}</strong></div>
        </div>
      </aside>
    </transition>

    <transition name="fade">
      <div v-if="editNode" class="edit-dialog">
        <div class="edit-card">
          <div class="section-head">
            <span>编辑节点</span>
          </div>
          <input v-model="editDraft.name" class="input" placeholder="节点名称" />
          <textarea v-model="editDraft.definition" class="input textarea" placeholder="节点定义"></textarea>
          <div class="edit-actions">
            <button class="btn-ghost" @click="editNode = null">取消</button>
            <button class="btn-primary" @click="saveNodeEdit">保存</button>
          </div>
        </div>
      </div>
    </transition>
  </section>
</template>
