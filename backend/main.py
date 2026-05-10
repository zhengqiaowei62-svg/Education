"""FastAPI 入口：聚合各业务路由 + CORS。

启动：
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import upload, graph, rag, chat

app = FastAPI(
    title="学科知识整合智能体",
    description="多教材解析 / 知识图谱 / 跨教材融合 / RAG 精准问答",
    version="0.1.0",
)

# 跨域：开发阶段全开，部署时按需收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 业务路由
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
