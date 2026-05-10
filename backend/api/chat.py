"""
统一聊天入口 - 集成 Router + RAG + HITL修改
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

from backend.core.router import classify_intent
from backend.core import rag_pipeline
from backend.storage import state

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    top_k: int = 5
    search_mode: str = "hybrid"


class ChatResponse(BaseModel):
    intent: str  # "RAG" or "MODIFY"
    answer: str
    citations: Optional[List] = None
    modification: Optional[dict] = None


@router.post("/chat")
def chat_endpoint(req: ChatRequest):
    """
    统一聊天端点：
    1. Router分类意图
    2. RAG → 调用rag_pipeline.query()
    3. MODIFY → 调用图谱修改（依赖Task4的/api/graph/modify实现）
    """
    intent = classify_intent(req.message)

    if intent == "RAG":
        # 走RAG问答
        try:
            answer, citations, source_chunks = rag_pipeline.query(
                question=req.message,
                top_k=req.top_k,
                search_mode=req.search_mode,
            )
            return ChatResponse(
                intent="RAG",
                answer=answer or "暂无回答",
                citations=citations,
            )
        except Exception as e:
            return ChatResponse(
                intent="RAG",
                answer=f"RAG查询出错: {str(e)}",
                citations=[],
            )

    else:  # MODIFY
        # 调用图谱修改逻辑
        try:
            from backend.api.graph import _execute_modification
            result = _execute_modification(req.message)
            return ChatResponse(
                intent="MODIFY",
                answer=result.get("message", "修改已执行"),
                modification=result,
            )
        except ImportError:
            # Task4尚未实现时的降级
            return ChatResponse(
                intent="MODIFY",
                answer=f"已识别为图谱修改意图：「{req.message}」。修改功能即将上线。",
                modification={"status": "pending", "instruction": req.message},
            )
        except Exception as e:
            return ChatResponse(
                intent="MODIFY",
                answer=f"修改执行出错: {str(e)}",
                modification={"status": "error", "error": str(e)},
            )
