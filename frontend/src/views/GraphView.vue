<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import G6 from '@antv/g6'
import { getMergedGraph } from '../api'
import BioDecor from '../components/BioDecor.vue'

const emit = defineEmits(['back'])
const container = ref(null)
let graph = null
const detail = ref(null)
const stats = ref({ nodes: 0, edges: 0 })
const loading = ref(true)

const REL_COLOR = {
  prerequisite: '#0ea5e9',
  parallel:     '#94a3b8',
  contains:     '#14b8a6',
  applies_to:   '#a855f7',
}

function nodeStyle(n) {
  // 节点大小由 frequency 决定（融合后越多教材出现越大）
  const r = 18 + Math.min(n.frequency || 1, 6) * 4
  return { size: r, fill: '#ffffff', stroke: '#0ea5e9', lineWidth: 1.5 }
}

async function load() {
  loading.value = true
  try {
    const g = await getMergedGraph()
    const data = {
      nodes: (g.nodes || []).map(n => ({
        id: n.id,
        label: n.name,
        ...nodeStyle(n),
        raw: n,
      })),
      edges: (g.edges || []).map(e => ({
        source: e.source, target: e.target,
        label: e.relation_type,
        style: { stroke: REL_COLOR[e.relation_type] || '#cbd5e1', lineDash: e.relation_type === 'parallel' ? [4,4] : null, endArrow: true },
        raw: e,
      })),
    }
    stats.value = { nodes: data.nodes.length, edges: data.edges.length }
    if (graph) graph.changeData(data)
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

onMounted(() => {
  graph = new G6.Graph({
    container: container.value,
    width: container.value.clientWidth,
    height: container.value.clientHeight,
    fitView: true,
    fitViewPadding: 40,
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    layout: {
      type: 'force',
      preventOverlap: true,
      linkDistance: 110,
      nodeStrength: -60,
    },
    defaultNode: {
      type: 'circle',
      size: 28,
      style: { fill: '#fff', stroke: '#0ea5e9', lineWidth: 1.5 },
      labelCfg: { position: 'bottom', offset: 6, style: { fontSize: 11, fill: '#334155' } },
    },
    defaultEdge: {
      type: 'line',
      style: { stroke: '#cbd5e1', endArrow: { path: G6.Arrow.triangle(6, 8), fill: '#cbd5e1' } },
      labelCfg: { autoRotate: true, style: { fontSize: 9, fill: '#94a3b8', background: { fill: '#fff', padding: [2,4,2,4], radius: 2 } } },
    },
  })

  graph.on('node:click', evt => {
    detail.value = evt.item.getModel().raw
  })
  graph.on('canvas:click', () => { detail.value = null })

  load()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  graph && graph.destroy()
})
function resize() {
  if (graph && container.value) graph.changeSize(container.value.clientWidth, container.value.clientHeight)
}
</script>

<template>
  <section class="relative h-full w-full bg-white">
    <!-- 顶栏 -->
    <header class="absolute top-0 left-0 right-0 h-14 px-5 flex items-center justify-between glass border-b z-20">
      <div class="flex items-center gap-3">
        <button class="btn-ghost !p-2" @click="emit('back')">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        </button>
        <div class="font-semibold tracking-wide">融合知识图谱</div>
        <span class="tag">{{ stats.nodes }} 节点 · {{ stats.edges }} 关系</span>
      </div>
      <div class="flex items-center gap-3 text-[11px]">
        <div v-for="(c, k) in { prerequisite:'前置依赖', parallel:'并列', contains:'包含', applies_to:'应用' }" :key="k"
             class="flex items-center gap-1.5">
          <span class="w-2.5 h-0.5 rounded" :style="{ background: { prerequisite:'#0ea5e9', parallel:'#94a3b8', contains:'#14b8a6', applies_to:'#a855f7' }[k] }"></span>
          <span class="text-slate-500">{{ c }}</span>
        </div>
      </div>
    </header>

    <!-- 装饰 -->
    <BioDecor kind="dna" :size="240" color="#0ea5e9"
              extraClass="absolute right-8 bottom-8 opacity-[0.06] drift-slow pointer-events-none" />

    <!-- 画布 -->
    <div ref="container" class="absolute inset-0 pt-14"></div>

    <!-- 加载态 -->
    <div v-if="loading"
         class="absolute inset-0 grid place-items-center bg-white/60 backdrop-blur-sm pointer-events-none">
      <div class="text-sm text-slate-500">载入图谱中…</div>
    </div>
    <div v-if="!loading && stats.nodes === 0"
         class="absolute inset-0 grid place-items-center pointer-events-none">
      <div class="text-center text-slate-400">
        <BioDecor kind="cell" :size="120" color="#94a3b8" extraClass="mx-auto opacity-50" />
        <div class="text-sm mt-3">还没有融合图谱</div>
        <div class="text-[11px]">请先回工作台运行双 Agent 工作流</div>
      </div>
    </div>

    <!-- 节点详情 -->
    <transition name="fade">
      <div v-if="detail"
           class="absolute right-5 top-20 w-80 card p-5 z-30 max-h-[70vh] overflow-y-auto">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-[11px] text-slate-400">{{ detail.category }}</div>
            <div class="text-base font-semibold text-slate-800 mt-0.5">{{ detail.name }}</div>
          </div>
          <button class="text-slate-300 hover:text-slate-600" @click="detail = null">✕</button>
        </div>
        <div class="mt-3 text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
          {{ detail.definition || '（暂无定义）' }}
        </div>
        <div class="divider-soft my-4"></div>
        <div class="text-[11px] text-slate-500 space-y-1">
          <div>章节：{{ detail.chapter }}</div>
          <div>页码：第 {{ detail.page }} 页</div>
          <div>来源：{{ detail.textbook_id }}</div>
          <div>跨教材频次：{{ detail.frequency }}</div>
        </div>
      </div>
    </transition>
  </section>
</template>
