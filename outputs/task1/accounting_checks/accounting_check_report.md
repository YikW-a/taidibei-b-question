# 会计勾稽校验报告

## 总体结果
- 校验规则数：16
- 可判定样本数：11894
- 通过数：11653
- 失败数：241
- 跳过数：0
- 总体通过率：97.97%
- 总体失败率：2.03%

## 规则定义

| 规则 | 作用范围 | 公式 | 说明 |
| --- | --- | --- | --- |
| cash_flow_equation | cash_flow_sheet | `NCF=OCF+ICF+FCF` | 校验现金及现金等价物净增加额与三类活动净现金流的勾稽关系。 |
| net_profit_excl_non_recurring_yoy_consistency | core_performance_indicators_sheet | `YoY_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%` | 按同报告期跨年对齐，校验扣非净利润同比字段。 |
| net_profit_qoq_consistency | core_performance_indicators_sheet+income_sheet | `QoQ_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%` | 依据累计值还原单季度值后，校验净利润环比字段。 |
| gross_profit_margin_consistency | core_performance_indicators_sheet+income_sheet | `GPM=\frac{R^*-C}{R^*}\times 100\%` | 以择优收入口径校验毛利率，避免因收入选取错误造成假异常。 |
| roe_consistency | core_performance_indicators_sheet+income_sheet+balance_sheet | `ROE=\frac{NP}{E}\times 100\%` | 在年报、正权益且符号一致条件下，以保守口径校验 ROE。 |
| eps_net_profit_sign_consistency | core_performance_indicators_sheet+income_sheet | `\operatorname{sign}(EPS)=\operatorname{sign}(NP)` | 在股本为正的前提下，每股收益与净利润应保持同号。 |
| asset_liability_ratio_consistency | balance_sheet | `\rho_{AL}=\frac{L}{A}\times 100\%` | 校验资产负债率字段与资产负债表金额之间的一致性。 |
| balance_equation | balance_sheet | `A=L+E` | 校验资产总计是否与负债合计和所有者权益合计闭合。 |
| financing_cf_ratio_consistency | cash_flow_sheet | `Ratio=\frac{financing_cf_net_amount}{NCF}\times 100\%` | 校验 `financing_cf_ratio_of_net_cf` 与净现金流占比公式的一致性。 |
| investing_cf_ratio_consistency | cash_flow_sheet | `Ratio=\frac{investing_cf_net_amount}{NCF}\times 100\%` | 校验 `investing_cf_ratio_of_net_cf` 与净现金流占比公式的一致性。 |
| margin_order_consistency | core_performance_indicators_sheet | `NPM \le GPM + \delta,\ \delta=20` | 净利率通常不应显著高于毛利率，用于捕捉收入口径或成本口径错配。 |
| net_asset_per_share_consistency | core_performance_indicators_sheet+balance_sheet+income_sheet | `NAVPS=\frac{E\times 10000}{Shares},\ Shares=\frac{NP\times 10000}{EPS}` | 以权益和推断股本校验每股净资产。 |
| net_profit_margin_consistency | core_performance_indicators_sheet+income_sheet | `NPM=\frac{NP}{R^*}\times 100\%` | 以择优收入口径校验净利率。 |
| operating_cf_per_share_consistency | core_performance_indicators_sheet+cash_flow_sheet+income_sheet | `OCFPS=\frac{OCF\times 10000}{Shares}` | 以经营活动现金流量净额和推断股本校验每股经营现金流。 |
| operating_cf_ratio_consistency | cash_flow_sheet | `Ratio=\frac{operating_cf_net_amount}{NCF}\times 100\%` | 校验 `operating_cf_ratio_of_net_cf` 与净现金流占比公式的一致性。 |
| operating_revenue_qoq_consistency | core_performance_indicators_sheet+income_sheet | `QoQ_t=\frac{x_t-x_{t-1}}{|x_{t-1}|}\times 100\%` | 依据累计值还原单季度值后，校验营业收入环比字段。 |

## 分规则结果

