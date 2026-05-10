"""图谱抽取（Agent A）+ 跨教材融合（Agent B）。"""
from fastapi import APIRouter, HTTPException

from backend.models.schemas import (
    GraphExtractRequest, GraphExtractResponse,
    GraphMergeRequest, GraphMergeResponse,
    KnowledgeGraph,
)
from backend.core import kg_extractor, kg_aligner
from backend.storage import state

router = APIRouter()


@router.post("/extract", response_model=GraphExtractResponse)
def extract_graph(req: GraphExtractRequest):
    tb = state.TEXTBOOKS.get(req.textbook_id)
    if not tb:
        raise HTTPException(404, "textbook not found")
    g = kg_extractor.extract_textbook(tb)
    state.GRAPHS[req.textbook_id] = g
    return GraphExtractResponse(graph=g)


@router.get("/{textbook_id}", response_model=KnowledgeGraph)
def get_graph(textbook_id: str):
    return state.GRAPHS.get(textbook_id, KnowledgeGraph(textbook_id=textbook_id))


@router.get("", response_model=KnowledgeGraph)
def get_merged_graph():
    return state.MERGED_GRAPH


@router.post("/merge", response_model=GraphMergeResponse)
def merge_graphs(req: GraphMergeRequest):
    graphs = []
    for tid in req.textbook_ids:
        g = state.GRAPHS.get(tid)
        if not g:
            # 自动抽取没图谱的教材
            tb = state.TEXTBOOKS.get(tid)
            if tb:
                g = kg_extractor.extract_textbook(tb)
                state.GRAPHS[tid] = g
        if g:
            graphs.append(g)

    merged, decisions, stats = kg_aligner.align_and_merge(
        graphs, similarity_threshold=req.similarity_threshold,
    )
    state.MERGED_GRAPH = merged
    return GraphMergeResponse(
        merged_graph=merged, decisions=decisions, stats=stats,
    )
