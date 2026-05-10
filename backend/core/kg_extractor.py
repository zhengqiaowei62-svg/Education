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
from typing import List

from backend.models.schemas import Chapter, KnowledgeGraph, KGNode, KGEdge
from backend.utils.llm import chat_json, llm_available


SYSTEM_PROMPT = """你是一名学科教材知识图谱构建专家（Extractor Agent）。
你的唯一职责是把章节正文转换为结构化的知识图谱 JSON。
严禁输出任何解释、寒暄、markdown 代码块。仅输出 JSON。"""


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


def extract_from_chapter(textbook_id: str, chapter: Chapter) -> KnowledgeGraph:
    if not llm_available("extractor") or not chapter.content.strip():
        return KnowledgeGraph(textbook_id=textbook_id, nodes=[], edges=[])

    prompt = USER_TEMPLATE.format(
        title=chapter.title,
        content=_trim(chapter.content, 4000),
    )
    data = chat_json(prompt, system=SYSTEM_PROMPT, role="extractor",
                     default={"nodes": [], "edges": []})
    return _to_graph(data, textbook_id, chapter)


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


def extract_textbook(textbook) -> KnowledgeGraph:
    """对一本教材的所有章节顺序抽取并合并。"""
    all_nodes: list[KGNode] = []
    all_edges: list[KGEdge] = []
    # 控制：最多处理前 N 个章节，避免 5h 内 token 爆炸
    MAX_CHAPTERS = 12
    for ch in textbook.chapters[:MAX_CHAPTERS]:
        if ch.char_count < 200:
            continue
        g = extract_from_chapter(textbook.textbook_id, ch)
        all_nodes.extend(g.nodes)
        all_edges.extend(g.edges)
    return KnowledgeGraph(textbook_id=textbook.textbook_id,
                          nodes=all_nodes, edges=all_edges)
