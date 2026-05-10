"""统一的 Pydantic 数据模型。

放在一处便于前后端字段对齐与文档生成。
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# -------------------- 教材解析 --------------------

class Chapter(BaseModel):
    chapter_id: str
    title: str
    page_start: int = 0
    page_end: int = 0
    content: str = ""
    char_count: int = 0


class Textbook(BaseModel):
    textbook_id: str
    filename: str
    title: str
    total_pages: int = 0
    total_chars: int = 0
    chapters: List[Chapter] = []


class UploadFileStatus(BaseModel):
    filename: str
    size: int
    format: str
    status: Literal["parsing", "done", "failed"] = "parsing"
    textbook_id: Optional[str] = None
    message: Optional[str] = None


class UploadResponse(BaseModel):
    files: List[UploadFileStatus]


# -------------------- 知识图谱 --------------------

class KGNode(BaseModel):
    id: str
    name: str
    definition: str = ""
    category: str = "核心概念"
    chapter: str = ""
    page: int = 0
    textbook_id: str = ""
    frequency: int = 1  # 跨教材出现次数（融合后）


class KGEdge(BaseModel):
    source: str
    target: str
    relation_type: Literal["prerequisite", "parallel", "contains", "applies_to"]
    description: str = ""


class KnowledgeGraph(BaseModel):
    textbook_id: Optional[str] = None  # 单本图谱时使用
    nodes: List[KGNode] = []
    edges: List[KGEdge] = []


class GraphExtractRequest(BaseModel):
    textbook_id: str


class GraphExtractResponse(BaseModel):
    graph: KnowledgeGraph


# -------------------- 跨教材融合 --------------------

class MergeDecision(BaseModel):
    decision_id: str
    action: Literal["merge", "keep", "remove"]
    affected_nodes: List[str]
    result_node: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0


class GraphMergeRequest(BaseModel):
    textbook_ids: List[str]
    similarity_threshold: float = 0.85


class GraphMergeResponse(BaseModel):
    merged_graph: KnowledgeGraph
    decisions: List[MergeDecision]
    stats: dict  # 原始字数 / 整合后字数 / 压缩比 / 节点数变化


# -------------------- RAG --------------------

class RagIndexRequest(BaseModel):
    textbook_ids: Optional[List[str]] = None  # None = 全部


class RagIndexResponse(BaseModel):
    indexed_textbooks: int
    indexed_chunks: int


class RagStatus(BaseModel):
    indexed_textbooks: int
    indexed_chunks: int
    ready: bool


class Citation(BaseModel):
    textbook: str
    chapter: str
    page: int
    relevance_score: float


class RagQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = 5


class RagQueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    source_chunks: List[str]
