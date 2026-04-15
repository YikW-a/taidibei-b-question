from __future__ import annotations

import json
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from .charts import ChartPlan
from .charts import FONT_PROP, _apply_font_to_axes, _format_numeric_label, _scale_series_for_plot


FIELD_LABELS = {
    "stock_abbr": "公司简称",
    "stock_code": "股票代码",
    "report_period": "报告期",
    "net_profit": "净利润",
    "total_operating_revenue": "营业总收入",
    "investing_cf_net_amount": "投资性现金流量净额",
    "gross_profit_margin": "销售毛利率",
    "net_profit_margin": "销售净利率",
    "avg_gross_profit_margin": "行业平均销售毛利率",
    "avg_net_profit_margin": "行业平均销售净利率",
    "rnd_expense_ratio": "研发费用占比",
    "asset_cash_and_cash_equivalents": "货币资金",
    "liability_short_term_loans": "短期借款",
    "cash_to_total_assets_ratio": "货币资金占总资产比例",
    "net_profit_yoy_growth_rate": "净利润同比增长率",
    "net_profit_yoy_growth_rate_2024": "2024Q3净利润同比增长率",
    "net_profit_yoy_growth_rate_2025": "2025Q3净利润同比增长率",
    "net_profit_yoy_growth_2024": "2024Q3净利润同比增长率",
    "net_profit_yoy_growth_2025": "2025Q3净利润同比增长率",
}


@dataclass
class DataRef:
    dataset_name: str
    row_count: int
    preview_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TransformSpec:
    sort_by: str | None = None
    sort_ascending: bool = True
    top_n: int | None = None
    filters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EncodingSpec:
    field: str | None = None
    data_type: str = "quantitative"
    label: str | None = None
    unit: str | None = None


@dataclass
class LayoutSpec:
    width: float = 10.5
    height: float = 6.0
    dpi: int = 150
    legend: bool = True
    rotate_xticks: int = 30
    show_value_labels: bool = True


@dataclass
class OutputSpec:
    filename: str
    image_format: str = "jpg"
    relative_path: str | None = None


@dataclass
class ChartSpec:
    schema_version: str
    question_id: str
    image_index: int
    chart_type: str
    title: str
    data: DataRef
    transforms: TransformSpec
    encodings: dict[str, EncodingSpec]
    layout: LayoutSpec
    output: OutputSpec
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["encodings"] = {key: asdict(value) for key, value in self.encodings.items()}
        return payload


