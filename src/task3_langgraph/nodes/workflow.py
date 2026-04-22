from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from ..config.settings import Task3LangGraphConfig
from ..schemas import QuestionRecord, Task3GraphState
from ..services import Task3IntentParser
from ..tools import Task3Runtime
from ..tools.chart_spec import build_chart_spec, render_chart_from_spec, save_chart_spec
from ..tools.charts import ChartPlan, build_default_chart_plan


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
        "reuse_prior_context": False,
    }


def parse_question_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question = ctx.get_question(state["question_id"])
    turn_index = state.get("current_turn_index", 0)
    current_question = question.sub_questions[turn_index]
    cumulative_question = " | ".join(question.sub_questions[: turn_index + 1])
    referential_follow_up_tokens = [
        "判断依据",
        "依据是什么",
        "你确定",
        "名单",
        "为什么这么说",
        "你怎么判断",
        "数据来源",
        "是否可靠",
        "可靠性",
        "从哪里查询",
    ]
    is_open_trend_or_forecast_question = any(
        token in current_question for token in ["未来", "趋势", "预测", "中药材价格", "价格波动"]
    )
    should_parse_current_only = bool(
        turn_index > 0
        and state.get("context_companies")
        and any(token in current_question for token in referential_follow_up_tokens)
        and not is_open_trend_or_forecast_question
    )
    parse_text = current_question if should_parse_current_only else cumulative_question
    intent = ctx.intent_parser.parse_text(parse_text)
    intent.periods = _refine_follow_up_periods(current_question, intent.periods, state.get("result_rows", []) or [])
    if (
        not intent.companies
        and state.get("context_companies")
        and any(
            token in current_question
            for token in [
                "这些公司",
                "上述公司",
                "这些企业",
                "上述企业",
                "它们",
                "其中",
                "名单",
                "你确定",
                "判断依据",
                "依据是什么",
                "数据来源",
                "是否可靠",
                "可靠性",
                "从哪里查询",
            ]
        )
    ):
        intent.companies = list(state.get("context_companies", []))
    if should_parse_current_only and state.get("context_rows"):
        intent.needs_sql = False
        intent.needs_retrieval = True
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
    inherited_result_rows = list(state.get("result_rows", []) or [])
    if should_parse_current_only and not inherited_result_rows and state.get("context_companies"):
        inherited_result_rows = [{"stock_abbr": company} for company in list(state.get("context_companies", []) or [])]
    return {
        **state,
        "current_question": current_question,
        "cumulative_question": cumulative_question,
        "parsed_slots": parsed_slots,
        "reuse_prior_context": should_parse_current_only,
        "sql": "",
        "sql_error": "",
        "sql_attempts": 0,
        "result_preview": (
            state.get("result_preview", "")
            if should_parse_current_only and state.get("result_rows")
            else json.dumps(inherited_result_rows[:20], ensure_ascii=False)
            if should_parse_current_only and inherited_result_rows
            else ""
        ),
        "result_rows": inherited_result_rows if should_parse_current_only else [],
        "result_row_count": len(inherited_result_rows) if should_parse_current_only else 0,
        "retrieved_evidence": [],
        "retrieval_preview": "",
        "reranked_evidence": [],
        "rerank_preview": "",
        "fused_context": {},
        "self_check": {},
        "chart_plan": {},
        "chart_spec": {},
        "current_chart_paths": [],
        "all_chart_paths": [],
        "current_chart_specs": [],
        "all_chart_specs": [],
        "current_answer": "",
        "current_references": [],
        "answer_rewritten": False,
        "notes": list(state.get("notes", [])) + list(intent.notes or []),
    }


