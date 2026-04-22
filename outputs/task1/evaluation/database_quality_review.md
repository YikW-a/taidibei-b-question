# 任务一数据库质量复核

## 1. 总体情况

- 主记录总数：`3293`
- `balance_sheet` 记录数：`823`
- `cash_flow_sheet` 记录数：`823`
- `core_performance_indicators_sheet` 记录数：`824`
- `income_sheet` 记录数：`823`

## 2. 入库前校验结果

- 校验问题总数：`168`
- `cash_flow_sheet|warning`：`163`
- `core_performance_indicators_sheet|warning`：`5`

## 3. 数值异常复核

- 数值异常条目数：`144`
- 高频异常字段：
  - `cash_flow_sheet.operating_cf_ratio_of_net_cf` / `percentage_outlier`：`57`
  - `cash_flow_sheet.financing_cf_ratio_of_net_cf` / `percentage_outlier`：`48`
  - `cash_flow_sheet.investing_cf_ratio_of_net_cf` / `percentage_outlier`：`38`
  - `core_performance_indicators_sheet.roe_weighted_excl_non_recurring` / `percentage_outlier`：`1`
  - `cash_flow_sheet.cash_flow_equation_precheck` / `validation_warning`：`163`
  - `core_performance_indicators_sheet.gross_profit_margin_consistency_precheck` / `validation_warning`：`5`

## 4. 重点异常样例

- `cash_flow_sheet` `600085|2025Q3|2025` `operating_cf_ratio_of_net_cf` = `-33046.13860620054`（percentage_outlier）
- `cash_flow_sheet` `600085|2025Q3|2025` `investing_cf_ratio_of_net_cf` = `6689.6838000218895`（percentage_outlier）
- `cash_flow_sheet` `600085|2025Q3|2025` `financing_cf_ratio_of_net_cf` = `26089.598584333835`（percentage_outlier）
- `cash_flow_sheet` `600252|2025Q1|2025` `operating_cf_ratio_of_net_cf` = `-1694.1744992788422`（percentage_outlier）
- `cash_flow_sheet` `600252|2025Q1|2025` `financing_cf_ratio_of_net_cf` = `1839.6390665896909`（percentage_outlier）
- `cash_flow_sheet` `600252|2025Q3|2025` `operating_cf_ratio_of_net_cf` = `-2538.5263512568135`（percentage_outlier）
- `cash_flow_sheet` `600252|2025Q3|2025` `financing_cf_ratio_of_net_cf` = `3030.781972227577`（percentage_outlier）
- `cash_flow_sheet` `600285|2023Q3|2023` `operating_cf_ratio_of_net_cf` = `1319.8535192319534`（percentage_outlier）
- `cash_flow_sheet` `600332|2022FY|2022` `operating_cf_ratio_of_net_cf` = `-3354.2161793127043`（percentage_outlier）
- `cash_flow_sheet` `600332|2022FY|2022` `investing_cf_ratio_of_net_cf` = `3475.9958653873064`（percentage_outlier）

## 5. 复核结论

- 当前结果已在入库前增加异常值清洗、跨表一致性校验与旧口径字段回填。
- 仍需重点关注底层抽取带来的极端金额和比例异常，并优先复核会在任务二问答中直接影响排序、筛选和均值统计的字段。
