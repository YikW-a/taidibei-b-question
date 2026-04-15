# 任务二使用说明

## 1. 当前版本定位

当前版本支持两种模式：

1. `template` 模式
2. `llm` 模式

其中 `llm` 模式更贴近正式目标，链路为：

1. 读取问题汇总
2. 调用大语言模型理解问题
3. 让模型针对统一查询视图 `financials_view` 生成 SQL
4. 执行 SQL 读取数据库
5. 把查询结果再次送入模型生成回答
6. 导出 `result_2.xlsx`

当前版本已经按赛题提交要求拆分输出：

1. 正式提交输出
2. 工程调试输出

其中正式提交输出遵循题面示例：

1. 图片统一保存到 `result/` 文件夹
2. 图片命名格式为 `问题编号_顺序编号.jpg`
3. 回答列采用题目“表 2 回答结构”对应的 JSON 字符串
4. `result_2.xlsx` 采用题目“表 3 提交示例”的列结构
5. 若同一道题使用了多种图表类型，`图形格式` 列会使用 `；` 连接列出，例如 `折线图；水平柱状图`

`template` 模式则是规则模板兜底，适合无模型配置时本地调试。

当前 `llm` 模式已经加入自动纠错回路：

1. 首次生成 SQL
2. 做 SQL 安全校验
3. 执行数据库查询
4. 若 SQL 校验或执行失败，则把报错信息与上一次 SQL 回送模型自动修正
5. 最多重试 3 次
6. 查询成功后，再将结果送入模型生成中文回答

同时，`llm` 模式还加入了结果质量校验：

- 如果“全市场/行业问题”被错误写成 `stock_abbr LIKE '%中药%'` 之类的模糊过滤，会判为无效并要求模型重写 SQL
- 如果排名题只返回 1 条、趋势题少于 2 个时间点、对比题缺少对比期，也会自动触发修正重试

当前版本的通用工程目标是把附件 4 的问题集串成一条可运行链路：

1. 读取问题汇总
2. 解析多轮问题文本
3. 识别公司、报告期、指标和图表意图
4. 复用任务一 SQLite / MySQL 数据库进行查询
5. 生成文字回答、结果预览和图表
6. 导出 `result_2.xlsx`

这版优先覆盖高频问数场景：
- 单公司单指标查询
- 趋势查询
- 排名查询
- 条件筛选查询
- 对比查询
- 简单统计查询

同时支持基础的多轮对话还原与澄清引导：
- 对多轮问题，程序会按轮次保留原始 `Q`
- 在前序轮次信息不足时，会自动生成澄清回复
- 在当前轮信息已经足够时，会尝试直接给出阶段性答案
- 如果某一轮问题明确要求“绘制图表/趋势图/柱状图”等，该轮 `A.image` 会写入对应图片相对路径，而不是只挂在最后一轮
- 如果同一道题包含多个作图轮次，程序会按轮次分别输出 `问题编号_1.jpg`、`问题编号_2.jpg` 等文件，并把相应路径挂到对应轮次的 `A.image`
- 当前重点识别并引导补全的要素包括：
  - 公司名称 / 股票代码
  - 报告期
  - 查询指标

## 1.1 图表生成策略

当前版本的图表不再是单一的“关键词命中后直接画图”，而是三层策略：

1. 规则选图
- 根据题目语义、结果表结构、字段类型自动生成默认绘图计划
- 例如：
  - 趋势/变化 -> 折线图
  - 排名/前十/排序 -> 柱状图或水平柱状图
  - 占比 -> 饼图
  - 相关性 -> 散点图
  - 分布 -> 直方图或箱线图
  - 多公司多指标对比 -> 雷达图

2. LLM 绘图计划修正
- `llm` 模式下，模型在生成 SQL 后，还会基于查询结果样例对默认绘图计划做一次结构化修正
- 输出内容包括：
  - 图类型
  - x 轴字段
  - y 轴字段
  - 分组字段
  - 排序方式
  - 图标题

