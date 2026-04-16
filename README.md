# 泰迪杯 B 题项目总览

本项目对应竞赛 B 题，当前主线已经统一到三套模块：

1. 任务一：财报 PDF 抽取、清洗、校验、入库与质量评估
2. 任务二：基于任务一数据库的 LangGraph 多轮智能问数
3. 任务三：基于研报知识库与任务一数据库的 `RAG + SQL + LangGraph` 增强分析

当前项目已经不再维护旧版任务二普通流水线，任务二主实现为 `task2_langgraph`，任务三主实现为 `task3_langgraph`。

## 目录入口

- 任务一说明：
  - [README_task1.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task1.md)
- 任务二说明：
  - [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task2_langgraph.md)
- 任务三说明：
  - [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task3_langgraph.md)
- 新环境交接文档：
  - [PROJECT_HANDOFF_PROMPT.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/PROJECT_HANDOFF_PROMPT.md)

## 当前推荐使用的入口

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

## 当前项目状态

### 任务一

- 框架已完成
- 当前处于提质阶段
- 重点在：
  - 字段来源约束
  - 提取流程优化
  - 异常值治理
  - 数据库质量复核

### 任务二

- `LangGraph + LLM-only + chart_spec` 主链已成型
- 当前重点是：
  - 小批量回归
  - Prompt 调优
  - 图表策略调优
  - 澄清门控收口

### 任务三

- 数据准备层已基本搭好：
  - 附件 5 metadata
  - 字段说明接入
  - PDF 正文抽取
  - 标题/段落优先 chunk
  - `bge-m3`
  - `FAISS`
- 小样本回答链已跑通
- 当前重点是：
  - 检索质量
  - SQL 与证据融合
  - `references` 精度
  - 后续图表链

## 技术栈

- Python
- pandas
- PyMuPDF / pdfplumber / camelot
- SQLAlchemy
- SQLite / MySQL
- LangChain
- LangGraph
- OpenAI 兼容 LLM API
- OpenAI 兼容 Embedding API
- `BAAI/bge-m3`
- FAISS
- matplotlib
- openpyxl

## 依赖安装

建议直接使用项目根目录依赖：

```bash
pip install -r requirements.txt
```

## 配置说明

本地配置文件模板：

- `configs/task2_llm.env.example`
- `configs/task3_llm.env.example`

实际使用时建议复制为本地文件后填写：

```bash
cp configs/task2_llm.env.example configs/task2_llm.env
cp configs/task3_llm.env.example configs/task3_llm.env
```

这些本地配置文件已被 `.gitignore` 忽略，不会提交到仓库。

## 版本管理建议

当前仓库建议只提交：

- 源代码
- 脚本
- 文档
- 配置模板

默认不提交：

- `正式数据/`
- `outputs/`
- 本地 `.env`
- 本地数据库
- 缓存目录

## 换环境接手顺序

建议新环境中的 Codex 或开发者按以下顺序阅读：

1. [PROJECT_HANDOFF_PROMPT.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/PROJECT_HANDOFF_PROMPT.md)
2. [README_task1.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task1.md)
3. [README_task2_langgraph.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task2_langgraph.md)
4. [README_task3_langgraph.md](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task3_langgraph.md)

然后再根据当前工作重点进入具体任务模块。