def build_chart_spec(
    question_id: str,
    dataframe: pd.DataFrame,
    plan: ChartPlan,
    image_index: int = 1,
    sql: str | None = None,
) -> ChartSpec | None:
    if dataframe.empty or not plan.should_draw:
        return None

    value_fields = [field for field in (plan.y_fields or []) if field in dataframe.columns]
    chart_type = _normalize_chart_type(plan.chart_type)
    value_field = plan.y_fields[0] if plan.y_fields else _first_numeric_column(dataframe)
    if chart_type != "table" and value_field is None:
        return None
    if len(dataframe) <= 1 and chart_type != "table":
        if len(value_fields) >= 2:
            chart_type = "bar"
        else:
            return None

    category_field = plan.category_field
    if chart_type in {"bar", "pie", "table"} and (not category_field or category_field not in dataframe.columns):
        category_field = _first_dimension_column(dataframe)
    x_field = plan.x_field
    if chart_type == "line" and (not x_field or x_field not in dataframe.columns):
        x_field = "report_period" if "report_period" in dataframe.columns else _first_dimension_column(dataframe)
    if chart_type == "line":
        enough_points = (
            x_field in dataframe.columns
            and dataframe[x_field].dropna().astype(str).nunique() >= 2
            and len(dataframe) >= 2
        )
        if not enough_points:
            if len(value_fields) >= 2:
                chart_type = "bar"
            else:
                return None

    series_field = None
    period_field = "report_period" if "report_period" in dataframe.columns else ("period" if "period" in dataframe.columns else None)
    if chart_type == "line" and "stock_abbr" in dataframe.columns and dataframe["stock_abbr"].nunique() > 1:
        series_field = "stock_abbr"
    if chart_type == "bar" and period_field and "stock_abbr" in dataframe.columns and dataframe[period_field].nunique() > 1:
        if category_field == period_field or category_field is None:
            category_field = "stock_abbr"
        series_field = period_field

    encodings: dict[str, EncodingSpec] = {}
    if value_field is not None:
        encodings["value"] = EncodingSpec(
            field=value_field,
            data_type="quantitative",
            label=_field_label(value_field),
            unit=_infer_unit(value_field, dataframe[value_field]),
        )
        if chart_type == "line":
            encodings["x"] = EncodingSpec(field=x_field, data_type="temporal", label=_field_label(x_field))
        else:
            encodings["category"] = EncodingSpec(field=category_field, data_type="nominal", label=_field_label(category_field))
    if series_field:
        encodings["series"] = EncodingSpec(field=series_field, data_type="nominal", label=_field_label(series_field))

    output_name = f"{question_id}_{image_index}.jpg"
    meta = {
        "source_sql": sql or "",
        "value_fields": list(value_fields or ([value_field] if value_field else [])),
        "value_labels": [_field_label(field) for field in (value_fields or ([value_field] if value_field else [])) if field],
        "original_chart_plan": {
            "chart_type": plan.chart_type,
            "x_field": plan.x_field,
            "y_fields": plan.y_fields,
            "category_field": plan.category_field,
            "sort_by": plan.sort_by,
            "sort_ascending": plan.sort_ascending,
            "top_n": plan.top_n,
        },
    }
    if chart_type == "bar" and category_field and category_field in dataframe.columns and dataframe[category_field].duplicated().any():
        numeric = pd.to_numeric(dataframe[value_field], errors="coerce").dropna() if value_field else pd.Series(dtype=float)
        if not numeric.empty:
            meta["category_aggregate"] = "min" if numeric.quantile(0.75) <= 0 else "max"

    return ChartSpec(
        schema_version="task2.chart-spec.v2",
        question_id=question_id,
        image_index=image_index,
        chart_type=chart_type,
        title=plan.title,
        data=DataRef(
            dataset_name="financials_view.result",
            row_count=len(dataframe),
            preview_rows=dataframe.head(12).to_dict(orient="records"),
        ),
        transforms=TransformSpec(
            sort_by=plan.sort_by,
            sort_ascending=plan.sort_ascending,
            top_n=plan.top_n,
        ),
        encodings=encodings,
        layout=LayoutSpec(
            legend=bool(series_field),
            rotate_xticks=30 if chart_type != "pie" else 0,
            show_value_labels=chart_type in {"bar", "pie"},
        ),
        output=OutputSpec(
            filename=output_name,
            relative_path=f"./result/{output_name}",
        ),
        meta=meta,
    )


