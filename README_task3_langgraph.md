# 任务三 LangGraph 使用说明

## 1. 模块定位

任务三当前主实现为：

- [src/task3_langgraph](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph)

它已经不是纯骨架，而是一个已经完成：

- 研报知识库构建
- SQL + RAG 融合
- 图表输出
- 结构化引用输出

的“**可初步提交版本**”。

入口分为两个：

- 建库入口：
  - [run_task3_index.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_index.py)
- 回答入口：
  - [run_task3_langgraph.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_langgraph.py)

---

## 2. 当前已完成能力

### 2.1 数据准备层

已完成：

1. 附件 5 元数据接入
2. `字段说明.xlsx` 标准化接入
3. PDF 正文抽取
4. 标题/段落优先 chunk
5. 图表/表格编号与标题基础字段准备
6. `BAAI/bge-m3`
7. `FAISS`
8. `metadata / vector / hybrid` 检索

当前知识库状态：

- `总 chunk = 12856`
- `已建向量索引 chunk = 12856`
- `index_status = ready`

### 2.2 回答主链

当前 task3 主链已经接通：

`parse -> clarify -> query_plan/retrieval_plan -> SQL -> retrieve -> rerank -> fuse -> chart -> answer -> self_check -> export`

### 2.3 图表链

task3 图表链已经正式接入，并且**实现独立于 task2**。

本地图表模块位于：

- [src/task3_langgraph/tools/charts.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/charts.py)
- [src/task3_langgraph/tools/chart_spec.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/chart_spec.py)

规则是：

- 题面明确要求绘图 / 可视化时，强制尝试生图
- 图片路径写入 `A.image`

### 2.4 `references`

当前 `references` 结构已经收敛为：

- `paper_path`
- `text`
- `paper_image`

其中：

- `paper_path`：相对路径
- `text`：研报原文摘要
- `paper_image`：仅命中图表/表格时写入，语义是：
  - `图表编号 + 标题`

### 2.5 `paper_image`

`paper_image` 现在已经从“结构支持”升级到“真实命中可用”：

- 当前代码会在最终 `references` 中**有意识保留 1 条图表类证据**
- 最近全量结果中已统计到：
  - `paper_image_hits = 170`

---

## 3. 当前全量状态

最近一轮 task3 全量回答结果已经做到：

- `80` 题全部导出非空回答
- 当前知识库：
  - `总 chunk = 12856`
  - `已建向量索引 chunk = 12856`
  - `index_type = faiss_flat_ip`
  - `index_status = ready`

当前更准确的判断是：

- 主链已经是：
  - `PDF -> chunk -> bge-m3 -> FAISS -> retrieval -> answer`
- `paper_image` 已经在真实结果中命中
- 强制要求绘图的题，当前没有系统性漏图问题
- 剩余问题主要转向：
  - 少量多轮题的一致性
  - 少量 SQL 主导 / 知识库边界题引用为空
  - 个别题仍可继续润色答案自然度

最近针对多轮题还补了：

- 相对期间解析：
  - 例如“去年”会优先落到 `2024FY`
- 别名映射：
  - 例如 `三金 -> 桂林三金`
- 阈值筛选空结果的自动重试
- 针对筛选 / 排名题的更保守短路径

例如：

- `B2048`
  - SQL 会先筛出公司
  - 当前筛出的是 `康惠制药`
  - 但附件 5 中没有该公司的个股研报 chunk
  - 所以 `references=0` 属于真实边界，而不是题面解析错误

---

## 4. 当前题型路由

当前 task3 已引入更细的题型路由：

- `sql_only`
- `sql_chart`
- `causal_analysis`
- `industry_open_analysis`
- `hybrid_sql_rag`

对应默认策略：

### 纯 SQL 题

- `needs_sql=true`
- `needs_retrieval=false`

### 纯 SQL 图表题

- `needs_sql=true`
- `needs_retrieval=false`
- 优先走短路径并生图

### 归因题

- `needs_sql=true`
- `needs_retrieval=true`

### 行业开放题

- `needs_retrieval=true`
- `source_scope=industry`

### 混合题

- `needs_sql=true`
- `needs_retrieval=true`

---

## 5. 当前提速策略

task3 现在已完成一轮性能收口，当前已落地：

1. planning 合并
2. SQL 缓存
3. retrieval 缓存
4. rerank fast path
5. self_check fast path
6. rewrite 触发范围收紧
7. 纯 SQL / 纯图表题短路径

例如：

- `B2003` 单题耗时已从约 `181s` 逐步压到约 `67s`

---

## 6. 常用命令

### 6.1 建库

```bash
python run_task3_index.py \
  --embedding-batch-size 64 \
  --embedding-batch-pause-seconds 1
```

### 6.2 全量回答

```bash
/opt/anaconda3/envs/taidibei/bin/python run_task3_langgraph.py
```

### 6.2.1 使用自定义测试题集

```bash
/opt/anaconda3/envs/taidibei/bin/python run_task3_langgraph.py \
  --question-file "正式数据/测试集/任务三问题汇总.xlsx" \
  --output-dir "outputs/testsets/task3_langgraph" \
  --knowledge-base-dir "outputs/task3_langgraph"
```

这里的含义是：

- 回答结果写到 `outputs/testsets/task3_langgraph`
- 继续复用已经建好的正式知识库：
  - `outputs/task3_langgraph/artifacts/chunks`
  - `outputs/task3_langgraph/artifacts/vector_store`

### 6.2.2 使用统一测试入口

```bash
python3 run_test_question_sets.py --skip-task2
```

### 6.3 只清回答输出、保留知识库

```bash
rm -rf outputs/task3_langgraph/result \
       outputs/task3_langgraph/artifacts/debug \
       outputs/task3_langgraph/artifacts/retrieval \
       outputs/task3_langgraph/artifacts/chart_specs
rm -f outputs/task3_langgraph/result_3.xlsx \
      outputs/task3_langgraph/artifacts/task3_langgraph_results.csv \
      outputs/task3_langgraph/artifacts/task3_langgraph_summary.json \
      outputs/task3_langgraph/task3_langgraph_query_cache.db
```

### 6.4 测试集推荐放置位置

后续比赛测试题集建议固定放在：

- `正式数据/测试集/任务三问题汇总.xlsx`

统一测试输出默认放在：

- `outputs/testsets/task3_langgraph`

---

## 7. 关键文件

- 主入口：
  - [run_task3_langgraph.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_langgraph.py)
  - [run_task3_index.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task3_index.py)
- 配置：
  - [src/task3_langgraph/config/settings.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/config/settings.py)
- 解析器：
  - [src/task3_langgraph/services/parser.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/services/parser.py)
- 运行时：
  - [src/task3_langgraph/tools/runtime.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/runtime.py)
- 检索：
  - [src/task3_langgraph/tools/retrieval.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/retrieval.py)
- 建库：
  - [src/task3_langgraph/tools/report_parser.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/report_parser.py)
  - [src/task3_langgraph/tools/vector_store.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/tools/vector_store.py)
- 节点：
  - [src/task3_langgraph/nodes/workflow.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task3_langgraph/nodes/workflow.py)

---

## 8. 当前判断

**task3 现在已经达到“可初步提交”状态。**

当前最主要的剩余问题是：

1. 少量外部接口 `503`
2. 少量真实边界题仍然无引用
3. 个别题的答案仍可继续润色

但从主链角度看，当前已经具备：

- 知识库
- SQL
- RAG
- 图表
- 引用
- `paper_image`
- 全量运行能力