def clarify_or_continue_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    parsed = state.get("parsed_slots", {})
    text = state.get("current_question", "")
    context_companies = list(state.get("context_companies", []) or [])
    missing: list[str] = []
    asks_for_specific_company = any(token in text for token in ["哪家公司", "哪家企业", "哪只股票", "哪个公司"])
    broad_screening_tokens = [
        "有哪些",
        "哪些",
        "哪几家",
        "前",
        "Top",
        "top",
        "超过",
        "高于",
        "低于",
        "不低于",
        "不超过",
        "共同点",
        "筛选",
        "统计",
        "找出",
        "列出",
        "检索",
        "查询",
        "对比",
        "差异",
        "占比",
        "数量",
        "各公司",
        "所有公司",
        "中标企业",
        "存在",
        "公司的数量",
        "企业数量",
    ]
    is_broad_company_screening = bool(
        (
            parsed.get("metrics")
            or parsed.get("needs_sql")
            or parsed.get("needs_retrieval")
            or parsed.get("top_n") is not None
            or parsed.get("threshold") is not None
        )
        and (
            parsed.get("threshold") is not None
            or parsed.get("top_n") is not None
            or any(token in text for token in broad_screening_tokens)
        )
    )
    is_follow_up_group_question = any(
        token in text
        for token in ["他们", "这些", "上述", "其中", "共同点", "原因", "判断依据", "名单", "你确定", "依据是什么", "数据来源", "是否可靠", "可靠性", "从哪里查询"]
    )
    is_open_trend_or_forecast_question = any(
        token in text for token in ["未来", "趋势", "预测", "中药材价格", "价格波动", "判断的依据"]
    )
    has_prior_company_context = bool(context_companies) and is_follow_up_group_question and not is_open_trend_or_forecast_question
    is_open_industry_or_market_question = (
        "行业" in text
        or "板块" in text
        or any(token in text for token in ["公司数量", "各公司", "所有公司", "企业数量", "中药企业", "中标企业"])
        or any(token in text for token in ["以2-3家", "以 2-3 家", "2-3家", "两三家", "为例"])
    )
    asks_for_specific_company_after_screening = bool(
        asks_for_specific_company
        and (
            parsed.get("top_n") is not None
            or parsed.get("threshold") is not None
            or any(token in text for token in ["最大", "最高", "最低", "上涨幅度", "下降幅度", "前", "top", "Top"])
            or any(token in text for token in ["这些企业", "这些公司", "上述公司", "其中公司", "其中企业"])
        )
    )
    if (
        not parsed.get("companies")
        and not has_prior_company_context
        and not is_open_industry_or_market_question
        and (
            (
                asks_for_specific_company
                and not asks_for_specific_company_after_screening
                and not is_broad_company_screening
            )
            or (
                any(token in text for token in ["公司", "企业"])
                and not is_broad_company_screening
                and not is_follow_up_group_question
            )
        )
    ):
        missing.append("company")
    if not parsed.get("periods") and parsed.get("metrics") and any(token in text for token in ["近三年", "近3年"]) is False:
        if any(token in text for token in ["季度", "年度", "上半年", "报告期", "去年", "今年"]):
            missing.append("period")
    if not parsed.get("metrics") and any(
        token in text
        for token in ["收入", "利润", "毛利率", "净利率", "现金流", "负债率", "收益率", "财务数据", "业绩", "表现"]
    ):
        missing.append("metric")
    return {
        **state,
        "missing_slots": list(dict.fromkeys(missing)),
        "needs_clarification": bool(missing),
    }


def build_query_plan_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question_text = _current_turn_question(state, ctx)
    query_plan, retrieval_plan = ctx.runtime.build_plans(
        question_text,
        state.get("parsed_slots", {}),
        context_companies=state.get("context_companies", []),
        context_rows=state.get("context_rows", []),
    )
    if state.get("reuse_prior_context") and not state.get("parsed_slots", {}).get("metrics") and not state.get("parsed_slots", {}).get("periods"):
        query_plan["needs_sql"] = False
        retrieval_plan["needs_retrieval"] = False
    return {**state, "query_plan": query_plan, "retrieval_plan": retrieval_plan}


