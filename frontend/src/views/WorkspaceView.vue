<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import G6 from '@antv/g6'
import {
  buildIndex,
  deleteTextbook,
  extractGraph,
  getMergedGraph,
  getRagSource,
  getSingleGraph,
  listTextbooks,
  mergeGraphs,
  ragQuery,
  ragStatus,
  uploadFiles,
} from '../api'
import BioDecor from '../components/BioDecor.vue'
import DashboardView from './DashboardView.vue'

const emit = defineEmits(['open-graph', 'home'])
const showDashboard = ref(false)

const fileInput = ref(null)
const graphContainer = ref(null)
let graph = null

const textbooks = ref([])
const selectedIds = ref(new Set())
const expandedIds = ref(new Set())
const graphScope = ref({ mode: 'merged', textbookId: null, title: '' }) // mode: 'merged' | 'single'
const graphLoading = ref(false)
const selectedList = computed(() => textbooks.value.filter(t => selectedIds.value.has(t.textbook_id)))
const selectedSummary = computed(() => selectedList.value.length ? `${selectedList.value.length} 本已选` : '未选择教材')

const uploading = ref(false)
const dropHover = ref(false)
const uploadStatus = ref([])
const indexState = ref({ indexed_textbooks: 0, indexed_chunks: 0, ready: false })
const indexing = ref(false)
const stage = ref('idle')
const stageLog = ref([])
const mergeResult = ref(null)

const activeTool = ref('integrate')
const searchMode = ref('hybrid')
const thinkingMode = ref('deep')
const integrateMode = ref('graph')
const messages = ref([])
const question = ref('')
const asking = ref(false)
const sourcePreview = ref(null)
const loadingSource = ref(false)
const graphStats = ref({ nodes: 0, edges: 0 })

const reportDraft = computed(() => {
  const books = textbooks.value.length
  const chunks = indexState.value.indexed_chunks
  const nodes = graphStats.value.nodes
  const edges = graphStats.value.edges
  return `当前已接入 ${books} 本教材，生成 ${chunks} 个文本向量块，知识图谱包含 ${nodes} 个节点与 ${edges} 条关系。`
})

const tabs = [
  { id: 'integrate', label: '整合操作' },
  { id: 'rag', label: 'RAG 问答' },
  { id: 'chat', label: '对话' },
  { id: 'report', label: '报告生成' },
]

const sessions = ref([
  { id: 'default', title: '新教材问答', count: 0, active: true },
  { id: 'review', title: '考前机制梳理', count: 6, active: false },
  { id: 'terms', title: '高频概念复盘', count: 11, active: false },
])

const recentQuestions = computed(() =>
  messages.value.filter(m => m.role === 'user').slice(-6).reverse()
)

const log = (msg) => stageLog.value.unshift({ t: new Date().toLocaleTimeString(), msg })

const refreshList = async () => {
  textbooks.value = await listTextbooks()
  textbooks.value.forEach(t => selectedIds.value.add(t.textbook_id))
  selectedIds.value = new Set(selectedIds.value)
}

const refreshIndex = async () => {
  indexState.value = await ragStatus()
}

const toggleSelect = (id) => {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
  selectedIds.value = new Set(selectedIds.value)
}

const toggleExpand = (id) => {
  if (expandedIds.value.has(id)) expandedIds.value.delete(id)
  else expandedIds.value.add(id)
  expandedIds.value = new Set(expandedIds.value)
}

/** 选择/构建并展示某一本教材的知识图谱 */
const showSingleGraph = async (tb) => {
  if (!tb || graphLoading.value) return
  graphLoading.value = true
  graphScope.value = { mode: 'single', textbookId: tb.textbook_id, title: tb.title }
  log(`查看《${tb.title}》单本图谱…`)
  try {
    let g = await getSingleGraph(tb.textbook_id)
    if (!g || !(g.nodes || []).length) {
      log(`图谱为空，正在为《${tb.title}》调用 Agent A 抽取…`)
      const r = await extractGraph(tb.textbook_id)
      g = r.graph || r
    }
    const data = makeGraphData(g)
    graphStats.value = { nodes: data.nodes.length, edges: data.edges.length }
    await nextTick()
    if (data.nodes.length) renderGraph(data)
    else { graph?.destroy(); graph = null }
    log(`《${tb.title}》图谱：${data.nodes.length} 节点 / ${data.edges.length} 关系`)
  } catch (error) {
    log(`单本图谱失败：${error?.message || error}`)
  } finally {
    graphLoading.value = false
  }
}

const showMergedGraph = async () => {
  graphScope.value = { mode: 'merged', textbookId: null, title: '' }
  await loadGraph()
}