| 规则 | 可判定 | 通过 | 失败 | 通过率 | 失败率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash_flow_equation | 823 | 636 | 187 | 77.28% | 22.72% |
| net_profit_excl_non_recurring_yoy_consistency | 512 | 475 | 37 | 92.77% | 7.23% |
| net_profit_qoq_consistency | 644 | 637 | 7 | 98.91% | 1.09% |
| gross_profit_margin_consistency | 823 | 818 | 5 | 99.39% | 0.61% |
| roe_consistency | 202 | 201 | 1 | 99.50% | 0.50% |
| eps_net_profit_sign_consistency | 820 | 816 | 4 | 99.51% | 0.49% |
| asset_liability_ratio_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| balance_equation | 823 | 823 | 0 | 100.00% | 0.00% |
| financing_cf_ratio_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| investing_cf_ratio_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| margin_order_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| net_asset_per_share_consistency | 816 | 816 | 0 | 100.00% | 0.00% |
| net_profit_margin_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| operating_cf_per_share_consistency | 816 | 816 | 0 | 100.00% | 0.00% |
| operating_cf_ratio_consistency | 823 | 823 | 0 | 100.00% | 0.00% |
| operating_revenue_qoq_consistency | 677 | 677 | 0 | 100.00% | 0.00% |

## 失败样例（前 20 条）

| 规则 | 股票代码 | 股票简称 | 报告期 | 报告年份 | 实际值 | 期望值 | 差值 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| cash_flow_equation | 002589 | 瑞康医药 | 2024FY | 2024 | 21794.7456 | 298054.4524 | 276259.7068 |
| cash_flow_equation | 002589 | 瑞康医药 | 2022FY | 2022 | -34908.9830 | 190502.0183 | 225411.0013 |
| cash_flow_equation | 000650 | 仁和药业 | 2023Q1 | 2023 | -179749.2491 | -359498.4981 | 179749.2491 |
| cash_flow_equation | 600329 | 达仁堂 | 2024FY | 2024 | 94704.6824 | 255105.2205 | 160400.5381 |
| cash_flow_equation | 002603 | 以岭药业 | 2023FY | 2023 | -96402.9022 | -255547.2869 | 159144.3848 |
| cash_flow_equation | 000538 | 云南白药 | 2024H1 | 2024 | -145735.0472 | -8948.0225 | 136787.0247 |
| cash_flow_equation | 000999 | 华润三九 | 2023FY | 2023 | 385367.6936 | 519397.7069 | 134030.0133 |
| cash_flow_equation | 002589 | 瑞康医药 | 2023H1 | 2023 | 40796.8405 | 162397.7359 | 121600.8954 |
| cash_flow_equation | 002737 | 葵花药业 | 2022FY | 2022 | 108432.9348 | 227397.5554 | 118964.6206 |
| cash_flow_equation | 002287 | 奇正藏药 | 2024FY | 2024 | -19891.2281 | 90838.6501 | 110729.8783 |
| cash_flow_equation | 000538 | 云南白药 | 2022FY | 2022 | -582370.4830 | -492106.4990 | 90263.9840 |
| cash_flow_equation | 002287 | 奇正藏药 | 2024H1 | 2024 | 48614.5703 | 128371.7949 | 79757.2246 |
| cash_flow_equation | 002737 | 葵花药业 | 2023FY | 2023 | -11271.2044 | 62381.4632 | 73652.6677 |
| cash_flow_equation | 600993 | 马应龙 | 2023H1 | 2023 | -41919.3402 | 25740.6132 | 67659.9533 |
| cash_flow_equation | 600422 | 昆药集团 | 2024FY | 2024 | 76709.1027 | 11999.5928 | 64709.5099 |
| cash_flow_equation | 002603 | 以岭药业 | 2025H1 | 2025 | 17980.3812 | 79010.4728 | 61030.0916 |
| cash_flow_equation | 600085 | 同仁堂 | 2024H1 | 2024 | -63166.1756 | -6304.4615 | 56861.7141 |
| cash_flow_equation | 600572 | 康恩贝 | 2022FY | 2022 | 2877.3618 | 57423.7150 | 54546.3531 |
| cash_flow_equation | 600993 | 马应龙 | 2025H1 | 2025 | -128820.4983 | -77275.7929 | 51544.7053 |
| cash_flow_equation | 600993 | 马应龙 | 2022FY | 2022 | -9748.7848 | -59707.5474 | 49958.7626 |