3. 渲染层
- 正式提交图片统一使用增强版 `matplotlib` 导出 `.jpg`
- 若当前环境安装了 `pyecharts`，程序会额外输出 HTML 图表，便于调试和人工检查
- 这样可以同时保留较稳的图片导出和更灵活的 HTML 可视化

如果你希望进一步提升图表观感，建议额外安装：

```bash
pip install pyecharts
```

这样程序会额外生成 HTML 图表版本；正式提交的 `.jpg` 仍由 `matplotlib` 生成。

## 2. 运行方式

默认复用任务一 SQLite，走模板模式：

```bash
python3 run_task2.py
```

使用大语言模型模式：

```bash
python3 run_task2.py \
  --mode llm \
  --llm-base-url "https://api.siliconflow.cn/v1" \
  --llm-api-key "YOUR_API_KEY" \
  --llm-model "deepseek-ai/DeepSeek-V3.2"
```

如果你不想每次都写一长串参数，可以把配置写到：

- [task2_llm.env](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/configs/task2_llm.env)

填好后，直接运行：

```bash
python3 run_task2.py --mode llm
```

默认会自动读取：

```text
configs/task2_llm.env
```

文件格式如下：

```env
TASK2_LLM_BASE_URL=https://api.siliconflow.cn/v1
TASK2_LLM_API_KEY=YOUR_API_KEY
TASK2_LLM_MODEL=deepseek-ai/DeepSeek-V3.2
```

如果你想临时换一个配置文件，也可以：

```bash
python3 run_task2.py --mode llm --llm-config configs/task2_llm.env
```


## 2.1 如何验证 API 是否配置成功

建议先分三步验证，而不要只看“程序有没有报错”。

### 第一步：验证 `base_url + api_key`

先请求模型列表：

```bash
curl --request GET \
  --url https://api.siliconflow.cn/v1/models \
  --header "Authorization: Bearer YOUR_API_KEY"
```

如果返回正常 JSON，说明接口和密钥基本可用。

### 第二步：验证 `model`

再发一个最小聊天请求：

```bash
curl --request POST \
  --url https://api.siliconflow.cn/v1/chat/completions \
  --header "Authorization: Bearer YOUR_API_KEY" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "deepseek-ai/DeepSeek-V3.2",
    "messages": [
      {"role": "user", "content": "只回复：ok"}
    ],
    "temperature": 0
  }'
```

如果能返回 `ok`，说明模型名也配置对了。

### 第三步：验证任务二程序

运行任务二的 `llm` 模式后，重点看：

- 终端里的 `Status summary`
- 若有失败，终端里的 `First error samples`
- [task2_summary.json](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2/artifacts/task2_summary.json)
- [task2_results.csv](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2/artifacts/task2_results.csv)

## 2.2 运行时会看到什么

当前程序已经加入实时进度输出。运行时会显示：

1. 每题开始提示  
示例：

```text
[1/70] start B1001 | mode=llm | 金花股份利润总额是多少 | 2025年第三季度的
```

2. 每题结束提示  
示例：

```text
[1/70] done  B1001 | status=ok | attempts=2 | ok=1 todo=0 error=0
```

3. 运行结束后的汇总  
示例：

```text
Status summary:
status
ok       68
error     2
```

如果有失败，还会打印前几条失败原因，方便直接判断是 `404`、`401`、模型名不对，还是 SQL 连续纠错失败。

指定 MySQL：

```bash
python3 run_task2.py \
  --database-url "mysql+pymysql://root:password@127.0.0.1:3306/task1_db?charset=utf8mb4"
```

指定输出目录：

```bash
python3 run_task2.py --output-dir outputs/task2_debug
```

只跑随机小样本，例如随机 10 题：

```bash
python3 run_task2.py --mode llm --sample-limit 10
```

指定抽样随机种子：

```bash
python3 run_task2.py --mode llm --sample-limit 10 --sample-seed 7
```

按题号定向运行：

```bash
python3 run_task2.py --mode llm --question-ids B1001,B1046,B1066
```

说明：
- `--question-ids` 优先级高于 `--sample-limit`
- 适合专门联调多轮问题、图表问题或异常题号

