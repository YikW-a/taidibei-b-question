from __future__ import annotations

import json
from collections.abc import Callable

import pandas as pd

from ..config.settings import Task3LangGraphConfig
from ..schemas import QuestionRecord, Task3GraphState
from ..services import Task3IntentParser
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
        self.intent_parser: Task3IntentParser = self.runtime.intent_parser

    def get_question(self, question_id: str) -> QuestionRecord:
        return self.runtime.get_question(question_id)


def initialize_state(question_id: str, ctx: Task3NodeContext) -> Task3GraphState:
    question = ctx.get_question(question_id)
    return {
        "question_id": question.question_id,
        "question_type": question.question_type,
        "raw_question_json": question.original_question_json,
        "raw_question": question.raw_question,
        "sub_questions": question.sub_questions,
        "total_turns": len(question.sub_questions),
        "current_turn_index": 0,
        "turn_answers": [],
        "sql_history": [],
        "context_companies": [],
        "context_rows": [],
        "notes": [],
        "final_status": "running",
    }


def parse_question_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question = ctx.get_question(state["question_id"])
    turn_index = state.get("current_turn_index", 0)
    current_question = question.sub_questions[turn_index]
    cumulative_question = " | ".join(question.sub_questions[: turn_index + 1])
    intent = ctx.intent_parser.parse_text(cumulative_question)
    if (
        not intent.companies
        and state.get("context_companies")
        and any(token in current_question for token in ["这些公司", "上述公司", "这些企业", "上述企业", "它们", "其中"])
    ):
        intent.companies = list(state.get("context_companies", []))
    parsed_slots = {
        "companies": intent.companies,
        "stock_codes": intent.stock_codes,
        "metrics": intent.metrics,
        "periods": intent.periods,
        "focus_topics": intent.focus_topics,
        "intent_type": intent.intent_type,
        "needs_sql": intent.needs_sql,
        "needs_retrieval": intent.needs_retrieval,
        "top_n": intent.top_n,
        "threshold": intent.threshold,
    }
    return {
        **state,
        "current_question": current_question,
        "cumulative_question": cumulative_question,
        "parsed_slots": parsed_slots,
        "sql": "",
        "sql_error": "",
        "sql_attempts": 0,
        "result_preview": "",
        "result_rows": [],
        "result_row_count": 0,
        "retrieved_evidence": [],
        "retrieval_preview": "",
        "reranked_evidence": [],
        "rerank_preview": "",
        "fused_context": {},
        "self_check": {},
        "current_answer": "",
        "current_references": [],
    }


def clarify_or_continue_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    parsed = state.get("parsed_slots", {})
    text = state.get("current_question", "")
    missing: list[str] = []
    asks_for_specific_company = any(token in text for token in ["哪家公司", "哪家企业", "哪只股票", "哪个公司"])
    is_broad_company_screening = bool(
        parsed.get("metrics")
        and (
            parsed.get("threshold") is not None
            or parsed.get("top_n") is not None
            or any(token in text for token in ["有哪些", "哪些", "哪几家", "前", "Top", "top", "超过", "高于", "低于", "不低于", "不超过", "共同点", "筛选"])
        )
    )
    is_follow_up_group_question = any(token in text for token in ["他们", "这些", "上述", "其中", "共同点", "原因"])
    if (
        not parsed.get("companies")
        and "行业" not in text
        and (asks_for_specific_company or (any(token in text for token in ["公司", "企业"]) and not is_broad_company_screening and not is_follow_up_group_question))
    ):
        missing.append("company")
    if not parsed.get("periods") and parsed.get("metrics") and any(token in text for token in ["近三年", "近3年"]) is False:
        if any(token in text for token in ["季度", "年度", "上半年", "报告期", "去年", "今年"]):
            missing.append("period")
    return {
        **state,
        "missing_slots": list(dict.fromkeys(missing)),
        "needs_clarification": bool(missing),
    }


def build_query_plan_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question_text = _current_turn_question(state, ctx)
    plan = ctx.runtime.build_query_plan(
        question_text,
        state.get("parsed_slots", {}),
        context_companies=state.get("context_companies", []),
        context_rows=state.get("context_rows", []),
    )
    return {**state, "query_plan": plan}


def build_retrieval_plan_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question_text = _current_turn_question(state, ctx)
    plan = ctx.runtime.build_retrieval_plan(question_text, state.get("parsed_slots", {}))
    return {**state, "retrieval_plan": plan}


def generate_sql_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    if state.get("needs_clarification"):
        return state
    sql, reason = ctx.runtime.generate_sql(
        _current_turn_question(state, ctx),
        query_plan=state.get("query_plan", {}),
        context_rows=state.get("context_rows", []),
        previous_sql=state.get("sql"),
        previous_error=state.get("sql_error"),
    )
    history = list(state.get("sql_history", []))
    if sql and sql not in history:
        history.append(sql)
    return {
        **state,
        "sql": sql,
        "sql_history": history,
        "sql_attempts": state.get("sql_attempts", 0) + (1 if sql else 0),
        "notes": state.get("notes", []) + ([reason] if reason else []),
    }


