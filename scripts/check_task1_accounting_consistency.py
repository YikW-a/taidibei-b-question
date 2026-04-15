from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


KEY_COLUMNS = ["stock_code", "report_period", "report_year"]


@dataclass
class RuleEvaluation:
    rule_name: str
    table_scope: str
    applicable_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    pass_rate: float
    failure_rate: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Task 1: 会计勾稽校验与指标统计")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="数据库连接串。默认读取 outputs/task1/task1_financials.db",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/task1/accounting_checks"),
        help="勾稽校验输出目录",
    )
    return parser.parse_args()


def load_table(engine, table_name: str) -> pd.DataFrame:
    return pd.read_sql_table(table_name, engine)


def safe_merge(left: pd.DataFrame, right: pd.DataFrame, suffixes: tuple[str, str]) -> pd.DataFrame:
    return left.merge(right, on=KEY_COLUMNS, how="inner", suffixes=suffixes)


def evaluate_numeric_rule(
    dataframe: pd.DataFrame,
    rule_name: str,
    table_scope: str,
    left_col: str,
    right_col: str,
    *,
    abs_tol: float,
    rel_tol: float,
) -> tuple[RuleEvaluation, pd.DataFrame]:
    frame = dataframe.copy()
    frame["applicable"] = frame[left_col].notna() & frame[right_col].notna()
    applicable = frame[frame["applicable"]].copy()
    skipped_count = int((~frame["applicable"]).sum())
    if applicable.empty:
        summary = RuleEvaluation(
            rule_name=rule_name,
            table_scope=table_scope,
            applicable_count=0,
            passed_count=0,
            failed_count=0,
            skipped_count=skipped_count,
            pass_rate=0.0,
            failure_rate=0.0,
        )
        return summary, applicable

    diff = (applicable[left_col] - applicable[right_col]).abs()
    base = applicable[right_col].abs().clip(lower=1.0)
    passed_mask = (diff <= abs_tol) | ((diff / base) <= rel_tol)
    applicable["difference"] = diff
    applicable["expected_value"] = applicable[right_col]
    applicable["actual_value"] = applicable[left_col]
    applicable["status"] = passed_mask.map({True: "pass", False: "fail"})
    applicable["rule_name"] = rule_name
    applicable["table_scope"] = table_scope

    applicable_count = len(applicable)
    passed_count = int(passed_mask.sum())
    failed_count = applicable_count - passed_count
    summary = RuleEvaluation(
        rule_name=rule_name,
        table_scope=table_scope,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        pass_rate=round(passed_count / applicable_count, 4),
        failure_rate=round(failed_count / applicable_count, 4),
    )
    return summary, applicable


def evaluate_formula_rule(
    dataframe: pd.DataFrame,
    rule_name: str,
    table_scope: str,
    required_cols: list[str],
    formula,
    *,
    abs_tol: float,
    rel_tol: float,
) -> tuple[RuleEvaluation, pd.DataFrame]:
    frame = dataframe.copy()
    frame["applicable"] = frame[required_cols].notna().all(axis=1)
    applicable = frame[frame["applicable"]].copy()
    skipped_count = int((~frame["applicable"]).sum())
    if applicable.empty:
        summary = RuleEvaluation(
            rule_name=rule_name,
            table_scope=table_scope,
            applicable_count=0,
            passed_count=0,
            failed_count=0,
            skipped_count=skipped_count,
            pass_rate=0.0,
            failure_rate=0.0,
        )
        return summary, applicable

    applicable["expected_value"] = formula(applicable)
    diff = (applicable["actual_value"] - applicable["expected_value"]).abs()
    base = applicable["expected_value"].abs().clip(lower=1.0)
    passed_mask = (diff <= abs_tol) | ((diff / base) <= rel_tol)
    applicable["difference"] = diff
    applicable["status"] = passed_mask.map({True: "pass", False: "fail"})
    applicable["rule_name"] = rule_name
    applicable["table_scope"] = table_scope

    applicable_count = len(applicable)
    passed_count = int(passed_mask.sum())
    failed_count = applicable_count - passed_count
    summary = RuleEvaluation(
        rule_name=rule_name,
        table_scope=table_scope,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        pass_rate=round(passed_count / applicable_count, 4),
        failure_rate=round(failed_count / applicable_count, 4),
    )
    return summary, applicable


