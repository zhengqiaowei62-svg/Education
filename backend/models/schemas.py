"""统一的 Pydantic 数据模型。

放在一处便于前后端字段对齐与文档生成。
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# -------------------- 教材解析 --------------------

class SourceBlock(BaseModel):
    block_id: str
    kind: Literal["text", "image", "table", "figure"] = "text"
    page: int = 1
    bbox: List[float] = []
    text: str = ""
    chapter_id: str = ""
    chapter: str = ""
    image_ext: Optional[str] = None


class Chapter(BaseModel):
    chapter_id: str
    title: str
    page_start: int = 0
    page_end: int = 0
    content: str = ""
    char_count: int = 0
    block_ids: List[str] = []


class Textbook(BaseModel):
    textbook_id: str
    filename: str
    title: str
    total_pages: int = 0
    total_chars: int = 0
    chapters: List[Chapter] = []
    blocks: List[SourceBlock] = []


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
    confidence: float = 1.0  # 抽取置信度
    bbox: List[float] = []
    source_block_id: Optional[str] = None
    source_url: Optional[str] = None


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
    textbook_id: str = ""
    textbook: str
    chapter: str
    page: int
    page_end: int = 0
    relevance_score: float
    chunk_id: str = ""
    bbox: List[float] = []
    block_ids: List[str] = []
    quote: str = ""
    source_url: str = ""
    retrieval_mode: str = "hybrid"


class RagQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = 5
    search_mode: Literal["hybrid", "term", "semantic", "region"] = "hybrid"
    # 多轮对话历史：[{role: 'user'|'assistant', content: '...'}]
    history: List[dict] = []


class RagQueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    source_chunks: List[str]


# -------------------- Human-in-the-Loop 图谱修改 --------------------

class GraphModifyRequest(BaseModel):
    """教师图谱修改请求"""
    instruction: str  # 教师的自然语言指令
    node_ids: Optional[List[str]] = None  # 可选：指定操作的节点ID


class ModificationRecord(BaseModel):
    """图谱修改记录"""
    mod_id: str
    action: str  # split, rename, delete, merge, add_edge, remove_edge
    target_nodes: List[str]
    before: dict  # 修改前状态
    after: dict   # 修改后状态
    teacher_instruction: str
    timestamp: str
    confidence: float = 1.0
