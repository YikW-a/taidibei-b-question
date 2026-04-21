from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from ..config.settings import Task2LangGraphConfig
from ..schemas import QuestionRecord, Task2GraphState
from ..services import IntentParser
from ..tools import Task2Runtime, build_chart_spec, render_chart_from_spec, save_chart_spec
from ..tools.charts import ChartPlan, build_default_chart_plan, chart_type_to_label, refine_chart_plan_with_llm


CHART_REQUEST_TOKENS = (
    "图",
    "绘制",
    "表格",
    "趋势图",
    "折线图",
    "柱状图",
    "条形图",
    "水平柱状图",
    "双条形图",
    "双柱状图",
    "饼图",
    "散点图",
    "直方图",
    "箱线图",
    "雷达图",
)


class Task2NodeContext:
    def __init__(self, config: Task2LangGraphConfig) -> None:
        self.config = config
        self.runtime = Task2Runtime(config)
        self.intent_parser: IntentParser = self.runtime.intent_parser

    def get_question(self, question_id: str) -> QuestionRecord:
        return self.runtime.get_question(question_id)


def initialize_state(question_id: str, ctx: Task2NodeContext) -> Task2GraphState:
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
        "all_chart_paths": [],
        "all_chart_specs": [],
        "graph_formats": [],
        "sql_history": [],
        "context_companies": [],
        "context_rows": [],
        "notes": [],
        "final_status": "running",
    }


def parse_question_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    question = ctx.get_question(state["question_id"])
    turn_index = state.get("current_turn_index", 0)
    current_question = question.sub_questions[turn_index]
    cumulative_question = " | ".join(question.sub_questions[: turn_index + 1])
    intent = ctx.intent_parser.parse_text(cumulative_question)
    current_question = question.sub_questions[turn_index]
    if (
        not intent.companies
        and state.get("context_companies")
        and any(token in current_question for token in ["这些公司", "这些企业", "上述公司", "上述企业", "这些", "上述"])
    ):
        intent.companies = list(state.get("context_companies", []))
    parsed_slots = {
        "companies": intent.companies,
        "stock_codes": intent.stock_codes,
        "periods": intent.periods,
        "metrics": intent.metrics,
        "chart_type": intent.chart_type,
        "intent_type": intent.intent_type,
        "top_n": intent.top_n,
        "threshold": intent.threshold,
    }
    return {
        **state,
        "current_question": current_question,
        "cumulative_question": cumulative_question,
        "parsed_slots": parsed_slots,
        "notes": state.get("notes", []) + list(intent.notes),
        "sql": "",
        "sql_error": "",
        "sql_attempts": 0,
        "result_preview": "",
        "result_rows": [],
        "result_row_count": 0,
        "chart_plan": {},
        "chart_spec": {},
        "current_chart_paths": [],
        "current_chart_specs": [],
        "current_answer": "",
    }


def clarify_or_continue_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    parsed = state.get("parsed_slots", {})
    text = state.get("current_question", "")
    cumulative = state.get("cumulative_question", text)
    intent_type = str(parsed.get("intent_type") or "")

    missing: list[str] = []
    has_chart_request = any(token in text for token in CHART_REQUEST_TOKENS)
    broad_scope_tokens = (
        "66家",
        "中药上市公司",
        "所有公司",
        "全部公司",
        "行业",
        "公司中",
        "哪些公司",
        "前十",
        "前五",
        "前三",
        "排名",
        "统计",
        "均值",
        "平均",
        "最高",
        "最低",
        "top",
    )
    broad_scope_company_patterns = (
        "哪些公司",
        "有哪些公司",
        "公司有哪些",
        "公司中",
        "公司里",
        "公司按",
        "公司，",
        "公司,",
    )
    is_broad_scope = (
        any(token in cumulative.lower() for token in [token.lower() for token in broad_scope_tokens])
        or any(token in cumulative for token in broad_scope_company_patterns)
        or parsed.get("top_n") is not None
        or intent_type in {"ranking", "filter", "period_stat", "comparison"}
        or (
            "公司" in cumulative
            and not parsed.get("companies")
            and (parsed.get("metrics") or parsed.get("periods"))
            and (parsed.get("chart_type") or intent_type in {"trend_or_chart", "filter", "ranking", "comparison"})
        )
    )
    if (
        not parsed.get("companies")
        and not is_broad_scope
        and any(token in cumulative for token in ["股份", "药业", "白药", "药", "公司"])
    ):
        missing.append("company")
    if (
        not parsed.get("periods")
        and parsed.get("companies")
        and parsed.get("metrics")
        and state.get("total_turns", 1) > 1
        and state.get("current_turn_index", 0) < state.get("total_turns", 1) - 1
        and not any(token in cumulative for token in ["去年", "今年", "近3年", "近三年", "最近", "历年"])
    ):
        missing.append("period")
    if not parsed.get("periods") and any(token in cumulative for token in ["季度", "年度", "前年", "去年", "今年", "报告期", "第三季度", "前三季度"]):
        if not any(token in cumulative for token in ["近3年", "近三年", "2022-", "2023-", "2024-", "2025-"]):
            missing.append("period")
    if not parsed.get("metrics") and any(token in cumulative for token in ["收入", "利润", "毛利率", "净利率", "现金流", "负债率", "收益率"]):
        missing.append("metric")
    if has_chart_request and not parsed.get("metrics"):
        missing.append("metric")

    return {
        **state,
        "missing_slots": list(dict.fromkeys(missing)),
        "needs_clarification": bool(missing),
    }


