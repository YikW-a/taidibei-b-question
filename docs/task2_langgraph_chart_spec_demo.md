# Task2 LangGraph 图表 Spec 驱动渲染示例

## 1. 为什么要从 `chart_plan` 继续升级到 `chart_spec`

当前系统里已经有一层 `chart_plan`，它主要回答的是：

- 画什么图
- 用哪几个字段
- 是否排序
- 取前几条

但 `chart_plan` 还不够标准，主要问题是：

1. 它偏“渲染参数”，不够像可交换的数据契约。
2. LLM 输出不稳定时，渲染器很难校验每个字段的语义。
3. 后续如果想换渲染器，或者接任务三的 `RAG + 图表解释`，可复用性不够。

所以更推荐的结构是：

`问题 -> chart_plan -> chart_spec -> renderer`

其中：

- `chart_plan`：偏“意图层”
- `chart_spec`：偏“结构化契约层”
- `renderer`：偏“确定性执行层”

## 2. 当前原型里新增的 `chart_spec` 结构

当前 `task2_langgraph` 已经能把每张图落成一份 `.spec.json`，路径在：

- [outputs/task2_langgraph/artifacts/chart_specs](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/chart_specs)

核心结构大致是：

```json
{
  "schema_version": "task2.chart-spec.v2",
  "question_id": "B1028",
  "image_index": 1,
  "chart_type": "line",
  "title": "近3年净利润变化趋势",
  "data": {
    "dataset_name": "financials_view.result",
    "row_count": 12,
    "preview_rows": []
  },
  "transforms": {
    "sort_by": "report_period",
    "sort_ascending": true,
    "top_n": null,
    "filters": []
  },
  "encodings": {
    "x": {
      "field": "report_period",
      "data_type": "temporal",
      "label": "report_period",
      "unit": null
    },
    "value": {
      "field": "net_profit",
      "data_type": "quantitative",
      "label": "net_profit",
      "unit": "万元"
    },
    "series": {
      "field": "stock_abbr",
      "data_type": "nominal",
      "label": "stock_abbr",
      "unit": null
    }
  },
  "layout": {
    "width": 10.5,
    "height": 6.0,
    "dpi": 150,
    "legend": true,
    "rotate_xticks": 30,
    "show_value_labels": false
  },
  "output": {
    "filename": "B1028_1.jpg",
    "image_format": "jpg",
    "relative_path": "./result/B1028_1.jpg"
  },
  "meta": {
    "source_sql": "SELECT ...",
    "original_chart_plan": {
      "chart_type": "line",
      "x_field": "report_period",
      "y_fields": ["net_profit"],
      "category_field": "stock_abbr"
    }
  }
}
```

## 3. 对比效果

### 示例 1：单公司近 3 年营收趋势

旧 `chart_plan`：

```json
{
  "chart_type": "line",
  "title": "千金药业近3年营业总收入趋势",
  "x_field": "report_period",
  "y_fields": ["operating_revenue"],
  "category_field": null,
  "sort_by": "report_period",
  "sort_ascending": true,
  "top_n": null,
  "should_draw": true
}
```

新 `chart_spec`：

```json
{
  "chart_type": "line",
  "data": {
    "dataset_name": "financials_view.result",
    "row_count": 3
  },
  "transforms": {
    "sort_by": "report_period",
    "sort_ascending": true,
    "top_n": null
  },
  "encodings": {
    "x": {"field": "report_period", "data_type": "temporal"},
    "value": {"field": "operating_revenue", "data_type": "quantitative", "unit": "万元"}
  },
  "layout": {
    "legend": false,
    "rotate_xticks": 30,
    "show_value_labels": false
  },
  "output": {"filename": "B1006_1.jpg", "relative_path": "./result/B1006_1.jpg"}
}
```

改进点：

- `chart_plan` 只表达“打算怎么画”
- `chart_spec` 明确了数据语义、单位和输出文件

