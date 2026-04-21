from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


KEY_COLUMNS = ["stock_code", "report_period", "report_year"]
PERIOD_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}


@dataclass
class RuleEvaluation:
    rule_name: str
    description: str
    formula: str
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


def safe_float(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if pd.isna(numeric):
        return None
    return numeric


def period_suffix(report_period: str | None) -> str:
    text = str(report_period or "")
    for suffix in PERIOD_ORDER:
        if text.endswith(suffix):
            return suffix
    return text


def is_fy_period(report_period: str | None) -> bool:
    return period_suffix(report_period) == "FY"


def infer_share_count(net_profit_10k_yuan: float | None, eps: float | None) -> float | None:
    if net_profit_10k_yuan in (None, 0) or eps in (None, 0):
        return None
    shares = (net_profit_10k_yuan * 10000) / eps
    if shares <= 0 or shares < 1_000_000 or shares > 1_000_000_000_000:
        return None
    return shares


def same_sign_or_zero(left: float, right: float) -> bool:
    if left == 0 or right == 0:
        return True
    return left * right > 0


def material_per_share_mismatch(stored: float, derived: float) -> bool:
    if not same_sign_or_zero(stored, derived):
        return True
    tolerance = max(2.0, abs(stored) * 0.8, abs(derived) * 0.8)
    return abs(stored - derived) > tolerance


def margin_candidate_score(revenue: float, cost: float | None, net_profit: float | None) -> float:
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


def select_margin_revenue(
    income_revenue: float | None,
    kpi_revenue: float | None,
    cost: float | None,
    net_profit: float | None,
) -> float | None:
    candidates: list[tuple[float, float]] = []
    for revenue in (income_revenue, kpi_revenue):
        if revenue in (None, 0) or revenue <= 0:
            continue
        candidates.append((margin_candidate_score(revenue, cost, net_profit), revenue))
    if not candidates:
        return income_revenue or kpi_revenue
    candidates.sort(key=lambda item: (item[0], -abs(item[1])))
    return candidates[0][1]


def build_precomputed_rule_summary(
    detail_df: pd.DataFrame,
    rule_name: str,
    description: str,
    formula: str,
    table_scope: str,
    *,
    abs_tol: float,
    rel_tol: float,
) -> tuple[RuleEvaluation, pd.DataFrame]:
    frame = detail_df.copy()
    if not frame.empty:
        frame = frame.dropna(subset=["actual_value", "expected_value"]).copy()
    if frame.empty:
        summary = RuleEvaluation(
            rule_name=rule_name,
            description=description,
            formula=formula,
            table_scope=table_scope,
            applicable_count=0,
            passed_count=0,
            failed_count=0,
            skipped_count=0,
            pass_rate=0.0,
            failure_rate=0.0,
        )
        return summary, frame

    diff = (frame["actual_value"] - frame["expected_value"]).abs()
    base = frame["expected_value"].abs().clip(lower=1.0)
    passed_mask = (diff <= abs_tol) | ((diff / base) <= rel_tol)
    frame["difference"] = diff
    frame["status"] = passed_mask.map({True: "pass", False: "fail"})
    frame["rule_name"] = rule_name
    frame["description"] = description
    frame["formula"] = formula
    frame["table_scope"] = table_scope

    applicable_count = len(frame)
    passed_count = int(passed_mask.sum())
    failed_count = applicable_count - passed_count
    summary = RuleEvaluation(
        rule_name=rule_name,
        description=description,
        formula=formula,
        table_scope=table_scope,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=0,
        pass_rate=round(passed_count / applicable_count, 4),
        failure_rate=round(failed_count / applicable_count, 4),
    )
    return summary, frame


def build_upper_bound_rule_summary(
    detail_df: pd.DataFrame,
    rule_name: str,
    description: str,
    formula: str,
    table_scope: str,
    *,
    tolerance: float,
) -> tuple[RuleEvaluation, pd.DataFrame]:
    frame = detail_df.copy()
    if not frame.empty:
        frame = frame.dropna(subset=["actual_value", "expected_value"]).copy()
    if frame.empty:
        summary = RuleEvaluation(
            rule_name=rule_name,
            description=description,
            formula=formula,
            table_scope=table_scope,
            applicable_count=0,
            passed_count=0,
            failed_count=0,
            skipped_count=0,
            pass_rate=0.0,
            failure_rate=0.0,
        )
        return summary, frame

    upper = frame["expected_value"] + tolerance
    passed_mask = frame["actual_value"] <= upper
    frame["difference"] = (frame["actual_value"] - frame["expected_value"]).abs()
    frame["status"] = passed_mask.map({True: "pass", False: "fail"})
    frame["rule_name"] = rule_name
    frame["description"] = description
    frame["formula"] = formula
    frame["table_scope"] = table_scope

    applicable_count = len(frame)
    passed_count = int(passed_mask.sum())
    failed_count = applicable_count - passed_count
    summary = RuleEvaluation(
        rule_name=rule_name,
        description=description,
        formula=formula,
        table_scope=table_scope,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=0,
        pass_rate=round(passed_count / applicable_count, 4),
        failure_rate=round(failed_count / applicable_count, 4),
    )
    return summary, frame


def build_boolean_rule_summary(
    detail_df: pd.DataFrame,
    rule_name: str,
    description: str,
    formula: str,
    table_scope: str,
    pass_mask,
) -> tuple[RuleEvaluation, pd.DataFrame]:
    frame = detail_df.copy()
    if frame.empty:
        summary = RuleEvaluation(
            rule_name=rule_name,
            description=description,
            formula=formula,
            table_scope=table_scope,
            applicable_count=0,
            passed_count=0,
            failed_count=0,
            skipped_count=0,
            pass_rate=0.0,
            failure_rate=0.0,
        )
        return summary, frame

    if callable(pass_mask):
        mask = pass_mask(frame)
    else:
        mask = pass_mask
    frame["difference"] = pd.NA
    frame["status"] = mask.map({True: "pass", False: "fail"})
    frame["rule_name"] = rule_name
    frame["description"] = description
    frame["formula"] = formula
    frame["table_scope"] = table_scope

    applicable_count = len(frame)
    passed_count = int(mask.sum())
    failed_count = applicable_count - passed_count
    summary = RuleEvaluation(
        rule_name=rule_name,
        description=description,
        formula=formula,
        table_scope=table_scope,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=0,
        pass_rate=round(passed_count / applicable_count, 4),
        failure_rate=round(failed_count / applicable_count, 4),
    )
    return summary, frame


def build_rule_evaluations(engine) -> tuple[list[RuleEvaluation], pd.DataFrame]:
    balance_df = load_table(engine, "balance_sheet")
    cash_df = load_table(engine, "cash_flow_sheet")
    income_df = load_table(engine, "income_sheet")
    kpi_df = load_table(engine, "core_performance_indicators_sheet")

    details: list[pd.DataFrame] = []
    summaries: list[RuleEvaluation] = []

    def add_rule(frame: pd.DataFrame, *, rule_name: str, description: str, formula: str, table_scope: str, abs_tol: float, rel_tol: float) -> None:
        summary, detail = build_precomputed_rule_summary(
            frame,
            rule_name,
            description,
            formula,
            table_scope,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )
        summaries.append(summary)
        details.append(detail)

    def add_upper_rule(frame: pd.DataFrame, *, rule_name: str, description: str, formula: str, table_scope: str, tolerance: float) -> None:
        summary, detail = build_upper_bound_rule_summary(
            frame,
            rule_name,
            description,
            formula,
            table_scope,
            tolerance=tolerance,
        )
        summaries.append(summary)
        details.append(detail)

    def add_boolean_rule(frame: pd.DataFrame, *, rule_name: str, description: str, formula: str, table_scope: str, pass_mask) -> None:
        summary, detail = build_boolean_rule_summary(
            frame,
            rule_name,
            description,
            formula,
            table_scope,
            pass_mask,
        )
        summaries.append(summary)
        details.append(detail)

    balance_work = balance_df[KEY_COLUMNS + [
        "stock_abbr",
        "asset_total_assets",
        "liability_total_liabilities",
        "equity_total_equity",
        "asset_liability_ratio",
    ]].copy()
    applicable = balance_work.dropna(subset=["asset_total_assets", "liability_total_liabilities", "equity_total_equity"]).copy()
    applicable["actual_value"] = applicable["asset_total_assets"]
    applicable["expected_value"] = applicable["liability_total_liabilities"] + applicable["equity_total_equity"]
    add_rule(
        applicable,
        rule_name="balance_equation",
        description="校验资产总计是否与负债合计和所有者权益合计闭合。",
        formula=r"A=L+E",
        table_scope="balance_sheet",
        abs_tol=1.0,
        rel_tol=0.02,
    )

    applicable = balance_work.dropna(subset=["asset_total_assets", "liability_total_liabilities", "asset_liability_ratio"]).copy()
    applicable = applicable[applicable["asset_total_assets"] != 0].copy()
    applicable["actual_value"] = applicable["asset_liability_ratio"]
    applicable["expected_value"] = applicable["liability_total_liabilities"] / applicable["asset_total_assets"] * 100
    add_rule(
        applicable,
        rule_name="asset_liability_ratio_consistency",
        description="校验资产负债率字段与资产负债表金额之间的一致性。",
        formula=r"\rho_{AL}=\frac{L}{A}\times 100\%",
        table_scope="balance_sheet",
        abs_tol=1.0,
        rel_tol=0.02,
    )

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
    applicable = cash_work.dropna(subset=["net_cash_flow", "operating_cf_net_amount", "investing_cf_net_amount", "financing_cf_net_amount"]).copy()
    applicable["actual_value"] = applicable["net_cash_flow"]
    applicable["expected_value"] = applicable["operating_cf_net_amount"] + applicable["investing_cf_net_amount"] + applicable["financing_cf_net_amount"]
    add_rule(
        applicable,
        rule_name="cash_flow_equation",
        description="校验现金及现金等价物净增加额与三类活动净现金流的勾稽关系。",
        formula=r"NCF=OCF+ICF+FCF",
        table_scope="cash_flow_sheet",
        abs_tol=1.0,
        rel_tol=0.03,
    )

    for amount_col, ratio_col, rule_name in [
        ("operating_cf_net_amount", "operating_cf_ratio_of_net_cf", "operating_cf_ratio_consistency"),
        ("investing_cf_net_amount", "investing_cf_ratio_of_net_cf", "investing_cf_ratio_consistency"),
        ("financing_cf_net_amount", "financing_cf_ratio_of_net_cf", "financing_cf_ratio_consistency"),
    ]:
        applicable = cash_work.dropna(subset=["net_cash_flow", amount_col, ratio_col]).copy()
        applicable = applicable[applicable["net_cash_flow"] != 0].copy()
        applicable["actual_value"] = applicable[ratio_col]
        applicable["expected_value"] = applicable[amount_col] / applicable["net_cash_flow"] * 100
        add_rule(
            applicable,
            rule_name=rule_name,
            description=f"校验 `{ratio_col}` 与净现金流占比公式的一致性。",
            formula=rf"Ratio=\frac{{{amount_col}}}{{NCF}}\times 100\%",
            table_scope="cash_flow_sheet",
            abs_tol=2.0,
            rel_tol=0.05,
        )

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
        "total_operating_revenue",
        "net_profit_excl_non_recurring",
        "net_profit_excl_non_recurring_yoy",
        "operating_revenue_qoq_growth",
        "net_profit_qoq_growth",
    ]
    income_kpi = safe_merge(kpi_df[kpi_keep], income_df[income_keep], suffixes=("_kpi", "_income"))
    income_kpi["stock_abbr"] = income_kpi["stock_abbr_kpi"].fillna(income_kpi["stock_abbr_income"])
    income_kpi["selected_revenue"] = income_kpi.apply(
        lambda row: select_margin_revenue(
            safe_float(row["total_operating_revenue_income"]),
            safe_float(row["total_operating_revenue_kpi"]),
            safe_float(row["operating_expense_cost_of_sales"]),
            safe_float(row["net_profit"]),
        ),
        axis=1,
    )

    applicable = income_kpi.dropna(subset=["gross_profit_margin", "selected_revenue", "operating_expense_cost_of_sales"]).copy()
    applicable = applicable[applicable["selected_revenue"] != 0].copy()
    applicable["actual_value"] = applicable["gross_profit_margin"]
    applicable["expected_value"] = (applicable["selected_revenue"] - applicable["operating_expense_cost_of_sales"]) / applicable["selected_revenue"] * 100
    add_rule(
        applicable,
        rule_name="gross_profit_margin_consistency",
        description="以择优收入口径校验毛利率，避免因收入选取错误造成假异常。",
        formula=r"GPM=\frac{R^*-C}{R^*}\times 100\%",
        table_scope="core_performance_indicators_sheet+income_sheet",
        abs_tol=3.0,
        rel_tol=0.08,
    )

    applicable = income_kpi.dropna(subset=["net_profit_margin", "selected_revenue", "net_profit"]).copy()
    applicable = applicable[applicable["selected_revenue"] != 0].copy()
    applicable["actual_value"] = applicable["net_profit_margin"]
    applicable["expected_value"] = applicable["net_profit"] / applicable["selected_revenue"] * 100
    add_rule(
        applicable,
        rule_name="net_profit_margin_consistency",
        description="以择优收入口径校验净利率。",
        formula=r"NPM=\frac{NP}{R^*}\times 100\%",
        table_scope="core_performance_indicators_sheet+income_sheet",
        abs_tol=3.0,
        rel_tol=0.08,
    )

    margin_order = income_kpi.dropna(subset=["gross_profit_margin", "net_profit_margin"]).copy()
    margin_order["actual_value"] = margin_order["net_profit_margin"]
    margin_order["expected_value"] = margin_order["gross_profit_margin"]
    add_upper_rule(
        margin_order,
        rule_name="margin_order_consistency",
        description="净利率通常不应显著高于毛利率，用于捕捉收入口径或成本口径错配。",
        formula=r"NPM \le GPM + \delta,\ \delta=20",
        table_scope="core_performance_indicators_sheet",
        tolerance=20.0,
    )

    eps_sign = income_kpi.dropna(subset=["eps", "net_profit"]).copy()
    eps_sign = eps_sign[(eps_sign["eps"] != 0) & (eps_sign["net_profit"] != 0)].copy()
    eps_sign["actual_value"] = eps_sign["eps"]
    eps_sign["expected_value"] = eps_sign["net_profit"]
    add_boolean_rule(
        eps_sign,
        rule_name="eps_net_profit_sign_consistency",
        description="在股本为正的前提下，每股收益与净利润应保持同号。",
        formula=r"\operatorname{sign}(EPS)=\operatorname{sign}(NP)",
        table_scope="core_performance_indicators_sheet+income_sheet",
        pass_mask=lambda df: (df["eps"] * df["net_profit"]) > 0,
    )

    kpi_balance_income = income_kpi.merge(
        balance_df[KEY_COLUMNS + ["equity_total_equity"]],
        on=KEY_COLUMNS,
        how="inner",
    )
    roe_applicable = kpi_balance_income.dropna(subset=["roe", "net_profit", "equity_total_equity"]).copy()
    roe_applicable = roe_applicable[
        roe_applicable["report_period"].map(is_fy_period)
        & (roe_applicable["equity_total_equity"] > 0)
        & (roe_applicable["roe"].abs() <= 100)
    ].copy()
    roe_applicable["expected_value"] = roe_applicable["net_profit"] / roe_applicable["equity_total_equity"] * 100
    roe_applicable = roe_applicable[
        (roe_applicable["expected_value"].abs() <= 100)
        & roe_applicable.apply(lambda row: same_sign_or_zero(float(row["roe"]), float(row["expected_value"])), axis=1)
    ].copy()
    roe_applicable["actual_value"] = roe_applicable["roe"]
    add_rule(
        roe_applicable,
        rule_name="roe_consistency",
        description="在年报、正权益且符号一致条件下，以保守口径校验 ROE。",
        formula=r"ROE=\frac{NP}{E}\times 100\%",
        table_scope="core_performance_indicators_sheet+income_sheet+balance_sheet",
        abs_tol=8.0,
        rel_tol=0.8,
    )

    kpi_cross = kpi_balance_income.merge(
        cash_df[KEY_COLUMNS + ["operating_cf_net_amount"]],
        on=KEY_COLUMNS,
        how="inner",
    )
    kpi_cross["share_count"] = kpi_cross.apply(
        lambda row: infer_share_count(safe_float(row["net_profit"]), safe_float(row["eps"])),
        axis=1,
    )

    navps_rows: list[dict[str, object]] = []
    ocfps_rows: list[dict[str, object]] = []
    for row in kpi_cross.to_dict(orient="records"):
        share_count = safe_float(row.get("share_count"))
        if share_count in (None, 0):
            continue
        equity = safe_float(row.get("equity_total_equity"))
        stored_navps = safe_float(row.get("net_asset_per_share"))
        if equity is not None and stored_navps is not None:
            navps_rows.append(
                {
                    "stock_code": row["stock_code"],
                    "stock_abbr": row.get("stock_abbr"),
                    "report_period": row["report_period"],
                    "report_year": row["report_year"],
                    "actual_value": stored_navps,
                    "expected_value": (equity * 10000) / share_count,
                }
            )
        operating_cf = safe_float(row.get("operating_cf_net_amount"))
        stored_ocfps = safe_float(row.get("operating_cf_per_share"))
        if operating_cf is not None and stored_ocfps is not None:
            ocfps_rows.append(
                {
                    "stock_code": row["stock_code"],
                    "stock_abbr": row.get("stock_abbr"),
                    "report_period": row["report_period"],
                    "report_year": row["report_year"],
                    "actual_value": stored_ocfps,
                    "expected_value": (operating_cf * 10000) / share_count,
                }
            )

    add_rule(
        pd.DataFrame(navps_rows),
        rule_name="net_asset_per_share_consistency",
        description="以权益和推断股本校验每股净资产。",
        formula=r"NAVPS=\frac{E\times 10000}{Shares},\ Shares=\frac{NP\times 10000}{EPS}",
        table_scope="core_performance_indicators_sheet+balance_sheet+income_sheet",
        abs_tol=0.2,
        rel_tol=0.08,
    )
    add_rule(
        pd.DataFrame(ocfps_rows),
        rule_name="operating_cf_per_share_consistency",
        description="以经营活动现金流量净额和推断股本校验每股经营现金流。",
        formula=r"OCFPS=\frac{OCF\times 10000}{Shares}",
        table_scope="core_performance_indicators_sheet+cash_flow_sheet+income_sheet",
        abs_tol=0.2,
        rel_tol=0.08,
    )

    metric_source = income_kpi[KEY_COLUMNS + [
        "stock_abbr",
        "total_operating_revenue_kpi",
        "total_operating_revenue_income",
        "net_profit",
        "operating_revenue_qoq_growth",
        "net_profit_qoq_growth",
        "net_profit_excl_non_recurring",
        "net_profit_excl_non_recurring_yoy",
    ]].copy()

    qoq_rows_revenue = build_qoq_detail_rows(metric_source, "total_operating_revenue_kpi", "total_operating_revenue_income", "operating_revenue_qoq_growth")
    qoq_rows_profit = build_qoq_detail_rows(metric_source, "net_profit", "net_profit", "net_profit_qoq_growth")
    yoy_rows_excl = build_yoy_detail_rows(metric_source, "net_profit_excl_non_recurring", "net_profit_excl_non_recurring_yoy")

    add_rule(
        pd.DataFrame(qoq_rows_revenue),
        rule_name="operating_revenue_qoq_consistency",
        description="依据累计值还原单季度值后，校验营业收入环比字段。",
        formula=r"QoQ_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%",
        table_scope="core_performance_indicators_sheet+income_sheet",
        abs_tol=5.0,
        rel_tol=0.15,
    )
    add_rule(
        pd.DataFrame(qoq_rows_profit),
        rule_name="net_profit_qoq_consistency",
        description="依据累计值还原单季度值后，校验净利润环比字段。",
        formula=r"QoQ_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%",
        table_scope="core_performance_indicators_sheet+income_sheet",
        abs_tol=5.0,
        rel_tol=0.15,
    )
    add_rule(
        pd.DataFrame(yoy_rows_excl),
        rule_name="net_profit_excl_non_recurring_yoy_consistency",
        description="按同报告期跨年对齐，校验扣非净利润同比字段。",
        formula=r"YoY_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%",
        table_scope="core_performance_indicators_sheet",
        abs_tol=5.0,
        rel_tol=0.15,
    )

    non_empty_details = [frame.dropna(axis=1, how="all") for frame in details if not frame.empty]
    non_empty_details = [frame for frame in non_empty_details if not frame.empty]
    detail_df = pd.concat(non_empty_details, ignore_index=True, sort=False) if non_empty_details else pd.DataFrame()
    if "stock_abbr" not in detail_df.columns:
        detail_df["stock_abbr"] = None
    keep_cols = [
        "rule_name",
        "description",
        "formula",
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


def build_qoq_detail_rows(
    dataframe: pd.DataFrame,
    kpi_metric_col: str,
    fallback_metric_col: str,
    qoq_col: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    work = dataframe.copy()
    work["metric_value"] = work[kpi_metric_col].fillna(work[fallback_metric_col])

    for stock_code, company_df in work.groupby("stock_code"):
        years = sorted(company_df["report_year"].dropna().astype(int).unique())
        company_year_map: dict[int, dict[str, dict[str, object]]] = {}
        for year in years:
            sub = company_df[company_df["report_year"] == year].copy()
            period_map: dict[str, dict[str, object]] = {}
            for item in sub.to_dict(orient="records"):
                suffix = period_suffix(item["report_period"])
                period_map[suffix] = item
            company_year_map[year] = period_map

        for year in years:
            period_map = company_year_map.get(year, {})
            cumulative: dict[str, float] = {}
            for suffix in ["Q1", "H1", "Q3", "FY"]:
                item = period_map.get(suffix)
                if not item:
                    continue
                value = safe_float(item.get("metric_value"))
                if value is not None:
                    cumulative[suffix] = value
            singles = build_single_quarter_values(cumulative)

            previous_single = None
            for suffix in ["Q1", "H1", "Q3", "FY"]:
                item = period_map.get(suffix)
                if not item:
                    continue
                actual = safe_float(item.get(qoq_col))
                current_single = singles.get(suffix)
                if suffix == "Q1":
                    prev_year_map = company_year_map.get(year - 1, {})
                    prev_q3 = safe_float(prev_year_map.get("Q3", {}).get("metric_value")) if prev_year_map.get("Q3") else None
                    prev_fy = safe_float(prev_year_map.get("FY", {}).get("metric_value")) if prev_year_map.get("FY") else None
                    if actual is not None and None not in (current_single, prev_q3, prev_fy):
                        previous_q4 = prev_fy - prev_q3
                        if previous_q4 != 0:
                            rows.append(
                                {
                                    "stock_code": stock_code,
                                    "stock_abbr": item.get("stock_abbr"),
                                    "report_period": item.get("report_period"),
                                    "report_year": item.get("report_year"),
                                    "actual_value": actual,
                                    "expected_value": (current_single - previous_q4) / abs(previous_q4) * 100,
                                }
                            )
                    previous_single = current_single
                    continue
                if actual is not None and current_single is not None and previous_single not in (None, 0):
                    rows.append(
                        {
                            "stock_code": stock_code,
                            "stock_abbr": item.get("stock_abbr"),
                            "report_period": item.get("report_period"),
                            "report_year": item.get("report_year"),
                            "actual_value": actual,
                            "expected_value": (current_single - previous_single) / abs(previous_single) * 100,
                        }
                    )
                previous_single = current_single
    return rows


def build_yoy_detail_rows(
    dataframe: pd.DataFrame,
    metric_col: str,
    yoy_col: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    work = dataframe[["stock_code", "stock_abbr", "report_period", "report_year", metric_col, yoy_col]].copy()
    work["period_suffix"] = work["report_period"].map(period_suffix)

    for (stock_code, suffix), sub in work.groupby(["stock_code", "period_suffix"]):
        if suffix not in PERIOD_ORDER:
            continue
        sub = sub.sort_values("report_year")
        previous_value = None
        for item in sub.to_dict(orient="records"):
            current_value = safe_float(item.get(metric_col))
            current_yoy = safe_float(item.get(yoy_col))
            if current_value is not None and previous_value not in (None, 0) and current_yoy is not None:
                rows.append(
                    {
                        "stock_code": stock_code,
                        "stock_abbr": item.get("stock_abbr"),
                        "report_period": item.get("report_period"),
                        "report_year": item.get("report_year"),
                        "actual_value": current_yoy,
                        "expected_value": (current_value - previous_value) / abs(previous_value) * 100,
                    }
                )
            if current_value is not None:
                previous_value = current_value
    return rows


def build_single_quarter_values(cumulative_values: dict[str, float]) -> dict[str, float]:
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
        "worst_rules": summary_df.head(8)[["rule_name", "failure_rate", "failed_count"]].to_dict(orient="records"),
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
        "## 规则定义",
        "",
        "| 规则 | 作用范围 | 公式 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for row in summary_df.itertuples(index=False):
        lines.append(f"| {row.rule_name} | {row.table_scope} | `{row.formula}` | {row.description} |")

    lines.extend(
        [
            "",
            "## 分规则结果",
            "",
            "| 规则 | 可判定 | 通过 | 失败 | 通过率 | 失败率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary_df.itertuples(index=False):
        lines.append(
            f"| {row.rule_name} | {row.applicable_count} | {row.passed_count} | {row.failed_count} | {row.pass_rate:.2%} | {row.failure_rate:.2%} |"
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
                f"| {row.rule_name} | {row.stock_code} | {row.stock_abbr} | {row.report_period} | {row.report_year} | {row.actual_value:.4f} | {row.expected_value:.4f} | {row.difference:.4f} |"
            )

    (output_dir / "accounting_check_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overall


def main() -> None:
    args = parse_args()
    database_url = args.database_url or f"sqlite:///{Path('outputs/task1/task1_financials.db').resolve()}"
    engine = create_engine(database_url)
    summaries, detail_df = build_rule_evaluations(engine)
    overall = write_outputs(args.output_dir, summaries, detail_df)
    print(json.dumps(overall, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
