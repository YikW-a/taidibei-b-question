from __future__ import annotations

import json
import math
import textwrap
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties

try:
    from pyecharts import options as opts
    from pyecharts.charts import Bar, Boxplot, Line, Pie, Radar, Scatter

    HAS_PYECHARTS = True
except Exception:
    HAS_PYECHARTS = False

    class _Dummy:
        pass

    opts = _Dummy()
    Bar = Boxplot = Line = Pie = Radar = Scatter = None


warnings.filterwarnings("ignore", message=r"Glyph .* missing from font\(s\) .*")
AVAILABLE_CJK_FONT = None
AVAILABLE_CJK_FONT_PATH = None
for _font_name in ["Arial Unicode MS", "Songti SC", "STSong", "Hiragino Sans GB", "Arial Unicode"]:
    try:
        _font_path = font_manager.findfont(_font_name, fallback_to_default=False)
        if _font_path:
            AVAILABLE_CJK_FONT = _font_name
            AVAILABLE_CJK_FONT_PATH = _font_path
            break
    except Exception:
        continue
plt.rcParams["font.family"] = AVAILABLE_CJK_FONT or "DejaVu Sans"
plt.rcParams["font.sans-serif"] = [AVAILABLE_CJK_FONT or "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
FONT_PROP = FontProperties(fname=AVAILABLE_CJK_FONT_PATH) if AVAILABLE_CJK_FONT_PATH else None

CHART_LABELS = {
    None: "无",
    "line": "折线图",
    "bar": "柱状图",
    "barh": "水平柱状图",
    "pie": "饼图",
    "scatter": "散点图",
    "hist": "直方图",
    "box": "箱线图",
    "radar": "雷达图",
}

SUPPORTED_CHART_TYPES = {"line", "bar", "barh", "pie", "scatter", "hist", "box", "radar"}
PRIMARY_METRIC_FIELDS = [
    "total_operating_revenue",
    "net_profit",
    "total_profit",
    "operating_profit",
    "asset_liability_ratio",
    "operating_cf_net_amount",
    "investing_cf_net_amount",
    "financing_cf_net_amount",
    "gross_profit_margin",
    "net_profit_margin",
    "roe",
]
IDENTIFIER_COLUMNS = ["report_period", "stock_abbr", "stock_code"]


@dataclass
class ChartPlan:
    chart_type: str
    title: str
    x_field: str | None = None
    y_fields: list[str] = field(default_factory=list)
    series_field: str | None = None
    category_field: str | None = None
    sort_by: str | None = None
    sort_ascending: bool = True
    top_n: int | None = None
    should_draw: bool = True
    reason: str = ""


def chart_type_to_label(chart_type: str | None) -> str:
    return CHART_LABELS.get(chart_type, "无")


def build_default_chart_plan(
    question_text: str,
    dataframe: pd.DataFrame,
    preferred_chart_type: str | None = None,
    preferred_metric_field: str | None = None,
    preferred_metric_name: str | None = None,
) -> ChartPlan | None:
    if dataframe.empty:
        return None
    numeric_cols = _numeric_columns(dataframe)
    if not numeric_cols:
        return None

    chart_type = preferred_chart_type or _infer_chart_type(question_text, dataframe)
    if chart_type is None:
        return None

    label_col = _best_label_column(dataframe)
    metric_col = _best_metric_column(dataframe, preferred_metric_field)
    metric_name = preferred_metric_name or metric_col or "查询结果"

    if chart_type == "line":
        x_field = "report_period" if "report_period" in dataframe.columns else label_col
        series_field = "stock_abbr" if x_field == "report_period" and "stock_abbr" in dataframe.columns and dataframe["stock_abbr"].nunique() > 1 else None
        return ChartPlan(
            chart_type="line",
            title=_build_title(question_text, metric_name),
            x_field=x_field,
            y_fields=[metric_col],
            series_field=series_field,
            sort_by=x_field,
            sort_ascending=True,
            reason="时间序列或趋势问题优先使用折线图。",
        )
    if chart_type in {"bar", "barh"}:
        category_field = "stock_abbr" if "stock_abbr" in dataframe.columns else label_col
        if any(token in question_text for token in ["双条形图", "双柱状图"]) and category_field:
            compare_fields = _best_compare_metric_fields(dataframe)
            if len(compare_fields) >= 2:
                return ChartPlan(
                    chart_type="bar",
                    title=_build_title(question_text, "双条形图"),
                    category_field=category_field,
                    y_fields=compare_fields[:2],
                    sort_by=compare_fields[0],
                    sort_ascending=False,
                    top_n=min(12, len(dataframe)),
                    reason="双年份/双指标对比问题优先使用成组柱状图。",
                )
        chosen = "barh" if chart_type == "barh" or _ranking_like(question_text) else "bar"
        return ChartPlan(
            chart_type=chosen,
            title=_build_title(question_text, metric_name),
            category_field=category_field,
            y_fields=[metric_col],
            sort_by=metric_col,
            sort_ascending=False,
            top_n=min(15, len(dataframe)),
            reason="排名/对比问题优先使用柱状图，项目较多时优先水平柱状图。",
        )
    if chart_type == "pie":
        return ChartPlan(
            chart_type="pie",
            title=_build_title(question_text, metric_name),
            category_field="stock_abbr" if "stock_abbr" in dataframe.columns else label_col,
            y_fields=[metric_col],
            top_n=min(8, len(dataframe)),
            reason="结构占比问题优先使用饼图。",
        )
    if chart_type == "scatter":
        xy = _best_two_numeric_columns(dataframe, preferred_metric_field)
        return ChartPlan(
            chart_type="scatter",
            title=_build_title(question_text, "相关性"),
            x_field=xy[0],
            y_fields=[xy[1]],
            series_field="stock_abbr" if "stock_abbr" in dataframe.columns else None,
            reason="相关性问题优先使用散点图。",
        )
    if chart_type == "hist":
        return ChartPlan(
            chart_type="hist",
            title=_build_title(question_text, metric_name),
            y_fields=[metric_col],
            reason="分布问题优先使用直方图。",
        )
    if chart_type == "box":
        return ChartPlan(
            chart_type="box",
            title=_build_title(question_text, metric_name),
            y_fields=[metric_col],
            reason="分布离散程度问题优先使用箱线图。",
        )
    if chart_type == "radar":
        metric_fields = _best_radar_metrics(dataframe, preferred_metric_field)
        if not metric_fields or "stock_abbr" not in dataframe.columns:
            return None
        return ChartPlan(
            chart_type="radar",
            title=_build_title(question_text, "核心指标对比"),
            series_field="stock_abbr",
            y_fields=metric_fields,
            top_n=min(6, dataframe["stock_abbr"].nunique()),
            reason="多公司多指标对比问题优先使用雷达图。",
        )
    return None


def refine_chart_plan_with_llm(
    llm_client,
    question_text: str,
    sql: str,
    dataframe: pd.DataFrame,
    default_plan: ChartPlan | None,
) -> ChartPlan | None:
    if default_plan is None or dataframe.empty:
        return default_plan
    sample = dataframe.head(12).to_dict(orient="records")
    system_prompt = (
        "You are a financial data visualization planner. "
        "Given a user question, SQL result columns, sample rows, and a draft chart plan, "
        "return strict JSON only. "
        "Allowed chart_type values: line, bar, barh, pie, scatter, hist, box, radar, none. "
        "Return keys: chart_type, title, x_field, y_fields, series_field, category_field, sort_by, sort_ascending, top_n, should_draw, reason. "
        "Only use existing columns. Keep the plan concise and practical for financial analysis."
    )
    user_prompt = (
        f"Question: {question_text}\n"
        f"SQL: {sql}\n"
        f"Columns: {json.dumps(list(dataframe.columns), ensure_ascii=False)}\n"
        f"Sample rows: {json.dumps(sample, ensure_ascii=False)}\n"
        f"Draft plan: {json.dumps(asdict(default_plan), ensure_ascii=False)}\n"
        "Return improved JSON only."
    )
    try:
        from .llm_client import extract_json_object

        response = llm_client.chat(system_prompt, user_prompt, temperature=0.0)
        payload = extract_json_object(response)
        return _sanitize_chart_plan(payload, dataframe, fallback=default_plan)
    except Exception:
        return default_plan


def render_chart(
    output_dir: Path,
    question_id: str,
    dataframe: pd.DataFrame,
    plan: ChartPlan,
    image_index: int = 1,
    html_dir: Path | None = None,
) -> str:
    if dataframe.empty or not plan.should_draw:
        return ""
    prepared = _prepare_dataframe_for_plan(dataframe, plan)
    if prepared.empty:
        return ""
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = output_dir / f"{question_id}_{image_index}.jpg"

    if HAS_PYECHARTS and html_dir is not None:
        _render_pyecharts_html(prepared, plan, chart_path, html_dir)
    _render_with_matplotlib(prepared, plan, chart_path)
    return str(chart_path)


def _infer_chart_type(question_text: str, dataframe: pd.DataFrame) -> str | None:
    if any(token in question_text for token in ["趋势", "变化", "走势"]):
        return "line"
    if any(token in question_text for token in ["水平柱状图"]):
        return "barh"
    if any(token in question_text for token in ["柱状图", "条形图", "排名", "前十", "前五", "前三", "排序"]):
        return "bar"
    if "饼图" in question_text:
        return "pie"
    if "散点图" in question_text or "相关性" in question_text:
        return "scatter"
    if "直方图" in question_text or "分布" in question_text:
        return "hist"
    if "箱线图" in question_text:
        return "box"
    if "雷达图" in question_text:
        return "radar"
    if "report_period" in dataframe.columns and dataframe["report_period"].nunique() > 1:
        return "line"
    return None


def _ranking_like(question_text: str) -> bool:
    return any(token in question_text for token in ["排名", "前十", "前五", "前三", "最高", "最低"])


def _numeric_columns(dataframe: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for column in dataframe.columns:
        series = pd.to_numeric(dataframe[column], errors="coerce")
        if series.notna().sum() > 0:
            cols.append(column)
    return cols


def _best_label_column(dataframe: pd.DataFrame) -> str | None:
    for column in IDENTIFIER_COLUMNS:
        if column in dataframe.columns:
            return column
    return dataframe.columns[0] if len(dataframe.columns) else None


def _best_metric_column(dataframe: pd.DataFrame, preferred: str | None) -> str:
    if preferred and preferred in dataframe.columns and pd.to_numeric(dataframe[preferred], errors="coerce").notna().sum() > 0:
        return preferred
    numeric_cols = _numeric_columns(dataframe)
    for column in PRIMARY_METRIC_FIELDS:
        if column in numeric_cols:
            return column
    return numeric_cols[0]


def _best_two_numeric_columns(dataframe: pd.DataFrame, preferred: str | None) -> tuple[str, str]:
    numeric_cols = _numeric_columns(dataframe)
    if preferred and preferred in numeric_cols:
        others = [col for col in numeric_cols if col != preferred]
        if others:
            return others[0], preferred
    if len(numeric_cols) >= 2:
        return numeric_cols[0], numeric_cols[1]
    return numeric_cols[0], numeric_cols[0]


def _best_radar_metrics(dataframe: pd.DataFrame, preferred: str | None) -> list[str]:
    numeric_cols = _numeric_columns(dataframe)
    chosen: list[str] = []
    if preferred and preferred in numeric_cols:
        chosen.append(preferred)
    for column in PRIMARY_METRIC_FIELDS:
        if column in numeric_cols and column not in chosen:
            chosen.append(column)
    for column in numeric_cols:
        if column not in chosen:
            chosen.append(column)
    return chosen[:6]


def _best_compare_metric_fields(dataframe: pd.DataFrame) -> list[str]:
    numeric_cols = _numeric_columns(dataframe)
    preferred = [
        col
        for col in numeric_cols
        if any(token in col for token in ["2024", "2025"]) and "rank" not in col.lower()
    ]
    if len(preferred) >= 2:
        return preferred[:2]
    return numeric_cols[:2]


def _build_title(question_text: str, suffix: str) -> str:
    base = question_text.replace("|", " ").replace("**", "").replace("`", "").strip()
    if len(base) > 24:
        base = base[:24] + "..."
    return f"{base} - {suffix}"


def _sanitize_chart_plan(payload: dict, dataframe: pd.DataFrame, fallback: ChartPlan) -> ChartPlan:
    chart_type = payload.get("chart_type") or fallback.chart_type
    if chart_type == "none":
        return ChartPlan(chart_type=fallback.chart_type, title=fallback.title, should_draw=False, reason=str(payload.get("reason", "")))
    if chart_type not in SUPPORTED_CHART_TYPES:
        chart_type = fallback.chart_type
    valid_cols = set(dataframe.columns)
    y_fields = [item for item in payload.get("y_fields", fallback.y_fields) if item in valid_cols]
    if not y_fields:
        y_fields = fallback.y_fields
    plan = ChartPlan(
        chart_type=chart_type,
        title=str(payload.get("title") or fallback.title),
        x_field=payload.get("x_field") if payload.get("x_field") in valid_cols else fallback.x_field,
        y_fields=y_fields,
        series_field=payload.get("series_field") if payload.get("series_field") in valid_cols else fallback.series_field,
        category_field=payload.get("category_field") if payload.get("category_field") in valid_cols else fallback.category_field,
        sort_by=payload.get("sort_by") if payload.get("sort_by") in valid_cols else fallback.sort_by,
        sort_ascending=bool(payload.get("sort_ascending", fallback.sort_ascending)),
        top_n=int(payload.get("top_n")) if str(payload.get("top_n", "")).isdigit() else fallback.top_n,
        should_draw=bool(payload.get("should_draw", True)),
        reason=str(payload.get("reason", fallback.reason)),
    )
    return plan


def _prepare_dataframe_for_plan(dataframe: pd.DataFrame, plan: ChartPlan) -> pd.DataFrame:
    work = dataframe.copy()
    if plan.sort_by and plan.sort_by in work.columns:
        sort_series = pd.to_numeric(work[plan.sort_by], errors="coerce")
        if sort_series.notna().sum() > 0:
            work = work.assign(_sort_key=sort_series).sort_values("_sort_key", ascending=plan.sort_ascending).drop(columns=["_sort_key"])
        else:
            work = work.sort_values(plan.sort_by, ascending=plan.sort_ascending)
    if plan.top_n:
        work = work.head(plan.top_n)
    return work


def _render_pyecharts_html(dataframe: pd.DataFrame, plan: ChartPlan, chart_path: Path, html_dir: Path | None) -> None:
    if not HAS_PYECHARTS or html_dir is None:
        return
    try:
        chart = _build_pyecharts_chart(dataframe, plan)
        if chart is None:
            return
        html_dir.mkdir(parents=True, exist_ok=True)
        chart.render(str(html_dir / f"{chart_path.stem}.html"))
    except Exception:
        return


def _build_pyecharts_chart(dataframe: pd.DataFrame, plan: ChartPlan):
    if plan.chart_type in {"bar", "barh"}:
        labels = dataframe[plan.category_field or _best_label_column(dataframe)].astype(str).tolist()
        values = pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").fillna(0).round(2).tolist()
        chart = Bar(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add_xaxis(labels)
        reversal = plan.chart_type == "barh"
        chart.add_yaxis(chart_type_to_label(plan.chart_type), values, category_gap="40%")
        chart.set_global_opts(
            title_opts=opts.TitleOpts(title=plan.title),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=25)),
            yaxis_opts=opts.AxisOpts(name="数值"),
            legend_opts=opts.LegendOpts(is_show=False),
        )
        if reversal:
            chart.reversal_axis()
        return chart
    if plan.chart_type == "line":
        x_field = plan.x_field or _best_label_column(dataframe)
        x_axis = dataframe[x_field].astype(str).tolist()
        chart = Line(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add_xaxis(x_axis)
        if plan.series_field and plan.series_field in dataframe.columns:
            for series_name, sub in dataframe.groupby(plan.series_field):
                chart.add_yaxis(str(series_name), pd.to_numeric(sub[plan.y_fields[0]], errors="coerce").fillna(0).round(2).tolist(), is_smooth=True)
        else:
            chart.add_yaxis(chart_type_to_label(plan.chart_type), pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").fillna(0).round(2).tolist(), is_smooth=True)
        chart.set_global_opts(title_opts=opts.TitleOpts(title=plan.title), xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=25)))
        return chart
    if plan.chart_type == "pie":
        labels = dataframe[plan.category_field or _best_label_column(dataframe)].astype(str).tolist()
        values = pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").fillna(0).round(2).tolist()
        chart = Pie(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add("", list(zip(labels, values)), radius=["35%", "65%"])
        chart.set_global_opts(title_opts=opts.TitleOpts(title=plan.title))
        return chart
    if plan.chart_type == "scatter":
        x = pd.to_numeric(dataframe[plan.x_field], errors="coerce").fillna(0).round(2).tolist()
        y = pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").fillna(0).round(2).tolist()
        chart = Scatter(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add_xaxis(x)
        chart.add_yaxis(plan.y_fields[0], y)
        chart.set_global_opts(title_opts=opts.TitleOpts(title=plan.title))
        return chart
    if plan.chart_type == "box":
        values = [pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").dropna().tolist()]
        chart = Boxplot(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add_xaxis([plan.y_fields[0]])
        chart.add_yaxis("", chart.prepare_data(values))
        chart.set_global_opts(title_opts=opts.TitleOpts(title=plan.title))
        return chart
    if plan.chart_type == "radar":
        if not plan.series_field or not plan.y_fields:
            return None
        schema = [opts.RadarIndicatorItem(name=field, max_=_safe_radar_max(dataframe[field])) for field in plan.y_fields]
        chart = Radar(init_opts=opts.InitOpts(width="980px", height="560px"))
        chart.add_schema(schema=schema)
        for _, row in dataframe.head(plan.top_n or len(dataframe)).iterrows():
            values = [[float(pd.to_numeric(pd.Series([row[field]]), errors="coerce").fillna(0).iloc[0]) for field in plan.y_fields]]
            chart.add(str(row[plan.series_field]), values)
        chart.set_global_opts(title_opts=opts.TitleOpts(title=plan.title))
        return chart
    return None


def _render_with_matplotlib(dataframe: pd.DataFrame, plan: ChartPlan, chart_path: Path) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(10.5, 6), dpi=150)
    ax = fig.add_subplot(111, polar=plan.chart_type == "radar")
    title = "\n".join(textwrap.wrap(plan.title, width=28))
    palette = ["#295C8E", "#4F8FBF", "#74B3CE", "#F4A259", "#BC4B51", "#6D597A"]

    if plan.chart_type in {"bar", "barh"}:
        label_col = plan.category_field or _best_label_column(dataframe)
        labels = dataframe[label_col].astype(str).tolist()
        if len(plan.y_fields) >= 2 and plan.chart_type == "bar":
            first_values, first_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
            second_values, second_suffix = _scale_series_for_plot(plan.y_fields[1], dataframe[plan.y_fields[1]])
            values_a = first_values.tolist()
            values_b = second_values.tolist()
            x = np.arange(len(labels))
            width = 0.38
            bars_a = ax.bar(x - width / 2, values_a, width=width, color=palette[0], label=plan.y_fields[0])
            bars_b = ax.bar(x + width / 2, values_b, width=width, color=palette[3], label=plan.y_fields[1])
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=30)
            ax.legend(frameon=False, prop=FONT_PROP)
            for bars, suffix in [(bars_a, first_suffix), (bars_b, second_suffix)]:
                for bar in bars:
                    value = bar.get_height()
                    label_text = f"{value:.2f}{suffix}" if suffix else _format_numeric_label(value)
                    ax.text(bar.get_x() + bar.get_width() / 2, value, label_text, ha="center", va="bottom", fontsize=8, fontproperties=FONT_PROP)
        else:
            scaled_values, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
            values = scaled_values.tolist()
            colors = [palette[i % len(palette)] for i in range(len(values))]
            if plan.chart_type == "barh":
                ax.barh(labels, values, color=colors)
                ax.invert_yaxis()
                for idx, value in enumerate(values):
                    label_text = f"{value:.2f}{axis_suffix}" if axis_suffix else _format_numeric_label(value)
                    ax.text(value, idx, f" {label_text}", va="center", fontsize=9, fontproperties=FONT_PROP)
            else:
                bars = ax.bar(labels, values, color=colors)
                ax.tick_params(axis="x", rotation=30)
                for bar, value in zip(bars, values):
                    label_text = f"{value:.2f}{axis_suffix}" if axis_suffix else _format_numeric_label(value)
                    ax.text(bar.get_x() + bar.get_width() / 2, value, label_text, ha="center", va="bottom", fontsize=9, fontproperties=FONT_PROP)
            if axis_suffix:
                ax.set_xlabel(f"数值{axis_suffix}", fontproperties=FONT_PROP)
    elif plan.chart_type == "line":
        x_field = plan.x_field or _best_label_column(dataframe)
        scaled_values, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
        if plan.series_field and plan.series_field in dataframe.columns:
            for idx, (series_name, sub) in enumerate(dataframe.groupby(plan.series_field)):
                sub = sub.sort_values(x_field)
                y, _ = _scale_series_for_plot(plan.y_fields[0], sub[plan.y_fields[0]])
                ax.plot(sub[x_field].astype(str), y, marker="o", linewidth=2.2, color=palette[idx % len(palette)], label=str(series_name))
            ax.legend(frameon=False, prop=FONT_PROP)
        else:
            y = scaled_values
            ax.plot(dataframe[x_field].astype(str), y, marker="o", linewidth=2.4, color=palette[0])
        ax.tick_params(axis="x", rotation=30)
        if axis_suffix:
            ax.set_ylabel(f"{plan.y_fields[0]}{axis_suffix}", fontproperties=FONT_PROP)
    elif plan.chart_type == "pie":
        label_col = plan.category_field or _best_label_column(dataframe)
        labels = dataframe[label_col].astype(str).tolist()
        values = pd.to_numeric(dataframe[plan.y_fields[0]], errors="coerce").fillna(0).tolist()
        wedges, texts, autotexts = ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=palette[: len(values)], wedgeprops={"width": 0.45, "edgecolor": "white"})
        for autotext in autotexts:
            autotext.set_fontsize(9)
            if FONT_PROP:
                autotext.set_fontproperties(FONT_PROP)
        if FONT_PROP:
            for text in texts:
                text.set_fontproperties(FONT_PROP)
    elif plan.chart_type == "scatter":
        x = pd.to_numeric(dataframe[plan.x_field], errors="coerce").fillna(0)
        y, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
        ax.scatter(x, y, c=palette[1], s=60, alpha=0.75, edgecolors="white", linewidth=0.8)
        if plan.series_field and plan.series_field in dataframe.columns:
            for _, row in dataframe.iterrows():
                y_value = _scale_series_for_plot(plan.y_fields[0], pd.Series([row[plan.y_fields[0]]]))[0].iloc[0]
                ax.annotate(str(row[plan.series_field]), (pd.to_numeric(pd.Series([row[plan.x_field]]), errors="coerce").fillna(0).iloc[0], y_value), fontsize=8, alpha=0.75, fontproperties=FONT_PROP)
        ax.set_xlabel(plan.x_field or "", fontproperties=FONT_PROP)
        ax.set_ylabel(f"{plan.y_fields[0]}{axis_suffix}", fontproperties=FONT_PROP)
    elif plan.chart_type == "hist":
        values, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
        values = values.dropna()
        ax.hist(values, bins=min(12, max(5, len(values) // 3 if len(values) > 0 else 5)), color=palette[2], edgecolor="white", alpha=0.9)
        ax.set_xlabel(f"{plan.y_fields[0]}{axis_suffix}", fontproperties=FONT_PROP)
    elif plan.chart_type == "box":
        values, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
        values = values.dropna()
        ax.boxplot(values, patch_artist=True, boxprops={"facecolor": palette[3], "alpha": 0.7}, medianprops={"color": "#222222", "linewidth": 2})
        ax.set_xticks([1])
        ax.set_xticklabels([f"{plan.y_fields[0]}{axis_suffix}"], fontproperties=FONT_PROP)
    elif plan.chart_type == "radar":
        metrics = plan.y_fields
        angles = np.linspace(0, 2 * math.pi, len(metrics), endpoint=False).tolist()
        angles += angles[:1]
        ax.set_theta_offset(math.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_thetagrids(np.degrees(angles[:-1]), metrics)
        for idx, (_, row) in enumerate(dataframe.head(plan.top_n or len(dataframe)).iterrows()):
            values = [float(pd.to_numeric(pd.Series([row[field]]), errors="coerce").fillna(0).iloc[0]) for field in metrics]
            values += values[:1]
            color = palette[idx % len(palette)]
            label = str(row[plan.series_field]) if plan.series_field else f"series_{idx+1}"
            ax.plot(angles, values, linewidth=2, label=label, color=color)
            ax.fill(angles, values, alpha=0.12, color=color)
        ax.legend(loc="upper right", bbox_to_anchor=(1.22, 1.12), frameon=False, prop=FONT_PROP)
    else:
        y, axis_suffix = _scale_series_for_plot(plan.y_fields[0], dataframe[plan.y_fields[0]])
        ax.plot(range(len(y)), y, marker="o", linewidth=2.2, color=palette[0])
        if axis_suffix:
            ax.set_ylabel(f"{plan.y_fields[0]}{axis_suffix}", fontproperties=FONT_PROP)

    if plan.chart_type != "pie":
        ax.grid(alpha=0.28)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=14, fontproperties=FONT_PROP)
    _apply_font_to_axes(ax)
    fig.tight_layout()
    fig.savefig(chart_path, format="jpg", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _safe_radar_max(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return 100.0
    return float(max(values.max() * 1.15, 1.0))


def _format_numeric_label(value: float) -> str:
    abs_value = abs(float(value))
    if abs_value >= 10000:
        return f"{value/10000:.2f}万"
    return f"{value:.2f}"


def _scale_series_for_plot(field_name: str, series: pd.Series) -> tuple[pd.Series, str]:
    numeric = pd.to_numeric(series, errors="coerce")
    field_lower = field_name.lower()
    ratio_like = any(token in field_lower for token in ["ratio", "margin", "growth", "roe", "per_share"])
    if ratio_like:
        return numeric.fillna(0), ""
    max_abs = numeric.dropna().abs().max() if numeric.notna().any() else 0
    if max_abs >= 1e7:
        return numeric.fillna(0) / 10000.0, "（万元）"
    return numeric.fillna(0), ""


def _apply_font_to_axes(ax) -> None:
    if FONT_PROP is None:
        return
    for label in ax.get_xticklabels():
        label.set_fontproperties(FONT_PROP)
    for label in ax.get_yticklabels():
        label.set_fontproperties(FONT_PROP)