const onDelete = async (id) => {
  await deleteTextbook(id)
  selectedIds.value.delete(id)
  await refreshList()
}

const onPick = () => fileInput.value?.click()

const onFiles = async (event) => {
  await doUpload(Array.from(event.target.files || []))
  event.target.value = ''
}

const onDrop = async (event) => {
  event.preventDefault()
  dropHover.value = false
  await doUpload(Array.from(event.dataTransfer.files || []))
}

const doUpload = async (files) => {
  if (!files.length) return
  uploading.value = true
  try {
    const result = await uploadFiles(files)
    uploadStatus.value = result.files || []
    await refreshList()
    log(`完成上传解析：${files.length} 个文件`)
  } finally {
    uploading.value = false
  }
}

const onIndex = async () => {
  const ids = [...selectedIds.value]
  if (!ids.length || indexing.value) return
  indexing.value = true
  try {
    const result = await buildIndex(ids)
    await refreshIndex()
    log(`文本向量块整理完成：${result.indexed_chunks} chunks`)
  } finally {
    indexing.value = false
  }
}

const runGraphBuild = async () => {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  stage.value = 'extracting'
  log(`开始构建 ${ids.length} 本教材的知识图谱`)
  for (const id of ids) {
    const tb = textbooks.value.find(t => t.textbook_id === id)
    try {
      log(`抽取图谱区块：《${tb?.title || id}》`)
      await extractGraph(id)
    } catch (error) {
      log(`抽取失败：${error?.message || error}`)
    }
  }
  stage.value = 'merging'
  try {
    mergeResult.value = await mergeGraphs(ids, 0.55)
    log(`图谱融合完成：${mergeResult.value.decisions?.length || 0} 项裁决`)
    await loadGraph()
  } catch (error) {
    log(`融合失败：${error?.message || error}`)
  }
  stage.value = 'done'
}

const runIntegrate = async () => {
  if (integrateMode.value === 'rag') await onIndex()
  else await runGraphBuild()
}

const onAsk = async () => {
  const text = question.value.trim()
  if (!text || asking.value) return
  messages.value.push({ role: 'user', text })
  sessions.value[0].count += 1
  question.value = ''
  asking.value = true
  const placeholder = { role: 'agent', text: '正在检索教材证据…', citations: [], pending: true }
  messages.value.push(placeholder)
  try {
    const topK = thinkingMode.value === 'deep' ? 8 : 5
    // 携带最近 8 条对话作为多轮上下文（不含本次占位答复）
    const history = messages.value
      .filter(m => !m.pending && (m.text || '').trim())
      .slice(-8)
      .map(m => ({ role: m.role === 'agent' ? 'assistant' : 'user', content: m.text }))
    const result = await ragQuery(text, topK, searchMode.value, history)
    Object.assign(placeholder, {
      text: result.answer,
      citations: result.citations || [],
      source_chunks: result.source_chunks || [],
      pending: false,
    })
  } catch (error) {
    placeholder.text = `请求失败：${error?.message || error}`
    placeholder.pending = false
  } finally {
    asking.value = false
  }
}

const openCitation = async (citation) => {
  sourcePreview.value = citation
  if (!citation?.chunk_id) return
  loadingSource.value = true
  try {
    const source = await getRagSource(citation.chunk_id)
    if (source?.found) sourcePreview.value = { ...citation, ...source }
  } finally {
    loadingSource.value = false
  }
}

const makeGraphData = (merged) => ({
  nodes: (merged.nodes || []).map(node => ({
    id: node.id,
    label: node.name,
    size: node.category === '图像区块' ? 24 : 30 + Math.min(node.frequency || 1, 5) * 3,
    style: {
      fill: node.category === '图像区块' ? '#f8faf8' : '#fff',
      stroke: node.category === '图像区块' ? '#a49678' : '#6f9584',
      lineWidth: 1.5,
      shadowColor: 'rgba(66, 91, 80, .12)',
      shadowBlur: 12,
    },
    raw: node,
  })),
  edges: (merged.edges || []).map(edge => ({
    source: edge.source,
    target: edge.target,
    label: edge.relation_type,
    style: { stroke: '#c9d8d0', endArrow: true },
  })),
})

