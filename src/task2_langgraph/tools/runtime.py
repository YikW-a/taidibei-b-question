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
    "利润总额": ["total_profit"],
    "销售毛利率": ["gross_profit_margin"],
    "销售净利率": ["net_profit_margin"],
    "ROE": ["roe"],
    "资产负债率": ["asset_liability_ratio"],
    "经营性现金流量净额": ["operating_cf_net_amount"],
    "投资性现金流量净额": ["investing_cf_net_amount"],
    "货币资金": ["asset_cash_and_cash_equivalents"],
    "短期借款": ["liability_short_term_loans"],
    "未分配利润": ["equity_unappropriated_profit"],
    "研发费用": ["operating_expense_rnd_expenses"],
    "研发费用占比": ["rnd_expense_ratio"],
    "存货周转率": ["inventory_turnover_ratio"],
    "营业总收入增长率": ["operating_revenue_yoy_growth"],
}


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
        system_prompt = self.prompt_manager.load("sql_generation_system")
        user_prompt = (
            f"{self._schema_text()}\n\n"
            f"Question: {question.raw_question}\n"
            f"Query plan: {json.dumps(query_plan or {}, ensure_ascii=False)}\n"
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
            return self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()
        except Exception:
            return "请补充查询所需的关键信息。"

    def deterministic_listing_answer(self, question_text: str, query_result: pd.DataFrame) -> str:
        if query_result.empty:
            return "未查询到符合条件的数据，或当前条件下结果为空。"
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
        return "\n".join(lines) if lines else "未查询到符合条件的数据，或当前条件下结果为空。"

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
            token in question_text for token in ["列出", "展示", "同步输出", "具体数值", "请展示", "表格", "名单", "分别是多少"]
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

    def _relevant_result_columns(self, query_plan: dict[str, object], dataframe: pd.DataFrame) -> list[str]:
        metric_to_columns = {
            "营业总收入": ["total_operating_revenue", "营业总收入"],
            "净利润": ["net_profit", "net_profit_2025", "净利润", "ratio"],
            "未分配利润": ["equity_unappropriated_profit", "unappropriated_profit", "未分配利润"],
            "销售毛利率": ["gross_profit_margin", "销售毛利率"],
            "销售净利率": ["net_profit_margin", "销售净利率"],
            "ROE": ["roe", "净资产收益率", "收益率"],
            "资产负债率": ["asset_liability_ratio", "资产负债率"],
            "经营性现金流量净额": ["operating_cf_net_amount", "经营性现金流量净额"],
            "投资性现金流量净额": ["investing_cf_net_amount", "投资性现金流量净额"],
            "货币资金": ["asset_cash_and_cash_equivalents", "货币资金"],
            "短期借款": ["liability_short_term_loans", "短期借款"],
            "研发费用": ["operating_expense_rnd_expenses", "研发费用"],
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
