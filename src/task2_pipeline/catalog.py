from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    field_name: str
    display_name: str
    source_table: str


METRIC_SPECS: dict[str, MetricSpec] = {
    "营业总收入": MetricSpec("total_operating_revenue", "营业总收入(万元)", "income_sheet"),
    "主营业务收入": MetricSpec("total_operating_revenue", "营业总收入(万元)", "income_sheet"),
    "收入": MetricSpec("total_operating_revenue", "营业总收入(万元)", "income_sheet"),
    "净利润": MetricSpec("net_profit", "净利润(万元)", "income_sheet"),
    "利润总额": MetricSpec("total_profit", "利润总额(万元)", "income_sheet"),
    "营业利润": MetricSpec("operating_profit", "营业利润(万元)", "income_sheet"),
    "研发费用": MetricSpec("operating_expense_rnd_expenses", "研发费用(万元)", "income_sheet"),
    "销售费用": MetricSpec("operating_expense_selling_expenses", "销售费用(万元)", "income_sheet"),
    "管理费用": MetricSpec("operating_expense_administrative_expenses", "管理费用(万元)", "income_sheet"),
    "财务费用": MetricSpec("operating_expense_financial_expenses", "财务费用(万元)", "income_sheet"),
    "营业成本": MetricSpec("operating_expense_cost_of_sales", "营业成本(万元)", "income_sheet"),
    "总资产": MetricSpec("asset_total_assets", "总资产(万元)", "balance_sheet"),
    "资产总额": MetricSpec("asset_total_assets", "总资产(万元)", "balance_sheet"),
    "负债总额": MetricSpec("liability_total_liabilities", "负债总额(万元)", "balance_sheet"),
    "股东权益总额": MetricSpec("equity_total_equity", "股东权益总额(万元)", "balance_sheet"),
    "股东权益": MetricSpec("equity_total_equity", "股东权益总额(万元)", "balance_sheet"),
    "未分配利润": MetricSpec("equity_unappropriated_profit", "未分配利润(万元)", "balance_sheet"),
    "存货": MetricSpec("asset_inventory", "存货(万元)", "balance_sheet"),
    "应收账款": MetricSpec("asset_accounts_receivable", "应收账款(万元)", "balance_sheet"),
    "货币资金": MetricSpec("asset_cash_and_cash_equivalents", "货币资金(万元)", "balance_sheet"),
    "短期借款": MetricSpec("liability_short_term_loans", "短期借款(万元)", "balance_sheet"),
    "资产负债率": MetricSpec("asset_liability_ratio", "资产负债率(%)", "balance_sheet"),
    "经营性现金流量净额": MetricSpec("operating_cf_net_amount", "经营性现金流量净额(万元)", "cash_flow_sheet"),
    "经营活动产生的现金流量净额": MetricSpec("operating_cf_net_amount", "经营性现金流量净额(万元)", "cash_flow_sheet"),
    "投资性现金流量净额": MetricSpec("investing_cf_net_amount", "投资性现金流量净额(万元)", "cash_flow_sheet"),
    "筹资性现金流量净额": MetricSpec("financing_cf_net_amount", "筹资性现金流量净额(万元)", "cash_flow_sheet"),
    "净现金流": MetricSpec("net_cash_flow", "净现金流(元)", "cash_flow_sheet"),
    "销售毛利率": MetricSpec("gross_profit_margin", "销售毛利率(%)", "core_performance_indicators_sheet"),
    "销售净利率": MetricSpec("net_profit_margin", "销售净利率(%)", "core_performance_indicators_sheet"),
    "ROE": MetricSpec("roe", "ROE(%)", "core_performance_indicators_sheet"),
    "净利润同比增长率": MetricSpec("net_profit_yoy_growth", "净利润同比增长率(%)", "income_sheet"),
    "营业总收入同比增长率": MetricSpec("operating_revenue_yoy_growth", "营业总收入同比增长率(%)", "income_sheet"),
    "营业总收入环比增长率": MetricSpec("operating_revenue_qoq_growth", "营业总收入环比增长率(%)", "core_performance_indicators_sheet"),
    "加权平均净资产收益率（扣非）": MetricSpec("roe_weighted_excl_non_recurring", "加权平均净资产收益率（扣非）(%)", "core_performance_indicators_sheet"),
    "扣非净利润": MetricSpec("net_profit_excl_non_recurring", "扣非净利润(万元)", "core_performance_indicators_sheet"),
    "每股净资产": MetricSpec("net_asset_per_share", "每股净资产", "core_performance_indicators_sheet"),
}


QUESTION_KEYWORDS_TO_METRICS: list[tuple[str, str]] = sorted(
    METRIC_SPECS.keys(),
    key=len,
    reverse=True,
)


COMMON_COMPANY_ALIASES = {
    "999": "华润三九",
    "三金": "桂林三金",
    "香雪制药": "香雪制药",
    "贵州百灵": "贵州百灵",
    "赛隆药业": "赛隆药业",
    "长药控股": "长药控股",
}
