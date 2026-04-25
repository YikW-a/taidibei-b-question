# 任务一实验结果表

| 表名 | 记录数 | 平均字段覆盖率 | 主要缺失字段 |
| --- | ---: | ---: | --- |
| core_performance_indicators_sheet | 120 | 0.9594 | 无明显高缺失字段 |
| balance_sheet | 120 | 0.9927 | 无明显高缺失字段 |
| cash_flow_sheet | 120 | 0.9904 | 无明显高缺失字段 |
| income_sheet | 120 | 0.9995 | 无明显高缺失字段 |

## 缺失原因 Top 字段
### balance_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| liability_advance_from_customers | 14 | likely_extraction_gap |

### cash_flow_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| net_cash_flow_yoy_growth | 15 | prior_period_value_unavailable |

### core_performance_indicators_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| net_profit_excl_non_recurring_yoy | 26 | likely_extraction_gap |
| net_profit_qoq_growth | 22 | likely_not_disclosed_in_source |
| operating_revenue_qoq_growth | 20 | likely_not_disclosed_in_source |
| net_asset_per_share | 2 | missing_share_basis |
| operating_cf_per_share | 2 | upstream_cash_flow_missing |
| eps | 1 | likely_extraction_gap |

### income_sheet
| 字段 | 缺失数 | 主因 |
| --- | ---: | --- |
| asset_impairment_loss | 1 | likely_extraction_gap |