def build_retrieval_plan_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    return state


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
        sql = state.get("sql", "")
        df = ctx.runtime.run_sql(sql)
        query_plan = dict(state.get("query_plan", {}) or {})
        normalized_sql = ctx.runtime._normalize_threshold_literals(sql, query_plan) if sql else sql
        if df.empty and normalized_sql and normalized_sql != sql:
            retry_df = ctx.runtime.run_sql(normalized_sql)
            if not retry_df.empty:
                history = list(state.get("sql_history", []) or [])
                if normalized_sql not in history:
                    history.append(normalized_sql)
                state = {**state, "sql": normalized_sql, "sql_history": history}
                df = retry_df
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
        repaired_sql = ctx.runtime.repair_sql_after_error(state.get("sql", ""), str(exc))
        if repaired_sql:
            try:
                df = ctx.runtime.run_sql(repaired_sql)
                history = list(state.get("sql_history", []) or [])
                if repaired_sql not in history:
                    history.append(repaired_sql)
                context_companies = (
                    df["stock_abbr"].dropna().astype(str).drop_duplicates().tolist()
                    if "stock_abbr" in df.columns
                    else state.get("context_companies", [])
                )
                return {
                    **state,
                    "sql": repaired_sql,
                    "sql_history": history,
                    "result_rows": df.to_dict(orient="records"),
                    "result_row_count": len(df),
                    "result_preview": df.head(20).to_json(force_ascii=False, orient="records"),
                    "context_companies": context_companies,
                    "context_rows": df.head(30).to_dict(orient="records"),
                    "sql_error": "",
                    "final_status": "running",
                    "notes": state.get("notes", []) + ["sql_repaired_after_execution_error"],
                }
            except Exception:
                pass
        return {**state, "sql_error": str(exc), "final_status": "sql_error"}


