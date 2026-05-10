# 多教材知识图谱整合系统（Multi-Textbook KG Integrator）

> 面向**医学/生物医学教学场景**的「多教材 → 统一知识图谱 + 可追溯 RAG 问答」系统。  
> 提供从原始 PDF 到「知识图谱 · 整合报告 · 智能问答 · 数据驱动评测」的全流程闭环。

—

## 1. 项目概览

本系统解决的问题：**当多本教材（例如《生理学》《组织胚胎学》等）描述同一医学概念时，如何自动识别、对齐、合并、并以可追溯方式呈现？**

核心能力：
- 📚 **多模态解析**：PDF → 文本 + 图像 + 公式 + 版面区块（MinerU2.5-Pro）。
- 🧠 **双 Agent 知识抽取**：Extractor（生成知识图谱）+ Judge（合并 / 修订决策）。
- 🌐 **多视图知识图谱**：力导向图 / 知识树 / 自由画布 / **矩阵热力图**，支持 Shift+拖拽合并、双击编辑。
- 🔍 **混合检索 RAG**：BM25（词项）+ 向量（BGE-small-zh）+ 区域感知（章/页/坐标）+ RRF 融合 + **MMR Rerank**。
- 💬 **可追溯问答**：每条回答携带「教材 / 章节 / 页码 / 区块坐标 / 原文摘录」。
- 🛠️ **HITL 自然语言图谱编辑**：「把 X 拆成两个节点」「将 A 与 B 合并」直接执行并写入审计日志。
- 📊 **运营仪表盘**：Token 消耗 / 图谱规模 / **RAG 基准评测** / 整合报告 PDF 导出。
- 🐳 **一键部署**：Docker Compose；亦可本地用 Ollama 跑开源模型。

—

## 2. 系统架构（一图）

```
┌────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Vue 3     │ ──▶ │  FastAPI    │ ──▶ │  Pipeline    │ ──▶ │  LLM Client  │
│  + AntV G6 │     │  /api/*     │     │  PDF / KG /  │     │  Extractor / │
│  + Tailwind│     │             │     │  RAG / HITL  │     │  Judge / Vis │
└────────────┘     └──────┬──────┘     └──────┬───────┘     └──────┬───────┘
                          │                   │                    │
                          ▼                   ▼                    ▼
                    in-memory state     numpy + BM25         OpenAI 兼容
                    (TEXTBOOKS,         (Cosine + RRF        (ModelScope /
                     MERGED_GRAPH,       + MMR Rerank)        OpenAI / Ollama)
                     CHUNKS, ...)
```

详见 [docs/系统设计.md](docs/系统设计.md)。

—

## 3. 环境依赖

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | **3.11 / 3.12** | FastAPI 后端运行环境 |
| Node.js | **18+** | Vite 前端构建 |
| pnpm / npm | 任一 | 推荐 `npm` |
| 可选：Docker | 24+ | 一键部署 |
| 可选：Ollama | latest | 本地 LLM |

后端关键库（见 [requirements.txt](requirements.txt)）：
`fastapi==0.110.0` · `uvicorn==0.29.0` · `openai>=1.13.3` · `numpy==1.26.4` ·
`pypdf==4.2.0` · `python-multipart==0.0.9` · `pydantic>=2.6.1` · 可选 `sentence-transformers==2.7.0`（启用真正的向量召回）。

前端：`vue@3` · `@antv/g6@4.x` · `tailwindcss` · `axios` · `vite`。

—

## 4. 安装步骤（本地开发）

### 4.1 克隆 + 安装依赖

```powershell
git clone <your-repo>.git
cd Education

# 后端：建议虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 可选：启用真正的向量召回（默认走 hash 哈希向量回退）
pip install sentence-transformers==2.7.0

# 前端
cd frontend
npm install
cd ..
```

### 4.2 配置 `.env`

```powershell
Copy-Item .env.example .env
```

最小可跑配置（云端 ModelScope）：

```env
EXTRACTOR_API_KEY=ms-xxxxxxxx-xxxx-xxxx
JUDGE_API_KEY=ms-xxxxxxxx-xxxx-xxxx
VISION_API_KEY=ms-xxxxxxxx-xxxx-xxxx
```

切换到**本地 Ollama**：

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

完整字段说明见 [.env.example](.env.example)。

### 4.3 启动

