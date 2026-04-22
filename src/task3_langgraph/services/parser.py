from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from ..schemas import ParsedTask3Intent, QuestionRecord


QUESTION_KEYWORDS_TO_METRICS = {
    "营业总收入": "营业总收入",
    "主营业务收入": "营业总收入",
    "营业收入": "营业总收入",
    "销售额": "营业总收入",
    "营收": "营业总收入",
    "收入": "营业总收入",
    "净利润": "净利润",
    "扣非净利润": "扣非净利润",
    "扣除非经常性损益后的净利润": "扣非净利润",
    "利润": "净利润",
    "利润总额": "利润总额",
    "毛利率": "销售毛利率",
    "净利率": "销售净利率",
    "净利润率": "销售净利率",
    "加权平均净资产收益率（扣非）": "加权平均净资产收益率（扣非）",
    "加权平均净资产收益率(扣非)": "加权平均净资产收益率（扣非）",
    "扣非净资产收益率": "加权平均净资产收益率（扣非）",
    "扣非ROE": "加权平均净资产收益率（扣非）",
    "资产负债率": "资产负债率",
    "经营性现金流量净额": "经营性现金流量净额",
    "投资性现金流量净额": "投资性现金流量净额",
    "货币资金": "货币资金",
    "短期借款": "短期借款",
    "营业成本": "营业成本",
    "销售费用": "销售费用",
    "管理费用": "管理费用",
    "研发费用": "研发费用",
    "研发费用占比": "研发费用占比",
    "未分配利润": "未分配利润",
    "存货周转率": "存货周转率",
    "总资产": "总资产",
    "股东权益总额": "股东权益总额",
    "股东权益": "股东权益总额",
    "应收账款": "应收账款",
    "海外业务收入": "海外业务收入",
    "主营业务类型": "主营业务类型",
    "营业总收入增长率": "营业总收入增长率",
    "营收增长率": "营业总收入增长率",
    "收益率": "ROE",
    "净资产收益率": "ROE",
}

TOPIC_KEYWORDS = [
    "医保目录",
    "集采",
    "中药集采扩围",
    "创新药",
    "出海",
    "海外市场拓展",
    "海外拓展",
    "AI医疗",
    "人工智能",
    "产业升级",
    "并购",
    "资产重组",
    "商誉减值风险",
    "应收账款回收风险",
    "FDA",
    "FDA认证",
    "业绩预告",
    "渠道",
    "改革",
    "行业",
    "中药材",
    "价格",
    "价格波动",
    "趋势",
    "预测",
    "供需",
    "库存",
    "种植",
    "气候",
    "成本控制",
    "成本结构",
    "业务类型",
    "主营业务类型",
    "偿债风险",
    "偿债能力",
    "投资项目",
    "大健康",
    "新品上市周期",
    "研发投入结构",
    "订单农业",
    "基地共建",
    "种植基地",
    "原因",
    "归因",
    "驱动",
    "风险",
    "催化",
]

CHART_TOKENS = ["可视化", "绘图", "画图", "图表", "柱状图", "折线图", "饼图", "雷达图", "散点图", "直方图", "箱线图"]
REASON_TOKENS = ["原因", "归因", "为什么", "驱动", "怎么看", "分析"]
INDUSTRY_OPEN_TOKENS = ["行业", "板块", "景气度", "趋势", "预测", "中药材", "价格波动", "供需", "库存", "种植", "气候"]
SCREENING_TOKENS = ["有哪些", "哪些", "哪几家", "前十", "前五", "前三", "最高", "最低", "超过", "高于", "低于", "不低于", "不超过", "统计", "找出", "列出", "筛选", "数量"]
RETRIEVAL_STRONG_TOKENS = [
    "结合研报",
    "结合个股研报",
    "结合行业研报",
    "检索研报",
    "研报中",
    "提取研报",
    "提取研报观点",
    "提取观点",
    "观点",
    "说明",
    "风险预警",
    "判断依据",
    "依据是什么",
    "产业升级相关布局",
]

COMMON_COMPANY_ALIASES = {
    "999": "华润三九",
    "三九": "华润三九",
    "白云山": "白云山",
    "云南白药": "云南白药",
    "金花": "金花股份",
    "三金": "桂林三金",
}

