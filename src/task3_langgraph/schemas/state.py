from __future__ import annotations

from typing import Any, TypedDict


class Task3GraphState(TypedDict, total=False):
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
    reuse_prior_context: bool

    query_plan: dict[str, Any]
    retrieval_plan: dict[str, Any]

    sql: str
    sql_history: list[str]
    sql_attempts: int
    sql_error: str

    result_preview: str
    result_rows: list[dict[str, Any]]
    result_row_count: int
    context_companies: list[str]
    context_rows: list[dict[str, Any]]

    retrieved_evidence: list[dict[str, Any]]
    retrieval_preview: str
    reranked_evidence: list[dict[str, Any]]
    rerank_preview: str
    fused_context: dict[str, Any]
    self_check: dict[str, Any]
    chart_plan: dict[str, Any]
    chart_spec: dict[str, Any]
    current_chart_paths: list[str]
    all_chart_paths: list[str]
    current_chart_specs: list[str]
    all_chart_specs: list[str]

    current_answer: str
    current_references: list[dict[str, Any]]
    answer_rewritten: bool
    turn_answers: list[dict[str, Any]]
    answer_json: str
    references_json: str

    notes: list[str]
    final_status: str


__all__ = ["Task3GraphState"]
