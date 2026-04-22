from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from ..schemas import ParsedIntent, QuestionRecord


QUESTION_KEYWORDS_TO_METRICS = {
    "营业总收入": "营业总收入",
    "收入": "营业总收入",
    "净利润": "净利润",
    "扣非净利润": "扣非净利润",
    "扣除非经常性损益后的净利润": "扣非净利润",
    "利润总额": "利润总额",
    "复合增长率": "复合增长率",
    "同比增长率": "同比增长率",
    "同比增长": "同比增长率",
    "股东权益-未分配利润": "未分配利润",
    "未分配利润": "未分配利润",
    "研发费用占营业总收入比例": "研发费用占比",
    "研发费用占比": "研发费用占比",
    "研发费用": "研发费用",
    "销售费用": "销售费用",
    "销售毛利率": "销售毛利率",
    "销售净利率": "销售净利率",
    "加权平均净资产收益率（扣非）": "加权平均净资产收益率（扣非）",
    "加权平均净资产收益率(扣非)": "加权平均净资产收益率（扣非）",
    "扣非净资产收益率": "加权平均净资产收益率（扣非）",
    "扣非ROE": "加权平均净资产收益率（扣非）",
    "存货周转率": "存货周转率",
    "资产负债率": "资产负债率",
    "经营性现金流量净额": "经营性现金流量净额",
    "投资性现金流量净额": "投资性现金流量净额",
    "货币资金": "货币资金",
    "短期借款": "短期借款",
    "营业总收入增长率": "营业总收入增长率",
    "营收增长率": "营业总收入增长率",
    "出口业务占比": "出口业务占比",
    "ROE": "ROE",
    "净资产收益率": "ROE",
    "收益率": "ROE",
    "核心利润指标": "净利润",
    "核心利润": "净利润",
}

COMMON_COMPANY_ALIASES = {
    "999": "华润三九",
    "白云山": "白云山",
    "云南白药": "云南白药",
    "金花": "金花股份",
    "金花药业": "金花股份",
}

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
        questions.append(
            QuestionRecord(
                question_id=str(row.编号),
                question_type=str(row.问题类型),
                original_question_json=str(row.问题),
                raw_question=" | ".join(sub_questions),
                sub_questions=sub_questions,
            )
        )
    return questions


class IntentParser:
    def __init__(self, company_reference: pd.DataFrame, extra_company_names: list[str] | None = None) -> None:
        self.company_reference = company_reference.copy()
        self.company_reference["股票代码"] = self.company_reference["股票代码"].astype(str).str.zfill(6)
        company_names = self.company_reference["A股简称"].astype(str).unique().tolist()
        if extra_company_names:
            company_names.extend([str(name) for name in extra_company_names if str(name).strip()])
        normalized_names = []
        for name in company_names:
            name = str(name).strip()
            if name and name not in normalized_names:
                normalized_names.append(name)
        self.company_names = sorted(normalized_names, key=len, reverse=True)
        self._normalized_company_map = {
            self._normalize_company_text(name): name for name in self.company_names if self._normalize_company_text(name)
        }

    def parse_text(self, text: str) -> ParsedIntent:
        companies, stock_codes = self._extract_companies(text)
        metrics = self._extract_metrics(text)
        periods = self._extract_periods(text)
        top_n = self._extract_top_n(text)
        threshold = self._extract_threshold(text)
        chart_type = self._extract_chart_type(text)
        intent_type = self._classify_intent(text, companies, metrics, periods, chart_type)
        notes: list[str] = []
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
        for code in re.findall(r"(?<!\d)(\d{3}|\d{6})(?!\d)", text):
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
        normalized_text = self._normalize_company_text(text)
        for normalized_name, canonical in self._normalized_company_map.items():
            if normalized_name and normalized_name in normalized_text and canonical not in companies:
                companies.append(canonical)
        hint_match = re.search(r"(?:企业名称|公司名称|公司简称)[:：]?\s*([^\s，。；,;]+)", text)
        if hint_match:
            hinted = self._resolve_company_hint(hint_match.group(1))
            if hinted and hinted not in companies:
                companies.append(hinted)
        return companies, stock_codes

    def _resolve_company_hint(self, hint: str) -> str | None:
        cleaned = re.sub(r"[（(].*?[）)]", "", hint).strip()
        cleaned = re.sub(r"(股份|药业|制药|集团|公司)$", "", cleaned)
        if not cleaned:
            return None
        exact = [name for name in self.company_names if name == cleaned]
        if exact:
            return exact[0]
        contains = [name for name in self.company_names if cleaned in name]
        if len(contains) == 1:
            return contains[0]
        prefix = [name for name in self.company_names if name.startswith(cleaned)]
        if len(prefix) == 1:
            return prefix[0]
        normalized = self._normalize_company_text(cleaned)
        mapped = self._normalized_company_map.get(normalized)
        if mapped:
            return mapped
        return None

    @staticmethod
    def _normalize_company_text(text: str) -> str:
        value = re.sub(r"\s+", "", str(text))
        value = re.sub(r"[（(].*?[）)]", "", value)
        return value.strip()

    def _extract_metrics(self, text: str) -> list[str]:
        metrics: list[str] = []
        for keyword, metric in QUESTION_KEYWORDS_TO_METRICS.items():
            if keyword in text and metric not in metrics:
                metrics.append(metric)
        return metrics

    def _extract_periods(self, text: str) -> list[str]:
        periods: list[str] = []
        for pattern, formatter in PERIOD_PATTERNS:
            for match in re.findall(pattern, text):
                value = formatter(match)
                if value not in periods:
                    periods.append(value)
        for match in re.finditer(r"(\d{4})年(?!前?三季度|第[一二三四]季度|半年度|上半年|全年|年度)", text):
            value = f"{match.group(1)}FY"
            if value not in periods:
                periods.append(value)
        range_match = re.search(r"(\d{4})-(\d{4})年第三季度", text)
        if range_match:
            start_year, end_year = range_match.groups()
            for year in range(int(start_year), int(end_year) + 1):
                periods.append(f"{year}Q3")
        if "去年" in text and "2024FY" not in periods:
            periods.append("2024FY")
        return list(dict.fromkeys(periods))

    def _extract_top_n(self, text: str) -> int | None:
        lowered = text.lower()
        for marker, value in [("前十", 10), ("前五", 5), ("前三", 3), ("top10", 10), ("top5", 5), ("top3", 3)]:
            if marker in lowered:
                return value
        match = re.search(r"前(\d+)家|前(\d+)位|最高的(\d+)家", text)
        if match:
            for item in match.groups():
                if item:
                    return int(item)
        return None

    def _extract_threshold(self, text: str) -> float | None:
        for token in ["超过", "高于", "低于", "不少于", "不低于", "不超过", "不高于"]:
            match = re.search(rf"{token}\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|亿元人民币|亿|万元|万|元|%)?", text)
            if match:
                value = float(match.group(1))
                unit = (match.group(2) or "").strip()
                if unit in {"亿元", "亿元人民币", "亿"}:
                    return value * 10000
                if unit in {"元"}:
                    return value / 10000
                return value
        return None

    def _extract_chart_type(self, text: str) -> str | None:
        chart_map = {
            "表格": "table",
            "双条形图": "grouped_bar",
            "双柱状图": "grouped_bar",
            "水平柱状图": "barh",
            "折线图": "line",
            "趋势图": "line",
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
            pos = text.rfind(keyword)
            if pos >= 0 and (matched is None or pos > matched[0]):
                matched = (pos, chart_type)
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
        if metrics and periods:
            return "period_stat"
        return "generic"


__all__ = ["IntentParser", "load_questions"]
