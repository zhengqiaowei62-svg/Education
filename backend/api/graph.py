"""图谱抽取（Agent A）+ 跨教材融合（Agent B）+ HITL 修改。"""
from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException

from backend.models.schemas import (
    GraphExtractRequest, GraphExtractResponse,
    GraphMergeRequest, GraphMergeResponse,
    KnowledgeGraph, GraphModifyRequest, ModificationRecord,
)
from backend.core import kg_extractor, kg_aligner
from backend.storage import state
from backend.utils import llm

router = APIRouter()


@router.post("/extract", response_model=GraphExtractResponse)
def extract_graph(req: GraphExtractRequest):
    tb = state.TEXTBOOKS.get(req.textbook_id)
    if not tb:
        raise HTTPException(404, "textbook not found")
    g = kg_extractor.extract_textbook(tb)
    state.GRAPHS[req.textbook_id] = g
    return GraphExtractResponse(graph=g)


@router.get("", response_model=KnowledgeGraph)
def get_merged_graph():
    return state.MERGED_GRAPH


@router.post("/merge", response_model=GraphMergeResponse)
def merge_graphs(req: GraphMergeRequest):
    # 收集需要抽取的教材
    to_extract = []
    graphs = []

    for tid in req.textbook_ids:
        g = state.GRAPHS.get(tid)
        if g:
            graphs.append(g)
        else:
            tb = state.TEXTBOOKS.get(tid)
            if tb:
                to_extract.append(tb)

    # Map-Reduce 并行抽取缺失的图谱
    if to_extract:
        results = kg_extractor.extract_textbooks_parallel(to_extract)
        for tid, g in results:
            state.GRAPHS[tid] = g
            graphs.append(g)

    # Reduce阶段：融合
    merged, decisions, stats = kg_aligner.align_and_merge(
        graphs, similarity_threshold=req.similarity_threshold,
    )
    state.MERGED_GRAPH = merged
    return GraphMergeResponse(
        merged_graph=merged, decisions=decisions, stats=stats,
    )


