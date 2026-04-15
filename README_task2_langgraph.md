# 任务二 LangGraph 使用说明

## 1. 模块定位

[src/task2_langgraph](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph) 是当前任务二的主架构实现。它不再依赖旧版 `template + llm` 平铺流程，而是将“多轮问题理解、SQL 生成与修复、结果校验、图表规划、回答生成、提交导出”统一组织为一张可追踪的 LangGraph 状态图。

这一版的核心目标有三点：

1. 把附件 4 的多轮问数任务稳定串成可批量运行的单题闭环。
2. 让 SQL 生成、纠错、结果校验和图表渲染形成显式状态机，便于调试和论文表达。
3. 为后续任务三继续接入 `RAG + SQL + 自检` 节点预留标准扩展位。

当前任务二已经完成了从“脚本化问数”到“LangGraph 工作流”的迁移，当前状态可以概括为：

1. 框架已成型：多轮、澄清、SQL、图表、导出都已接通
2. 当前重点不再是重构，而是小批次回归与 Prompt / chart spec 调优
3. 剩余问题主要集中在：
   - 个别题型的图表表达不理想
   - 少数场景的澄清门控过宽或过窄
   - 导出状态与中间 artifacts 偶尔不同步
   - 任务一脏数据仍会污染任务二均值、排序和图表

当前模块直接读取以下输入：

- [正式数据/附件4：问题汇总.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/正式数据/附件4：问题汇总.xlsx)
- [正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx)
- [outputs/task1/task1_financials.db](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task1/task1_financials.db)

其中任务一数据库会在运行时被拼接为统一查询视图 `financials_view`，作为任务二全部 SQL 的唯一查询入口。

## 2. 总体架构

当前实现采用“配置层 - 状态层 - 服务层 - 工具层 - 节点层 - 图编排层”的目录化结构。

- `config`
  负责输入路径、数据库地址、输出目录和 LLM 参数管理。
- `schemas`
  负责题目对象、解析结果对象和 LangGraph 共享状态定义。
- `services`
  负责意图解析、Prompt 加载、OpenAI 兼容模型调用与 JSON 解析。
- `tools`
  负责统一查询视图构建、SQL 校验执行、结果后处理、图表 spec 与渲染。
- `nodes`
  负责把单题处理拆成细粒度节点，每个节点只承担一类职责。
- `graph`
  负责把节点串成 `StateGraph`，并定义澄清分支、SQL 重试分支与导出终点。
- `app`
  负责 CLI 入口、批量运行和结果汇总导出。

从执行链路上看，单题流程为：

`读取题目 -> 解析槽位 -> 判断是否澄清 -> 生成查询计划 -> 生成 SQL -> 执行并校验 -> 规划图表 -> 渲染图片 -> 生成回答 -> 追加轮次结果 -> 导出`

其中 `generate_sql -> execute_sql` 之间带有最多 3 次自动修复回路；图表部分采用 `chart_plan -> chart_spec -> renderer` 三层链路，避免让模型直接输出最终绘图代码。

## 3. 目录与文件

### 3.1 入口文件

- 主入口: [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task2_langgraph.py)
- CLI: [src/task2_langgraph/app/cli.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/app/cli.py)

### 3.2 核心模块

- 配置: [src/task2_langgraph/config/settings.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/config/settings.py)
- 状态定义: [src/task2_langgraph/schemas/state.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/schemas/state.py)
- 意图解析: [src/task2_langgraph/services/parser.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/services/parser.py)
- LLM 客户端: [src/task2_langgraph/services/llm.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/services/llm.py)
- 运行时工具: [src/task2_langgraph/tools/runtime.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/runtime.py)
- 图表规划: [src/task2_langgraph/tools/charts.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/charts.py)
- 图表 spec: [src/task2_langgraph/tools/chart_spec.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/chart_spec.py)
- 节点逻辑: [src/task2_langgraph/nodes/workflow.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/nodes/workflow.py)
- 图编排: [src/task2_langgraph/graph/builder.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/graph/builder.py)
- 批量运行器: [src/task2_langgraph/graph/runner.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/graph/runner.py)