## 3. 数据来源说明

任务二涉及两类输入，它们的作用不同：

1. 问题输入
- 来源文件：[附件4：问题汇总.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/正式数据/附件4：问题汇总.xlsx)
- 用途：读取题目编号、题型和问答文本
- 说明：这里只读取“问题”，不读取财务数据

2. 财务数据输入
- 默认来源：[task1_financials.db](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task1/task1_financials.db)
- 可选来源：通过 `--database-url` 指定的 MySQL / SQLite
- 用途：真正执行查询的数据源
- 说明：任务二的财务问数查询是基于数据库，不是基于 Excel 财报表

当前程序会从数据库中读取以下四张业务表：
- `core_performance_indicators_sheet`
- `balance_sheet`
- `cash_flow_sheet`
- `income_sheet`

### 3.1 模板模式的数据路径

`template` 模式会直接从任务一数据库读取四张业务表，构建宽表视图后完成：
- 排名查询
- 筛选查询
- 趋势查询
- 对比查询
- 简单统计查询

因此，模板模式的数据来源是数据库，不是 Excel。

### 3.2 LLM 模式的数据路径

`llm` 模式同样先从任务一数据库读取四张业务表，然后整理成一个统一查询视图：
- `financials_view`

这个统一视图会缓存到：
- `outputs/task2/task2_query_cache.db`

之后的大语言模型并不是直接读取 Excel，而是：

1. 面向 `financials_view` 生成 SQL
2. 执行 SQL 查询数据库
3. 将查询结果回送给模型生成最终回答

所以可以明确理解为：
- Excel 只负责提供“问题文本”
- 数据库负责提供“财务查询数据”
- LLM 模式本质上仍然是“基于数据库问数”

## 4. 正式提交输出

- `outputs/task2/result_2.xlsx`
  - 任务二正式提交表
  - 列结构与赛题“表 3 提交示例”一致
  - 当前包含 5 列：
    - `编号`
    - `问题`
    - `SQL 查询语句`
    - `图形格式`
    - `回答`

- `outputs/task2/result/`
  - 正式提交所需的图表目录
  - 图片命名规则为 `问题编号_顺序编号.jpg`
  - 在 `回答` 列 JSON 中使用相对路径引用，例如 `./result/B1002_1.jpg`

### 4.1 回答列格式

`回答` 列是一个 JSON 字符串，结构与题面“表 2 回答结构”一致，例如：

```json
[
  {
    "Q": "金花股份近几年的利润总额变化趋势是什么样的",
    "A": {
      "content": "金花股份的利润总额趋势已生成，共 12 个数据点。",
      "image": ["./result/B1002_1.jpg"]
    }
  }
]
```

如果是多轮问题，则会按问题原始顺序保留多轮 `Q`，最终一轮放入完整回答；若本题无图，则 `image` 返回空列表。

如果前序轮次缺失关键条件，程序会输出澄清式回复，例如：

```json
[
  {
    "Q": "金花股份利润总额是多少",
    "A": {
      "content": "请问你查询哪一个报告期的利润总额？",
      "image": []
    }
  },
  {
    "Q": "2025年第三季度的",
    "A": {
      "content": "金花股份 2025 年第三季度的利润总额是 3533.59 万元。",
      "image": []
    }
  }
]
```

如果某一中间轮的累计信息已经足够完成一次查询，程序会优先返回阶段性答案，而不是一律等待最后一轮。

### 4.2 图形格式列说明

`图形格式` 列使用中文图形名称，常见包括：

- `无`
- `折线图`
- `柱状图`
- `水平柱状图`
- `饼图`
- `散点图`
- `直方图`
- `箱线图`
- `雷达图`

## 5. 工程调试输出

- `outputs/task2/artifacts/task2_results.csv`
  - 工程调试明细表
  - 会保留内部字段，例如解析到的公司、指标、结果预览、图表绝对路径、状态、重试次数、备注等

