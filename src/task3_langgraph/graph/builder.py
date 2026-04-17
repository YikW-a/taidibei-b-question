from __future__ import annotations

from ..config.settings import Task3LangGraphConfig
from ..nodes import (
    Task3NodeContext,
    append_turn_result_node,
    build_query_plan_node,
    clarify_or_continue_node,
    execute_sql_node,
    export_result_node,
    fuse_sql_and_evidence_node,
    generate_answer_node,
    generate_sql_node,
    parse_question_node,
    render_chart_node,
    rerank_evidence_node,
    retrieve_reports_node,
    self_check_node,
)
from ..schemas.state import Task3GraphState


def build_task3_graph(config: Task3LangGraphConfig):
    from langgraph.graph import END, START, StateGraph

    ctx = Task3NodeContext(config)
    graph = StateGraph(Task3GraphState)
    graph.add_node("parse_question", lambda state: parse_question_node(state, ctx))
    graph.add_node("clarify_or_continue", lambda state: clarify_or_continue_node(state, ctx))
    graph.add_node("build_query_plan", lambda state: build_query_plan_node(state, ctx))
    graph.add_node("generate_sql", lambda state: generate_sql_node(state, ctx))
    graph.add_node("execute_sql", lambda state: execute_sql_node(state, ctx))
    graph.add_node("retrieve_reports", lambda state: retrieve_reports_node(state, ctx))
    graph.add_node("rerank_evidence", lambda state: rerank_evidence_node(state, ctx))
    graph.add_node("fuse_sql_and_evidence", lambda state: fuse_sql_and_evidence_node(state, ctx))
    graph.add_node("render_chart", lambda state: render_chart_node(state, ctx))
    graph.add_node("generate_answer", lambda state: generate_answer_node(state, ctx))
    graph.add_node("run_self_check", lambda state: self_check_node(state, ctx))
    graph.add_node("append_turn_result", lambda state: append_turn_result_node(state, ctx))
    graph.add_node("export_result", lambda state: export_result_node(state, ctx))

    graph.add_edge(START, "parse_question")
    graph.add_edge("parse_question", "clarify_or_continue")
    graph.add_conditional_edges(
        "clarify_or_continue",
        lambda state: "generate_answer" if state.get("needs_clarification") else "build_query_plan",
        {
            "generate_answer": "generate_answer",
            "build_query_plan": "build_query_plan",
        },
    )
    graph.add_conditional_edges(
        "build_query_plan",
        lambda state: "generate_sql" if state.get("query_plan", {}).get("needs_sql") else "retrieve_reports",
        {
            "generate_sql": "generate_sql",
            "retrieve_reports": "retrieve_reports",
        },
    )
    graph.add_edge("generate_sql", "execute_sql")
    graph.add_conditional_edges(
        "execute_sql",
        lambda state: (
            "generate_sql"
            if state.get("sql_error") and int(state.get("sql_attempts", 0) or 0) < 3
            else "retrieve_reports"
        ),
        {
            "generate_sql": "generate_sql",
            "retrieve_reports": "retrieve_reports",
        },
    )
    graph.add_edge("retrieve_reports", "rerank_evidence")
    graph.add_edge("rerank_evidence", "fuse_sql_and_evidence")
    graph.add_edge("fuse_sql_and_evidence", "render_chart")
    graph.add_edge("render_chart", "generate_answer")
    graph.add_edge("generate_answer", "run_self_check")
    graph.add_edge("run_self_check", "append_turn_result")
    graph.add_edge("append_turn_result", "export_result")
    graph.add_edge("export_result", END)
    return graph.compile()
