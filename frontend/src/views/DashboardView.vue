<script setup>
/**
 * 运营仪表盘：Token 消耗 / 图谱规模 / RAG 基准 / 整合报告下载
 * 由 WorkspaceView 顶栏的「仪表盘」按钮唤起；右上角 X 关闭。
 */
import { onMounted, ref } from 'vue'
import {
  getTokenStats,
  resetTokenStats,
  getGraphStats,
  runBenchmark,
  reportMarkdown,
  reportDownloadUrl,
  reportPdfUrl,
} from '../api'

const emit = defineEmits(['close'])

const tokens = ref(null)
const graph = ref(null)
const bench = ref(null)
const benchBusy = ref(false)
const reportText = ref('')
const reportLoading = ref(false)
const tab = ref('tokens')

async function loadAll() {
  try { tokens.value = await getTokenStats() } catch {}
  try { graph.value  = await getGraphStats() } catch {}
}
onMounted(loadAll)

async function onReset() {
  await resetTokenStats()
  await loadAll()
}

async function onBench() {
  benchBusy.value = true
  try { bench.value = await runBenchmark() } finally { benchBusy.value = false }
}

async function onLoadReport() {
  reportLoading.value = true
  try { reportText.value = await reportMarkdown() } finally { reportLoading.value = false }
}

const fmt = (n) => (n ?? 0).toLocaleString()
const pct = (a, total) => total ? ((a / total) * 100).toFixed(1) + '%' : '0%'
</script>

