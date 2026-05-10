"""快速烟雾测试：直接验证 Stage 2/3 改动（BGE 嵌入 + 多轮历史），跳过 LLM 抽取。"""
import sys, time, traceback
from backend.core import rag_pipeline as rp
from backend.storage import state
from backend.models.schemas import RagQueryRequest


def banner(s): print(f"\n{'=' * 6} {s} {'=' * 6}")


def main():
    # 1. schema/state
    banner("schema & state")
    req = RagQueryRequest(question="x", history=[{"role": "user", "content": "hi"}])
    assert req.history and req.history[0]["content"] == "hi"
    assert hasattr(state, "CHUNK_VECS")
    print("OK history field + CHUNK_VECS attr")

    # 2. _format_history
    banner("_format_history")
    hist = [
        {"role": "user", "content": "什么是动作电位？"},
        {"role": "assistant", "content": "动作电位是可兴奋细胞的快速跨膜电位变化。"},
        {"role": "user", "content": "它和静息电位什么关系？"},
    ]
    out = rp._format_history(hist)
    print(out)
    assert "用户：" in out and "助手：" in out

    # 3. 手动注入 chunks，测 _encode + _semantic（BGE 路径或哈希回退路径）
    banner("BGE encode / semantic")
    state.CHUNKS = [
        {"chunk_id": "c1", "text": "动作电位是神经元受刺激后产生的快速可逆跨膜电位变化。",
         "textbook_id": "tb1", "textbook": "生理学", "chapter_id": "ch1",
         "chapter": "神经元", "page": 1, "page_end": 1, "bbox": [], "block_ids": [],
         "vector_tags": [], "vector": rp._hash_embedding("动作电位"), "source_url": ""},
        {"chunk_id": "c2", "text": "静息电位是细胞未受刺激时膜内外的电位差。",
         "textbook_id": "tb1", "textbook": "生理学", "chapter_id": "ch1",
         "chapter": "神经元", "page": 1, "page_end": 1, "bbox": [], "block_ids": [],
         "vector_tags": [], "vector": rp._hash_embedding("静息电位"), "source_url": ""},
        {"chunk_id": "c3", "text": "线粒体是细胞的能量工厂。",
         "textbook_id": "tb2", "textbook": "组织学", "chapter_id": "ch1",
         "chapter": "细胞器", "page": 5, "page_end": 5, "bbox": [], "block_ids": [],
         "vector_tags": [], "vector": rp._hash_embedding("线粒体"), "source_url": ""},
    ]
    state.CHUNK_BY_ID = {c["chunk_id"]: c for c in state.CHUNKS}
    t0 = time.time()
    try:
        vecs = rp._encode([c["text"] for c in state.CHUNKS])
        state.CHUNK_VECS = vecs
        print(f"_encode shape={vecs.shape} dtype={vecs.dtype} took {time.time()-t0:.2f}s")
    except Exception as e:
        print(f"[warn] _encode 失败（将用哈希回退）：{e}")
        state.CHUNK_VECS = None

    sem = rp._semantic("动作电位的定义")
    print("semantic top hits:")
    for score, chunk in sem[:3]:
        print(f"  {chunk['chunk_id']}  score={score:.4f}  text={chunk['text'][:30]}…")
    assert sem and sem[0][1]["chunk_id"] == "c1", "语义检索应排名 c1 第一"

    print("\n[OK] Stage 2/3 烟雾测试全部通过")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