@router.post("/modify")
def modify_graph(req: GraphModifyRequest):
    """
    教师通过自然语言指令修改图谱
    调用 Judge Agent 解析指令，执行修改并记录
    """
    instruction = req.instruction
    merged = state.MERGED_GRAPH

    if not merged or not merged.nodes:
        return {"status": "error", "message": "当前无融合图谱，请先执行合并"}

    # 构造Judge Agent的prompt
    # 列出可操作的节点（最多前50个）
    node_list = "\n".join([
        f"- id={n.id}, name={n.name}, category={n.category}"
        for n in merged.nodes[:50]
    ])

    system_prompt = """你是知识图谱修改助手。根据教师的指令，生成精确的修改操作。
输出JSON格式：
{
  "action": "split|rename|delete|merge|add_edge|remove_edge",
  "target_node_ids": ["节点ID列表"],
  "params": {
    "new_name": "重命名时的新名称（可选）",
    "new_nodes": [{"name":"拆分后节点1","definition":"定义"},{"name":"节点2","definition":"定义"}],
    "edge": {"source":"源ID","target":"目标ID","relation_type":"关系类型","description":"描述"}
  },
  "reason": "操作理由"
}
只输出JSON，不要解释。"""

    user_prompt = f"""当前图谱节点列表：
{node_list}

教师指令：{instruction}

请生成修改操作JSON。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    result = llm.chat_json(
        "", "", role="judge", messages=messages,
        max_tokens=800, temperature=0.1, default=None
    )

    if not result:
        return {"status": "error", "message": "LLM解析指令失败"}

    action = result.get("action", "unknown")
    target_ids = result.get("target_node_ids", [])
    params = result.get("params", {})
    reason = result.get("reason", "")

    # 记录修改前状态
    before_state = {}
    for nid in target_ids:
        for node in merged.nodes:
            if node.id == nid:
                before_state[nid] = node.model_dump()
                break

    # 执行修改操作
    after_state = {}
    message = ""

    if action == "rename" and target_ids:
        new_name = params.get("new_name", "")
        for node in merged.nodes:
            if node.id in target_ids:
                node.name = new_name
                after_state[node.id] = node.model_dump()
        message = f"已将节点重命名为「{new_name}」"

    elif action == "delete" and target_ids:
        merged.nodes = [n for n in merged.nodes if n.id not in target_ids]
        merged.edges = [e for e in merged.edges if e.source not in target_ids and e.target not in target_ids]
        after_state = {nid: None for nid in target_ids}
        message = f"已删除 {len(target_ids)} 个节点及相关边"

    elif action == "split" and target_ids:
        new_nodes_data = params.get("new_nodes", [])
        # 删除原节点
        old_node = None
        for n in merged.nodes:
            if n.id == target_ids[0]:
                old_node = n
                break
        if old_node:
            merged.nodes = [n for n in merged.nodes if n.id != old_node.id]
            # 创建新节点
            from backend.models.schemas import KGNode
            for i, nd in enumerate(new_nodes_data):
                new_id = f"split_{uuid.uuid4().hex[:8]}"
                new_node = KGNode(
                    id=new_id,
                    name=nd.get("name", f"拆分节点{i+1}"),
                    definition=nd.get("definition", old_node.definition),
                    category=old_node.category,
                    chapter=old_node.chapter,
                    page=old_node.page,
                    textbook_id=old_node.textbook_id,
                    frequency=1,
                    bbox=old_node.bbox
                )
                merged.nodes.append(new_node)
                after_state[new_id] = new_node.model_dump()
            message = f"已将「{old_node.name}」拆分为 {len(new_nodes_data)} 个新节点"

    elif action == "merge" and len(target_ids) >= 2:
        nodes_to_merge = [n for n in merged.nodes if n.id in target_ids]
        if len(nodes_to_merge) >= 2:
            from backend.models.schemas import KGNode
            new_id = f"manual_merge_{uuid.uuid4().hex[:8]}"
            new_name = params.get("new_name", nodes_to_merge[0].name)
            new_node = KGNode(
                id=new_id,
                name=new_name,
                definition=max([n.definition for n in nodes_to_merge], key=len),
                category=nodes_to_merge[0].category,
                chapter=nodes_to_merge[0].chapter,
                page=nodes_to_merge[0].page,
                textbook_id=",".join(set(n.textbook_id for n in nodes_to_merge)),
                frequency=len(nodes_to_merge),
                bbox=nodes_to_merge[0].bbox
            )
            merged.nodes = [n for n in merged.nodes if n.id not in target_ids]
            merged.nodes.append(new_node)
            # 边重映射
            for edge in merged.edges:
                if edge.source in target_ids:
                    edge.source = new_id
                if edge.target in target_ids:
                    edge.target = new_id
            after_state[new_id] = new_node.model_dump()
            message = f"已合并 {len(nodes_to_merge)} 个节点为「{new_name}」"

    elif action == "add_edge":
        edge_data = params.get("edge", {})
        if edge_data:
            from backend.models.schemas import KGEdge
            new_edge = KGEdge(
                source=edge_data.get("source", ""),
                target=edge_data.get("target", ""),
                relation_type=edge_data.get("relation_type", "parallel"),
                description=edge_data.get("description", "")
            )
            merged.edges.append(new_edge)
            after_state["new_edge"] = new_edge.model_dump()
            message = f"已添加新边: {new_edge.source} → {new_edge.target}"

    elif action == "remove_edge":
        edge_data = params.get("edge", {})
        src = edge_data.get("source", "")
        tgt = edge_data.get("target", "")
        before_count = len(merged.edges)
        merged.edges = [e for e in merged.edges if not (e.source == src and e.target == tgt)]
        removed = before_count - len(merged.edges)
        message = f"已移除 {removed} 条边"

    else:
        return {"status": "error", "message": f"不支持的操作类型: {action}"}

    # 记录修改
    record = ModificationRecord(
        mod_id=f"mod_{uuid.uuid4().hex[:8]}",
        action=action,
        target_nodes=target_ids,
        before=before_state,
        after=after_state,
        teacher_instruction=instruction,
        timestamp=datetime.now().isoformat(),
        confidence=1.0
    )
    state.MODIFICATIONS.append(record)

    return {
        "status": "success",
        "message": message,
        "action": action,
        "reason": reason,
        "mod_id": record.mod_id
    }


@router.get("/history")
def get_modification_history():
    """获取图谱修改历史"""
    return {
        "total": len(state.MODIFICATIONS),
        "records": [r.model_dump() for r in state.MODIFICATIONS]
    }


@router.get("/{textbook_id}", response_model=KnowledgeGraph)
def get_graph(textbook_id: str):
    return state.GRAPHS.get(textbook_id, KnowledgeGraph(textbook_id=textbook_id))


def _execute_modification(instruction: str) -> dict:
    """供 /api/chat 的 MODIFY 路径调用"""
    req = GraphModifyRequest(instruction=instruction)
    return modify_graph(req)
