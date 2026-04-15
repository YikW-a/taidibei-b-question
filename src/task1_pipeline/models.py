from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


TableName = str


@dataclass
class ReportFile:
    exchange: str
    source_name: str
    source_path: str
    stock_code: str | None = None
    stock_abbr: str | None = None
    report_date: str | None = None
    report_year: int | None = None
    report_period: str | None = None
    report_type: str | None = None


@dataclass
class ExtractedTable:
    table_name: TableName
    page_number: int
    source_method: str
    dataframe: pd.DataFrame
    raw_title: str | None = None
    unit_hint: str | None = None


@dataclass
class StandardizedRecord:
    table_name: TableName
    values: dict[str, Any]
    source_name: str
    report_type: str | None
    page_number: int
    source_method: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationIssue:
    severity: str
    rule_name: str
    table_name: str
    source_name: str
    message: str
    record_key: str | None = None