def retrieve_reports_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    retrieval_plan = dict(state.get("retrieval_plan", {}) or {})
    question_text = _current_turn_question(state, ctx)
    query_plan = dict(state.get("query_plan", {}) or {})
    if ctx.runtime.should_skip_retrieval(
        question_text,
        query_plan,
        state.get("parsed_slots", {}),
        int(state.get("current_turn_index", 0) or 0),
    ):
        return {
            **state,
            "retrieval_plan": {**retrieval_plan, "needs_retrieval": False},
            "retrieved_evidence": [],
            "retrieval_preview": "",
            "notes": state.get("notes", []) + ["retrieval_skipped_fast_path", "retrieval_hits=0"],
        }
    result_rows = list(state.get("result_rows", []) or [])
    if (
        retrieval_plan.get("needs_retrieval")
        and not retrieval_plan.get("companies")
        and str(query_plan.get("intent_type", "") or "") in {"hybrid_sql_rag", "causal_analysis"}
    ):
        sql_companies = list(dict.fromkeys([str(item).strip() for item in (state.get("context_companies", []) or []) if str(item).strip()]))
        if not sql_companies and result_rows:
            for row in result_rows:
                if not isinstance(row, dict):
                    continue
                stock_abbr = str(row.get("stock_abbr", "") or "").strip()
                if stock_abbr and stock_abbr not in sql_companies:
                    sql_companies.append(stock_abbr)
                if len(sql_companies) >= 5:
                    break
        if sql_companies:
            retrieval_plan["companies"] = sql_companies
            if retrieval_plan.get("source_scope") == "hybrid":
                retrieval_plan["source_scope"] = "stock"
            state_notes = list(state.get("notes", []) or [])
            state_notes.append(f"retrieval_companies_seeded_from_sql={','.join(sql_companies[:5])}")
            state = {**state, "notes": state_notes}

    if (
        not retrieval_plan.get("companies")
        and result_rows
        and any(token in question_text for token in ["该公司", "这家公司", "其主营", "主营业务类型", "业务类型", "成本控制优势"])
    ):
        target_company = ""
        first_row = result_rows[0] if result_rows else {}
        if isinstance(first_row, dict):
            target_company = str(first_row.get("stock_abbr", "") or "").strip()
        if target_company:
            retrieval_plan["companies"] = [target_company]
            retrieval_plan["source_scope"] = "stock"

    evidences = ctx.runtime.retrieve_evidence(retrieval_plan)
    derived_companies = ctx.runtime.derive_companies_from_evidences(evidences, question=question_text)
    next_state = {
        **state,
        "retrieval_plan": retrieval_plan,
        "retrieved_evidence": evidences,
        "retrieval_preview": json.dumps(evidences[:5], ensure_ascii=False),
        "context_companies": list(dict.fromkeys((state.get("context_companies", []) or []) + derived_companies)),
        "notes": state.get("notes", [])
        + [
            f"retrieval_mode={retrieval_plan.get('retrieval_mode', 'metadata')}",
            f"retrieval_hits={len(evidences)}",
        ],
    }
    needs_evidence_seeded_filter = (
        query_plan.get("needs_sql")
        and not query_plan.get("companies")
        and ctx.runtime.requires_evidence_seeded_company_filter(question_text)
    )
    if needs_evidence_seeded_filter and not derived_companies and state.get("result_rows"):
        next_state.update(
            {
                "result_rows": [],
                "result_row_count": 0,
                "result_preview": "",
                "context_rows": [],
                "notes": next_state.get("notes", []) + ["sql_rows_cleared_without_evidence_company_match"],
            }
        )
    if (
        query_plan.get("needs_sql")
        and not query_plan.get("companies")
        and derived_companies
        and (
            not state.get("result_rows")
            or needs_evidence_seeded_filter
        )
    ):
        query_plan["companies"] = derived_companies
        sql, reason = ctx.runtime.generate_sql(
            _current_turn_question(state, ctx),
            query_plan=query_plan,
            context_rows=state.get("context_rows", []),
            previous_sql=state.get("sql"),
            previous_error=state.get("sql_error"),
        )
        if sql:
            history = list(state.get("sql_history", []) or [])
            if sql not in history:
                history.append(sql)
            try:
                df = ctx.runtime.run_sql(sql)
                context_companies = (
                    df["stock_abbr"].dropna().astype(str).drop_duplicates().tolist()
                    if "stock_abbr" in df.columns
                    else derived_companies
                )
                next_state.update(
                    {
                "query_plan": query_plan,
                        "sql": sql,
                        "sql_history": history,
                        "result_rows": df.to_dict(orient="records"),
                        "result_row_count": len(df),
                        "result_preview": df.head(20).to_json(force_ascii=False, orient="records"),
                        "context_companies": list(dict.fromkeys((context_companies or []) + (state.get("context_companies", []) or []))),
                        "context_rows": df.head(30).to_dict(orient="records"),
                        "sql_error": "",
                        "notes": next_state.get("notes", []) + ["sql_backfilled_from_evidence_companies"] + ([reason] if reason else []),
                    }
                )
            except Exception as exc:
                next_state.update(
                    {
                        "query_plan": query_plan,
                        "sql": sql,
                        "sql_history": history,
                        "sql_error": str(exc),
                        "notes": next_state.get("notes", []) + ["sql_backfill_failed"],
                    }
                )
    return next_state