def build_query_plan_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    parsed = state.get("parsed_slots", {})
    plan = ctx.runtime.build_query_plan(
        _current_turn_question(state, ctx),
        parsed,
        context_companies=state.get("context_companies", []),
        context_rows=state.get("context_rows", []),
    )
    return {**state, "query_plan": plan}


def generate_sql_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    if state.get("needs_clarification"):
        return state
    question = _current_turn_question(state, ctx)
    sql, reason = ctx.runtime.generate_sql(
        question,
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
        "sql_attempts": state.get("sql_attempts", 0) + 1,
        "notes": state.get("notes", []) + ([reason] if reason else []),
    }


def execute_sql_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    if state.get("needs_clarification"):
        return state
    try:
        df = ctx.runtime.run_sql(state.get("sql", ""))
        df = ctx.runtime.postprocess_result(_current_turn_question(state, ctx), state.get("query_plan", {}), df)
        ctx.runtime.validate_result(_current_turn_question(state, ctx), state.get("sql", ""), df)
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
        return {
            **state,
            "sql_error": str(exc),
            "final_status": "sql_error",
        }


def plan_chart_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    if state.get("needs_clarification"):
        return state
    dataframe = _result_dataframe(state)
    if dataframe.empty:
        return state
    parsed = state.get("parsed_slots", {})
    question_text = state.get("current_question", "")
    try:
        preferred_metrics = state.get("query_plan", {}).get("metrics") or parsed.get("metrics", [])
        preferred_metric_name = preferred_metrics[0] if preferred_metrics else None
        preferred_chart_type = state.get("query_plan", {}).get("chart_type") or parsed.get("chart_type")
        plan = build_default_chart_plan(
            question_text,
            dataframe,
            preferred_chart_type=preferred_chart_type,
            preferred_metric_field=None,
            preferred_metric_name=preferred_metric_name,
        )
        if plan is not None and preferred_chart_type != "scatter":
            try:
                plan = refine_chart_plan_with_llm(
                    ctx.runtime.llm_client,
                    ctx.runtime.prompt_manager.load("chart_plan_system"),
                    question_text,
                    state.get("sql", ""),
                    dataframe.head(50),
                    plan,
                )
            except Exception:
                pass
        if plan is None:
            return state
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
        }
    except Exception as exc:
        return {**state, "notes": state.get("notes", []) + [f"chart_plan_failed={repr(exc)}"], "chart_plan": {}}


