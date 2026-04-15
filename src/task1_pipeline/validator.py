from __future__ import annotations

import math

import pandas as pd

from .mappings import TABLE_REQUIRED_COLUMNS
from .models import StandardizedRecord, ValidationIssue

PERCENTAGE_ALERT_THRESHOLD = 1000.0


class DataValidator:
    def validate_records(self, records: list[StandardizedRecord]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        grouped: dict[str, list[StandardizedRecord]] = {}
        for record in records:
            grouped.setdefault(record.table_name, []).append(record)

        for table_name, table_records in grouped.items():
            issues.extend(self._check_required_fields(table_name, table_records))
            issues.extend(self._check_duplicate_keys(table_name, table_records))
            issues.extend(self._check_common_numeric_sanity(table_name, table_records))
        issues.extend(self._check_cross_table_consistency(records))
        return issues

    def _check_required_fields(self, table_name: str, records: list[StandardizedRecord]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        required_columns = TABLE_REQUIRED_COLUMNS.get(table_name, [])
        for record in records:
            for col in required_columns:
                value = record.values.get(col)
                if value in {None, ""}:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            rule_name="required_fields",
                            table_name=table_name,
                            source_name=record.source_name,
                            record_key=self._record_key(record.values),
                            message=f"missing required field: {col}",
                        )
                    )
        return issues

    def _check_duplicate_keys(self, table_name: str, records: list[StandardizedRecord]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen: dict[str, int] = {}
        for record in records:
            key = self._record_key(record.values)
            seen[key] = seen.get(key, 0) + 1
        for key, count in seen.items():
            if count > 1:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        rule_name="duplicate_business_key",
                        table_name=table_name,
                        source_name="*",
                        record_key=key,
                        message=f"duplicate business key count={count}",
                    )
                )
        return issues

    def _check_common_numeric_sanity(self, table_name: str, records: list[StandardizedRecord]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        percentage_fields = [k for k in {"roe", "gross_profit_margin", "net_profit_margin", "asset_liability_ratio"}]
        growth_markers = ("yoy", "qoq", "ratio")
        for record in records:
            for field, value in record.values.items():
                if value is None or not isinstance(value, (int, float)) or math.isnan(value):
                    continue
                if field.endswith("_ratio_of_net_cf"):
                    continue
                if field in percentage_fields or any(marker in field for marker in growth_markers):
                    if abs(value) > PERCENTAGE_ALERT_THRESHOLD:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                rule_name="percentage_outlier",
                                table_name=table_name,
                                source_name=record.source_name,
                                record_key=self._record_key(record.values),
                                message=f"{field} has suspicious percentage value: {value}",
                            )
                        )
        return issues

    def _check_cross_table_consistency(self, records: list[StandardizedRecord]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        grouped: dict[str, dict[str, StandardizedRecord]] = {}
        for record in records:
            grouped.setdefault(self._record_key(record.values), {})[record.table_name] = record

        for record_key, tables in grouped.items():
            balance = tables.get("balance_sheet")
            cash_flow = tables.get("cash_flow_sheet")
            income = tables.get("income_sheet")
            kpi = tables.get("core_performance_indicators_sheet")

            if balance is not None:
                assets = self._safe_float(balance.values.get("asset_total_assets"))
                liabilities = self._safe_float(balance.values.get("liability_total_liabilities"))
                equity = self._safe_float(balance.values.get("equity_total_equity"))
                ratio = self._safe_float(balance.values.get("asset_liability_ratio"))
                if None not in (assets, liabilities, equity):
                    tolerance = max(100.0, abs(assets) * 0.02)
                    diff = abs(assets - liabilities - equity)
                    if diff > tolerance:
                        issues.append(self._issue("warning", "balance_equation_precheck", "balance_sheet", balance.source_name, record_key, f"assets != liabilities + equity (diff={diff:.2f})"))
                if None not in (assets, liabilities, ratio) and assets not in (None, 0):
                    derived_ratio = liabilities / assets * 100
                    if abs(derived_ratio - ratio) > 5:
                        issues.append(self._issue("warning", "asset_liability_ratio_consistency", "balance_sheet", balance.source_name, record_key, f"asset_liability_ratio mismatch: stored={ratio:.2f}, derived={derived_ratio:.2f}"))

            if cash_flow is not None:
                operating = self._safe_float(cash_flow.values.get("operating_cf_net_amount"))
                investing = self._safe_float(cash_flow.values.get("investing_cf_net_amount"))
                financing = self._safe_float(cash_flow.values.get("financing_cf_net_amount"))
                net_cash = self._safe_float(cash_flow.values.get("net_cash_flow"))
                if None not in (operating, investing, financing, net_cash):
                    derived_net = operating + investing + financing
                    tolerance = max(100.0, abs(net_cash) * 0.05)
                    if abs(derived_net - net_cash) > tolerance:
                        issues.append(self._issue("warning", "cash_flow_equation_precheck", "cash_flow_sheet", cash_flow.source_name, record_key, f"net_cash_flow mismatch: stored={net_cash:.2f}, derived={derived_net:.2f}"))

            if income is not None and kpi is not None:
                revenue = self._safe_float(income.values.get("total_operating_revenue"))
                cost = self._safe_float(income.values.get("operating_expense_cost_of_sales"))
                net_profit = self._safe_float(income.values.get("net_profit"))
                kpi_gross_margin = self._safe_float(kpi.values.get("gross_profit_margin"))
                kpi_net_margin = self._safe_float(kpi.values.get("net_profit_margin"))
                kpi_roe = self._safe_float(kpi.values.get("roe"))
                equity = self._safe_float(balance.values.get("equity_total_equity")) if balance is not None else None

                if revenue not in (None, 0) and cost is not None and kpi_gross_margin is not None:
                    derived = (revenue - cost) / revenue * 100
                    if abs(derived - kpi_gross_margin) > 5:
                        issues.append(self._issue("warning", "gross_profit_margin_consistency_precheck", "core_performance_indicators_sheet", kpi.source_name, record_key, f"gross_profit_margin mismatch: stored={kpi_gross_margin:.2f}, derived={derived:.2f}"))
                if revenue not in (None, 0) and net_profit is not None and kpi_net_margin is not None:
                    derived = net_profit / revenue * 100
                    if abs(derived - kpi_net_margin) > 5:
                        issues.append(self._issue("warning", "net_profit_margin_consistency_precheck", "core_performance_indicators_sheet", kpi.source_name, record_key, f"net_profit_margin mismatch: stored={kpi_net_margin:.2f}, derived={derived:.2f}"))
                if equity not in (None, 0) and net_profit is not None and kpi_roe is not None:
                    derived = net_profit / equity * 100
                    if abs(derived - kpi_roe) > 5:
                        issues.append(self._issue("warning", "roe_consistency_precheck", "core_performance_indicators_sheet", kpi.source_name, record_key, f"roe mismatch: stored={kpi_roe:.2f}, derived={derived:.2f}"))
        return issues

    def issues_to_dataframe(self, issues: list[ValidationIssue]) -> pd.DataFrame:
        return pd.DataFrame([issue.__dict__ for issue in issues])

    def _record_key(self, values: dict[str, object]) -> str:
        return "|".join(
            [
                str(values.get("stock_code", "")),
                str(values.get("report_period", "")),
                str(values.get("report_year", "")),
            ]
        )

    def _issue(
        self,
        severity: str,
        rule_name: str,
        table_name: str,
        source_name: str,
        record_key: str,
        message: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=severity,
            rule_name=rule_name,
            table_name=table_name,
            source_name=source_name,
            record_key=record_key,
            message=message,
        )

    def _safe_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        if math.isnan(numeric):
            return None
        return numeric
