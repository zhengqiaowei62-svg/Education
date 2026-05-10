<script setup>
/**
 * 工作区：左侧"教材列表 / 历史会话"，中部"上传 + RAG 对话"，
 * 右侧操作面板（双 Agent 工作流、压缩比统计），顶栏可进入图谱。
 */
import { ref, onMounted, computed } from 'vue'
import {
  uploadFiles, listTextbooks, deleteTextbook,
  buildIndex, ragQuery, ragStatus,
  extractGraph, mergeGraphs,
} from '../api'
import BioDecor from '../components/BioDecor.vue'

const emit = defineEmits(['open-graph', 'home'])

// ---------- 教材列表 ----------
const textbooks = ref([])
const selectedIds = ref(new Set())
const selectedList = computed(() =>
  textbooks.value.filter(t => selectedIds.value.has(t.textbook_id))
)
const refreshList = async () => {
  textbooks.value = await listTextbooks()
  // 默认全选新加入的
  textbooks.value.forEach(t => selectedIds.value.add(t.textbook_id))
}
const toggleSelect = (id) => {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
  selectedIds.value = new Set(selectedIds.value)
}
const onDelete = async (id) => {
  await deleteTextbook(id)
  selectedIds.value.delete(id)
  await refreshList()
}

// ---------- 上传 ----------
const fileInput = ref(null)
const uploading = ref(false)
const dropHover = ref(false)
const uploadStatus = ref([])

const onPick = () => fileInput.value?.click()
const onFiles = async (e) => {
  const files = Array.from(e.target.files || [])
  await doUpload(files)
  e.target.value = ''
}
const onDrop = async (e) => {
  e.preventDefault()
  dropHover.value = false
  await doUpload(Array.from(e.dataTransfer.files || []))
}
const doUpload = async (files) => {
  if (!files.length) return
  uploading.value = true
  try {
    const r = await uploadFiles(files)
    uploadStatus.value = r.files
    await refreshList()
  } finally { uploading.value = false }
}

// ---------- 双 Agent 工作流 ----------
const stage = ref('idle') // idle | extracting | merging | done
const mergeResult = ref(null)
const stageLog = ref([])

const log = (msg) => stageLog.value.unshift({ t: new Date().toLocaleTimeString(), msg })

const runWorkflow = async () => {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  stage.value = 'extracting'
  log(`Agent A · 开始抽取 ${ids.length} 本教材`)
  for (const id of ids) {
    const tb = textbooks.value.find(t => t.textbook_id === id)
    log(`  · 抽取《${tb?.title || id}》…`)
    try { await extractGraph(id) } catch (e) { log(`  ! 抽取失败: ${e}`) }
  }
  stage.value = 'merging'
  log('Agent B · 跨教材对齐与裁决')
  try {
    mergeResult.value = await mergeGraphs(ids, 0.55)
    log(`  · 决策 ${mergeResult.value.decisions?.length || 0} 项 / 节点 ${mergeResult.value.stats?.node_count_before} → ${mergeResult.value.stats?.node_count_after}`)
  } catch (e) {
    log(`  ! 融合失败: ${e}`)
  }
  stage.value = 'done'
}

// ---------- RAG ----------
const indexState = ref({ indexed_textbooks: 0, indexed_chunks: 0, ready: false })
const indexing = ref(false)
const refreshIndex = async () => { indexState.value = await ragStatus() }

const onIndex = async () => {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  indexing.value = true
  try {
    await buildIndex(ids)
    await refreshIndex()
    log(`RAG · 索引就绪 ${indexState.value.indexed_chunks} 个 chunk`)
  } finally { indexing.value = false }
}

const messages = ref([])
const question = ref('')
const asking = ref(false)
const onAsk = async () => {
  const q = question.value.trim()
  if (!q || asking.value) return
  messages.value.push({ role: 'user', text: q })
  question.value = ''
  asking.value = true
  // 占位回复
  const placeholder = { role: 'agent', text: '思考中…', citations: [], pending: true }
  messages.value.push(placeholder)
  try {
    const r = await ragQuery(q, 5)
    Object.assign(placeholder, { text: r.answer, citations: r.citations, source_chunks: r.source_chunks, pending: false })
  } catch (e) {
    placeholder.text = `请求失败：${e.message || e}`
    placeholder.pending = false
  } finally {
    asking.value = false
  }
}

onMounted(async () => {
  try { await refreshList() } catch {}
  try { await refreshIndex() } catch {}
})
</script>

