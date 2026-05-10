"""单次抽取拨号验证。"""
import time, json
from backend.utils.llm import chat_json

prompt = """请把下面这段教材抽成 2 个核心知识点 + 1 条关系，仅输出 JSON。

【schema】{"nodes":[{"id":"n1","name":"...","definition":"...","category":"核心概念","page":1}],"edges":[{"source":"n1","target":"n2","relation_type":"prerequisite","description":"..."}]}

【正文】静息电位是细胞静息时膜内外的电位差，约 -70 毫伏。动作电位是细胞受刺激后膜电位的快速倒转，理解动作电位需先掌握静息电位。"""

sys = "只输出合法 JSON 对象，禁止解释或 <think> 思考链。"
t = time.time()
r = chat_json(prompt, system=sys, role="extractor",
              max_tokens=800, temperature=0.1,
              default={"nodes": [], "edges": []})
print(f"{time.time()-t:.1f}s |", json.dumps(r, ensure_ascii=False, indent=2))