### 3.3 Prompt 文件

外置 Prompt 位于 [src/task2_langgraph/prompts](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/prompts)：

- `query_plan_system.txt`
- `sql_generation_system.txt`
- `answer_generation_system.txt`
- `clarification_system.txt`
- `chart_plan_system.txt`

这意味着任务二的主要调优路径已经从“继续补题号规则”转向“先看 debug 结果，再小批次改 Prompt”。

## 4. 状态机节点说明

当前图中的节点职责如下。

| 节点 | 主要职责 | 关键输入 | 关键输出 |
| --- | --- | --- | --- |
| `parse_question` | 解析当前轮问题与累计上下文，抽取公司、期间、指标、图表意图 | `sub_questions`、`current_turn_index` | `parsed_slots`、`current_question`、`cumulative_question` |
| `clarify_or_continue` | 判断是否缺少公司、时间、指标等关键槽位 | `parsed_slots` | `missing_slots`、`needs_clarification` |
| `build_query_plan` | 把解析槽位整理为结构化查询计划，并吸收上轮上下文 | `parsed_slots`、`context_companies`、`context_rows` | `query_plan` |
| `generate_sql` | 基于问题、查询计划和上一轮报错生成或修复 SQL | `query_plan`、`sql_error` | `sql`、`sql_history`、`sql_attempts` |
| `execute_sql` | 执行 SQL，并对结果做后处理和质量校验 | `sql` | `result_rows`、`result_preview`、`result_row_count`、`sql_error` |
| `plan_chart` | 基于题意和查询结果生成默认图表计划，并可由 LLM 再修正 | `result_rows`、`query_plan` | `chart_plan` |
| `render_chart` | 将图表计划转为 `chart_spec`，再确定性渲染为图片 | `chart_plan`、`result_rows` | `chart_spec`、`current_chart_paths` |
| `generate_answer` | 对澄清轮生成追问，对查询轮生成正式中文回答 | `result_rows`、`sql` | `current_answer` |
| `append_turn_result` | 把当前轮 `Q/A/image` 追加到会话结果 | `current_answer`、`current_chart_paths` | `turn_answers` |
| `export_result` | 生成提交字段所需的 `answer_json` 和 `graph_format_text` | `turn_answers`、`graph_formats` | `answer_json`、`graph_format_text` |

## 4.1 当前已知问题与边界

- 任务二已经是 `LLM-only` 路线，不再保留旧版 `template` 兜底。
- 图表链路已经切成 `chart_plan -> chart_spec -> renderer`，但复杂题仍可能退回简单图型或表格图。
- 若底层数据库字段缺失或异常，任务二即使查询链路正确，也可能出现空回答、空图或不可信均值。
- 当前优先保证“结果正确和稳定”，其次才是“图形足够美观”；因此部分复杂题会保守退化为简单图型或表格图。

## 5. 关键实现机制

### 5.1 多轮上下文继承

系统会保留：

- `context_companies`
- `context_rows`
- `turn_answers`

因此后续轮次中的“这些公司”“上述企业”“其中哪家”等表述，可以复用上一轮已识别的公司集合或上一轮查询结果，而不是把每一轮都当成孤立问题处理。

### 5.2 统一查询视图 `financials_view`

运行时会把任务一输出的四张表：

- `income_sheet`
- `core_performance_indicators_sheet`
- `balance_sheet`
- `cash_flow_sheet`

按 `stock_code + report_period + report_year` 进行宽表拼接，形成统一视图 `financials_view`。这样任务二的 SQL 生成只需面向一张标准视图，大幅降低了 Prompt 和查询模板的复杂度。

同时，系统会补充若干派生指标，例如：

- `rnd_expense_ratio`
- `inventory_turnover_ratio`

并对金额类、比例类字段做异常值清洗，减少模型误用脏值的概率。

