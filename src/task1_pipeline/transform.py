from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any

import pandas as pd

from .db import TABLE_SCHEMAS
from .field_rules import FIELD_RULES, PERIOD_ORDER
from .mappings import FIELD_ALIASES
from .models import ExtractedTable, ReportFile, StandardizedRecord
from .normalizers import clean_label, convert_for_field, normalize_report_period, parse_numeric

PERCENTAGE_SANITY_THRESHOLD = 1000.0
AMOUNT_SANITY_THRESHOLD_10K_YUAN = 100_000_000.0
EPS_SANITY_THRESHOLD = 20.0
PER_SHARE_SANITY_THRESHOLD = 200.0


class TableTransformer:
    def __init__(self) -> None:
        self._serial_counter = defaultdict(int)

    def transform(self, report: ReportFile, extracted: ExtractedTable) -> list[StandardizedRecord]:
        mapping = FIELD_ALIASES[extracted.table_name]
        record_values: dict[str, object] = {
            "stock_code": report.stock_code,
            "stock_abbr": report.stock_abbr,
            "report_year": report.report_year,
            "report_period": normalize_report_period(report.report_year, report.report_type, report.report_period),
        }
        warnings: list[str] = []
        mapped_count = 0

        if extracted.table_name == "core_performance_indicators_sheet":
            mapped_count = self._map_core_indicators(extracted.dataframe, mapping, record_values, extracted.unit_hint)
        else:
            mapped_count = self._map_statement_table(extracted.dataframe, mapping, record_values, extracted.unit_hint, extracted.source_method)

        self._serial_counter[extracted.table_name] += 1
        record_values["serial_number"] = self._serial_counter[extracted.table_name]
        if mapped_count == 0:
            warnings.append("no_mapped_fields_found")

        return [
            StandardizedRecord(
                table_name=extracted.table_name,
                values=record_values,
                source_name=report.source_name,
                report_type=report.report_type,
                page_number=extracted.page_number,
                source_method=extracted.source_method,
                warnings=warnings,
            )
        ]

    def _map_statement_table(
        self,
        dataframe: pd.DataFrame,
        mapping: dict[str, str],
        record_values: dict[str, object],
        unit_hint: str | None,
        source_method: str | None,
    ) -> int:
        effective_unit = unit_hint or "元"
        mapped_count = 0
        field_scores: dict[str, float] = {}
        allow_blank_zero = not _is_text_line_source(source_method)
        iterator_mapping = mapping if allow_blank_zero else None
        for label, numeric_texts in self._iter_row_labels_and_numeric_texts(dataframe, iterator_mapping):
            normalized_label = clean_label(label)
            if not normalized_label:
                continue
            numeric_texts = _clean_numeric_texts(numeric_texts)
            if not numeric_texts:
                if allow_blank_zero and (blank_zero_candidate := _blank_row_zero_candidate(mapping, normalized_label)) is not None:
                    alias, field_name = blank_zero_candidate
                    if _is_missing(record_values.get(field_name)):
                        candidate_score = _field_candidate_score(field_name, alias, normalized_label, ["0"], 0.0)
                        if field_name not in field_scores or candidate_score > field_scores[field_name]:
                            if field_name not in field_scores:
                                mapped_count += 1
                            field_scores[field_name] = candidate_score
                            record_values[field_name] = 0.0
                continue
            current_value = None
            previous_value = self._second_numeric(numeric_texts, effective_unit, None)
            for alias, field_name in mapping.items():
                if clean_label(alias) in normalized_label:
                    candidate_value = self._first_numeric(numeric_texts, effective_unit, field_name)
                    if candidate_value is not None:
                        current_value = candidate_value
                        candidate_score = _field_candidate_score(field_name, alias, normalized_label, numeric_texts, current_value)
                        if field_name not in field_scores or candidate_score > field_scores[field_name]:
                            if field_name not in field_scores:
                                mapped_count += 1
                            field_scores[field_name] = candidate_score
                            record_values[field_name] = current_value
                            self._apply_statement_derivations(field_name, current_value, previous_value, record_values)
        self._finalize_statement_derivations(record_values)
        return mapped_count

    def _map_core_indicators(
        self,
        dataframe: pd.DataFrame,
        mapping: dict[str, str],
        record_values: dict[str, object],
        unit_hint: str | None,
    ) -> int:
        effective_unit = unit_hint or "元"
        mapped_count = 0
        field_scores: dict[str, float] = {}
        pending_label = ""
        in_quarter_breakdown = False
        report_period = record_values.get("report_period")
        for label, numeric_texts in self._iter_row_labels_and_numeric_texts(dataframe):
            normalized_label = clean_label(label)
            if not normalized_label:
                continue
            numeric_texts = _clean_numeric_texts(numeric_texts)
            is_noise_label = _is_core_mapping_noise_label(normalized_label)
            if "分季度主要财务数据" in normalized_label or _is_core_quarter_breakdown_label(normalized_label):
                in_quarter_breakdown = True
            if normalized_label in {"(元)", "（元）", "的净利润", "经常性损益的净利润（元）"} and pending_label:
                normalized_label = clean_label(pending_label + normalized_label)
            else:
                pending_label = normalized_label

            current_value = None
            if not in_quarter_breakdown and not is_noise_label:
                for alias, field_name in mapping.items():
                    if clean_label(alias) in normalized_label:
                        candidate_value = self._core_first_numeric(
                            numeric_texts,
                            effective_unit,
                            field_name,
                            report_period,
                        )
                        if candidate_value is not None:
                            current_value = candidate_value
                            candidate_score = _field_candidate_score(field_name, alias, normalized_label, numeric_texts, current_value)
                            if field_name not in field_scores or candidate_score > field_scores[field_name]:
                                if field_name not in field_scores:
                                    mapped_count += 1
                                field_scores[field_name] = candidate_score
                                record_values[field_name] = current_value

            if (
                "营业收入" in normalized_label
                and not in_quarter_breakdown
                and not is_noise_label
                and (yoy_value := self._core_growth_numeric(numeric_texts, "total_operating_revenue", report_period)) is not None
                and _should_fill_derived_or_reused_value(record_values, "operating_revenue_yoy_growth")
            ):
                record_values["operating_revenue_yoy_growth"] = yoy_value
            if (
                "归属于上市公司股东的净利润" in normalized_label
                and "扣除非经常性损益" not in normalized_label
                and not in_quarter_breakdown
                and not is_noise_label
                and (yoy_value := self._core_growth_numeric(numeric_texts, "net_profit_10k_yuan", report_period)) is not None
                and _should_fill_derived_or_reused_value(record_values, "net_profit_yoy_growth")
            ):
                record_values["net_profit_yoy_growth"] = yoy_value
            if (
                "扣除非经常性损益" in normalized_label
                and not in_quarter_breakdown
                and not is_noise_label
                and (yoy_value := self._core_growth_numeric(numeric_texts, "net_profit_excl_non_recurring", report_period)) is not None
                and _should_fill_derived_or_reused_value(record_values, "net_profit_excl_non_recurring_yoy")
            ):
                record_values["net_profit_excl_non_recurring_yoy"] = yoy_value
            if (
                ("基本每股收益" in normalized_label or "每股收益" in normalized_label)
                and not in_quarter_breakdown
                and not is_noise_label
                and current_value is not None
                and _is_missing(record_values.get("eps"))
            ):
                record_values["eps"] = current_value
        return mapped_count

    def _core_first_numeric(
        self,
        numeric_texts: list[str],
        unit_hint: str | None,
        field_name: str,
        report_period: object,
    ) -> float | None:
        preferred_text = _select_core_report_amount_text(field_name, numeric_texts, report_period)
        if preferred_text is not None:
            preferred_value = convert_for_field(field_name, preferred_text, unit_hint)
            if preferred_value is not None:
                return preferred_value
        return self._first_numeric(numeric_texts, unit_hint, field_name)

    def _core_growth_numeric(
        self,
        numeric_texts: list[str],
        field_name: str,
        report_period: object,
    ) -> float | None:
        preferred_text = _select_core_report_growth_text(field_name, numeric_texts, report_period)
        if preferred_text is not None:
            preferred_value = parse_numeric(preferred_text, "%")
            if preferred_value is not None:
                return preferred_value
        return self._growth_numeric(numeric_texts)

    def _iter_row_labels_and_numeric_texts(
        self,
        dataframe: pd.DataFrame,
        mapping: dict[str, str] | None = None,
    ) -> list[tuple[str, list[str]]]:
        df = dataframe.copy()
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return []
        raw_rows: list[tuple[str, list[str]]] = []
        for _, row in df.iterrows():
            cells = ["" if pd.isna(v) else str(v).strip() for v in row.tolist()]
            if not any(cells):
                continue
            label_parts: list[str] = []
            numeric_texts: list[str] = []
            for cell in cells:
                if not cell:
                    continue
                inline_label, inline_numeric_texts = _split_inline_numeric_texts(cell)
                if inline_numeric_texts:
                    if inline_label:
                        label_parts.append(inline_label)
                    numeric_texts.extend(inline_numeric_texts)
                    continue
                if cell in {"-", "－", "+", "＋"}:
                    numeric_texts.append(cell)
                    continue
                parsed = parse_numeric(cell)
                looks_numeric = (
                    parsed is not None
                    and not any(ch.isalpha() or ("\u4e00" <= ch <= "\u9fff") for ch in cell if ch not in "%().-/＋+－-0123456789,， ")
                )
                starts_like_number = cell[:1].isdigit() or cell[:1] in {"-", "+", "－", "＋", "("}
                if (looks_numeric and starts_like_number) or cell == "不适用" or "百分点" in cell:
                    numeric_texts.append(cell)
                else:
                    label_parts.append(cell)
            label = "".join(label_parts).strip()
            raw_rows.append((label, numeric_texts))
        rows: list[tuple[str, list[str]]] = []
        pending_labels: list[str] = []
        for label, numeric_texts in raw_rows:
            if label and not numeric_texts:
                normalized_label = clean_label(label)
                if mapping is not None and _blank_row_zero_candidate(mapping, normalized_label) is not None:
                    if pending_labels:
                        rows.append(("".join(pending_labels), []))
                        pending_labels = []
                    rows.append((label, []))
                    continue
                pending_labels.append(label)
                continue
            merged_label = "".join(pending_labels + ([label] if label else []))
            if numeric_texts:
                rows.append((merged_label, numeric_texts))
                pending_labels = []
                continue
            if label:
                rows.append((merged_label, numeric_texts))
                pending_labels = []
        return rows

    def _first_numeric(self, numeric_texts: list[str], unit_hint: str | None, field_name: str) -> float | None:
        for text in numeric_texts:
            value = convert_for_field(field_name, text, unit_hint)
            if value is not None:
                return value
        return None

    def _second_numeric(self, numeric_texts: list[str], unit_hint: str | None, field_name: str | None) -> float | None:
        found = []
        for text in numeric_texts:
            if field_name is None:
                value = parse_numeric(text, unit_hint)
            else:
                value = convert_for_field(field_name, text, unit_hint)
            if value is not None:
                found.append(value)
        return found[1] if len(found) > 1 else None

    def _growth_numeric(self, numeric_texts: list[str]) -> float | None:
        if len(numeric_texts) < 3:
            return None
        for text in numeric_texts[2:]:
            if "%" not in text and "百分点" not in text:
                parsed_candidate = parse_numeric(text, None)
                if parsed_candidate is None or abs(parsed_candidate) > 500:
                    continue
            value = parse_numeric(text, "%")
            if value is not None:
                return value
        return None

    def _apply_statement_derivations(
        self,
        field_name: str,
        current_value: float | None,
        previous_value: float | None,
        record_values: dict[str, object],
    ) -> None:
        if current_value is None or previous_value in (None, 0):
            return
        growth = ((current_value - previous_value) / abs(previous_value)) * 100
        if field_name == "asset_total_assets" and _should_fill_derived_or_reused_value(record_values, "asset_total_assets_yoy_growth"):
            record_values["asset_total_assets_yoy_growth"] = growth
        elif field_name == "liability_total_liabilities" and _should_fill_derived_or_reused_value(
            record_values, "liability_total_liabilities_yoy_growth"
        ):
            record_values["liability_total_liabilities_yoy_growth"] = growth
        elif field_name == "total_operating_revenue" and _should_fill_derived_or_reused_value(
            record_values, "operating_revenue_yoy_growth"
        ):
            record_values["operating_revenue_yoy_growth"] = growth
        elif field_name == "net_profit" and _should_fill_derived_or_reused_value(record_values, "net_profit_yoy_growth"):
            record_values["net_profit_yoy_growth"] = growth
        elif field_name == "net_cash_flow" and _should_fill_derived_or_reused_value(record_values, "net_cash_flow_yoy_growth"):
            record_values["net_cash_flow_yoy_growth"] = growth

    def _finalize_statement_derivations(self, record_values: dict[str, object]) -> None:
        assets = record_values.get("asset_total_assets")
        liabilities = record_values.get("liability_total_liabilities")
        if assets not in (None, 0, "") and liabilities not in (None, ""):
            if _should_fill_derived_or_reused_value(record_values, "asset_liability_ratio"):
                try:
                    record_values["asset_liability_ratio"] = float(liabilities) / float(assets) * 100
                except Exception:
                    pass
        if record_values.get("equity_total_equity") in (None, "") and assets not in (None, "") and liabilities not in (None, ""):
            try:
                record_values["equity_total_equity"] = float(assets) - float(liabilities)
            except Exception:
                pass


