from __future__ import annotations

from typing import Any, TypedDict


class Task2GraphState(TypedDict, total=False):
    question_id: str
    question_type: str
    raw_question_json: str
    raw_question: str
    sub_questions: list[str]
    total_turns: int

    current_turn_index: int
    current_question: str
    cumulative_question: str

    parsed_slots: dict[str, Any]
    missing_slots: list[str]
    needs_clarification: bool

    query_plan: dict[str, Any]

    sql: str
    sql_history: list[str]
    sql_attempts: int
    sql_error: str

    result_preview: str
    result_rows: list[dict[str, Any]]
    result_row_count: int
    context_companies: list[str]
    context_rows: list[dict[str, Any]]

    chart_plan: dict[str, Any]
    chart_spec: dict[str, Any]
    current_chart_specs: list[str]
    all_chart_specs: list[str]
    current_chart_paths: list[str]
    all_chart_paths: list[str]
    graph_formats: list[str]

    current_answer: str
    turn_answers: list[dict[str, Any]]
    answer_json: str
    graph_format_text: str

    notes: list[str]
    final_status: str


__all__ = ["Task2GraphState"]