### 5.3 SQL 安全限制与自动修复

当前 SQL 只允许：

- `SELECT`
- `WITH`

并且必须查询 `financials_view`，禁止：

- `INSERT`
- `UPDATE`
- `DELETE`
- `DROP`
- `ALTER`
- `CREATE`
- `ATTACH`
- `PRAGMA`

如果 SQL 执行失败，或结果被判定为无效，系统会把“上一版 SQL + 报错信息”重新送回模型，最多重试 3 次。当前会触发修复的典型问题包括：

- 排名题返回记录过少
- 趋势题时间点不足
- 报告期格式不规范
- 结果全为零
- 比例字段疑似放大 100 倍或 10000 倍

### 5.4 结果后处理与答案兜底

执行 SQL 后，系统会先根据问题涉及的指标挑出有效列，再过滤“相关指标全部为空”的记录。回答阶段优先让模型生成中文结论；若问题明确要求“列出”“展示”“分别是多少”等，或者模型回答遗漏公司与关键字段，则退回确定性枚举回答，避免生成看似自然但信息不全的文本。

### 5.5 图表三层链路

当前图表模块不再让模型直接决定最终图片，而是采用：

`问题 -> chart_plan -> chart_spec -> renderer`

三层架构：

1. `chart_plan`
   负责决定画什么图、用哪些字段、是否排序和取 TopN。
2. `chart_spec`
   把图表计划转成标准结构化契约，明确编码、布局、输出文件和元信息。
3. `renderer`
   只负责按 spec 做确定性渲染，默认输出 `.jpg`。

这套设计的直接好处是：

- LLM 只负责规划，不直接控制绘图细节。
- 图表结果可以通过 `.spec.json` 独立审查和复现。
- 后续切换渲染器或为任务三加入图表解释节点时，更容易扩展。

图表 spec 说明见 [docs/task2_langgraph_chart_spec_demo.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/docs/task2_langgraph_chart_spec_demo.md)。

## 5.6 配套论文文档

当前任务二已补齐以下配套文档：

- 技术路线图: [docs/task2/任务二技术路线图.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/docs/task2/任务二技术路线图.md)
- 算法流程图: [docs/task2/任务二算法流程图.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/docs/task2/任务二算法流程图.md)
- 论文正文初稿: [docs/task2/任务二论文正文小节初稿.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/docs/task2/任务二论文正文小节初稿.md)

## 6. 运行方式

### 6.1 LLM 配置

当前模块为 `llm-only`，运行前需要配置：

- `TASK2_LLM_BASE_URL`
- `TASK2_LLM_API_KEY`
- `TASK2_LLM_MODEL`

默认配置文件为：

- [configs/task2_llm.env](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/configs/task2_llm.env)
- 模板文件: [configs/task2_llm.env.example](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/configs/task2_llm.env.example)

示例：

```env
TASK2_LLM_BASE_URL=https://api.siliconflow.cn/v1
TASK2_LLM_API_KEY=YOUR_API_KEY
TASK2_LLM_MODEL=deepseek-ai/DeepSeek-V3.2
```

推荐先执行：

```bash
cp configs/task2_llm.env.example configs/task2_llm.env
```

再把真实 `API Key` 写入本地的 `configs/task2_llm.env`。该文件已被 `.gitignore` 忽略，不会被提交到 GitHub。

### 6.2 单题调试

```bash
python3 run_task2_langgraph.py --question-id B1006
```

### 6.3 按题号批量运行

```bash
python3 run_task2_langgraph.py --question-ids B1001,B1006,B1048
```

### 6.4 随机抽样运行

```bash
python3 run_task2_langgraph.py --sample-limit 10 --sample-seed 7
```

### 6.5 全量运行

```bash
python3 run_task2_langgraph.py
```

如果需要显式指定配置文件：

```bash
python3 run_task2_langgraph.py --llm-config configs/task2_llm.env
```

## 7. 输出结果