def records_to_dataframes(records: list[StandardizedRecord]) -> dict[str, pd.DataFrame]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[record.table_name].append(record.values)
    output: dict[str, pd.DataFrame] = {}
    for table_name, items in grouped.items():
        dataframe = pd.DataFrame(items)
        schema_columns = [column_name for column_name, _ in TABLE_SCHEMAS[table_name]]
        for column_name in schema_columns:
            if column_name not in dataframe.columns:
                dataframe[column_name] = pd.NA
        output[table_name] = dataframe[schema_columns]
    return output


def consolidate_records(records: list[StandardizedRecord]) -> list[StandardizedRecord]:
    grouped: dict[tuple[str, str, str, str], list[StandardizedRecord]] = defaultdict(list)
    for record in records:
        values = record.values
        key = (
            record.table_name,
            str(values.get("stock_code", "")),
            str(values.get("report_period", "")),
            str(values.get("report_year", "")),
        )
        grouped[key].append(record)

    consolidated: list[StandardizedRecord] = []
    for _, candidates in grouped.items():
        candidates = sorted(candidates, key=_record_rank, reverse=True)
        base = candidates[0]
        merged_values: dict[str, Any] = {}
        merged_sources: list[str] = []
        merged_warnings: list[str] = []
        for candidate in candidates:
            if candidate.source_name not in merged_sources:
                merged_sources.append(candidate.source_name)
            for warning in candidate.warnings:
                if warning not in merged_warnings:
                    merged_warnings.append(warning)
            for field, value in candidate.values.items():
                if field not in merged_values or _is_missing(merged_values[field]):
                    if not _is_missing(value):
                        merged_values[field] = value
                elif _is_missing(merged_values[field]) and not _is_missing(value):
                    merged_values[field] = value

        consolidated.append(
            StandardizedRecord(
                table_name=base.table_name,
                values=merged_values,
                source_name=";".join(merged_sources),
                report_type=base.report_type,
                page_number=base.page_number,
                source_method=base.source_method,
                warnings=_finalize_warnings(merged_warnings, merged_values),
            )
        )
    return consolidated


