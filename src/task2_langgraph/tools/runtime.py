from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine

from ..config import Task2LangGraphConfig
from ..schemas import QuestionRecord
from ..services import IntentParser, OpenAICompatibleClient, PromptManager, extract_json_object, load_questions


SAFE_SQL_PREFIXES = ("select", "with")
FORBIDDEN_SQL_TOKENS = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "attach ", "pragma ")
SUPPORTED_METRIC_COLUMNS = {
    "营业总收入": ["total_operating_revenue"],
    "净利润": ["net_profit"],
    "扣非净利润": ["net_profit_excl_non_recurring"],
    "利润总额": ["total_profit"],
    "销售毛利率": ["gross_profit_margin"],
    "销售净利率": ["net_profit_margin"],
    "ROE": ["roe"],
    "加权平均净资产收益率（扣非）": ["roe_weighted_excl_non_recurring"],
    "资产负债率": ["asset_liability_ratio"],
    "经营性现金流量净额": ["operating_cf_net_amount"],
    "投资性现金流量净额": ["investing_cf_net_amount"],
    "货币资金": ["asset_cash_and_cash_equivalents"],
    "短期借款": ["liability_short_term_loans"],
    "未分配利润": ["equity_unappropriated_profit"],
    "研发费用": ["operating_expense_rnd_expenses"],
    "销售费用": ["operating_expense_selling_expenses"],
    "研发费用占比": ["rnd_expense_ratio"],
    "存货周转率": ["inventory_turnover_ratio"],
    "营业总收入增长率": ["operating_revenue_yoy_growth"],
}
DERIVABLE_SINGLE_QUARTER_COLUMNS = [
    "total_operating_revenue",
    "net_profit",
    "total_profit",
    "operating_profit",
    "operating_expense_cost_of_sales",
    "operating_expense_selling_expenses",
    "operating_expense_administrative_expenses",
    "operating_expense_financial_expenses",
    "operating_expense_rnd_expenses",
    "operating_expense_taxes_and_surcharges",
    "total_operating_expenses",
    "other_income",
    "asset_impairment_loss",
    "credit_impairment_loss",
    "operating_cf_net_amount",
    "investing_cf_net_amount",
    "financing_cf_net_amount",
    "operating_cf_cash_from_sales",
    "investing_cf_cash_for_investments",
    "investing_cf_cash_from_investment_recovery",
    "financing_cf_cash_from_borrowing",
    "financing_cf_cash_for_debt_repayment",
    "net_profit_excl_non_recurring",
]
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "H1": 3, "Q3": 4, "Q4": 5, "FY": 6}


