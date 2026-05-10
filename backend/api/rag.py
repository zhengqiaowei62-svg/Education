"""RAG：建索引 / 问答 / 状态。"""
from fastapi import APIRouter

from backend.models.schemas import (
    RagIndexRequest, RagIndexResponse,
    RagQueryRequest, RagQueryResponse,
    RagStatus,
)
from backend.core import rag_pipeline
from backend.storage import state

router = APIRouter()


@router.get("/status", response_model=RagStatus)
def status():
    return RagStatus(
        indexed_textbooks=len({c["textbook_id"] for c in state.CHUNKS}),
        indexed_chunks=len(state.CHUNKS),
        ready=len(state.CHUNKS) > 0,
    )


@router.post("/index", response_model=RagIndexResponse)
def build_index(req: RagIndexRequest):
    n_books, n_chunks = rag_pipeline.build_index(req.textbook_ids)
    return RagIndexResponse(indexed_textbooks=n_books, indexed_chunks=n_chunks)


@router.post("/query", response_model=RagQueryResponse)
def query(req: RagQueryRequest):
    answer, citations, source_chunks = rag_pipeline.query(
        req.question,
        req.top_k,
        search_mode=req.search_mode,
        history=req.history,
    )
    return RagQueryResponse(
        answer=answer,
        citations=citations,
        source_chunks=source_chunks,
    )


@router.get("/source/{chunk_id}")
def source(chunk_id: str):
    chunk = state.CHUNK_BY_ID.get(chunk_id)
    if not chunk:
        return {"found": False, "chunk_id": chunk_id}
    return {"found": True, **{k: v for k, v in chunk.items() if k != "vector"}}