```powershell
# 终端 A：后端 (127.0.0.1:8000)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 B：前端 (127.0.0.1:5174)
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

打开 <http://127.0.0.1:5174> 即可。

—

## 5. Docker 一键部署

确保已装 Docker Desktop / Docker Engine + Compose v2。

```powershell
Copy-Item .env.example .env   # 填写 API Key
docker compose up -d --build
# 前端：http://localhost:8080   后端：http://localhost:8000/api/health
```

`docker-compose.yml` 默认启动两个服务：

| 服务 | 镜像 | 端口 | 持久化卷 |
| --- | --- | --- | --- |
| `backend` | 由根 [Dockerfile](Dockerfile) 构建 | `8000:8000` | `./report`、`./tests` |
| `frontend` | [frontend/Dockerfile](frontend/Dockerfile)（多阶段：Vite build → Nginx） | `8080:80` | — |

停止：`docker compose down`；查看日志：`docker compose logs -f backend`。

—

## 6. 使用流程

1. **上传教材**：进入「工作区」，拖入若干 PDF。系统会调用 MinerU 解析文本/图像/区块。
2. **抽取图谱**：每本书侧栏点「抽取」→ Extractor Agent 输出该书 KG。
3. **整合**：选 ≥ 2 本书 → 顶部「整合 N 本」→ Judge Agent 决策合并 / 重命名 / 拆分。
4. **图谱探索**：「全屏图谱」可在 4 种视图间切换；Shift+拖拽两节点触发自然语言合并指令。
5. **建立 RAG 索引**：「索引」按钮一键 chunking + 向量化。
6. **问答**：右侧聊天区提问；每条回答附「来源块」可点开查看原文坐标。
7. **仪表盘**：顶部「仪表盘」按钮 → 查看 Token 消耗、图谱规模、运行 RAG 基准、下载/导出整合报告。

—

## 7. 项目结构

```
Education/
├── backend/
│   ├── api/             # FastAPI 路由：upload / graph / rag / chat / stats
│   ├── core/            # 业务核心：pdf_parser / graph_builder / rag_pipeline
│   ├── utils/           # llm.py（双 Agent + Token 统计 + Ollama）/ ...
│   ├── storage/state.py # 内存态 + 落盘
│   ├── models/schemas.py
│   └── main.py
├── frontend/
│   ├── src/views/       # LandingView / WorkspaceView / GraphView / DashboardView
│   ├── src/api/         # axios 封装
│   └── nginx.conf
├── docs/                # 需求分析 / 系统设计 / Agent 架构说明
├── report/整合报告.md
├── tests/               # smoke_rag / smoke_http / rag_benchmark
├── .env.example
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

—

## 8. 关键 API 速查

| Method | Path | 说明 |
| --- | --- | --- |
| POST | `/api/upload` | 上传 PDF，返回 textbook_id |
| GET  | `/api/textbooks` | 列出已上传教材 |
| POST | `/api/graph/extract` | 单书图谱抽取 |
| POST | `/api/graph/merge` | 多书图谱融合 |
| POST | `/api/graph/modify` | **HITL** 自然语言修改图谱 |
| GET  | `/api/graph/` | 当前融合图谱 |
| POST | `/api/rag/index` | 建立检索索引 |
| POST | `/api/rag/query` | 混合检索 + Rerank 问答 |
| GET  | `/api/rag/source/{id}` | 取原文块 |
| GET  | `/api/stats/tokens` | LLM Token 用量 |
| GET  | `/api/stats/graph` | 图谱规模统计 |
| POST | `/api/stats/benchmark` | 跑 RAG 基准评测 |
| GET  | `/api/report/download` | 下载整合报告 (md) |
| GET  | `/api/report/pdf` | 导出 PDF |

—

## 9. 测试

```powershell
python tests/smoke_rag.py        # 离线 / 不依赖 LLM
python tests/smoke_http.py       # 在线 HTTP（需后端已启动）

# 跑 RAG 基准（或在仪表盘点击）
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/stats/benchmark | ConvertTo-Json -Depth 4
```

—

## 10. 故障排查

| 现象 | 排查 |
| --- | --- |
| 启动报 `ImportError: sentence_transformers` | 未装即可，会回退到 hash 向量；如需高质量召回 `pip install sentence-transformers` |
| `/api/rag/query` 401/403 | 检查 `.env` 中 `JUDGE_API_KEY` 是否有效 |
| Ollama 模式无响应 | `ollama serve` 是否运行；`ollama list` 是否有 `OLLAMA_MODEL` |
| Docker 后端容器 OOM | 调小 `RAG_CHUNK_SIZE` 或不安装 sentence-transformers |
| PDF 抽取失败 | `VISION_API_KEY` 是否对应 MinerU 模型；查看 backend 日志 |

—

## 11. 文档索引

- 需求分析：[docs/需求分析.md](docs/需求分析.md)
- 系统设计：[docs/系统设计.md](docs/系统设计.md)
- Agent 架构（含创新特性说明）：[docs/Agent架构说明.md](docs/Agent架构说明.md)
- 整合报告样例：[report/整合报告.md](report/整合报告.md)

—

## 12. 许可证

仅用于学术评审 / 教学示例。第三方模型（ModelScope / BGE / MinerU）请遵守其各自许可。
