"""RAG Pipeline.

- 文本切割：滑窗 overlap，PDF chunk 绑定 page/bbox/block_ids
- 向量整理：为每个 chunk 生成 vector_tags 与本地 hash embedding
- 检索：BM25 强词块匹配 + 语义向量 + 图谱/章节区域检索，RRF 融合
- 溯源：citation 返回 chunk_id、bbox、quote 与 source_url
"""
from __future__ import annotations
from collections import Counter, defaultdict
import hashlib
import math
import os
import re
import threading
from typing import Iterable, List, Tuple

from backend.models.schemas import Citation, SourceBlock
from backend.utils.llm import chat, llm_available, tokens
from backend.storage import state


CHUNK_SIZE = 600
CHUNK_OVERLAP = 100
EMBED_DIM = 384
RRF_K = 60


# ----------- 真实语义嵌入（BGE 等 sentence-transformers 模型） -----------

_ST_MODEL = None
_ST_LOCK = threading.Lock()
_ST_DISABLED = False
_ST_MODEL_NAME = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")


def _get_st_model():
    """惰性加载 sentence-transformers 模型；失败一次即永久降级到哈希向量。"""
    global _ST_MODEL, _ST_DISABLED
    if _ST_DISABLED:
        return None
    if _ST_MODEL is not None:
        return _ST_MODEL
    with _ST_LOCK:
        if _ST_MODEL is not None:
            return _ST_MODEL
        if _ST_DISABLED:
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            print(f"[rag] loading embedding model: {_ST_MODEL_NAME}", flush=True)
            _ST_MODEL = SentenceTransformer(_ST_MODEL_NAME)
            return _ST_MODEL
        except Exception as exc:  # noqa: BLE001
            print(f"[rag] embedding model unavailable, fallback to hash: {exc}", flush=True)
            _ST_DISABLED = True
            return None


def _encode(texts: list[str]):
    """批量编码为 L2 归一化的 numpy 矩阵；失败返回 None。"""
    model = _get_st_model()
    if model is None or not texts:
        return None
    try:
        import numpy as np  # noqa: WPS433
        vecs = model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype="float32")
    except Exception as exc:  # noqa: BLE001
        print(f"[rag] encode failed: {exc}", flush=True)
        return None


# ----------- 分块与向量整理 -----------

def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks = []
    i = 0
    step = max(size - overlap, 1)
    while i < len(text):
        piece = text[i: i + size]
        if piece.strip():
            chunks.append(piece)
        if i + size >= len(text):
            break
        i += step
    return chunks


def _vector_tags(text: str, limit: int = 8) -> list[str]:
    terms = [t for t in tokens(text) if len(t.strip()) > 1 or "\u4e00" <= t <= "\u9fff"]
    return [term for term, _ in Counter(terms).most_common(limit)]


def _hash_embedding(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    for token in tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "little")
        idx = raw % EMBED_DIM
        sign = 1.0 if (raw >> 9) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _union_bbox(blocks: Iterable[SourceBlock]) -> list[float]:
    boxes = [b.bbox for b in blocks if b.bbox and len(b.bbox) == 4]
    if not boxes:
        return []
    pages = {b.page for b in blocks if b.bbox and len(b.bbox) == 4}
    if len(pages) > 1:
        return []
    return [
        round(min(b[0] for b in boxes), 2),
        round(min(b[1] for b in boxes), 2),
        round(max(b[2] for b in boxes), 2),
        round(max(b[3] for b in boxes), 2),
    ]


def _make_chunk(tb, chapter, text: str, index: int,
                blocks: list[SourceBlock]) -> dict:
    page = min((b.page for b in blocks), default=chapter.page_start or 1)
    page_end = max((b.page for b in blocks), default=chapter.page_end or page)
    chunk_id = f"{tb.textbook_id}_{chapter.chapter_id}_c{index:04d}"
    block_ids = [b.block_id for b in blocks]
    return {
        "chunk_id": chunk_id,
        "textbook_id": tb.textbook_id,
        "textbook": tb.title,
        "chapter_id": chapter.chapter_id,
        "chapter": chapter.title,
        "page": page,
        "page_end": page_end,
        "bbox": _union_bbox(blocks),
        "block_ids": block_ids,
        "text": text,
        "vector_tags": _vector_tags(text),
        "vector": _hash_embedding(text),
        "source_url": f"/source/{chunk_id}?textbook_id={tb.textbook_id}&page={page}",
    }


