# 项目交接 Prompt（新环境 Codex 使用）

你正在接手一个数学建模竞赛项目，项目目录为：

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题`

请先阅读并理解本文件，再结合：

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task1.md`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task2_langgraph.md`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task3_langgraph.md`

继续后续工作。

---

## 1. 项目目标

本项目对应竞赛 B 题，整体分为三个任务：

1. 任务一：从财务报告 PDF 中抽取四张目标表，完成字段映射、单位统一、自动校验、入库与质量评估。
2. 任务二：基于任务一数据库做多轮智能问数，支持澄清、SQL 生成、图表输出，并按赛题要求导出 `result_2.xlsx`。
3. 任务三：基于研报知识库与任务一数据库，完成 `RAG + SQL + LangGraph` 的增强分析问答。

当前工作重点已经扩展到任务三骨架搭建，但整体优先级仍是：

1. 任务一保证数据底座质量
2. 任务二保证数据库问数链稳定
3. 任务三在此基础上完成 `RAG + SQL` 融合链

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

### 2.3 任务三

任务三主模块已经建立：

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph`

并且已拆分为两个入口：

- 建库入口：`/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_index.py`
- 回答入口：`/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_langgraph.py`

当前任务三已经完成：

1. 附件 5 研报信息表和字段说明接入
2. PDF 正文抽取
3. 标题/段落优先 chunk 切分
4. 图表/表格引用基础字段准备
5. `bge-m3` embedding 接入
6. 真正的 `FAISS` 向量索引
7. `metadata / vector / hybrid` 检索底座
8. `retrieve -> rerank -> fuse -> answer -> self_check` 骨架
9. 3 到 5 题小样本回答冒烟已跑通
10. 全量知识库已 ready，当前：
   - `总 chunk = 12856`
   - `已建向量索引 chunk = 12856`
   - `index_status = ready`
11. 已完成一轮 `40` 题半量回归：
   - `total_questions = 40`
   - `ok_count = 40`
   - `error_count = 0`
12. `result_3.xlsx` 当前已收敛为 4 列：
   - `编号`
   - `问题`
   - `SQL 查询语句`
   - `回答`
13. `回答` 中 `A` 的字段顺序已固定为：
   - `content`
   - `image`
   - `references`
14. `references` 当前只保留：
   - `paper_path`
   - `text`
   - `paper_image`
   其中：
   - `paper_path` 使用相对路径
   - `paper_image` 只有命中图表/表格时才写，语义是“图表编号 + 标题”
15. task3 图表链现已正式接入，且**实现已独立于 task2**
    - 本地图表模块位于：
      - `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/charts.py`
      - `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/chart_spec.py`
    - 题目明确要求绘图/可视化时，会强制尝试生图
    - 生成图片路径会写入 `A.image`
16. 当前 task3 已引入更细的题型路由：
    - `sql_only`
    - `sql_chart`
    - `causal_analysis`
    - `industry_open_analysis`
    - `hybrid_sql_rag`
17. 当前 task3 已完成一轮性能收口：
    - planning 合并
    - SQL / retrieval 缓存
    - rerank / self_check / rewrite 触发范围收紧
    - 纯 SQL 题、纯图表题、单公司归因题更容易走短路径
    - 例如 `B2003` 单题耗时已从约 `181s` 压到约 `67s`
18. 当前 task3 已达到“可初步提交、仍需继续收口”的状态：
    - 主链可用
    - 输出结构已收敛
    - 后续重点不再是补骨架，而是全量质量回归、引用质量提纯、图表策略和性能继续收口

当前任务三已经从“纯骨架”进入“可用第一版”，但还处在小样本调优阶段，不是最终效果版。

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

### 任务三正在做的事

任务三当前不是继续补目录骨架，而是：

1. 先稳住数据准备层
   - chunk
   - metadata 标准化
   - `bge-m3`
   - `FAISS`
2. 跑小样本检索与小样本回答冒烟
3. 调整：
   - 澄清门控
   - SQL 与证据融合
   - `references` 结构
4. 之后再做全量调优
5. 当前已开始做性能治理：
   - query/retrieval plan 合并
   - SQL 缓存
   - retrieval 缓存
   - rerank / self_check / rewrite 触发条件收紧
6. 当前更推荐的推进方式是：
   - 先跑更大批次甚至全量
   - 再按真实耗时和失败题做定向收口
   - 不再优先继续补新模块

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

### 任务三

- Python
- LangGraph
- LangChain
- OpenAI 兼容 LLM API
- OpenAI 兼容 Embedding API
- `BAAI/bge-m3`
- FAISS (`faiss-cpu`)
- PyMuPDF
- pandas
- SQLite（复用任务一数据库）

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
7. 任务三当前默认使用：
   - LLM：OpenAI 兼容接口
   - Embedding：硅基流动 `BAAI/bge-m3`
8. 任务三知识库构建与回答流程已经拆分为两个入口：
   - `run_task3_index.py`
   - `run_task3_langgraph.py`
9. 任务三当前采用“纯文本抽取 + 结构化切分”，不是先转 markdown 再切 chunk。

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

### 任务三已完成

- `task3_langgraph` 独立模块搭建
- 两个入口拆分：
  - 建库入口
  - 回答入口
- 附件 5：
  - `个股_研报信息.xlsx`
  - `行业_研报信息.xlsx`
  - `字段说明.xlsx`
  已正式接入
- PDF 正文抽取与结构化 chunk
- `metadata_ref + report_metadata_lookup`
- `bge-m3` embedding 调用
- `FAISS IndexFlatIP`
- `metadata / vector / hybrid`
- `rerank` 骨架
- 小样本回答冒烟成功
- 半量 `40` 题回归成功（`40/40 ok`）
- `result_3.xlsx` 列结构已收敛为：
  - `编号`
  - `问题`
  - `SQL 查询语句`
  - `回答`
- `references` 结构已收敛为：
  - `paper_path`
  - `text`
  - `paper_image`
- task3 图表链已接入，且已独立于 task2
- 当前像 `B2003` 这类明确要求绘图的题，第一轮已能生成图片并写入 `A.image`

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
5. 性能优化暂记待办，后续单独推进

### 任务三

1. 继续小样本回答回归
2. 收紧澄清门控，避免完整条件问题被误追问
3. 改善 SQL 与证据融合质量，减少利润/营收等字段语义混淆
4. 继续提升 `references` 质量，尤其是：
   - 让更多题稳定命中有效引用
   - 让命中图表的题稳定输出 `paper_image = 图表编号 + 标题`
5. 继续观察复杂题运行速度，验证 fast path 是否真正生效
6. 继续优化 task3 图表策略与可视化覆盖范围

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

### 任务三

- 小样本回答链已经跑通，但效果仍需调优，不宜直接视为最终版。
- 当前 `references` 已有：
  - `paper_path`
  - `text`
  - `paper_image`
  其中 `paper_image` 的语义已经对齐为“命中的 PDF 图表/表格编号 + 标题”，但不是所有题都会命中图表。
- 当前 chunk 已是标题/段落优先切分，但仍不是最终章节级语义切分。
- 建库输出中的 `ready` 可能是“局部索引 ready”，需要结合本次 `--index-limit` 判断，不一定代表全量知识库都建完。
- 回答入口默认不会自动重建全量向量索引；如果要重建知识库，应使用 `run_task3_index.py`。
- 当前已经接入提速策略，但复杂题仍可能较慢。
  - 例如 `B2003` 单题实测约 `181s`
  - 因此 task3 目前属于“已开始提速，但还未完成最终性能收口”
- 当前 task3 图表链已经接入，但仍有边界：
  - 题目明确要求绘图时会强制尝试生图
  - 若当前数据不足、chart plan 无法落地、或结果不适合安全绘图，`A.image` 仍可能为空
- 当前有些题 `references` 为空是正常边界，而不是程序错误：
  - 附件 5 中没有对应公司的个股研报
  - 或当前问题更偏 SQL 且没有可靠研报证据
  - 例如 `B2056` 当前就是这种情况

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

### 任务三

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_index.py`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_langgraph.py`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/README_task3_langgraph.md`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/docs/task3/任务三完成流程与技术方案.md`

### 调试重点目录

- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task1`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/debug`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/chart_specs`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task3_langgraph`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task3_langgraph/artifacts/debug`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task3_langgraph/artifacts/retrieval`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task3_langgraph/artifacts/chunks`
- `/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task3_langgraph/artifacts/vector_store`