<template>
  <div class="dash-mask" @click.self="emit('close')">
    <section class="dash-panel">
      <header class="dash-head">
        <div>
          <h2>运营仪表盘</h2>
          <p>Token 消耗 · 图谱规模 · RAG 基准 · 整合报告</p>
        </div>
        <button class="icon-button" @click="emit('close')" title="关闭">×</button>
      </header>

      <nav class="dash-tabs">
        <button :class="{active:tab==='tokens'}"  @click="tab='tokens'">Token 统计</button>
        <button :class="{active:tab==='graph'}"   @click="tab='graph'">图谱规模</button>
        <button :class="{active:tab==='bench'}"   @click="tab='bench'">RAG 基准</button>
        <button :class="{active:tab==='report'}"  @click="tab='report'">整合报告</button>
      </nav>

      <!-- Tokens -->
      <div v-if="tab==='tokens'" class="dash-body">
        <div class="dash-actions">
          <button class="btn" @click="loadAll">刷新</button>
          <button class="btn ghost" @click="onReset">清零</button>
        </div>
        <div v-if="tokens" class="token-grid">
          <div class="metric">
            <span>调用总次数</span><strong>{{ fmt(tokens.total?.calls) }}</strong>
          </div>
          <div class="metric">
            <span>Prompt tokens</span><strong>{{ fmt(tokens.total?.prompt) }}</strong>
          </div>
          <div class="metric">
            <span>Completion tokens</span><strong>{{ fmt(tokens.total?.completion) }}</strong>
          </div>
          <div class="metric highlight">
            <span>合计 tokens</span><strong>{{ fmt(tokens.total?.tokens) }}</strong>
          </div>
        </div>
        <table v-if="tokens" class="dash-table">
          <thead><tr><th>角色</th><th>调用</th><th>Prompt</th><th>Completion</th><th>占比</th></tr></thead>
          <tbody>
            <tr v-for="(v, role) in tokens.by_role" :key="role">
              <td>{{ role }}</td><td>{{ fmt(v.calls) }}</td>
              <td>{{ fmt(v.prompt) }}</td><td>{{ fmt(v.completion) }}</td>
              <td>{{ pct((v.prompt+v.completion), tokens.total?.tokens) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="hint">Token 数若未由 LLM 服务返回，将基于「中文字符 + 英文词/4」近似估算。</p>
      </div>

      <!-- Graph -->
      <div v-else-if="tab==='graph'" class="dash-body">
        <div v-if="graph" class="token-grid">
          <div class="metric"><span>已上传教材</span><strong>{{ graph.books_uploaded }}</strong></div>
          <div class="metric"><span>已抽取教材</span><strong>{{ graph.books_extracted }}</strong></div>
          <div class="metric"><span>融合节点</span><strong>{{ graph.merged_nodes }}</strong></div>
          <div class="metric"><span>融合边</span><strong>{{ graph.merged_edges }}</strong></div>
          <div class="metric"><span>RAG 索引块</span><strong>{{ graph.indexed_chunks }}</strong></div>
          <div class="metric"><span>HITL 修改</span><strong>{{ graph.modifications }}</strong></div>
        </div>
        <h4>类别分布</h4>
        <table class="dash-table">
          <tbody>
            <tr v-for="(n, cat) in graph?.by_category" :key="cat"><td>{{ cat }}</td><td>{{ n }}</td></tr>
          </tbody>
        </table>
        <h4>关系分布</h4>
        <table class="dash-table">
          <tbody>
            <tr v-for="(n, rel) in graph?.by_relation" :key="rel"><td>{{ rel }}</td><td>{{ n }}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Bench -->
      <div v-else-if="tab==='bench'" class="dash-body">
        <div class="dash-actions">
          <button class="btn" :disabled="benchBusy" @click="onBench">
            {{ benchBusy ? '运行中…' : '运行基准评测' }}
          </button>
          <span class="hint">使用内置医学问答样本（或 tests/rag_benchmark.json）。</span>
        </div>
        <div v-if="bench" class="token-grid">
          <div class="metric"><span>样本数</span><strong>{{ bench.total_cases }}</strong></div>
          <div class="metric highlight"><span>命中率</span><strong>{{ (bench.hit_rate*100).toFixed(1) }}%</strong></div>
          <div class="metric"><span>耗时</span><strong>{{ bench.elapsed_ms }} ms</strong></div>
        </div>
        <table v-if="bench" class="dash-table">
          <thead><tr><th>问题</th><th>命中</th><th>Top1 块</th><th>Score</th><th>Rerank</th><th>延时</th></tr></thead>
          <tbody>
            <tr v-for="r in bench.rows" :key="r.question">
              <td>{{ r.question }}</td>
              <td>{{ r.match ? '✓' : '✗' }}</td>
              <td>{{ r.top1_chunk }}</td>
              <td>{{ r.top1_score }}</td>
              <td>{{ r.rerank_score }}</td>
              <td>{{ r.latency_ms }} ms</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Report -->
      <div v-else-if="tab==='report'" class="dash-body">
        <div class="dash-actions">
          <button class="btn" @click="onLoadReport">{{ reportLoading ? '加载中…' : '预览' }}</button>
          <a class="btn ghost" :href="reportDownloadUrl">下载 Markdown</a>
          <a class="btn ghost" :href="reportPdfUrl" target="_blank">导出 PDF</a>
        </div>
        <pre v-if="reportText" class="report-md">{{ reportText }}</pre>
        <p v-else class="hint">点击「预览」查看 report/整合报告.md 内容；PDF 需要安装 weasyprint。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dash-mask{position:fixed;inset:0;background:rgba(20,28,24,.55);z-index:80;display:flex;align-items:center;justify-content:center;}
.dash-panel{width:min(960px,95vw);max-height:90vh;background:#fbfdf9;border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden;}
.dash-head{display:flex;justify-content:space-between;align-items:center;padding:18px 24px;border-bottom:1px solid #e3ecde;}
.dash-head h2{margin:0;font-size:20px;color:#34433c;}
.dash-head p{margin:4px 0 0;color:#7a8a82;font-size:13px;}
.icon-button{background:none;border:none;font-size:24px;cursor:pointer;color:#7a8a82;}
.dash-tabs{display:flex;gap:6px;padding:8px 24px;border-bottom:1px solid #e3ecde;background:#f1f5ee;}
.dash-tabs button{background:transparent;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;color:#5a6b62;font-size:13px;}
.dash-tabs button.active{background:#fff;color:#34433c;box-shadow:0 1px 4px rgba(0,0,0,.06);}
.dash-body{padding:18px 24px;overflow:auto;}
.dash-actions{display:flex;gap:8px;align-items:center;margin-bottom:14px;}
.btn{background:#5b8c75;color:#fff;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-block;}
.btn.ghost{background:#fff;color:#5b8c75;border:1px solid #cfdcc7;}
.btn[disabled]{opacity:.5;cursor:not-allowed;}
.token-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:18px;}
.metric{background:#fff;border:1px solid #e3ecde;border-radius:12px;padding:12px 14px;}
.metric span{display:block;color:#7a8a82;font-size:12px;}
.metric strong{display:block;color:#34433c;font-size:22px;margin-top:4px;}
.metric.highlight{background:#eaf5e6;border-color:#bcd8af;}
.dash-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px;}
.dash-table th,.dash-table td{border-bottom:1px solid #ecf2e6;padding:6px 10px;text-align:left;}
.dash-table th{background:#f5f9f1;color:#5a6b62;}
.hint{color:#7a8a82;font-size:12px;margin-top:8px;}
.report-md{background:#fff;border:1px solid #e3ecde;border-radius:10px;padding:14px;font-family:'JetBrains Mono','Consolas',monospace;font-size:12.5px;white-space:pre-wrap;max-height:55vh;overflow:auto;line-height:1.6;}
h4{margin:16px 0 6px;color:#34433c;font-size:14px;}
</style>
