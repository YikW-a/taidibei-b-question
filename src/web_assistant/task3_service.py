from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.task3_langgraph.app.common import resolve_config
from src.task3_langgraph.nodes import (
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
from src.task3_langgraph.schemas import QuestionRecord, Task3GraphState


@dataclass
class WebConversation:
    session_id: str
    questions: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class InteractiveTask3Service:
    """Small adapter that reuses task3 nodes without changing task3 source code."""

    def __init__(
        self,
        *,
        base_dir: Path,
        output_dir: Path,
        knowledge_base_dir: Path,
        llm_config: Path | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.output_dir = output_dir
        self.config = resolve_config(
            base_dir=base_dir,
            llm_config=llm_config,
            output_dir=output_dir,
            knowledge_base_dir=knowledge_base_dir,
            build_index_on_start=False,
        )
        self.ctx = Task3NodeContext(self.config)
        self._lock = threading.RLock()
        self._sessions: dict[str, WebConversation] = {}

    @property
    def result_dir(self) -> Path:
        return self.config.result_dir

    def ask(self, *, session_id: str, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        with self._lock:
            started_at = time.perf_counter()
            conversation = self._sessions.setdefault(session_id, WebConversation(session_id=session_id))
            conversation.questions.append(question)
            conversation.updated_at = time.time()
            state = self._run_conversation(conversation)
            elapsed_seconds = round(time.perf_counter() - started_at, 2)
            turn_answers = list(state.get("turn_answers", []) or [])
            latest = turn_answers[-1] if turn_answers else {"Q": question, "A": {"content": "", "image": [], "references": []}}
            return {
                "session_id": session_id,
                "status": state.get("final_status", "ok"),
                "elapsed_seconds": elapsed_seconds,
                "latest": self._normalize_answer(latest),
                "turns": [self._normalize_answer(item) for item in turn_answers],
                "notes": list(state.get("notes", []) or []),
            }

    def reset(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._sessions.pop(session_id, None)
        return {"session_id": session_id, "status": "reset"}

    def _run_conversation(self, conversation: WebConversation) -> Task3GraphState:
        question_id = f"WEB_{conversation.session_id}_{len(conversation.questions):03d}"
        original_question_json = json.dumps([{"Q": item} for item in conversation.questions], ensure_ascii=False)
        self.ctx.runtime.questions[question_id] = QuestionRecord(
            question_id=question_id,
            question_type="web_interactive",
            original_question_json=original_question_json,
            raw_question=" | ".join(conversation.questions),
            sub_questions=list(conversation.questions),
        )
        state: Task3GraphState = {
            "question_id": question_id,
            "question_type": "web_interactive",
            "raw_question_json": original_question_json,
            "raw_question": " | ".join(conversation.questions),
            "sub_questions": list(conversation.questions),
            "total_turns": len(conversation.questions),
            "current_turn_index": 0,
            "turn_answers": [],
            "sql_history": [],
            "context_companies": [],
            "context_rows": [],
            "notes": [],
            "final_status": "running",
            "reuse_prior_context": False,
        }
        for turn_index in range(len(conversation.questions)):
            state["current_turn_index"] = turn_index
            state = self._run_one_turn(state)
        return state

    def _run_one_turn(self, state: Task3GraphState) -> Task3GraphState:
        state = parse_question_node(state, self.ctx)
        state = clarify_or_continue_node(state, self.ctx)
        if state.get("needs_clarification"):
            state = generate_answer_node(state, self.ctx)
            state = self_check_node(state, self.ctx)
            state = append_turn_result_node(state, self.ctx)
            return export_result_node(state, self.ctx)

        state = build_query_plan_node(state, self.ctx)
        if state.get("query_plan", {}).get("needs_sql"):
            while True:
                state = generate_sql_node(state, self.ctx)
                state = execute_sql_node(state, self.ctx)
                if not state.get("sql_error") or int(state.get("sql_attempts", 0) or 0) >= 3:
                    break

        state = retrieve_reports_node(state, self.ctx)
        state = rerank_evidence_node(state, self.ctx)
        state = fuse_sql_and_evidence_node(state, self.ctx)
        state = render_chart_node(state, self.ctx)
        state = generate_answer_node(state, self.ctx)
        state = self_check_node(state, self.ctx)
        state = append_turn_result_node(state, self.ctx)
        return export_result_node(state, self.ctx)

    def _normalize_answer(self, answer: dict[str, Any]) -> dict[str, Any]:
        payload = dict(answer.get("A", {}) or {})
        images = [self._image_url(item) for item in list(payload.get("image", []) or []) if item]
        references = []
        for item in list(payload.get("references", []) or []):
            if not isinstance(item, dict):
                continue
            references.append(
                {
                    "paper_path": str(item.get("paper_path", "") or ""),
                    "paper_image": str(item.get("paper_image", "") or ""),
                    "text": str(item.get("text", "") or ""),
                }
            )
        return {
            "Q": str(answer.get("Q", "") or ""),
            "A": {
                "content": str(payload.get("content", "") or ""),
                "image": images,
                "references": references,
            },
        }

    @staticmethod
    def _image_url(path: str) -> str:
        name = Path(path).name
        return f"/generated/{name}"
