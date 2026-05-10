"""统计与导出端点：Token 消耗、整合报告下载、迷你 RAG 基准。"""
from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, FileResponse, JSONResponse

from backend.utils import llm
from backend.storage import state
from backend.core import rag_pipeline

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]


@router.get("/stats/tokens")
def stats_tokens():
    """LLM token 消耗（按角色 / 总计）。供前端图表读取。"""
    return llm.get_token_usage()


@router.post("/stats/tokens/reset")
def stats_tokens_reset():
    llm.reset_token_usage()
    return {"status": "ok"}


@router.get("/stats/graph")
def stats_graph():
    """图谱当前规模 + 教材覆盖。"""
    g = state.MERGED_GRAPH
    n_books = len(state.TEXTBOOKS)
    n_extracted = len(state.GRAPHS)
    by_cat: dict[str, int] = {}
    for n in g.nodes:
        by_cat[n.category] = by_cat.get(n.category, 0) + 1
    by_rel: dict[str, int] = {}
    for e in g.edges:
        by_rel[e.relation_type] = by_rel.get(e.relation_type, 0) + 1
    return {
        "books_uploaded": n_books,
        "books_extracted": n_extracted,
        "merged_nodes": len(g.nodes),
        "merged_edges": len(g.edges),
        "by_category": by_cat,
        "by_relation": by_rel,
        "modifications": len(state.MODIFICATIONS),
        "indexed_chunks": len(state.CHUNKS),
    }


# -------- 整合报告导出（Markdown / 简易 PDF） --------

REPORT_PATH = ROOT / "report" / "整合报告.md"


@router.get("/report/markdown", response_class=PlainTextResponse)
def report_markdown():
    if REPORT_PATH.is_file():
        return REPORT_PATH.read_text(encoding="utf-8")
    return "# 整合报告\n\n报告尚未生成。"


@router.get("/report/download")
def report_download():
    if REPORT_PATH.is_file():
        return FileResponse(
            REPORT_PATH,
            media_type="text/markdown; charset=utf-8",
            filename="整合报告.md",
        )
    return JSONResponse({"status": "error", "message": "report not generated"}, status_code=404)


@router.get("/report/pdf")
def report_pdf():
    """尝试将整合报告转为 PDF；失败时降级返回 Markdown 文件。
    依赖：pip install markdown weasyprint （weasyprint 在 Windows 上需要 GTK 运行时）
    """
    md_text = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.is_file() else "# 整合报告\n\n（未生成）"
    pdf_path = ROOT / "report" / "整合报告.pdf"
    try:
        import markdown as _md  # type: ignore
        from weasyprint import HTML  # type: ignore
        html_body = _md.markdown(md_text, extensions=["tables", "fenced_code"])
        html = (
            "<html><head><meta charset='utf-8'><style>"
            "body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;line-height:1.7;padding:24px;}"
            "table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:4px 8px;}"
            "code,pre{background:#f4f4f4;padding:2px 4px;border-radius:3px;}"
            "</style></head><body>" + html_body + "</body></html>"
        )
        HTML(string=html).write_pdf(str(pdf_path))
        return FileResponse(pdf_path, media_type="application/pdf", filename="整合报告.pdf")
    except Exception as exc:  # noqa: BLE001
        # 降级：返回 markdown 提示安装 weasyprint
        return JSONResponse(
            {
                "status": "fallback",
                "message": f"PDF 生成失败（{exc}），请使用 /api/report/download 下载 Markdown 版本。",
                "hint": "安装：pip install markdown weasyprint",
            },
            status_code=200,
        )


# -------- 迷你 RAG Benchmark --------

# 内置最小评测集；用户可在 tests/rag_benchmark.json 自定义覆盖。
DEFAULT_BENCH = [
    {"q": "动作电位的产生机制？",          "must_contain": ["动作电位"]},
    {"q": "静息电位由什么决定？",          "must_contain": ["静息电位"]},
    {"q": "突触传递的基本过程？",          "must_contain": ["突触"]},
]


def _load_benchmark() -> list[dict]:
    p = ROOT / "tests" / "rag_benchmark.json"
    if p.is_file():
        try:
            import json
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_BENCH


@router.post("/stats/benchmark")
def run_benchmark():
    """对当前 RAG 索引跑一遍最小评测；返回命中率/平均分/耗时。"""
    cases = _load_benchmark()
    if not state.CHUNKS:
        return {"status": "error", "message": "RAG 索引为空，请先 /api/rag/index"}
    import time
    t0 = time.time()
    rows = []
    hit = 0
    for c in cases:
        ts = time.time()
        hits = rag_pipeline.retrieve(c["q"], top_k=3)
        dt = time.time() - ts
        text = " ".join(h["text"] for h in hits)
        ok = all(k in text for k in c.get("must_contain", []))
        if ok:
            hit += 1
        rows.append({
            "question": c["q"],
            "top1_chunk": hits[0]["chunk_id"] if hits else None,
            "top1_score": hits[0].get("relevance_score") if hits else 0,
            "rerank_score": hits[0].get("rerank_score") if hits else 0,
            "match": ok,
            "latency_ms": round(dt * 1000, 1),
            "n_hits": len(hits),
        })
    return {
        "total_cases": len(cases),
        "hit": hit,
        "hit_rate": round(hit / max(len(cases), 1), 3),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "rows": rows,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
