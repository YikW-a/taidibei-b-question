# 任务一数据库质量复核

## 1. 总体情况

- 主记录总数：`480`
- `balance_sheet` 记录数：`120`
- `cash_flow_sheet` 记录数：`120`
- `core_performance_indicators_sheet` 记录数：`120`
- `income_sheet` 记录数：`120`

## 2. 入库前校验结果

- 校验问题总数：`15`
- `cash_flow_sheet|warning`：`14`
- `core_performance_indicators_sheet|warning`：`1`

## 3. 数值异常复核

- 数值异常条目数：`16`
- 高频异常字段：
  - `cash_flow_sheet.operating_cf_ratio_of_net_cf` / `percentage_outlier`：`6`
  - `cash_flow_sheet.investing_cf_ratio_of_net_cf` / `percentage_outlier`：`5`
  - `cash_flow_sheet.financing_cf_ratio_of_net_cf` / `percentage_outlier`：`5`
  - `cash_flow_sheet.cash_flow_equation_precheck` / `validation_warning`：`14`
  - `core_performance_indicators_sheet.gross_profit_margin_consistency_precheck` / `validation_warning`：`1`

## 4. 重点异常样例

- `cash_flow_sheet` `603127|2023Q3|2023` `operating_cf_ratio_of_net_cf` = `-5472.2643123852595`（percentage_outlier）
- `cash_flow_sheet` `603127|2023Q3|2023` `investing_cf_ratio_of_net_cf` = `1673.5982615819169`（percentage_outlier）
- `cash_flow_sheet` `603127|2023Q3|2023` `financing_cf_ratio_of_net_cf` = `4067.089675803032`（percentage_outlier）
- `cash_flow_sheet` `603127|2024Q1|2024` `operating_cf_ratio_of_net_cf` = `1028.1323338794014`（percentage_outlier）
- `cash_flow_sheet` `603259|2022FY|2022` `investing_cf_ratio_of_net_cf` = `5062.007029162446`（percentage_outlier）
- `cash_flow_sheet` `603259|2024H1|2024` `investing_cf_ratio_of_net_cf` = `-1868.2651274411196`（percentage_outlier）
- `cash_flow_sheet` `603259|2024H1|2024` `financing_cf_ratio_of_net_cf` = `1951.9875866583188`（percentage_outlier）
- `cash_flow_sheet` `603259|2024Q3|2024` `operating_cf_ratio_of_net_cf` = `-1148.7082448577783`（percentage_outlier）
- `cash_flow_sheet` `002821|2023FY|2023` `operating_cf_ratio_of_net_cf` = `1004.3553681951589`（percentage_outlier）
- `cash_flow_sheet` `002821|2024Q1|2024` `operating_cf_ratio_of_net_cf` = `16042.925049951114`（percentage_outlier）

## 5. 复核结论

- 当前结果已在入库前增加异常值清洗、跨表一致性校验与旧口径字段回填。
- 仍需重点关注底层抽取带来的极端金额和比例异常，并优先复核会在任务二问答中直接影响排序、筛选和均值统计的字段。