def build_rule_evaluations(engine) -> tuple[list[RuleEvaluation], pd.DataFrame]:
    balance_df = load_table(engine, "balance_sheet")
    cash_df = load_table(engine, "cash_flow_sheet")
    income_df = load_table(engine, "income_sheet")
    kpi_df = load_table(engine, "core_performance_indicators_sheet")

    details: list[pd.DataFrame] = []
    summaries: list[RuleEvaluation] = []

    balance_work = balance_df[KEY_COLUMNS + [
        "stock_abbr",
        "asset_total_assets",
        "liability_total_liabilities",
        "equity_total_equity",
        "asset_liability_ratio",
    ]].copy()
    balance_work["actual_value"] = balance_work["asset_total_assets"]
    summary, detail = evaluate_formula_rule(
        balance_work,
        "balance_equation",
        "balance_sheet",
        ["asset_total_assets", "liability_total_liabilities", "equity_total_equity"],
        lambda df: df["liability_total_liabilities"] + df["equity_total_equity"],
        abs_tol=1.0,
        rel_tol=0.02,
    )
    summaries.append(summary)
    details.append(detail)

    balance_ratio = balance_work.copy()
    balance_ratio["actual_value"] = balance_ratio["asset_liability_ratio"]
    summary, detail = evaluate_formula_rule(
        balance_ratio,
        "asset_liability_ratio_consistency",
        "balance_sheet",
        ["asset_total_assets", "liability_total_liabilities", "asset_liability_ratio"],
        lambda df: df["liability_total_liabilities"] / df["asset_total_assets"] * 100,
        abs_tol=1.0,
        rel_tol=0.02,
    )
    summaries.append(summary)
    details.append(detail)

    cash_work = cash_df[KEY_COLUMNS + [
        "stock_abbr",
        "net_cash_flow",
        "operating_cf_net_amount",
        "investing_cf_net_amount",
        "financing_cf_net_amount",
        "operating_cf_ratio_of_net_cf",
        "investing_cf_ratio_of_net_cf",
        "financing_cf_ratio_of_net_cf",
    ]].copy()
    cash_work["actual_value"] = cash_work["net_cash_flow"]
    summary, detail = evaluate_formula_rule(
        cash_work,
        "cash_flow_equation",
        "cash_flow_sheet",
        ["net_cash_flow", "operating_cf_net_amount", "investing_cf_net_amount", "financing_cf_net_amount"],
        lambda df: df["operating_cf_net_amount"] + df["investing_cf_net_amount"] + df["financing_cf_net_amount"],
        abs_tol=1.0,
        rel_tol=0.03,
    )
    summaries.append(summary)
    details.append(detail)

    for amount_col, ratio_col, rule_name in [
        ("operating_cf_net_amount", "operating_cf_ratio_of_net_cf", "operating_cf_ratio_consistency"),
        ("investing_cf_net_amount", "investing_cf_ratio_of_net_cf", "investing_cf_ratio_consistency"),
        ("financing_cf_net_amount", "financing_cf_ratio_of_net_cf", "financing_cf_ratio_consistency"),
    ]:
        ratio_work = cash_work.copy()
        ratio_work["actual_value"] = ratio_work[ratio_col]
        ratio_work["net_cash_nonzero"] = ratio_work["net_cash_flow"].notna() & (ratio_work["net_cash_flow"] != 0)
        ratio_work = ratio_work[ratio_work["net_cash_nonzero"]].copy()
        summary, detail = evaluate_formula_rule(
            ratio_work,
            rule_name,
            "cash_flow_sheet",
            [ratio_col, amount_col, "net_cash_flow"],
            lambda df, amount_col=amount_col: df[amount_col] / df["net_cash_flow"] * 100,
            abs_tol=2.0,
            rel_tol=0.05,
        )
        summaries.append(summary)
        details.append(detail)

    income_keep = KEY_COLUMNS + [
        "stock_abbr",
        "total_operating_revenue",
        "operating_expense_cost_of_sales",
        "net_profit",
    ]
    kpi_keep = KEY_COLUMNS + [
        "stock_abbr",
        "gross_profit_margin",
        "net_profit_margin",
        "roe",
        "net_asset_per_share",
        "operating_cf_per_share",
        "eps",
    ]
    income_kpi = safe_merge(kpi_df[kpi_keep], income_df[income_keep], suffixes=("_kpi", "_income"))
    income_kpi["stock_abbr"] = income_kpi["stock_abbr_kpi"].fillna(income_kpi["stock_abbr_income"])

    income_kpi["actual_value"] = income_kpi["gross_profit_margin"]
    summary, detail = evaluate_formula_rule(
        income_kpi,
        "gross_profit_margin_consistency",
        "core_performance_indicators_sheet+income_sheet",
        ["gross_profit_margin", "total_operating_revenue", "operating_expense_cost_of_sales"],
        lambda df: (df["total_operating_revenue"] - df["operating_expense_cost_of_sales"]) / df["total_operating_revenue"] * 100,
        abs_tol=3.0,
        rel_tol=0.08,
    )
    summaries.append(summary)
    details.append(detail)

    income_kpi["actual_value"] = income_kpi["net_profit_margin"]
    summary, detail = evaluate_formula_rule(
        income_kpi,
        "net_profit_margin_consistency",
        "core_performance_indicators_sheet+income_sheet",
        ["net_profit_margin", "total_operating_revenue", "net_profit"],
        lambda df: df["net_profit"] / df["total_operating_revenue"] * 100,
        abs_tol=3.0,
        rel_tol=0.08,
    )
    summaries.append(summary)
    details.append(detail)

    kpi_balance_income = income_kpi.merge(
        balance_df[KEY_COLUMNS + ["equity_total_equity"]],
        on=KEY_COLUMNS,
        how="inner",
    )
    kpi_balance_income["actual_value"] = kpi_balance_income["roe"]
    summary, detail = evaluate_formula_rule(
        kpi_balance_income,
        "roe_consistency",
        "core_performance_indicators_sheet+income_sheet+balance_sheet",
        ["roe", "net_profit", "equity_total_equity"],
        lambda df: df["net_profit"] / df["equity_total_equity"] * 100,
        abs_tol=3.0,
        rel_tol=0.08,
    )
    summaries.append(summary)
    details.append(detail)

    kpi_cross = kpi_balance_income.merge(
        cash_df[KEY_COLUMNS + ["operating_cf_net_amount"]],
        on=KEY_COLUMNS,
        how="inner",
    )
    kpi_cross["share_count"] = (kpi_cross["net_profit"] * 10000) / kpi_cross["eps"]

    net_asset_work = kpi_cross.copy()
    net_asset_work["actual_value"] = net_asset_work["net_asset_per_share"]
    summary, detail = evaluate_formula_rule(
        net_asset_work,
        "net_asset_per_share_consistency",
        "core_performance_indicators_sheet+balance_sheet+income_sheet",
        ["net_asset_per_share", "equity_total_equity", "share_count"],
        lambda df: (df["equity_total_equity"] * 10000) / df["share_count"],
        abs_tol=0.2,
        rel_tol=0.08,
    )
    summaries.append(summary)
    details.append(detail)

    operating_cf_per_share_work = kpi_cross.copy()
    operating_cf_per_share_work["actual_value"] = operating_cf_per_share_work["operating_cf_per_share"]
    summary, detail = evaluate_formula_rule(
        operating_cf_per_share_work,
        "operating_cf_per_share_consistency",
        "core_performance_indicators_sheet+cash_flow_sheet+income_sheet",
        ["operating_cf_per_share", "operating_cf_net_amount", "share_count"],
        lambda df: (df["operating_cf_net_amount"] * 10000) / df["share_count"],
        abs_tol=0.2,
        rel_tol=0.08,
    )
    summaries.append(summary)
    details.append(detail)

    detail_df = pd.concat(details, ignore_index=True, sort=False)
    if "stock_abbr" not in detail_df.columns:
        detail_df["stock_abbr"] = None
    detail_df["stock_abbr"] = detail_df["stock_abbr"].fillna(detail_df.get("stock_abbr_kpi")).fillna(detail_df.get("stock_abbr_income"))
    keep_cols = [
        "rule_name",
        "table_scope",
        "stock_code",
        "stock_abbr",
        "report_period",
        "report_year",
        "actual_value",
        "expected_value",
        "difference",
        "status",
    ]
    detail_df = detail_df[keep_cols]
    return summaries, detail_df


