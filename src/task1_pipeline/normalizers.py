from __future__ import annotations

import re
from typing import Any


def clean_label(text: Any) -> str:
    if text is None:
        return ""
    value = str(text)
    value = value.replace("\n", "").replace("\r", "")
    value = re.sub(r"\s+", "", value)
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("：", ":")
    return value


def detect_unit(text: str | None) -> str | None:
    if not text:
        return None
    text = str(text)
    amount_unit = detect_amount_unit(text)
    if amount_unit:
        return amount_unit
    if "%" in text or "率" in text or "同比" in text or "环比" in text:
        return "%"
    return None


def detect_amount_unit(text: str | None) -> str | None:
    if not text:
        return None
    text = str(text)
    if "亿元" in text:
        return "亿元"
    if "万元" in text:
        return "万元"
    if "元" in text:
        return "元"
    return None


def parse_numeric(value: Any, unit_hint: str | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value).strip()
        if text in {"", "--", "—", "N/A", "nan", "None"}:
            return None
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1]
        text = text.replace(",", "").replace("，", "")
        text = text.replace("－", "-").replace("＋", "+")
        text = re.sub(r"^([+-])\s+", r"\1", text)
        percent_in_value = "%" in text
        text = text.replace("%", "")
        unit_in_value = detect_unit(text)
        text = text.replace("亿元", "").replace("万元", "").replace("元", "")
        text = text.replace("股", "")
        text = text.strip()
        if text in {"", "--", "—"}:
            return None
        try:
            numeric = float(text)
        except ValueError:
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if not match:
                return None
            numeric = float(match.group(0))
        if negative:
            numeric = -numeric
        effective_unit = unit_in_value or unit_hint
        if percent_in_value or effective_unit == "%":
            return numeric
        if effective_unit == "亿元":
            return numeric * 10000
        if effective_unit == "元":
            return numeric / 10000
    return numeric


def parse_numeric_plain(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in {"", "--", "—", "N/A", "nan", "None"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "").replace("，", "")
    text = text.replace("－", "-").replace("＋", "+")
    text = re.sub(r"^([+-])\s+", r"\1", text)
    text = text.replace("%", "")
    text = text.replace("亿元", "").replace("万元", "").replace("元", "")
    text = text.replace("股", "")
    text = text.strip()
    if text in {"", "--", "—"}:
        return None
    try:
        numeric = float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        numeric = float(match.group(0))
    return -numeric if negative else numeric


FIELDS_KEEP_YUAN = {
    "eps",
    "net_asset_per_share",
    "operating_cf_per_share",
}

FIELDS_PERCENT = {
    "operating_revenue_yoy_growth",
    "operating_revenue_qoq_growth",
    "net_profit_yoy_growth",
    "net_profit_qoq_growth",
    "roe",
    "net_profit_excl_non_recurring_yoy",
    "gross_profit_margin",
    "net_profit_margin",
    "roe_weighted_excl_non_recurring",
    "asset_total_assets_yoy_growth",
    "liability_total_liabilities_yoy_growth",
    "asset_liability_ratio",
    "net_cash_flow_yoy_growth",
    "operating_cf_ratio_of_net_cf",
    "investing_cf_ratio_of_net_cf",
    "financing_cf_ratio_of_net_cf",
}


def convert_for_field(field_name: str, raw_value: Any, source_unit: str | None) -> float | None:
    raw_numeric = parse_numeric_plain(raw_value)
    if raw_numeric is None:
        return None
    if field_name in FIELDS_PERCENT:
        return parse_numeric(raw_value, "%")
    explicit_unit = detect_amount_unit(str(raw_value))
    if field_name in FIELDS_KEEP_YUAN:
        return raw_numeric
    effective_unit = explicit_unit or source_unit
    if effective_unit == "亿元":
        return raw_numeric * 10000
    if effective_unit == "元":
        return raw_numeric / 10000
    return raw_numeric


def normalize_report_period(report_year: int | None, report_type: str | None, raw_text: str | None) -> str | None:
    if report_year is None:
        return None
    text = raw_text or report_type or ""
    if "一季度" in text or "第一季度" in text:
        return f"{report_year}Q1"
    if "半年度" in text or "半年" in text:
        return f"{report_year}H1"
    if "三季度" in text or "第三季度" in text:
        return f"{report_year}Q3"
    if "年度" in text or "年报" in text:
        return f"{report_year}FY"
    return str(report_year)
