# Task2 LangGraph 第一轮 Prompt 调优基准集

## 代表题 10 题

- `B1001`
  多轮澄清，单公司单指标查询。
- `B1006`
  多轮分析 + 趋势图 + 柱状图切换。
- `B1013`
  行业范围筛选 + 行业均值 + 多指标条件。
- `B1023`
  复合增长率计算 + 排名 + 图表。
- `B1044`
  多轮追问，TopN 公司后续继续追净利润与行业均值比较。
- `B1048`
  多阶段推理，榜单变化与二次比较。
- `B1050`
  单公司长时间序列趋势 + 折线图。
- `B1055`
  双时期名单变化 + 双条形图。
- `B1066`
  模糊问题到明确条件的多轮澄清与筛选。
- `B1069`
  开放式概括 + 行业均值统计 + 同比变化。

## 第一轮调优目标

1. 让 `query_plan` 更稳定地识别：
   - 全行业 vs 单公司
   - 多轮上下文补全
   - TopN / 阈值 / 图表意图
2. 让 `generate_sql` 真正利用 `query_plan`
3. 让 `chart_plan` 在趋势、排名、双时期对比上更稳
4. 让 `answer_generation` 更聚焦当前轮问题

## 调试文件优先查看顺序

1. `parsed_slots`
2. `query_plan`
3. `sql`
4. `sql_error`
5. `chart_plan`
6. `answer_json`

## 推荐运行命令

```bash
conda run -n taidibei python run_task2_langgraph.py --question-ids B1001,B1006,B1013,B1023,B1044,B1048,B1050,B1055,B1066,B1069
```
