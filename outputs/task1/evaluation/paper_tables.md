# 任务一实验结果表

| 表名 | 记录数 | 平均字段覆盖率 | 主要缺失字段 |
| --- | ---: | ---: | --- |
| core_performance_indicators_sheet | 824 | 0.9558 | 无明显高缺失字段 |
| balance_sheet | 823 | 0.9978 | 无明显高缺失字段 |
| cash_flow_sheet | 823 | 0.9952 | 无明显高缺失字段 |
| income_sheet | 823 | 0.9983 | 无明显高缺失字段 |

## 缺失原因 Top 字段
### balance_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| liability_advance_from_customers | 21 | likely_extraction_gap |
| asset_trading_financial_assets | 7 | likely_extraction_gap |
| asset_construction_in_progress | 1 | likely_extraction_gap |

### cash_flow_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| net_cash_flow_yoy_growth | 41 | prior_period_value_unavailable |
| investing_cf_cash_from_investment_recovery | 9 | likely_extraction_gap |
| operating_cf_cash_from_sales | 1 | likely_extraction_gap |

### core_performance_indicators_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| net_profit_qoq_growth | 178 | likely_not_disclosed_in_source |
| net_profit_excl_non_recurring_yoy | 174 | likely_extraction_gap |
| operating_revenue_qoq_growth | 145 | likely_extraction_gap |
| roe_weighted_excl_non_recurring | 16 | derivable_but_inputs_missing |
| net_profit_excl_non_recurring | 15 | likely_extraction_gap |
| net_profit_yoy_growth | 8 | likely_extraction_gap |

### income_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| net_profit_yoy_growth | 8 | likely_extraction_gap |
| total_operating_expenses | 6 | likely_extraction_gap |
| asset_impairment_loss | 4 | likely_extraction_gap |
| credit_impairment_loss | 4 | likely_extraction_gap |