const renderGraph = (data) => {
  if (!graphContainer.value) return
  graph?.destroy()
  graph = new G6.Graph({
    container: graphContainer.value,
    width: graphContainer.value.clientWidth,
    height: graphContainer.value.clientHeight,
    fitView: true,
    fitViewPadding: 42,
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    layout: {
      type: 'force',
      preventOverlap: true,
      linkDistance: 116,
      nodeStrength: -68,
    },
    defaultNode: {
      type: 'circle',
      labelCfg: { position: 'bottom', offset: 8, style: { fontSize: 11, fill: '#34433c' } },
    },
    defaultEdge: {
      type: 'line',
      labelCfg: { autoRotate: true, style: { fontSize: 9, fill: '#7f8c86' } },
    },
  })
  graph.data(data)
  graph.render()
  graph.fitView(42)
}

const loadGraph = async () => {
  try {
    const merged = await getMergedGraph()
    const data = makeGraphData(merged)
    graphStats.value = { nodes: data.nodes.length, edges: data.edges.length }
    await nextTick()
    if (data.nodes.length) renderGraph(data)
    else {
      graph?.destroy()
      graph = null
    }
  } catch {
    graphStats.value = { nodes: 0, edges: 0 }
  }
}

const resizeGraph = () => {
  if (graph && graphContainer.value) {
    graph.changeSize(graphContainer.value.clientWidth, graphContainer.value.clientHeight)
    graph.fitView(42)
  }
}

onMounted(async () => {
  window.addEventListener('resize', resizeGraph)
  try { await refreshList() } catch {}
  try { await refreshIndex() } catch {}
  await loadGraph()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeGraph)
  graph?.destroy()
})
</script>

