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
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

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


USER_TEMPLATE = """请从下面的教材章节中抽取 5–15 个核心知识点（概念/定理/方法/现象），并充分识别它们之间的关系。

【输出 schema】
{{
  "nodes": [
    {{"id": "n1", "name": "概念名", "definition": "20-60字的定义", "category": "核心概念|定理|方法|现象", "page": 35, "confidence": 0.95}}
  ],
  "edges": [
    {{"source": "n1", "target": "n2", "relation_type": "prerequisite|parallel|contains|applies_to", "description": "10-30字"}}
  ]
}}

【关系边要求 — 非常重要】
- 每个节点至少与1个其他节点建立关系边，不允许出现孤立节点
- edges 数量应不少于 nodes 数量的 80%（例如10个节点至少8条边）
- 关系类型选择指南：
  · prerequisite（前置依赖）：概念A是理解概念B的前提
  · contains（包含）：大概念包含子概念，章节层级关系
  · parallel（并列）：同层级、同类别的概念
  · applies_to（应用于）：方法/定理应用到具体场景
- 优先识别 prerequisite 和 contains 关系，其次 applies_to，最后 parallel

【few-shot 示例】
输入章节："第二章 细胞的基本功能 …静息电位是细胞处于静息状态时膜内外的电位差…动作电位是细胞受到刺激后…钠钾泵维持浓度梯度…阈电位是触发动作电位的临界值…"
输出：
{{"nodes":[{{"id":"n1","name":"细胞膜电位","definition":"细胞膜内外的电位差总称","category":"核心概念","page":32,"confidence":0.90}},{{"id":"n2","name":"静息电位","definition":"细胞静息时膜内外的电位差","category":"核心概念","page":33,"confidence":0.95}},{{"id":"n3","name":"动作电位","definition":"细胞受刺激后膜电位的快速可逆倒转","category":"核心概念","page":35,"confidence":0.92}},{{"id":"n4","name":"钠钾泵","definition":"主动转运Na+和K+维持浓度梯度的膜蛋白","category":"方法","page":34,"confidence":0.93}},{{"id":"n5","name":"阈电位","definition":"触发动作电位的临界去极化电位值","category":"核心概念","page":36,"confidence":0.91}}],"edges":[{{"source":"n1","target":"n2","relation_type":"contains","description":"静息电位是膜电位的一种形式"}},{{"source":"n1","target":"n3","relation_type":"contains","description":"动作电位是膜电位的一种形式"}},{{"source":"n2","target":"n3","relation_type":"prerequisite","description":"理解动作电位需先掌握静息电位"}},{{"source":"n4","target":"n2","relation_type":"prerequisite","description":"钠钾泵维持静息电位所需的离子梯度"}},{{"source":"n5","target":"n3","relation_type":"prerequisite","description":"达到阈电位才能触发动作电位"}}]}}

【硬约束】
- id 用 n1/n2/n3… 短编号
- relation_type 只能取 prerequisite / parallel / contains / applies_to
- definition 必须基于章节原文，不要编造
- 仅输出 JSON 对象，不要任何其它字符
- edges 数量不得少于 nodes 数量减1（确保图连通性）

【章节标题】{title}

【章节正文（节选）】
{content}
"""


def _trim(text: str, limit: int = 2500) -> str:
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
        content=_trim(chapter.content, 2500),
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
                confidence=float(raw.get("confidence", 0.9)),
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


