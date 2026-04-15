from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .catalog import COMMON_COMPANY_ALIASES, QUESTION_KEYWORDS_TO_METRICS
from .models import ParsedIntent, QuestionRecord


PERIOD_PATTERNS = [
    (r"(\d{4})年前三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})年第三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})年第二季度", lambda y: f"{y}Q2"),
    (r"(\d{4})年第一季度", lambda y: f"{y}Q1"),
    (r"(\d{4})年半年度", lambda y: f"{y}H1"),
    (r"(\d{4})年上半年", lambda y: f"{y}H1"),
    (r"(\d{4})年全年", lambda y: f"{y}FY"),
    (r"(\d{4})年年度", lambda y: f"{y}FY"),
]


def load_questions(question_file: Path) -> list[QuestionRecord]:
    df = pd.read_excel(question_file)
    questions: list[QuestionRecord] = []
    for row in df.itertuples(index=False):
        sub_questions = [item["Q"] for item in json.loads(row.问题)]
        raw = " | ".join(sub_questions)
        questions.append(
            QuestionRecord(
                question_id=str(row.编号),
                question_type=str(row.问题类型),
                original_question_json=str(row.问题),
                raw_question=raw,
                sub_questions=sub_questions,
            )
        )
    return questions


class IntentParser:
    def __init__(self, company_reference: pd.DataFrame) -> None:
        self.company_reference = company_reference.copy()
        self.company_reference["股票代码"] = self.company_reference["股票代码"].astype(str).str.zfill(6)
        self.company_names = sorted(self.company_reference["A股简称"].astype(str).unique().tolist(), key=len, reverse=True)

    def parse(self, question: QuestionRecord) -> ParsedIntent:
        text = question.raw_question
        return self.parse_text(text)

    def parse_text(self, text: str) -> ParsedIntent:
        companies, stock_codes = self._extract_companies(text)
        metrics = self._extract_metrics(text)
        periods = self._extract_periods(text)
        top_n = self._extract_top_n(text)
        threshold = self._extract_threshold(text)
        chart_type = self._extract_chart_type(text)
        intent_type = self._classify_intent(text, companies, metrics, periods, chart_type)
        notes = []
        if not periods and "近几年" in text:
            notes.append("默认按数据库中可用年度/季度时间序列返回")
        if "去年" in text:
            notes.append("“去年”默认解释为数据库中的最近完整年度，即 2024FY")
        return ParsedIntent(
            intent_type=intent_type,
            companies=companies,
            stock_codes=stock_codes,
            metrics=metrics,
            periods=periods,
            top_n=top_n,
            threshold=threshold,
            chart_type=chart_type,
            notes=notes,
        )

    def _extract_companies(self, text: str) -> tuple[list[str], list[str]]:
        companies: list[str] = []
        stock_codes: list[str] = []

        for code in re.findall(r"\b\d{6}\b|\b\d{3}\b", text):
            normalized = code.zfill(6)
            match = self.company_reference[self.company_reference["股票代码"] == normalized]
            if not match.empty:
                company = str(match.iloc[0]["A股简称"])
                if company not in companies:
                    companies.append(company)
                if normalized not in stock_codes:
                    stock_codes.append(normalized)

        for alias, canonical in COMMON_COMPANY_ALIASES.items():
            if alias in text and canonical not in companies:
                companies.append(canonical)

        for name in self.company_names:
            if name in text and name not in companies:
                companies.append(name)

        return companies, stock_codes

    def _extract_metrics(self, text: str) -> list[str]:
        metrics: list[str] = []
        for keyword in QUESTION_KEYWORDS_TO_METRICS:
            if keyword in text and keyword not in metrics:
                metrics.append(keyword)
        if not metrics and "收益率" in text:
            metrics.append("ROE")
        return metrics

    def _extract_periods(self, text: str) -> list[str]:
        periods: list[str] = []
        for pattern, formatter in PERIOD_PATTERNS:
            for match in re.findall(pattern, text):
                value = formatter(match)
                if value not in periods:
                    periods.append(value)
        range_match = re.search(r"(\d{4})-(\d{4})年第三季度", text)
        if range_match:
            start_year, end_year = range_match.groups()
            for year in range(int(start_year), int(end_year) + 1):
                value = f"{year}Q3"
                if value not in periods:
                    periods.append(value)
        if "去年" in text and "2024FY" not in periods:
            periods.append("2024FY")
        return periods

    def _extract_top_n(self, text: str) -> int | None:
        for marker, value in [("前十", 10), ("前五", 5), ("前三", 3), ("top10", 10), ("top5", 5), ("top3", 3)]:
            if marker in text.lower():
                return value
        number_match = re.search(r"前(\d+)家|前(\d+)位|最高的(\d+)家", text)
        if number_match:
            for group in number_match.groups():
                if group:
                    return int(group)
        return None

    def _extract_threshold(self, text: str) -> float | None:
        match = re.search(r"超过([0-9]+(?:\.[0-9]+)?)", text)
        if match:
            return float(match.group(1))
        match = re.search(r"高于([0-9]+(?:\.[0-9]+)?)", text)
        if match:
            return float(match.group(1))
        return None

    def _extract_chart_type(self, text: str) -> str | None:
        chart_map = {
            "折线图": "line",
            "趋势图": "line",
            "水平柱状图": "barh",
            "条形图": "bar",
            "柱状图": "bar",
            "雷达图": "radar",
            "饼图": "pie",
            "散点图": "scatter",
            "直方图": "hist",
            "箱线图": "box",
        }
        matched: tuple[int, str] | None = None
        for keyword, chart_type in chart_map.items():
            position = text.rfind(keyword)
            if position >= 0 and (matched is None or position > matched[0]):
                matched = (position, chart_type)
        return matched[1] if matched else None

    def _classify_intent(
        self,
        text: str,
        companies: list[str],
        metrics: list[str],
        periods: list[str],
        chart_type: str | None,
    ) -> str:
        if chart_type or "趋势" in text:
            return "trend_or_chart"
        if any(word in text for word in ["排名", "前五", "前三", "前十", "最高", "最低"]):
            return "ranking"
        if any(word in text for word in ["哪些", "筛选", "超过", "低于", "为负", "为正"]):
            return "filter"
        if len(companies) >= 2 and metrics:
            return "comparison"
        if companies and metrics:
            return "single_company_metric"
        if companies and metrics and periods:
            return "single_company_metric"
        if metrics and periods:
            return "period_stat"
        return "generic"