<template>
  <section class="workspace-shell">
    <header class="app-topbar">
      <div class="topbar-left">
        <button class="icon-button" @click="emit('home')" title="回到初始界面">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1v-10.5Z" />
          </svg>
        </button>
        <div>
          <div class="topbar-title">KnowLab Workspace</div>
          <div class="topbar-subtitle">{{ selectedSummary }} · {{ indexState.indexed_chunks }} chunks · {{ graphStats.nodes }} nodes</div>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="btn-ghost btn-compact" :disabled="indexing || !selectedIds.size" @click="onIndex">
          {{ indexing ? '索引中…' : '建立索引' }}
        </button>
        <button class="btn-primary btn-compact" @click="showDashboard = true" style="margin-right:8px;">仪表盘</button>
        <button class="btn-primary btn-compact" @click="emit('open-graph')">全屏图谱</button>
      </div>
    </header>

    <div class="workspace-dashboard">
      <aside class="textbook-panel panel-surface">
        <div class="section-head">
          <span>教材管理</span>
          <span>{{ textbooks.length }}</span>
        </div>

        <section
          class="manager-upload"
          :class="{ hover: dropHover }"
          @click="onPick"
          @dragenter.prevent="dropHover = true"
          @dragover.prevent
          @dragleave.prevent="dropHover = false"
          @drop="onDrop"
        >
          <div class="upload-icon">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
            </svg>
          </div>
          <strong>{{ uploading ? '解析中…' : '上传教材' }}</strong>
          <span>PDF / MD / TXT / DOCX</span>
        </section>
        <input ref="fileInput" type="file" multiple class="hidden" accept=".pdf,.md,.txt,.docx" @change="onFiles" />

        <div class="status-strip">
          <div><strong>{{ indexState.indexed_chunks }}</strong><span>向量块</span></div>
          <div><strong>{{ graphStats.nodes }}</strong><span>图谱节点</span></div>
        </div>

        <div class="source-list manager-list">
          <div v-if="!textbooks.length" class="empty-state compact">
            <BioDecor kind="cell" :size="70" color="#9fb8ab" extraClass="mx-auto opacity-50" />
            <p>还没有教材</p>
            <small>上传后会在这里显示解析状态</small>
          </div>
          <article
            v-for="tb in textbooks"
            :key="tb.textbook_id"
            class="source-item"
            :class="{ selected: selectedIds.has(tb.textbook_id), expanded: expandedIds.has(tb.textbook_id) }"
          >
            <div class="source-row" @click="toggleSelect(tb.textbook_id)">
              <input type="checkbox" :checked="selectedIds.has(tb.textbook_id)" @click.stop @change="toggleSelect(tb.textbook_id)" />
              <button
                class="chevron-btn"
                :class="{ open: expandedIds.has(tb.textbook_id) }"
                :title="expandedIds.has(tb.textbook_id) ? '收起章节' : '展开章节'"
                @click.stop="toggleExpand(tb.textbook_id)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
              </button>
              <div class="source-main">
                <strong>{{ tb.title }}</strong>
                <span>{{ tb.chapters?.length || 0 }} 章 · {{ (tb.total_chars / 1000).toFixed(1) }}k 字 · {{ tb.total_pages || 0 }} 页</span>
              </div>
              <button class="icon-button btn-quiet btn-compact" title="查看本书知识图谱" @click.stop="showSingleGraph(tb)">
                <svg viewBox="0 0 24 24" aria-hidden="true" width="14" height="14">
                  <circle cx="5" cy="6" r="2.2" /><circle cx="19" cy="6" r="2.2" />
                  <circle cx="12" cy="18" r="2.2" />
                  <path d="M5 6h14M5 6l7 12M19 6l-7 12" />
                </svg>
              </button>
              <button title="删除教材" @click.stop="onDelete(tb.textbook_id)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m3 0-.8 14H5.8L5 6" /></svg>
              </button>
            </div>
            <ul v-if="expandedIds.has(tb.textbook_id) && tb.chapters?.length" class="chapter-list">
              <li v-for="(ch, idx) in tb.chapters" :key="ch.chapter_id || idx" class="chapter-item">
                <span class="chapter-index">{{ String(idx + 1).padStart(2, '0') }}</span>
                <div class="chapter-meta">
                  <strong>{{ ch.title }}</strong>
                  <span>第 {{ ch.page_start }}–{{ ch.page_end }} 页 · {{ ch.char_count }} 字</span>
                </div>
              </li>
            </ul>
            <p v-else-if="expandedIds.has(tb.textbook_id)" class="chapter-empty">未解析出章节。</p>
          </article>
        </div>
      </aside>

      <main class="graph-main panel-surface">
        <div class="graph-main-head">
          <div>
            <span class="eyebrow">Knowledge Graph</span>
            <h2>
              {{ graphScope.mode === 'single' ? `单本图谱·${graphScope.title}` : '知识图谱可视化区' }}
            </h2>
          </div>
          <div class="graph-main-actions">
            <div class="segmented-control mini">
              <button :class="{ active: graphScope.mode === 'merged' }" @click="showMergedGraph">融合</button>
              <button :class="{ active: graphScope.mode === 'single' }" :disabled="graphScope.mode !== 'single'">单本</button>
            </div>
            <button class="btn-ghost btn-compact" :disabled="graphLoading" @click="graphScope.mode === 'single' && graphScope.textbookId ? showSingleGraph(textbooks.find(t => t.textbook_id === graphScope.textbookId)) : loadGraph()">刷新</button>
            <button class="btn-primary btn-compact" @click="emit('open-graph')">多视图</button>
          </div>
        </div>
        <div class="graph-stage">
          <div ref="graphContainer" class="workspace-graph-canvas"></div>
          <div v-if="!graphStats.nodes" class="workspace-graph-empty">
            <BioDecor kind="mol" :size="110" color="#8cad9d" extraClass="mx-auto opacity-35 drift" />
            <p>中间区域用于展示融合后的知识图谱</p>
            <small>在右侧“整合操作”中选择知识图谱并开始构建</small>
          </div>
        </div>
      </main>

      <aside class="tool-panel panel-surface">
        <div class="tool-tabs">
          <button v-for="tab in tabs" :key="tab.id" :class="{ active: activeTool === tab.id }" @click="activeTool = tab.id">
            {{ tab.label }}
          </button>
        </div>

        <section v-if="activeTool === 'integrate'" class="tool-body">
          <section class="setting-card">
            <div class="section-head">
              <span>思考模式</span>
              <span>{{ thinkingMode === 'deep' ? '推理整合' : '快速问答' }}</span>
            </div>
            <div class="segmented-control">
              <button :class="{ active: thinkingMode === 'fast' }" @click="thinkingMode = 'fast'">快速</button>
              <button :class="{ active: thinkingMode === 'deep' }" @click="thinkingMode = 'deep'">深入</button>
            </div>
          </section>
          <section class="setting-card">
            <div class="section-head">
              <span>整合模式</span>
              <span>{{ stage }}</span>
            </div>
            <div class="segmented-control">
              <button :class="{ active: integrateMode === 'rag' }" @click="integrateMode = 'rag'">文本向量</button>
              <button :class="{ active: integrateMode === 'graph' }" @click="integrateMode = 'graph'">知识图谱</button>
            </div>
            <button class="btn-primary workflow-button" :disabled="!selectedIds.size || indexing || stage === 'extracting' || stage === 'merging'" @click="runIntegrate">
              {{ integrateMode === 'rag' ? (indexing ? '整理中…' : '整理文本向量块') : (stage === 'extracting' || stage === 'merging' ? '构建中…' : '构建知识图谱') }}
            </button>
          </section>
          <div v-if="mergeResult" class="metric-card">
            <div class="metric-row"><span>节点数</span><strong>{{ mergeResult.stats.node_count_before }} → {{ mergeResult.stats.node_count_after }}</strong></div>
            <div class="metric-row"><span>压缩比</span><strong>{{ (mergeResult.stats.compression_ratio * 100).toFixed(1) }}%</strong></div>
          </div>
          <div class="log-panel">
            <div class="section-head"><span>运行日志</span></div>
            <div v-if="!stageLog.length" class="empty-log">日志会在操作后显示</div>
            <div v-for="(item, index) in stageLog" :key="index" class="log-row">
              <span>{{ item.t }}</span><p>{{ item.msg }}</p>
            </div>
          </div>
        </section>

        <section v-else-if="activeTool === 'rag'" class="tool-body rag-tool">
          <div class="segmented-control mini">
            <button :class="{ active: searchMode === 'term' }" @click="searchMode = 'term'">词块</button>
            <button :class="{ active: searchMode === 'region' }" @click="searchMode = 'region'">区域</button>
            <button :class="{ active: searchMode === 'hybrid' }" @click="searchMode = 'hybrid'">混合</button>
          </div>
          <div class="side-message-list">
            <div v-if="!messages.length" class="empty-state compact">
              <p>向教材提问</p>
              <small>引用可点击定位到原文块</small>
            </div>
            <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
              <div class="message-bubble">
                <div v-if="message.pending" class="typing"><span></span><span></span><span></span></div>
                <div v-else class="whitespace-pre-wrap">{{ message.text }}</div>
                <div v-if="message.citations?.length" class="citation-list">
                  <button v-for="(citation, citeIndex) in message.citations" :key="citeIndex" class="citation-item" @click="openCitation(citation)" :title="'点击查看原文区块：' + (citation.quote || citation.chapter)">
                    <span class="cite-head">[{{ citeIndex + 1 }}] {{ citation.textbook }}</span>
                    <span class="cite-meta">{{ citation.chapter || '未分章' }} · 第 {{ citation.page }}{{ citation.page_end && citation.page_end !== citation.page ? '–' + citation.page_end : '' }} 页</span>
                    <span class="cite-foot">
                      <em class="cite-mode">{{ citation.retrieval_mode }}</em>
                      <em class="cite-score">相关度 {{ (citation.relevance_score || 0).toFixed(2) }}</em>
                      <em class="cite-link">查看原文 →</em>
                    </span>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="ask-box side-ask">
            <input v-model="question" class="input" placeholder="例如：动作电位机制" :disabled="asking" @keyup.enter="onAsk" />
            <button class="icon-button send-button" :disabled="asking || !question.trim()" @click="onAsk" title="发送">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" /></svg>
            </button>
          </div>
        </section>

        <section v-else-if="activeTool === 'chat'" class="tool-body">
          <div class="section-head"><span>对话记录</span><span>{{ sessions.length }}</span></div>
          <button v-for="session in sessions" :key="session.id" class="history-item" :class="{ selected: session.active }">
            <strong>{{ session.title }}</strong><span>{{ session.count }} 条记录</span>
          </button>
          <div class="section-head recent"><span>最近问题</span></div>
          <button v-for="(item, index) in recentQuestions" :key="index" class="question-chip">{{ item.text }}</button>
          <div v-if="!recentQuestions.length" class="empty-state compact"><p>暂无对话</p><small>在 RAG 问答里开始</small></div>
        </section>

        <section v-else class="tool-body">
          <div class="section-head"><span>学习报告</span><span>Draft</span></div>
          <div class="report-card">
            <p>{{ reportDraft }}</p>
            <button class="btn-primary btn-full">生成报告</button>
          </div>
        </section>
      </aside>
    </div>

    <transition name="fade">
      <aside v-if="sourcePreview" class="source-drawer">
        <button class="icon-button close-button" @click="sourcePreview = null" title="关闭">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
        <span class="eyebrow">Source Block</span>
        <h2>原文定位</h2>
        <div class="source-meta">
          <div><span>教材</span><strong>{{ sourcePreview.textbook }}</strong></div>
          <div><span>章节</span><strong>{{ sourcePreview.chapter }}</strong></div>
          <div><span>页码</span><strong>第 {{ sourcePreview.page }} 页</strong></div>
          <div><span>坐标</span><strong>{{ sourcePreview.bbox?.length ? sourcePreview.bbox.join(', ') : '文本页级定位' }}</strong></div>
        </div>
        <p v-if="loadingSource" class="source-loading">载入原文块…</p>
        <blockquote>{{ sourcePreview.text || sourcePreview.quote }}</blockquote>
      </aside>
    </transition>
    <DashboardView v-if="showDashboard" @close="showDashboard = false" />
  </section>
</template>