def save_chart_spec(output_dir: Path, spec: ChartSpec) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{spec.question_id}_{spec.image_index}.spec.json"
    path.write_text(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_chart_from_spec(output_dir: Path, dataframe: pd.DataFrame, spec: ChartSpec) -> str:
    if dataframe.empty:
        return ""
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = output_dir / spec.output.filename

    df = _apply_spec_transforms(dataframe, spec)
    if df.empty:
        return ""

    chart_type = spec.chart_type
    value_encoding = spec.encodings.get("value")
    if chart_type != "table" and (value_encoding is None or not value_encoding.field or value_encoding.field not in df.columns):
        return ""

    title = "\n".join(textwrap.wrap(spec.title, width=24))
    palette = ["#295C8E", "#4F8FBF", "#74B3CE", "#F4A259", "#BC4B51", "#6D597A"]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(spec.layout.width, spec.layout.height), dpi=spec.layout.dpi)
    ax = fig.add_subplot(111)

    if chart_type == "line":
        x_encoding = spec.encodings.get("x")
        if x_encoding is None or not x_encoding.field or x_encoding.field not in df.columns:
            return ""
        series_encoding = spec.encodings.get("series")
        axis_suffix = ""
        if series_encoding and series_encoding.field and series_encoding.field in df.columns and df[series_encoding.field].nunique() > 1:
            for idx, (series_name, group) in enumerate(df.groupby(series_encoding.field, sort=False)):
                x = group[x_encoding.field].astype(str).tolist()
                y, axis_suffix = _scale_series_for_plot(value_encoding.field, group[value_encoding.field])
                ax.plot(x, y, marker="o", linewidth=2.0, color=palette[idx % len(palette)], label=str(series_name))
        else:
            x = df[x_encoding.field].astype(str).tolist()
            y, axis_suffix = _scale_series_for_plot(value_encoding.field, df[value_encoding.field])
            ax.plot(x, y, marker="o", linewidth=2.4, color=palette[0], label=value_encoding.label or value_encoding.field)
        ax.tick_params(axis="x", rotation=spec.layout.rotate_xticks)
        if axis_suffix:
            ax.set_ylabel(axis_suffix, fontproperties=FONT_PROP)
        if spec.layout.legend:
            ax.legend(frameon=False, prop=FONT_PROP)
    elif chart_type == "pie":
        category_encoding = spec.encodings.get("category")
        if category_encoding is None or not category_encoding.field or category_encoding.field not in df.columns:
            return ""
        labels = df[category_encoding.field].astype(str).tolist()
        values, _ = _scale_series_for_plot(value_encoding.field, df[value_encoding.field])
        values = values.clip(lower=0)
        if float(values.sum()) <= 0:
            return ""
        ax.pie(
            values,
            labels=labels,
            autopct="%1.1f%%",
            startangle=90,
            textprops={"fontproperties": FONT_PROP} if FONT_PROP else None,
        )
        ax.axis("equal")
    elif chart_type == "table":
        category_encoding = spec.encodings.get("category")
        columns = []
        if category_encoding and category_encoding.field and category_encoding.field in df.columns:
            columns.append(category_encoding.field)
        for field_name in spec.meta.get("value_fields") or []:
            if field_name in df.columns and field_name not in columns:
                columns.append(field_name)
        if not columns:
            columns = list(df.columns[: min(6, len(df.columns))])
        display = df[columns].head(spec.transforms.top_n or 12).copy()
        for column in display.columns:
            numeric = pd.to_numeric(display[column], errors="coerce")
            if numeric.notna().sum() > 0:
                display[column] = numeric.map(lambda x: _format_numeric_label(x) if pd.notna(x) else "")
        ax.axis("off")
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
        category_encoding = spec.encodings.get("category")
        if category_encoding is None or not category_encoding.field or category_encoding.field not in df.columns:
            return ""
        series_encoding = spec.encodings.get("series")
        if series_encoding and series_encoding.field and series_encoding.field in df.columns and len(spec.meta.get("value_fields") or []) == 1:
            value_field_name = (spec.meta.get("value_fields") or [value_encoding.field])[0]
            pivot = (
                df[[category_encoding.field, series_encoding.field, value_field_name]]
                .dropna(subset=[category_encoding.field, series_encoding.field])
                .pivot_table(
                    index=category_encoding.field,
                    columns=series_encoding.field,
                    values=value_field_name,
                    aggfunc="first",
                )
                .fillna(0)
            )
            if pivot.empty:
                return ""
            labels = pivot.index.astype(str).tolist()
            x = range(len(labels))
            width = 0.8 / max(len(pivot.columns), 1)
            suffix = ""
            for idx, series_name in enumerate(pivot.columns.tolist()):
                values, suffix = _scale_series_for_plot(value_field_name, pivot[series_name])
                offsets = [item + (idx - (len(pivot.columns) - 1) / 2) * width for item in x]
                bars = ax.bar(offsets, values, width=width, color=palette[idx % len(palette)], label=_field_label(series_name))
                if spec.layout.show_value_labels:
                    for bar, value in zip(bars, values.tolist()):
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            value,
                            f"{_format_numeric_label(value)}{suffix}",
                            ha="center",
                            va="bottom",
                            fontproperties=FONT_PROP,
                            fontsize=8,
                        )
            ax.set_xticks(list(x))
            ax.set_xticklabels(labels)
            ax.legend(frameon=False, prop=FONT_PROP)
            ax.tick_params(axis="x", rotation=spec.layout.rotate_xticks)
            ax.margins(y=0.18)
            if value_encoding and value_encoding.unit:
                ax.set_ylabel(f"数值{value_encoding.unit}", fontproperties=FONT_PROP)
            ax.set_title(title, fontsize=14, fontweight="bold", pad=14, fontproperties=FONT_PROP)
            _apply_font_to_axes(ax)
            fig.tight_layout(rect=[0, 0, 1, 0.95])
            fig.savefig(chart_path, format=spec.output.image_format, dpi=spec.layout.dpi, bbox_inches="tight")
            plt.close(fig)
            return str(chart_path)
        labels = df[category_encoding.field].astype(str).tolist()
        value_fields = [
            field for field in (spec.meta.get("value_fields") or [value_encoding.field]) if field and field in df.columns
        ]
        value_labels = {
            field: label
            for field, label in zip(
                (spec.meta.get("value_fields") or [value_encoding.field]),
                (spec.meta.get("value_labels") or []),
            )
        }
        if len(value_fields) > 1:
            if not (category_encoding and category_encoding.field and category_encoding.field in df.columns):
                labels = [value_labels.get(field_name, _field_label(field_name)) for field_name in value_fields]
                row = df.iloc[0]
                values = [pd.to_numeric(pd.Series([row[field_name]]), errors="coerce").fillna(0).iloc[0] for field_name in value_fields]
                scaled_values, suffix = _scale_series_for_plot(value_fields[0], pd.Series(values))
                bars = ax.bar(labels, scaled_values, color=palette[: len(labels)])
                if spec.layout.show_value_labels:
                    for bar, value in zip(bars, scaled_values.tolist()):
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            value,
                            f"{_format_numeric_label(value)}{suffix}",
                            ha="center",
                            va="bottom",
                            fontproperties=FONT_PROP,
                            fontsize=9,
                        )
                ax.tick_params(axis="x", rotation=spec.layout.rotate_xticks)
                if value_encoding.unit:
                    ax.set_ylabel(f"数值{value_encoding.unit}", fontproperties=FONT_PROP)
                ax.set_title(title, fontsize=14, fontweight="bold", pad=14, fontproperties=FONT_PROP)
                _apply_font_to_axes(ax)
                fig.tight_layout(rect=[0, 0, 1, 0.95])
                fig.savefig(chart_path, format=spec.output.image_format, dpi=spec.layout.dpi, bbox_inches="tight")
                plt.close(fig)
                return str(chart_path)
            x = range(len(labels))
            width = 0.8 / max(len(value_fields), 1)
            suffix = ""
            for idx, field_name in enumerate(value_fields):
                values, suffix = _scale_series_for_plot(field_name, df[field_name])
                offsets = [item + (idx - (len(value_fields) - 1) / 2) * width for item in x]
                bars = ax.bar(
                    offsets,
                    values,
                    width=width,
                    color=palette[idx % len(palette)],
                    label=value_labels.get(field_name, _field_label(field_name)),
                )
                if spec.layout.show_value_labels:
                    for bar, value in zip(bars, values.tolist()):
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            value,
                            f"{_format_numeric_label(value)}{suffix}",
                            ha="center",
                            va="bottom",
                            fontproperties=FONT_PROP,
                            fontsize=8,
                        )
            ax.set_xticks(list(x))
            ax.set_xticklabels(labels)
            ax.legend(frameon=False, prop=FONT_PROP)
        else:
            values, suffix = _scale_series_for_plot(value_encoding.field, df[value_encoding.field])
            bars = ax.bar(labels, values, color=palette[: len(labels)])
            if spec.layout.show_value_labels:
                for bar, value in zip(bars, values.tolist()):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        value,
                        f"{_format_numeric_label(value)}{suffix}",
                        ha="center",
                        va="bottom",
                        fontproperties=FONT_PROP,
                        fontsize=9,
                    )
        ax.tick_params(axis="x", rotation=spec.layout.rotate_xticks)
        ax.margins(y=0.18)
        if value_encoding.unit:
            ax.set_ylabel(f"数值{value_encoding.unit}", fontproperties=FONT_PROP)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=14, fontproperties=FONT_PROP)
    _apply_font_to_axes(ax)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(chart_path, format=spec.output.image_format, dpi=spec.layout.dpi, bbox_inches="tight")
    plt.close(fig)
    return str(chart_path)


