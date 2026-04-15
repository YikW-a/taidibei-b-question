# 项目交接 Prompt（新环境 Codex 使用）

你正在接手一个数学建模竞赛项目，项目目录为：

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题`

请先阅读并理解本文件，再结合：

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task1.md`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task2_langgraph.md`

继续后续工作。

---

## 1. 项目目标

本项目对应竞赛 B 题，整体分为三个任务：

1. 任务一：从财务报告 PDF 中抽取四张目标表，完成字段映射、单位统一、自动校验、入库与质量评估。
2. 任务二：基于任务一数据库做多轮智能问数，支持澄清、SQL 生成、图表输出，并按赛题要求导出 `result_2.xlsx`。
3. 任务三：后续要做研报增强分析，预计采用 `RAG + SQL + LangGraph`。

当前工作重点仍集中在任务一和任务二。

---

## 2. 当前进度

### 2.1 任务一

任务一工程已经建立完成，包含：

- 财报清单预处理
- PDF 抽取
- 字段映射与单位统一
- 跨表补值与派生字段
- 入库前异常值清洗
- 数据一致性校验
- 数据库质量复核
- SQLite / MySQL 入库
- 最终表导出
- 评估报告与论文材料输出

当前任务一已经进入“提质阶段”，重点不是重建框架，而是：

1. 按附件 3 明确字段的直读、复用、推导关系
2. 优化提取阶段，减少错列、错页、错值
3. 回头修会污染任务二的异常金额值与异常比例值
4. 继续提升 `balance_sheet` 与 KPI 表的稳定性

### 2.2 任务二

任务二已从旧版平铺流程迁移到：

- `LangGraph + LLM-only + chart_spec 驱动渲染`

当前 `src/task2_langgraph` 是任务二主架构，包含：

- 多轮问题解析
- 澄清门控
- `query_plan -> SQL -> answer`
- `chart_plan -> chart_spec -> renderer`
- `result_2.xlsx` 导出
- `debug/*.json` 与 `chart_specs/*.spec.json` 调试落盘

当前任务二已经可以批量运行，但还在“效果调优”阶段，主要继续做：

1. Prompt 调优
2. 图表策略调优
3. 澄清门控收敛
4. 任务一脏数据导致的问题回溯

---

## 3. 当前正在做什么

### 任务一正在做的事

当前需要继续验证和优化：

1. `operating_revenue_qoq_growth`
2. `net_profit_qoq_growth`

这两个字段不是必须完全依赖 PDF 直读，而是应该根据同公司同年份不同报告期的累计口径进行还原后再计算。

同时需要继续关注：

- `balance_sheet` 横向空缺较多的问题
- 个别异常营收值、异常毛利率、异常净利率、异常 ROE
- 现金流占比异常

### 任务二正在做的事

任务二当前不是继续重构架构，而是：

1. 小批量回归
2. 看 `artifacts/debug/*.json`
3. 调 `prompts/*.txt`
4. 优先通过通用规则而不是题号特判解决问题

---

## 4. 技术栈

### 任务一

- Python
- pandas
- PyMuPDF
- pdfplumber
- camelot
- SQLAlchemy
- SQLite / MySQL
- openpyxl
- matplotlib

### 任务二

- Python
- LangGraph
- LangChain
- OpenAI 兼容 LLM API
- SQLite（读取任务一数据库）
- pandas
- matplotlib
- 自定义 `chart_spec` 渲染链路

---

## 5. 关键约束

1. 任务一四张最终表必须严格按附件 3 的字段顺序导出。
2. 任务二必须读取数据库，不是直接读 Excel 财务数据。
3. 任务二输出要符合赛题格式：
   - 图片放在 `result/`
   - 文件命名为 `问题编号_顺序号.jpg`
   - 提交文件为 `result_2.xlsx`
4. 任务二现在走 `LLM-only` 路线，不再保留旧版 `template` 模式。
5. 任务二后续优化应优先做：
   - Prompt 调优
   - 通用规则优化
   - 图表策略调整
   而不是按题号硬编码特判。
6. 任务一的异常值会直接污染任务二，所以若任务二结果明显异常，应优先回查任务一数据层。

---

## 6. 已完成的工作

### 任务一已完成

- SSE/SZSE 目录预处理脚本
- 财报 PDF 抽取主流程
- 附件 3 schema 落地
- 最终四张表导出
- 自动校验与一致性预校验
- 数据库质量复核
- 会计勾稽校验脚本
- README、论文材料、评估报告

### 任务二已完成

- `task2_langgraph` 独立模块化重构
- LangGraph 状态流
- 多轮澄清
- SQL 自动修复重试
- 图表 `chart_spec` 驱动渲染
- 小批量调试链路
- `result_2.xlsx` 正式导出
- 两个 README 已整理

---

## 7. 待完成的工作

### 任务一

1. 继续验证并提高 `qoq` 字段非空率
2. 继续降低 `balance_sheet` 横向空缺
3. 收紧异常金额和异常比例值治理
4. 继续优化提取层候选表质量评分

### 任务二

1. 继续全量 70 题效果回归
2. 优化图表策略，减少不必要的表格图或错误图
3. 收敛澄清门控
4. 提高回答完整性

### 任务三

尚未正式开始，计划后续采用：

- `RAG + SQL + LangGraph`

---

## 8. 当前已知问题与边界

### 任务一

- 某些极端金额值、极端比例值更像提取错位，不应直接当真值使用
- `balance_sheet` 缺失和 `cash_flow_sheet` 勾稽问题仍是重点
- `qoq` 逻辑已接入，但需要用最新代码全量重跑后再正式评估

### 任务二

- 个别题型仍会出现图表表达不理想
- 少量题会因为任务一脏数据出现异常均值或异常排序
- 部分复杂问题更适合继续调 `query_plan / answer / chart_plan` prompt，而不是补特判

---

## 9. 关键文件

### 任务一

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task1.py`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task1_pipeline`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task1.md`

### 任务二

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task2_langgraph.py`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_langgraph`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task2_langgraph.md`

### 调试重点目录

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task1`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/debug`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/chart_specs`

---

## 10. 新环境接手建议

进入新环境后建议按下面顺序：

1. 先阅读：
   - `README_task1.md`
   - `README_task2_langgraph.md`
   - 本文件
2. 安装依赖：
   - `pip install -r requirements.txt`
3. 检查任务一数据库是否存在：
   - `outputs/task1/task1_financials.db`
4. 检查任务二 LLM 配置：
   - `configs/task2_llm.env`
5. 先跑单题 / 小样本再跑全量
6. 如遇异常，优先看：
   - 任务一：`summary.json / validation_log.csv / database_quality_review.md`
   - 任务二：`result_2.xlsx / debug/*.json / chart_specs/*.spec.json`

---

## 11. 希望 Codex 后续遵循的工作方式

1. 优先保持当前框架，不轻易重构主流程。
2. 任务一优先优化提取质量、字段来源约束和异常值治理。
3. 任务二优先做小批量回归和 Prompt 调优。
4. 若任务二出现异常问答，优先判断：
   - 是任务一数据问题
   - 还是任务二解析 / SQL / 图表 / 回答问题
5. 避免按题号硬编码，优先做通用规则。
