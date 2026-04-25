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
├── run_task1_test.py
├── run_task2_langgraph.py
├── run_task2_langgraph_test.py
├── run_task3_index.py
├── run_task3_index_test.py
├── run_task3_langgraph.py
├── run_task3_langgraph_test.py
├── run_web_assistant.py
├── configs/
├── docs/
│   ├── 任务一建模与求解（论文版）.md
│   ├── 任务二建模与求解（论文版）.md
│   └── 任务三建模与求解（论文版）.md
├── outputs/
├── outputs_test/
├── scripts/
├── src/
│   ├── task1_pipeline/
│   ├── task2_langgraph/
│   └── task3_langgraph/
├── src_test/
│   ├── task1_pipeline/
│   ├── task2_langgraph/
│   └── task3_langgraph/
├── 正式数据/
└── 测试数据/
```

---

## 目录说明

### 根目录入口

- [run_task1.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task1.py)：任务一主入口
- [run_task1_test.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task1_test.py)：任务一测试数据入口
- [run_task2_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task2_langgraph.py)：任务二主入口
- [run_task2_langgraph_test.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task2_langgraph_test.py)：任务二测试数据入口
- [run_task3_index.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_index.py)：任务三知识库构建入口
- [run_task3_index_test.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_index_test.py)：任务三测试数据建库入口
- [run_task3_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_langgraph.py)：任务三回答入口
- [run_task3_langgraph_test.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_langgraph_test.py)：任务三测试数据回答入口
- [run_web_assistant.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_web_assistant.py)：上市公司财报“智能问数”助手网页入口

### `src/`

- [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)：任务一主线代码
- [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)：任务二主线代码
- [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph)：任务三主线代码
- [src/web_assistant](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/web_assistant)：独立网页问答界面，复用任务三后端逻辑，不改动三项任务主线代码
- [src_test](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src_test)：测试数据专用包装层，默认读取 `测试数据/`，默认输出到 `outputs_test/`，不改动主线 `src/`

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
- [任务三建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务三建模与求解（论文版）.md)

其中任务二论文已补充：

- `LangGraph` 状态图流程
- 提示词分层设计
- SQLite 兼容 SQL 约束
- 季度口径派生公式
- 从 `61 ok / 9 warning` 到 `69 ok / 1 warning` 的优化收口

任务三论文当前补充：

- `RAG + SQL + LangGraph` 的统一状态图
- 研报知识库构建与混合检索
- 提示词工程分层设计
- SQLite 修复、边界收口与回答自检
- 最终 `80 ok / 0 error` 的结果收口

### `outputs/`

运行产物统一放在这里。当前目录下已经存在：

- `outputs/task1`
- `outputs/task2_langgraph`
- `outputs/task3_langgraph`
- `outputs_test/`

其中：

- `outputs/task1`：任务一正式版结果
- `outputs/task2_langgraph`：任务二正式版结果
- `outputs/task3_langgraph`：任务三正式版结果与知识库产物
- `outputs_test`：测试数据独立运行产物，不污染正式版结果

### `正式数据/`

比赛附件与原始数据放在这里，当前可见的主目录包括：

- `附件2：财务报告`
- `附件5：研报数据`

### `测试数据/`

测试数据与正式数据保持相同附件框架，但内容独立，用于单独建库和问答：

- `附件1：医药上市公司基本信息（截至到2026年1月13日）.xlsx`
- `附件2：财务报告`
- `附件4：问题汇总.xlsx`
- `附件5：研报数据`
- `附件6：问题汇总.xlsx`

---

## 当前实现状态

### 任务一

- 当前保留主线实现，并新增 `src_test/task1_pipeline` 作为测试数据专用包装层
- 主代码目录：
  - [src/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task1_pipeline)
- 测试代码目录：
  - [src_test/task1_pipeline](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src_test/task1_pipeline)
- 详细说明：
  - [README_task1.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/README_task1.md)

### 任务二

- 主代码目录：
  - [src/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task2_langgraph)
- 测试代码目录：
  - [src_test/task2_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src_test/task2_langgraph)
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
- 测试代码目录：
  - [src_test/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src_test/task3_langgraph)
- 正式输出目录：
  - [outputs/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task3_langgraph)
- 当前正式结果：
  - `80` 题
  - `80 ok / 0 error`
- 当前方法关键词：
  - `RAG + SQL + LangGraph + 分层提示词 + 混合检索 + chart_spec`
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

### 网页问答助手

```bash
python3 run_web_assistant.py
```

启动后会自动打开浏览器，也可以手动访问：

```text
http://127.0.0.1:8765
```

网页名称为“上市公司财报“智能问数”助手”，包含问题输入框、回答框和图片框。后端复用任务三的 `RAG + SQL + LangGraph` 逻辑，支持连续追问；若生成图表，图片会展示在图片框；若存在研报引用，会跟随每轮回答展示在回答框下方，并以“研报标题”和“引用图表”的形式呈现。页面提供“新会话”和“结束服务”按钮，并通过前端心跳检测在网页关闭后自动释放本地端口；回答框会展示本轮回答时间。

如只希望启动服务而不自动打开浏览器：

```bash
python3 run_web_assistant.py --no-open
```

### 测试数据独立运行

测试分支默认：

- 代码目录：`src_test/`
- 输入目录：`测试数据/`
- 输出目录：`outputs_test/`

推荐运行顺序如下。

#### 测试数据任务一

```bash
python3 run_task1_test.py
```

该入口会先根据 `测试数据/附件2：财务报告` 自动生成测试版 manifest，再写入：

- `outputs_test/task1/task1_financials.db`
- `outputs_test/task1/final_tables/`

#### 测试数据任务二

```bash
python3 run_task2_langgraph_test.py
```

默认读取：

- `测试数据/附件4：问题汇总.xlsx`
- `测试数据/附件1：医药上市公司基本信息（截至到2026年1月13日）.xlsx`
- `outputs_test/task1/task1_financials.db`

#### 测试数据任务三建库

```bash
python3 run_task3_index_test.py
```

默认读取：

- `测试数据/附件5：研报数据/医疗服务_个股_研报信息.xlsx`
- `测试数据/附件5：研报数据/医疗服务_行业_研报信息.xlsx`
- `测试数据/附件5：研报数据/个股研报`
- `测试数据/附件5：研报数据/行业研报`
- `outputs_test/task1/task1_financials.db`

知识库与索引写入：

- `outputs_test/task3_langgraph/artifacts/`

#### 测试数据任务三回答

```bash
python3 run_task3_langgraph_test.py
```

默认读取：

- `测试数据/附件6：问题汇总.xlsx`
- `outputs_test/task1/task1_financials.db`
- `outputs_test/task3_langgraph/artifacts/`

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
6. [任务三建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务三建模与求解（论文版）.md)