def enrich_consolidated_records(records: list[StandardizedRecord]) -> list[StandardizedRecord]:
    grouped: dict[tuple[str, str, str], dict[str, StandardizedRecord]] = defaultdict(dict)
    for record in records:
        values = record.values
        key = (
            str(values.get("stock_code", "")),
            str(values.get("report_period", "")),
            str(values.get("report_year", "")),
        )
        grouped[key][record.table_name] = record

    for tables in grouped.values():
        balance = tables.get("balance_sheet")
        cash_flow = tables.get("cash_flow_sheet")
        income = tables.get("income_sheet")
        kpi = tables.get("core_performance_indicators_sheet")

        if balance is not None:
            _derive_balance_fields(balance.values)
        if cash_flow is not None:
            _derive_cash_flow_fields(cash_flow.values)
        if kpi is not None:
            _enrich_kpi_from_related_tables(
                kpi.values,
                income.values if income else {},
                balance.values if balance else {},
                cash_flow.values if cash_flow else {},
            )

    return records


def sanitize_consolidated_records(records: list[StandardizedRecord]) -> list[StandardizedRecord]:
    grouped: dict[tuple[str, str, str], dict[str, StandardizedRecord]] = defaultdict(dict)
    grouped_by_company_year: dict[tuple[str, str], dict[str, dict[str, StandardizedRecord]]] = defaultdict(dict)
    grouped_company_years: dict[str, dict[str, dict[str, dict[str, StandardizedRecord]]]] = defaultdict(lambda: defaultdict(dict))
    grouped_by_company_period: dict[tuple[str, str], dict[str, dict[str, StandardizedRecord]]] = defaultdict(dict)
    for record in records:
        values = record.values
        key = (
            str(values.get("stock_code", "")),
            str(values.get("report_period", "")),
            str(values.get("report_year", "")),
        )
        grouped[key][record.table_name] = record

    for key, tables in grouped.items():
        balance = tables.get("balance_sheet")
        cash_flow = tables.get("cash_flow_sheet")
        income = tables.get("income_sheet")
        kpi = tables.get("core_performance_indicators_sheet")

        if balance is not None:
            _sanitize_record_values(balance.values)
            _derive_balance_fields(balance.values)
        if cash_flow is not None:
            _sanitize_record_values(cash_flow.values)
            _derive_cash_flow_fields(cash_flow.values)
        if income is not None:
            _sanitize_record_values(income.values)
        _apply_field_rule_constraints(tables)
        grouped_by_company_year[(key[0], key[2])][key[1]] = tables
        grouped_company_years[key[0]][key[2]][key[1]] = tables
        period_suffix = _period_suffix(key[1])
        if period_suffix:
            grouped_by_company_period[(key[0], period_suffix)][key[2]] = tables

    for period_tables in grouped_by_company_year.values():
        _derive_company_year_qoq_fields(period_tables)

    for company_years in grouped_company_years.values():
        _derive_company_cross_year_q1_qoq_fields(company_years)

    for year_tables in grouped_by_company_period.values():
        _derive_company_period_yoy_fields(year_tables)

    for tables in grouped.values():
        kpi = tables.get("core_performance_indicators_sheet")
        income = tables.get("income_sheet")
        balance = tables.get("balance_sheet")
        cash_flow = tables.get("cash_flow_sheet")
        if kpi is not None:
            _sanitize_kpi_values(
                kpi.values,
                income.values if income else {},
                balance.values if balance else {},
                cash_flow.values if cash_flow else {},
            )

    return records


def _record_rank(record: StandardizedRecord) -> tuple[int, int, int, int]:
    mapped_field_count = sum(1 for value in record.values.values() if not _is_missing(value))
    method_priority = _source_method_priority(record.source_method)
    is_full = 1 if (record.report_type or "") == "全文" else 0
    warning_penalty = -len(record.warnings)
    return (method_priority, mapped_field_count, is_full, warning_penalty)


def _source_method_priority(source_method: str | None) -> int:
    method = source_method or ""
    if method.startswith("pdfplumber") or method.startswith("pymupdf.find_tables"):
        return 4
    if method.startswith("camelot"):
        return 3
    if method == "text_fallback":
        return 2
    if method.startswith("fitz.combined_text"):
        return 1
    return 0


def _is_text_line_source(source_method: str | None) -> bool:
    method = source_method or ""
    return method.startswith("fitz.combined_text") or method == "text_fallback"


