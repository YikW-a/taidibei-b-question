# 泰迪杯 B 题项目总览

本项目面向竞赛 B 题，当前已形成三段式主线：

1. **任务一**：财报 PDF 抽取、清洗、校验、入库与质量评估
2. **任务二**：基于任务一数据库的 LangGraph 多轮智能问数
3. **任务三**：基于研报知识库与任务一数据库的 `RAG + SQL + LangGraph` 增强分析

当前仓库已经不再保留旧版任务二普通流水线，任务二主实现为：

- [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)

任务三主实现为：

- [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph)

---

## 项目文档

- 总交接文档：
  - [PROJECT_HANDOFF_PROMPT.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/PROJECT_HANDOFF_PROMPT.md)
- 任务一说明：
  - [README_task1.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task1.md)
- 任务二说明：
  - [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task2_langgraph.md)
- 任务三说明：
  - [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task3_langgraph.md)
- 论文原稿 PDF：
  - [docs/document.pdf](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/document.pdf)
- 融合后的论文完整版：
  - [docs/论文完整版.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/论文完整版.md)

---

## 当前状态

### 任务一

- 当前任务一仅保留主线实现：
  - [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)
- 测试支线已经并回主线，不再保留 `task1_test / outputs_test`
- 已完成财报目录预处理、PDF 抽取、字段映射、单位统一、跨表补值、异常值清洗、SQLite/MySQL 入库、质量评估与会计勾稽校验
- 当前主线版本已形成较稳定的数据底座，重点转为：
  - 长尾版式治理
  - 核心指标口径收口
  - 现金流尾部勾稽
  - 数据库质量复核

### 任务二

- 主架构已稳定迁移到 `LangGraph + LLM-only + chart_spec`
- 已接通：
  - 多轮解析
  - 澄清门控
  - `query_plan -> SQL -> answer`
  - `chart_plan -> chart_spec -> renderer`
  - `result_2.xlsx` 导出
- 当前全量结果已做到：
  - `70` 题全部有非空回答
  - 仍有少量 `warning` 题需要继续做图表与复杂 SQL 质量收口
- 最近新增与修复：
  - 统一测试集入口支持自定义题库路径
  - 运行异常时自动补结构化兜底答案，避免导出空白
  - 针对散点图题补了本地图表链支持，避免被错误降成表格
- 当前重点：
  - 小批量回归
  - Prompt 调优
  - 图表策略收口
  - 澄清门控收敛

### 任务三

- 数据准备层已完成：
  - 附件 5 metadata / 字段说明接入
  - PDF 正文抽取
  - 标题/段落优先 chunk
  - `bge-m3`
  - `FAISS`
- 回答主链已接通：
  - `SQL + RAG + rerank + answer + self_check + references`
- 图表链已接入，并且**已独立于 task2**
- 最新全量运行结果：
  - `80` 题已全部导出非空回答
  - 当前主链可稳定跑通，知识库状态为 `ready`
- `references.paper_image` 已在真实结果中命中，不再是空功能
- 最近新增与修复：
  - 统一测试集入口支持复用现有知识库
  - `paper_image` 会优先保留 1 条图表类证据
  - 题型路由进一步细分为 `sql_only / sql_chart / causal_analysis / industry_open_analysis / hybrid_sql_rag`
  - 对 `B2007/B2009` 这类多轮题补了相对期间解析和别名映射
- 当前已达到“**可初步提交，仍需继续收口**”阶段

---

## 推荐入口

### 任务一

```bash
python3 run_task1.py
```

### 任务二

```bash
python3 run_task2_langgraph.py
```

### 任务三建库

```bash
python3 run_task3_index.py
```

### 任务三回答

```bash
python3 run_task3_langgraph.py
```

### 统一测试集入口

```bash
python3 run_test_question_sets.py
```

---

## 测试集使用方式

当比赛方给出新的测试问题表格时，建议放到：

- `正式数据/测试集/任务二问题汇总.xlsx`
- `正式数据/测试集/任务三问题汇总.xlsx`

统一测试入口会默认读取这两个文件，并把结果输出到：

- `outputs/testsets/task2_langgraph`
- `outputs/testsets/task3_langgraph`

其中：

- 任务二输出主文件：
  - `outputs/testsets/task2_langgraph/result_2.xlsx`
- 任务三输出主文件：
  - `outputs/testsets/task3_langgraph/result_3.xlsx`

### 统一联跑

```bash
python3 run_test_question_sets.py
```

### 只跑任务二

```bash
python3 run_test_question_sets.py --skip-task3
```

### 只跑任务三

```bash
python3 run_test_question_sets.py --skip-task2
```

### 自定义测试题文件路径

```bash
python3 run_test_question_sets.py \
  --task2-question-file /path/to/task2.xlsx \
  --task3-question-file /path/to/task3.xlsx
```

### 任务三测试前的注意事项

任务三统一测试入口默认会复用已经构建好的知识库目录：

- `outputs/task3_langgraph`

也就是说，在跑测试集前，建议先确认已经完成过：

```bash
python3 run_task3_index.py \
  --embedding-batch-size 64 \
  --embedding-batch-pause-seconds 1
```

如果你想让测试输出和正式输出完全隔离，同时继续复用知识库，统一入口已经默认这么做了，不需要再手动改代码。

---

## 环境与依赖

建议使用项目根目录依赖：

```bash
pip install -r requirements.txt
```

本地配置模板：

- `configs/task2_llm.env.example`
- `configs/task3_llm.env.example`

使用前可复制：

```bash
cp configs/task2_llm.env.example configs/task2_llm.env
cp configs/task3_llm.env.example configs/task3_llm.env
```

这些本地配置文件已被 `.gitignore` 忽略。

---

## 仓库协作建议

建议提交到 Git 的内容：

- 源代码
- 脚本
- README / 交接文档
- 配置模板
- 论文原稿与论文完整版

默认不提交：

- `正式数据/`
- `outputs/`
- 本地 `.env`
- 本地数据库
- 各类缓存

---

## 换环境接手顺序

建议在新环境中按以下顺序阅读：

1. [PROJECT_HANDOFF_PROMPT.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/PROJECT_HANDOFF_PROMPT.md)
2. [README_task1.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task1.md)
3. [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task2_langgraph.md)
4. [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task3_langgraph.md)
5. [docs/论文完整版.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/论文完整版.md)
