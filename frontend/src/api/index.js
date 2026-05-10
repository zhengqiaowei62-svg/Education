import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 120000 })

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
  http.post('/graph/extract', { textbook_id }).then(r => r.data)

export const mergeGraphs = (textbook_ids, similarity_threshold = 0.55) =>
  http.post('/graph/merge', { textbook_ids, similarity_threshold }).then(r => r.data)

export const getMergedGraph = () => http.get('/graph').then(r => r.data)
export const getSingleGraph = (id) => http.get(`/graph/${id}`).then(r => r.data)

export const buildIndex = (textbook_ids) =>
  http.post('/rag/index', { textbook_ids }).then(r => r.data)

export const ragQuery = (question, top_k = 5, search_mode = 'hybrid', history = []) =>
  http.post('/rag/query', { question, top_k, search_mode, history }).then(r => r.data)

export const ragStatus = () => http.get('/rag/status').then(r => r.data)
export const getRagSource = (chunkId) => http.get(`/rag/source/${chunkId}`).then(r => r.data)
export const health = () => http.get('/health').then(r => r.data)
