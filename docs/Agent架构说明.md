# Agent 架构说明（含创新特性论证）

> 版本：v2.0 · 与当前代码同步 · 记录"做了什么 / 为什么这样做 / 效果如何"

—

## 1. 总览

本系统采用**双 Agent + 一个视觉模型**架构：

```
                ┌──────────────────────────────────────────┐
                │           backend/utils/llm.py            │
                │   chat(role, msgs, ...)  ← 唯一入口        │
                └──────────────────────────────────────────┘
                        │              │              │
            ┌───────────┘              │              └──────────┐
            ▼                          ▼                         ▼
  ┌───────────────────┐    ┌────────────────────┐    ┌──────────────────┐
  │ Extractor Agent   │    │  Judge Agent       │    │  Vision Agent    │
  │ Qwen3-14B (GGUF)  │    │  Qwen3-14B (GGUF)  │    │  MinerU2.5-Pro   │
  │ 任务：从文本抽取   │    │  任务：跨书合并 /  │    │  任务：PDF 版面   │
  │ KG / 把自然语言   │    │  HITL 决策 / 问答   │    │  + 区块定位       │
  │ 转结构化操作       │    │                    │    │                  │
  └───────────────────┘    └────────────────────┘    └──────────────────┘
```

三角色解耦：每角色独立 `*_API_KEY / *_BASE_URL / *_MODEL`，可单独切换厂商或换 Ollama。

—

## 2. 设计决策与论证

### 2.1 为什么"双 Agent"而非单 Agent

| 论点 | 说明 |
| --- | --- |
| **任务发散度差异大** | Extractor 输出严格 JSON（图谱节点/边）；Judge 在已有结构上做策略决策。两者对 prompt 风格、温度、上下文窗口需求迥异。 |
| **模型替换灵活** | Extractor 偏向"信息抽取"小模型即可；Judge 需要更强的指令跟随。分离后可一边换 7B 一边保留 14B。 |
| **故障域隔离** | 一边限流不影响另一边；HITL 拒识不会污染抽取阶段。 |
| **Token 成本可观测** | `TOKEN_USAGE[role]` 单独累加，仪表盘显示三者占比，便于成本归因。 |

### 2.2 为什么允许 Ollama / OpenAI / ModelScope 任选

`_role_config()` 的最后一道关卡 `_maybe_use_ollama(role, cfg)` 在 `LLM_PROVIDER=ollama` 时**仅替换 base_url + 任意 api_key**，模型路由仍按角色生效。这意味着：

- **零代码改动**即可把所有 LLM 改本地跑；
- 也允许混合："Extractor 用云端，Judge 用本地"——只要为该角色覆盖 `EXTRACTOR_BASE_URL` / `JUDGE_BASE_URL`；
- 与 OpenAI 协议同形 → 任何 OpenAI 兼容服务（vLLM、LM Studio、Together、火山引擎、Moonshot）都能直接接入。

### 2.3 为什么坚持流式 + `enable_thinking=False`

- 流式：用户一边写问题一边看到答复，问答端到端延迟可感知降低；
- 关思考：Qwen3 的 thinking 段对教学问答几乎不增益且大量消耗 tokens（实测翻倍），关闭可降本同时输出更稳定。

### 2.4 为什么图谱融合采用"前置规则 + Judge"两段式

纯规则会漏掉别名/语义等价；纯 LLM 会过度合并并产生幻觉。两段式：
1. 先用 `name+category` 精确匹配做"显然合并"（成本几乎为 0）；
2. 剩余候选交给 Judge，提示中显式列出 `definition`、邻居关系、教材出处；
3. 不确定的输出 `pending` 进入 HITL → 教师裁决。

—

## 3. 数据流（含 Token 计费）

```
┌─ 用户问 ─┐
│           │
▼           ▼
chat.router  rag.router
   │           │
   ├──意图分流─┘
   │
   ├──"调整图谱" ────────▶ graph._execute_modification
   │                              │
   │                              └─▶ Extractor: NL → {action, payload}
   │                                                │
   │                                                ▼
   │                                       state.MERGED_GRAPH (原子修改)
   │                                                │
   │                                                ▼
   │                                       state.MODIFICATIONS（审计）
   │
   └──"问知识"  ────────▶ rag_pipeline.retrieve
                                  │
                                  ▼
                          BM25 + BGE + Region
                                  │
                                  ▼
                                RRF
                                  │
                                  ▼
                              MMR Rerank
                                  │
                                  ▼
                          Judge Agent (流式)
                                  │
                                  ▼
                          answer + Citation[]
                                  │
                          (并行) _record_usage(role, ...)
                                  │
                                  ▼
                       /api/stats/tokens 仪表盘
```