def _normalize_chart_type(chart_type: str | None) -> str:
    if chart_type in {"line", "bar", "pie", "table"}:
        return chart_type
    if chart_type in {"barh", "grouped_bar", "radar", "scatter", "hist", "box"}:
        return "bar"
    return "bar"


def _first_numeric_column(dataframe: pd.DataFrame) -> str | None:
    for column in dataframe.columns:
        if pd.to_numeric(dataframe[column], errors="coerce").notna().sum() > 0:
            return str(column)
    return None


def _first_dimension_column(dataframe: pd.DataFrame) -> str | None:
    numeric_columns = {
        column for column in dataframe.columns if pd.to_numeric(dataframe[column], errors="coerce").notna().sum() > 0
    }
    for candidate in ["stock_abbr", "report_period", "stock_code"]:
        if candidate in dataframe.columns and candidate not in numeric_columns:
            return candidate
    for column in dataframe.columns:
        if column not in numeric_columns:
            return str(column)
    return str(dataframe.columns[0]) if len(dataframe.columns) else None


def _infer_unit(field_name: str, series: pd.Series) -> str | None:
    field_lower = str(field_name).lower()
    if any(token in field_lower for token in ["ratio", "margin", "growth", "roe", "率", "占比"]):
        return "%"
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        return None
    if numeric.abs().max() >= 1e5:
        return "万元"
    return None