批量运行完成后，会在 [outputs/task2_langgraph](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph) 下生成：

- [outputs/task2_langgraph/result_2.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/result_2.xlsx)
- [outputs/task2_langgraph/result](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/result)
- [outputs/task2_langgraph/artifacts/task2_langgraph_results.csv](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/task2_langgraph_results.csv)
- [outputs/task2_langgraph/artifacts/task2_langgraph_summary.json](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/task2_langgraph_summary.json)
- [outputs/task2_langgraph/artifacts/debug](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/debug)
- [outputs/task2_langgraph/artifacts/chart_specs](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/chart_specs)

各文件作用如下：

- `result_2.xlsx`
  赛题提交主表，包含 `编号 / 问题 / SQL 查询语句 / 图形格式 / 回答`。
- `result/`
  题目要求的图片目录，文件命名为 `问题编号_序号.jpg`。
- `task2_langgraph_results.csv`
  调试明细，额外包含 `状态 / 备注` 字段。
- `task2_langgraph_summary.json`
  批量运行汇总信息，便于快速查看 `ok / warning / error` 数量。
- `debug/*.json`
  每题完整状态快照，含 `parsed_slots / query_plan / sql_history / chart_plan / answer_json`。
- `chart_specs/*.spec.json`
  每张图的结构化描述文件，便于图表链路调试。

## 8. 调试建议

推荐按下面顺序调试任务二，而不是一开始就盯着最终 Excel：

1. 先跑 `--question-id`，确认单题的 `parsed_slots`、`query_plan` 和 `sql_history` 是否合理。
2. 再看 `debug/*.json`，判断失败是出在意图解析、SQL 生成、结果校验还是图表计划。
3. 优先调整 Prompt，再考虑是否补充新的规则。
4. 当同类题反复失败时，再补通用业务规则，而不是直接写题号特判。

推荐的新环境调试顺序是：

1. 先单题：`--question-id`
2. 再小批量：`--sample-limit 10 --sample-seed 7`
3. 再定向题集：`--question-ids ...`
4. 最后全量 70 题

每次优先检查：
- `result_2.xlsx`
- `artifacts/debug/*.json`
- `artifacts/chart_specs/*.spec.json`
- `artifacts/task2_langgraph_summary.json`

如果图画得不对，建议优先看：

- `chart_plan`
- `chart_spec`
- `result_rows`

因为图表问题往往不在渲染器本身，而在于前面的字段选择、排序方向或系列划分不合理。

## 9. 与任务一、任务三的关系

任务二的输入底座来自任务一，输出形式又要满足赛题最终提交约束，因此它处于“数据底座”和“智能问答交互”之间的中间层。当前 LangGraph 版已经把这一层的关键状态显式化了。

从后续扩展看，任务三只需在此基础上继续增加：

- 财报或研报检索节点
- 证据重排序节点
- SQL 与文本证据融合节点
- 自检与事实核验节点

因此，这套任务二架构并不是一次性脚本，而是面向后续增强分析任务的统一工作流底座。

## 10. 换环境接手建议

如果在新环境继续任务二，建议按下面顺序恢复：

1. 先保证任务一数据库可用
   - 核对 `outputs/task1/task1_financials.db`
2. 配置 LLM
   - 编辑 `configs/task2_llm.env`
3. 安装依赖
   - 使用项目根目录的 `requirements.txt`
4. 先做最小连通测试
   - `python run_task2_langgraph.py --question-id B1001`
5. 再做小批次 Prompt 调优
   - `python run_task2_langgraph.py --sample-limit 10 --sample-seed 7`
6. 最后跑全量
   - `rm -rf outputs/task2_langgraph`
   - `python run_task2_langgraph.py`

如果新环境里任务二表现明显退化，优先检查：
- LLM 接口是否稳定
- `configs/task2_llm.env` 是否加载成功
- 任务一数据库是否是最新结果
- `artifacts/debug/*.json` 中的 `query_plan / sql / result_rows / chart_spec` 哪一层先出错
