# 任务三 LangGraph 使用说明

## 1. 模块定位

任务三当前正式实现位于：

- [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph)

其目标不是单纯做“研报问答”，而是把三类能力接成一条可复核的分析链：

1. 任务一财务数据库查询
2. 附件 5 研报知识库检索
3. 基于 `LangGraph` 的多轮分析、引用与图表生成

当前主入口为：

- 建库入口：[run_task3_index.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_index.py)
- 回答入口：[run_task3_langgraph.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/run_task3_langgraph.py)

论文说明见：

- [任务三建模与求解（论文版）.md](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/docs/任务三建模与求解（论文版）.md)

---

## 2. 当前正式结果

正式输出目录：

- [outputs/task3_langgraph](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task3_langgraph)

当前正式版结果为：

- `80` 题
- `80 ok / 0 error`

对应摘要文件：

- [task3_langgraph_summary.json](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task3_langgraph/artifacts/task3_langgraph_summary.json)
- [result_3.xlsx](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task3_langgraph/result_3.xlsx)

知识库当前状态：

- `chunk_count = 12856`
- `index_type = faiss_flat_ip`
- `embedding_model = BAAI/bge-m3`
- `index_status = ready`

向量索引元数据：

- [index_meta.json](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/outputs/task3_langgraph/artifacts/vector_store/index_meta.json)

---

## 3. 整体流程

任务三当前主链为：

`parse -> clarify -> query_plan/retrieval_plan -> SQL -> retrieve -> rerank -> fuse -> chart -> answer -> self_check -> export`

对应状态图实现：

- [src/task3_langgraph/graph/builder.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/graph/builder.py)

核心节点实现：

- [src/task3_langgraph/nodes/workflow.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/nodes/workflow.py)

当前链路的职责分工大致是：

1. `parse_question`
   - 解析公司、报告期、指标、主题词、TopN、阈值和题型路由
2. `clarify_or_continue`
   - 判断是否缺少关键槽位，必要时生成追问
3. `build_query_plan`
   - 同步生成 SQL 查询计划和研报检索计划
4. `generate_sql / execute_sql`
   - 生成并执行安全 SQL，遇到 SQLite 方言问题时尝试修复
5. `retrieve_reports / rerank_evidence`
   - 从元数据和向量索引中召回并重排证据
6. `fuse_sql_and_evidence`
   - 合并结构化数据与研报证据
7. `render_chart`
   - 根据题意与结果自动生成 `chart_spec` 和图片
8. `generate_answer`
   - 输出中文回答与引用
9. `run_self_check`
   - 对答案进行数字、一致性与引用复核
10. `export_result`
   - 输出最终 `result_3.xlsx`、debug 和 retrieval 产物

---

## 4. 输出结构约定

任务三最终回答采用：

```json
[
  {
    "Q": "子问题文本",
    "A": {
      "content": "中文回答",
      "image": ["./result/B2003_1.jpg"],
      "references": [
        {
          "paper_path": "../附件 5：研报数据/行业研报/xxx.pdf",
          "text": "证据摘要",
          "paper_image": "图3：医保谈判成功率变化"
        }
      ]
    }
  }
]
```

其中：

- `content`：必填，为当前子问题回答
- `image`：非必填；生成图时写入相对路径，否则为空列表
- `references`：必填；每条引用包含 `paper_path`、`text`、`paper_image`
- `paper_path`：统一规范为 `../附件 5：研报数据/...`
- `paper_image`：含义是图表标题文本，如“图 3：...”或“表 4：...”，不是图片路径

这一输出协议已在正式结果中收口稳定。

---

## 5. 关键模块

### 5.1 解析与路由

- [services/parser.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/services/parser.py)

当前已支持：

- 公司别名识别
- 指标别名映射
- 报告期标准化
- `sql_only / sql_chart / causal_analysis / industry_open_analysis / hybrid_sql_rag` 路由

相较于早期版本，已经补入了与任务一字段口径一致的指标映射，例如：

- `扣非净利润`
- `加权平均净资产收益率（扣非）`
- `营业总收入增长率`

### 5.2 运行时与数据库视图

- [tools/runtime.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/runtime.py)

这里负责：

- 构建 `financials_view`
- 派生 `Q2 / Q4` 单季度记录
- 统一 LLM / embedding / rerank / retrieval 调度
- SQL 缓存、检索缓存与回答后处理

