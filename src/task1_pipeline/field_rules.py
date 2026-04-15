from __future__ import annotations

FIELD_RULES: dict[str, dict[str, dict[str, object]]] = {
    "core_performance_indicators_sheet": {
        "eps": {"mode": "direct"},
        "total_operating_revenue": {"mode": "prefer_reuse", "source": "income_sheet.total_operating_revenue"},
        "operating_revenue_yoy_growth": {"mode": "prefer_reuse", "source": "income_sheet.operating_revenue_yoy_growth"},
        "operating_revenue_qoq_growth": {"mode": "prefer_derive", "depends_on": ["total_operating_revenue", "report_period", "report_year"]},
        "net_profit_10k_yuan": {"mode": "prefer_reuse", "source": "income_sheet.net_profit"},
        "net_profit_yoy_growth": {"mode": "prefer_reuse", "source": "income_sheet.net_profit_yoy_growth"},
        "net_profit_qoq_growth": {"mode": "prefer_derive", "depends_on": ["net_profit_10k_yuan", "report_period", "report_year"]},
        "net_asset_per_share": {"mode": "prefer_derive", "depends_on": ["balance_sheet.equity_total_equity", "eps", "income_sheet.net_profit"]},
        "roe": {"mode": "prefer_derive", "depends_on": ["income_sheet.net_profit", "balance_sheet.equity_total_equity"]},
        "operating_cf_per_share": {"mode": "prefer_derive", "depends_on": ["cash_flow_sheet.operating_cf_net_amount", "eps", "income_sheet.net_profit"]},
        "net_profit_excl_non_recurring": {"mode": "direct"},
        "net_profit_excl_non_recurring_yoy": {"mode": "prefer_derive"},
        "gross_profit_margin": {"mode": "prefer_derive", "depends_on": ["income_sheet.total_operating_revenue", "income_sheet.operating_expense_cost_of_sales"]},
        "net_profit_margin": {"mode": "prefer_derive", "depends_on": ["income_sheet.net_profit", "income_sheet.total_operating_revenue"]},
        "roe_weighted_excl_non_recurring": {"mode": "prefer_derive", "depends_on": ["net_profit_excl_non_recurring", "balance_sheet.equity_total_equity"]},
    },
    "balance_sheet": {
        "asset_liability_ratio": {"mode": "prefer_derive", "depends_on": ["asset_total_assets", "liability_total_liabilities"]},
        "equity_total_equity": {"mode": "prefer_derive", "depends_on": ["asset_total_assets", "liability_total_liabilities"]},
        "liability_contract_liabilities": {"mode": "direct_or_reuse", "source": "liability_advance_from_customers"},
    },
    "cash_flow_sheet": {
        "net_cash_flow": {"mode": "prefer_derive", "depends_on": ["operating_cf_net_amount", "investing_cf_net_amount", "financing_cf_net_amount"]},
        "operating_cf_ratio_of_net_cf": {"mode": "prefer_derive", "depends_on": ["operating_cf_net_amount", "net_cash_flow"]},
        "investing_cf_ratio_of_net_cf": {"mode": "prefer_derive", "depends_on": ["investing_cf_net_amount", "net_cash_flow"]},
        "financing_cf_ratio_of_net_cf": {"mode": "prefer_derive", "depends_on": ["financing_cf_net_amount", "net_cash_flow"]},
    },
}


PERIOD_ORDER = {
    "Q1": 1,
    "H1": 2,
    "Q3": 3,
    "FY": 4,
}
