"""命令行 RAG 基准评测工具。

用法：
    # 1. 启动后端并建好索引（上传若干教材后调用 /api/rag/index）
    # 2. 运行：
    python tests/rag_benchmark.py
    python tests/rag_benchmark.py --base http://127.0.0.1:8000 --out report/rag_benchmark.json

支持自定义评测集：在 tests/rag_benchmark.json 中提供
    [{"q": "...", "must_contain": ["关键词1", "关键词2"]}, ...]
否则使用 backend/api/stats.py 中的 DEFAULT_BENCH。

输出：
    控制台彩色摘要 + JSON 详细结果（默认 report/rag_benchmark.json）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG benchmark runner")
    parser.add_argument("--base", default="http://127.0.0.1:8000",
                        help="后端基址（默认 http://127.0.0.1:8000）")
    parser.add_argument("--out", default="report/rag_benchmark.json",
                        help="结果 JSON 输出路径")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    url = args.base.rstrip("/") + "/api/stats/benchmark"
    print(f"[bench] POST {url}")
    t0 = time.time()
    try:
        resp = httpx.post(url, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[bench] 请求失败：{exc}")
        return 2
    if resp.status_code != 200:
        print(f"[bench] HTTP {resp.status_code}: {resp.text[:200]}")
        return 3
    data = resp.json()
    if data.get("status") == "error":
        print(f"[bench] 服务端报错：{data.get('message')}")
        return 4

    # 摘要
    print()
    print("=" * 60)
    print(f"  样本数      : {data.get('total_cases')}")
    print(f"  命中数      : {data.get('hit')}")
    print(f"  命中率      : {(data.get('hit_rate', 0)*100):.1f}%")
    print(f"  服务端耗时  : {data.get('elapsed_ms')} ms")
    print(f"  本地总耗时  : {round((time.time()-t0)*1000,1)} ms")
    print("=" * 60)
    rows = data.get("rows") or []
    for r in rows:
        flag = "✓" if r.get("match") else "✗"
        print(f"  [{flag}] {r['question'][:30]:30s}  top1={r.get('top1_chunk')}  "
              f"score={r.get('top1_score')}  rerank={r.get('rerank_score')}  "
              f"{r.get('latency_ms')} ms")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[bench] 结果已写入 {out}")

    # 退出码：命中率 < 0.5 视为失败（CI 友好）
    return 0 if (data.get("hit_rate", 0) >= 0.5) else 1


if __name__ == "__main__":
    sys.exit(main())
