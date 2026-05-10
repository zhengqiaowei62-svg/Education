# Agent 架构说明

## a) 架构总览

本系统采用 **单 Agent + 多工具（Tool-using Agent）** 的架构：核心由一个 Orchestrator
负责对用户意图进行路由，并调用一组确定性工具（解析、抽取、对齐、检索）来完成
任务。LLM 仅在"知识抽取"、"等价判定"、"答案生成"三个**真正需要语义理解**的环节被
调用，其余流程使用纯代码以降低 Token 消耗与不确定性。

```mermaid
graph TD
    User[用户] --> Orchestrator[Orchestrator Agent]
    Orchestrator -->|tool: parse| Parser
    Orchestrator -->|tool: extract| Extractor[KG Extractor · LLM]
    Orchestrator -->|tool: align| Aligner[KG Aligner · Embedding+LLM]
    Orchestrator -->|tool: rag| RAG[RAG Pipeline · LLM]
    Orchestrator --> User
```

## b) 设计决策论证

**为什么单 Agent 而非多 Agent？**
- 5 小时极速开发，多 Agent 调度成本（消息总线、状态同步、错误传播）超过其收益。
- 各步骤之间是"明确的流水线"而非"开放式协作"，确定性流程比 Agent 自由编排更稳。
- LLM 调用集中收敛在三个工具内，prompt 复杂度可控，每个 prompt < 2k tokens。

**Prompt 复杂度管理**：
- 按章节切分调用，单次上下文 ≤ 4k 字符。
- 强制 JSON schema + few-shot，使用 `chat_json` 解析失败时降级为空结果。

## c) 数据流与调用链路

见 `docs/系统设计.md`，此处不重复。

## d) 取舍与权衡

- 放弃多 Agent 协作（LangGraph）：节省搭建时间，把工时投入对齐算法与 RAG 评测。
- 放弃 BM25+Rerank（默认）：作为 P1 加分项实现，基线先用纯向量。
- 已知局限：
  - PDF 章节识别仅基于正则，扫描版 PDF 会失败（未来：OCR 兜底）。
  - 对齐阈值固定 0.85，未做学科自适应（未来：构建标注集做阈值搜索）。

## 创新点（占位，待补充）

- TODO: 整合决策的可解释性面板
- TODO: 教学连贯性自动检查（依赖断链探测）
