from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .models import ReportFile


TITLE_PATTERN = re.compile(
    r"(20\d{2})\s*年\s*(第一季度|一季度|半年度|第三季度|三季度|年度)\s*报(?:告|告全文|告摘要)?\s*(摘要|全文)?"
)
SOURCE_TITLE_PATTERN = re.compile(r"(20\d{2})\s*年\s*(第一季度|一季度|半年度|第三季度|三季度|年度)")
CODE_PATTERN = re.compile(r"(?:证券代码|公司代码|股票代码)\s*[:：]?\s*(\d{6})")
ABBR_PATTERN = re.compile(r"(?:证券简称|公司简称|股票简称)\s*[:：]?\s*([^\s]+)")
FALLBACK_ABBR_TO_CODE = {
    "贵州百灵": "002424",
    "赛隆药业": "002898",
    "香雪制药": "300147",
    "长药控股": "300391",
}


def _normalize_stock_code(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return digits[-6:].zfill(6)


def load_company_lookup(xlsx_path: Path) -> dict[str, dict[str, str]]:
    if not xlsx_path.exists():
        return {}
    df = pd.read_excel(xlsx_path, sheet_name="基本信息表")
    lookup: dict[str, dict[str, str]] = {}
    for row in df.to_dict(orient="records"):
        code = str(row.get("股票代码", "")).split(".")[0]
        if not code:
            continue
        lookup[code.zfill(6)] = {
            "stock_abbr": str(row.get("A股简称", "")).strip(),
            "company_name": str(row.get("公司名称", "")).strip(),
        }
    return lookup


def load_company_lookup_by_abbr(xlsx_path: Path) -> dict[str, dict[str, str]]:
    if not xlsx_path.exists():
        return {}
    df = pd.read_excel(xlsx_path, sheet_name="基本信息表")
    lookup: dict[str, dict[str, str]] = {}
    for row in df.to_dict(orient="records"):
        abbr = str(row.get("A股简称", "")).strip()
        code = str(row.get("股票代码", "")).split(".")[0].zfill(6)
        if not abbr:
            continue
        lookup[abbr.replace(" ", "")] = {
            "stock_code": code,
            "company_name": str(row.get("公司名称", "")).strip(),
        }
    return lookup


def enrich_report_with_company_info(
    report: ReportFile,
    lookup: dict[str, dict[str, str]],
    lookup_by_abbr: dict[str, dict[str, str]] | None = None,
) -> ReportFile:
    report.stock_code = _normalize_stock_code(report.stock_code)
    if report.stock_code and report.stock_code in lookup:
        if not report.stock_abbr:
            report.stock_abbr = lookup[report.stock_code]["stock_abbr"]
    elif report.stock_abbr and lookup_by_abbr:
        key = report.stock_abbr.replace(" ", "")
        if key in lookup_by_abbr:
            report.stock_code = lookup_by_abbr[key]["stock_code"]
    if not report.stock_code and report.stock_abbr:
        report.stock_code = FALLBACK_ABBR_TO_CODE.get(report.stock_abbr.replace(" ", ""))
    return report


def enrich_report_with_cover_text(report: ReportFile, cover_text: str) -> ReportFile:
    title_match = TITLE_PATTERN.search(cover_text)
    if title_match:
        report.report_year = int(title_match.group(1))
        report.report_period = title_match.group(2)
        report.report_type = title_match.group(3) or "全文"
    elif report.source_name:
        source_match = SOURCE_TITLE_PATTERN.search(report.source_name)
        if source_match:
            report.report_year = int(source_match.group(1))
            report.report_period = source_match.group(2)

    if not report.stock_code:
        code_match = CODE_PATTERN.search(cover_text)
        if code_match:
            report.stock_code = _normalize_stock_code(code_match.group(1))

    if not report.stock_abbr:
        abbr_match = ABBR_PATTERN.search(cover_text)
        if abbr_match:
            report.stock_abbr = abbr_match.group(1).strip()
    if not report.stock_code and report.stock_abbr:
        report.stock_code = FALLBACK_ABBR_TO_CODE.get(report.stock_abbr.replace(" ", ""))
    return report