def write_outputs(output_dir: Path, summaries: list[RuleEvaluation], detail_df: pd.DataFrame) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame([asdict(item) for item in summaries]).sort_values(["failure_rate", "rule_name"], ascending=[False, True])
    failed_df = detail_df[detail_df["status"] == "fail"].copy().sort_values(["rule_name", "difference"], ascending=[True, False])
    passed_total = int(summary_df["passed_count"].sum())
    failed_total = int(summary_df["failed_count"].sum())
    applicable_total = int(summary_df["applicable_count"].sum())
    skipped_total = int(summary_df["skipped_count"].sum())
    overall = {
        "rule_count": int(len(summary_df)),
        "applicable_total": applicable_total,
        "passed_total": passed_total,
        "failed_total": failed_total,
        "skipped_total": skipped_total,
        "overall_pass_rate": round(passed_total / applicable_total, 4) if applicable_total else 0.0,
        "overall_failure_rate": round(failed_total / applicable_total, 4) if applicable_total else 0.0,
        "worst_rules": summary_df.head(5)[["rule_name", "failure_rate", "failed_count"]].to_dict(orient="records"),
    }

    summary_path = output_dir / "accounting_check_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump({"overall": overall, "rules": [asdict(item) for item in summaries]}, f, ensure_ascii=False, indent=2)

    summary_df.to_csv(output_dir / "accounting_check_rule_summary.csv", index=False, encoding="utf-8-sig")
    detail_df.to_csv(output_dir / "accounting_check_detail.csv", index=False, encoding="utf-8-sig")
    failed_df.to_csv(output_dir / "accounting_check_failed_cases.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# 会计勾稽校验报告",
        "",
        "## 总体结果",
        f"- 校验规则数：{overall['rule_count']}",
        f"- 可判定样本数：{overall['applicable_total']}",
        f"- 通过数：{overall['passed_total']}",
        f"- 失败数：{overall['failed_total']}",
        f"- 跳过数：{overall['skipped_total']}",
        f"- 总体通过率：{overall['overall_pass_rate']:.2%}",
        f"- 总体失败率：{overall['overall_failure_rate']:.2%}",
        "",
        "## 分规则结果",
        "",
        "| 规则 | 作用范围 | 可判定 | 通过 | 失败 | 跳过 | 通过率 | 失败率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_df.itertuples(index=False):
        lines.append(
            f"| {row.rule_name} | {row.table_scope} | {row.applicable_count} | {row.passed_count} | {row.failed_count} | {row.skipped_count} | {row.pass_rate:.2%} | {row.failure_rate:.2%} |"
        )

    if not failed_df.empty:
        lines.extend(
            [
                "",
                "## 失败样例（前 20 条）",
                "",
                "| 规则 | 股票代码 | 股票简称 | 报告期 | 报告年份 | 实际值 | 期望值 | 差值 |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in failed_df.head(20).itertuples(index=False):
            lines.append(
                f"| {row.rule_name} | {row.stock_code} | {row.stock_abbr or ''} | {row.report_period} | {row.report_year} | {row.actual_value:.6f} | {row.expected_value:.6f} | {row.difference:.6f} |"
            )

    (output_dir / "accounting_check_report.md").write_text("\n".join(lines), encoding="utf-8")
    return overall


def main() -> None:
    args = parse_args()
    database_url = args.database_url or f"sqlite:///{(Path.cwd() / 'outputs/task1/task1_financials.db').as_posix()}"
    engine = create_engine(database_url)
    summaries, detail_df = build_rule_evaluations(engine)
    overall = write_outputs(args.output_dir, summaries, detail_df)
    print(json.dumps(overall, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