---

## 10. 新环境接手建议

进入新环境后建议按下面顺序：

1. 先阅读：
   - `README_task1.md`
   - `README_task2_langgraph.md`
   - `README_task3_langgraph.md`
   - 本文件
2. 安装依赖：
   - `pip install -r requirements.txt`
3. 检查任务一数据库是否存在：
   - `outputs/task1/task1_financials.db`
4. 检查任务二 / 任务三 LLM 配置：
   - `configs/task2_llm.env`
   - `configs/task3_llm.env`
5. 若要继续任务三，优先区分：
   - 建库：`run_task3_index.py`
   - 回答：`run_task3_langgraph.py`
6. 先跑单题 / 小样本再跑全量
7. 如遇异常，优先看：
   - 任务一：`summary.json / validation_log.csv / database_quality_review.md`
   - 任务二：`result_2.xlsx / debug/*.json / chart_specs/*.spec.json`
   - 任务三：`result_3.xlsx / debug/*.json / retrieval/*.json / chunks/report_chunks.json / vector_store/index_meta.json`

---

## 11. 希望 Codex 后续遵循的工作方式

1. 优先保持当前框架，不轻易重构主流程。
2. 任务一优先优化提取质量、字段来源约束和异常值治理。
3. 任务二优先做小批量回归和 Prompt 调优。
4. 任务三优先做小样本回归和检索/融合/引用调优。
5. 若任务二出现异常问答，优先判断：
   - 是任务一数据问题
   - 还是任务二解析 / SQL / 图表 / 回答问题
6. 若任务三回答异常，优先判断：
   - 是任务一数据库问题
   - 是知识库 chunk / retrieval 问题
   - 还是任务三澄清 / SQL / 融合 / references 问题
7. 避免按题号硬编码，优先做通用规则。
