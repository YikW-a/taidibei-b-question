from __future__ import annotations

from dataclasses import dataclass
import json
import random
import time

import pandas as pd

from ..config.settings import Task2LangGraphConfig
from ..nodes import Task2NodeContext, initialize_state
from ..schemas import Task2GraphState
from .builder import build_task2_graph

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None


@dataclass
class Task2LangGraphPrototype:
    config: Task2LangGraphConfig
    context: Task2NodeContext | None = None
    app: object | None = None

    def __post_init__(self) -> None:
        self.context = Task2NodeContext(self.config)
        self.app = build_task2_graph(self.config)

    def question_ids(self) -> list[str]:
        assert self.context is not None
        return list(self.context.runtime.questions.keys())

    def run_single(self, question_id: str) -> Task2GraphState:
        assert self.context is not None
        assert self.app is not None
        state = initialize_state(question_id, self.context)
        for turn_index in range(state["total_turns"]):
            state["current_turn_index"] = turn_index
            state = self.app.invoke(state)
        return state

    def select_question_ids(
        self,
        explicit_ids: list[str] | None = None,
        sample_limit: int | None = None,
        sample_seed: int = 7,
    ) -> list[str]:
        available = self.question_ids()
        if explicit_ids:
            wanted = [qid.strip() for qid in explicit_ids if qid.strip()]
            return [qid for qid in wanted if qid in available]
        if sample_limit is not None and sample_limit > 0:
            rng = random.Random(sample_seed)
            sample_size = min(sample_limit, len(available))
            return sorted(rng.sample(available, sample_size), key=available.index)
        return available

    def run_many(self, question_ids: list[str], show_progress: bool = True) -> list[Task2GraphState]:
        results: list[Task2GraphState] = []
        ok_count = 0
        warning_count = 0
        error_count = 0
        total = len(question_ids)
        progress_bar = None
        if show_progress and tqdm is not None:
            progress_bar = tqdm(total=total, desc="Task2 LangGraph", unit="question")
        for index, question_id in enumerate(question_ids, start=1):
            started_at = time.time()
            if show_progress:
                if progress_bar is not None:
                    progress_bar.set_postfix_str(f"start={question_id} ok={ok_count} error={error_count}")
                else:
                    print(f"[{index}/{total}] start {question_id} | mode={self.config.llm_mode}", flush=True)
            try:
                state = self.run_single(question_id)
            except Exception as exc:  # pragma: no cover
                question = self.context.get_question(question_id) if self.context is not None else None
                fallback_answer_json, fallback_turn_answers = self._build_fallback_answer_payload(
                    question_id=question_id,
                    raw_question=question.raw_question if question else "",
                    sub_questions=question.sub_questions if question else [],
                    notes=[repr(exc)],
                )
                state = {
                    "question_id": question_id,
                    "final_status": "error",
                    "question_type": question.question_type if question else "",
                    "raw_question_json": question.original_question_json if question else "[]",
                    "raw_question": question.raw_question if question else "",
                    "turn_answers": fallback_turn_answers,
                    "all_chart_paths": [],
                    "graph_formats": [],
                    "answer_json": fallback_answer_json,
                    "graph_format_text": "无",
                    "sql": "",
                    "notes": [repr(exc)],
                }
            state = self._ensure_nonempty_answer_payload(state)
            status = state.get("final_status", "ok")
            if status == "error":
                error_count += 1
            elif status == "warning":
                warning_count += 1
            else:
                ok_count += 1
            results.append(state)
            if show_progress:
                elapsed = time.time() - started_at
                if progress_bar is not None:
                    progress_bar.update(1)
                    progress_bar.set_postfix_str(
                        f"last={question_id} status={status} ok={ok_count} warn={warning_count} error={error_count} t={elapsed:.1f}s"
                    )
                else:
                    print(
                        f"[{index}/{total}] done  {question_id} | status={status} | ok={ok_count} warn={warning_count} error={error_count} | t={elapsed:.1f}s",
                        flush=True,
                    )
        if progress_bar is not None:
            progress_bar.close()
        return results

    def _build_fallback_answer_payload(
        self,
        *,
        question_id: str,
        raw_question: str,
        sub_questions: list[str],
        notes: list[str],
    ) -> tuple[str, list[dict[str, object]]]:
        note_text = "；".join(item for item in notes if item)
        content = (
            "本题在运行过程中出现异常，暂未能生成稳定答案。"
            + (f"异常信息：{note_text}" if note_text else "")
        )
        turn_questions = sub_questions or ([raw_question] if raw_question else [question_id])
        turn_answers = [{"Q": item, "A": {"content": content, "image": []}} for item in turn_questions]
        return json.dumps(turn_answers, ensure_ascii=False), turn_answers

    def _ensure_nonempty_answer_payload(self, state: Task2GraphState) -> Task2GraphState:
        answer_json = str(state.get("answer_json", "") or "").strip()
        if answer_json and answer_json not in {"[]", "{}", "null", "None"}:
            return state
        raw_question = str(state.get("raw_question", "") or "")
        turn_answers = list(state.get("turn_answers", []) or [])
        if turn_answers:
            synthesized = json.dumps(turn_answers, ensure_ascii=False)
            return {**state, "answer_json": synthesized}
        question = self.context.get_question(state["question_id"]) if self.context is not None else None
        fallback_answer_json, fallback_turn_answers = self._build_fallback_answer_payload(
            question_id=str(state.get("question_id", "") or ""),
            raw_question=raw_question,
            sub_questions=question.sub_questions if question else [],
            notes=list(state.get("notes", []) or []),
        )
        return {
            **state,
            "turn_answers": fallback_turn_answers,
            "answer_json": fallback_answer_json,
        }

    def export_batch_results(self, states: list[Task2GraphState]) -> dict[str, object]:
        output_dir = self.config.output_dir
        artifacts_dir = self.config.artifacts_dir
        debug_dir = artifacts_dir / "debug"
        result_xlsx = output_dir / "result_2.xlsx"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for state in states:
            question_id = state.get("question_id", "")
            debug_payload = {
                "question_id": question_id,
                "question_type": state.get("question_type", ""),
                "raw_question": state.get("raw_question", ""),
                "raw_question_json": state.get("raw_question_json", "[]"),
                "parsed_slots": state.get("parsed_slots", {}),
                "missing_slots": state.get("missing_slots", []),
                "needs_clarification": state.get("needs_clarification", False),
                "query_plan": state.get("query_plan", {}),
                "sql": state.get("sql", ""),
                "sql_history": state.get("sql_history", []),
                "sql_attempts": state.get("sql_attempts", 0),
                "sql_error": state.get("sql_error", ""),
                "result_row_count": state.get("result_row_count", 0),
                "result_rows": state.get("result_rows", []),
                "context_companies": state.get("context_companies", []),
                "context_rows": state.get("context_rows", []),
                "result_preview": state.get("result_preview", ""),
                "chart_plan": state.get("chart_plan", {}),
                "chart_spec": state.get("chart_spec", {}),
                "all_chart_specs": state.get("all_chart_specs", []),
                "all_chart_paths": state.get("all_chart_paths", []),
                "graph_formats": state.get("graph_formats", []),
                "turn_answers": state.get("turn_answers", []),
                "answer_json": state.get("answer_json", "[]"),
                "notes": state.get("notes", []),
                "final_status": state.get("final_status", "ok"),
            }
            if question_id:
                (debug_dir / f"{question_id}.json").write_text(
                    json.dumps(debug_payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            rows.append(
                {
                    "编号": question_id,
                    "问题": state.get("raw_question_json", "[]"),
                    "SQL 查询语句": "\n\n".join(state.get("sql_history", []) or ([state.get("sql", "")] if state.get("sql") else [])),
                    "图形格式": state.get("graph_format_text", "无"),
                    "回答": state.get("answer_json", "[]"),
                    "状态": state.get("final_status", "ok"),
                    "备注": "；".join(state.get("notes", [])),
                }
            )
        df = pd.DataFrame(rows)
        export_df = df[["编号", "问题", "SQL 查询语句", "图形格式", "回答"]]
        export_df.to_excel(result_xlsx, index=False)
        df.to_csv(artifacts_dir / "task2_langgraph_results.csv", index=False, encoding="utf-8-sig")
        summary = {
            "total_questions": len(states),
            "ok_count": int((df["状态"] == "ok").sum()) if not df.empty else 0,
            "warning_count": int((df["状态"] == "warning").sum()) if not df.empty else 0,
            "error_count": int((df["状态"] == "error").sum()) if not df.empty else 0,
            "question_ids": df["编号"].tolist(),
            "result_2_xlsx": str(result_xlsx),
            "debug_dir": str(debug_dir),
            "chart_spec_dir": str(self.config.chart_spec_dir),
        }
        (artifacts_dir / "task2_langgraph_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