<template>
  <section class="relative h-full w-full flex flex-col bg-grid">
    <!-- 顶栏 -->
    <header class="h-14 px-5 flex items-center justify-between glass border-b z-10">
      <div class="flex items-center gap-3">
        <button class="btn-ghost !p-2" @click="emit('home')" title="回到首页">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>
          </svg>
        </button>
        <div class="font-semibold tracking-wide">KnowLab Workspace</div>
        <span class="tag">{{ textbooks.length }} 本教材 · {{ indexState.indexed_chunks }} chunks</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-ghost text-xs" @click="emit('open-graph')">
          <span class="inline-flex items-center gap-1.5">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M9 6h6M7.5 8.5l3.5 6.5M16.5 8.5l-3.5 6.5"/></svg>
            打开知识图谱
          </span>
        </button>
      </div>
    </header>

    <!-- 主体三栏 -->
    <div class="flex-1 flex overflow-hidden">
      <!-- 左侧：NotebookLM 风格教材/会话 -->
      <aside class="w-[260px] border-r bg-white/60 backdrop-blur-sm flex flex-col">
        <div class="p-4">
          <div class="text-[11px] uppercase tracking-widest text-slate-400 mb-2">来源 Sources</div>
          <button class="btn-primary w-full !py-2 !text-sm flex items-center justify-center gap-1.5"
                  @click="onPick">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
            添加教材
          </button>
          <input ref="fileInput" type="file" multiple class="hidden"
                 accept=".pdf,.md,.txt,.docx" @change="onFiles" />
        </div>
        <div class="divider-soft mx-3"></div>
        <div class="flex-1 overflow-y-auto px-2 py-3 space-y-1">
          <div v-if="!textbooks.length" class="px-3 py-12 text-center text-xs text-slate-400">
            <BioDecor kind="cell" :size="64" color="#94a3b8" extraClass="mx-auto mb-3 opacity-50" />
            还没有教材<br/>点击上方按钮上传
          </div>
          <div v-for="tb in textbooks" :key="tb.textbook_id"
               class="group rounded-lg px-3 py-2 cursor-pointer transition border border-transparent"
               :class="selectedIds.has(tb.textbook_id)
                 ? 'bg-sky-50 border-sky-100'
                 : 'hover:bg-slate-50'"
               @click="toggleSelect(tb.textbook_id)">
            <div class="flex items-start gap-2">
              <input type="checkbox" :checked="selectedIds.has(tb.textbook_id)"
                     class="mt-1 accent-sky-500" @click.stop @change="toggleSelect(tb.textbook_id)" />
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-slate-800 truncate">{{ tb.title }}</div>
                <div class="text-[11px] text-slate-400 mt-0.5">
                  {{ tb.chapters?.length || 0 }} 章 · {{ (tb.total_chars/1000).toFixed(1) }}k 字
                </div>
              </div>
              <button class="opacity-0 group-hover:opacity-100 transition text-slate-300 hover:text-rose-500"
                      @click.stop="onDelete(tb.textbook_id)" title="删除">
                <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <!-- 中部：上传 + 对话 -->
      <main class="flex-1 flex flex-col overflow-hidden">
        <!-- 上传区（无教材时大、有教材时折叠为 dropzone）-->
        <div class="px-8 pt-6 pb-2">
          <div
            class="card relative overflow-hidden transition-all duration-300 cursor-pointer"
            :class="textbooks.length ? 'p-4' : 'p-10'"
            :style="dropHover ? 'border-color: var(--accent); background: var(--accent-soft);' : ''"
            @click="onPick"
            @dragenter.prevent="dropHover = true"
            @dragover.prevent
            @dragleave.prevent="dropHover = false"
            @drop="onDrop"
          >
            <BioDecor v-if="!textbooks.length" kind="dna" :size="120" color="#0ea5e9"
                      extraClass="absolute right-6 top-1/2 -translate-y-1/2 opacity-20 drift-slow" />
            <div class="flex items-center gap-4">
              <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-sky-500 to-teal-500 grid place-items-center text-white">
                <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
                </svg>
              </div>
              <div class="flex-1">
                <div class="text-base font-semibold text-slate-800">
                  {{ textbooks.length ? '继续添加教材' : '上传教材开始整合之旅' }}
                </div>
                <div class="text-xs text-slate-500 mt-0.5">
                  支持 PDF / Markdown / TXT / DOCX · 拖拽或点击均可
                </div>
              </div>
              <div v-if="uploading" class="text-xs text-sky-600">
                <span class="inline-block w-2 h-2 bg-sky-500 rounded-full animate-pulse mr-1.5"></span>解析中…
              </div>
            </div>
          </div>
        </div>

        <!-- 对话区 -->
        <div class="flex-1 px-8 pb-4 overflow-hidden flex flex-col">
          <div class="flex items-center justify-between py-3">
            <div class="text-sm font-semibold text-slate-700">RAG 精准问答</div>
            <div class="flex items-center gap-2">
              <button class="btn-ghost !text-xs" :disabled="indexing || !selectedIds.size" @click="onIndex">
                {{ indexing ? '建索引中…' : '建立索引' }}
              </button>
              <span class="text-[11px] text-slate-400">
                索引: {{ indexState.indexed_chunks }} chunks · {{ indexState.ready ? '就绪' : '未就绪' }}
              </span>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto rounded-2xl border bg-white/70 backdrop-blur-sm p-5 space-y-4">
            <div v-if="!messages.length" class="h-full grid place-items-center text-center text-slate-400">
              <div>
                <BioDecor kind="mol" :size="80" color="#0ea5e9" extraClass="mx-auto opacity-30 drift" />
                <div class="text-sm mt-3">先「建立索引」，再向 KnowLab 提问</div>
                <div class="text-[11px] mt-1">每个回答都会附带教材 / 章节 / 页码引用</div>
              </div>
            </div>

            <div v-for="(m, i) in messages" :key="i"
                 class="flex" :class="m.role === 'user' ? 'justify-end' : 'justify-start'">
              <div class="max-w-[78%] px-4 py-3 text-sm leading-relaxed shadow-sm"
                   :class="m.role === 'user' ? 'bubble-user' : 'bubble-agent'">
                <div v-if="m.pending" class="flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"></span>
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" style="animation-delay:.2s"></span>
                  <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" style="animation-delay:.4s"></span>
                </div>
                <div v-else class="whitespace-pre-wrap">{{ m.text }}</div>
                <ul v-if="m.citations?.length" class="mt-3 space-y-1">
                  <li v-for="(c, j) in m.citations" :key="j"
                      class="text-[11px] px-2 py-1 rounded bg-slate-50 border text-slate-600 flex justify-between">
                    <span class="truncate">[{{ j+1 }}] 《{{ c.textbook }}》· {{ c.chapter }} · 第 {{ c.page }} 页</span>
                    <span class="text-slate-400 ml-2">{{ (c.relevance_score*100).toFixed(0) }}%</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="mt-3 card p-2 flex items-center gap-2">
            <input v-model="question" class="input !border-0 !shadow-none focus:!shadow-none"
                   placeholder="例如：动作电位的产生机制是什么？"
                   @keyup.enter="onAsk" :disabled="asking" />
            <button class="btn-primary !py-2 !px-4 text-sm" :disabled="asking" @click="onAsk">
              提问
            </button>
          </div>
        </div>
      </main>

      <!-- 右侧：双 Agent 工作流 -->
      <aside class="w-[320px] border-l bg-white/60 backdrop-blur-sm flex flex-col">
        <div class="p-5">
          <div class="text-[11px] uppercase tracking-widest text-slate-400 mb-3">Workflow</div>

          <div class="space-y-3">
            <!-- Agent A -->
            <div class="card p-4">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-xs text-slate-400">Agent A</div>
                  <div class="text-sm font-semibold">Extractor · 抽取者</div>
                </div>
                <span class="tag">{{ stage === 'extracting' ? '运行中' : 'idle' }}</span>
              </div>
              <div class="mt-2 text-[11px] text-slate-500 leading-relaxed">
                按章节调用 LLM，输出严格 JSON 节点 + 关系
              </div>
            </div>

            <!-- 箭头 -->
            <div class="flex justify-center text-slate-300">
              <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 5v14M5 12l7 7 7-7"/>
              </svg>
            </div>

            <!-- Agent B -->
            <div class="card p-4">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-xs text-slate-400">Agent B</div>
                  <div class="text-sm font-semibold">Aligner · 裁决者</div>
                </div>
                <span class="tag">{{ stage === 'merging' ? '运行中' : 'idle' }}</span>
              </div>
              <div class="mt-2 text-[11px] text-slate-500 leading-relaxed">
                Embedding 初筛 → LLM 裁决 merge / keep / remove
              </div>
            </div>
          </div>

          <button class="btn-primary w-full mt-4 !py-2.5 !text-sm"
                  :disabled="!selectedIds.size || stage === 'extracting' || stage === 'merging'"
                  @click="runWorkflow">
            <span v-if="stage === 'extracting' || stage === 'merging'">运行中…</span>
            <span v-else>▶ 运行双 Agent 工作流</span>
          </button>

          <!-- 压缩比 -->
          <div v-if="mergeResult" class="card p-4 mt-3">
            <div class="text-xs text-slate-400 mb-2">整合统计</div>
            <div class="text-xs space-y-1.5 text-slate-600">
              <div class="flex justify-between">
                <span>节点 数</span>
                <span class="font-medium text-slate-800">
                  {{ mergeResult.stats.node_count_before }} → {{ mergeResult.stats.node_count_after }}
                </span>
              </div>
              <div class="flex justify-between">
                <span>压缩比</span>
                <span class="font-medium" :class="mergeResult.stats.compression_ratio <= 0.3 ? 'text-emerald-600' : 'text-amber-600'">
                  {{ (mergeResult.stats.compression_ratio * 100).toFixed(1) }}%
                </span>
              </div>
              <div class="flex justify-between">
                <span>决策数</span>
                <span class="font-medium text-slate-800">{{ mergeResult.decisions?.length || 0 }}</span>
              </div>
            </div>
            <button class="btn-ghost w-full !text-xs mt-3" @click="emit('open-graph')">查看融合图谱 →</button>
          </div>

          <!-- 日志 -->
          <div v-if="stageLog.length" class="mt-4">
            <div class="text-[11px] uppercase tracking-widest text-slate-400 mb-2">日志</div>
            <div class="text-[11px] text-slate-500 space-y-1 max-h-40 overflow-y-auto">
              <div v-for="(l, i) in stageLog" :key="i" class="flex gap-2">
                <span class="text-slate-300">{{ l.t }}</span>
                <span class="flex-1 truncate">{{ l.msg }}</span>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>
