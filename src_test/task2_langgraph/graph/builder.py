from __future__ import annotations

from ..nodes import (
    Task2NodeContext,
    append_turn_result_node,
    build_query_plan_node,
    clarify_or_continue_node,
    execute_sql_node,
    export_result_node,
    generate_answer_node,
    generate_sql_node,
    parse_question_node,
    plan_chart_node,
    render_chart_node,
)
from src.task2_langgraph.schemas.state import Task2GraphState


def build_task2_graph(config):
    from langgraph.graph import END, START, StateGraph

    ctx = Task2NodeContext(config)
    graph = StateGraph(Task2GraphState)
    graph.add_node("parse_question", lambda state: parse_question_node(state, ctx))
    graph.add_node("clarify_or_continue", lambda state: clarify_or_continue_node(state, ctx))
    graph.add_node("build_query_plan", lambda state: build_query_plan_node(state, ctx))
    graph.add_node("generate_sql", lambda state: generate_sql_node(state, ctx))
    graph.add_node("execute_sql", lambda state: execute_sql_node(state, ctx))
    graph.add_node("plan_chart", lambda state: plan_chart_node(state, ctx))
    graph.add_node("render_chart", lambda state: render_chart_node(state, ctx))
    graph.add_node("generate_answer", lambda state: generate_answer_node(state, ctx))
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
    graph.add_edge("build_query_plan", "generate_sql")
    graph.add_edge("generate_sql", "execute_sql")
    graph.add_conditional_edges(
        "execute_sql",
        lambda state: (
            "generate_sql"
            if state.get("sql_error") and int(state.get("sql_attempts", 0) or 0) < 3
            else ("generate_answer" if state.get("sql_error") else "plan_chart")
        ),
        {
            "generate_sql": "generate_sql",
            "generate_answer": "generate_answer",
            "plan_chart": "plan_chart",
        },
    )
    graph.add_conditional_edges(
        "plan_chart",
        lambda state: "render_chart" if state.get("chart_plan", {}).get("should_draw") else "generate_answer",
        {
            "render_chart": "render_chart",
            "generate_answer": "generate_answer",
        },
    )
    graph.add_edge("render_chart", "generate_answer")
    graph.add_edge("generate_answer", "append_turn_result")
    graph.add_edge("append_turn_result", "export_result")
    graph.add_edge("export_result", END)
    return graph.compile()
