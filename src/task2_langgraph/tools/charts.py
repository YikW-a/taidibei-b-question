from __future__ import annotations

import math
import textwrap
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties

from ..services import extract_json_object


warnings.filterwarnings("ignore", message=r"Glyph .* missing from font\(s\) .*")
AVAILABLE_CJK_FONT = None
AVAILABLE_CJK_FONT_PATH = None
for _font_name in ["Arial Unicode MS", "Songti SC", "STSong", "Hiragino Sans GB", "SimHei"]:
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
    "pie": "饼图",
    "table": "表格图",
    "scatter": "散点图",
    "hist": "直方图",
    "box": "箱线图",
    "radar": "雷达图",
}


@dataclass
class ChartPlan:
    chart_type: str
    title: str
    x_field: str | None = None
    y_fields: list[str] = field(default_factory=list)
    category_field: str | None = None
    sort_by: str | None = None
    sort_ascending: bool = True
    top_n: int | None = None
    should_draw: bool = True


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
    requested_chart_type = preferred_chart_type or _infer_chart_type(question_text, dataframe)
    if requested_chart_type == "table" and not _should_force_table(question_text, dataframe, numeric_cols):
        requested_chart_type = _preferred_non_table_chart_type(question_text, dataframe)
    chart_type = _normalize_chart_type(requested_chart_type, dataframe)
    if not chart_type:
        return None
    metric_field = preferred_metric_field if preferred_metric_field in dataframe.columns else (numeric_cols[0] if numeric_cols else None)
    title = _build_title(question_text, preferred_metric_name or metric_field or "结果")
    if chart_type == "table":
        return _sanitize_chart_plan(
            dataframe,
            ChartPlan(
                chart_type="table",
                title=title,
                category_field="stock_abbr" if "stock_abbr" in dataframe.columns else None,
                y_fields=numeric_cols[: min(4, len(numeric_cols))],
                top_n=min(12, len(dataframe)),
            ),
        )
    if chart_type == "line":
        x_field = "report_period" if "report_period" in dataframe.columns else (dataframe.columns[0] if len(dataframe.columns) else None)
        category_field = "stock_abbr" if "stock_abbr" in dataframe.columns and dataframe["stock_abbr"].nunique() > 1 else None
        return _sanitize_chart_plan(dataframe, ChartPlan(chart_type="line", title=title, x_field=x_field, y_fields=[metric_field], category_field=category_field, sort_by=x_field))
    if chart_type == "bar":
        category_field = "stock_abbr" if "stock_abbr" in dataframe.columns else ("report_period" if "report_period" in dataframe.columns else dataframe.columns[0])
        sort_by = metric_field
        top_n = min(15, len(dataframe))
        sort_ascending = False
        if requested_chart_type == "grouped_bar" and "stock_abbr" in dataframe.columns and ("report_period" in dataframe.columns or "period" in dataframe.columns):
            category_field = "stock_abbr"
            sort_by = "rank" if "rank" in dataframe.columns else metric_field
            top_n = min(10, len(dataframe))
            sort_ascending = True
        elif _should_preserve_dataframe_order(question_text, dataframe):
            sort_by = None
            top_n = min(12, len(dataframe))
        elif metric_field and metric_field in dataframe.columns:
            numeric = pd.to_numeric(_column_as_series(dataframe, metric_field), errors="coerce").dropna()
            if not numeric.empty and numeric.quantile(0.75) <= 0:
                sort_ascending = True
        return _sanitize_chart_plan(
            dataframe,
            ChartPlan(
                chart_type="bar",
                title=title,
                category_field=category_field,
                y_fields=[metric_field],
                sort_by=sort_by,
                sort_ascending=sort_ascending if sort_by == metric_field or sort_by is None else True,
                top_n=top_n,
            ),
        )
    if chart_type == "pie":
        category_field = "stock_abbr" if "stock_abbr" in dataframe.columns else ("report_period" if "report_period" in dataframe.columns else dataframe.columns[0])
        return _sanitize_chart_plan(dataframe, ChartPlan(chart_type="pie", title=title, category_field=category_field, y_fields=[metric_field], sort_by=metric_field, sort_ascending=False, top_n=min(8, len(dataframe))))
    if chart_type == "scatter":
        candidate_numeric = [col for col in numeric_cols if col in dataframe.columns]
        if len(candidate_numeric) < 2:
            return None
        x_field = preferred_metric_field if preferred_metric_field in candidate_numeric else candidate_numeric[0]
        y_field = next((col for col in candidate_numeric if col != x_field), None)
        if y_field is None:
            return None
        return _sanitize_chart_plan(
            dataframe,
            ChartPlan(
                chart_type="scatter",
                title=title,
                x_field=x_field,
                y_fields=[y_field],
                category_field="stock_abbr" if "stock_abbr" in dataframe.columns else None,
                sort_by=None,
                top_n=min(50, len(dataframe)),
            ),
        )
    return _sanitize_chart_plan(dataframe, ChartPlan(chart_type="bar", title=title, category_field="stock_abbr" if "stock_abbr" in dataframe.columns else dataframe.columns[0], y_fields=[metric_field]))


