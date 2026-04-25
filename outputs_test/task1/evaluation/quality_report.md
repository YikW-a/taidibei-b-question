# Task1 抽取质量报告

## 总览
- 主记录数: 480
- balance_sheet: 120
- cash_flow_sheet: 120
- core_performance_indicators_sheet: 120
- income_sheet: 120

## 表级覆盖率
- balance_sheet: 0.9927
- cash_flow_sheet: 0.9904
- core_performance_indicators_sheet: 0.9594
- income_sheet: 0.9995

## 高缺失字段

## 缺失原因判断
### balance_sheet
- liability_advance_from_customers: 缺失 14 条, 主因 `likely_extraction_gap`

### cash_flow_sheet
- net_cash_flow_yoy_growth: 缺失 15 条, 主因 `prior_period_value_unavailable`

### core_performance_indicators_sheet
- net_profit_excl_non_recurring_yoy: 缺失 26 条, 主因 `likely_extraction_gap`
- net_profit_qoq_growth: 缺失 22 条, 主因 `likely_not_disclosed_in_source`
- operating_revenue_qoq_growth: 缺失 20 条, 主因 `likely_not_disclosed_in_source`
- net_asset_per_share: 缺失 2 条, 主因 `missing_share_basis`
- operating_cf_per_share: 缺失 2 条, 主因 `upstream_cash_flow_missing`
- eps: 缺失 1 条, 主因 `likely_extraction_gap`

### income_sheet
- asset_impairment_loss: 缺失 1 条, 主因 `likely_extraction_gap`
