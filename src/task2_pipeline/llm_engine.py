from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from .catalog import METRIC_SPECS
from .charting import build_default_chart_plan, chart_type_to_label, refine_chart_plan_with_llm, render_chart
from .llm_client import OpenAICompatibleClient, extract_json_object
from .models import ParsedIntent, QuestionRecord


SAFE_SQL_PREFIXES = ("select", "with")
FORBIDDEN_SQL_TOKENS = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "attach ", "pragma ")


class LLMQueryEngine:
    def __init__(
        self,
        source_database_url: str,
        cache_db_path: Path,
        llm_client: OpenAICompatibleClient,
        result_dir: Path,
        artifacts_dir: Path | None = None,
    ) -> None:
        self.source_database_url = source_database_url
        self.cache_db_path = cache_db_path
        self.llm_client = llm_client
        self.result_dir = result_dir
        self.artifacts_dir = artifacts_dir
        self.schema_text = ""
        self.company_count = 0
        self._prepare_query_cache()

    def _prepare_query_cache(self) -> None:
        engine = create_engine(self.source_database_url)
        income = pd.read_sql_table("income_sheet", engine)
        kpi = pd.read_sql_table("core_performance_indicators_sheet", engine)
        balance = pd.read_sql_table("balance_sheet", engine)
        cash = pd.read_sql_table("cash_flow_sheet", engine)

        key = ["stock_code", "report_period", "report_year"]
        wide = income.merge(
            kpi.drop(columns=["stock_abbr"], errors="ignore"),
            on=key,
            how="outer",
            suffixes=("_income", "_kpi"),
        )
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
        }.items():
            merged = None
            for candidate in candidates:
                if candidate in wide.columns:
                    merged = wide[candidate] if merged is None else merged.fillna(wide[candidate])
            if merged is not None:
                wide[target] = merged

        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.cache_db_path)
        wide.to_sql("financials_view", conn, if_exists="replace", index=False)
        conn.close()
        self.company_count = int(wide["stock_code"].astype(str).nunique()) if "stock_code" in wide.columns else 0
        self.schema_text = self._build_schema_text(wide)

    def _build_schema_text(self, dataframe: pd.DataFrame) -> str:
        lines = ["financials_view columns:"]
        for col, dtype in dataframe.dtypes.items():
            lines.append(f"- {col}: {dtype}")
        lines.extend(
            [
                "",
                "Common business meanings:",
                "- total_operating_revenue: 营业总收入(万元)",
                "- net_profit: 净利润(万元)",
                "- total_profit: 利润总额(万元)",
                "- asset_liability_ratio: 资产负债率(%)",
                "- operating_cf_net_amount: 经营性现金流量净额(万元)",
                "- gross_profit_margin: 销售毛利率(%)",
                "- net_profit_margin: 销售净利率(%)",
                "- roe: 净资产收益率(%)",
                "- report_period values: 2022FY, 2023Q1, 2023H1, 2023Q3, 2023FY ...",
                f"- financials_view already contains the full universe of {self.company_count} listed Chinese medicine companies; do not use stock_abbr LIKE '%中药%' or similar fuzzy name filters to represent the whole industry/universe.",
            ]
        )
        return "\n".join(lines)

    def answer(
        self,
        question: QuestionRecord,
        intent: ParsedIntent,
        image_index: int = 1,
        chart_question_text: str | None = None,
    ) -> tuple[str, str, str, str, str, int, str]:
        sql, query_result, attempts, note = self._execute_with_retry(question)
        answer = self._generate_answer(question, sql, query_result)
        preview = query_result.head(20).to_json(force_ascii=False, orient="records")
        chart_plan = self._plan_chart(question, sql, query_result, intent, chart_question_text=chart_question_text)
        chart_path = render_chart(
            self.result_dir,
            question.question_id,
            query_result.head(50),
            chart_plan,
            image_index=image_index,
            html_dir=(self.artifacts_dir / "pyecharts_html") if self.artifacts_dir else None,
        ) if chart_plan and chart_plan.should_draw else ""
        graph_format = chart_type_to_label(chart_plan.chart_type) if chart_plan and chart_path else "无"
        return sql, answer, preview, chart_path, graph_format, attempts, note

    def _generate_sql(
        self,
        question: QuestionRecord,
        previous_sql: str | None = None,
        previous_error: str | None = None,
    ) -> tuple[str, str]:
        system_prompt = (
            "You are a financial NL2SQL assistant. "
            "Generate a single safe SQLite SELECT query over financials_view only. "
            "Return strict JSON: {\"sql\": \"...\", \"reason\": \"...\"}. "
            "Never use markdown. "
            "Never output anything except JSON. "
            "Only use columns that exist in the provided schema. "
            "Prefer explicit column names, aliases, ORDER BY, LIMIT where useful. "
            "For vague wording, infer a reasonable financial interpretation. "
            "Use report_period values like 2025Q3, 2024FY. "
            "When the question refers to all 66 Chinese medicine listed companies, the whole industry, or industry averages, query the whole financials_view for the period instead of filtering stock_abbr by words like '中药' or '药业'."
        )
        user_prompt = (
            f"{self.schema_text}\n\n"
            f"Question ID: {question.question_id}\n"
            f"Question Type: {question.question_type}\n"
            f"Question Text: {question.raw_question}\n"
        )
        if previous_sql or previous_error:
            user_prompt += (
                "\nPrevious attempt information:\n"
                f"- previous_sql: {previous_sql or ''}\n"
                f"- previous_error: {previous_error or ''}\n"
                "Please repair the SQL and return corrected JSON only.\n"
            )
        response = self.llm_client.chat(system_prompt, user_prompt, temperature=0.0)
        payload = extract_json_object(response)
        sql = str(payload["sql"]).strip()
        self._validate_sql(sql)
        reason = str(payload.get("reason", "")).strip()
        return sql, reason

    def _validate_sql(self, sql: str) -> None:
        lowered = re.sub(r"\s+", " ", sql.strip().lower())
        if not lowered.startswith(SAFE_SQL_PREFIXES):
            raise ValueError(f"Only SELECT/CTE queries are allowed, got: {sql}")
        if "financials_view" not in lowered:
            raise ValueError("SQL must query financials_view.")
        for token in FORBIDDEN_SQL_TOKENS:
            if token in lowered:
                raise ValueError(f"Forbidden SQL token detected: {token}")

    def _run_sql(self, sql: str) -> pd.DataFrame:
        conn = sqlite3.connect(self.cache_db_path)
        try:
            df = pd.read_sql_query(sql, conn)
        finally:
            conn.close()
        return df

    def _execute_with_retry(self, question: QuestionRecord, max_attempts: int = 3) -> tuple[str, pd.DataFrame, int, str]:
        previous_sql = None
        previous_error = None
        last_reason = ""
        for attempt in range(1, max_attempts + 1):
            try:
                sql, reason = self._generate_sql(
                    question,
                    previous_sql=previous_sql,
                    previous_error=previous_error,
                )
                last_reason = reason
                result = self._run_sql(sql)
                self._validate_result(question, sql, result)
                return sql, result, attempt, f"llm_sql_ok: {reason or f'attempt={attempt}'}"
            except Exception as exc:
                previous_error = str(exc)
                if "sql" in locals():
                    previous_sql = sql
                last_reason = previous_error
        raise RuntimeError(f"LLM SQL generation failed after {max_attempts} attempts: {last_reason}")

    def _generate_answer(self, question: QuestionRecord, sql: str, query_result: pd.DataFrame) -> str:
        records = query_result.head(50).to_dict(orient="records")
        system_prompt = (
            "You are a financial analysis assistant. "
            "Use the SQL result to answer the user's question in Chinese. "
            "Be concise, factual, and avoid making up unavailable data."
        )
        user_prompt = (
            f"Question: {question.raw_question}\n"
            f"SQL: {sql}\n"
            f"Result rows (JSON): {json.dumps(records, ensure_ascii=False)}\n"
            "Please provide a direct answer in Chinese."
        )
        return self.llm_client.chat(system_prompt, user_prompt, temperature=0.2).strip()

    def _plan_chart(
        self,
        question: QuestionRecord,
        sql: str,
        query_result: pd.DataFrame,
        intent: ParsedIntent,
        chart_question_text: str | None = None,
    ):
        preferred_metric_field = None
        preferred_metric_name = None
        for metric in intent.metrics:
            if metric in METRIC_SPECS:
                preferred_metric_field = METRIC_SPECS[metric].field_name
                preferred_metric_name = METRIC_SPECS[metric].display_name
                break
        default_plan = build_default_chart_plan(
            chart_question_text or question.raw_question,
            query_result,
            preferred_chart_type=intent.chart_type,
            preferred_metric_field=preferred_metric_field,
            preferred_metric_name=preferred_metric_name,
        )
        if default_plan is None:
            return None
        if self._should_keep_default_chart_plan(question, query_result, default_plan):
            return default_plan
        return refine_chart_plan_with_llm(
            self.llm_client,
            chart_question_text or question.raw_question,
            sql,
            query_result.head(50),
            default_plan,
        )

    def _should_keep_default_chart_plan(self, question: QuestionRecord, query_result: pd.DataFrame, default_plan) -> bool:
        numeric_cols = [col for col in query_result.columns if pd.to_numeric(query_result[col], errors="coerce").notna().sum() > 0]
        text = question.raw_question
        if any(token in text for token in ["双条形图", "双柱状图", "折线图", "趋势图", "水平柱状图"]):
            return True
        if default_plan.chart_type in {"bar", "barh", "line"} and len(numeric_cols) <= 2 and len(query_result.columns) <= 4:
            return True
        return False

    def _validate_result(self, question: QuestionRecord, sql: str, result: pd.DataFrame) -> None:
        text = question.raw_question
        lowered_sql = sql.lower()
        broad_scope = any(token in text for token in ["66家", "中药上市公司", "中药公司", "行业均值", "行业平均", "所有上市公司", "哪些公司", "哪些企业"])
        ranking_like = any(token in text for token in ["前十", "前五", "前三", "top", "排名"])
        trend_like = any(token in text for token in ["趋势", "变化", "走势", "2022-", "2023-", "2024-", "2025-"])
        compare_periods = "2024Q3" in lowered_sql and "2025Q3" in lowered_sql or ("2024年第三季度" in text and "2025年第三季度" in text)

        if broad_scope and ("like '%中药%'" in lowered_sql or "like '%药业%'" in lowered_sql or "like '%中医%'" in lowered_sql):
            raise ValueError("Broad-scope queries must not use fuzzy stock_abbr LIKE filters such as '%中药%' or '%药业%'.")

        if broad_scope and "stock_abbr" in result.columns and result["stock_abbr"].dropna().nunique() <= 1 and len(result) <= 2:
            raise ValueError("Broad-scope query returned too few companies; likely filtered the universe incorrectly.")

        expected_min_rows = 3
        if "前十" in text or "top10" in text.lower():
            expected_min_rows = 8
        elif "前五" in text or "top5" in text.lower():
            expected_min_rows = 4
        elif "前三" in text or "top3" in text.lower():
            expected_min_rows = 3
        if ranking_like and len(result) < expected_min_rows:
            raise ValueError("Ranking query returned too few rows; likely did not retrieve the requested top list.")

        if trend_like:
            if "report_period" in result.columns and result["report_period"].dropna().nunique() < 2:
                raise ValueError("Trend query returned fewer than 2 periods, which is insufficient for a trend chart.")
            if len(result) < 2 and "report_period" not in result.columns:
                raise ValueError("Trend query returned too few rows.")
            if any(token in text for token in ["近3年", "三年", "3年"]) and "report_period" in result.columns and result["report_period"].dropna().nunique() < 3:
                raise ValueError("Multi-year trend query returned fewer than 3 periods.")

        if compare_periods and "report_period" in result.columns and result["report_period"].dropna().nunique() < 2:
            raise ValueError("Comparison query should contain at least two report periods.")

        numeric_frame = result.apply(pd.to_numeric, errors="coerce")
        if not numeric_frame.empty and numeric_frame.notna().sum().sum() > 0:
            if numeric_frame.fillna(0).abs().sum().sum() == 0:
                raise ValueError("Query result is numerically empty/all zero, likely not suitable for answering or charting.")