### 5.3 知识库构建与检索

- [tools/report_parser.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/report_parser.py)
- [tools/vector_store.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/vector_store.py)
- [tools/retrieval.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/retrieval.py)

当前检索不是单一路径，而是：

- 元数据检索
- 向量检索
- `HybridRetriever` 融合

其中 stock/industry/hybrid 三种 `source_scope` 会根据题型自动切换。

### 5.4 图表链

- [tools/charts.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/charts.py)
- [tools/chart_spec.py](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/tools/chart_spec.py)

当前图表链已经独立于任务二，直接输出：

- `chart_spec`
- 渲染图片
- `A.image` 相对路径

---

## 6. 当前已收口的优化点

### 6.1 SQL 生成与执行

近期已经完成这些关键修补：

1. SQLite `UNION / UNION ALL + ORDER BY` 错误修复
2. 中位数类问题改为兼容 SQLite 的窗口函数思路
3. 对不支持的细分业务字段增加显式边界，不再用错误字段硬替代
4. `Q2 / Q4` 与“同期”问题的报告期口径对齐

### 6.2 回答生成

为避免把 `stock_code` 当成金额值，当前加入了：

1. 简单事实题的确定性短路径
2. 问题驱动的指标列优选
3. 标识列过滤
4. 多轮题的上下文继承和报告期修正

### 6.3 证据链

当前对检索结果做了三层稳态优化：

1. 先用元数据与向量召回候选
2. 再做证据重排
3. 最后在引用生成时标准化 `paper_path / paper_image`

### 6.4 边界收口

对于 schema 中没有结构化字段支撑的问题，如某些“细分业务收入占比”“老年病相关药品收入占比”类问法，当前策略是：

- 明确说明结构化数据无法直接支持该口径
- 不再用 `营业总收入` 或模糊 `LIKE` 条件假装回答

这个取舍会让答案更保守，但显著降低“看起来回答了、实际上答错口径”的风险。

---

## 7. 提示词工程

任务三采用分层提示词，而不是单一总提示词。当前提示词目录：

- [src/task3_langgraph/prompts](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/src/task3_langgraph/prompts)

主要包括：

- `planning_system.txt`
- `query_plan_system.txt`
- `retrieval_plan_system.txt`
- `sql_generation_system.txt`
- `clarification_system.txt`
- `evidence_rerank_system.txt`
- `answer_generation_system.txt`
- `self_check_system.txt`

设计思路是：

1. 规划提示词负责“决定做什么”
2. SQL 提示词负责“如何安全查”
3. 检索提示词负责“去哪里找证据”
4. 回答提示词负责“如何用数据和证据表达”
5. 自检提示词负责“检查有没有写错”

这套分层提示词是任务三后期稳定性的关键来源之一。

---

## 8. 所用模型与平台

任务三默认使用 OpenAI 兼容接口，示例配置见：

- [configs/task3_llm.env.example](/Users/yijiawen/YJW/竞赛/2026.4 泰迪杯/最终选题/configs/task3_llm.env.example)

当前默认组合为：

- LLM 平台：`SiliconFlow`
- 生成模型：`deepseek-ai/DeepSeek-V3.2`
- 向量模型：`BAAI/bge-m3`
- 重排模型：`BAAI/bge-reranker-v2-m3`

---

## 9. 常用命令

### 9.1 建库

```bash
python3 run_task3_index.py
```

### 9.2 全量回答

```bash
python3 run_task3_langgraph.py
```

### 9.3 指定题目回归

```bash
conda run -n taidibei python run_task3_langgraph.py \
  --question-ids B2001,B2012,B2024 \
  --output-dir outputs/task3_langgraph_regression
```

### 9.4 统一测试入口

```bash
python3 run_test_question_sets.py --skip-task2
```

---

## 10. 当前结论

**当前 `outputs/task3_langgraph` 可以作为任务三正式版结果。**

这一版的主要特点是：

- 结果结构稳定
- 多轮题上下文继承基本打通
- `paper_path / paper_image / image` 协议已统一
- SQL、RAG、图表、引用四条链均可全量运行
- 最终结果达到 `80 ok / 0 error`

如果后续继续优化，最值得投入的方向主要是：

1. 更细粒度的研报证据聚合
2. 多研报冲突观点的显式比较
3. 开放分析题中“定量 + 定性”权重的自适应融合
