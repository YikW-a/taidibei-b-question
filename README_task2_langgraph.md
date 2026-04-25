# 任务二 LangGraph 使用说明

## 1. 模块定位

任务二当前主实现为：

- [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)

它已经完全替代旧版普通任务二实现，当前仓库只保留 LangGraph 版本。

主入口：

- [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task2_langgraph.py)

任务二当前已经完成从“脚本化问数”到“**显式状态图工作流**”的迁移，现阶段重点不再是重构架构，而是：

- 小样本回归
- Prompt 调优
- 图表策略收口
- 澄清门控收敛

当前这版正式实现的核心思路可以概括为：

- 用 `LangGraph` 管理多轮状态，而不是把整题交给单次黑盒生成；
- 用分层提示词分别约束 `query_plan / SQL / clarification / answer`；
- 用任务一统一后的字段口径反向约束任务二的指标理解与 SQL 生成；
- 对高频且口径敏感的题型增加确定性 SQL 模板，降低对即时生成的依赖。

---

## 2. 当前已完成能力

任务二当前已经接通：

1. 多轮问题解析
2. 澄清门控
3. `query_plan -> SQL -> answer`
4. SQL 自动修复重试
5. `chart_plan -> chart_spec -> renderer`
6. `result_2.xlsx` 导出
7. `debug/*.json` 与 `chart_specs/*.spec.json` 调试落盘

当前模块读取：

- [附件4：问题汇总.xlsx](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/正式数据/附件4：问题汇总.xlsx)
- [附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx)
- [outputs/task1/task1_financials.db](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task1/task1_financials.db)

其中数据库会在运行时拼成统一宽表视图：

- `financials_view`

---

## 2.1 最新运行状态

当前任务二正式输出目录为：

- [outputs/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task2_langgraph)

正式结果文件：

- [result_2.xlsx](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task2_langgraph/result_2.xlsx)
- [task2_langgraph_results.csv](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task2_langgraph/artifacts/task2_langgraph_results.csv)
- [task2_langgraph_summary.json](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task2_langgraph/artifacts/task2_langgraph_summary.json)
- [任务二建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务二建模与求解（论文版）.md)

最近一轮正式结果已经做到：

- `70` 题全部导出非空回答
- 当前 summary 为：
  - `ok = 69`
  - `warning = 1`
  - `error = 0`

当前仅剩的 `warning` 为：

- `B1063`

其原因不是 SQL bug 或回答链路失败，而是任务一数据库当前仅有 `1` 家公司同时具备 `2022Q3 / 2023Q3 / 2024Q3 / 2025Q3` 的完整可比营业总收入数据，因此无法形成题目要求的行业复合增长率分布直方图。

最近这轮收口后，已经补齐的典型问题包括：

1. `B1008 / B1015 / B1039`
   - 空结果不再一律报 warning，而是输出“数据库当前无符合条件记录”的有效回答。
2. `B1034`
   - 补齐 `Q2 / Q4` 单季度派生逻辑，并修正 `Q3` 环比必须使用“单季度值”而非累计值。
3. `B1043`
   - 用 SQLite 兼容的窗口函数中位数写法替代 `PERCENTILE_CONT`。
4. `B1046`
   - 第二问不再只给数量，能够列出两家公司名称及资产负债率。
5. `B1066 / B1069`
   - 多轮澄清与回答收口更自然，不再出现前一问完全失焦、后一问单独作答的割裂感。

从方法层面看，这轮任务二优化不仅是代码逻辑修补，也包括提示词体系重构：

1. `query_plan` 提示词负责把自然语言约束收敛到标准槽位；
2. `sql_generation` 提示词负责把 SQL 生成限制在 SQLite 与财务口径可接受范围内；
3. `clarification` 提示词负责最小化追问成本；
4. `answer_generation` 提示词负责保证回答“只基于结果、尽量列全关键字段”。

这些提示词优化已经写入论文稿：

- [任务二建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务二建模与求解（论文版）.md)

---

## 3. 当前核心架构

任务二采用：

- `LangGraph + LLM-only + chart_spec`

单题主链为：

`parse -> clarify -> query_plan -> SQL -> execute -> chart_plan -> chart_spec -> renderer -> answer -> export`

其中特别重要的设计有：

### 3.1 多轮状态继承

系统会保留：

- `context_companies`
- `context_rows`
- `turn_answers`

用于处理：

- “这些公司”
- “上述企业”
- “其中哪家”

### 3.2 SQL 自修复

`generate_sql -> execute_sql` 之间带最多 3 次自动修复回路，能够处理：

- 字段名错误
- 时间口径错误
- 结果过少
- 结果全空

### 3.3 图表三层链

任务二当前不是让 LLM 直接绘图，而是：

`chart_plan -> chart_spec -> renderer`

这套结构后续也为任务三图表链提供了参考。

### 3.4 提示词分层

任务二当前不把提示词当作外围配置，而是把它们视为系统方法的一部分。现有提示词分为四层：

1. `query_plan_system.txt`
2. `sql_generation_system.txt`
3. `clarification_system.txt`
4. `answer_generation_system.txt`

四层分别承担“槽位归一”“安全 SQL 生成”“追问补槽”和“结果约束表达”的职责。这样做的直接好处是：不同节点的优化目标不会相互污染，例如不会让回答生成阶段反过来干扰 SQL 约束，也不会让 SQL 生成阶段承担过多自然语言修辞任务。

---

## 4. 当前重点与边界

当前任务二已经属于：

- **框架成熟**
- **主链可用**

但还需要继续收口：

1. 少数题型的图表表达
2. 个别多轮问题第一问的承接式回答风格
3. 行业分布题对底层覆盖不足的解释方式
4. 任务一数据覆盖边界导致的少量无解题

当前暂不把性能优化作为主线，性能问题已记为后续待办。

---

## 5. 常用命令

### 单题调试

```bash
python3 run_task2_langgraph.py --question-id B1006
```

### 按题号批量运行

```bash
python3 run_task2_langgraph.py --question-ids B1001,B1006,B1048
```

### 全量运行

```bash
python3 run_task2_langgraph.py
```

### 使用自定义测试题集

```bash
python3 run_task2_langgraph.py \
  --question-file "正式数据/测试集/任务二问题汇总.xlsx" \
  --output-dir "outputs/testsets/task2_langgraph"
```


---

## 6. 关键文件

- 主入口：
  - [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task2_langgraph.py)
- 配置：
  - [src/task2_langgraph/config/settings.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/config/settings.py)
- 解析器：
  - [src/task2_langgraph/services/parser.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/services/parser.py)
- 运行时：
  - [src/task2_langgraph/tools/runtime.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/tools/runtime.py)
- 图表：
  - [src/task2_langgraph/tools/charts.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/tools/charts.py)
  - [src/task2_langgraph/tools/chart_spec.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/tools/chart_spec.py)
- 节点：
  - [src/task2_langgraph/nodes/workflow.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph/nodes/workflow.py)

---

## 7. 当前判断

**任务二当前已经达到可正式提交状态。**

当前后续工作的重点不是继续搭框架，而是：

- 回归
- Prompt 调优
- 图表策略收口
- 与任务一脏数据的联动修正

另外，任务二中已经验证有效的通用优化，当前也已同步到任务三的重复模块中，主要包括：

- 指标映射补全；
- `metric` 缺失识别增强；
- `Q2 / Q4` 派生单季度逻辑；
- SQL 提示词中的 SQLite 和季度口径约束；
- 澄清回退模板。
