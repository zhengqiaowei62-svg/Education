"""Agent B · Aligner/Judge —— 跨教材融合裁决者。

工作流（伪双 Agent · 工作流编排）：
1. 收集所有教材的节点
2. 用代码（确定性）做相似度初筛 → 候选同一概念簇
3. 把每个簇喂给 Agent B：让 LLM 决定 merge / keep / remove，并给出 reason
4. 按决策合并节点，重映射边

设计要点：
- 所有 LLM 调用都是 JSON 严格输出 + 失败回退（Jaccard 阈值 + 名称完全相同 → 默认 merge）
- 边去重（相同 source/target/relation_type）
"""
from __future__ import annotations
import uuid
from typing import List, Tuple, Dict

from backend.models.schemas import (
    KnowledgeGraph, KGNode, KGEdge, MergeDecision,
)
from backend.utils.llm import chat_json, llm_available, text_similarity


JUDGE_SYSTEM = """你是一名医学/生物学教学内容整合专家（Aligner Agent）。
你的职责：对来自不同教材、疑似描述同一概念的多个知识点做出整合裁决。
严禁输出任何解释、寒暄、markdown、<think> 思考链。仅输出 JSON 对象。
/no_think"""


JUDGE_TEMPLATE = """以下是来自不同教材的若干知识点，疑似描述"同一个概念"。请裁决并仅输出如下 JSON：

{{
  "action": "merge" | "keep" | "remove",
  "canonical_name": "整合后建议使用的术语（如果 merge）",
  "canonical_definition": "整合后建议保留的定义（如果 merge，<=80字）",
  "reason": "决策理由（<=50字）",
  "confidence": 0.0 - 1.0
}}

裁决规则：
- merge：本质是同一概念（措辞/翻译不同，定义实质等价）
- keep：相关但不等价（如"抗原"与"免疫原"概念有重叠但应保留区分）
- remove：明显冗余且没有任何独特信息

候选知识点：
{candidates}
"""


def _format_candidates(nodes: List[KGNode]) -> str:
    parts = []
    for i, n in enumerate(nodes, 1):
        parts.append(
            f"[{i}] 来源教材={n.textbook_id} 章节={n.chapter} 名称={n.name}\n    定义: {n.definition[:120]}"
        )
    return "\n".join(parts)


def _cluster_by_similarity(nodes: List[KGNode], threshold: float) -> List[List[int]]:
    """Union-Find：基于名称 + 定义 Jaccard 相似度聚簇。"""
    n = len(nodes)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            ni, nj = nodes[i], nodes[j]
            # 同教材的节点不互相合并
            if ni.textbook_id == nj.textbook_id:
                continue
            name_sim = text_similarity(ni.name, nj.name)
            def_sim = text_similarity(ni.definition, nj.definition)
            score = max(name_sim, 0.5 * name_sim + 0.5 * def_sim)
            if name_sim >= 0.95 or score >= threshold:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)
    return [c for c in clusters.values() if len(c) >= 1]


def _judge_cluster(nodes: List[KGNode]) -> dict:
    """对一个候选簇调用 Agent B 做裁决。"""
    # 单元素：直接保留
    if len(nodes) == 1:
        return {"action": "keep", "canonical_name": nodes[0].name,
                "canonical_definition": nodes[0].definition,
                "reason": "唯一概念，无重复", "confidence": 1.0}

    if not llm_available("judge"):
        # 回退：名称完全相同 → merge；否则 keep
        same = all(n.name == nodes[0].name for n in nodes)
        return {
            "action": "merge" if same else "keep",
            "canonical_name": nodes[0].name,
            "canonical_definition": max((n.definition for n in nodes), key=len),
            "reason": "（无 LLM）基于规则的回退裁决",
            "confidence": 0.6 if same else 0.4,
        }

    prompt = JUDGE_TEMPLATE.format(candidates=_format_candidates(nodes))
    data = chat_json(prompt, system=JUDGE_SYSTEM, role="judge", default=None,
                     temperature=0.1, max_tokens=2000)
    if not isinstance(data, dict):
        data = {"action": "keep", "canonical_name": nodes[0].name,
                "canonical_definition": nodes[0].definition,
                "reason": "LLM 解析失败，默认保留", "confidence": 0.3}
    if data.get("action") not in {"merge", "keep", "remove"}:
        data["action"] = "keep"
    return data