PERIOD_PATTERNS = [
    (r"(\d{4})年前三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})前三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})年第三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})第三季度", lambda y: f"{y}Q3"),
    (r"(\d{4})年第二季度", lambda y: f"{y}Q2"),
    (r"(\d{4})第二季度", lambda y: f"{y}Q2"),
    (r"(\d{4})年第一季度", lambda y: f"{y}Q1"),
    (r"(\d{4})第一季度", lambda y: f"{y}Q1"),
    (r"(\d{4})年半年度", lambda y: f"{y}H1"),
    (r"(\d{4})年上半年", lambda y: f"{y}H1"),
    (r"(\d{4})上半年", lambda y: f"{y}H1"),
    (r"(\d{4})年全年", lambda y: f"{y}FY"),
    (r"(\d{4})年年度", lambda y: f"{y}FY"),
    (r"(\d{4})年度", lambda y: f"{y}FY"),
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


class Task3IntentParser:
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

    def parse_text(self, text: str) -> ParsedTask3Intent:
        companies, stock_codes = self._extract_companies(text)
        metrics = self._extract_metrics(text)
        periods = self._extract_periods(text)
        focus_topics = self._extract_topics(text)
        top_n = self._extract_top_n(text)
        threshold = self._extract_threshold(text)
        route = self._classify_route(text, companies, metrics, periods, focus_topics, top_n, threshold)
        return ParsedTask3Intent(
            intent_type=route["intent_type"],
            companies=companies,
            stock_codes=stock_codes,
            metrics=metrics,
            periods=periods,
            focus_topics=focus_topics,
            needs_sql=route["needs_sql"],
            needs_retrieval=route["needs_retrieval"],
            top_n=top_n,
            threshold=threshold,
            notes=route["notes"],
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
        return companies, stock_codes

    def _extract_metrics(self, text: str) -> list[str]:
        metrics: list[str] = []
        for keyword, metric in QUESTION_KEYWORDS_TO_METRICS.items():
            if keyword in text and metric not in metrics:
                metrics.append(metric)
        return metrics

    def _extract_topics(self, text: str) -> list[str]:
        topics: list[str] = []
        for keyword in TOPIC_KEYWORDS:
            if keyword in text and keyword not in topics:
                topics.append(keyword)
        return topics

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
        if "近三年" in text or "近3年" in text:
            for year in ["2023FY", "2024FY", "2025FY"]:
                if year not in periods:
                    periods.append(year)
        if "去年" in text and not periods:
            if "前三季度" in text or "第三季度" in text:
                periods.append("2024Q3")
            elif "第二季度" in text:
                periods.append("2024Q2")
            elif "第一季度" in text:
                periods.append("2024Q1")
            elif "上半年" in text or "半年度" in text:
                periods.append("2024H1")
            else:
                periods.append("2024FY")
        if "今年" in text and not periods:
            if "前三季度" in text or "第三季度" in text:
                periods.append("2025Q3")
            elif "第二季度" in text:
                periods.append("2025Q2")
            elif "第一季度" in text:
                periods.append("2025Q1")
            elif "上半年" in text or "半年度" in text:
                periods.append("2025H1")
            else:
                periods.append("2025FY")
        return list(dict.fromkeys(periods))

    def _extract_top_n(self, text: str) -> int | None:
        lowered = text.lower()
        for marker, value in [("前十", 10), ("前五", 5), ("前三", 3), ("top10", 10), ("top5", 5), ("top3", 3)]:
            if marker in lowered:
                return value
        return None

    def _extract_threshold(self, text: str) -> float | None:
        match = re.search(r"(超过|高于|低于|不超过|不低于)\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|亿|万元|万|元|%)?", text)
        if not match:
            return None
        value = float(match.group(2))
        unit = (match.group(3) or "").strip()
        if unit in {"亿元", "亿"}:
            return value * 10000
        if unit == "元":
            return value / 10000
        return value

    def _classify_route(
        self,
        text: str,
        companies: list[str],
        metrics: list[str],
        periods: list[str],
        focus_topics: list[str],
        top_n: int | None,
        threshold: float | None,
    ) -> dict[str, object]:
        has_chart = any(token in text for token in CHART_TOKENS)
        has_reason = any(word in text for word in REASON_TOKENS)
        is_industry_open = any(token in text for token in INDUSTRY_OPEN_TOKENS)
        has_strong_retrieval_signal = any(token in text for token in RETRIEVAL_STRONG_TOKENS)
        has_screening = bool(
            top_n is not None
            or threshold is not None
            or any(token in text for token in SCREENING_TOKENS)
            or "所有公司" in text
            or "各公司" in text
            or "企业" in text
        )
        has_sql_signal = bool(metrics or periods or top_n is not None or threshold is not None or has_screening)
        notes: list[str] = []

        if has_chart and has_sql_signal and not has_reason:
            return {
                "intent_type": "sql_chart",
                "needs_sql": True,
                "needs_retrieval": False,
                "notes": ["route=sql_chart"],
            }
        if has_reason:
            return {
                "intent_type": "causal_analysis",
                "needs_sql": bool(has_sql_signal),
                "needs_retrieval": True,
                "notes": ["route=causal_analysis"],
            }
        if has_strong_retrieval_signal and is_industry_open and not companies:
            return {
                "intent_type": "industry_open_analysis",
                "needs_sql": bool(has_sql_signal),
                "needs_retrieval": True,
                "notes": ["route=industry_open_analysis"],
            }
        if has_strong_retrieval_signal and has_sql_signal:
            return {
                "intent_type": "hybrid_sql_rag",
                "needs_sql": True,
                "needs_retrieval": True,
                "notes": ["route=hybrid_sql_rag"],
            }
        if is_industry_open and not companies and not has_sql_signal:
            return {
                "intent_type": "industry_open_analysis",
                "needs_sql": False,
                "needs_retrieval": True,
                "notes": ["route=industry_open_analysis"],
            }
        if has_sql_signal and not focus_topics and not is_industry_open and not has_strong_retrieval_signal:
            return {
                "intent_type": "sql_only",
                "needs_sql": True,
                "needs_retrieval": False,
                "notes": ["route=sql_only"],
            }
        if has_sql_signal and (focus_topics or is_industry_open or has_strong_retrieval_signal):
            return {
                "intent_type": "hybrid_sql_rag",
                "needs_sql": True,
                "needs_retrieval": True,
                "notes": ["route=hybrid_sql_rag"],
            }
        if companies or focus_topics or is_industry_open:
            return {
                "intent_type": "rag_only" if not is_industry_open else "industry_open_analysis",
                "needs_sql": False,
                "needs_retrieval": True,
                "notes": ["route=rag_only" if not is_industry_open else "route=industry_open_analysis"],
            }
        return {
            "intent_type": "open_analysis",
            "needs_sql": False,
            "needs_retrieval": True,
            "notes": notes,
        }

    @staticmethod
    def _normalize_company_text(text: str) -> str:
        value = re.sub(r"\s+", "", str(text))
        value = re.sub(r"[（(].*?[）)]", "", value)
        return value.strip()


__all__ = ["Task3IntentParser", "load_questions"]
