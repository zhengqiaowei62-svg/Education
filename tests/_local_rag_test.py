"""Test RAG pipeline with extractive fallback (no LLM dependency)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override LLM to simulate unavailable/garbage responses
os.environ["JUDGE_API_KEY"] = ""  # Make LLM unavailable for this test

from backend.core.rag_pipeline import query, build_index
from backend.core.parser import parse
from backend.storage import state

# Reset state
state.TEXTBOOKS.clear()
state.CHUNKS.clear()
state.CHUNK_BY_ID.clear()

# Parse test file
data = open("tests/sample_neuro.md", "rb").read()
tb = parse(data, "md", "neuro.md", "test_001")
state.TEXTBOOKS["test_001"] = tb

# Build index
n_books, n_chunks = build_index(["test_001"])
print(f"✓ Index built: {n_books} book(s), {n_chunks} chunk(s)")
assert n_chunks > 0, "No chunks generated!"

# Test query (should use extractive fallback since LLM unavailable)
answer, citations, source_chunks = query("什么是突触传递？")
print(f"✓ Answer ({len(answer)} chars): {answer[:200]}")
print(f"✓ Citations: {len(citations)}")
assert len(answer) > 20, f"Answer too short: {answer}"
assert "突触" in answer, "Answer doesn't contain expected content"
assert len(citations) > 0, "No citations returned"

# Test another query
answer2, cit2, _ = query("动作电位的机制是什么？")
print(f"✓ Answer2 ({len(answer2)} chars): {answer2[:200]}")
assert "动作电位" in answer2 or "去极化" in answer2, f"Answer doesn't match: {answer2[:100]}"

print("\n=== ALL LOCAL TESTS PASSED ===")
