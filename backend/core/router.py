"""
Router Agent - 轻量级意图路由器
职责：判断用户输入是「知识查询(RAG)」还是「图谱修改(MODIFY)」
设计：规则预判 + LLM兜底，确保快速响应
"""
from typing import Literal

from backend.utils import llm

# 修改类关键词（命中则直接返回MODIFY，无需LLM）
MODIFY_KEYWORDS = [
    "修改", "删除", "移除", "合并", "拆分", "更名", "重命名",
    "添加", "新增", "调整", "更新", "去掉", "分开", "改成",
    "把…改为", "不应该", "应该是", "有误", "错误", "纠正"
]

ROUTER_SYSTEM = """你是意图分类器。判断用户输入的意图类别。
仅输出一个词：RAG 或 MODIFY
- RAG：用户在查询知识、提问题、想了解某个概念
- MODIFY：用户想修改/调整/纠正知识图谱中的内容
只输出 RAG 或 MODIFY，不要输出任何其他内容。"""


def classify_intent(user_input: str) -> Literal["RAG", "MODIFY"]:
    """
    意图分类：
    1. 规则预判：检查修改类关键词
    2. LLM兜底：不确定时调用模型判断
    """
    # 规则预判
    text = user_input.strip()
    for kw in MODIFY_KEYWORDS:
        if kw in text:
            print(f"[Router] 规则命中关键词 '{kw}' → MODIFY")
            return "MODIFY"

    # 短查询大概率是RAG
    if len(text) < 10 and ("?" in text or "？" in text or "什么" in text or "如何" in text):
        print(f"[Router] 短查询规则 → RAG")
        return "RAG"

    # LLM判断
    try:
        result = llm.chat(
            prompt=text[:200],  # 截断，节省token
            system=ROUTER_SYSTEM,
            role="extractor",
            max_tokens=10,
            temperature=0.0,
        )
        if result:
            result = result.strip().upper()
            if "MODIFY" in result:
                print(f"[Router] LLM判定 → MODIFY")
                return "MODIFY"
        print(f"[Router] LLM判定 → RAG")
        return "RAG"
    except Exception as e:
        print(f"[Router] LLM调用失败，默认RAG: {e}")
        return "RAG"
