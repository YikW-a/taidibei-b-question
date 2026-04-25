from __future__ import annotations

from src.task2_langgraph.nodes.workflow import (
    append_turn_result_node,
    build_query_plan_node,
    clarify_or_continue_node,
    execute_sql_node,
    export_result_node,
    generate_answer_node,
    generate_sql_node,
    initialize_state,
    parse_question_node,
    plan_chart_node,
    prototype_manual_run,
    render_chart_node,
)
from src.task2_langgraph.schemas import QuestionRecord

from ..config.settings import Task2LangGraphConfig
from ..tools import Task2Runtime


class Task2NodeContext:
    def __init__(self, config: Task2LangGraphConfig) -> None:
        self.config = config
        self.runtime = Task2Runtime(config)
        self.intent_parser = self.runtime.intent_parser

    def get_question(self, question_id: str) -> QuestionRecord:
        return self.runtime.get_question(question_id)


__all__ = [
    "Task2NodeContext",
    "append_turn_result_node",
    "build_query_plan_node",
    "clarify_or_continue_node",
    "execute_sql_node",
    "export_result_node",
    "generate_answer_node",
    "generate_sql_node",
    "initialize_state",
    "parse_question_node",
    "plan_chart_node",
    "prototype_manual_run",
    "render_chart_node",
]