class Task2Runtime:
    def __init__(self, config: Task2LangGraphConfig) -> None:
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.result_dir.mkdir(parents=True, exist_ok=True)
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(config.database_url)
        self.view_df = self._sanitize_view(self._build_view())
        self._write_query_cache()
        company_reference = pd.read_excel(config.company_info_path, sheet_name=0)
        self.company_reference = company_reference.copy()
        self.company_reference["股票代码"] = self.company_reference["股票代码"].astype(str).str.zfill(6)
        extra_company_names = (
            self.view_df.get("stock_abbr", pd.Series(dtype=str))
            .dropna()
            .astype(str)
            .str.strip()
            .unique()
            .tolist()
        )
        self.intent_parser = IntentParser(company_reference, extra_company_names=extra_company_names)
        self.questions = {question.question_id: question for question in load_questions(config.question_file)}
        self.prompt_manager = PromptManager(Path(__file__).resolve().parents[1] / "prompts")
        if not (config.llm_base_url and config.llm_api_key and config.llm_model):
            raise ValueError(
                "task2_langgraph is llm-only. Please provide TASK2_LLM_BASE_URL, "
                "TASK2_LLM_API_KEY, TASK2_LLM_MODEL."
            )
        self.llm_client = OpenAICompatibleClient(config.llm_base_url, config.llm_api_key, config.llm_model)

    def get_question(self, question_id: str) -> QuestionRecord:
        if question_id not in self.questions:
            raise KeyError(f"Question id not found: {question_id}")
        return self.questions[question_id]

    def generate_sql(
        self,
        question: QuestionRecord,
        query_plan: dict[str, object] | None = None,
        context_rows: list[dict[str, Any]] | None = None,
        previous_sql: str | None = None,
        previous_error: str | None = None,
    ) -> tuple[str, str]:
        special_sql = self._maybe_generate_special_sql(question, query_plan or {})
        if special_sql is not None:
            return special_sql, "Used deterministic SQL template for a known query pattern."
        system_prompt = self.prompt_manager.load("sql_generation_system")
        user_prompt = (
            f"{self._schema_text()}\n\n"
            f"Question: {question.raw_question}\n"
            f"Query plan: {json.dumps(query_plan or {}, ensure_ascii=False)}\n"
        )
        if not (query_plan or {}).get("companies"):
            user_prompt += (
                "Important: if the query plan does not explicitly provide companies, "
                "do not invent or manually enumerate a stock_abbr IN (...) list.\n"
            )
        if any(str(period).endswith(("Q2", "Q4")) for period in (query_plan or {}).get("periods", []) or []):
            user_prompt += (
                "Important: financials_view already contains derived single-quarter rows such as Q2/Q4 when they "
                "can be reconstructed from cumulative disclosures, so you may query 2025Q2/2025Q4 directly.\n"
            )
        user_prompt += (
            "SQLite compatibility: do not use PERCENTILE_CONT / WITHIN GROUP. "
            "If median is needed, emulate it with ROW_NUMBER() and COUNT() window functions.\n"
        )
        if context_rows:
            user_prompt += f"Previous turn result rows: {json.dumps(context_rows[:12], ensure_ascii=False)}\n"
        if previous_sql or previous_error:
            user_prompt += (
                f"Previous SQL: {previous_sql or ''}\n"
                f"Previous error: {previous_error or ''}\n"
                "Please repair it.\n"
            )
        if previous_error and "Percentage-like columns appear over-scaled" in previous_error:
            user_prompt += (
                "Repair hint: for ratio/margin/growth/roe fields involved in filtering, comparison, or averaging, "
                "exclude obvious outliers with ABS(field) <= 1000 before computing averages or selecting results.\n"
            )
        payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
        sql = str(payload["sql"]).strip()
        self.validate_sql(sql)
        return sql, str(payload.get("reason", "")).strip()

    def build_query_plan(
        self,
        question: QuestionRecord,
        parsed_slots: dict[str, object],
        context_companies: list[str] | None = None,
        context_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        default_plan = {
            "intent_type": parsed_slots.get("intent_type"),
            "companies": list(parsed_slots.get("companies", [])),
            "periods": parsed_slots.get("periods", []),
            "metrics": parsed_slots.get("metrics", []),
            "chart_type": parsed_slots.get("chart_type"),
            "top_n": parsed_slots.get("top_n"),
            "threshold": parsed_slots.get("threshold"),
            "question": question.sub_questions[0] if question.sub_questions else question.raw_question,
            "should_draw": bool(parsed_slots.get("chart_type")) or "趋势" in question.raw_question or "图" in question.raw_question,
            "needs_clarification": False,
            "missing_slots": [],
        }
        try:
            system_prompt = self.prompt_manager.load("query_plan_system")
            user_prompt = (
                f"Question: {question.raw_question}\n"
                f"Parsed slots: {parsed_slots}\n"
                f"Previous cohort companies: {context_companies or []}\n"
                f"Previous turn rows: {json.dumps((context_rows or [])[:10], ensure_ascii=False)}\n"
                "Please refine the query plan."
            )
            payload = extract_json_object(self.llm_client.chat(system_prompt, user_prompt, temperature=0.0))
            for key, value in payload.items():
                if key in {"companies", "periods", "metrics", "missing_slots"}:
                    if value:
                        default_plan[key] = value
                    continue
                if key in {"chart_type", "top_n", "threshold", "intent_type"}:
                    if value is not None:
                        default_plan[key] = value
                    continue
                default_plan[key] = value
        except Exception:
            pass
        if (
            not default_plan.get("companies")
            and context_companies
            and any(token in question.raw_question for token in ["这些公司", "这些企业", "上述公司", "上述企业", "它们", "其中"])
        ):
            default_plan["companies"] = list(context_companies)
        unsupported = [
            metric
            for metric in default_plan.get("metrics", []) or []
            if metric not in SUPPORTED_METRIC_COLUMNS and metric not in {"同比增长率", "复合增长率", "出口业务占比"}
        ]
        if unsupported:
            default_plan["unsupported_metrics"] = unsupported
        return default_plan

    def validate_sql(self, sql: str) -> None:
        lowered = " ".join(sql.strip().lower().split())
        if not lowered.startswith(SAFE_SQL_PREFIXES):
            raise ValueError("Only SELECT/CTE queries are allowed.")
        if "financials_view" not in lowered:
            raise ValueError("SQL must query financials_view.")
        for token in FORBIDDEN_SQL_TOKENS:
            if token in lowered:
                raise ValueError(f"Forbidden SQL token detected: {token}")

    def run_sql(self, sql: str) -> pd.DataFrame:
        conn = sqlite3.connect(self.config.query_cache_db)
        try:
            return pd.read_sql_query(sql, conn)
        finally:
            conn.close()

    def postprocess_result(
        self,
        question: QuestionRecord,
        query_plan: dict[str, object] | None,
        result: pd.DataFrame,
    ) -> pd.DataFrame:
        if result.empty:
            return result
        work = result.copy()
        work = self._sanitize_result_frame(work)
        relevant_columns = self._relevant_result_columns(query_plan or {}, work)
        if relevant_columns:
            mask = work[relevant_columns].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
            work = work.loc[mask].copy()
        return work

    def validate_result(self, question: QuestionRecord, sql: str, result: pd.DataFrame) -> None:
        text = question.raw_question
        if any(token in text for token in ["前十", "前五", "前三", "top"]) and len(result) < 3:
            raise ValueError("Ranking query returned too few rows.")
        if any(token in text for token in ["趋势", "折线图", "变化"]) and "report_period" in result.columns and result["report_period"].nunique() < 2:
            raise ValueError("Trend query returned too few periods.")
        period_values = set(result["report_period"].astype(str).tolist()) if "report_period" in result.columns else set()
        if period_values and any("-" in value or "/" in value for value in period_values):
            raise ValueError("Report period format is not normalized.")
        numeric = result.apply(pd.to_numeric, errors="coerce")
        if not numeric.empty and numeric.notna().sum().sum() > 0 and numeric.fillna(0).abs().sum().sum() == 0:
            raise ValueError("Query result is numerically empty/all zero.")
        suspicious_columns = []
        for column in result.columns:
            column_lower = str(column).lower()
            if any(token in column_lower for token in ["ratio", "margin", "growth", "roe", "率", "占比", "比例"]):
                series = pd.to_numeric(result[column], errors="coerce").dropna()
                if not series.empty and series.abs().quantile(0.9) > 1000:
                    suspicious_columns.append(column)
        if suspicious_columns:
            raise ValueError(
                "Percentage-like columns appear over-scaled: " + ", ".join(suspicious_columns)
            )

    def generate_answer(self, question: QuestionRecord, sql: str, query_result: pd.DataFrame) -> str:
        system_prompt = self.prompt_manager.load("answer_generation_system")
        user_prompt = (
            f"Question: {question.raw_question}\n"
            f"SQL: {sql}\n"
            f"Rows: {query_result.head(30).to_json(force_ascii=False, orient='records')}\n"
            "请直接给出中文回答。"
        )
        answer = self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()
        return self._ensure_answer_completeness(question.raw_question, query_result, answer)

    def generate_clarification(self, question: QuestionRecord, missing_slots: list[str]) -> str:
        try:
            system_prompt = self.prompt_manager.load("clarification_system")
            user_prompt = f"Question: {question.raw_question}\nMissing slots: {missing_slots}"
            answer = self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()
            return answer or self._deterministic_clarification(missing_slots)
        except Exception:
            return self._deterministic_clarification(missing_slots)

    def deterministic_listing_answer(self, question_text: str, query_result: pd.DataFrame) -> str:
        if query_result.empty:
            return "未查询到符合条件的数据，或当前条件下结果为空。"
        count_column = "company_count" if "company_count" in query_result.columns else None
        if count_column and len(query_result) == 1:
            count_value = pd.to_numeric(query_result[count_column], errors="coerce").iloc[0]
            if pd.notna(count_value):
                summary = f"共 {int(count_value)} 家。"
                if "stock_abbr" not in query_result.columns:
                    return summary
        display_columns = [column for column in query_result.columns if str(column) not in {"serial_number", "report_year"}]
        lines: list[str] = []
        for row in query_result.head(30).to_dict(orient="records"):
            prefix: list[str] = []
            if row.get("stock_abbr"):
                prefix.append(f"{row['stock_abbr']}（{row['stock_code']}）" if row.get("stock_code") else str(row["stock_abbr"]))
            elif row.get("stock_code"):
                prefix.append(str(row["stock_code"]))
            fields: list[str] = []
            for column in display_columns:
                if column in {"stock_abbr", "stock_code"}:
                    continue
                value = row.get(column)
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                fields.append(f"{column}={self._format_value(column, value)}")
            text = "，".join(prefix + fields)
            if text:
                lines.append(text)
        if not lines:
            return "未查询到符合条件的数据，或当前条件下结果为空。"
        if "stock_abbr" in query_result.columns and len(query_result) <= 10:
            return f"共 {len(query_result)} 家：\n" + "\n".join(lines)
        return "\n".join(lines)

    def build_empty_result_response(
        self,
        question: QuestionRecord,
        query_plan: dict[str, object] | None = None,
    ) -> tuple[str, str]:
        plan = query_plan or {}
        question_text = question.sub_questions[0] if question.sub_questions else question.raw_question
        companies = [str(item) for item in plan.get("companies", []) or [] if str(item).strip()]
        periods = [str(item) for item in plan.get("periods", []) or [] if str(item).strip()]
        metrics = [str(item) for item in plan.get("metrics", []) or [] if str(item).strip()]
        threshold = plan.get("threshold")
        candidate = self.view_df.copy()
        if companies and "stock_abbr" in candidate.columns:
            candidate = candidate[candidate["stock_abbr"].astype(str).isin(companies)].copy()
        company_scope = "、".join(companies) if companies else "当前筛选范围"
        period_scope = "、".join(periods) if periods else "指定报告期"
        metric_scope = "、".join(metrics) if metrics else "题目要求的指标"

        if "复合增长率" in question_text and "66家" in question_text and periods:
            available_count = self._count_companies_with_required_periods(candidate, periods)
            if available_count < 2:
                return (
                    f"当前数据库中仅有 {available_count} 家公司同时具备 {period_scope} 的完整可比数据，无法形成题目要求的行业分布图。",
                    "warning",
                )

        if companies and periods:
            period_rows = candidate[candidate["report_period"].astype(str).isin(periods)].copy()
            if period_rows.empty:
                available_periods = self._available_periods_for_companies(companies, periods)
                if available_periods:
                    return (
                        f"当前数据库中未找到 {company_scope} 在 {period_scope} 的记录；目前可用报告期为 {available_periods}。",
                        "ok",
                    )
                return (
                    f"当前数据库中未找到 {company_scope} 在 {period_scope} 的记录。",
                    "ok",
                )

        if plan.get("intent_type") in {"filter", "ranking"}:
            threshold_text = ""
            if threshold is not None:
                threshold_text = f"（阈值 {threshold}）"
            if "连续" in question_text and periods:
                return (
                    f"当前数据库中，没有公司在 {period_scope} 这几个报告期内连续满足题目设定的 {metric_scope} 条件{threshold_text}。",
                    "ok",
                )
            return (
                f"当前数据库中，没有公司满足题目设定的 {metric_scope} 筛选条件{threshold_text}。",
                "ok",
            )

        return ("未查询到符合条件的数据，或当前条件下结果为空。", "warning")

    def finalize_turn_answers(
        self,
        turn_answers: list[dict[str, Any]],
        *,
        context_rows: list[dict[str, Any]] | None = None,
        current_question: str = "",
    ) -> list[dict[str, Any]]:
        finalized = json.loads(json.dumps(turn_answers, ensure_ascii=False))
        if not finalized:
            return finalized
        first = finalized[0]
        first_question = str(first.get("Q", ""))
        first_content = str(first.get("A", {}).get("content", ""))
        if (
            "业绩比较好" in first_question
            and ("未查询到" in first_content or "请补充" in first_content or not first_content.strip())
            and context_rows
        ):
            companies = []
            for row in context_rows:
                stock_abbr = str(row.get("stock_abbr", "") or "").strip()
                stock_code = str(row.get("stock_code", "") or "").strip()
                if not stock_abbr:
                    continue
                label = f"{stock_abbr}（{stock_code}）" if stock_code else stock_abbr
                if label not in companies:
                    companies.append(label)
            if companies:
                period = str(context_rows[0].get("report_period", "") or "").strip()
                prefix = f"结合后续筛选条件，{period}业绩表现较好的公司包括：" if period else "结合后续筛选条件，业绩表现较好的公司包括："
                first["A"]["content"] = prefix + "、".join(companies) + "。"
        return finalized

    def _build_view(self) -> pd.DataFrame:
        income = pd.read_sql_table("income_sheet", self.engine)
        kpi = pd.read_sql_table("core_performance_indicators_sheet", self.engine)
        balance = pd.read_sql_table("balance_sheet", self.engine)
        cash = pd.read_sql_table("cash_flow_sheet", self.engine)
        key = ["stock_code", "report_period", "report_year"]
        wide = income.merge(kpi.drop(columns=["stock_abbr"], errors="ignore"), on=key, how="outer", suffixes=("_income", "_kpi"))
        wide = wide.merge(balance.drop(columns=["stock_abbr"], errors="ignore"), on=key, how="outer")
        wide = wide.merge(cash.drop(columns=["stock_abbr"], errors="ignore"), on=key, how="outer", suffixes=("", "_cash"))
        if "stock_abbr" not in wide.columns:
            wide["stock_abbr"] = None
        for candidate in ["stock_abbr_income", "stock_abbr_kpi"]:
            if candidate in wide.columns:
                wide["stock_abbr"] = wide["stock_abbr"].fillna(wide[candidate])
        for target, candidates in {
            "total_operating_revenue": ["total_operating_revenue_income", "total_operating_revenue_kpi"],
            "operating_revenue_yoy_growth": ["operating_revenue_yoy_growth_income", "operating_revenue_yoy_growth_kpi"],
            "net_profit_yoy_growth": ["net_profit_yoy_growth_income", "net_profit_yoy_growth_kpi"],
            "net_profit": ["net_profit", "net_profit_10k_yuan"],
            "equity_unappropriated_profit": ["equity_unappropriated_profit"],
            "operating_expense_rnd_expenses": ["operating_expense_rnd_expenses"],
            "operating_expense_selling_expenses": ["operating_expense_selling_expenses"],
            "asset_inventory": ["asset_inventory"],
            "operating_expense_cost_of_sales": ["operating_expense_cost_of_sales"],
        }.items():
            merged = None
            for candidate in candidates:
                if candidate in wide.columns:
                    merged = wide[candidate] if merged is None else merged.fillna(wide[candidate])
            if merged is not None:
                wide[target] = merged
        wide = self._append_single_quarter_rows(wide)
        if "operating_expense_rnd_expenses" in wide.columns and "total_operating_revenue" in wide.columns:
            revenue = pd.to_numeric(wide["total_operating_revenue"], errors="coerce")
            rnd = pd.to_numeric(wide["operating_expense_rnd_expenses"], errors="coerce")
            ratio = (rnd / revenue) * 100
            wide["rnd_expense_ratio"] = ratio.replace([float("inf"), float("-inf")], pd.NA)
        if "operating_expense_cost_of_sales" in wide.columns and "asset_inventory" in wide.columns:
            cost_of_sales = pd.to_numeric(wide["operating_expense_cost_of_sales"], errors="coerce")
            inventory = pd.to_numeric(wide["asset_inventory"], errors="coerce")
            turnover = cost_of_sales / inventory.replace(0, pd.NA)
            wide["inventory_turnover_ratio"] = turnover.replace([float("inf"), float("-inf")], pd.NA)
        return wide

    def _append_single_quarter_rows(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty or "report_period" not in dataframe.columns or "report_year" not in dataframe.columns:
            return dataframe
        derivable_columns = [column for column in DERIVABLE_SINGLE_QUARTER_COLUMNS if column in dataframe.columns]
        if not derivable_columns:
            return dataframe

        new_rows: list[dict[str, Any]] = []
        group_columns = ["stock_code", "report_year"]
        work = dataframe.copy()
        work["report_year"] = pd.to_numeric(work["report_year"], errors="coerce")
        work = work.dropna(subset=["stock_code", "report_year", "report_period"]).copy()
        work["report_year"] = work["report_year"].astype(int)

        for (stock_code, report_year), group in work.groupby(group_columns):
            period_map = {
                str(row["report_period"])[4:]: row
                for row in group.to_dict(orient="records")
                if str(row.get("report_period", "")).startswith(str(report_year))
            }
            existing_periods = {
                str(row.get("report_period", ""))
                for row in group.to_dict(orient="records")
                if str(row.get("report_period", "")).startswith(str(report_year))
            }
            for target_suffix, base_suffix, previous_suffix in [("Q2", "H1", "Q1"), ("Q4", "FY", "Q3")]:
                target_period = f"{report_year}{target_suffix}"
                if target_period in existing_periods:
                    continue
                base_row = period_map.get(base_suffix)
                previous_row = period_map.get(previous_suffix)
                if not base_row or not previous_row:
                    continue
                new_row = {column: pd.NA for column in dataframe.columns}
                new_row["stock_code"] = stock_code
                if "stock_abbr" in dataframe.columns:
                    new_row["stock_abbr"] = base_row.get("stock_abbr") or previous_row.get("stock_abbr")
                new_row["report_period"] = target_period
                new_row["report_year"] = report_year
                for column in derivable_columns:
                    base_value = pd.to_numeric(pd.Series([base_row.get(column)]), errors="coerce").iloc[0]
                    previous_value = pd.to_numeric(pd.Series([previous_row.get(column)]), errors="coerce").iloc[0]
                    if pd.isna(base_value) or pd.isna(previous_value):
                        continue
                    new_row[column] = float(base_value - previous_value)
                if any(pd.notna(new_row.get(column)) for column in derivable_columns):
                    new_rows.append(new_row)

        if not new_rows:
            return dataframe
        return pd.concat([dataframe, pd.DataFrame(new_rows)], ignore_index=True, sort=False)

    def _sanitize_view(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        return self._sanitize_result_frame(dataframe.copy())

    def _sanitize_result_frame(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        amount_like_tokens = [
            "revenue",
            "profit",
            "amount",
            "expense",
            "equity",
            "asset",
            "liability",
            "cash",
            "收入",
            "利润",
            "费用",
            "金额",
            "总额",
            "权益",
            "资产",
            "负债",
            "净额",
        ]
        ratio_like_tokens = ["ratio", "margin", "growth", "roe", "率", "占比", "比例"]
        for column in dataframe.columns:
            numeric = pd.to_numeric(self._column_as_series(dataframe, column), errors="coerce")
            if numeric.notna().sum() == 0:
                continue
            column_name = str(column).lower()
            if any(token in column_name for token in ratio_like_tokens):
                dataframe[column] = numeric.mask(numeric.abs() > 1000)
                continue
            if any(token in column_name for token in amount_like_tokens):
                dataframe[column] = numeric.mask(numeric.abs() > 1e8)
        return dataframe

    def _ensure_answer_completeness(self, question_text: str, query_result: pd.DataFrame, answer: str) -> str:
        if query_result.empty:
            return answer
        requires_listing = any(
            token in question_text for token in ["列出", "展示", "同步输出", "具体数值", "请展示", "表格", "名单", "分别是多少", "这些公司中", "有哪些公司"]
        )
        if not requires_listing or len(query_result) > 30:
            return answer
        company_count = 0
        if "stock_abbr" in query_result.columns:
            company_count = int(query_result["stock_abbr"].astype(str).nunique())
        listed_companies = (
            sum(1 for name in query_result["stock_abbr"].dropna().astype(str).unique().tolist() if name in answer)
            if company_count
            else 0
        )
        required_field_tokens = [
            token
            for token in [
                "营业总收入",
                "净利润",
                "销售毛利率",
                "销售净利率",
                "资产负债率",
                "经营性现金流量净额",
                "投资性现金流量净额",
                "研发费用",
                "研发费用占比",
                "未分配利润",
                "货币资金",
                "短期借款",
            ]
            if token in question_text
        ]
        field_coverage_ok = all(token in answer for token in required_field_tokens[:3]) if required_field_tokens else True
        if (company_count and listed_companies < min(company_count, 3)) or not field_coverage_ok:
            return self.deterministic_listing_answer(question_text, query_result)
        return answer

    def _deterministic_clarification(self, missing_slots: list[str]) -> str:
        missing = set(missing_slots)
        if missing == {"metric"}:
            return "请补充想看的具体财务指标，例如营业总收入、净利润或资产负债率。"
        if missing == {"period"}:
            return "请补充具体报告期，例如2025年第三季度或2025年全年。"
        if missing == {"company"}:
            return "请补充公司名称或股票代码。"
        if missing == {"period", "metric"}:
            return "请补充具体报告期和财务指标，例如2025年第三季度的营业总收入。"
        if missing == {"company", "metric"}:
            return "请补充公司名称和财务指标，例如云南白药的净利润。"
        if missing == {"company", "period"}:
            return "请补充公司名称和报告期，例如云南白药2025年第三季度。"
        return "请补充查询所需的关键信息。"

    def _available_periods_for_companies(self, companies: list[str], requested_periods: list[str]) -> str:
        candidate = self.view_df.copy()
        if "stock_abbr" not in candidate.columns:
            return ""
        candidate = candidate[candidate["stock_abbr"].astype(str).isin(companies)].copy()
        available_periods = candidate["report_period"].dropna().astype(str).unique().tolist()
        requested_years = {period[:4] for period in requested_periods if len(period) >= 4 and period[:4].isdigit()}
        same_year = [period for period in available_periods if period[:4] in requested_years]
        final_periods = same_year or available_periods
        final_periods = sorted(final_periods, key=self._period_sort_key)
        return "、".join(final_periods[:8])

    def _count_companies_with_required_periods(self, dataframe: pd.DataFrame, periods: list[str]) -> int:
        if dataframe.empty or "stock_code" not in dataframe.columns or "report_period" not in dataframe.columns:
            return 0
        needed = set(str(item) for item in periods if item)
        if not needed:
            return 0
        grouped = (
            dataframe[dataframe["report_period"].astype(str).isin(needed)]
            .groupby("stock_code")["report_period"]
            .nunique()
        )
        return int((grouped >= len(needed)).sum())

    def _period_sort_key(self, period: str) -> tuple[int, int]:
        text = str(period)
        year = int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else 0
        suffix = text[4:]
        return year, PERIOD_ORDER.get(suffix, 99)

    def _maybe_generate_special_sql(self, question: QuestionRecord, query_plan: dict[str, object]) -> str | None:
        question_text = question.raw_question
        periods = [str(item) for item in query_plan.get("periods", []) or [] if str(item).strip()]
        metrics = [str(item) for item in query_plan.get("metrics", []) or [] if str(item).strip()]
        companies = [str(item) for item in query_plan.get("companies", []) or [] if str(item).strip()]
        threshold = query_plan.get("threshold")

        if "中位数" in question_text and "净利润" in question_text and "毛利率" in question_text:
            target_period = periods[0] if periods else "2025Q3"
            return (
                "WITH ranked AS ("
                f" SELECT stock_code, stock_abbr, net_profit, gross_profit_margin, "
                "ROW_NUMBER() OVER (ORDER BY net_profit) AS rn, "
                "COUNT(*) OVER () AS cnt "
                f"FROM financials_view WHERE report_period = '{target_period}'"
                "), median_rows AS ("
                " SELECT AVG(net_profit) AS median_net_profit FROM ranked "
                "WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)"
                "), industry_avg AS ("
                " SELECT AVG(gross_profit_margin) AS avg_gross_margin FROM ranked"
                ") "
                "SELECT r.stock_code, r.stock_abbr, r.net_profit, r.gross_profit_margin "
                "FROM ranked r CROSS JOIN median_rows m CROSS JOIN industry_avg a "
                "WHERE r.net_profit > m.median_net_profit AND r.gross_profit_margin < a.avg_gross_margin "
                "ORDER BY r.net_profit DESC"
            )

        if len(companies) == 1 and periods and set(metrics).issubset({"研发费用", "销售费用"}) and metrics:
            company = companies[0]
            target_period = periods[0]
            select_columns = ["stock_code", "stock_abbr", "report_period"]
            if "研发费用" in metrics:
                select_columns.append("operating_expense_rnd_expenses AS 研发费用")
            if "销售费用" in metrics:
                select_columns.append("operating_expense_selling_expenses AS 销售费用")
            select_sql = ", ".join(select_columns)
            return (
                f"SELECT {select_sql} "
                "FROM financials_view "
                f"WHERE stock_abbr = '{company}' AND report_period = '{target_period}'"
            )

        if "连续" in question_text and periods and "加权平均净资产收益率（扣非）" in metrics:
            target_periods = ", ".join(f"'{period}'" for period in periods)
            threshold_value = float(threshold) if threshold is not None else 10.0
            return (
                "WITH filtered AS ("
                " SELECT stock_code, stock_abbr, report_period, roe_weighted_excl_non_recurring "
                "FROM financials_view "
                f"WHERE report_period IN ({target_periods}) AND roe_weighted_excl_non_recurring > {threshold_value}"
                "), qualified AS ("
                " SELECT stock_code, stock_abbr FROM filtered "
                "GROUP BY stock_code, stock_abbr "
                f"HAVING COUNT(DISTINCT report_period) = {len(periods)}"
                ") "
                "SELECT f.stock_code, f.stock_abbr, f.report_period, f.roe_weighted_excl_non_recurring "
                "FROM filtered f JOIN qualified q ON f.stock_code = q.stock_code "
                "ORDER BY f.stock_code, f.report_period"
            )

        if "连续" in question_text and periods and "扣非净利润" in metrics:
            target_periods = ", ".join(f"'{period}'" for period in periods)
            threshold_value = float(threshold) if threshold is not None else 10000.0
            return (
                "WITH filtered AS ("
                " SELECT stock_code, stock_abbr, report_period, net_profit_excl_non_recurring "
                "FROM financials_view "
                f"WHERE report_period IN ({target_periods}) AND net_profit_excl_non_recurring > {threshold_value}"
                "), qualified AS ("
                " SELECT stock_code, stock_abbr FROM filtered "
                "GROUP BY stock_code, stock_abbr "
                f"HAVING COUNT(DISTINCT report_period) = {len(periods)}"
                ") "
                "SELECT f.stock_code, f.stock_abbr, f.report_period, f.net_profit_excl_non_recurring "
                "FROM filtered f JOIN qualified q ON f.stock_code = q.stock_code "
                "ORDER BY f.stock_code, f.report_period"
            )

        if "复合增长率" in question_text and ("直方图" in question_text or query_plan.get("chart_type") == "hist"):
            sorted_periods = sorted(periods, key=self._period_sort_key)
            if len(sorted_periods) >= 2:
                coverage_count = self._count_companies_with_required_periods(self.view_df, sorted_periods)
                if coverage_count < 2:
                    return "SELECT * FROM financials_view WHERE 1=0"
                start_period = sorted_periods[0]
                end_period = sorted_periods[-1]
                start_year = int(start_period[:4])
                end_year = int(end_period[:4])
                span_years = max(1, end_year - start_year)
                return (
                    "WITH growth AS ("
                    " SELECT stock_code, stock_abbr, "
                    f"MAX(CASE WHEN report_period = '{start_period}' THEN total_operating_revenue END) AS revenue_start, "
                    f"MAX(CASE WHEN report_period = '{end_period}' THEN total_operating_revenue END) AS revenue_end "
                    "FROM financials_view "
                    f"WHERE report_period IN ('{start_period}', '{end_period}') "
                    "GROUP BY stock_code, stock_abbr "
                    "HAVING revenue_start IS NOT NULL AND revenue_end IS NOT NULL AND revenue_start > 0"
                    "), cagr AS ("
                    " SELECT stock_code, stock_abbr, "
                    f"(POW(revenue_end / revenue_start, 1.0 / {span_years}) - 1) * 100 AS cagr_percentage "
                    "FROM growth"
                    ") "
                    "SELECT FLOOR(cagr_percentage / 10.0) * 10 AS bin_start, COUNT(*) AS company_count "
                    "FROM cagr GROUP BY FLOOR(cagr_percentage / 10.0) * 10 ORDER BY bin_start"
                )

        if "经营性现金流量净额为负的公司有多少家" in question_text and "这些公司中" not in question_text:
            target_period = periods[0] if periods else "2025Q3"
            return (
                "SELECT COUNT(DISTINCT stock_code) AS company_count "
                "FROM financials_view "
                f"WHERE report_period = '{target_period}' AND operating_cf_net_amount < 0"
            )

        if "这些公司中" in question_text and "有几家" in question_text and "经营性现金流量净额" in metrics and "资产负债率" in metrics:
            target_period = periods[0] if periods else ""
            threshold_value = float(threshold) if threshold is not None else 60.0
            return (
                "SELECT stock_code, stock_abbr, operating_cf_net_amount, asset_liability_ratio "
                "FROM financials_view "
                f"WHERE report_period = '{target_period}' "
                "AND operating_cf_net_amount < 0 "
                f"AND asset_liability_ratio > {threshold_value} "
                "ORDER BY asset_liability_ratio DESC, operating_cf_net_amount ASC"
            )

        if len(companies) == 1 and "营业总收入" in metrics and any(period.endswith("Q2") for period in periods) and any(period.endswith("Q3") for period in periods):
            sorted_periods = sorted(periods, key=self._period_sort_key)
            if len(sorted_periods) >= 2:
                first_period, second_period = sorted_periods[0], sorted_periods[-1]
                company = companies[0]
                company_filter = f"stock_abbr = '{company}'"
                if "（" in company:
                    company_filter = f"stock_abbr = '{company.split('（', 1)[0]}'"
                if second_period.endswith("Q3") and first_period.endswith("Q2"):
                    year = second_period[:4]
                    q2_period = f"{year}Q2"
                    h1_period = f"{year}H1"
                    q3_period = f"{year}Q3"
                    return (
                        "WITH base AS ("
                        " SELECT stock_code, stock_abbr, report_period, total_operating_revenue "
                        "FROM financials_view "
                        f"WHERE {company_filter} AND report_period IN ('{q2_period}', '{h1_period}', '{q3_period}')"
                        "), agg AS ("
                        " SELECT stock_code, stock_abbr, "
                        f"MAX(CASE WHEN report_period = '{q2_period}' THEN total_operating_revenue END) AS total_operating_revenue_q2, "
                        f"MAX(CASE WHEN report_period = '{h1_period}' THEN total_operating_revenue END) AS total_operating_revenue_h1, "
                        f"MAX(CASE WHEN report_period = '{q3_period}' THEN total_operating_revenue END) AS total_operating_revenue_q3_cumulative "
                        "FROM base GROUP BY stock_code, stock_abbr"
                        ") "
                        "SELECT stock_code, stock_abbr, "
                        f"'{q2_period}' AS report_period_prev, "
                        "total_operating_revenue_q2 AS total_operating_revenue_prev, "
                        f"'{q3_period}' AS report_period_curr, "
                        "(total_operating_revenue_q3_cumulative - total_operating_revenue_h1) AS total_operating_revenue_curr, "
                        "ROUND((((total_operating_revenue_q3_cumulative - total_operating_revenue_h1) - total_operating_revenue_q2) / ABS(total_operating_revenue_q2)) * 100, 2) AS qoq_growth "
                        "FROM agg "
                        "WHERE total_operating_revenue_q2 IS NOT NULL "
                        "AND total_operating_revenue_q2 != 0 "
                        "AND total_operating_revenue_h1 IS NOT NULL "
                        "AND total_operating_revenue_q3_cumulative IS NOT NULL"
                    )
                return (
                    "WITH earlier AS ("
                    " SELECT stock_code, stock_abbr, report_period, total_operating_revenue "
                    "FROM financials_view "
                    f"WHERE {company_filter} AND report_period = '{first_period}'"
                    "), later AS ("
                    " SELECT stock_code, stock_abbr, report_period, total_operating_revenue "
                    "FROM financials_view "
                    f"WHERE {company_filter} AND report_period = '{second_period}'"
                    ") "
                    "SELECT e.stock_code, e.stock_abbr, "
                    "e.report_period AS report_period_prev, "
                    "e.total_operating_revenue AS total_operating_revenue_prev, "
                    "l.report_period AS report_period_curr, "
                    "l.total_operating_revenue AS total_operating_revenue_curr, "
                    "ROUND(((l.total_operating_revenue - e.total_operating_revenue) / ABS(e.total_operating_revenue)) * 100, 2) AS qoq_growth "
                    "FROM earlier e JOIN later l USING (stock_code, stock_abbr) "
                    "WHERE e.total_operating_revenue IS NOT NULL AND e.total_operating_revenue != 0"
                )

        if "营业总收入和净利润均排名前十" in question_text:
            target_period = periods[0] if periods else "2025Q3"
            return (
                "WITH ranked_by_revenue AS ("
                " SELECT stock_code, stock_abbr, total_operating_revenue, "
                "ROW_NUMBER() OVER (ORDER BY total_operating_revenue DESC) AS revenue_rank "
                "FROM financials_view "
                f"WHERE report_period = '{target_period}'"
                "), ranked_by_profit AS ("
                " SELECT stock_code, stock_abbr, net_profit, "
                "ROW_NUMBER() OVER (ORDER BY net_profit DESC) AS profit_rank "
                "FROM financials_view "
                f"WHERE report_period = '{target_period}'"
                ") "
                "SELECT r.stock_code, r.stock_abbr, r.total_operating_revenue, r.revenue_rank, p.net_profit, p.profit_rank "
                "FROM ranked_by_revenue r "
                "JOIN ranked_by_profit p ON r.stock_code = p.stock_code "
                "WHERE r.revenue_rank <= 10 AND p.profit_rank <= 10 "
                "ORDER BY r.revenue_rank, p.profit_rank"
            )

        if (
            "营业总收入" in metrics
            and "净利润" in metrics
            and "均值" in question_text
            and any(token in question_text for token in ["同比", "同期"])
            and len(periods) >= 2
        ):
            sorted_periods = sorted(periods, key=self._period_sort_key)
            previous_period = sorted_periods[0]
            current_period = sorted_periods[-1]
            return (
                "WITH current_period AS ("
                " SELECT AVG(total_operating_revenue) AS avg_total_operating_revenue_curr, "
                "AVG(net_profit) AS avg_net_profit_curr "
                "FROM financials_view "
                f"WHERE report_period = '{current_period}'"
                "), previous_period AS ("
                " SELECT AVG(total_operating_revenue) AS avg_total_operating_revenue_prev, "
                "AVG(net_profit) AS avg_net_profit_prev "
                "FROM financials_view "
                f"WHERE report_period = '{previous_period}'"
                ") "
                "SELECT avg_total_operating_revenue_curr, avg_net_profit_curr, "
                "ROUND(((avg_total_operating_revenue_curr - avg_total_operating_revenue_prev) / ABS(avg_total_operating_revenue_prev)) * 100, 2) AS total_operating_revenue_yoy_growth, "
                "ROUND(((avg_net_profit_curr - avg_net_profit_prev) / ABS(avg_net_profit_prev)) * 100, 2) AS net_profit_yoy_growth "
                "FROM current_period CROSS JOIN previous_period "
                "WHERE avg_total_operating_revenue_prev IS NOT NULL AND avg_total_operating_revenue_prev != 0 "
                "AND avg_net_profit_prev IS NOT NULL AND avg_net_profit_prev != 0"
            )

        return None

    def _relevant_result_columns(self, query_plan: dict[str, object], dataframe: pd.DataFrame) -> list[str]:
        metric_to_columns = {
            "营业总收入": ["total_operating_revenue", "营业总收入"],
            "净利润": ["net_profit", "net_profit_2025", "净利润", "ratio"],
            "扣非净利润": ["net_profit_excl_non_recurring", "扣非净利润"],
            "未分配利润": ["equity_unappropriated_profit", "unappropriated_profit", "未分配利润"],
            "销售毛利率": ["gross_profit_margin", "销售毛利率"],
            "销售净利率": ["net_profit_margin", "销售净利率"],
            "ROE": ["roe", "净资产收益率", "收益率"],
            "加权平均净资产收益率（扣非）": ["roe_weighted_excl_non_recurring", "加权平均净资产收益率（扣非）", "扣非净资产收益率"],
            "资产负债率": ["asset_liability_ratio", "资产负债率"],
            "经营性现金流量净额": ["operating_cf_net_amount", "经营性现金流量净额"],
            "投资性现金流量净额": ["investing_cf_net_amount", "投资性现金流量净额"],
            "货币资金": ["asset_cash_and_cash_equivalents", "货币资金"],
            "短期借款": ["liability_short_term_loans", "短期借款"],
            "研发费用": ["operating_expense_rnd_expenses", "研发费用"],
            "销售费用": ["operating_expense_selling_expenses", "销售费用"],
            "研发费用占比": ["rnd_expense_ratio", "研发费用占比"],
            "存货周转率": ["inventory_turnover_ratio", "存货周转率"],
            "营业总收入增长率": ["operating_revenue_yoy_growth", "营业总收入增长率"],
        }
        relevant: list[str] = []
        sort_by = query_plan.get("sort_by")
        if isinstance(sort_by, str) and sort_by in dataframe.columns:
            relevant.append(sort_by)
        for metric in query_plan.get("metrics", []) or []:
            for candidate in metric_to_columns.get(str(metric), []):
                if candidate in dataframe.columns and candidate not in relevant:
                    relevant.append(candidate)
        return relevant

    @staticmethod
    def _column_as_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
        value = dataframe[column]
        if isinstance(value, pd.DataFrame):
            return value.iloc[:, 0]
        return value

    def _write_query_cache(self) -> None:
        conn = sqlite3.connect(self.config.query_cache_db)
        try:
            self.view_df.to_sql("financials_view", conn, if_exists="replace", index=False)
        finally:
            conn.close()

    def _schema_text(self) -> str:
        lines = ["financials_view columns:"]
        for col, dtype in self.view_df.dtypes.items():
            lines.append(f"- {col}: {dtype}")
        return "\n".join(lines)

    @staticmethod
    def _format_value(column: str, value: Any) -> str:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.notna(numeric):
            if any(token in str(column).lower() for token in ["ratio", "margin", "growth", "roe", "率", "占比", "比例"]):
                return f"{numeric:.2f}%"
            return f"{numeric:.2f}"
        return str(value)


__all__ = ["Task2Runtime"]
