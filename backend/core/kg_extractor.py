"""Agent A · Extractor —— 知识图谱抽取者。

职责：纯粹的"阅读理解机器"。输入一个章节文本，输出标准化 JSON 节点+边。
原则：
1. 严格 JSON schema 约束
2. Few-shot 示范
3. 单章节单次调用，控制上下文
4. 解析失败回退为空图，不传染下游
"""
from __future__ import annotations
import uuid
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field, field_validator

from backend.models.schemas import Chapter, KnowledgeGraph, KGNode, KGEdge
from backend.utils.llm import chat_json, chat_json_validated, llm_available


# --- Reflexion 校验模型 ---
class ExtractedNode(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=60)
    definition: str = Field(default="", max_length=300)
    category: str = Field(default="核心概念")
    page: Optional[int] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        allowed = {"核心概念", "定理", "方法", "现象", "图像区块"}
        if v not in allowed:
            return "核心概念"
        return v


class ExtractedEdge(BaseModel):
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    relation_type: str = Field(default="parallel")
    description: str = Field(default="", max_length=120)

    @field_validator("relation_type")
    @classmethod
    def validate_relation(cls, v):
        allowed = {"prerequisite", "parallel", "contains", "applies_to"}
        if v not in allowed:
            return "parallel"
        return v


class ExtractedGraph(BaseModel):
    nodes: List[ExtractedNode] = Field(default_factory=list)
    edges: List[ExtractedEdge] = Field(default_factory=list)


SYSTEM_PROMPT = """你是一名学科教材知识图谱构建专家（Extractor Agent）。
你的唯一职责是把章节正文转换为结构化的知识图谱 JSON。
严禁输出任何解释、寒暄、markdown 代码块、<think> 思考链。请直接输出 JSON。
/no_think"""


USER_TEMPLATE = """请从下面的教材章节中抽取 5–15 个核心知识点（概念/定理/方法/现象），并识别它们之间的关系。

【输出 schema】
{{
  "nodes": [
    {{"id": "n1", "name": "概念名", "definition": "20-60字的定义", "category": "核心概念|定理|方法|现象", "page": 35}}
  ],
  "edges": [
    {{"source": "n1", "target": "n2", "relation_type": "prerequisite|parallel|contains|applies_to", "description": "10-30字"}}
  ]
}}

【few-shot 示例】
输入章节："第二章 细胞的基本功能 …静息电位是细胞处于静息状态时膜内外的电位差…动作电位是细胞受到刺激后…"
输出：
{{"nodes":[{{"id":"n1","name":"静息电位","definition":"细胞静息时膜内外的电位差","category":"核心概念","page":33}},{{"id":"n2","name":"动作电位","definition":"细胞受刺激后膜电位的快速可逆倒转","category":"核心概念","page":35}}],"edges":[{{"source":"n1","target":"n2","relation_type":"prerequisite","description":"理解动作电位需先掌握静息电位"}}]}}

【硬约束】
- id 用 n1/n2/n3… 短编号
- relation_type 只能取 prerequisite / parallel / contains / applies_to
- definition 必须基于章节原文，不要编造
- 仅输出 JSON 对象，不要任何其它字符

【章节标题】{title}

【章节正文（节选）】
{content}
"""


def _trim(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.6)]
    tail = text[-int(limit * 0.4):]
    return head + "\n…（中段省略）…\n" + tail