def _auto_connect_isolated(nodes: List[KGNode], edges: List[KGEdge]) -> List[KGEdge]:
    """为孤立节点自动补充边关系（兜底方案）。

    只处理完全孤立的节点（没有任何边连接），将其与同章节已连接的节点建立 parallel 关系。
    """
    if not nodes or not edges:
        # 如果完全没有边，用链式连接同章节节点
        if not edges and len(nodes) > 1:
            new_edges = []
            chapter_groups: dict[str, List[KGNode]] = {}
            for n in nodes:
                chapter_groups.setdefault(n.chapter, []).append(n)
            for chapter_nodes in chapter_groups.values():
                for i in range(len(chapter_nodes) - 1):
                    new_edges.append(KGEdge(
                        source=chapter_nodes[i].id,
                        target=chapter_nodes[i + 1].id,
                        relation_type="parallel",
                        description="同章节概念关联",
                    ))
            return new_edges
        return edges

    # 找出已连接的节点
    connected_ids = set()
    for e in edges:
        connected_ids.add(e.source)
        connected_ids.add(e.target)

    # 找出孤立节点
    node_ids = {n.id for n in nodes}
    isolated_ids = node_ids - connected_ids

    if not isolated_ids:
        return edges

    new_edges = list(edges)
    for iso_id in isolated_ids:
        iso_node = next((n for n in nodes if n.id == iso_id), None)
        if not iso_node:
            continue

        # 找同章节中已连接的节点
        same_chapter_connected = [
            n for n in nodes
            if n.chapter == iso_node.chapter and n.id != iso_id and n.id in connected_ids
        ]
        if same_chapter_connected:
            target = same_chapter_connected[0]
            new_edges.append(KGEdge(
                source=iso_id,
                target=target.id,
                relation_type="parallel",
                description="同章节概念关联",
            ))
        else:
            # 同章节都是孤立的，连接到同章节第一个非自身节点
            same_chapter_any = [
                n for n in nodes
                if n.chapter == iso_node.chapter and n.id != iso_id
            ]
            if same_chapter_any:
                target = same_chapter_any[0]
                new_edges.append(KGEdge(
                    source=iso_id,
                    target=target.id,
                    relation_type="parallel",
                    description="同章节概念关联",
                ))

    print(f"[AutoConnect] 补充了 {len(new_edges) - len(edges)} 条边（孤立节点: {len(isolated_ids)}）")
    return new_edges


def _cross_chapter_edges(nodes: List[KGNode], edges: List[KGEdge]) -> List[KGEdge]:
    """为相邻章节之间建立 prerequisite 关系。

    逻辑：将前一章节的最后一个节点与下一章节的第一个节点用 prerequisite 连接，
    表达章节间的知识递进关系。
    """
    # 按章节分组，保持顺序
    chapter_order: List[str] = []
    chapter_nodes: dict[str, List[KGNode]] = {}
    for n in nodes:
        if n.category == "图像区块":
            continue
        if n.chapter not in chapter_nodes:
            chapter_order.append(n.chapter)
            chapter_nodes[n.chapter] = []
        chapter_nodes[n.chapter].append(n)

    new_edges = list(edges)
    existing_pairs = {(e.source, e.target) for e in edges}

    for i in range(len(chapter_order) - 1):
        prev_chapter = chapter_order[i]
        next_chapter = chapter_order[i + 1]
        prev_nodes = chapter_nodes.get(prev_chapter, [])
        next_nodes = chapter_nodes.get(next_chapter, [])

        if prev_nodes and next_nodes:
            # 前一章最后一个节点 -> 下一章第一个节点
            src = prev_nodes[-1]
            tgt = next_nodes[0]
            if (src.id, tgt.id) not in existing_pairs:
                new_edges.append(KGEdge(
                    source=src.id,
                    target=tgt.id,
                    relation_type="prerequisite",
                    description=f"章节递进：{prev_chapter[:15]}→{next_chapter[:15]}",
                ))
                existing_pairs.add((src.id, tgt.id))

    added = len(new_edges) - len(edges)
    if added > 0:
        print(f"[CrossChapter] 补充了 {added} 条跨章节边")
    return new_edges


def extract_textbook(textbook, max_workers: int = 2) -> KnowledgeGraph:
    """Map-Reduce 并行抽取：多章节并发处理（默认2并发，避免LLM端点过载）"""
    MAX_CHAPTERS = 6
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

    # 后处理：为孤立节点补边
    all_edges = _auto_connect_isolated(all_nodes, all_edges)

    # 后处理：跨章节连接
    all_edges = _cross_chapter_edges(all_nodes, all_edges)

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
        # 只为有实质文字内容的区块创建节点，跳过无意义的空图像区块
        if len((block.text or "").strip()) < 20:
            continue
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