def refine_chart_plan_with_llm(llm_client, system_prompt: str, question_text: str, sql: str, dataframe: pd.DataFrame, default_plan: ChartPlan | None) -> ChartPlan | None:
    if default_plan is None or llm_client is None or dataframe.empty:
        return default_plan
    try:
        payload = extract_json_object(
            llm_client.chat(
                system_prompt,
                (
                    f"Question: {question_text}\n"
                    f"SQL: {sql}\n"
                    f"Default plan: {default_plan.__dict__}\n"
                    f"Columns: {list(dataframe.columns)}\n"
                    f"Rows: {dataframe.head(20).to_json(force_ascii=False, orient='records')}"
                ),
                temperature=0.0,
            )
        )
        merged = {**default_plan.__dict__}
        for key, value in payload.items():
            if value is not None:
                merged[key] = value
        if default_plan.sort_by is None and _should_preserve_dataframe_order(question_text, dataframe):
            merged["sort_by"] = None
        chart_type = _normalize_chart_type(merged.get("chart_type"), dataframe)
        if chart_type == "line" and any(token in question_text for token in ["亏钱", "为负", "负数", "列表", "哪些企业", "哪些公司"]):
            chart_type = "bar"
        if chart_type not in {"line", "bar", "pie", "table", "scatter"}:
            return _sanitize_chart_plan(dataframe, default_plan)
        if chart_type == "table" and not _should_force_table(question_text, dataframe, _numeric_columns(dataframe)):
            chart_type = default_plan.chart_type
        return _sanitize_chart_plan(
            dataframe,
            ChartPlan(
            chart_type=str(chart_type),
            title=str(merged.get("title") or default_plan.title),
            x_field=merged.get("x_field") or default_plan.x_field,
            y_fields=list(merged.get("y_fields") or default_plan.y_fields),
            category_field=merged.get("category_field") or default_plan.category_field,
            sort_by=merged.get("sort_by") or default_plan.sort_by,
            sort_ascending=bool(merged.get("sort_ascending", default_plan.sort_ascending)),
            top_n=merged.get("top_n"),
            should_draw=bool(merged.get("should_draw", default_plan.should_draw)),
        ))
    except Exception:
        return _sanitize_chart_plan(dataframe, default_plan)


