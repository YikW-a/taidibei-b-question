# 任务二 LangGraph 使用说明

## 1. 模块定位

任务二当前主实现为：

- [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph)

它已经完全替代旧版普通任务二实现，当前仓库只保留 LangGraph 版本。

主入口：

- [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task2_langgraph.py)

任务二当前已经完成从“脚本化问数”到“**显式状态图工作流**”的迁移，现阶段重点不再是重构架构，而是：

- 小样本回归
- Prompt 调优
- 图表策略收口
- 澄清门控收敛

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

- [附件4：问题汇总.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/正式数据/附件4：问题汇总.xlsx)
- [附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/正式数据/附件1：中药上市公司基本信息（截至到2025年12月22日）.xlsx)
- [outputs/task1/task1_financials.db](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task1/task1_financials.db)

其中数据库会在运行时拼成统一宽表视图：

- `financials_view`

---

## 2.1 最新运行状态

最近一轮 task2 全量结果已经做到：

- `70` 题全部导出非空回答
- 当前 summary 为：
  - `ok = 61`
  - `warning = 9`
  - `error = 0`

也就是说，任务二现在的主要问题已经不是“跑不出来”或“空白结果”，而是：

- 少量复杂题的图表类型不够理想
- 个别复杂 SQL / 解释型回答仍需收口

最近还补了两类工程兜底：

1. 运行异常自动补结构化答案，避免导出空白
2. 图表节点和回答节点失败时自动降级，不再整题炸掉

另外，针对 `B1057` 这类题，最近补了：

- 散点图 chart plan / chart spec / renderer 支持
- 避免被错误退化成表格

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

---

## 4. 当前重点与边界

当前任务二已经属于：

- **框架成熟**
- **主链可用**

但还需要继续收口：

1. 少数题型的图表表达
2. 澄清门控过宽 / 过窄
3. 个别回答完整性兜底
4. 任务一脏数据导致的异常结果

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

### 使用统一测试入口

```bash
python3 run_test_question_sets.py --skip-task3
```

---

## 6. 关键文件

- 主入口：
  - [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task2_langgraph.py)
- 配置：
  - [src/task2_langgraph/config/settings.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/config/settings.py)
- 解析器：
  - [src/task2_langgraph/services/parser.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/services/parser.py)
- 运行时：
  - [src/task2_langgraph/tools/runtime.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/runtime.py)
- 图表：
  - [src/task2_langgraph/tools/charts.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/charts.py)
  - [src/task2_langgraph/tools/chart_spec.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/tools/chart_spec.py)
- 节点：
  - [src/task2_langgraph/nodes/workflow.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph/nodes/workflow.py)

---

## 7. 当前判断

**任务二已经达到可初步提交状态。**

当前后续工作的重点不是继续搭框架，而是：

- 回归
- Prompt 调优
- 图表策略收口
- 与任务一脏数据的联动修正