def execute_sql_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    if state.get("needs_clarification") or not state.get("query_plan", {}).get("needs_sql"):
        return {**state, "sql_error": "", "final_status": "running"}
    try:
        df = ctx.runtime.run_sql(state.get("sql", ""))
        context_companies = (
            df["stock_abbr"].dropna().astype(str).drop_duplicates().tolist()
            if "stock_abbr" in df.columns
            else state.get("context_companies", [])
        )
        return {
            **state,
            "result_rows": df.to_dict(orient="records"),
            "result_row_count": len(df),
            "result_preview": df.head(20).to_json(force_ascii=False, orient="records"),
            "context_companies": context_companies,
            "context_rows": df.head(30).to_dict(orient="records"),
            "sql_error": "",
            "final_status": "running",
        }
    except Exception as exc:
        return {**state, "sql_error": str(exc), "final_status": "sql_error"}


def retrieve_reports_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    evidences = ctx.runtime.retrieve_evidence(state.get("retrieval_plan", {}))
    retrieval_plan = state.get("retrieval_plan", {})
    return {
        **state,
        "retrieved_evidence": evidences,
        "retrieval_preview": json.dumps(evidences[:5], ensure_ascii=False),
        "notes": state.get("notes", [])
        + [
            f"retrieval_mode={retrieval_plan.get('retrieval_mode', 'metadata')}",
            f"retrieval_hits={len(evidences)}",
        ],
    }


def rerank_evidence_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    reranked, rerank_meta = ctx.runtime.rerank_evidence(
        question=_current_turn_question(state, ctx),
        retrieval_plan=state.get("retrieval_plan", {}),
        evidences=state.get("retrieved_evidence", []),
    )
    return {
        **state,
        "reranked_evidence": reranked,
        "rerank_preview": json.dumps(rerank_meta, ensure_ascii=False),
        "notes": state.get("notes", [])
        + [
            f"rerank_strategy={rerank_meta.get('strategy', '')}",
            f"rerank_kept={rerank_meta.get('kept_count', 0)}",
        ],
    }


def fuse_sql_and_evidence_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    fused = ctx.runtime.fuse_context(
        question=_current_turn_question(state, ctx),
        sql_rows=state.get("result_rows", []),
        evidences=state.get("reranked_evidence", []) or state.get("retrieved_evidence", []),
    )
    return {**state, "fused_context": fused}


def self_check_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    if state.get("needs_clarification"):
        return state
    check = ctx.runtime.self_check(
        question=_current_turn_question(state, ctx),
        answer=state.get("current_answer", ""),
        sql_rows=state.get("result_rows", []),
        evidences=state.get("reranked_evidence", []) or state.get("retrieved_evidence", []),
    )
    return {**state, "self_check": check}


def generate_answer_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question_text = _current_turn_question(state, ctx)
    if state.get("needs_clarification"):
        answer = ctx.runtime.generate_clarification(question_text, state.get("missing_slots", []))
        return {**state, "current_answer": answer, "current_references": []}
    query_result = _result_dataframe(state)
    answer = ctx.runtime.generate_answer(
        question=question_text,
        sql=state.get("sql", ""),
        query_plan=state.get("query_plan", {}),
        query_result=query_result,
        evidences=state.get("reranked_evidence", []) or state.get("retrieved_evidence", []),
    )
    references = [
        ctx.runtime.enrich_reference(item, question=question_text)
        for item in (state.get("reranked_evidence", []) or state.get("retrieved_evidence", []))[:5]
    ]
    return {**state, "current_answer": answer, "current_references": references}


def append_turn_result_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    turn_answers = list(state.get("turn_answers", []))
    turn_answers.append(
        {
            "Q": state.get("current_question", ""),
            "A": {
                "content": state.get("current_answer", ""),
                "references": state.get("current_references", []),
                "image": [],
            },
        }
    )
    notes = list(state.get("notes", []))
    if state.get("self_check"):
        notes.append(f"self_check={json.dumps(state.get('self_check', {}), ensure_ascii=False)}")
    return {**state, "turn_answers": turn_answers, "notes": notes}


def export_result_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    references = []
    for answer in state.get("turn_answers", []):
        references.extend(answer.get("A", {}).get("references", []))
    dedup = []
    seen = set()
    for item in references:
        key = (
            item.get("paper_path", ""),
            item.get("text", ""),
            item.get("paper_image", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return {
        **state,
        "answer_json": json.dumps(state.get("turn_answers", []), ensure_ascii=False),
        "references_json": json.dumps(dedup, ensure_ascii=False),
        "final_status": "ok" if state.get("final_status") != "error" else "error",
    }


def _current_turn_question(state: Task3GraphState, ctx: Task3NodeContext) -> str:
    question = ctx.get_question(state["question_id"])
    turn_index = state.get("current_turn_index", 0)
    return question.sub_questions[turn_index]


def _result_dataframe(state: Task3GraphState) -> pd.DataFrame:
    rows = state.get("result_rows", [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