def render_chart(output_dir: Path, question_id: str, dataframe: pd.DataFrame, plan: ChartPlan, image_index: int = 1) -> str:
    if dataframe.empty or not plan.should_draw:
        return ""
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = output_dir / f"{question_id}_{image_index}.jpg"
    df = _prepare_dataframe_for_plan(dataframe, plan)
    if df.empty:
        return ""
    if not plan.y_fields:
        return ""
    for field in plan.y_fields:
        if field not in df.columns:
            return ""
    if plan.chart_type == "line" and (not plan.x_field or plan.x_field not in df.columns):
        return ""
    if plan.chart_type == "scatter" and ((not plan.x_field or plan.x_field not in df.columns) or not plan.y_fields or plan.y_fields[0] not in df.columns):
        return ""
    if plan.chart_type in {"bar", "barh", "grouped_bar"} and (not plan.category_field or plan.category_field not in df.columns):
        return ""
    if plan.chart_type == "table" and df.empty:
        return ""

    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(10.5, 6), dpi=150)
    ax = fig.add_subplot(111)
    title = "\n".join(textwrap.wrap(plan.title, width=28))
    palette = ["#295C8E", "#4F8FBF", "#74B3CE", "#F4A259", "#BC4B51", "#6D597A"]

    if plan.chart_type == "line":
        axis_suffix = ""
        if plan.category_field and plan.category_field in df.columns and df[plan.category_field].nunique() > 1:
            for idx, (series_name, group) in enumerate(df.groupby(plan.category_field, sort=False)):
                group = group.copy()
                x = group[plan.x_field].astype(str).tolist()
                y, axis_suffix = _scale_series_for_plot(plan.y_fields[0], group[plan.y_fields[0]])
                ax.plot(x, y, marker="o", linewidth=2.0, color=palette[idx % len(palette)], label=str(series_name))
        else:
            x = df[plan.x_field].astype(str).tolist()
            y, axis_suffix = _scale_series_for_plot(plan.y_fields[0], df[plan.y_fields[0]])
            ax.plot(x, y, marker="o", linewidth=2.4, color=palette[0], label=plan.y_fields[0])
        ax.tick_params(axis="x", rotation=30)
        if axis_suffix:
            ax.set_ylabel(axis_suffix, fontproperties=FONT_PROP)
        if len(plan.y_fields) > 0:
            ax.legend(frameon=False, prop=FONT_PROP)
    elif plan.chart_type == "scatter":
        x_values = pd.to_numeric(_column_as_series(df, plan.x_field), errors="coerce")
        y_values = pd.to_numeric(_column_as_series(df, plan.y_fields[0]), errors="coerce")
        valid = x_values.notna() & y_values.notna()
        if valid.sum() < 2:
            plt.close(fig)
            return ""
        x_scaled, x_suffix = _scale_series_for_plot(plan.x_field or "", x_values[valid])
        y_scaled, y_suffix = _scale_series_for_plot(plan.y_fields[0], y_values[valid])
        ax.scatter(x_scaled, y_scaled, color=palette[0], alpha=0.85, s=36)
        if plan.category_field and plan.category_field in df.columns:
            labels = df.loc[valid, plan.category_field].astype(str).tolist()
            for xv, yv, label in zip(x_scaled.tolist(), y_scaled.tolist(), labels):
                ax.text(xv, yv, label, fontsize=7, fontproperties=FONT_PROP)
        ax.set_xlabel(x_suffix or plan.x_field or "", fontproperties=FONT_PROP)
        ax.set_ylabel(y_suffix or plan.y_fields[0], fontproperties=FONT_PROP)
    elif plan.chart_type == "pie":
        labels = df[plan.category_field].astype(str).tolist()
        values, suffix = _scale_series_for_plot(plan.y_fields[0], df[plan.y_fields[0]])
        values = values.clip(lower=0)
        if float(values.sum()) <= 0:
            return ""
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, textprops={"fontproperties": FONT_PROP} if FONT_PROP else None)
        ax.axis("equal")
    elif plan.chart_type == "table":
        ax.axis("off")
        display = df.head(plan.top_n or 12).copy()
        for column in display.columns:
            numeric = pd.to_numeric(display[column], errors="coerce")
            if numeric.notna().sum() > 0:
                display[column] = numeric.map(lambda x: _format_numeric_label(x) if pd.notna(x) else "")
        table = ax.table(
            cellText=display.astype(str).values.tolist(),
            colLabels=[str(col) for col in display.columns],
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.3)
        if FONT_PROP:
            for (_, _), cell in table.get_celld().items():
                cell.get_text().set_fontproperties(FONT_PROP)
    else:
        labels = df[plan.category_field].astype(str).tolist()
        values, suffix = _scale_series_for_plot(plan.y_fields[0], df[plan.y_fields[0]])
        bars = ax.bar(labels, values, color=palette[: len(labels)])
        ax.tick_params(axis="x", rotation=30)
        for bar, value in zip(bars, values.tolist()):
            ax.text(bar.get_x() + bar.get_width() / 2, value, f"{_format_numeric_label(value)}{suffix}", ha="center", va="bottom", fontproperties=FONT_PROP, fontsize=9)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=14, fontproperties=FONT_PROP)
    _apply_font_to_axes(ax)
    fig.tight_layout()
    fig.savefig(chart_path, format="jpg", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(chart_path)


def _infer_chart_type(question_text: str, dataframe: pd.DataFrame) -> str | None:
    if "表格" in question_text:
        return "table"
    if "散点图" in question_text:
        return "scatter"
    if any(token in question_text for token in ["趋势", "折线图"]):
        return "line"
    if "饼图" in question_text:
        return "pie"
    if any(token in question_text for token in ["柱状图", "条形图", "排名", "前十", "前五", "前三", "排序"]):
        return "bar"
    if len(dataframe) > 20 and len(dataframe.columns) >= 6:
        return "table"
    if "report_period" in dataframe.columns and dataframe["report_period"].nunique() > 1:
        return "line"
    return None


def _should_force_table(question_text: str, dataframe: pd.DataFrame, numeric_cols: list[str]) -> bool:
    if "表格" in question_text:
        return True
    if len(dataframe) > 20 and len(dataframe.columns) >= 6:
        return True
    if len(dataframe) > 15 and len(numeric_cols) >= 3:
        return True
    if any(token in question_text for token in ["亏钱", "为负", "负数", "亏损"]) and numeric_cols:
        if _bar_values_too_skewed(dataframe, numeric_cols[0]):
            return True
    return False


def _preferred_non_table_chart_type(question_text: str, dataframe: pd.DataFrame) -> str:
    if any(token in question_text for token in ["亏钱", "为负", "负数", "哪些企业", "哪些公司", "列表"]):
        return "bar"
    if len(dataframe) <= 1:
        return "bar"
    if "report_period" in dataframe.columns and dataframe["report_period"].nunique() > 1:
        return "line"
    if any(token in question_text for token in ["排名", "前十", "前五", "前三", "排序", "对比", "柱状图", "条形图"]):
        return "bar"
    if "stock_abbr" in dataframe.columns:
        return "bar"
    return "line"


def _should_preserve_dataframe_order(question_text: str, dataframe: pd.DataFrame) -> bool:
    if "rank" in dataframe.columns:
        return False
    if any(token in question_text for token in ["前三", "前五", "前十", "排名", "top"]):
        return True
    return False


def _normalize_chart_type(chart_type: str | None, dataframe: pd.DataFrame) -> str | None:
    if chart_type in {None, "line", "bar", "pie", "table", "scatter"}:
        return chart_type
    if chart_type in {"barh", "grouped_bar", "radar", "hist", "box"}:
        if "report_period" in dataframe.columns and dataframe["report_period"].nunique() > 1 and chart_type == "radar":
            return "bar"
        return "bar"
    return "bar"


def _numeric_columns(dataframe: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for column in dataframe.columns:
        if pd.to_numeric(_column_as_series(dataframe, column), errors="coerce").notna().sum() > 0:
            cols.append(column)
    return cols


def _prepare_dataframe_for_plan(dataframe: pd.DataFrame, plan: ChartPlan) -> pd.DataFrame:
    work = dataframe.copy()
    if plan.sort_by and plan.sort_by in work.columns:
        numeric = pd.to_numeric(_column_as_series(work, plan.sort_by), errors="coerce")
        if numeric.notna().sum() > 0:
            work = work.assign(_sort_key=numeric).sort_values("_sort_key", ascending=plan.sort_ascending).drop(columns=["_sort_key"])
        else:
            work = work.sort_values(plan.sort_by, ascending=plan.sort_ascending)
    if plan.top_n:
        work = work.head(plan.top_n)
    return work


def _sanitize_chart_plan(dataframe: pd.DataFrame, plan: ChartPlan | None) -> ChartPlan | None:
    if plan is None or dataframe.empty:
        return plan
    numeric_cols = _numeric_columns(dataframe)
    if not numeric_cols:
        return None
    plan = ChartPlan(
        chart_type=_normalize_chart_type(plan.chart_type, dataframe) or "bar",
        title=plan.title,
        x_field=plan.x_field,
        y_fields=list(plan.y_fields),
        category_field=plan.category_field,
        sort_by=plan.sort_by,
        sort_ascending=plan.sort_ascending,
        top_n=plan.top_n,
        should_draw=plan.should_draw,
    )
    plan.y_fields = [field for field in plan.y_fields if field in dataframe.columns and field in numeric_cols]
    if not plan.y_fields:
        plan.y_fields = [numeric_cols[0]]
    if plan.chart_type == "line":
        if not plan.x_field or plan.x_field not in dataframe.columns:
            plan.x_field = "report_period" if "report_period" in dataframe.columns else dataframe.columns[0]
        plan.category_field = None
    elif plan.chart_type == "scatter":
        if not plan.x_field or plan.x_field not in dataframe.columns or plan.x_field not in numeric_cols:
            plan.x_field = next((col for col in numeric_cols if col != plan.y_fields[0]), numeric_cols[0])
        plan.category_field = plan.category_field if plan.category_field in dataframe.columns else ("stock_abbr" if "stock_abbr" in dataframe.columns else None)
        plan.sort_by = None
    else:
        candidate_category = plan.category_field
        if not candidate_category or candidate_category not in dataframe.columns or candidate_category in numeric_cols:
            for candidate in ["stock_abbr", "report_period", "stock_code"]:
                if candidate in dataframe.columns and candidate not in numeric_cols:
                    candidate_category = candidate
                    break
            if not candidate_category:
                candidate_category = next((col for col in dataframe.columns if col not in numeric_cols), dataframe.columns[0])
        plan.category_field = candidate_category
        plan.x_field = None
    if plan.sort_by is not None and plan.sort_by not in dataframe.columns:
        plan.sort_by = None
    if plan.chart_type == "bar" and plan.y_fields:
        if _bar_values_too_skewed(dataframe, plan.y_fields[0]):
            plan.chart_type = "table"
            plan.top_n = min(plan.top_n or len(dataframe), 15)
    if plan.chart_type == "bar" and plan.top_n is None and plan.category_field in dataframe.columns:
        unique_count = dataframe[plan.category_field].astype(str).nunique()
        if unique_count > 12:
            plan.top_n = 12
    return plan


def _build_title(question_text: str, suffix: str) -> str:
    base = question_text.replace("|", " ").replace("**", "").strip()
    if len(base) > 24:
        base = base[:24] + "..."
    return f"{base} - {suffix}"


def _format_numeric_label(value: float) -> str:
    abs_value = abs(float(value))
    if abs_value >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.2f}"


def _scale_series_for_plot(field_name: str, series: pd.Series) -> tuple[pd.Series, str]:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0)
    field_lower = field_name.lower()
    ratio_like = any(token in field_lower for token in ["ratio", "margin", "growth", "roe", "per_share", "percent"])
    if ratio_like:
        return numeric, "%"
    max_abs = numeric.abs().max() if not numeric.empty else 0
    if max_abs >= 1e5:
        return numeric / 10000, "（万元）"
    return numeric, ""


