from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .models import StandardizedRecord, ValidationIssue

PERCENTAGE_ALERT_THRESHOLD = 1000.0
AMOUNT_ALERT_THRESHOLD_10K_YUAN = 100_000_000.0


def build_quality_review_frames(
    records: list[StandardizedRecord],
    validation_issues: list[ValidationIssue],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    anomaly_rows: list[dict[str, object]] = []
    field_counter: Counter[tuple[str, str, str]] = Counter()

    for record in records:
        record_key = _record_key(record.values)
        for field_name, value in record.values.items():
            if field_name in {"serial_number", "stock_code", "stock_abbr", "report_period", "report_year"}:
                continue
            numeric_value = _safe_float(value)
            if numeric_value is None:
                continue

            anomaly_type: str | None = None
            if _looks_like_percentage_field(field_name) and abs(numeric_value) > PERCENTAGE_ALERT_THRESHOLD:
                anomaly_type = "percentage_outlier"
            elif not _looks_like_percentage_field(field_name) and abs(numeric_value) > AMOUNT_ALERT_THRESHOLD_10K_YUAN:
                anomaly_type = "amount_outlier"
            if anomaly_type is None:
                continue

            anomaly_rows.append(
                {
                    "table_name": record.table_name,
                    "record_key": record_key,
                    "source_name": record.source_name,
                    "field_name": field_name,
                    "value": numeric_value,
                    "anomaly_type": anomaly_type,
                }
            )
            field_counter[(record.table_name, field_name, anomaly_type)] += 1

    anomaly_df = pd.DataFrame(anomaly_rows)
    field_summary_rows = [
        {
            "table_name": table_name,
            "field_name": field_name,
            "anomaly_type": anomaly_type,
            "count": count,
        }
        for (table_name, field_name, anomaly_type), count in field_counter.most_common()
    ]
    field_summary_df = pd.DataFrame(field_summary_rows)

    if not validation_issues:
        return anomaly_df, field_summary_df

    validation_counter = Counter((issue.table_name, issue.rule_name, issue.severity) for issue in validation_issues)
    validation_rows = [
        {
            "table_name": table_name,
            "field_name": rule_name,
            "anomaly_type": f"validation_{severity}",
            "count": count,
        }
        for (table_name, rule_name, severity), count in validation_counter.most_common()
    ]
    if validation_rows:
        field_summary_df = pd.concat([field_summary_df, pd.DataFrame(validation_rows)], ignore_index=True)
    return anomaly_df, field_summary_df


def write_quality_review_report(
    summary: dict[str, object],
    anomaly_df: pd.DataFrame,
    field_summary_df: pd.DataFrame,
    output_path: Path,
) -> None:
    lines: list[str] = [
        "# 任务一数据库质量复核",
        "",
        "## 1. 总体情况",
        "",
        f"- 主记录总数：`{summary.get('total_records', 0)}`",
    ]
    for table_name, count in sorted((summary.get("table_record_counts", {}) or {}).items()):
        lines.append(f"- `{table_name}` 记录数：`{count}`")

    validation_issue_counts = summary.get("validation_issue_counts", {}) or {}
    lines.extend(
        [
            "",
            "## 2. 入库前校验结果",
            "",
            f"- 校验问题总数：`{sum(int(v) for v in validation_issue_counts.values())}`",
        ]
    )
    for rule_name, count in sorted(validation_issue_counts.items()):
        lines.append(f"- `{rule_name}`：`{count}`")

    lines.extend(
        [
            "",
            "## 3. 数值异常复核",
            "",
            f"- 数值异常条目数：`{len(anomaly_df)}`",
        ]
    )
    if not field_summary_df.empty:
        lines.append("- 高频异常字段：")
        for _, row in field_summary_df.head(12).iterrows():
            lines.append(
                f"  - `{row['table_name']}.{row['field_name']}` / `{row['anomaly_type']}`：`{int(row['count'])}`"
            )

    if not anomaly_df.empty:
        lines.extend(["", "## 4. 重点异常样例", ""])
        for _, row in anomaly_df.head(10).iterrows():
            lines.append(
                f"- `{row['table_name']}` `{row['record_key']}` `{row['field_name']}` = `{row['value']}`（{row['anomaly_type']}）"
            )

    lines.extend(
        [
            "",
            "## 5. 复核结论",
            "",
            "- 当前结果已在入库前增加异常值清洗、跨表一致性校验与旧口径字段回填。",
            "- 仍需重点关注底层抽取带来的极端金额和比例异常，并优先复核会在任务二问答中直接影响排序、筛选和均值统计的字段。",
        ]
    )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_key(values: dict[str, object]) -> str:
    return "|".join(
        [
            str(values.get("stock_code", "")),
            str(values.get("report_period", "")),
            str(values.get("report_year", "")),
        ]
    )


def _safe_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if pd.isna(numeric):
        return None
    return numeric


def _looks_like_percentage_field(field_name: str) -> bool:
    if field_name.endswith("_ratio_of_net_cf"):
        return True
    return any(marker in field_name for marker in ("yoy", "qoq", "ratio", "margin", "roe"))