def _chunks_from_blocks(tb, chapter) -> list[dict]:
    text_blocks = [
        block for block in tb.blocks
        if block.kind == "text" and block.chapter_id == chapter.chapter_id and block.text.strip()
    ]
    if not text_blocks:
        return [
            _make_chunk(tb, chapter, piece, i + 1, [])
            for i, piece in enumerate(chunk_text(chapter.content))
        ]

    chunks: list[dict] = []
    current_text: list[str] = []
    current_blocks: list[SourceBlock] = []
    chunk_index = 1

    def flush() -> None:
        nonlocal chunk_index, current_text, current_blocks
        text = "\n".join(current_text).strip()
        if text:
            chunks.append(_make_chunk(tb, chapter, text, chunk_index, current_blocks))
            chunk_index += 1
        overlap_tail = text[-CHUNK_OVERLAP:] if len(text) > CHUNK_OVERLAP else ""
        current_text = [overlap_tail] if overlap_tail else []
        current_blocks = current_blocks[-1:] if current_blocks else []

    for block in text_blocks:
        pieces = chunk_text(block.text)
        for piece in pieces:
            next_len = sum(len(t) for t in current_text) + len(piece)
            if current_text and next_len > CHUNK_SIZE:
                flush()
            current_text.append(piece)
            current_blocks.append(block)
    flush()
    return chunks


def build_index(textbook_ids: List[str] | None = None) -> Tuple[int, int]:
    """重建内存索引。"""
    state.CHUNKS.clear()
    state.CHUNK_BY_ID.clear()
    state.CHUNK_VECS = None
    targets = textbook_ids or list(state.TEXTBOOKS.keys())
    n_books = 0
    for tid in targets:
        tb = state.TEXTBOOKS.get(tid)
        if not tb:
            continue
        n_books += 1
        for chapter in tb.chapters:
            for chunk in _chunks_from_blocks(tb, chapter):
                state.CHUNKS.append(chunk)
                state.CHUNK_BY_ID[chunk["chunk_id"]] = chunk

    # 真实向量批编码（可选、失败自动降级）
    if state.CHUNKS:
        vecs = _encode([c["text"] for c in state.CHUNKS])
        if vecs is not None and len(vecs) == len(state.CHUNKS):
            state.CHUNK_VECS = vecs
            print(f"[rag] built dense index: {vecs.shape}", flush=True)
    return n_books, len(state.CHUNKS)


# ----------- 检索 -----------

