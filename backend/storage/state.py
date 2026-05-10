"""共享内存态：教材、图谱、RAG chunk。

极速 demo 阶段不引入 DB；后续可平移到 SQLite/Chroma。
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any

from backend.models.schemas import Textbook, KnowledgeGraph, ModificationRecord

# textbook_id -> Textbook（含 chapters[].content）
TEXTBOOKS: Dict[str, Textbook] = {}

# textbook_id -> KnowledgeGraph
GRAPHS: Dict[str, KnowledgeGraph] = {}

# 跨教材融合后的全局图谱
MERGED_GRAPH: KnowledgeGraph = KnowledgeGraph(nodes=[], edges=[])

# RAG chunks: list of dict {chunk_id, textbook_id, textbook, chapter, page,
# bbox, block_ids, text, vector, vector_tags}
CHUNKS: List[dict] = []

# chunk_id -> chunk，便于 citation 点击后定位原文块
CHUNK_BY_ID: Dict[str, dict] = {}

# 真实向量矩阵（BGE-small-zh 等，shape = [N, D]，dtype=float32, 已 L2 归一化）
# 当 sentence-transformers 不可用时保持为 None，retrieve 走哈希向量降级
CHUNK_VECS: Optional[Any] = None

# 图谱修改历史
MODIFICATIONS: list = []

# 待确认的合并决策 (decision_id -> MergeDecision)
PENDING_DECISIONS: dict = {}

