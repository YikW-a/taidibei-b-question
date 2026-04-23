from __future__ import annotations

import json
import shutil
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
        self._cancel_lock = threading.RLock()
        self._cancelled_sessions: set[str] = set()
        self._sessions: dict[str, WebConversation] = {}

    @property
    def result_dir(self) -> Path:
        return self.config.result_dir

    def ask(self, *, session_id: str, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        with self._lock:
            self._clear_cancel(session_id)
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
            self._drop_web_questions(session_id)
        self._clear_cancel(session_id)
        return {"session_id": session_id, "status": "reset"}

    def cancel(self, *, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {"session_id": session_id, "status": "ignored"}
        with self._cancel_lock:
            self._cancelled_sessions.add(session_id)
        return {"session_id": session_id, "status": "cancelled"}

    def cleanup_outputs(self) -> dict[str, Any]:
        output_dir = self.config.output_dir.resolve()
        outputs_root = (self.base_dir / "outputs").resolve()
        if output_dir == outputs_root or outputs_root not in output_dir.parents:
            return {"status": "skipped", "reason": "output_dir_not_in_project_outputs", "path": str(output_dir)}
        if self.config.knowledge_base_root.resolve() == output_dir:
            return {"status": "skipped", "reason": "output_dir_is_knowledge_base", "path": str(output_dir)}
        shutil.rmtree(output_dir, ignore_errors=True)
        return {"status": "cleaned", "path": str(output_dir)}

    def question_bank(self) -> list[dict[str, Any]]:
        def sort_key(item: tuple[str, QuestionRecord]) -> tuple[int, str]:
            question_id = item[0]
            suffix = "".join(ch for ch in question_id if ch.isdigit())
            return (int(suffix) if suffix else 10**9, question_id)

        with self._lock:
            items: list[dict[str, Any]] = []
            for question_id, record in sorted(self.ctx.runtime.questions.items(), key=sort_key):
                if question_id.startswith("WEB_"):
                    continue
                questions = [str(item).strip() for item in record.sub_questions if str(item).strip()]
                items.append(
                    {
                        "id": question_id,
                        "type": record.question_type,
                        "questions": questions,
                        "display": " / ".join(questions),
                    }
                )
            return items

    def _run_conversation(self, conversation: WebConversation) -> Task3GraphState:
        question_id = f"WEB_{conversation.session_id}_{len(conversation.questions):03d}"
        original_question_json = json.dumps([{"Q": item} for item in conversation.questions], ensure_ascii=False)
        self._raise_if_cancelled(conversation.session_id)
        self._drop_web_questions(conversation.session_id)
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
            self._raise_if_cancelled(conversation.session_id)
            state["current_turn_index"] = turn_index
            state = self._run_one_turn(state, conversation.session_id)
        return state

    def _run_one_turn(self, state: Task3GraphState, session_id: str) -> Task3GraphState:
        self._raise_if_cancelled(session_id)
        state = parse_question_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
        state = clarify_or_continue_node(state, self.ctx)
        if state.get("needs_clarification"):
            self._raise_if_cancelled(session_id)
            state = generate_answer_node(state, self.ctx)
            self._raise_if_cancelled(session_id)
            state = self_check_node(state, self.ctx)
            state = append_turn_result_node(state, self.ctx)
            return export_result_node(state, self.ctx)

        self._raise_if_cancelled(session_id)
        state = build_query_plan_node(state, self.ctx)
        if state.get("query_plan", {}).get("needs_sql"):
            while True:
                self._raise_if_cancelled(session_id)
                state = generate_sql_node(state, self.ctx)
                self._raise_if_cancelled(session_id)
                state = execute_sql_node(state, self.ctx)
                if not state.get("sql_error") or int(state.get("sql_attempts", 0) or 0) >= 3:
                    break

        self._raise_if_cancelled(session_id)
        state = retrieve_reports_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
        state = rerank_evidence_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
        state = fuse_sql_and_evidence_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
        state = render_chart_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
        state = generate_answer_node(state, self.ctx)
        self._raise_if_cancelled(session_id)
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

    def _drop_web_questions(self, session_id: str) -> None:
        prefix = f"WEB_{session_id}_"
        for question_id in [key for key in self.ctx.runtime.questions if key.startswith(prefix)]:
            self.ctx.runtime.questions.pop(question_id, None)

    def _clear_cancel(self, session_id: str) -> None:
        with self._cancel_lock:
            self._cancelled_sessions.discard(session_id)

    def _raise_if_cancelled(self, session_id: str) -> None:
        with self._cancel_lock:
            cancelled = session_id in self._cancelled_sessions
        if cancelled:
            raise RuntimeError("当前生成已取消。")
