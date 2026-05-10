"""端到端 API 烟雾测试：
upload → extract(A) → merge(B) → rag/index → rag/query
"""
import sys, json, time, pathlib
import httpx

BASE = "http://127.0.0.1:8000"
ROOT = pathlib.Path(__file__).resolve().parent
SAMPLES = [ROOT / "sample_neuro.md", ROOT / "sample_physio.md"]


def step(name):
    print(f"\n{'=' * 8} {name} {'=' * 8}")


def main():
    with httpx.Client(timeout=600) as cli:
        step("健康检查")
        r = cli.get(f"{BASE}/api/health")
        print(r.status_code, r.json())
        assert r.status_code == 200

        step("上传两本教材")
        files = [("files", (p.name, p.read_bytes(), "text/markdown")) for p in SAMPLES]
        r = cli.post(f"{BASE}/api/upload", files=files)
        print(r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2)[:600])
        assert r.status_code == 200
        ids = [tb["textbook_id"] for tb in r.json().get("files", []) if tb.get("textbook_id")]
        assert ids, "未返回 textbook id"
        print(f"→ ids = {ids}")

        step("Agent A · 单本抽取（第一本）")
        t0 = time.time()
        r = cli.post(f"{BASE}/api/graph/extract", json={"textbook_id": ids[0]})
        print(f"耗时 {time.time()-t0:.1f}s, status={r.status_code}")
        data = r.json()
        print(f"nodes={len(data.get('nodes', []))} edges={len(data.get('edges', []))}")
        if data.get("nodes"):
            print("示例节点:", json.dumps(data["nodes"][:3], ensure_ascii=False))

        step("Agent B · 跨教材融合（自动补抽其余）")
        t0 = time.time()
        r = cli.post(f"{BASE}/api/graph/merge", json={"textbook_ids": ids})
        print(f"耗时 {time.time()-t0:.1f}s, status={r.status_code}")
        m = r.json()
        print("stats:", m.get("stats"))
        print(f"merged nodes={len(m.get('graph', {}).get('nodes', []))}, "
              f"edges={len(m.get('graph', {}).get('edges', []))}")
        if m.get("decisions"):
            print(f"决策 {len(m['decisions'])} 条，前 3 条:")
            for d in m["decisions"][:3]:
                print("  ", json.dumps(d, ensure_ascii=False))

        step("RAG · 建立索引")
        r = cli.post(f"{BASE}/api/rag/index", json={"textbook_ids": ids})
        print(r.status_code, r.json())

        step("RAG · 提问")
        q = "动作电位和静息电位的关系是什么？"
        r = cli.post(f"{BASE}/api/rag/query", json={"question": q, "top_k": 3})
        print(r.status_code)
        ans = r.json()
        print("answer:", (ans.get("answer") or "")[:400])
        print("citations:", json.dumps(ans.get("citations", [])[:3], ensure_ascii=False))

    print("\n[OK] 端到端流程完成")


if __name__ == "__main__":
    sys.exit(main() or 0)