def align_and_merge(
    graphs: List[KnowledgeGraph],
    similarity_threshold: float = 0.55,
) -> Tuple[KnowledgeGraph, List[MergeDecision], dict]:
    """主入口。

    返回 (融合后的图谱, 决策列表, 统计字典)
    """
    all_nodes: List[KGNode] = []
    all_edges: List[KGEdge] = []
    for g in graphs:
        all_nodes.extend(g.nodes)
        all_edges.extend(g.edges)

    if not all_nodes:
        return KnowledgeGraph(nodes=[], edges=[]), [], _stats(0, 0, 0, 0)

    clusters = _cluster_by_similarity(all_nodes, similarity_threshold)

    decisions: List[MergeDecision] = []
    id_remap: Dict[str, str] = {}  # 旧 id -> 新 id（合并/删除后的目标）
    kept_nodes: List[KGNode] = []
    removed_ids: set[str] = set()

    for cluster_idx, idxs in enumerate(clusters):
        cluster_nodes = [all_nodes[i] for i in idxs]
        verdict = _judge_cluster(cluster_nodes)
        action = verdict.get("action", "keep")

        if action == "merge" and len(cluster_nodes) > 1:
            new_id = f"merged_{uuid.uuid4().hex[:8]}"
            canon_name = verdict.get("canonical_name") or cluster_nodes[0].name
            canon_def = verdict.get("canonical_definition") or max(
                (n.definition for n in cluster_nodes), key=len, default="")
            merged = KGNode(
                id=new_id,
                name=str(canon_name)[:60],
                definition=str(canon_def)[:300],
                category=cluster_nodes[0].category,
                chapter=cluster_nodes[0].chapter,
                page=cluster_nodes[0].page,
                textbook_id=",".join(sorted({n.textbook_id for n in cluster_nodes})),
                frequency=len(cluster_nodes),
            )
            kept_nodes.append(merged)
            for n in cluster_nodes:
                id_remap[n.id] = new_id
            decisions.append(MergeDecision(
                decision_id=f"d_{cluster_idx:04d}",
                action="merge",
                affected_nodes=[n.id for n in cluster_nodes],
                result_node=new_id,
                reason=str(verdict.get("reason", ""))[:200],
                confidence=float(verdict.get("confidence", 0.7) or 0.7),
            ))
        elif action == "remove":
            for n in cluster_nodes:
                removed_ids.add(n.id)
            decisions.append(MergeDecision(
                decision_id=f"d_{cluster_idx:04d}",
                action="remove",
                affected_nodes=[n.id for n in cluster_nodes],
                reason=str(verdict.get("reason", ""))[:200],
                confidence=float(verdict.get("confidence", 0.5) or 0.5),
            ))
        else:  # keep
            for n in cluster_nodes:
                kept_nodes.append(n)
                id_remap[n.id] = n.id
            decisions.append(MergeDecision(
                decision_id=f"d_{cluster_idx:04d}",
                action="keep",
                affected_nodes=[n.id for n in cluster_nodes],
                reason=str(verdict.get("reason", ""))[:200],
                confidence=float(verdict.get("confidence", 0.8) or 0.8),
            ))

    # 边重映射 + 去重
    seen = set()
    new_edges: List[KGEdge] = []
    for e in all_edges:
        s = id_remap.get(e.source)
        t = id_remap.get(e.target)
        if not s or not t or s == t:
            continue
        if s in removed_ids or t in removed_ids:
            continue
        key = (s, t, e.relation_type)
        if key in seen:
            continue
        seen.add(key)
        new_edges.append(KGEdge(
            source=s, target=t,
            relation_type=e.relation_type,
            description=e.description,
        ))

    # 统计
    original_chars = sum(len(n.definition) + len(n.name) for n in all_nodes)
    merged_chars = sum(len(n.definition) + len(n.name) for n in kept_nodes)
    stats = _stats(len(all_nodes), len(kept_nodes), original_chars, merged_chars)

    merged_graph = KnowledgeGraph(nodes=kept_nodes, edges=new_edges)
    return merged_graph, decisions, stats


def _stats(node_before: int, node_after: int,
           chars_before: int, chars_after: int) -> dict:
    ratio = (chars_after / chars_before) if chars_before else 0.0
    return {
        "node_count_before": node_before,
        "node_count_after": node_after,
        "original_chars": chars_before,
        "merged_chars": chars_after,
        "compression_ratio": round(ratio, 4),
    }