def render_chart_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    plan_dict = state.get("chart_plan") or {}
    if not plan_dict or state.get("needs_clarification"):
        return state
    dataframe = _result_dataframe(state)
    if dataframe.empty:
        return state
    try:
        plan = ChartPlan(
            chart_type=str(plan_dict["chart_type"]),
            title=str(plan_dict["title"]),
            x_field=plan_dict.get("x_field"),
            y_fields=list(plan_dict.get("y_fields") or []),
            category_field=plan_dict.get("category_field"),
            sort_by=plan_dict.get("sort_by"),
            sort_ascending=bool(plan_dict.get("sort_ascending", True)),
            top_n=plan_dict.get("top_n"),
            should_draw=bool(plan_dict.get("should_draw", True)),
        )
    except Exception:
        return state
    try:
        image_index = state.get("current_turn_index", 0) + 1
        chart_spec = build_chart_spec(
            state["question_id"],
            dataframe.head(50),
            plan,
            image_index=image_index,
            sql=state.get("sql", ""),
        )
        current_specs: list[str] = []
        chart_spec_dict: dict[str, object] = {}
        if chart_spec is not None:
            spec_path = save_chart_spec(ctx.config.chart_spec_dir, chart_spec)
            current_specs = [str(spec_path)]
            chart_spec_dict = chart_spec.to_dict()
        chart_path = ""
        if chart_spec is not None:
            chart_path = render_chart_from_spec(
                ctx.config.result_dir,
                dataframe.head(50),
                chart_spec,
            )
        current_paths = [f"./result/{Path(chart_path).name}"] if chart_path else []
        graph_formats = list(state.get("graph_formats", []))
        if chart_path:
            label = chart_type_to_label(plan.chart_type)
            if label != "无" and label not in graph_formats:
                graph_formats.append(label)
        return {
            **state,
            "chart_spec": chart_spec_dict,
            "current_chart_specs": current_specs,
            "all_chart_specs": state.get("all_chart_specs", []) + current_specs,
            "current_chart_paths": current_paths,
            "all_chart_paths": state.get("all_chart_paths", []) + current_paths,
            "graph_formats": graph_formats,
        }
    except Exception as exc:
        return {**state, "notes": state.get("notes", []) + [f"render_chart_failed={repr(exc)}"]}


def generate_answer_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    if state.get("needs_clarification"):
        answer = ctx.runtime.generate_clarification(_current_turn_question(state, ctx), state.get("missing_slots", []))
        return {**state, "current_answer": answer, "final_status": "ok"}
    if state.get("current_answer"):
        return {**state, "final_status": "ok"}
    question = _current_turn_question(state, ctx)
    dataframe = _result_dataframe(state)
    if not dataframe.empty:
        try:
            answer = ctx.runtime.generate_answer(question, state.get("sql", ""), dataframe)
            return {**state, "current_answer": answer, "final_status": "ok"}
        except Exception as exc:
            fallback = ctx.runtime.deterministic_listing_answer(question.raw_question, dataframe)
            return {
                **state,
                "current_answer": fallback,
                "final_status": "warning",
                "notes": state.get("notes", []) + [f"generate_answer_failed={repr(exc)}"],
            }
    if state.get("sql"):
        return {
            **state,
            "current_answer": "未查询到符合条件的数据，或当前条件下结果为空。",
            "final_status": "warning",
        }
    return {**state, "current_answer": "当前轮次未生成有效回答。", "final_status": "warning"}


def append_turn_result_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    turn_answers = state.get("turn_answers", [])
    turn_answers.append(
        {
            "Q": state.get("current_question", ""),
            "A": {
                "content": state.get("current_answer", ""),
                "image": state.get("current_chart_paths", []),
            },
        }
    )
    return {**state, "turn_answers": turn_answers}


def export_result_node(state: Task2GraphState, ctx: Task2NodeContext) -> Task2GraphState:
    return {
        **state,
        "answer_json": json.dumps(state.get("turn_answers", []), ensure_ascii=False),
        "graph_format_text": "；".join(state.get("graph_formats", [])) if state.get("graph_formats") else "无",
        "final_status": state.get("final_status", "ok"),
    }


def prototype_manual_run(question_id: str, config: Task2LangGraphConfig) -> Task2GraphState:
    ctx = Task2NodeContext(config)
    state = initialize_state(question_id, ctx)
    for turn_index in range(state["total_turns"]):
        state["current_turn_index"] = turn_index
        for node in [
            parse_question_node,
            clarify_or_continue_node,
            build_query_plan_node,
            generate_sql_node,
            execute_sql_node,
            plan_chart_node,
            render_chart_node,
            generate_answer_node,
            append_turn_result_node,
        ]:
            state = node(state, ctx)
    state = export_result_node(state, ctx)
    return state


def _current_turn_question(state: Task2GraphState, ctx: Task2NodeContext) -> QuestionRecord:
    base = ctx.get_question(state["question_id"])
    cumulative = state.get("cumulative_question", state.get("current_question", ""))
    current = state.get("current_question", "")
    return replace(
        base,
        raw_question=cumulative,
        sub_questions=[current],
        original_question_json=json.dumps([{"Q": current}], ensure_ascii=False),
    )


def _result_dataframe(state: Task2GraphState) -> pd.DataFrame:
    return pd.DataFrame(state.get("result_rows", []))
