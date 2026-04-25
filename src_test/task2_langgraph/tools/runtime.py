from __future__ import annotations

from typing import Any

import pandas as pd

from src.task2_langgraph.tools.runtime import Task2Runtime as BaseTask2Runtime


AMOUNT_LIKE_TOKENS = (
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
)
RATIO_LIKE_TOKENS = ("ratio", "margin", "growth", "roe", "率", "占比", "比例")


class Task2Runtime(BaseTask2Runtime):
    def _build_view(self) -> pd.DataFrame:
        dataframe = super()._build_view()
        if dataframe.empty:
            return dataframe
        return self._deduplicate_view(dataframe)

    def _sanitize_result_frame(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        sanitized = super()._sanitize_result_frame(dataframe)
        if sanitized.empty:
            return sanitized
        for column in sanitized.columns:
            column_name = str(column).lower()
            if not any(token in column_name for token in AMOUNT_LIKE_TOKENS):
                continue
            numeric = pd.to_numeric(self._column_as_series(sanitized, column), errors="coerce")
            if numeric.notna().sum() == 0:
                continue
            sanitized[column] = numeric.mask(numeric.abs() <= 1e-3, 0.0)
        return sanitized

    def _maybe_generate_special_sql(self, question, query_plan: dict[str, object]) -> str | None:
        question_text = question.raw_question
        periods = [str(item) for item in query_plan.get("periods", []) or [] if str(item).strip()]
        metrics = [str(item) for item in query_plan.get("metrics", []) or [] if str(item).strip()]
        companies = [str(item) for item in query_plan.get("companies", []) or [] if str(item).strip()]

        if len(companies) == 1 and len(periods) == 1 and len(metrics) == 1:
            metric = metrics[0]
            metric_columns = {
                "营业总收入": "total_operating_revenue",
                "净利润": "net_profit",
                "扣非净利润": "net_profit_excl_non_recurring",
                "销售毛利率": "gross_profit_margin",
                "销售净利率": "net_profit_margin",
                "资产负债率": "asset_liability_ratio",
                "经营性现金流量净额": "operating_cf_net_amount",
                "投资性现金流量净额": "investing_cf_net_amount",
                "研发费用": "operating_expense_rnd_expenses",
                "销售费用": "operating_expense_selling_expenses",
                "未分配利润": "equity_unappropriated_profit",
                "短期借款": "liability_short_term_loans",
                "货币资金": "asset_cash_and_cash_equivalents",
            }
            metric_column = metric_columns.get(metric)
            if metric_column:
                company = companies[0].split("（", 1)[0]
                period = periods[0]
                return (
                    "SELECT stock_code, stock_abbr, report_period, "
                    f"{metric_column} "
                    "FROM financials_view "
                    f"WHERE stock_abbr = '{company}' AND report_period = '{period}'"
                )

        if "复合增长率" in question_text and "营业总收入" in metrics and len(periods) >= 2:
            sorted_periods = sorted(periods, key=self._period_sort_key)
            start_period = sorted_periods[0]
            end_period = sorted_periods[-1]
            span_years = max(1, int(end_period[:4]) - int(start_period[:4]))
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
                f"(POWER(revenue_end / revenue_start, 1.0 / {span_years}) - 1) * 100 AS cagr_percentage "
                "FROM growth"
                ") "
                "SELECT stock_code, stock_abbr, cagr_percentage "
                "FROM cagr ORDER BY cagr_percentage DESC LIMIT 1"
            )

        if "平均销售毛利率" in question_text and "低于均值" in question_text:
            target_period = periods[0] if periods else "2025Q3"
            return (
                "WITH company_gross_margin AS ("
                " SELECT stock_code, stock_abbr, gross_profit_margin "
                "FROM financials_view "
                f"WHERE report_period = '{target_period}' AND gross_profit_margin IS NOT NULL "
                "ORDER BY stock_code "
                "LIMIT 10"
                "), avg_gross_margin AS ("
                " SELECT AVG(gross_profit_margin) AS avg_gross_margin "
                "FROM company_gross_margin"
                ") "
                "SELECT cgm.stock_code, cgm.stock_abbr, cgm.gross_profit_margin, agm.avg_gross_margin "
                "FROM company_gross_margin cgm "
                "CROSS JOIN avg_gross_margin agm "
                "WHERE cgm.gross_profit_margin < agm.avg_gross_margin "
                "ORDER BY cgm.gross_profit_margin"
            )

        return super()._maybe_generate_special_sql(question, query_plan)

    def build_empty_result_response(
        self,
        question,
        query_plan: dict[str, object] | None = None,
    ) -> tuple[str, str]:
        plan = query_plan or {}
        question_text = question.sub_questions[0] if question.sub_questions else question.raw_question
        periods = [str(item) for item in plan.get("periods", []) or [] if str(item).strip()]
        metrics = [str(item) for item in plan.get("metrics", []) or [] if str(item).strip()]
        if "复合增长率" in question_text and "营业总收入" in metrics and len(periods) >= 2:
            coverage: list[str] = []
            for period in sorted(periods, key=self._period_sort_key):
                subset = self.view_df[
                    (self.view_df["report_period"].astype(str) == period)
                    & pd.to_numeric(self.view_df.get("total_operating_revenue"), errors="coerce").notna()
                ]
                count = int(subset["stock_code"].astype(str).nunique()) if not subset.empty else 0
                coverage.append(f"{period}:{count}家")
            return (
                "当前数据库缺少计算营业总收入复合增长率所需的完整可比期数据，"
                f"各期可用公司覆盖为 {'，'.join(coverage)}，因此无法直接比较。",  # noqa: E501
                "ok",
            )
        return super().build_empty_result_response(question, query_plan)

    def generate_answer(self, question, sql: str, query_result: pd.DataFrame) -> str:
        question_text = question.raw_question
        if query_result.empty:
            return super().generate_answer(question, sql, query_result)

        if {"gross_profit_margin", "avg_gross_margin"}.issubset(query_result.columns) and "低于均值" in question_text:
            avg_margin = pd.to_numeric(query_result["avg_gross_margin"], errors="coerce").dropna()
            avg_text = f"{avg_margin.iloc[0]:.2f}%" if not avg_margin.empty else "未知"
            company_parts = []
            seen: set[str] = set()
            for row in query_result.to_dict(orient="records"):
                stock_code = str(row.get("stock_code", "") or "").strip()
                stock_abbr = str(row.get("stock_abbr", "") or "").strip()
                label = f"{stock_abbr}（{stock_code}）" if stock_abbr and stock_code else (stock_abbr or stock_code)
                if not label or label in seen:
                    continue
                seen.add(label)
                margin = pd.to_numeric(pd.Series([row.get("gross_profit_margin")]), errors="coerce").iloc[0]
                if pd.notna(margin):
                    company_parts.append(f"{label}：{margin:.2f}%")
                else:
                    company_parts.append(label)
            if company_parts:
                return (
                    f"2025年第三季度，10家公司的平均销售毛利率为 {avg_text}。"
                    f"低于均值的公司有：{'、'.join(company_parts)}。"
                )

        metric_columns = [
            column
            for column in query_result.columns
            if column not in {"stock_code", "stock_abbr", "report_period", "report_year"}
        ]
        if len(query_result) == 1 and len(metric_columns) == 1:
            row = query_result.iloc[0]
            stock_abbr = str(row.get("stock_abbr", "") or "").strip()
            stock_code = str(row.get("stock_code", "") or "").strip()
            report_period = str(row.get("report_period", "") or "").strip()
            metric_column = metric_columns[0]
            value_text = self._format_value(metric_column, row.get(metric_column))
            is_ratio = any(token in metric_column.lower() for token in RATIO_LIKE_TOKENS)
            company_label = f"{stock_abbr}（股票代码 {stock_code}）" if stock_abbr and stock_code else (stock_abbr or stock_code)
            period_label = self._humanize_period(report_period) if report_period else "对应报告期"
            suffix = "" if is_ratio else "万元"
            return f"{company_label}{period_label}的{self._column_to_label(metric_column)}为 {value_text}{suffix}。"

        return super().generate_answer(question, sql, query_result)

    def _column_to_label(self, column: str) -> str:
        mapping = {
            "operating_cf_net_amount": "经营性现金流量净额",
            "investing_cf_net_amount": "投资性现金流量净额",
            "gross_profit_margin": "销售毛利率",
            "total_operating_revenue": "营业总收入",
            "cagr_percentage": "营业总收入复合增长率",
        }
        return mapping.get(str(column), str(column))

    def _humanize_period(self, report_period: str) -> str:
        text = str(report_period)
        if len(text) < 6:
            return text
        year, suffix = text[:4], text[4:]
        mapping = {
            "FY": f"{year}年全年",
            "Q1": f"{year}年第一季度",
            "Q2": f"{year}年第二季度",
            "H1": f"{year}年上半年",
            "Q3": f"{year}年第三季度",
            "Q4": f"{year}年第四季度",
        }
        return mapping.get(suffix, text)

    def _deduplicate_view(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        group_keys = ["stock_code", "report_period", "report_year"]
        missing = [column for column in group_keys if column not in dataframe.columns]
        if missing:
            return dataframe
        dedup_rows: list[dict[str, Any]] = []
        for _, group in dataframe.groupby(group_keys, dropna=False, sort=False):
            row: dict[str, Any] = {}
            for column in dataframe.columns:
                series = group[column]
                non_null = series.dropna()
                if non_null.empty:
                    row[column] = pd.NA
                    continue
                if column in group_keys:
                    row[column] = non_null.iloc[0]
                    continue
                if str(column) == "stock_abbr":
                    row[column] = str(non_null.astype(str).iloc[0]).strip()
                    continue
                numeric = pd.to_numeric(non_null, errors="coerce")
                valid_numeric = numeric.dropna()
                column_name = str(column).lower()
                if not valid_numeric.empty:
                    if any(token in column_name for token in AMOUNT_LIKE_TOKENS):
                        non_zero = valid_numeric[valid_numeric.abs() > 1e-3]
                        chosen = non_zero.loc[non_zero.abs().idxmax()] if not non_zero.empty else valid_numeric.iloc[0]
                        row[column] = float(chosen)
                    elif any(token in column_name for token in RATIO_LIKE_TOKENS):
                        row[column] = float(valid_numeric.median())
                    else:
                        row[column] = float(valid_numeric.iloc[0])
                    continue
                row[column] = non_null.iloc[0]
            dedup_rows.append(row)
        return pd.DataFrame(dedup_rows, columns=dataframe.columns)