def _is_missing(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _finalize_warnings(warnings: list[str], values: dict[str, Any]) -> list[str]:
    mapped_fields = [
        k
        for k, v in values.items()
        if k not in {"serial_number", "stock_code", "stock_abbr", "report_period", "report_year"} and not _is_missing(v)
    ]
    final = list(warnings)
    if mapped_fields and "no_mapped_fields_found" in final:
        final = [w for w in final if w != "no_mapped_fields_found"]
    return final


def _derive_balance_fields(values: dict[str, Any]) -> None:
    assets = _safe_float(values.get("asset_total_assets"))
    liabilities = _safe_float(values.get("liability_total_liabilities"))
    equity = _safe_float(values.get("equity_total_equity"))
    if values.get("liability_contract_liabilities") in (None, "") and values.get("liability_advance_from_customers") not in (None, ""):
        values["liability_contract_liabilities"] = values.get("liability_advance_from_customers")
    if assets is not None and liabilities is not None:
        derived_equity = assets - liabilities
        if equity is None or _balance_equity_is_mismatched(assets, liabilities, equity):
            values["equity_total_equity"] = derived_equity
    if values.get("asset_liability_ratio") in (None, "") and assets not in (None, 0) and liabilities is not None:
        values["asset_liability_ratio"] = liabilities / assets * 100


def _derive_cash_flow_fields(values: dict[str, Any]) -> None:
    operating = _safe_float(values.get("operating_cf_net_amount"))
    investing = _safe_float(values.get("investing_cf_net_amount"))
    financing = _safe_float(values.get("financing_cf_net_amount"))
    net_cash = _safe_float(values.get("net_cash_flow"))
    if net_cash is None and None not in (operating, investing, financing):
        net_cash = operating + investing + financing
        values["net_cash_flow"] = net_cash
    if financing is None and None not in (net_cash, operating, investing):
        financing = net_cash - operating - investing
        values["financing_cf_net_amount"] = financing
    if investing is None and None not in (net_cash, operating, financing):
        investing = net_cash - operating - financing
        values["investing_cf_net_amount"] = investing
    if operating is None and None not in (net_cash, investing, financing):
        operating = net_cash - investing - financing
        values["operating_cf_net_amount"] = operating
    if net_cash in (None, 0):
        return
    for amount_field, ratio_field in [
        ("operating_cf_net_amount", "operating_cf_ratio_of_net_cf"),
        ("investing_cf_net_amount", "investing_cf_ratio_of_net_cf"),
        ("financing_cf_net_amount", "financing_cf_ratio_of_net_cf"),
    ]:
        if values.get(ratio_field) not in (None, ""):
            continue
        amount = _safe_float(values.get(amount_field))
        if amount is None:
            continue
        values[ratio_field] = amount / net_cash * 100


def _apply_field_rule_constraints(tables: dict[str, StandardizedRecord]) -> None:
    values_by_table = {table_name: record.values for table_name, record in tables.items()}

    balance_values = values_by_table.get("balance_sheet", {})
    cash_flow_values = values_by_table.get("cash_flow_sheet", {})
    income_values = values_by_table.get("income_sheet", {})
    kpi_values = values_by_table.get("core_performance_indicators_sheet", {})

    if balance_values:
        for field_name, rule in FIELD_RULES.get("balance_sheet", {}).items():
            _enforce_field_rule("balance_sheet", field_name, rule, values_by_table)

    if cash_flow_values:
        for field_name, rule in FIELD_RULES.get("cash_flow_sheet", {}).items():
            _enforce_field_rule("cash_flow_sheet", field_name, rule, values_by_table)

    if kpi_values:
        for field_name, rule in FIELD_RULES.get("core_performance_indicators_sheet", {}).items():
            _enforce_field_rule("core_performance_indicators_sheet", field_name, rule, values_by_table)

        if kpi_values.get("total_operating_revenue") in (None, "") and income_values.get("total_operating_revenue") not in (None, ""):
            kpi_values["total_operating_revenue"] = income_values.get("total_operating_revenue")
        if kpi_values.get("net_profit_10k_yuan") in (None, "") and income_values.get("net_profit") not in (None, ""):
            kpi_values["net_profit_10k_yuan"] = income_values.get("net_profit")


def _enforce_field_rule(
    table_name: str,
    field_name: str,
    rule: dict[str, object],
    values_by_table: dict[str, dict[str, Any]],
) -> None:
    target_values = values_by_table.get(table_name)
    if not target_values:
        return

    mode = str(rule.get("mode", "direct"))
    current_value = _safe_float(target_values.get(field_name))
    source_value = None
    if "source" in rule:
        source_value = _resolve_field_source(values_by_table, str(rule["source"]))

    if mode == "prefer_reuse" and source_value not in (None, ""):
        target_values[field_name] = source_value
        return

    if mode in {"reuse", "direct_or_reuse"} and source_value not in (None, ""):
        if target_values.get(field_name) in (None, ""):
            target_values[field_name] = source_value
        return

    if mode == "prefer_derive":
        derived_value = _derive_rule_value(table_name, field_name, values_by_table)
        if derived_value is not None:
            target_values[field_name] = derived_value
        return

    if mode in {"derive", "direct_or_derive"}:
        derived_value = _derive_rule_value(table_name, field_name, values_by_table)
        if derived_value is not None and _should_fill_derived_or_reused_value(target_values, field_name):
            target_values[field_name] = derived_value
        return

    if mode == "direct" and _looks_like_percentage_field(field_name) and _is_suspicious_percentage(current_value):
        target_values[field_name] = None


def _resolve_field_source(values_by_table: dict[str, dict[str, Any]], source_spec: str) -> Any:
    try:
        table_name, field_name = source_spec.split(".", 1)
    except ValueError:
        return None
    return values_by_table.get(table_name, {}).get(field_name)


def _derive_rule_value(table_name: str, field_name: str, values_by_table: dict[str, dict[str, Any]]) -> float | None:
    balance_values = values_by_table.get("balance_sheet", {})
    cash_flow_values = values_by_table.get("cash_flow_sheet", {})
    income_values = values_by_table.get("income_sheet", {})
    kpi_values = values_by_table.get("core_performance_indicators_sheet", {})

    if table_name == "balance_sheet":
        assets = _safe_float(balance_values.get("asset_total_assets"))
        liabilities = _safe_float(balance_values.get("liability_total_liabilities"))
        if field_name == "asset_liability_ratio" and assets not in (None, 0) and liabilities is not None:
            return liabilities / assets * 100
        if field_name == "equity_total_equity" and assets is not None and liabilities is not None:
            return assets - liabilities
        if field_name == "liability_contract_liabilities":
            return _safe_float(balance_values.get("liability_advance_from_customers"))

    if table_name == "cash_flow_sheet":
        operating = _safe_float(cash_flow_values.get("operating_cf_net_amount"))
        investing = _safe_float(cash_flow_values.get("investing_cf_net_amount"))
        financing = _safe_float(cash_flow_values.get("financing_cf_net_amount"))
        net_cash = _safe_float(cash_flow_values.get("net_cash_flow"))
        if field_name == "net_cash_flow" and None not in (operating, investing, financing):
            return operating + investing + financing
        if field_name == "operating_cf_ratio_of_net_cf" and net_cash not in (None, 0) and operating is not None:
            return operating / net_cash * 100
        if field_name == "investing_cf_ratio_of_net_cf" and net_cash not in (None, 0) and investing is not None:
            return investing / net_cash * 100
        if field_name == "financing_cf_ratio_of_net_cf" and net_cash not in (None, 0) and financing is not None:
            return financing / net_cash * 100

    if table_name == "core_performance_indicators_sheet":
        revenue = _safe_float(income_values.get("total_operating_revenue")) or _safe_float(kpi_values.get("total_operating_revenue"))
        cost = _safe_float(income_values.get("operating_expense_cost_of_sales"))
        net_profit = _safe_float(income_values.get("net_profit")) or _safe_float(kpi_values.get("net_profit_10k_yuan"))
        equity = _safe_float(balance_values.get("equity_total_equity"))
        operating_cf = _safe_float(cash_flow_values.get("operating_cf_net_amount"))
        eps = _safe_float(kpi_values.get("eps"))
        net_profit_excl = _safe_float(kpi_values.get("net_profit_excl_non_recurring"))
        shares = _infer_share_count(net_profit, eps)

        if field_name == "net_asset_per_share" and shares not in (None, 0) and equity is not None:
            return (equity * 10000) / shares
        if field_name == "roe" and equity not in (None, 0) and net_profit is not None:
            return net_profit / equity * 100
        if field_name == "operating_cf_per_share" and shares not in (None, 0) and operating_cf is not None:
            return (operating_cf * 10000) / shares
        if field_name == "gross_profit_margin" and revenue not in (None, 0) and cost is not None:
            return (revenue - cost) / revenue * 100
        if field_name == "net_profit_margin" and revenue not in (None, 0) and net_profit is not None:
            return net_profit / revenue * 100
        if field_name == "roe_weighted_excl_non_recurring" and equity not in (None, 0) and net_profit_excl is not None:
            return net_profit_excl / equity * 100
    return None


def _derive_company_year_qoq_fields(period_tables: dict[str, dict[str, StandardizedRecord]]) -> None:
    ordered_periods = sorted(
        (period for period in period_tables.keys() if period),
        key=lambda item: PERIOD_ORDER.get(_period_suffix(item), 999),
    )
    if not ordered_periods:
        return
    for metric_field, qoq_field, income_fallback_field in [
        ("total_operating_revenue", "operating_revenue_qoq_growth", "total_operating_revenue"),
        ("net_profit_10k_yuan", "net_profit_qoq_growth", "net_profit"),
    ]:
        cumulative_values: dict[str, float] = {}
        for period in ordered_periods:
            tables = period_tables[period]
            value = _resolve_qoq_metric_value(tables, metric_field, income_fallback_field)
            if value is not None:
                cumulative_values[_period_suffix(period)] = value

        single_quarter_values = _build_single_quarter_values(cumulative_values)
        previous_single = None
        for period in ordered_periods:
            suffix = _period_suffix(period)
            tables = period_tables[period]
            kpi_record = tables.get("core_performance_indicators_sheet")
            if kpi_record is None:
                continue
            current_single = single_quarter_values.get(suffix)
            if current_single is None:
                previous_single = previous_single if suffix != "Q1" else current_single
                continue
            if previous_single not in (None, 0) and suffix != "Q1":
                growth = (current_single - previous_single) / abs(previous_single) * 100
                current_qoq = _safe_float(kpi_record.values.get(qoq_field))
                if kpi_record.values.get(qoq_field) in (None, "") or _is_suspicious_percentage(current_qoq):
                    kpi_record.values[qoq_field] = growth
            previous_single = current_single


def _derive_company_cross_year_q1_qoq_fields(
    company_years: dict[str, dict[str, dict[str, StandardizedRecord]]]
) -> None:
    ordered_years = sorted((year for year in company_years.keys() if str(year).isdigit()), key=lambda item: int(item))
    if not ordered_years:
        return

    for metric_field, qoq_field, income_fallback_field in [
        ("total_operating_revenue", "operating_revenue_qoq_growth", "total_operating_revenue"),
        ("net_profit_10k_yuan", "net_profit_qoq_growth", "net_profit"),
    ]:
        for year in ordered_years:
            current_tables = company_years.get(year, {})
            current_period = f"{year}Q1"
            q1_tables = current_tables.get(current_period)
            if not q1_tables:
                continue
            kpi_record = q1_tables.get("core_performance_indicators_sheet")
            if kpi_record is None:
                continue
            current_qoq = _safe_float(kpi_record.values.get(qoq_field))
            if kpi_record.values.get(qoq_field) not in (None, "") and not _is_suspicious_percentage(current_qoq):
                continue

            previous_year = str(int(year) - 1)
            previous_tables = company_years.get(previous_year, {})
            prev_q3_tables = previous_tables.get(f"{previous_year}Q3")
            prev_fy_tables = previous_tables.get(f"{previous_year}FY")
            if not prev_q3_tables or not prev_fy_tables:
                continue

            current_q1 = _resolve_qoq_metric_value(q1_tables, metric_field, income_fallback_field)
            prev_q3 = _resolve_qoq_metric_value(prev_q3_tables, metric_field, income_fallback_field)
            prev_fy = _resolve_qoq_metric_value(prev_fy_tables, metric_field, income_fallback_field)
            if None in (current_q1, prev_q3, prev_fy):
                continue

            previous_q4 = prev_fy - prev_q3
            if previous_q4 == 0:
                continue
            kpi_record.values[qoq_field] = (current_q1 - previous_q4) / abs(previous_q4) * 100


def _derive_company_period_yoy_fields(year_tables: dict[str, dict[str, StandardizedRecord]]) -> None:
    ordered_years = sorted((year for year in year_tables.keys() if str(year).isdigit()), key=lambda item: int(item))
    if not ordered_years:
        return
    previous_excl_non_recurring = None
    for year in ordered_years:
        tables = year_tables[year]
        kpi_record = tables.get("core_performance_indicators_sheet")
        if kpi_record is None:
            continue
        current_value = _safe_float(kpi_record.values.get("net_profit_excl_non_recurring"))
        if current_value is None:
            continue
        if previous_excl_non_recurring not in (None, 0):
            growth = (current_value - previous_excl_non_recurring) / abs(previous_excl_non_recurring) * 100
            current_growth = _safe_float(kpi_record.values.get("net_profit_excl_non_recurring_yoy"))
            if kpi_record.values.get("net_profit_excl_non_recurring_yoy") in (None, "") or _is_suspicious_percentage(current_growth):
                kpi_record.values["net_profit_excl_non_recurring_yoy"] = growth
        previous_excl_non_recurring = current_value


def _build_single_quarter_values(cumulative_values: dict[str, float]) -> dict[str, float]:
    singles: dict[str, float] = {}
    q1 = cumulative_values.get("Q1")
    if q1 is not None:
        singles["Q1"] = q1
    h1 = cumulative_values.get("H1")
    if h1 is not None and q1 is not None:
        singles["H1"] = h1 - q1
    q3 = cumulative_values.get("Q3")
    if q3 is not None and h1 is not None:
        singles["Q3"] = q3 - h1
    fy = cumulative_values.get("FY")
    if fy is not None and q3 is not None:
        singles["FY"] = fy - q3
    return singles


def _resolve_qoq_metric_value(
    tables: dict[str, StandardizedRecord],
    metric_field: str,
    income_fallback_field: str,
) -> float | None:
    kpi_record = tables.get("core_performance_indicators_sheet")
    income_record = tables.get("income_sheet")
    kpi_values = kpi_record.values if kpi_record else {}
    income_values = income_record.values if income_record else {}
    value = _safe_float(kpi_values.get(metric_field))
    if value is not None:
        return value
    value = _safe_float(income_values.get(income_fallback_field))
    if value is not None and kpi_record is not None:
        kpi_record.values[metric_field] = value
    return value


def _period_suffix(report_period: str | None) -> str:
    if not report_period:
        return ""
    for suffix in PERIOD_ORDER:
        if str(report_period).endswith(suffix):
            return suffix
    return str(report_period)


def _enrich_kpi_from_related_tables(
    kpi_values: dict[str, Any],
    income_values: dict[str, Any],
    balance_values: dict[str, Any],
    cash_flow_values: dict[str, Any],
) -> None:
    report_period = str(kpi_values.get("report_period", ""))
    revenue = _select_kpi_margin_revenue(
        _safe_float(income_values.get("total_operating_revenue")),
        _safe_float(kpi_values.get("total_operating_revenue")),
        _safe_float(income_values.get("operating_expense_cost_of_sales")),
        _safe_float(income_values.get("net_profit")),
    )
    cost = _safe_float(income_values.get("operating_expense_cost_of_sales"))
    net_profit = _safe_float(income_values.get("net_profit"))
    gross_profit_margin = None
    net_profit_margin = None
    if revenue not in (None, 0) and cost is not None:
        gross_profit_margin = (revenue - cost) / revenue * 100
    if revenue not in (None, 0) and net_profit is not None:
        net_profit_margin = net_profit / revenue * 100

    for field_name, income_value in [
        ("total_operating_revenue", _safe_float(income_values.get("total_operating_revenue"))),
        ("net_profit_10k_yuan", _safe_float(income_values.get("net_profit"))),
    ]:
        current_value = _safe_float(kpi_values.get(field_name))
        if income_value is None:
            continue
        if _should_override_kpi_amount_with_income(current_value, income_value, report_period):
            kpi_values[field_name] = income_value

    for field_name, value in [
        ("total_operating_revenue", income_values.get("total_operating_revenue")),
        ("operating_revenue_yoy_growth", income_values.get("operating_revenue_yoy_growth")),
        ("net_profit_10k_yuan", income_values.get("net_profit")),
        ("net_profit_yoy_growth", income_values.get("net_profit_yoy_growth")),
    ]:
        if value not in (None, "") and _should_fill_derived_or_reused_value(kpi_values, field_name):
            kpi_values[field_name] = value

    for field_name, value, tolerance in [
        ("gross_profit_margin", gross_profit_margin, 20.0),
        ("net_profit_margin", net_profit_margin, 20.0),
    ]:
        if value is None:
            continue
        current_value = _safe_float(kpi_values.get(field_name))
        if _should_override_percentage_with_derived(current_value, value, tolerance):
            kpi_values[field_name] = value

    equity = _safe_float(balance_values.get("equity_total_equity"))
    if equity not in (None, 0) and net_profit is not None and _should_fill_derived_or_reused_value(kpi_values, "roe"):
        kpi_values["roe"] = net_profit / equity * 100

    net_profit_excl = _safe_float(kpi_values.get("net_profit_excl_non_recurring"))
    if (
        equity not in (None, 0)
        and net_profit_excl is not None
        and _should_fill_derived_or_reused_value(kpi_values, "roe_weighted_excl_non_recurring")
    ):
        kpi_values["roe_weighted_excl_non_recurring"] = net_profit_excl / equity * 100

    eps = _safe_float(kpi_values.get("eps"))
    shares = _infer_share_count(net_profit, eps)
    if shares in (None, 0):
        return

    if equity is not None:
        derived_net_asset_per_share = (equity * 10000) / shares
        current_net_asset_per_share = _safe_float(kpi_values.get("net_asset_per_share"))
        if _should_override_per_share_with_derived(current_net_asset_per_share, derived_net_asset_per_share):
            kpi_values["net_asset_per_share"] = derived_net_asset_per_share

    operating_cf = _safe_float(cash_flow_values.get("operating_cf_net_amount"))
    if operating_cf is not None:
        derived_operating_cf_per_share = (operating_cf * 10000) / shares
        current_operating_cf_per_share = _safe_float(kpi_values.get("operating_cf_per_share"))
        if _should_override_per_share_with_derived(current_operating_cf_per_share, derived_operating_cf_per_share):
            kpi_values["operating_cf_per_share"] = derived_operating_cf_per_share


def _should_fill_derived_or_reused_value(values: dict[str, Any], field_name: str) -> bool:
    current = values.get(field_name)
    if _is_missing(current):
        return True
    if _looks_like_percentage_field(field_name):
        return _is_suspicious_percentage(_safe_float(current))
    return False


def _should_override_percentage_with_derived(
    current_value: float | None,
    derived_value: float,
    tolerance: float,
) -> bool:
    if current_value is None:
        return True
    if _is_suspicious_percentage(current_value):
        return True
    return abs(current_value - derived_value) > tolerance


def _should_override_per_share_with_derived(current_value: float | None, derived_value: float) -> bool:
    if current_value is None:
        return True
    if current_value == 0 or derived_value == 0:
        return abs(current_value - derived_value) > 1.0
    if current_value * derived_value < 0:
        return True
    tolerance = max(1.0, abs(current_value) * 0.8, abs(derived_value) * 0.8)
    return abs(current_value - derived_value) > tolerance


def _select_kpi_margin_revenue(
    income_revenue: float | None,
    kpi_revenue: float | None,
    cost: float | None,
    net_profit: float | None,
) -> float | None:
    candidates: list[tuple[float, float]] = []
    for revenue in (income_revenue, kpi_revenue):
        if revenue in (None, 0) or revenue <= 0:
            continue
        candidates.append((_margin_candidate_score(revenue, cost, net_profit), revenue))
    if not candidates:
        return income_revenue or kpi_revenue
    candidates.sort(key=lambda item: (item[0], -abs(item[1])))
    return candidates[0][1]


def _margin_candidate_score(revenue: float, cost: float | None, net_profit: float | None) -> float:
    score = 0.0
    gross_margin = None
    net_margin = None
    if revenue != 0 and cost is not None:
        gross_margin = (revenue - cost) / revenue * 100
    if revenue != 0 and net_profit is not None:
        net_margin = net_profit / revenue * 100

    for value in (gross_margin, net_margin):
        if value is None:
            continue
        if abs(value) > 100:
            score += 1000.0 + abs(value)
        if value < -50:
            score += abs(value) - 50.0

    if gross_margin is not None and net_margin is not None and net_margin > gross_margin + 20:
        score += 500.0 + (net_margin - gross_margin - 20)
    return score


def _select_core_report_amount_text(
    field_name: str,
    numeric_texts: list[str],
    report_period: object,
) -> str | None:
    if _period_suffix(str(report_period)) != "Q3":
        return None
    if field_name not in {
        "total_operating_revenue",
        "net_profit_10k_yuan",
        "net_profit_excl_non_recurring",
        "eps",
        "operating_cf_per_share",
    }:
        return None
    ordered_tokens = [
        str(text).strip()
        for text in numeric_texts
        if parse_numeric(text, None) is not None
    ]
    if len(ordered_tokens) >= 4 and len(ordered_tokens) % 2 == 0:
        return ordered_tokens[len(ordered_tokens) // 2]
    amount_tokens = [
        str(text).strip()
        for text in numeric_texts
        if "%" not in str(text) and "百分点" not in str(text)
    ]
    if len(amount_tokens) >= 2:
        return amount_tokens[1]
    return None


def _select_core_report_growth_text(
    field_name: str,
    numeric_texts: list[str],
    report_period: object,
) -> str | None:
    if _period_suffix(str(report_period)) != "Q3":
        return None
    if field_name not in {
        "total_operating_revenue",
        "net_profit_10k_yuan",
        "net_profit_excl_non_recurring",
    }:
        return None
    ordered_tokens = [
        str(text).strip()
        for text in numeric_texts
        if parse_numeric(text, None) is not None
    ]
    if len(ordered_tokens) >= 4:
        return ordered_tokens[-1]
    return None


def _should_override_kpi_amount_with_income(
    current_value: float | None,
    income_value: float,
    report_period: str,
) -> bool:
    if current_value is None:
        return True
    suffix = _period_suffix(report_period)
    if suffix not in {"Q1", "H1", "Q3"}:
        return False
    if current_value == 0:
        return abs(income_value) > 100.0
    if current_value * income_value < 0:
        return True
    tolerance = max(100.0, abs(income_value) * 0.3)
    return abs(current_value - income_value) > tolerance


def _blank_row_zero_candidate(mapping: dict[str, str], normalized_label: str) -> tuple[str, str] | None:
    label_core = _strip_label_prefix(normalized_label)
    for alias, field_name in mapping.items():
        alias_clean = clean_label(alias)
        if not alias_clean or not _field_allows_blank_zero(field_name):
            continue
        if label_core == alias_clean or label_core.startswith(alias_clean):
            return alias, field_name
    return None


def _field_allows_blank_zero(field_name: str) -> bool:
    return field_name in {
        "asset_trading_financial_assets",
        "asset_construction_in_progress",
        "liability_short_term_loans",
        "liability_advance_from_customers",
        "liability_contract_liabilities",
        "financing_cf_cash_from_borrowing",
        "financing_cf_cash_for_debt_repayment",
        "investing_cf_cash_from_investment_recovery",
        "investing_cf_cash_for_investments",
    }


def _sanitize_record_values(values: dict[str, Any]) -> None:
    for field_name, value in list(values.items()):
        if field_name in {"serial_number", "stock_code", "stock_abbr", "report_period", "report_year"}:
            continue
        numeric_value = _safe_float(value)
        if numeric_value is None:
            continue
        if _is_suspicious_per_share_value(field_name, numeric_value):
            values[field_name] = None
            continue
        if _looks_like_percentage_field(field_name):
            if abs(numeric_value) > PERCENTAGE_SANITY_THRESHOLD:
                values[field_name] = None
        elif abs(numeric_value) > AMOUNT_SANITY_THRESHOLD_10K_YUAN:
            values[field_name] = None


def _sanitize_kpi_values(
    kpi_values: dict[str, Any],
    income_values: dict[str, Any],
    balance_values: dict[str, Any],
    cash_flow_values: dict[str, Any],
) -> None:
    _sanitize_record_values(kpi_values)
    _enrich_kpi_from_related_tables(kpi_values, income_values, balance_values, cash_flow_values)
    for field_name in [
        "gross_profit_margin",
        "net_profit_margin",
        "roe",
        "roe_weighted_excl_non_recurring",
        "operating_revenue_yoy_growth",
        "operating_revenue_qoq_growth",
        "net_profit_yoy_growth",
        "net_profit_qoq_growth",
        "net_profit_excl_non_recurring_yoy",
    ]:
        value = _safe_float(kpi_values.get(field_name))
        if _is_suspicious_percentage(value):
            kpi_values[field_name] = None
    _enrich_kpi_from_related_tables(kpi_values, income_values, balance_values, cash_flow_values)


def _looks_like_percentage_field(field_name: str) -> bool:
    if field_name.endswith("_ratio_of_net_cf"):
        return True
    markers = ("yoy", "qoq", "ratio", "margin", "roe")
    return any(marker in field_name for marker in markers) or field_name in {
        "asset_liability_ratio",
        "gross_profit_margin",
        "net_profit_margin",
        "roe",
        "roe_weighted_excl_non_recurring",
    }


def _infer_share_count(net_profit_10k_yuan: float | None, eps: float | None) -> float | None:
    if net_profit_10k_yuan in (None, 0) or eps in (None, 0):
        return None
    shares = (net_profit_10k_yuan * 10000) / eps
    if abs(shares) < 1_000_000 or abs(shares) > 1_000_000_000_000:
        return None
    return shares


def _safe_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _balance_equity_is_mismatched(assets: float, liabilities: float, equity: float) -> bool:
    derived_equity = assets - liabilities
    if derived_equity == 0:
        return False
    tolerance = max(100.0, abs(assets) * 0.02)
    if abs(derived_equity - equity) <= tolerance:
        return False
    if assets > 0 and liabilities >= 0 and derived_equity > 0 and equity > 0:
        return True
    return abs(derived_equity - equity) > max(tolerance, abs(derived_equity) * 0.5)


def _is_suspicious_percentage(value: float | None) -> bool:
    if value is None:
        return False
    return abs(value) > PERCENTAGE_SANITY_THRESHOLD


def _is_suspicious_per_share_value(field_name: str, value: float) -> bool:
    if field_name == "eps":
        return abs(value) > EPS_SANITY_THRESHOLD
    if field_name in {"net_asset_per_share", "operating_cf_per_share"}:
        return abs(value) > PER_SHARE_SANITY_THRESHOLD
    return False


def _field_candidate_score(
    field_name: str,
    alias: str,
    normalized_label: str,
    numeric_texts: list[str],
    value: float,
) -> float:
    alias_clean = clean_label(alias)
    label_core = _strip_label_prefix(normalized_label)

    score = 0.0
    if label_core == alias_clean:
        score += 100
    elif label_core.startswith(alias_clean):
        score += 80
    elif alias_clean in label_core:
        score += 55
    else:
        score += 20

    score += min(len(alias_clean), 20)
    score += min(len(numeric_texts), 3) * 6
    score += min(math.log10(abs(value) + 1), 12)

    if field_name == "net_profit" and any(
        keyword in normalized_label for keyword in ("归属于母公司", "归属于上市公司", "归属于本公司")
    ):
        score += 60

    if field_name == "equity_total_equity":
        if any(keyword in label_core for keyword in ("所有者权益合计", "股东权益合计", "所有者权益(或股东权益)合计")):
            score += 70
        if any(keyword in normalized_label for keyword in ("归属于母公司", "归属于上市公司", "归属于本公司")):
            score -= 70
        if "少数股东权益" in normalized_label:
            score -= 120

    if _is_probable_note_marker(numeric_texts):
        score -= 90

    if field_name in {"eps", "net_asset_per_share", "operating_cf_per_share"} and alias_clean not in {"每股收益"}:
        if alias_clean not in label_core[: len(alias_clean) + 2]:
            score -= 65

    score -= _field_label_penalty(field_name, normalized_label)
    return score


def _strip_label_prefix(label: str) -> str:
    cleaned = label
    for _ in range(4):
        updated = re.sub(r"^[（(]?[一二三四五六七八九十\d]+[）).、\.]*", "", cleaned)
        updated = re.sub(r"^[\.·:：\-]+", "", updated)
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _is_probable_note_marker(numeric_texts: list[str]) -> bool:
    if len(numeric_texts) != 1:
        return False
    raw = str(numeric_texts[0]).strip()
    if "." in raw or "%" in raw or any(unit in raw for unit in ("亿", "万", "元", "百分点")):
        return False
    parsed = parse_numeric(raw, None)
    if parsed is None:
        return False
    return float(parsed).is_integer() and 0 <= parsed <= 20


def _field_label_penalty(field_name: str, normalized_label: str) -> float:
    penalty = 0.0
    if field_name == "net_profit":
        for keyword in [
            "持续经营",
            "终止经营",
            "少数股东损益",
        ]:
            if keyword in normalized_label:
                penalty += 35
    if field_name == "eps" and "稀释" in normalized_label and "基本" not in normalized_label:
        penalty += 20
    return penalty


def _is_core_mapping_noise_label(normalized_label: str) -> bool:
    return (
        _is_core_quarter_breakdown_label(normalized_label)
        or _is_probable_narrative_label(normalized_label)
        or _is_probable_merged_metric_label(normalized_label)
    )


def _is_core_quarter_breakdown_label(normalized_label: str) -> bool:
    quarter_markers = ("第一季度", "第二季度", "第三季度", "第四季度", "1-3月份", "4-6月份", "7-9月份", "10-12月份")
    return sum(1 for marker in quarter_markers if marker in normalized_label) >= 2


def _is_probable_narrative_label(normalized_label: str) -> bool:
    if len(normalized_label) >= 18 and any(term in normalized_label for term in ("所致", "原因", "影响", "主要系")):
        return True
    if len(normalized_label) < 35:
        return False
    if any(mark in normalized_label for mark in ("。", "，", "；", ";")):
        return True
    narrative_terms = ("主要系", "导致", "同比增长", "同比下降", "较上年", "波动", "降低", "提升", "增加", "所致", "上年同期")
    return sum(1 for term in narrative_terms if term in normalized_label) >= 2


def _is_probable_merged_metric_label(normalized_label: str) -> bool:
    metric_markers = (
        "营业收入",
        "归属于上市公司股东的净利润",
        "扣除非经常性损益",
        "经营活动",
        "经营活动产生的现金流量净额",
        "基本每股收益",
        "稀释每股收益",
        "加权平均净资产收益率",
        "总资产",
        "归属于上市公司股东的所有者权益",
    )
    return sum(1 for marker in metric_markers if marker in normalized_label) >= 2


def _split_inline_numeric_texts(cell: str) -> tuple[str, list[str]]:
    cell = re.sub(r"^([＋+－-])\s+(?=\d)", r"\1", cell.strip())
    numeric_pattern = r"[-＋+－]?\(?\d[\d,，]*(?:\.\d+)?\)?(?:%|亿元|万元|元|百分点)?"
    numeric_texts = [match.group(0) for match in re.finditer(numeric_pattern, cell)]
    if not numeric_texts:
        return cell, []
    label = re.sub(numeric_pattern, " ", cell)
    label = " ".join(label.split()).strip()
    return label, numeric_texts[:5]


def _clean_numeric_texts(numeric_texts: list[str]) -> list[str]:
    cleaned = _merge_standalone_signs(numeric_texts)
    while len(cleaned) >= 2 and _looks_like_reference_or_year(cleaned[0], cleaned[1:]):
        cleaned = cleaned[1:]
    return cleaned


def _merge_standalone_signs(numeric_texts: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(numeric_texts):
        token = str(numeric_texts[index]).strip()
        if token in {"-", "－", "+", "＋"} and index + 1 < len(numeric_texts):
            next_token = str(numeric_texts[index + 1]).strip()
            if parse_numeric(next_token, None) is not None:
                sign = "-" if token in {"-", "－"} else "+"
                merged.append(sign + next_token)
                index += 2
                continue
        merged.append(str(numeric_texts[index]))
        index += 1
    return merged


def _looks_like_reference_or_year(token: str, later_tokens: list[str]) -> bool:
    raw = str(token).strip()
    if not raw:
        return False
    if re.fullmatch(r"\d{4}", raw):
        year = int(raw)
        if 2000 <= year <= 2100:
            return True
    if "%" in raw or any(unit in raw for unit in ("亿", "万", "元", "百分点")):
        return False
    if "." in raw:
        return False
    parsed = parse_numeric(raw, None)
    if parsed is None:
        return False
    if not float(parsed).is_integer():
        return False
    if not (0 <= parsed <= 500):
        return False
    for later in later_tokens:
        if "%" in later or any(unit in later for unit in ("亿", "万", "元", "百分点")):
            return True
        later_value = parse_numeric(later, None)
        if later_value is None:
            continue
        if abs(later_value) >= 1000 or "." in str(later):
            return True
    return False
