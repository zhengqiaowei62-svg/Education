"""HTTP 烟雾：upload → extract（仅一本，加速）→ rag/index → 带 history 的 query。
依赖后端在 127.0.0.1:8000 运行。"""
import json, time, sys, pathlib
import httpx

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(__file__).resolve().parent
SAMPLE = ROOT / "sample_neuro.md"


def main():
    with httpx.Client(timeout=600) as cli:
        print("== /api/health ==")
        print(cli.get(f"{BASE}/api/health").json())

        print("== /api/upload ==")
        r = cli.post(
            f"{BASE}/api/upload",
            files=[("files", (SAMPLE.name, SAMPLE.read_bytes(), "text/markdown"))],
        )
        print(r.status_code, json.dumps(r.json(), ensure_ascii=False)[:300])
        tid = r.json()["files"][0]["textbook_id"]

        print("== /api/graph/extract ==")
        t0 = time.time()
        r = cli.post(f"{BASE}/api/graph/extract", json={"textbook_id": tid})
        print(f"{r.status_code}  耗时 {time.time()-t0:.1f}s  "
              f"nodes={len(r.json().get('nodes', []))} edges={len(r.json().get('edges', []))}")

        print("== /api/rag/index ==")
        r = cli.post(f"{BASE}/api/rag/index", json={"textbook_ids": [tid]})
        print(r.status_code, r.json())

        print("== /api/rag/query (无 history) ==")
        r = cli.post(f"{BASE}/api/rag/query",
                     json={"question": "什么是动作电位？", "top_k": 3})
        ans = r.json()
        print(r.status_code, "answer:", (ans.get("answer") or "")[:200])
        print("citations:", len(ans.get("citations", [])))

        print("== /api/rag/query (带 history) ==")
        r = cli.post(f"{BASE}/api/rag/query", json={
            "question": "那它和静息电位是什么关系？",
            "top_k": 3,
            "history": [
                {"role": "user", "content": "什么是动作电位？"},
                {"role": "assistant", "content": "动作电位是可兴奋细胞受刺激后的快速跨膜电位变化。"},
            ],
        })
        ans = r.json()
        print(r.status_code, "answer:", (ans.get("answer") or "")[:300])

    print("\n[OK] HTTP 烟雾通过")


if __name__ == "__main__":
    sys.exit(main() or 0)
