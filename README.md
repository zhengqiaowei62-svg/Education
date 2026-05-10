# 学科知识整合智能体 (Education KG Agent)

> AI 全栈极速黑客松 · 5 小时极速实现版本

一个面向高校多教材整合场景的 AI 智能体：自动解析 PDF/MD/TXT 等多格式教材，构建可视化知识图谱，跨教材去重融合，并基于 RAG 提供带原文溯源的精准问答。

## 项目结构

```
Education/
├── backend/                    # 后端服务 (FastAPI)
│   ├── main.py                 # FastAPI 入口，CORS + 路由聚合
│   ├── api/                    # API 路由层（按业务领域切分）
│   │   ├── upload.py           # 教材上传与解析
│   │   ├── graph.py            # 知识图谱提取与跨教材融合
│   │   └── rag.py              # RAG 问答与索引
│   ├── core/                   # 核心业务逻辑（解析、抽取、对齐、检索）
│   │   ├── parser.py           # PDF/MD/TXT 解析（PyMuPDF）
│   │   ├── kg_extractor.py     # 章节级 LLM 知识点抽取
│   │   ├── kg_aligner.py       # 跨教材语义对齐与整合决策
│   │   └── rag_pipeline.py     # 分块、嵌入、向量检索、生成
│   ├── models/                 # Pydantic schema 定义
│   │   └── schemas.py
│   ├── storage/                # 运行时数据（向量库、解析结果，gitignore）
│   └── utils/                  # 工具方法（LLM 客户端、ID 生成等）
│       └── llm.py
├── frontend/                   # 前端 SPA (Vue 3 + Vite + Tailwind + AntV G6)
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── src/
│       ├── main.js             # Vue 入口
│       ├── App.vue             # 三栏布局根组件
│       ├── style.css           # Tailwind 入口
│       ├── api/index.js        # 后端 API 封装
│       └── components/
│           ├── TextbookPanel.vue    # 左侧：教材管理
│           ├── GraphCanvas.vue      # 中部：知识图谱画布（G6）
│           └── RightPanel.vue       # 右侧：整合 / RAG / 对话 Tab
├── docs/                       # 需求、设计、架构等评审文档
│   ├── 需求分析.md
│   ├── 系统设计.md
│   └── Agent架构说明.md
├── report/
│   └── 整合报告.md             # 以 7 本教材为例的整合报告
├── requirements.txt            # Python 依赖
├── .gitignore
└── README.md
```

## 环境依赖

- Python 3.10+
- Node.js 18+
- 一个可用的 LLM API Key（OpenAI / DeepSeek / 通义千问，任选其一）

## 快速开始

### 后端

```powershell
cd Education
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 配置环境变量（PowerShell）
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"   # 或其它兼容端点
$env:LLM_MODEL="deepseek-chat"

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
# 默认 http://localhost:5173 ，已配置代理 /api -> http://localhost:8000
```

## API 一览

| Method | Path                  | 描述                                |
| ------ | --------------------- | ----------------------------------- |
| POST   | `/api/upload`         | 多文件上传与解析（PDF/MD/TXT/DOCX） |
| GET    | `/api/textbooks`      | 已上传教材列表                      |
| POST   | `/api/graph/extract`  | 触发单本教材知识图谱抽取            |
| POST   | `/api/graph/merge`    | 跨教材图谱对齐与融合                |
| POST   | `/api/rag/index`      | 建立向量索引                        |
| POST   | `/api/rag/query`      | RAG 问答（带引用来源）              |
| GET    | `/api/rag/status`     | 索引状态                            |

更详细的字段定义见 [docs/系统设计.md](docs/系统设计.md)。