def _apply_spec_transforms(dataframe: pd.DataFrame, spec: ChartSpec) -> pd.DataFrame:
    work = dataframe.copy()
    category_encoding = spec.encodings.get("category")
    value_encoding = spec.encodings.get("value")
    aggregate_mode = spec.meta.get("category_aggregate")
    if (
        aggregate_mode in {"min", "max"}
        and category_encoding
        and value_encoding
        and category_encoding.field in work.columns
        and value_encoding.field in work.columns
    ):
        numeric = pd.to_numeric(work[value_encoding.field], errors="coerce")
        work = work.assign(_value_numeric=numeric)
        if aggregate_mode == "min":
            agg = work.groupby(category_encoding.field, as_index=False)["_value_numeric"].min()
        else:
            agg = work.groupby(category_encoding.field, as_index=False)["_value_numeric"].max()
        work = agg.rename(columns={"_value_numeric": value_encoding.field})
    sort_by = spec.transforms.sort_by
    if sort_by and sort_by in work.columns:
        numeric = pd.to_numeric(work[sort_by], errors="coerce")
        if numeric.notna().sum() > 0:
            work = work.assign(_sort_key=numeric).sort_values("_sort_key", ascending=spec.transforms.sort_ascending).drop(columns=["_sort_key"])
        else:
            work = work.sort_values(sort_by, ascending=spec.transforms.sort_ascending)
    series_encoding = spec.encodings.get("series")
    if spec.transforms.top_n:
        if series_encoding and series_encoding.field and series_encoding.field in work.columns:
            work = work.groupby(series_encoding.field, group_keys=False).head(spec.transforms.top_n)
        else:
            work = work.head(spec.transforms.top_n)
    return work


def _field_label(field_name: str | None) -> str | None:
    if not field_name:
        return field_name
    if field_name in FIELD_LABELS:
        return FIELD_LABELS[field_name]
    return str(field_name)


__all__ = ["ChartSpec", "build_chart_spec", "render_chart_from_spec", "save_chart_spec"]