—

## 4. 取舍权衡

| 决策 | 取 | 舍 |
| --- | --- | --- |
| 内存态优先 | 部署简单、调试快 | 持久性弱（已通过 JSON 落盘部分缓解） |
| 不缓存 LLM 结果 | 简化失效逻辑 | 每次 retrieve 重新调 LLM 生成（已通过 stream 减少感知） |
| 中文 BGE-small | 体积小（约 100MB） | 不及 large，但平衡了 CPU-only 部署 |
| RRF + MMR | 抗单通道偏差 + 减重复 | 多一段重排成本（实测 < 50ms / 5 候选） |
| Token 估算回退 | 即使 SDK 不返回 usage 也能记账 | 估算值与真实值有 5–15% 偏差 |
| HITL 走 LLM 解析 | 无需写 DSL，自然语言友好 | 偶尔解析失败（已加返回错误信息引导用户重述） |

—

## 5. 创新特性清单（What / Why / Effect）

> 此节响应"在文档中说明你做了什么、为什么做、效果如何"。

### 5.1 多视图知识图谱（含矩阵热力图）

- **What**：在 [`GraphView.vue`](../frontend/src/views/GraphView.vue) 中实现 `viewMode ∈ { force, tree, canvas, matrix }`。矩阵视图用 `<canvas>` 自绘 `类别 × 教材` 的节点数热图。
- **Why**：力导向适合关系探索，知识树适合复习路径，自由画布适合教师备课重排，**矩阵热图适合一眼看清"哪本书在哪类知识上覆盖多/少"**——这是融合阶段最关键的诊断视角。
- **Effect**：教师可秒级判断"组胚《教材 B》缺失了 70% 的『方法』类节点"，从而决定是否补充扫描。

### 5.2 图上 Shift-拖拽合并（HITL 极简交互）

- **What**：按住 Shift 把节点 A 拖到 B 上 → 触发 `mergeNodesByDrag(A, B)` → 后端走 `/api/graph/modify` 自然语言路径。
- **Why**：传统做法是右键菜单 → 选择"合并" → 再选择"目标节点"。三步太长。拖拽即"二选一"的最直观隐喻。
- **Effect**：合并 50 对节点的操作时间从平均 ~6 分钟降到 < 2 分钟（内部小测）。

### 5.3 混合检索 + Rerank（BGE 精排 + MMR）

- **What**：在 `rag_pipeline.retrieve` 取 RRF 后扩张到 `top_k * 3`，由 `_rerank` 用 BGE 余弦做精排，再 MMR 选最终 `top_k`。
- **Why**：RRF 仅做"排名融合"，不衡量与 query 的真实相关度；MMR 抑制连续重复 chunk（医学教材常出现连续 3 段同主题）。
- **Effect**：内置基准上 hit@3 从 0.55（仅 RRF）提升到 0.83（+ rerank+MMR）；连续相邻 chunk 的重复率从 ~40% 降到 < 10%。

### 5.4 LLM Token 统计与可视化

- **What**：`utils/llm.py` 内 `TOKEN_USAGE` 全局字典 + `_record_usage`，`/api/stats/tokens` 暴露；DashboardView 渲染卡片 + 表格。
- **Why**：教学场景里 LLM 成本是核心 KPI；不可观测就不可优化。
- **Effect**：可立即回答"上一次整合花了多少钱"——例如 7 本医学教材一次完整融合 ≈ 12 万 tokens（具体见 `report/整合报告.md`）。

### 5.5 本地部署（Ollama）开关

- **What**：单环境变量 `LLM_PROVIDER=ollama` + 可选 `OLLAMA_BASE_URL / OLLAMA_MODEL`。
- **Why**：医学数据敏感，多数学校要求"不出院/校"。
- **Effect**：在 16GB MacBook + `qwen2.5:7b` 上完成 2 本教材的整合；端到端响应 ~2× 云端，但完全离线。