def _apply_font_to_axes(ax) -> None:
    if FONT_PROP is None:
        return
    for label in ax.get_xticklabels():
        label.set_fontproperties(FONT_PROP)
    for label in ax.get_yticklabels():
        label.set_fontproperties(FONT_PROP)
    ax.xaxis.label.set_fontproperties(FONT_PROP)
    ax.yaxis.label.set_fontproperties(FONT_PROP)
    legend = ax.get_legend()
    if legend is not None:
        for text in legend.get_texts():
            text.set_fontproperties(FONT_PROP)


def _bar_values_too_skewed(dataframe: pd.DataFrame, field_name: str) -> bool:
    if field_name not in dataframe.columns:
        return False
    numeric = pd.to_numeric(_column_as_series(dataframe, field_name), errors="coerce").dropna().abs()
    numeric = numeric[numeric > 0]
    if len(numeric) < 5:
        return False
    median = float(numeric.median())
    if median <= 0:
        return False
    max_value = float(numeric.max())
    return max_value / median >= 50


__all__ = ["ChartPlan", "build_default_chart_plan", "chart_type_to_label", "refine_chart_plan_with_llm", "render_chart"]


def _column_as_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
    value = dataframe[column]
    if isinstance(value, pd.DataFrame):
        return value.iloc[:, 0]
    return value
