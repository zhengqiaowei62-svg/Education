"""RAG Pipeline · 极简但可用版本。

- chunking: sliding window，size=600，overlap=100
- 检索：基于关键词重叠 + 字符级相似度（无需向量模型，零下载）
- 生成：LLM 严格基于检索上下文回答，并附带引用元数据

后续可平替为 ChromaDB + sentence-transformers，接口不变。
"""
from __future__ import annotations
import re
from typing import List, Tuple

from backend.models.schemas import Citation
from backend.utils.llm import chat, llm_available, tokens
from backend.storage import state


CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


# ----------- 分块 -----------

def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks = []
    i = 0
    step = max(size - overlap, 1)
    while i < len(text):
        chunks.append(text[i: i + size])
        if i + size >= len(text):
            break
        i += step
    return chunks


def build_index(textbook_ids: List[str] | None = None) -> Tuple[int, int]:
    """重建 chunks 列表（覆盖旧索引）。"""
    state.CHUNKS.clear()
    targets = textbook_ids or list(state.TEXTBOOKS.keys())
    n_books = 0
    for tid in targets:
        tb = state.TEXTBOOKS.get(tid)
        if not tb:
            continue
        n_books += 1
        for ch in tb.chapters:
            for piece in chunk_text(ch.content):
                state.CHUNKS.append({
                    "textbook_id": tid,
                    "textbook": tb.title,
                    "chapter": ch.title,
                    "page": ch.page_start,
                    "text": piece,
                })
    return n_books, len(state.CHUNKS)


# ----------- 检索（关键词得分 + Jaccard） -----------

def _score(query_tokens: set[str], chunk_text: str) -> float:
    ct = set(tokens(chunk_text))
    if not ct or not query_tokens:
        return 0.0
    overlap = len(query_tokens & ct)
    if overlap == 0:
        return 0.0
    # 倾向于覆盖率（query 中有多少词在 chunk 里）
    coverage = overlap / max(len(query_tokens), 1)
    jaccard = overlap / len(query_tokens | ct)
    return 0.7 * coverage + 0.3 * jaccard


def retrieve(question: str, top_k: int = 5) -> List[dict]:
    qtok = set(tokens(question))
    scored = []
    for c in state.CHUNKS:
        s = _score(qtok, c["text"])
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, c in scored[:top_k]:
        out.append({**c, "relevance_score": round(s, 4)})
    return out


# ----------- 生成 -----------

ANSWER_SYSTEM = """你是一名严谨的医学/生物学教学助手。
你必须严格基于提供的"参考资料"回答用户问题，不允许使用资料以外的知识。
如果参考资料无法回答，请直接回复"当前知识库中未找到相关信息"。
回答末尾使用 [教材名称, 章节, 第X页] 的格式标注引用。"""


ANSWER_TEMPLATE = """【参考资料】
{context}

【用户问题】
{question}

请基于上述参考资料用 200 字以内简洁回答，并在结尾标注引用编号 [1][2]…对应资料编号。"""


def query(question: str, top_k: int = 5):
    hits = retrieve(question, top_k=top_k)
    citations = [
        Citation(
            textbook=h["textbook"],
            chapter=h["chapter"],
            page=h["page"],
            relevance_score=h["relevance_score"],
        ) for h in hits
    ]
    source_chunks = [h["text"] for h in hits]

    if not hits:
        return "当前知识库中未找到相关信息。", citations, source_chunks

    if not llm_available("judge"):
        # 回退：拼接最相关片段作为答案
        joined = "\n---\n".join(h["text"][:300] for h in hits[:2])
        return f"（未配置 LLM，仅返回最相关片段）\n{joined}", citations, source_chunks

    context = "\n\n".join(
        f"[{i+1}] 《{h['textbook']}》· {h['chapter']} · 第 {h['page']} 页\n{h['text']}"
        for i, h in enumerate(hits)
    )
    prompt = ANSWER_TEMPLATE.format(context=context[:6000], question=question)
    try:
        answer = chat(prompt, system=ANSWER_SYSTEM, role="judge",
                      temperature=0.2, max_tokens=500)
    except Exception as e:
        answer = f"LLM 调用失败：{e}\n\n可参考片段：\n{hits[0]['text'][:300]}"
    return answer, citations, source_chunks
