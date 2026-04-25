from __future__ import annotations

from collections.abc import Callable

from src.task3_langgraph.nodes.workflow import (
    append_turn_result_node,
    build_query_plan_node,
    execute_sql_node,
    export_result_node,
    fuse_sql_and_evidence_node,
    generate_answer_node,
    generate_sql_node,
    initialize_state,
    parse_question_node,
    render_chart_node,
    rerank_evidence_node,
    retrieve_reports_node,
    self_check_node,
)
from src.task3_langgraph.schemas import QuestionRecord

from ..config.settings import Task3LangGraphConfig
from ..tools import Task3Runtime


class Task3NodeContext:
    def __init__(
        self,
        config: Task3LangGraphConfig,
        *,
        index_progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.config = config
        self.runtime = Task3Runtime(config, index_progress_callback=index_progress_callback)
        self.intent_parser = self.runtime.intent_parser

    def get_question(self, question_id: str) -> QuestionRecord:
        return self.runtime.get_question(question_id)


def clarify_or_continue_node(state, ctx: Task3NodeContext):
    from src.task3_langgraph.nodes.workflow import clarify_or_continue_node as base_clarify_or_continue_node

    updated = base_clarify_or_continue_node(state, ctx)
    parsed = dict(updated.get("parsed_slots", {}) or {})
    missing = list(updated.get("missing_slots", []) or [])
    if "metric" in missing and not bool(parsed.get("needs_sql")):
        missing = [item for item in missing if item != "metric"]
    return {
        **updated,
        "missing_slots": missing,
        "needs_clarification": bool(missing),
    }