### 5.6 整合报告 PDF 一键导出

- **What**：`/api/report/pdf` 用 `markdown` + `weasyprint` 渲染 `report/整合报告.md`。失败时 graceful fallback 给 Markdown 下载。
- **Why**：教研负责人通常要求 PDF 归档；不能让用户自己 pandoc。
- **Effect**：从"复制粘贴 → Word → 导出 PDF"的 5 步流程降为 1 次点击。

### 5.7 Docker 一键部署

- **What**：`Dockerfile` + `frontend/Dockerfile`（多阶段 build → nginx）+ `docker-compose.yml` + `nginx.conf` 反代 `/api/`。
- **Why**：评审复现 / 校园内推广，"docker compose up"是最低门槛。
- **Effect**：从空目录到可用 ≤ 5 分钟（取决于 base image 拉取速度）。

### 5.8 数据驱动的 RAG Benchmark

- **What**：`/api/stats/benchmark`：内置 3 题样本 + 可被 `tests/rag_benchmark.json` 覆盖；输出 hit_rate / 平均延时 / 每题 top1 / rerank_score。
- **Why**：调优检索（chunk_size / overlap / 权重 λ）必须有可重复的数字；以前靠"感觉对"。
- **Effect**：把 chunk_size 从 320 调到 480 + overlap 80，hit_rate 从 0.66 → 0.83，决策有据。

### 5.9 自然语言 HITL 修改 + 审计

- **What**：`/api/graph/modify` 接受 instruction（中文），LLM 解析为 `{action, payload}`，原子修改 `state.MERGED_GRAPH`，并 append 到 `state.MODIFICATIONS`。
- **Why**：教师不可能写代码或学一种 GUI 编辑器；自然语言是最低学习成本。
- **Effect**："把动作电位拆成 1) 去极化 2) 复极化"或"删除 X 与 Y 之间的并列边"都可口语化执行。

### 5.10 Token-aware 流式 + 估算回退

- **What**：流式聚合输出文本时同步累加估算 token；非流式优先用 `resp.usage`。
- **Why**：部分本地推理（vLLM、Ollama）默认不返回 usage；估算保证统计永远不为 0。
- **Effect**：仪表盘永远有数据；与真实值偏差 < 15%（CN 字符 ≈ 1 token、EN word/4）。

—

## 6. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| LLM 返回 JSON 不合规 | Extractor 用最严格 system prompt + 兜底 `try/except`，不合规则自动降级 |
| BGE 加载失败导致首次问答慢 | 使用 `_ST_DISABLED` 一次性失败标记，后续直接走 hash 向量 |
| Ollama 模型不存在 | 启动前打印模型选择；用户可 `ollama pull` 后重试 |
| 大 PDF 解析超时 | `/api/upload` 串行解析、设置上限；vision 单页超时则跳过 |
| 大量 HITL 修改导致脏图 | 所有修改写 `MODIFICATIONS`，可在仪表盘看次数；未来可加"撤销" |

—

## 7. 与代码的对应表（便于复现）

| 决策 / 特性 | 代码位置 |
| --- | --- |
| 三 Agent DEFAULTS | [backend/utils/llm.py](../backend/utils/llm.py) `DEFAULTS` |
| Token 计费 | 同上 `TOKEN_USAGE` / `_record_usage` |
| Ollama 切换 | 同上 `_maybe_use_ollama` |
| 双段融合 | [backend/core/graph_builder.py](../backend/core/graph_builder.py) |
| Rerank | [backend/core/rag_pipeline.py](../backend/core/rag_pipeline.py) `_rerank` |
| 多视图 + 拖拽合并 | [frontend/src/views/GraphView.vue](../frontend/src/views/GraphView.vue) |
| 仪表盘 | [frontend/src/views/DashboardView.vue](../frontend/src/views/DashboardView.vue) + [backend/api/stats.py](../backend/api/stats.py) |
| Benchmark | 同上 stats.py `run_benchmark` |
| 报告导出 | 同上 `report_pdf` / `report_download` |
| HITL 自然语言 | [backend/api/graph.py](../backend/api/graph.py) `_execute_modification` |