def rerank_evidence_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    evidences = state.get("retrieved_evidence", [])
    if not ctx.runtime.should_rerank(_current_turn_question(state, ctx), state.get("retrieval_plan", {}), evidences):
        kept = ctx.runtime._deduplicate_evidences(list(evidences))[: int(state.get("retrieval_plan", {}).get("top_k", 5) or 5)]
        return {
            **state,
            "reranked_evidence": kept,
            "rerank_preview": json.dumps({"strategy": "skipped_fast_path", "kept_count": len(kept)}, ensure_ascii=False),
            "notes": state.get("notes", []) + ["rerank_strategy=skipped_fast_path", f"rerank_kept={len(kept)}"],
        }
    reranked, rerank_meta = ctx.runtime.rerank_evidence(
        question=_current_turn_question(state, ctx),
        retrieval_plan=state.get("retrieval_plan", {}),
        evidences=evidences,
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


def render_chart_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    if state.get("needs_clarification"):
        return {**state, "chart_plan": {}, "chart_spec": {}, "current_chart_paths": [], "current_chart_specs": []}
    dataframe = _result_dataframe(state)
    question_text = _current_turn_question(state, ctx)
    if dataframe.empty:
        return {**state, "chart_plan": {}, "chart_spec": {}, "current_chart_paths": [], "current_chart_specs": []}
    plan = _build_task3_chart_plan(question_text, dataframe, state.get("query_plan", {}) or {})
    if plan is None:
        return {**state, "chart_plan": {}, "chart_spec": {}, "current_chart_paths": [], "current_chart_specs": []}
    image_index = state.get("current_turn_index", 0) + 1
    chart_spec = build_chart_spec(
        state["question_id"],
        dataframe.head(80),
        plan,
        image_index=image_index,
        sql=state.get("sql", ""),
    )
    if chart_spec is None:
        return {**state, "chart_plan": {}, "chart_spec": {}, "current_chart_paths": [], "current_chart_specs": []}
    spec_path = save_chart_spec(ctx.config.chart_spec_dir, chart_spec)
    chart_path = render_chart_from_spec(ctx.config.result_dir, dataframe.head(80), chart_spec)
    current_paths = [f"./result/{Path(chart_path).name}"] if chart_path else []
    current_specs = [str(spec_path)]
    return {
        **state,
        "chart_plan": {
            "chart_type": plan.chart_type,
            "title": plan.title,
            "x_field": plan.x_field,
            "y_fields": plan.y_fields,
            "category_field": plan.category_field,
            "sort_by": plan.sort_by,
            "sort_ascending": plan.sort_ascending,
            "top_n": plan.top_n,
            "should_draw": plan.should_draw,
        },
        "chart_spec": chart_spec.to_dict(),
        "current_chart_paths": current_paths,
        "all_chart_paths": state.get("all_chart_paths", []) + current_paths,
        "current_chart_specs": current_specs,
        "all_chart_specs": state.get("all_chart_specs", []) + current_specs,
    }


def self_check_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    if state.get("needs_clarification"):
        return state
    evidences = state.get("reranked_evidence", []) or state.get("retrieved_evidence", [])
    answer_query_result = ctx.runtime.sanitize_query_result_for_answer(
        _current_turn_question(state, ctx),
        _result_dataframe(state),
    )
    if not ctx.runtime.should_run_self_check(
        _current_turn_question(state, ctx),
        state.get("query_plan", {}),
        answer_query_result,
        evidences,
    ):
        return {
            **state,
            "self_check": {"pass": True, "notes": ["self_check_skipped_fast_path"]},
        }
    check = ctx.runtime.self_check(
        question=_current_turn_question(state, ctx),
        answer=state.get("current_answer", ""),
        sql_rows=answer_query_result.to_dict(orient="records"),
        evidences=evidences,
    )
    if (
        ctx.runtime.should_rewrite_after_self_check(
            _current_turn_question(state, ctx),
            state.get("query_plan", {}),
            answer_query_result,
            evidences,
            check,
        )
        and not state.get("answer_rewritten", False)
        and state.get("current_answer", "").strip()
    ):
        rewritten = ctx.runtime.rewrite_answer(
            question=_current_turn_question(state, ctx),
            sql=state.get("sql", ""),
            query_plan=state.get("query_plan", {}),
            query_result=answer_query_result,
            evidences=evidences,
            previous_answer=state.get("current_answer", ""),
            self_check=check,
        )
        rewritten_check = ctx.runtime.self_check(
            question=_current_turn_question(state, ctx),
            answer=rewritten,
            sql_rows=answer_query_result.to_dict(orient="records"),
            evidences=evidences,
        )
        return {
            **state,
            "current_answer": rewritten,
            "self_check": rewritten_check,
            "answer_rewritten": True,
            "notes": state.get("notes", []) + ["answer_rewritten_after_self_check"],
        }
    return {**state, "self_check": check}


def generate_answer_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    question_text = _current_turn_question(state, ctx)
    if state.get("needs_clarification"):
        answer = ctx.runtime.generate_clarification(question_text, state.get("missing_slots", []))
        return {**state, "current_answer": answer, "current_references": []}
    query_result = ctx.runtime.sanitize_query_result_for_answer(
        question_text,
        _result_dataframe(state),
    )
    answer = ctx.runtime.generate_answer(
        question=question_text,
        sql=state.get("sql", ""),
        query_plan=state.get("query_plan", {}),
        query_result=query_result,
        evidences=state.get("reranked_evidence", []) or state.get("retrieved_evidence", []),
    )
    evidence_source = state.get("reranked_evidence", []) or state.get("retrieved_evidence", [])
    references = ctx.runtime.build_references(
        evidence_source,
        question=question_text,
        limit=5,
    )
    if state.get("reuse_prior_context") and not references and state.get("turn_answers"):
        last_turn_refs = list(state.get("turn_answers", [])[-1].get("A", {}).get("references", []) or [])
        references = last_turn_refs[:5]
    derived_companies = ctx.runtime.derive_companies_from_evidences(
        state.get("reranked_evidence", []) or state.get("retrieved_evidence", []),
        question=question_text,
    )
    return {
        **state,
        "current_answer": answer,
        "current_references": references,
        "context_companies": list(dict.fromkeys((state.get("context_companies", []) or []) + derived_companies)),
    }


def append_turn_result_node(state: Task3GraphState, ctx: Task3NodeContext) -> Task3GraphState:
    turn_answers = list(state.get("turn_answers", []))
    turn_answers.append(
        {
            "Q": state.get("current_question", ""),
            "A": {
                "content": state.get("current_answer", ""),
                "image": state.get("current_chart_paths", []),
                "references": state.get("current_references", []),
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


def _refine_follow_up_periods(current_question: str, periods: list[str], prior_rows: list[dict[str, object]]) -> list[str]:
    if "同期" not in current_question:
        return list(periods or [])
    prior_period = ""
    for row in prior_rows or []:
        if not isinstance(row, dict):
            continue
        for key in ["report_period", "报告期", "current_period", "base_period"]:
            value = str(row.get(key, "") or "").strip()
            if len(value) >= 6 and value[:4].isdigit():
                prior_period = value
                break
        if prior_period:
            break
    if not prior_period:
        return list(periods or [])
    suffix = prior_period[4:]
    refined: list[str] = []
    for period in periods or []:
        period_str = str(period)
        if period_str.endswith("FY") and re.search(r"\d{4}年同期", current_question):
            refined.append(f"{period_str[:4]}{suffix}")
        else:
            refined.append(period_str)
    if not refined:
        year_match = re.search(r"(\d{4})年同期", current_question)
        if year_match:
            refined.append(f"{year_match.group(1)}{suffix}")
    return list(dict.fromkeys(refined))


REQUIRED_CHART_TOKENS = ["可视化", "绘图", "画图", "图表", "柱状图", "折线图", "饼图", "雷达图", "散点图", "直方图", "箱线图"]
OPTIONAL_SKIP_TOKENS = ["为什么", "原因", "依据", "判断依据", "你确定"]
METRIC_FIELD_ALIASES = {
    "营业总收入": "total_operating_revenue",
    "主营业务收入": "total_operating_revenue",
    "收入": "total_operating_revenue",
    "净利润": "net_profit",
    "利润总额": "total_profit",
    "应收账款": "accounts_receivable",
    "应收账款占比": "accounts_receivable_ratio",
    "股东权益总额": "total_equity",
    "总资产": "total_assets",
    "货币资金": "asset_cash_and_cash_equivalents",
    "短期借款": "liability_short_term_loans",
    "销售费用": "selling_expenses",
    "管理费用": "administrative_expenses",
    "财务费用": "financial_expenses",
    "税金及附加": "taxes_and_surcharges",
    "营业成本": "operating_cost",
    "研发费用占比": "rnd_expense_ratio",
    "毛利率": "gross_profit_margin",
    "净利率": "net_profit_margin",
}


def _build_task3_chart_plan(question_text: str, dataframe: pd.DataFrame, query_plan: dict[str, object]) -> ChartPlan | None:
    requires_chart = any(token in question_text for token in REQUIRED_CHART_TOKENS)
    if not requires_chart and any(token in question_text for token in OPTIONAL_SKIP_TOKENS):
        return None
    preferred_chart_type = _infer_required_chart_type(question_text)
    preferred_metric_field = _preferred_metric_field(query_plan, dataframe, question_text)
    preferred_metric_name = None
    metrics = list(query_plan.get("metrics", []) or [])
    if metrics:
        preferred_metric_name = str(metrics[0])
    plan = build_default_chart_plan(
        question_text,
        dataframe,
        preferred_chart_type=preferred_chart_type,
        preferred_metric_field=preferred_metric_field,
        preferred_metric_name=preferred_metric_name,
    )
    if plan is None and requires_chart:
        plan = _fallback_required_chart_plan(dataframe, preferred_metric_field, preferred_metric_name)
    if plan is None:
        return None
    if requires_chart:
        plan.should_draw = True
    return plan


def _infer_required_chart_type(question_text: str) -> str | None:
    if "饼图" in question_text:
        return "pie"
    if any(token in question_text for token in ["柱状图", "条形图"]):
        return "bar"
    if any(token in question_text for token in ["折线图", "趋势", "近三年", "近3年", "近几年"]):
        return "line"
    if any(token in question_text for token in ["表格", "列表"]):
        return "table"
    return None


def _preferred_metric_field(query_plan: dict[str, object], dataframe: pd.DataFrame, question_text: str) -> str | None:
    for metric in list(query_plan.get("metrics", []) or []):
        field = METRIC_FIELD_ALIASES.get(str(metric), str(metric))
        if field in dataframe.columns:
            return field
    for alias, field in METRIC_FIELD_ALIASES.items():
        if alias in question_text and field in dataframe.columns:
            return field
    preferred_order = [
        "total_operating_revenue",
        "net_profit",
        "total_profit",
        "gross_profit_margin",
        "net_profit_margin",
        "accounts_receivable",
        "total_assets",
        "total_equity",
    ]
    for field in preferred_order:
        if field in dataframe.columns:
            return field
    numeric_cols = [
        col for col in dataframe.columns if pd.api.types.is_numeric_dtype(dataframe[col]) and col not in {"report_year"}
    ]
    return numeric_cols[0] if numeric_cols else None


def _fallback_required_chart_plan(
    dataframe: pd.DataFrame,
    preferred_metric_field: str | None,
    preferred_metric_name: str | None,
) -> ChartPlan | None:
    if preferred_metric_field and "report_period" in dataframe.columns and dataframe["report_period"].nunique() >= 2:
        return ChartPlan(
            chart_type="line",
            title=(preferred_metric_name or preferred_metric_field) + "趋势",
            x_field="report_period",
            y_fields=[preferred_metric_field],
            sort_by="report_period",
            should_draw=True,
        )
    if preferred_metric_field and "report_year" in dataframe.columns and dataframe["report_year"].nunique() >= 2:
        return ChartPlan(
            chart_type="line",
            title=(preferred_metric_name or preferred_metric_field) + "趋势",
            x_field="report_year",
            y_fields=[preferred_metric_field],
            sort_by="report_year",
            should_draw=True,
        )
    category_field = "stock_abbr" if "stock_abbr" in dataframe.columns else None
    numeric_fields = [
        col for col in dataframe.columns if pd.api.types.is_numeric_dtype(dataframe[col]) and col not in {"report_year"}
    ]
    if len(dataframe) == 1 and len(numeric_fields) >= 2:
        return ChartPlan(
            chart_type="bar",
            title=(preferred_metric_name or "指标") + "对比",
            category_field=category_field,
            y_fields=numeric_fields[:4],
            should_draw=True,
        )
    if preferred_metric_field and category_field:
        return ChartPlan(
            chart_type="bar",
            title=(preferred_metric_name or preferred_metric_field) + "对比",
            category_field=category_field,
            y_fields=[preferred_metric_field],
            sort_by=preferred_metric_field,
            sort_ascending=False,
            top_n=min(12, len(dataframe)),
            should_draw=True,
        )
    return None
