"""Full chain test - upload, extract, RAG, chat."""
import requests, time, sys

BASE = "http://localhost:8000"

def test_upload():
    print("\n=== A) Upload ===")
    with open("tests/sample_neuro.md", "rb") as f:
        r = requests.post(f"{BASE}/api/upload", files={"files": ("neuro.md", f)})
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Result: {data}")
    assert r.status_code == 200
    assert data["files"][0]["status"] == "done"
    return data["files"][0]["textbook_id"]

def test_textbooks():
    print("\n=== B) List Textbooks ===")
    r = requests.get(f"{BASE}/api/textbooks")
    print(f"  Status: {r.status_code}")
    data = r.json()
    print(f"  Count: {len(data)}")
    assert r.status_code == 200
    return data

def test_extract(tid):
    print(f"\n=== C) Extract Graph (tid={tid}) ===")
    r = requests.post(f"{BASE}/api/graph/extract", json={"textbook_id": tid}, timeout=300)
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        nodes = data.get("graph", {}).get("nodes", [])
        edges = data.get("graph", {}).get("edges", [])
        print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}")
        if nodes:
            print(f"  Sample node: {nodes[0].get('name', '?')}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code

def test_rag_index(tid):
    print(f"\n=== D) RAG Build Index (tid={tid}) ===")
    r = requests.post(f"{BASE}/api/rag/index", json={"textbook_ids": [tid]})
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        print(f"  Indexed: {data}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code, r.json() if r.ok else {}

def test_rag_query():
    print("\n=== E) RAG Query ===")
    r = requests.post(f"{BASE}/api/rag/query", json={"question": "什么是突触传递？"}, timeout=300)
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        print(f"  Answer: {str(data.get('answer', ''))[:200]}")
        print(f"  Citations: {len(data.get('citations', []))}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code

def test_chat_rag():
    print("\n=== F) Chat (RAG intent) ===")
    r = requests.post(f"{BASE}/api/chat", json={"message": "什么是动作电位？"}, timeout=300)
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        print(f"  Intent: {data.get('intent')}")
        print(f"  Answer: {str(data.get('answer', ''))[:200]}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code

def test_chat_modify():
    print("\n=== G) Chat (MODIFY intent) ===")
    r = requests.post(f"{BASE}/api/chat", json={"message": "把突触传递重命名为突触信号传导"}, timeout=300)
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        print(f"  Intent: {data.get('intent')}")
        print(f"  Answer: {str(data.get('answer', ''))[:200]}")
        print(f"  Modification: {data.get('modification')}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code

def test_merge(tid):
    print(f"\n=== H) Graph Merge (tid={tid}) ===")
    r = requests.post(f"{BASE}/api/graph/merge", json={"textbook_ids": [tid]}, timeout=300)
    print(f"  Status: {r.status_code}")
    if r.ok:
        data = r.json()
        mg = data.get("merged_graph", {})
        print(f"  Merged nodes: {len(mg.get('nodes', []))}")
        print(f"  Decisions: {len(data.get('decisions', []))}")
    else:
        print(f"  Error: {r.text[:300]}")
    return r.status_code

if __name__ == "__main__":
    # Test health first
    r = requests.get(f"{BASE}/api/health")
    assert r.status_code == 200, "Backend not running!"
    
    tid = test_upload()
    test_textbooks()
    
    # Test RAG index (doesn't need LLM)
    status, data = test_rag_index(tid)
    assert status == 200, f"RAG index failed: {status}"
    
    # Test RAG query (may use LLM or fallback)
    test_rag_query()
    
    # Test Chat RAG
    test_chat_rag()
    
    # Test extract (needs LLM)
    test_extract(tid)
    
    # Test Chat Modify
    test_chat_modify()
    
    # Test merge
    test_merge(tid)
    
    print("\n\n=== ALL TESTS COMPLETED ===")
