import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 300000 })
// 长任务专用：图谱抽取 / 融合 / 基准评测 等会调用 LLM 的接口
const httpLong = axios.create({ baseURL: '/api', timeout: 900000 })

export const uploadFiles = (files) => {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return http.post('/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const listTextbooks = () => http.get('/textbooks').then(r => r.data)
export const deleteTextbook = (id) => http.delete(`/textbooks/${id}`).then(r => r.data)

export const extractGraph = (textbook_id) =>
  httpLong.post('/graph/extract', { textbook_id }).then(r => r.data)

export const mergeGraphs = (textbook_ids, similarity_threshold = 0.55) =>
  httpLong.post('/graph/merge', { textbook_ids, similarity_threshold }).then(r => r.data)

export const getMergedGraph = () => http.get('/graph').then(r => r.data)
export const getSingleGraph = (id) => http.get(`/graph/${id}`).then(r => r.data)

export const buildIndex = (textbook_ids) =>
  http.post('/rag/index', { textbook_ids }).then(r => r.data)

export const ragQuery = (question, top_k = 5, search_mode = 'hybrid', history = []) =>
  httpLong.post('/rag/query', { question, top_k, search_mode, history }).then(r => r.data)

export const ragStatus = () => http.get('/rag/status').then(r => r.data)
export const getRagSource = (chunkId) => http.get(`/rag/source/${chunkId}`).then(r => r.data)
export const health = () => http.get('/health').then(r => r.data)

// ---- 统计 / 报告 / 基准 ----
export const getTokenStats = () => http.get('/stats/tokens').then(r => r.data)
export const resetTokenStats = () => http.post('/stats/tokens/reset').then(r => r.data)
export const getGraphStats = () => http.get('/stats/graph').then(r => r.data)
export const runBenchmark = () => httpLong.post('/stats/benchmark').then(r => r.data)
export const reportMarkdown = () => http.get('/report/markdown').then(r => r.data)
// 用于 <a download> 的直链（注意带 baseURL）
export const reportDownloadUrl = '/api/report/download'
export const reportPdfUrl = '/api/report/pdf'

// ---- 图谱：拖拽合并 / 修改 ----
export const modifyGraph = (instruction, node_ids = null) =>
  httpLong.post('/graph/modify', { instruction, node_ids }).then(r => r.data)
export const mergeNodesByDrag = (sourceName, targetName) =>
  modifyGraph(`将节点「${sourceName}」与「${targetName}」合并为同一个节点`, null)
