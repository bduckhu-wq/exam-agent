"""
LangGraph 构建器
根据 Skill 的 workflow 定义动态构建图
"""
from typing import Literal
from langgraph.graph import StateGraph, END
from .state import ExamState
from .nodes import (
    clarify_node,
    analyze_node,
    plan_node,
    generate_node,
    validate_node,
    adapt_node
)

# 节点 ID → 函数映射
NODE_FUNCTIONS = {
    "clarify": clarify_node,
    "analyze": analyze_node,
    "plan": plan_node,
    "generate": generate_node,
    "validate": validate_node,
    "adapt": adapt_node,
}


def build_question_generator_graph():
    """
    构建出题 Agent 的 LangGraph
    固定的流程：clarify → analyze → plan → generate → validate
    """
    graph = StateGraph(ExamState)

    # 添加节点
    graph.add_node("clarify", clarify_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("plan", plan_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)

    # 设置入口
    graph.set_entry_point("clarify")

    # 条件边：clarify 后判断是继续追问还是进入分析
    def route_after_clarify(state: ExamState) -> Literal["analyze", END]:
        """
        clarify 节点后的路由逻辑：
        - status == "clarifying" → END（参数不完整，等待用户补充）
        - status == "ready" → analyze（参数完整，进入分析阶段）
        """
        status = state.get("status")
        if status == "clarifying":
            return END  # 暂停等待用户补充信息
        return "analyze"

    graph.add_conditional_edges(
        "clarify",
        route_after_clarify,
        {
            "analyze": "analyze",
            END: END
        }
    )

    # 线性边
    graph.add_edge("analyze", "plan")
    graph.add_edge("plan", "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)

    return graph.compile()


def build_adaptor_graph():
    """
    构建题目改编的 LangGraph
    流程：parse → adapt → validate
    """
    graph = StateGraph(ExamState)

    # 目前简化处理，直接返回
    graph.add_node("adapt", adapt_node)
    graph.set_entry_point("adapt")
    graph.add_edge("adapt", END)

    return graph.compile()


def build_from_workflow(workflow: dict):
    """
    根据 Skill 的 workflow 定义动态构建图
    workflow 格式：
    {
        "nodes": [{"id": "analyze", "name": "知识分析"}],
        "edges": [{"from": "analyze", "to": "plan"}],
        "entry": "analyze"
    }
    """
    graph = StateGraph(ExamState)

    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    entry = workflow.get("entry", nodes[0]["id"] if nodes else "analyze")

    # 注册节点
    for node_def in nodes:
        node_id = node_def["id"]
        if node_id in NODE_FUNCTIONS:
            graph.add_node(node_id, NODE_FUNCTIONS[node_id])

    # 注册边
    conditional_edges = []
    for edge in edges:
        from_node = edge["from"]
        to_node = edge["to"]
        if edge.get("type") == "conditional":
            conditional_edges.append((from_node, edge))
        else:
            graph.add_edge(from_node, to_node)

    # 设置入口
    graph.set_entry_point(entry)
    graph.add_edge(list(NODE_FUNCTIONS.keys())[-1], END)

    return graph.compile()


# 预编译的图
_QUESTION_GENERATOR_GRAPH = None
_ADAPTOR_GRAPH = None


def get_question_generator_graph():
    global _QUESTION_GENERATOR_GRAPH
    if _QUESTION_GENERATOR_GRAPH is None:
        _QUESTION_GENERATOR_GRAPH = build_question_generator_graph()
    return _QUESTION_GENERATOR_GRAPH


def get_adaptor_graph():
    global _ADAPTOR_GRAPH
    if _ADAPTOR_GRAPH is None:
        _ADAPTOR_GRAPH = build_adaptor_graph()
    return _ADAPTOR_GRAPH
