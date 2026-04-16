from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


STOCK_REPORT_FIELD_RULES: dict[str, str] = {
    "title": "研报标题",
    "stockName": "个股名称",
    "stockCode": "个股代码",
    "orgCode": "机构代码",
    "orgName": "机构全称",
    "orgSName": "机构简称",
    "publishDate": "发布日期",
    "indvInduName": "个股所属行业",
    "emRatingName": "当前评级",
    "lastEmRatingName": "上次评级",
    "researcher": "研究员",
    "sRatingName": "标准化评级名称",
    "sRatingCode": "标准化评级代码",
    "market": "上市市场",
    "indvIsNew": "是否首次覆盖",
    "predictThisYearEps": "本年预测EPS",
    "predictNextYearEps": "下一年预测EPS",
    "predictNextTwoYearEps": "未来两年预测EPS",
    "predictThisYearPe": "本年预测PE",
    "predictNextYearPe": "下一年预测PE",
    "predictNextTwoYearPe": "未来两年预测PE",
}


INDUSTRY_REPORT_FIELD_RULES: dict[str, str] = {
    "title": "研报标题",
    "orgCode": "机构代码",
    "orgName": "机构全称",
    "orgSName": "机构简称",
    "publishDate": "发布日期",
    "industryName": "行业名称",
    "emRatingName": "当前评级",
    "lastEmRatingName": "上次评级",
    "researcher": "研究员",
    "sRatingName": "标准化评级名称",
    "sRatingCode": "标准化评级代码",
}


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _make_metadata_ref(row: dict[str, Any], source_type: str) -> str:
    title = str(_clean_scalar(row.get("title")) or "")
    publish_date = str(_clean_scalar(row.get("publishDate")) or "")
    organization = str(_clean_scalar(row.get("orgSName")) or _clean_scalar(row.get("orgName")) or "")
    company = str(_clean_scalar(row.get("stockName")) or "")
    industry = str(_clean_scalar(row.get("indvInduName") or row.get("industryName")) or "")
    code = str(_clean_scalar(row.get("stockCode")) or "")
    return f"{source_type}::{title}::{publish_date}::{organization}::{company or industry or code}"


def normalize_report_metadata(row: dict[str, Any], source_type: str) -> dict[str, Any]:
    field_rules = STOCK_REPORT_FIELD_RULES if source_type == "stock" else INDUSTRY_REPORT_FIELD_RULES
    organization = _clean_scalar(row.get("orgSName")) or _clean_scalar(row.get("orgName"))
    normalized = {
        "metadata_ref": _make_metadata_ref(row, source_type),
        "source_type": source_type,
        "title": _clean_scalar(row.get("title")),
        "company": _clean_scalar(row.get("stockName")) if source_type == "stock" else None,
        "stock_code": str(int(row.get("stockCode"))).zfill(6)
        if source_type == "stock" and _clean_scalar(row.get("stockCode")) is not None
        else None,
        "industry": _clean_scalar(row.get("indvInduName") if source_type == "stock" else row.get("industryName")),
        "publish_date": _clean_scalar(row.get("publishDate")),
        "organization": organization,
        "organization_full_name": _clean_scalar(row.get("orgName")),
        "organization_short_name": _clean_scalar(row.get("orgSName")),
        "institution_code": _clean_scalar(row.get("orgCode")),
        "rating_current": _clean_scalar(row.get("emRatingName")),
        "rating_previous": _clean_scalar(row.get("lastEmRatingName")),
        "rating_standard_name": _clean_scalar(row.get("sRatingName")),
        "rating_standard_code": _clean_scalar(row.get("sRatingCode")),
        "researchers": _clean_scalar(row.get("researcher")),
    }
    if source_type == "stock":
        normalized.update(
            {
                "market": _clean_scalar(row.get("market")),
                "is_new_coverage": _clean_scalar(row.get("indvIsNew")),
                "forecast_eps_this_year": _clean_scalar(row.get("predictThisYearEps")),
                "forecast_eps_next_year": _clean_scalar(row.get("predictNextYearEps")),
                "forecast_eps_two_year": _clean_scalar(row.get("predictNextTwoYearEps")),
                "forecast_pe_this_year": _clean_scalar(row.get("predictThisYearPe")),
                "forecast_pe_next_year": _clean_scalar(row.get("predictNextYearPe")),
                "forecast_pe_two_year": _clean_scalar(row.get("predictNextTwoYearPe")),
            }
        )
    return normalized


def load_field_descriptions(field_desc_path: Path) -> dict[str, dict[str, str]]:
    if not field_desc_path.exists():
        return {
            "stock": dict(STOCK_REPORT_FIELD_RULES),
            "industry": dict(INDUSTRY_REPORT_FIELD_RULES),
        }
    workbook = pd.ExcelFile(field_desc_path)
    mapping: dict[str, dict[str, str]] = {
        "stock": dict(STOCK_REPORT_FIELD_RULES),
        "industry": dict(INDUSTRY_REPORT_FIELD_RULES),
    }
    for source_type, sheet_name in [("stock", "个股_研报信息"), ("industry", "行业_研报信息")]:
        if sheet_name not in workbook.sheet_names:
            continue
        df = pd.read_excel(field_desc_path, sheet_name=sheet_name)
        if "字段名称" not in df.columns or "字段属性说明" not in df.columns:
            continue
        desc = {
            str(row["字段名称"]).strip(): str(row["字段属性说明"]).strip()
            for _, row in df.iterrows()
            if str(row.get("字段名称", "")).strip()
        }
        if desc:
            mapping[source_type].update(desc)
    return mapping


def normalize_report_metadata_with_rules(
    row: dict[str, Any],
    source_type: str,
    field_descriptions: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    metadata = normalize_report_metadata(row, source_type)
    return metadata


def build_report_metadata_lookup(
    stock_reports: pd.DataFrame,
    industry_reports: pd.DataFrame,
    field_descriptions: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for source_type, df in [("stock", stock_reports), ("industry", industry_reports)]:
        field_rules = (field_descriptions or {}).get(
            source_type,
            STOCK_REPORT_FIELD_RULES if source_type == "stock" else INDUSTRY_REPORT_FIELD_RULES,
        )
        for row in df.to_dict(orient="records"):
            core = normalize_report_metadata(row, source_type)
            typed_metadata = {field: _clean_scalar(row.get(field)) for field in field_rules}
            lookup[str(core["metadata_ref"])] = {
                **core,
                "report_metadata": typed_metadata,
                "metadata_field_rules": field_rules,
            }
    return lookup


__all__ = [
    "STOCK_REPORT_FIELD_RULES",
    "INDUSTRY_REPORT_FIELD_RULES",
    "build_report_metadata_lookup",
    "load_field_descriptions",
    "normalize_report_metadata",
    "normalize_report_metadata_with_rules",
]
