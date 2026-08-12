"""Chart selection and Plotly figure construction.

Colour use follows a validated palette (CVD-checked): categorical slots in
fixed order, an ordinal blue ramp for current-vs-prior periods, and a
blue/red diverging pair for movements. Meaning never relies on colour
alone - movements carry signed direct labels and every chart is paired
with its data table in the UI.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from models.evidence import ChartSpec
from services.catalogue import get_catalogue
from services.diagnostics import ShapedResult
from services.formatting import display_unit, fmt_year, is_integer_field

MAX_CHART_CATEGORIES = 25

CHART_TITLE_OPERATION_LABELS = {
    "compare": "Movement", "trend": "Trend", "rank": "Ranking",
    "share_of_total": "Share of Total",
    "contribution_to_movement": "Contribution to Movement",
}

PALETTES = {
    "light": {
        "categorical": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                        "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
        "current": "#2a78d6", "prior": "#86b6ef",
        "positive": "#2a78d6", "negative": "#e34948",
        "surface": "rgba(0,0,0,0)", "ink": "#0b0b0b", "ink2": "#52514e",
        "muted": "#898781", "grid": "#e1e0d9", "baseline": "#c3c2b7",
    },
    "dark": {
        "categorical": ["#3987e5", "#d95926", "#199e70", "#c98500",
                        "#d55181", "#008300", "#9085e9", "#e66767"],
        "current": "#3987e5", "prior": "#1c5cab",
        "positive": "#3987e5", "negative": "#e66767",
        "surface": "rgba(0,0,0,0)", "ink": "#ece9e0", "ink2": "#bebcb2",
        "muted": "#918f88", "grid": "#2c2c2a", "baseline": "#383835",
    },
    # Meme mode: a full saturated spectrum, matching the page. Series colours
    # are no longer CVD-validated here, which is an accepted trade for a
    # deliberately unserious theme - the paired table below every chart, and
    # the signed value labels on movement bars, carry the meaning without
    # relying on hue. The plotting surface stays near-opaque white so the
    # animated background cannot render the axes unreadable.
    "rainbow": {
        "categorical": ["#ff0040", "#ff7a00", "#ffe600", "#20e000",
                        "#00e5d0", "#0066ff", "#8c00ff", "#ff00c8"],
        "current": "#8c00ff", "prior": "#ff00c8",
        "positive": "#00a838", "negative": "#ff0040",
        "surface": "rgba(255,255,255,0.94)", "ink": "#12071c", "ink2": "#2c1440",
        "muted": "#6a4a86", "grid": "#e6ccf5", "baseline": "#8c00ff",
    },
}


def _auto_chart(result: ShapedResult) -> str | None:
    op = result.operation
    df = result.df
    if df.empty or not result.measures:
        return None
    if op == "list_changes":
        return None
    if op == "trend":
        return "line"
    if "absolute_change" in df.columns and result.group_by:
        vals = [v for v in df["absolute_change"] if v is not None and not
                (isinstance(v, float) and math.isnan(v))]
        if vals and min(vals) < 0 < max(vals):
            return "diverging_bar"
        return "grouped_bar"
    if result.group_by:
        if len(result.group_by) >= 2:
            return "stacked_bar"
        return "bar"
    return None


def choose_chart(result: ShapedResult, requested: str) -> str | None:
    if requested == "none":
        return None
    auto = _auto_chart(result)
    if requested == "auto":
        return auto
    if auto is None and result.df.empty:
        return None
    # An explicit request is honoured when the shape supports it.
    supported = {"bar", "grouped_bar", "diverging_bar", "line", "stacked_bar"}
    if requested in supported:
        if requested == "line" and result.operation != "trend" and "review" not in result.df.columns:
            return auto
        if requested in ("grouped_bar", "diverging_bar") and \
                "absolute_change" not in result.df.columns and len(result.periods) < 2:
            return auto if auto else ("bar" if result.group_by else None)
        return requested
    return auto


def default_chart_title(dataset: str, measures: list[str], group_by: list[str],
                        operation: str) -> str:
    """Deterministic fallback title naming the measure and grouping dimension.

    Used whenever the AI-drafted title is unavailable (fallback answer,
    drafting error, or a chart from a non-primary query plan).
    """
    cat = get_catalogue()
    measure = cat.measure_label(dataset, measures[0]) if measures else "Result"
    parts = [measure]
    op_label = CHART_TITLE_OPERATION_LABELS.get(operation)
    if op_label:
        parts.append(op_label)
    if group_by:
        parts.append("by " + ", ".join(cat.dimension_label(dataset, g)
                                       for g in group_by[:2]))
    return " ".join(parts)


def default_axis_label(dataset: str, field: str) -> str:
    """Deterministic axis title naming the dimension or field being plotted."""
    if field == "review":
        return "Review Period"
    cat = get_catalogue()
    if field in cat.dimensions(dataset) or field in cat.attributes(dataset):
        return cat.dimension_label(dataset, field)
    return field.replace("_", " ").title()


def build_chart_spec(result: ShapedResult, requested: str) -> ChartSpec | None:
    chart_type = choose_chart(result, requested)
    if chart_type is None:
        return None
    df = result.df
    if df.empty:
        return None
    m = result.measures[0] if result.measures else None
    x_field = None
    y_fields: list[str] = []

    if chart_type == "line":
        x_field = "review"
        y_fields = [m]
    elif chart_type == "diverging_bar":
        x_field = result.group_by[0] if result.group_by else None
        y_fields = ["absolute_change"]
    elif chart_type == "grouped_bar":
        if "current" in df.columns and "prior" in df.columns:
            x_field = result.group_by[0] if result.group_by else None
            y_fields = ["current", "prior"]
        else:
            x_field = result.group_by[0] if result.group_by else "review"
            y_fields = [m]
    elif chart_type == "stacked_bar":
        x_field = result.group_by[0] if result.group_by else None
        y_fields = [m]
    else:  # bar
        x_field = result.group_by[0] if result.group_by else ("review" if "review" in df.columns else None)
        y_fields = [m] if m and m in df.columns else (["current"] if "current" in df.columns else [])

    if not x_field or x_field not in df.columns or not y_fields:
        return None
    if df[x_field].nunique() > MAX_CHART_CATEGORIES:
        return None

    unit = result.unit
    keep = [c for c in dict.fromkeys(
        [x_field] + result.group_by[1:2] + y_fields) if c in df.columns]
    data = df[keep].to_dict(orient="records")
    cat = get_catalogue()
    return ChartSpec(
        chart_type=chart_type,
        title=default_chart_title(result.dataset, result.measures,
                                  result.group_by, result.operation),
        x_field=x_field,
        x_label=default_axis_label(result.dataset, x_field),
        y_fields=y_fields,
        y_label=cat.measure_label(result.dataset, m) if m else "",
        unit=unit,
        data=data,
        series_field=result.group_by[1] if (chart_type in ("line", "stacked_bar")
                                            and len(result.group_by) > 1) else (
            result.group_by[0] if chart_type == "line" and result.group_by else None),
        period_labels=result.period_labels,
    )


# ---------------------------------------------------------------------------
# Figure construction (theme-aware)
# ---------------------------------------------------------------------------

def _scale(values: list[float]) -> tuple[list[float], str]:
    """Convert GBP values to millions for display."""
    return [None if v is None else v / 1e6 for v in values], "GBP m"


def _layout(fig: go.Figure, pal: dict, y_title: str, x_title: str = ""):
    fig.update_layout(
        template=None,
        paper_bgcolor=pal["surface"], plot_bgcolor=pal["surface"],
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif',
                  size=12.5, color=pal["ink2"]),
        margin=dict(l=54, r=14, t=30, b=42),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=12, color=pal["ink2"]), bgcolor="rgba(0,0,0,0)"),
        bargap=0.35, bargroupgap=0.12,
        height=340,
        hoverlabel=dict(font_size=12.5),
    )
    fig.update_xaxes(showgrid=False, linecolor=pal["baseline"], linewidth=1,
                     tickfont=dict(color=pal["muted"]), zeroline=False,
                     title=dict(text=x_title, font=dict(size=12, color=pal["muted"])),
                     automargin=True)
    fig.update_yaxes(showgrid=True, gridcolor=pal["grid"], gridwidth=1,
                     linecolor="rgba(0,0,0,0)",
                     tickfont=dict(color=pal["muted"]),
                     zeroline=True, zerolinecolor=pal["baseline"], zerolinewidth=1,
                     title=dict(text=y_title, font=dict(size=12, color=pal["muted"])),
                     tickformat=",.0f", automargin=True)
    return fig


def build_figure(spec: ChartSpec, theme: str = "light") -> go.Figure:
    pal = PALETTES.get(theme, PALETTES["light"])
    data = spec.data
    # Year/ordinal categories are rendered as bare labels ("2026"), never as
    # numeric axis values that would pick up separators or decimals.
    x_is_ordinal = is_integer_field(spec.x_field)
    x = [(fmt_year(row.get(spec.x_field)) if x_is_ordinal else row.get(spec.x_field))
         for row in data]
    is_gbp = spec.unit == "GBP"
    fig = go.Figure()

    def yvals(field: str) -> list[float]:
        vals = [row.get(field) for row in data]
        return [None if v is None else (v / 1e6 if is_gbp else v) for v in vals]

    unit_label = "GBP m" if is_gbp else display_unit(spec.unit)
    y_label = f"{spec.y_label} ({unit_label})" if spec.y_label else unit_label

    if spec.chart_type == "line":
        series_field = getattr(spec, "series_field", None)
        if series_field and series_field in (data[0] if data else {}):
            names = list(dict.fromkeys(row[series_field] for row in data))
            for i, name in enumerate(names):
                rows = [r for r in data if r[series_field] == name]
                fig.add_trace(go.Scatter(
                    x=[(fmt_year(r[spec.x_field]) if x_is_ordinal
                        else r[spec.x_field]) for r in rows],
                    y=[(r[spec.y_fields[0]] / 1e6 if is_gbp else r[spec.y_fields[0]])
                       if r[spec.y_fields[0]] is not None else None for r in rows],
                    mode="lines+markers", name=str(name),
                    line=dict(width=2, color=pal["categorical"][i % 8]),
                    marker=dict(size=7)))
        else:
            fig.add_trace(go.Scatter(
                x=x, y=yvals(spec.y_fields[0]), mode="lines+markers",
                name=y_label, showlegend=False,
                line=dict(width=2, color=pal["categorical"][0]),
                marker=dict(size=7)))

    elif spec.chart_type == "diverging_bar":
        vals = yvals(spec.y_fields[0])
        colors = [pal["negative"] if (v or 0) < 0 else pal["positive"] for v in vals]
        fig.add_trace(go.Bar(
            x=x, y=vals, marker_color=colors,
            marker_line=dict(width=0),
            text=[f"{v:+,.1f}" if v is not None else "" for v in vals],
            textposition="outside",
            textfont=dict(size=12, color=pal["ink2"]),
            cliponaxis=False, showlegend=False))
        y_label = (f"{spec.y_label} Movement ({unit_label})" if spec.y_label
                   else f"Movement ({unit_label})")

    elif spec.chart_type == "grouped_bar" and spec.y_fields == ["current", "prior"]:
        labels = spec.period_labels or ["Current", "Prior"]
        for i, (fld, color) in enumerate([("current", pal["current"]),
                                          ("prior", pal["prior"])]):
            fig.add_trace(go.Bar(
                x=x, y=yvals(fld),
                name=labels[i] if i < len(labels) else fld.title(),
                marker_color=color, marker_line=dict(width=0)))

    elif spec.chart_type == "stacked_bar":
        series_field = getattr(spec, "series_field", None)
        if series_field:
            names = list(dict.fromkeys(row[series_field] for row in data))
            def _cat(row):
                v = row[spec.x_field]
                return fmt_year(v) if x_is_ordinal else v

            cats = list(dict.fromkeys(_cat(row) for row in data))
            for i, name in enumerate(names):
                by_cat = {_cat(r): r[spec.y_fields[0]] for r in data
                          if r[series_field] == name}
                gap = "#fcfcfb" if theme == "light" else "#1a1a19"
                fig.add_trace(go.Bar(
                    x=cats,
                    y=[(by_cat.get(c, 0) / 1e6 if is_gbp else by_cat.get(c, 0))
                       for c in cats],
                    name=str(name),
                    marker_color=pal["categorical"][i % 8],
                    marker_line=dict(width=2, color=gap)))
            fig.update_layout(barmode="stack")
        else:
            fig.add_trace(go.Bar(x=x, y=yvals(spec.y_fields[0]),
                                 marker_color=pal["categorical"][0],
                                 showlegend=False))

    else:  # bar / grouped fallback
        for i, fld in enumerate(spec.y_fields):
            fig.add_trace(go.Bar(
                x=x, y=yvals(fld), name=fld.replace("_", " ").title(),
                marker_color=pal["categorical"][i % 8],
                marker_line=dict(width=0),
                showlegend=len(spec.y_fields) > 1))
        if len(spec.y_fields) > 1:
            fig.update_layout(barmode="group")

    return _layout(fig, pal, y_label, spec.x_label)


def build_report_figure(block: dict, theme: str = "light") -> go.Figure | None:
    """Figure for a report-slide chart block (regenerated from stored data)."""
    pal = PALETTES.get(theme, PALETTES["light"])
    ctype = block.get("chart_type")
    xs = block.get("x", [])
    series = block.get("series", [])
    if not xs or not series:
        return None
    fig = go.Figure()
    if ctype == "waterfall":
        moves = series[0]["values"]
        start = block.get("start", 0)
        measure = ["absolute"] + ["relative"] * len(moves) + ["total"]
        fig.add_trace(go.Waterfall(
            x=[block.get("start_label", "Start")] + list(xs) + [block.get("end_label", "End")],
            measure=measure,
            y=[start] + list(moves) + [0],
            text=[f"{start:,.0f}"] + [f"{v:+,.1f}" for v in moves] + [""],
            textposition="outside",
            textfont=dict(size=11.5, color=pal["ink2"]),
            connector=dict(line=dict(color=pal["baseline"], width=1)),
            increasing=dict(marker=dict(color=pal["positive"])),
            decreasing=dict(marker=dict(color=pal["negative"])),
            totals=dict(marker=dict(color=pal["muted"])),
            cliponaxis=False, showlegend=False))
    elif ctype == "line":
        for i, s in enumerate(series):
            fig.add_trace(go.Scatter(x=xs, y=s["values"], mode="lines+markers",
                                     name=s["name"],
                                     line=dict(width=2, color=pal["categorical"][i % 8]),
                                     marker=dict(size=7)))
    elif ctype == "grouped_bar" and len(series) == 2:
        fig.add_trace(go.Bar(x=xs, y=series[0]["values"], name=series[0]["name"],
                             marker_color=pal["current"], marker_line=dict(width=0)))
        fig.add_trace(go.Bar(x=xs, y=series[1]["values"], name=series[1]["name"],
                             marker_color=pal["prior"], marker_line=dict(width=0)))
    else:
        for i, s in enumerate(series):
            fig.add_trace(go.Bar(x=xs, y=s["values"], name=s["name"],
                                 marker_color=pal["categorical"][i % 8],
                                 marker_line=dict(width=0),
                                 showlegend=len(series) > 1))
    unit = block.get("unit", "")
    fig = _layout(fig, pal, unit)
    fig.update_layout(height=320)
    return fig