def _bm25(question: str) -> list[tuple[float, dict]]:
    q_terms = tokens(question)
    if not q_terms:
        return []
    docs = [tokens(c["text"]) for c in state.CHUNKS]
    if not docs:
        return []
    avgdl = sum(len(d) for d in docs) / max(len(docs), 1)
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        doc_freq.update(set(doc))

    k1, b = 1.5, 0.75
    scored: list[tuple[float, dict]] = []
    for chunk, doc in zip(state.CHUNKS, docs):
        freq = Counter(doc)
        score = 0.0
        for term in q_terms:
            if not freq[term]:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = freq[term] + k1 * (1 - b + b * len(doc) / max(avgdl, 1))
            score += idf * freq[term] * (k1 + 1) / denom
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _semantic(question: str) -> list[tuple[float, dict]]:
    # 优先走真实语义向量（BGE 等）
    vecs = state.CHUNK_VECS
    if vecs is not None and len(state.CHUNKS) == len(vecs):
        q_vec = _encode([question])
        if q_vec is not None and len(q_vec) == 1:
            try:
                import numpy as np  # noqa: WPS433
                sims = (vecs @ q_vec[0].astype("float32"))  # 均已 L2 归一化
                ranked = sorted(
                    ((float(sims[i]), state.CHUNKS[i]) for i in range(len(state.CHUNKS))),
                    key=lambda item: item[0],
                    reverse=True,
                )
                return [pair for pair in ranked if pair[0] > 0]
            except Exception as exc:  # noqa: BLE001
                print(f"[rag] dense retrieve failed, fallback: {exc}", flush=True)
    # 降级：本地 hash embedding + token 重合度
    q_vec_local = _hash_embedding(question)
    scored = [(_cosine(q_vec_local, chunk["vector"]), chunk) for chunk in state.CHUNKS]
    scored = [(score, chunk) for score, chunk in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _region(question: str) -> list[tuple[float, dict]]:
    """图谱/章节区域检索：先命中概念节点，再扩展到同章节/相邻页 chunk。"""
    q_terms = set(tokens(question))
    if not q_terms:
        return []
    node_hits = []
    for node in state.MERGED_GRAPH.nodes:
        text = f"{node.name} {node.definition} {node.chapter}"
        node_terms = set(tokens(text))
        overlap = len(q_terms & node_terms)
        if overlap:
            node_hits.append((overlap / max(len(q_terms), 1), node))
    if not node_hits:
        return []

    region_scores: defaultdict[str, float] = defaultdict(float)
    for node_score, node in node_hits:
        for chunk in state.CHUNKS:
            same_book = node.textbook_id and chunk["textbook_id"] in node.textbook_id.split(",")
            same_chapter = node.chapter and node.chapter == chunk["chapter"]
            near_page = node.page and abs(int(chunk["page"]) - int(node.page)) <= 1
            if same_chapter or (same_book and near_page):
                region_scores[chunk["chunk_id"]] += node_score * (1.0 if same_chapter else 0.65)

    out = [(score, state.CHUNK_BY_ID[cid]) for cid, score in region_scores.items()]
    out.sort(key=lambda item: item[0], reverse=True)
    return out


def _rrf(ranked_lists: list[tuple[str, list[tuple[float, dict]]]],
         top_k: int) -> list[dict]:
    scores: defaultdict[str, float] = defaultdict(float)
    raw_scores: defaultdict[str, float] = defaultdict(float)
    modes: defaultdict[str, list[str]] = defaultdict(list)
    chunks: dict[str, dict] = {}
    for mode, ranked in ranked_lists:
        for rank, (score, chunk) in enumerate(ranked[: max(top_k * 3, 10)], start=1):
            cid = chunk["chunk_id"]
            scores[cid] += 1.0 / (RRF_K + rank)
            raw_scores[cid] = max(raw_scores[cid], float(score))
            if mode not in modes[cid]:
                modes[cid].append(mode)
            chunks[cid] = chunk
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [
        {
            **chunks[cid],
            "relevance_score": round(min(1.0, scores[cid] * 8 + raw_scores[cid] * 0.12), 4),
            "retrieval_mode": "+".join(modes[cid]),
        }
        for cid, _ in ordered
    ]


def retrieve(question: str, top_k: int = 5, search_mode: str = "hybrid") -> List[dict]:
    if not state.CHUNKS:
        return []
    channels: list[tuple[str, list[tuple[float, dict]]]] = []
    if search_mode in {"hybrid", "term"}:
        channels.append(("term", _bm25(question)))
    if search_mode in {"hybrid", "semantic", "region"}:
        channels.append(("semantic", _semantic(question)))
    if search_mode in {"hybrid", "region"}:
        channels.append(("region", _region(question)))
    # 第一阶段：RRF 融合得到 top_k * 3 候选
    rrf_pool = max(top_k * 3, 12)
    fused = _rrf(channels, rrf_pool)
    # 第二阶段：可选 Rerank（cross-score / MMR），输出最终 top_k
    final = _rerank(question, fused, top_k=top_k)
    return final


# ----------- Rerank（向量重排 + MMR 多样性） -----------

RERANK_LAMBDA = 0.7  # MMR 权重：相关性 vs 多样性


def _rerank(question: str, candidates: list[dict], top_k: int) -> list[dict]:
    """两步 Rerank：
    1. 用 BGE 余弦计算 query↔candidate 的精排分（若 BGE 不可用则跳过此步）
    2. MMR 选 top_k：兼顾相关性与多样性，避免连续 chunk 高度重复
    """
    if not candidates:
        return []
    # ----- 精排分 -----
    fine_scores: list[float] = []
    q_vec = _encode([question])
    cand_vecs = _encode([c["text"] for c in candidates]) if q_vec is not None else None
    if q_vec is not None and cand_vecs is not None and len(cand_vecs) == len(candidates):
        try:
            import numpy as np  # noqa: WPS433
            sims = (cand_vecs @ q_vec[0].astype("float32"))
            fine_scores = [float(x) for x in sims]
        except Exception as exc:  # noqa: BLE001
            print(f"[rag] rerank cosine failed: {exc}", flush=True)
    if not fine_scores:
        # 退化：用 RRF 后的 relevance_score 作为精排分
        fine_scores = [float(c.get("relevance_score", 0.0)) for c in candidates]

    # ----- MMR 多样性选择 -----
    chosen: list[int] = []
    available = list(range(len(candidates)))
    # 第一名取相关性最高
    first = max(available, key=lambda i: fine_scores[i])
    chosen.append(first)
    available.remove(first)

    def _div(i: int) -> float:
        # 与已选 chunk 文本的 token 重合度（无向量时用 Jaccard 替代）
        if cand_vecs is not None and len(cand_vecs) == len(candidates):
            try:
                import numpy as np  # noqa: WPS433
                vi = cand_vecs[i]
                return float(max((vi @ cand_vecs[j]) for j in chosen))
            except Exception:
                pass
        ti = set(tokens(candidates[i]["text"]))
        return max(
            (len(ti & set(tokens(candidates[j]["text"]))) / max(len(ti | set(tokens(candidates[j]["text"]))), 1))
            for j in chosen
        )

    while available and len(chosen) < top_k:
        scored = [
            (i, RERANK_LAMBDA * fine_scores[i] - (1 - RERANK_LAMBDA) * _div(i))
            for i in available
        ]
        next_i = max(scored, key=lambda x: x[1])[0]
        chosen.append(next_i)
        available.remove(next_i)

    out = []
    for rank, i in enumerate(chosen, 1):
        c = dict(candidates[i])
        c["rerank_score"] = round(fine_scores[i], 4)
        c["relevance_score"] = round(min(1.0, 0.6 * fine_scores[i] + 0.4 * float(c.get("relevance_score", 0))), 4)
        out.append(c)
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


def _citation(hit: dict) -> Citation:
    quote = re.sub(r"\s+", " ", hit["text"]).strip()[:180]
    return Citation(
        textbook_id=hit["textbook_id"],
        textbook=hit["textbook"],
        chapter=hit["chapter"],
        page=hit["page"],
        page_end=hit.get("page_end") or hit["page"],
        relevance_score=hit["relevance_score"],
        chunk_id=hit["chunk_id"],
        bbox=hit.get("bbox") or [],
        block_ids=hit.get("block_ids") or [],
        quote=quote,
        source_url=hit.get("source_url") or "",
        retrieval_mode=hit.get("retrieval_mode") or "hybrid",
    )


def _extractive_answer(hits: list[dict]) -> str:
    lines = ["（模型额度不足或暂不可用，已自动切换为本地检索摘要）"]
    for i, hit in enumerate(hits[:3], 1):
        text = re.sub(r"\s+", " ", hit["text"]).strip()[:220]
        lines.append(f"[{i}] {text} ……《{hit['textbook']}》{hit['chapter']} 第 {hit['page']} 页")
    return "\n".join(lines)


def _format_history(history: list[dict] | None, max_turns: int = 4) -> str:
    """取最近 max_turns 轮对话拼接为可读文本。"""
    if not history:
        return ""
    role_map = {"user": "用户", "assistant": "助手"}
    cleaned: list[str] = []
    for msg in history[-max_turns:]:
        role = role_map.get(str(msg.get("role", "")).lower(), "用户")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        cleaned.append(f"{role}：{content[:300]}")
    return "\n".join(cleaned)


def query(question: str, top_k: int = 5, search_mode: str = "hybrid",
          history: list[dict] | None = None):
    hits = retrieve(question, top_k=top_k, search_mode=search_mode)
    citations = [_citation(hit) for hit in hits]
    source_chunks = [hit["text"] for hit in hits]

    if not hits:
        return "当前知识库中未找到相关信息。", citations, source_chunks

    if not llm_available("judge"):
        return _extractive_answer(hits), citations, source_chunks

    context = "\n\n".join(
        f"[{i+1}] 《{hit['textbook']}》· {hit['chapter']} · 第 {hit['page']} 页"
        f" · 检索={hit.get('retrieval_mode', 'hybrid')}\n{hit['text']}"
        for i, hit in enumerate(hits)
    )
    prompt = ANSWER_TEMPLATE.format(context=context[:6000], question=question)

    history_block = _format_history(history)
    if history_block:
        prompt = (
            "以下是最近的对话历史，仅作上下文参考，仍以参考资料为准：\n"
            f"{history_block}\n\n" + prompt
        )

    try:
        answer = chat(prompt, system=ANSWER_SYSTEM, role="judge",
                      temperature=0.2, max_tokens=500)
        # 质量兜底：若 LLM 返回过短/无意义，降级为检索摘要
        if not answer or len(answer.strip()) < 10:
            print(f"[rag] answer too short ({len(answer.strip()) if answer else 0} chars), fallback to extractive")
            answer = _extractive_answer(hits)
    except Exception as e:
        print(f"[rag] generation fallback: {e}")
        answer = _extractive_answer(hits)
    return answer, citations, source_chunks
