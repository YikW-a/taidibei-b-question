from __future__ import annotations

import math
import re
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import create_engine

from .catalog import COMMON_COMPANY_ALIASES, METRIC_SPECS
from .charting import build_default_chart_plan, render_chart
from .models import ParsedIntent, QuestionRecord


warnings.filterwarnings("ignore", message=r"Glyph .* missing from font\(s\) .*")
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


class QueryEngine:
    def __init__(self, database_url: str, company_reference: pd.DataFrame, result_dir: Path) -> None:
        self.engine = create_engine(database_url)
        self.company_reference = company_reference.copy()
        self.company_reference["股票代码"] = self.company_reference["股票代码"].astype(str).str.zfill(6)
        self.result_dir = result_dir
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.view_df = self._build_view()

    def _build_view(self) -> pd.DataFrame:
        income = pd.read_sql_table("income_sheet", self.engine)
        kpi = pd.read_sql_table("core_performance_indicators_sheet", self.engine)
        balance = pd.read_sql_table("balance_sheet", self.engine)
        cash = pd.read_sql_table("cash_flow_sheet", self.engine)

        key = ["stock_code", "report_period", "report_year"]
        view = income.merge(
            kpi.drop(columns=["stock_abbr"], errors="ignore"),
            on=key,
            how="outer",
            suffixes=("_income", "_kpi"),
        )
        view = view.merge(balance.drop(columns=["stock_abbr"], errors="ignore"), on=key, how="outer")
        view = view.merge(cash.drop(columns=["stock_abbr"], errors="ignore"), on=key, how="outer", suffixes=("", "_cash"))
        view["stock_code"] = view["stock_code"].astype(str).str.zfill(6)
        stock_abbr = None
        for column_name in ["stock_abbr", "stock_abbr_income", "stock_abbr_kpi"]:
            if column_name in view.columns:
                if stock_abbr is None:
                    stock_abbr = view[column_name]
                else:
                    stock_abbr = stock_abbr.fillna(view[column_name])
        if stock_abbr is None:
            stock_abbr = pd.Series([None] * len(view), index=view.index)
        view["stock_abbr"] = stock_abbr
        for target, candidates in {
            "total_operating_revenue": ["total_operating_revenue_income", "total_operating_revenue_kpi"],
            "operating_revenue_yoy_growth": ["operating_revenue_yoy_growth_income", "operating_revenue_yoy_growth_kpi"],
            "net_profit_yoy_growth": ["net_profit_yoy_growth_income", "net_profit_yoy_growth_kpi"],
        }.items():
            merged_col = None
            for candidate in candidates:
                if candidate in view.columns:
                    if merged_col is None:
                        merged_col = view[candidate]
                    else:
                        merged_col = merged_col.fillna(view[candidate])
            if merged_col is not None:
                view[target] = merged_col
        view["period_sort"] = view["report_period"].map(_period_sort_key)
        view["year_period_label"] = view["report_period"]
        return view

    def answer(
        self,
        question: QuestionRecord,
        intent: ParsedIntent,
        image_index: int = 1,
        chart_question_text: str | None = None,
    ) -> tuple[str, str, str, str]:
        if intent.intent_type == "single_company_metric":
            return self._answer_single_company_metric(question, intent)
        if intent.intent_type == "trend_or_chart":
            return self._answer_trend(question, intent, image_index=image_index, chart_question_text=chart_question_text)
        if intent.intent_type == "ranking":
            return self._answer_ranking(question, intent, image_index=image_index, chart_question_text=chart_question_text)
        if intent.intent_type == "filter":
            return self._answer_filter(question, intent)
        if intent.intent_type == "comparison":
            return self._answer_comparison(question, intent)
        if intent.intent_type == "period_stat":
            return self._answer_period_stat(question, intent)
        return self._answer_fallback(question, intent)

    def _resolve_companies(self, intent: ParsedIntent) -> list[str]:
        resolved = []
        for company in intent.companies:
            alias = COMMON_COMPANY_ALIASES.get(company, company)
            if alias in self.view_df["stock_abbr"].fillna("").tolist() and alias not in resolved:
                resolved.append(alias)
                continue
            # contains fallback
            matches = self.view_df[self.view_df["stock_abbr"].fillna("").str.contains(company, na=False)]["stock_abbr"].dropna().unique().tolist()
            for item in matches:
                if item not in resolved:
                    resolved.append(item)
        return resolved

    def _resolve_metric_field(self, intent: ParsedIntent) -> tuple[str | None, str | None]:
        for metric in intent.metrics:
            if metric in METRIC_SPECS:
                spec = METRIC_SPECS[metric]
                return spec.field_name, spec.display_name
        return None, None

    def _base_filtered(self, intent: ParsedIntent) -> pd.DataFrame:
        df = self.view_df.copy()
        companies = self._resolve_companies(intent)
        if companies:
            df = df[df["stock_abbr"].isin(companies)]
        if intent.stock_codes:
            df = df[df["stock_code"].isin([code.zfill(6) for code in intent.stock_codes])]
        if intent.periods:
            df = df[df["report_period"].isin(intent.periods)]
        return df

    def _answer_single_company_metric(self, question: QuestionRecord, intent: ParsedIntent) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        if df.empty and not intent.periods:
            year_match = re.search(r"(20\d{2})年", question.raw_question)
            if year_match:
                year = int(year_match.group(1))
                df = self.view_df.copy()
                companies = self._resolve_companies(intent)
                if companies:
                    df = df[df["stock_abbr"].isin(companies)]
                df = df[df["report_year"] == year]
        metrics = [METRIC_SPECS[m] for m in intent.metrics if m in METRIC_SPECS]
        if df.empty or not metrics:
            return "", "未找到匹配记录。", "", "warning"

        if not intent.periods and "report_year" in df.columns and len(df["report_year"].dropna().unique()) == 1:
            df = df.sort_values(["report_year", "period_sort"]).groupby(["stock_code", "stock_abbr"], as_index=False).tail(1)

        cols = _unique_columns(["stock_code", "stock_abbr", "report_period"] + [m.field_name for m in metrics])
        cols = [c for c in cols if c in df.columns]
        result = df.sort_values(["report_year", "period_sort"])[cols].drop_duplicates()
        sql = _build_pseudo_sql(cols, df, question.raw_question)
        answer_parts = []
        for row in result.itertuples(index=False):
            row_text = f"{row.stock_abbr} {row.report_period}"
            for metric in metrics:
                value = getattr(row, metric.field_name)
                row_text += f" {metric.display_name}={_fmt(value)}"
            answer_parts.append(row_text)
        return sql, "；".join(answer_parts), result.head(10).to_json(force_ascii=False, orient="records"), ""

    def _answer_trend(
        self,
        question: QuestionRecord,
        intent: ParsedIntent,
        image_index: int = 1,
        chart_question_text: str | None = None,
    ) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        effective_text = chart_question_text or question.raw_question
        metric_field, metric_name = self._resolve_metric_field(intent)
        if metric_field is None:
            if "收入" in question.raw_question:
                metric_field, metric_name = "total_operating_revenue", "营业总收入(万元)"
            elif "净利润" in question.raw_question:
                metric_field, metric_name = "net_profit", "净利润(万元)"
            elif "资产负债率" in question.raw_question:
                metric_field, metric_name = "asset_liability_ratio", "资产负债率(%)"
        if metric_field is None or df.empty:
            return "", "未能识别趋势分析所需指标。", "", "warning"

        if not intent.periods and any(token in effective_text for token in ["近3年", "近三年", "3年", "三年"]):
            df = df[df["report_period"].astype(str).str.endswith("FY", na=False)].sort_values(["report_year", "period_sort"]).tail(3)
        elif not intent.periods:
            df = df.sort_values(["report_year", "period_sort"])
        else:
            df = df.sort_values(["report_year", "period_sort"])
        result = df[["stock_code", "stock_abbr", "report_period", metric_field]].dropna()
        sql = _build_pseudo_sql(result.columns.tolist(), result, question.raw_question)
        plan = build_default_chart_plan(
            chart_question_text or question.raw_question,
            result,
            preferred_chart_type=intent.chart_type or "line",
            preferred_metric_field=metric_field,
            preferred_metric_name=metric_name,
        )
        chart_path = render_chart(self.result_dir, question.question_id, result, plan, image_index=image_index) if plan else ""
        company_names = "、".join(sorted(result["stock_abbr"].dropna().unique().tolist()))
        answer = f"{company_names}的{metric_name}趋势已生成，共 {len(result)} 个数据点。"
        return sql, answer, result.head(20).to_json(force_ascii=False, orient="records"), chart_path

    def _answer_ranking(
        self,
        question: QuestionRecord,
        intent: ParsedIntent,
        image_index: int = 1,
        chart_question_text: str | None = None,
    ) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        metric_field, metric_name = self._resolve_metric_field(intent)
        if metric_field is None:
            if "营业总收入" in question.raw_question:
                metric_field, metric_name = "total_operating_revenue", "营业总收入(万元)"
            elif "净利润" in question.raw_question:
                metric_field, metric_name = "net_profit", "净利润(万元)"
            elif "存货" in question.raw_question:
                metric_field, metric_name = "asset_inventory", "存货(万元)"
        if metric_field is None or df.empty:
            return "", "未能识别排序所需指标。", "", "warning"

        top_n = intent.top_n or 10
        result = (
            df[["stock_code", "stock_abbr", "report_period", metric_field]]
            .dropna()
            .sort_values(metric_field, ascending=False)
            .head(top_n)
        )
        sql = _build_pseudo_sql(result.columns.tolist(), result, question.raw_question)
        chart_path = ""
        if intent.chart_type:
            plan = build_default_chart_plan(
                chart_question_text or question.raw_question,
                result,
                preferred_chart_type=intent.chart_type,
                preferred_metric_field=metric_field,
                preferred_metric_name=metric_name,
            )
            chart_path = render_chart(self.result_dir, question.question_id, result, plan, image_index=image_index) if plan else ""
        answer = f"{result.iloc[0]['report_period']} 按{metric_name}排序前 {len(result)} 家公司为：" + "、".join(result["stock_abbr"].tolist())
        return sql, answer, result.to_json(force_ascii=False, orient="records"), chart_path

    def _answer_filter(self, question: QuestionRecord, intent: ParsedIntent) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        if df.empty:
            return "", "未找到满足条件的数据。", "", "warning"

        result = df.copy()
        notes = []
        if "亏钱" in question.raw_question or "净利润为负" in question.raw_question:
            result = result[result["net_profit"] < 0]
            notes.append("净利润<0")
        if "经营性现金流量净额为负" in question.raw_question:
            result = result[result["operating_cf_net_amount"] < 0]
            notes.append("经营性现金流量净额<0")
        if "净利润为正" in question.raw_question:
            result = result[result["net_profit"] > 0]
            notes.append("净利润>0")
        if "资产负债率" in question.raw_question and "超过" in question.raw_question and intent.threshold is not None:
            result = result[result["asset_liability_ratio"] > intent.threshold]
            notes.append(f"资产负债率>{intent.threshold}")
        if "收入超过" in question.raw_question and intent.threshold is not None:
            threshold = intent.threshold
            if "亿元" in question.raw_question:
                threshold *= 10000
            result = result[result["total_operating_revenue"] > threshold]
            notes.append(f"营业总收入>{threshold}万元")
        if "销售毛利率" in question.raw_question and "销售净利率" in question.raw_question and any(token in question.raw_question for token in ["高于行业均值", "均高于行业均值"]):
            period_df = result.copy()
            gross_mean = pd.to_numeric(period_df.get("gross_profit_margin"), errors="coerce").dropna().mean()
            net_mean = pd.to_numeric(period_df.get("net_profit_margin"), errors="coerce").dropna().mean()
            result = period_df[
                (pd.to_numeric(period_df.get("gross_profit_margin"), errors="coerce") > gross_mean)
                & (pd.to_numeric(period_df.get("net_profit_margin"), errors="coerce") > net_mean)
            ]
            cols = [c for c in ["stock_code", "stock_abbr", "report_period", "gross_profit_margin", "net_profit_margin"] if c in result.columns]
            result = result[cols].drop_duplicates()
            sql = _build_pseudo_sql(cols, result, question.raw_question)
            companies = "、".join(result["stock_abbr"].astype(str).tolist()) if not result.empty else "无"
            answer = (
                f"行业均值中，销售毛利率为{_fmt(gross_mean)}%，销售净利率为{_fmt(net_mean)}%。"
                f" 同时高于两项行业均值的公司共 {len(result)} 家：{companies}。"
            )
            return sql, answer, result.head(30).to_json(force_ascii=False, orient="records"), ""
        cols = [c for c in ["stock_code", "stock_abbr", "report_period", "total_operating_revenue", "net_profit", "asset_liability_ratio", "operating_cf_net_amount"] if c in result.columns]
        result = result[cols].drop_duplicates()
        sql = _build_pseudo_sql(cols, result, question.raw_question)
        companies = "、".join(result["stock_abbr"].astype(str).drop_duplicates().tolist())
        answer = f"满足条件（{'；'.join(notes)}）的公司共 {len(result)} 家。"
        if companies:
            answer += f" 具体公司包括：{companies}。"
        return sql, answer, result.head(20).to_json(force_ascii=False, orient="records"), ""

    def _answer_comparison(self, question: QuestionRecord, intent: ParsedIntent) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        metric_field, metric_name = self._resolve_metric_field(intent)
        if metric_field is None and "收益率" in question.raw_question:
            metric_field, metric_name = "roe", "ROE(%)"
        if metric_field is None or df.empty:
            return "", "未能识别对比所需指标。", "", "warning"
        result = df[["stock_code", "stock_abbr", "report_period", metric_field]].dropna().sort_values([metric_field], ascending=False)
        sql = _build_pseudo_sql(result.columns.tolist(), result, question.raw_question)
        answer = f"对比结果中 {metric_name}最高的是 {result.iloc[0]['stock_abbr']}，数值为 {_fmt(result.iloc[0][metric_field])}。"
        return sql, answer, result.to_json(force_ascii=False, orient="records"), ""

    def _answer_period_stat(self, question: QuestionRecord, intent: ParsedIntent) -> tuple[str, str, str, str]:
        df = self._base_filtered(intent)
        if df.empty:
            return "", "未找到对应报告期数据。", "", "warning"
        if "按营业总收入从高到低排序" in question.raw_question:
            result = (
                df[["stock_code", "stock_abbr", "report_period", "total_operating_revenue"]]
                .dropna()
                .sort_values("total_operating_revenue", ascending=False)
            )
            answer = f"{result.iloc[0]['report_period']} 已按营业总收入从高到低排序返回，共 {len(result)} 家公司。"
            return _build_pseudo_sql(result.columns.tolist(), result, question.raw_question), answer, result.to_json(force_ascii=False, orient="records"), ""
        if "销售毛利率" in question.raw_question and "利润表" in question.raw_question:
            work = df.copy()
            work["gross_margin_from_income"] = (work["total_operating_revenue"] - work["operating_expense_cost_of_sales"]) / work["total_operating_revenue"] * 100
            cols = ["stock_code", "stock_abbr", "report_period", "total_operating_revenue_kpi", "gross_margin_from_income"]
            cols = [c for c in cols if c in work.columns]
            result = work[cols].dropna().copy()
            if "total_operating_revenue_kpi" in result.columns:
                result = result.rename(columns={"total_operating_revenue_kpi": "营业总收入_核心业绩指标表", "gross_margin_from_income": "销售毛利率_利润表推导"})
            answer = f"{result.iloc[0]['report_period']} 已返回各公司营业总收入与利润表推导销售毛利率。"
            return _build_pseudo_sql(result.columns.tolist(), result, question.raw_question), answer, result.head(30).to_json(force_ascii=False, orient="records"), ""
        if "分组" in question.raw_question and "销售净利率" in question.raw_question:
            work = df.copy()
            if "net_profit_margin" not in work.columns or work["net_profit_margin"].isna().all():
                work["net_profit_margin"] = work["net_profit"] / work["total_operating_revenue"] * 100
            bins = [-float("inf"), 5, 10, float("inf")]
            labels = ["0-5%", "5%-10%", "10%以上"]
            valid = work[work["net_profit_margin"].notna() & (work["net_profit_margin"] >= 0)].copy()
            valid["利润率区间"] = pd.cut(valid["net_profit_margin"], bins=bins, labels=labels, right=False)
            result = valid.groupby("利润率区间").size().reset_index(name="公司数量")
            answer = "销售净利率分组统计完成。"
            return _build_pseudo_sql(result.columns.tolist(), result, question.raw_question), answer, result.to_json(force_ascii=False, orient="records"), ""
        if "不一致" in question.raw_question and "营业总收入" in question.raw_question:
            work = df.copy()
            income_col = "total_operating_revenue_income" if "total_operating_revenue_income" in work.columns else "total_operating_revenue"
            kpi_col = "total_operating_revenue_kpi" if "total_operating_revenue_kpi" in work.columns else "total_operating_revenue"
            work["差值绝对值"] = (work[income_col] - work[kpi_col]).abs()
            result = work[work["差值绝对值"] > 0.01][["stock_code", "stock_abbr", "report_period", income_col, kpi_col, "差值绝对值"]].dropna()
            result = result.rename(columns={income_col: "营业总收入_利润表", kpi_col: "营业总收入_核心业绩指标表"})
            answer = f"检测到 {len(result)} 家公司在两表中的营业总收入存在差异。"
            return _build_pseudo_sql(result.columns.tolist(), result, question.raw_question), answer, result.head(50).to_json(force_ascii=False, orient="records"), ""
        if "均值" in question.raw_question or "平均" in question.raw_question:
            metrics = [METRIC_SPECS[m] for m in intent.metrics if m in METRIC_SPECS]
            if not metrics:
                return "", "未识别到可统计的指标。", "", "warning"
            summary = {}
            for metric in metrics:
                summary[metric.display_name] = round(df[metric.field_name].dropna().mean(), 4)
            answer = "、".join(f"{k}均值为{v}" for k, v in summary.items())
            return "", answer, pd.DataFrame([summary]).to_json(force_ascii=False, orient="records"), ""
        return self._answer_fallback(question, intent)

    def _answer_fallback(self, question: QuestionRecord, intent: ParsedIntent) -> tuple[str, str, str, str]:
        return "", "当前版本已完成任务二骨架，但该问题尚未配置专用模板，建议后续补充规则。", "", "todo"

def _period_sort_key(value: str) -> float:
    if value is None or not isinstance(value, str):
        return math.nan
    if value.endswith("Q1"):
        return float(value[:4]) + 0.1
    if value.endswith("Q2"):
        return float(value[:4]) + 0.2
    if value.endswith("H1"):
        return float(value[:4]) + 0.2
    if value.endswith("Q3"):
        return float(value[:4]) + 0.3
    if value.endswith("FY"):
        return float(value[:4]) + 0.4
    return math.nan


def _build_pseudo_sql(columns: list[str], dataframe: pd.DataFrame, question_text: str) -> str:
    period_hint = ""
    if "report_period" in dataframe.columns and not dataframe.empty:
        periods = dataframe["report_period"].dropna().astype(str).unique().tolist()
        period_hint = f" -- periods={','.join(periods[:5])}"
    return f"SELECT {', '.join(columns)} FROM financials_view /* {question_text} */{period_hint}"


def _fmt(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NA"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


def _unique_columns(columns: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for column in columns:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    return ordered
