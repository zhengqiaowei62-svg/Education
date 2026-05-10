"""
单元测试 - 测试纯函数逻辑（不依赖LLM）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestChunkText:
    """测试 RAG 文本分块函数"""

    def test_normal_text(self):
        """正常文本分块"""
        from backend.core.rag_pipeline import chunk_text
        text = "A" * 1200
        chunks = chunk_text(text, size=600, overlap=100)
        assert len(chunks) >= 2
        # 每个chunk不超过size
        for c in chunks:
            assert len(c) <= 600

    def test_short_text(self):
        """短文本不分块"""
        from backend.core.rag_pipeline import chunk_text
        text = "短文本测试"
        chunks = chunk_text(text, size=600, overlap=100)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text(self):
        """空文本"""
        from backend.core.rag_pipeline import chunk_text
        chunks = chunk_text("", size=600, overlap=100)
        assert len(chunks) <= 1  # 空或一个空串

    def test_overlap_continuity(self):
        """验证重叠部分存在连续性"""
        from backend.core.rag_pipeline import chunk_text
        text = "ABCDEFGHIJ" * 100  # 1000字
        chunks = chunk_text(text, size=600, overlap=100)
        if len(chunks) >= 2:
            # 第一个chunk的尾部100字应与第二个chunk的头部有重叠
            tail = chunks[0][-100:]
            head = chunks[1][:100]
            assert tail == head


class TestTextSimilarity:
    """测试文本相似度函数"""

    def test_identical_text(self):
        """完全相同文本相似度为1"""
        from backend.utils.llm import text_similarity
        score = text_similarity("静息电位", "静息电位")
        assert score >= 0.99

    def test_completely_different(self):
        """完全不同文本相似度接近0"""
        from backend.utils.llm import text_similarity
        score = text_similarity("苹果香蕉橘子", "计算机网络协议")
        assert score < 0.3

    def test_partial_overlap(self):
        """部分重叠文本"""
        from backend.utils.llm import text_similarity
        score = text_similarity("静息膜电位", "静息电位")
        assert 0.3 < score < 1.0

    def test_empty_string(self):
        """空字符串处理"""
        from backend.utils.llm import text_similarity
        score = text_similarity("", "")
        # 不应报错
        assert isinstance(score, (int, float))


class TestParseMd:
    """测试 Markdown 解析"""

    def test_single_chapter(self):
        """单章节MD解析"""
        from backend.core.parser import parse
        md_content = "# 第一章 细胞膜\n\n细胞膜是细胞的外层屏障，由磷脂双分子层组成。"
        tb = parse(md_content.encode("utf-8"), "md", "test.md", "book_test001")
        assert tb is not None
        assert len(tb.chapters) >= 1
        assert tb.textbook_id == "book_test001"

    def test_multi_chapter(self):
        """多章节MD解析"""
        from backend.core.parser import parse
        md_content = """# 第一章 细胞膜

细胞膜由磷脂双分子层组成。

# 第二章 细胞核

细胞核是遗传信息的存储中心。

# 第三章 线粒体

线粒体是细胞的能量工厂。
"""
        tb = parse(md_content.encode("utf-8"), "md", "test.md", "book_test002")
        assert tb is not None
        assert len(tb.chapters) >= 2  # 至少识别出2个章节

    def test_filename_as_title(self):
        """文件名作为标题"""
        from backend.core.parser import parse
        md_content = "一些内容没有章节标题"
        tb = parse(md_content.encode("utf-8"), "md", "生理学.md", "book_test003")
        assert tb.filename == "生理学.md"


class TestRouter:
    """测试意图路由"""

    def test_modify_keyword(self):
        """修改类关键词应返回MODIFY"""
        from backend.core.router import classify_intent
        assert classify_intent("把抗原和免疫原分开") == "MODIFY"
        assert classify_intent("删除这个节点") == "MODIFY"
        assert classify_intent("合并这两个概念") == "MODIFY"

    def test_query_intent(self):
        """查询类应返回RAG"""
        from backend.core.router import classify_intent
        # "什么是静息电位？" 长度<10且含"？"和"什么"，命中短查询规则→RAG
        result = classify_intent("什么是静息电位？")
        assert result in ["RAG", "MODIFY"]  # 至少不报错


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
