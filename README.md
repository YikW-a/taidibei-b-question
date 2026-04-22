# 泰迪杯 B 题项目总览

本项目当前按三条主线组织：

1. **任务一**：财报 PDF 抽取、标准化、校验、入库与评估
2. **任务二**：基于任务一数据库的 LangGraph 智能问数
3. **任务三**：基于研报知识库与任务一数据库的 `RAG + SQL + LangGraph` 增强分析

当前 README 以仓库里**现有文件和目录**为准，不再引用已删除的测试分支或旧文档。

---

## 当前项目结构

```text
.
├── README.md
├── README_task1.md
├── README_task2_langgraph.md
├── README_task3_langgraph.md
├── requirements.txt
├── run_task1.py
├── run_task2_langgraph.py
├── run_task3_index.py
├── run_task3_langgraph.py
├── run_test_question_sets.py
├── configs/
├── docs/
│   └── 任务一建模与求解（论文版）.md
├── outputs/
├── scripts/
├── src/
│   ├── task1_pipeline/
│   ├── task2_langgraph/
│   └── task3_langgraph/
└── 正式数据/
```

---

## 目录说明

### 根目录入口

- [run_task1.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task1.py)：任务一主入口
- [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task2_langgraph.py)：任务二主入口
- [run_task3_index.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_index.py)：任务三知识库构建入口
- [run_task3_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_langgraph.py)：任务三回答入口
- [run_test_question_sets.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_test_question_sets.py)：任务二、任务三统一测试入口

### `src/`

- [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)：任务一主线代码
- [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)：任务二主线代码
- [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph)：任务三主线代码

### `scripts/`

当前保留的脚本主要用于任务一预处理、导表和勾稽校验：

- [scripts/process_sse_reports.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/process_sse_reports.py)
- [scripts/process_szse_reports.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/process_szse_reports.py)
- [scripts/export_task1_final_tables.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/export_task1_final_tables.py)
- [scripts/check_task1_accounting_consistency.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/check_task1_accounting_consistency.py)
- [scripts/task1_env.sh](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/scripts/task1_env.sh)

### `configs/`

- `task2_llm.env.example`
- `task3_llm.env.example`

本地实际使用时通常复制为：

```bash
cp configs/task2_llm.env.example configs/task2_llm.env
cp configs/task3_llm.env.example configs/task3_llm.env
```

### `docs/`

当前保留的论文稿包括：

- [任务一建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务一建模与求解（论文版）.md)
- [任务二建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务二建模与求解（论文版）.md)

其中任务二论文已补充：

- `LangGraph` 状态图流程
- 提示词分层设计
- SQLite 兼容 SQL 约束
- 季度口径派生公式
- 从 `61 ok / 9 warning` 到 `69 ok / 1 warning` 的优化收口

### `outputs/`

运行产物统一放在这里。当前目录下已经存在：

- `outputs/task1`

任务二、任务三及测试集结果也会默认写到 `outputs/` 下的对应子目录。

### `正式数据/`

比赛附件与原始数据放在这里，当前可见的主目录包括：

- `附件2：财务报告`
- `附件5：研报数据`

---

## 当前实现状态

### 任务一

- 当前仅保留主线实现，不再保留 `task1_test / outputs_test`
- 主代码目录：
  - [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)
- 详细说明：
  - [README_task1.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task1.md)

### 任务二

- 主代码目录：
  - [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)
- 正式输出目录：
  - [outputs/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task2_langgraph)
- 当前正式结果：
  - `70` 题
  - `69 ok / 1 warning / 0 error`
- 当前方法关键词：
  - `LangGraph + 分层提示词 + 确定性 SQL 模板 + chart_spec`
- 详细说明：
  - [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task2_langgraph.md)

### 任务三

- 主代码目录：
  - [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph)
- 已同步任务二的部分通用优化：
  - 指标映射补全
  - `metric` 缺失识别增强
  - `Q2 / Q4` 派生单季度逻辑
  - SQL 提示词中的 SQLite / 季度口径约束
  - 澄清回退模板
- 详细说明：
  - [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task3_langgraph.md)

---

## 推荐运行方式

### 安装依赖

```bash
pip install -r requirements.txt
```

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

### 统一测试入口

```bash
python3 run_test_question_sets.py
```

---

## 协作约定

建议提交到仓库的内容：

- `src/`
- `scripts/`
- `configs/*.example`
- 各任务 README
- `docs/` 中仍保留的论文与说明文档

通常不提交：

- `正式数据/`
- `outputs/`
- 本地 `.env`
- 本地数据库
- 缓存目录与 `__pycache__`

---

## 阅读顺序

建议按下面顺序接手：

1. [README_task1.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task1.md)
2. [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task2_langgraph.md)
3. [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task3_langgraph.md)
4. [任务一建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务一建模与求解（论文版）.md)
5. [任务二建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务二建模与求解（论文版）.md)