### 示例 2：多公司多期净利润趋势

旧 `chart_plan`：

```json
{
  "chart_type": "line",
  "x_field": "report_period",
  "y_fields": ["net_profit"],
  "category_field": "stock_abbr"
}
```

新 `chart_spec`：

```json
{
  "chart_type": "line",
  "encodings": {
    "x": {"field": "report_period", "data_type": "temporal"},
    "value": {"field": "net_profit", "data_type": "quantitative", "unit": "万元"},
    "series": {"field": "stock_abbr", "data_type": "nominal"}
  },
  "layout": {
    "legend": true
  }
}
```

改进点：

- `series` 被显式写出来，渲染器不再需要猜“是不是要按公司分多条线”
- 这正好能解决之前 `B1028_1.jpg` 那种“多家公司被串成一条线”的问题

### 示例 3：TopN 排名图

旧 `chart_plan`：

```json
{
  "chart_type": "bar",
  "category_field": "stock_abbr",
  "y_fields": ["net_profit"],
  "sort_by": "net_profit",
  "sort_ascending": false,
  "top_n": 10
}
```

新 `chart_spec`：

```json
{
  "chart_type": "bar",
  "transforms": {
    "sort_by": "net_profit",
    "sort_ascending": false,
    "top_n": 10
  },
  "encodings": {
    "category": {"field": "stock_abbr", "data_type": "nominal"},
    "value": {"field": "net_profit", "data_type": "quantitative", "unit": "万元"}
  },
  "layout": {
    "show_value_labels": true
  }
}
```

改进点：

- `top_n` 和排序语义进入 `transforms`
- 渲染层以后可以统一做“类别太多时自动裁剪”的校验，而不是散在逻辑里

## 4. 这条路最大的价值

### 1. 更容易做校验

在 `render_chart` 之前就能检查：

- `x/category/value/series` 字段是否真的存在
- `value` 是否是数值列
- `line` 图是否缺少时间轴
- `bar` 图是否类别过多

### 2. 更容易替换渲染器

以后你可以保留上游：

- `question -> chart_plan -> chart_spec`

只替换下游：

- `matplotlib renderer`
- `plotly renderer`
- `table renderer`

### 3. 更适合后续任务三

任务三里如果你要做：

- SQL 结果图
- 研报证据表
- 归因对比图

那么 `chart_spec` 可以作为统一图表契约，避免不同链路各自输出一套格式。

## 5. 当前阶段的定位

当前项目里已经做到：

1. `chart_plan` 生成
2. `chart_spec` 生成并落盘
3. 仍然由现有 `renderer` 负责出图

也就是说，当前阶段是：

`半迁移`

不是完全改造渲染器，而是先把“标准 spec 层”插进链路，方便观察和调试。

## 6. 下一步如果继续推进

如果决定正式切到 spec 驱动渲染，我建议按这个顺序：

1. 扩大 `chart_spec` 字段
   - 增加 `legend_position`
   - 增加 `label_format`
   - 增加 `table_fallback`

2. 把当前 renderer 改成只读 `chart_spec`
   - 不再直接依赖 `ChartPlan`

3. 对复杂图统一做降级策略
   - 趋势图保留 `line`
   - 排名图保留 `bar`
   - 占比保留 `pie`
   - 复杂问题优先退化成 `table`

## 7. 你现在可以怎么查看效果

下一次运行 `task2_langgraph` 后，除了看：

- [outputs/task2_langgraph/result_2.xlsx](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/result_2.xlsx)
- [outputs/task2_langgraph/result](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/result)

还可以直接看：

- [outputs/task2_langgraph/artifacts/chart_specs](/Users/yijiawen/YJW/竞赛/泰迪杯/最终选题/outputs/task2_langgraph/artifacts/chart_specs)

每张图都会多出一份对应的：

- `Bxxxx_n.spec.json`

这就是 “spec 驱动渲染” 这条路在当前项目里的可视化效果。