def extract_from_chapter(textbook_id: str, chapter) -> KnowledgeGraph:
    if not llm_available("extractor") or not chapter.content.strip():
        return KnowledgeGraph(textbook_id=textbook_id, nodes=[], edges=[])

    user_prompt = USER_TEMPLATE.format(
        title=chapter.title,
        content=_trim(chapter.content, 4000),
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    # 使用 Reflexion 机制替代原始 chat_json
    validated = chat_json_validated(
        "extractor", messages, ExtractedGraph,
        max_reflexion=3, max_tokens=1500, temperature=0.1
    )

    if validated is None:
        # Reflexion失败，降级到原始解析
        raw = chat_json("", "", role="extractor", messages=messages,
                        max_tokens=1500, temperature=0.1)
        if not raw:
            return KnowledgeGraph(textbook_id=textbook_id, nodes=[], edges=[])
        # 用原有容错逻辑解析
        nodes_data = raw.get("nodes", [])
        edges_data = raw.get("edges", [])
    else:
        nodes_data = [n.model_dump() for n in validated.nodes]
        edges_data = [e.model_dump() for e in validated.edges]

    return _to_graph({"nodes": nodes_data, "edges": edges_data}, textbook_id, chapter)


def _to_graph(data: dict, textbook_id: str, chapter: Chapter) -> KnowledgeGraph:
    nodes: List[KGNode] = []
    id_map: dict[str, str] = {}
    for raw in (data or {}).get("nodes", []) or []:
        try:
            local_id = str(raw.get("id", ""))
            global_id = f"{textbook_id}_{chapter.chapter_id}_{local_id or uuid.uuid4().hex[:6]}"
            id_map[local_id] = global_id
            nodes.append(KGNode(
                id=global_id,
                name=str(raw.get("name", "")).strip()[:60] or "未命名",
                definition=str(raw.get("definition", "")).strip()[:300],
                category=str(raw.get("category", "核心概念")).strip()[:20] or "核心概念",
                chapter=chapter.title,
                page=int(raw.get("page", chapter.page_start) or chapter.page_start),
                textbook_id=textbook_id,
                frequency=1,
            ))
        except Exception as e:
            print(f"[extractor] bad node: {e}")

    edges: List[KGEdge] = []
    valid_rel = {"prerequisite", "parallel", "contains", "applies_to"}
    for raw in (data or {}).get("edges", []) or []:
        try:
            s = id_map.get(str(raw.get("source", "")))
            t = id_map.get(str(raw.get("target", "")))
            r = str(raw.get("relation_type", "")).strip()
            if not s or not t or r not in valid_rel:
                continue
            edges.append(KGEdge(
                source=s, target=t,
                relation_type=r,  # type: ignore
                description=str(raw.get("description", ""))[:120],
            ))
        except Exception as e:
            print(f"[extractor] bad edge: {e}")

    return KnowledgeGraph(textbook_id=textbook_id, nodes=nodes, edges=edges)


def extract_textbook(textbook, max_workers: int = 4) -> KnowledgeGraph:
    """Map-Reduce 并行抽取：多章节并发处理"""
    MAX_CHAPTERS = 12
    chapters = [ch for ch in textbook.chapters[:MAX_CHAPTERS] if ch.char_count >= 200]

    all_nodes = []
    all_edges = []

    print(f"[Map-Reduce] 启动并行抽取，共 {len(chapters)} 章节，max_workers={max_workers}")

    # Map阶段：并发抽取
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ch = {
            executor.submit(extract_from_chapter, textbook.textbook_id, ch): ch
            for ch in chapters
        }
        for i, future in enumerate(as_completed(future_to_ch), 1):
            ch = future_to_ch[future]
            try:
                g = future.result()
                all_nodes.extend(g.nodes)
                all_edges.extend(g.edges)
                print(f"[Map-Reduce] 完成 {i}/{len(chapters)}: {ch.title[:30]}")
            except Exception as e:
                print(f"[Map-Reduce] 章节失败: {ch.title[:30]} - {e}")

    # 图像区块处理（保持原有逻辑）
    visual_nodes, visual_edges = _visual_block_graph(textbook, all_nodes)
    all_nodes.extend(visual_nodes)
    all_edges.extend(visual_edges)

    print(f"[Map-Reduce] Reduce完成：{len(all_nodes)} 节点, {len(all_edges)} 边")
    return KnowledgeGraph(textbook_id=textbook.textbook_id, nodes=all_nodes, edges=all_edges)


def extract_textbooks_parallel(textbooks: list, max_workers: int = 2) -> list:
    """多教材并行Map-Reduce抽取"""
    results = []
    print(f"[Map-Reduce] 启动多教材并行，共 {len(textbooks)} 本")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_tb = {
            executor.submit(extract_textbook, tb, max_workers=3): tb
            for tb in textbooks
        }
        for future in as_completed(future_to_tb):
            tb = future_to_tb[future]
            try:
                g = future.result()
                results.append((tb.textbook_id, g))
                print(f"[Map-Reduce] 教材完成: {tb.title}")
            except Exception as e:
                print(f"[Map-Reduce] 教材失败: {tb.title} - {e}")

    return results


def _visual_block_graph(textbook, existing_nodes: list[KGNode]) -> tuple[list[KGNode], list[KGEdge]]:
    """把 PDF 图像/图表区块转成可见图谱节点。

    当前实现先保留 bbox 与页码，便于后续接入 MinerU/视觉模型对图像内容做 OCR/描述。
    """
    nodes: list[KGNode] = []
    edges: list[KGEdge] = []
    visual_blocks = [b for b in getattr(textbook, "blocks", []) if b.kind in {"image", "table", "figure"}]
    for block in visual_blocks[:40]:
        node_id = f"{textbook.textbook_id}_{block.block_id}_visual"
        node = KGNode(
            id=node_id,
            name=f"图像区块 P{block.page}",
            definition=block.text or f"PDF 第 {block.page} 页的图像/图表区域",
            category="图像区块",
            chapter=block.chapter,
            page=block.page,
            textbook_id=textbook.textbook_id,
            frequency=1,
            bbox=block.bbox,
            source_block_id=block.block_id,
            source_url=f"/source-block/{block.block_id}?textbook_id={textbook.textbook_id}&page={block.page}",
        )
        nodes.append(node)
        anchor = next((n for n in existing_nodes if n.chapter == block.chapter), None)
        if anchor:
            edges.append(KGEdge(
                source=anchor.id,
                target=node_id,
                relation_type="contains",
                description="章节概念包含该图像/图表证据区块",
            ))
    return nodes, edges