- `outputs/task2/artifacts/task2_summary.json`
  - 运行汇总
  - 用于快速查看 `ok / todo / error` 数量及意图分布
  - 若使用抽样运行，还会记录 `sample_limit` 与 `sample_seed`
  - 若使用题号定向运行，还会记录 `question_ids`

- `outputs/task2/task2_query_cache.db`
  - 仅 `llm` 模式使用
  - 由任务一数据库四张表整理出的统一查询缓存库
  - 内含 `financials_view`，供大语言模型生成 SQL 时查询

- `outputs/task2/artifacts/pyecharts_html/`
  - 当环境中安装了 `pyecharts` 时，程序会在这里保留图表 HTML 版本，便于调试和人工检查
  - 该目录不参与正式提交

## 6. 依赖说明

任务二新增依赖主要有：

- 核心运行依赖
  - `matplotlib`
  - `numpy`

- LLM 接口调用
  - 使用 Python 标准库 `urllib.request`
  - 不额外依赖 `openai` SDK

- 图表增强可选依赖
  - `pyecharts`

当前项目已经整理出一份合并后的统一依赖文件：

- [requirements.txt](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/requirements.txt)
  - 任务一 + 任务二统一依赖
  - 包含核心依赖和图表增强依赖

如果你只想继续复用旧环境，也可以保留：

- [requirements.txt](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/requirements.txt)
  - 任务一原始依赖清单

建议安装方式：

```bash
pip install -r requirements.txt
```

## 7. 当前实现说明

- `template` 模式和 `llm` 模式都基于数据库查询，不直接读取财务 Excel 数据
- `llm` 模式现在也支持按题意生成图表，不再只输出文字回答
- 图表链路当前采用“三层策略”：
  - 规则选图
  - LLM 绘图计划修正
  - `pyecharts` HTML 调试输出 + 增强版 `matplotlib` 正式出图
- 正式提交时，优先使用：
  - `outputs/task2/result_2.xlsx`
  - `outputs/task2/result/`

## 8. 代码结构

- [run_task2.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/run_task2.py)
  - 任务二入口

- [src/task2_pipeline/parser.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/parser.py)
  - 读取附件 4 问题
  - 实体、指标、报告期和意图解析

- [src/task2_pipeline/catalog.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/catalog.py)
  - 指标词典和常见公司别名

- [src/task2_pipeline/charting.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/charting.py)
  - 图表规划与渲染模块
  - 负责规则选图、LLM 绘图计划修正、`pyecharts` / `matplotlib` 渲染

- [src/task2_pipeline/engine.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/engine.py)
  - 构建四表宽表视图
  - 执行排名、筛选、趋势等模板化查询
  - 调用图表规划模块生成图表

- [src/task2_pipeline/llm_client.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/llm_client.py)
  - OpenAI 兼容接口调用封装
  - 负责与大语言模型通信

- [src/task2_pipeline/llm_engine.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/llm_engine.py)
  - 构建统一查询视图 `financials_view`
  - 调用 LLM 生成 SQL
  - 执行 SQL 并将结果回送给 LLM 生成最终回答

- [src/task2_pipeline/pipeline.py](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/src/task2_pipeline/pipeline.py)
  - 串联整条任务二流程

## 9. 当前边界

`llm` 模式当前的关键设计是让模型统一面向 `financials_view` 生成 SQL，而不是为每道题手写模板，因此更适合后续未知测试问题。

当前版本仍有这些边界：

- 当前多轮能力主要面向“附件 4 的预定义多轮问题”以及同类追问
- 复杂开放式多轮对话暂未引入长期会话记忆
- SQL 安全控制目前以只允许 `SELECT/WITH` 为主
- 模型效果仍依赖所选模型的中文理解和 NL2SQL 能力
- 若未安装 `pyecharts`，将不会生成 HTML 调试图，但不影响正式 `.jpg` 出图
- 若连续 3 次 SQL 纠错仍失败，该题会在结果表中标记为 `error`，便于人工复核

后续建议的增强顺序是：

1. 强化 LLM 模式下的 SQL 自校验与重试
2. 补更细粒度的多轮状态记忆与澄清追问
3. 继续打磨高频财务图表模板和视觉风格
