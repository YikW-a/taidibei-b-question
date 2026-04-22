# Task1 抽取质量报告

## 总览
- 主记录数: 3293
- balance_sheet: 823
- cash_flow_sheet: 823
- core_performance_indicators_sheet: 824
- income_sheet: 823

## 表级覆盖率
- balance_sheet: 0.9978
- cash_flow_sheet: 0.9952
- core_performance_indicators_sheet: 0.9558
- income_sheet: 0.9983

## 高缺失字段

## 缺失原因判断
### balance_sheet
- liability_advance_from_customers: 缺失 21 条, 主因 `likely_extraction_gap`
- asset_trading_financial_assets: 缺失 7 条, 主因 `likely_extraction_gap`
- asset_construction_in_progress: 缺失 1 条, 主因 `likely_extraction_gap`

### cash_flow_sheet
- net_cash_flow_yoy_growth: 缺失 41 条, 主因 `prior_period_value_unavailable`
- investing_cf_cash_from_investment_recovery: 缺失 9 条, 主因 `likely_extraction_gap`
- operating_cf_cash_from_sales: 缺失 1 条, 主因 `likely_extraction_gap`

### core_performance_indicators_sheet
- net_profit_qoq_growth: 缺失 178 条, 主因 `likely_not_disclosed_in_source`
- net_profit_excl_non_recurring_yoy: 缺失 174 条, 主因 `likely_extraction_gap`
- operating_revenue_qoq_growth: 缺失 145 条, 主因 `likely_extraction_gap`
- roe_weighted_excl_non_recurring: 缺失 16 条, 主因 `derivable_but_inputs_missing`
- net_profit_excl_non_recurring: 缺失 15 条, 主因 `likely_extraction_gap`
- net_profit_yoy_growth: 缺失 8 条, 主因 `likely_extraction_gap`
- net_asset_per_share: 缺失 4 条, 主因 `derivation_inputs_incomplete`
- operating_cf_per_share: 缺失 4 条, 主因 `upstream_cash_flow_missing`

### income_sheet
- net_profit_yoy_growth: 缺失 8 条, 主因 `likely_extraction_gap`
- total_operating_expenses: 缺失 6 条, 主因 `likely_extraction_gap`
- asset_impairment_loss: 缺失 4 条, 主因 `likely_extraction_gap`
- credit_impairment_loss: 缺失 4 条, 主因 `likely_extraction_gap`
