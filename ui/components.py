"""Reusable UI components: financial tables, answer cards, evidence panel
and the report slide renderer."""
from __future__ import annotations

import html
import io
import json
import math
import re
import uuid

import pandas as pd
import streamlit as st

from services import audit_service
from services.catalogue import get_catalogue
from services.chart_service import build_figure, build_report_figure
from services.formatting import fmt_measure, fmt_pct, fmt_year, is_integer_field
from services.review_service import quarter_label
from ui.theme import current_theme

PCT_COLS = {"percentage_change", "share_pct", "contribution_pct"}
DERIVED_LABELS = {
    "current": "Current", "prior": "Prior", "absolute_change": "Movement",
    "percentage_change": "Change %", "share_pct": "Share %",
    "contribution_pct": "Contribution %", "review": "Review",
    "prior_value": "Previous", "current_value": "Current",
}


def _copy_button(text: str, key: str, label: str = "Copy") -> None:
    """Render a copy-to-clipboard button using Streamlit's native download."""
    st.download_button(
        f":material/content_copy: {label}", data=text,
        file_name="copied_text.md", mime="text/markdown",
        key=key, use_container_width=False)


def _download_table_csv(df: pd.DataFrame, key: str, filename: str = "table") -> None:
    csv_data = df.to_csv(index=False)
    st.download_button(
        ":material/download: CSV", data=csv_data,
        file_name=f"{filename}.csv", mime="text/csv",
        key=key, use_container_width=False)


def _download_chart_png(fig, key: str, filename: str = "chart") -> None:
    try:
        img_bytes = fig.to_image(format="png", width=1200, height=600)
        st.download_button(
            ":material/download: PNG", data=img_bytes,
            file_name=f"{filename}.png", mime="image/png",
            key=key, use_container_width=False)
    except Exception:
        pass


def _chart_filename(title: str, fallback: str = "chart_export") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or fallback


def _esc(v) -> str:
    return html.escape(str(v))


def _column_label(col: str, dataset: str, unit: str, period_labels: list[str]) -> str:
    cat = get_catalogue()
    if col in ("current", "prior") and len(period_labels) >= 2:
        base = period_labels[0] if col == "current" else period_labels[1]
    else:
        base = DERIVED_LABELS.get(col)
    if base is None:
        if dataset in cat.datasets and (col in cat.dimensions(dataset)
                                        or col in cat.attributes(dataset)):
            base = cat.dimension_label(dataset, col)
        elif dataset in cat.datasets and col in cat.measures(dataset):
            base = cat.measure_label(dataset, col)
        else:
            base = col.replace("_", " ").title()
    if unit == "GBP" and (col in ("current", "prior", "absolute_change")
                          or (dataset in cat.datasets and col in cat.measures(dataset))):
        base += " (GBP m)"
    return base


def render_result_table(df: pd.DataFrame, dataset: str, unit: str,
                        period_labels: list[str], measures: list[str],
                        total_row: bool = True) -> None:
    """Render a deterministic result table as styled HTML."""
    if df.empty:
        st.caption("No rows.")
        return
    cat = get_catalogue()
    value_cols = set(measures) | {"current", "prior", "absolute_change"}
    num_cols = [c for c in df.columns if c in value_cols or c in PCT_COLS]
    # Year / ordinal columns are right-aligned like numbers but never carry
    # separators or decimals.
    int_cols = [c for c in df.columns if is_integer_field(c) and c not in num_cols]
    dim_cols = [c for c in df.columns if c not in num_cols and c not in int_cols]

    head = "".join(
        f"<th class='{'num' if (c in num_cols or c in int_cols) else ''}'>"
        f"{_esc(_column_label(c, dataset, unit, period_labels))}</th>"
        for c in df.columns)
    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if c in int_cols:
                cells.append(f"<td class='num'>{_esc(fmt_year(v))}</td>")
            elif c in num_cols:
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    text, neg = "–", False
                elif c in PCT_COLS:
                    text = fmt_pct(float(v), signed=(c != "share_pct"))
                    neg = float(v) < 0
                elif c == "absolute_change":
                    text = fmt_measure(float(v), unit, signed=True)
                    neg = float(v) < 0
                else:
                    text = fmt_measure(float(v), unit)
                    neg = float(v) < 0
                cells.append(f"<td class='num{' neg' if neg else ''}'>{_esc(text)}</td>")
            else:
                cells.append(f"<td>{_esc(v)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    # Total row for additive single-measure results with grouping. Year and
    # ordinal columns count as grouping columns but are never summed.
    if total_row and (dim_cols or int_cols) and len(df) > 1:
        additive = all(cat.measures(dataset).get(m, {}).get("additive", True)
                       for m in measures) if dataset in cat.datasets else True
        if additive and (set(measures) & set(df.columns) or
                         {"current", "prior"} <= set(df.columns)):
            cells = []
            for i, c in enumerate(df.columns):
                if c in num_cols and c not in PCT_COLS:
                    total = df[c].sum(skipna=True)
                    signed = c == "absolute_change"
                    cells.append(f"<td class='num{' neg' if total < 0 else ''}'>"
                                 f"{_esc(fmt_measure(float(total), unit, signed=signed))}</td>")
                elif c in PCT_COLS:
                    cells.append("<td class='num'></td>")
                else:
                    cells.append("<td>Total</td>" if i == 0 else "<td></td>")
            body_rows.append("<tr class='total'>" + "".join(cells) + "</tr>")

    st.markdown(
        f"<div class='rr-tablewrap'><table class='rr-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody>"
        f"</table></div>", unsafe_allow_html=True)

    table_key = f"dl_table_{uuid.uuid4().hex[:8]}"
    with st.container(key=f"{table_key}_rowend"):
        _download_table_csv(df, key=table_key, filename="table_export")


def evidence_badges(result) -> str:
    badges = []
    datasets = {o.engine_result.validated.dataset for o in result.query_outputs}
    if result.slides:
        badges.append("Report")
    if datasets & {"claims_latest", "claims_triangle", "premium"}:
        badges.append("Data")
    if "assumptions" in datasets:
        badges.append("Assumptions")
    if "results" in datasets:
        badges.append("Results")
    if result.draft and not result.used_fallback and (result.slides or datasets):
        badges.append("AI interpretation")
    return "".join(f"<span class='rr-badge'>{_esc(b)}</span>" for b in badges)


def _build_answer_markdown(result) -> str:
    """Build a markdown representation of the answer for clipboard copy."""
    draft = result.draft
    if not draft:
        return result.answer_text
    parts = [f"# {draft.headline}"]
    if draft.observations:
        parts.append("")
        for obs in draft.observations:
            parts.append(f"- {obs}")
    if draft.sections:
        for section in draft.sections:
            parts.append(f"\n## {section.title}")
            for point in section.points:
                parts.append(f"- {point}")
    if draft.limitations:
        parts.append("\n**Caveats:**")
        for lim in draft.limitations:
            parts.append(f"- {lim}")
    return "\n".join(parts)


def render_answer_card(result, key_prefix: str) -> None:
    """Answer card: headline, meta, observations, chart, table, actions."""
    draft = result.draft
    headline = draft.headline if draft else result.answer_text.splitlines()[0]

    meta_parts = []
    if result.period_label:
        meta_parts.append(_esc(result.period_label))
    if result.query_outputs:
        plan = result.query_outputs[0].engine_result.validated.plan
        for f in plan.filters:
            v = ", ".join(map(str, f.value)) if isinstance(f.value, list) else f.value
            meta_parts.append(f"{_esc(f.field.replace('_', ' ').title())}: {_esc(v)}")
        if not plan.filters:
            # Make an unfiltered scope explicit, so a whole-portfolio total can
            # never be read as though it applied to a narrower slice.
            scope = ("all " + ", ".join(g.replace("_", " ") for g in plan.group_by)
                     if plan.group_by else "whole portfolio")
            meta_parts.append(f"No filters · {_esc(scope)}")
    meta = " &nbsp;·&nbsp; ".join(meta_parts)

    obs_html = ""
    if draft and draft.observations:
        obs_html = "<ul class='rr-obs'>" + "".join(
            f"<li>{_esc(o)}</li>" for o in draft.observations) + "</ul>"
    sections_html = ""
    if draft and draft.sections:
        for section in draft.sections:
            points = "".join(f"<li>{_esc(p)}</li>" for p in section.points)
            sections_html += (f"<div class='rr-analysis-section'>"
                              f"<div class='rr-analysis-title'>{_esc(section.title)}"
                              f"</div><ul class='rr-obs'>{points}</ul></div>")
    limits_html = ""
    if draft and draft.limitations:
        limits_html = "".join(f"<div class='rr-limit'>{_esc(l)}</div>"
                              for l in draft.limitations[:3])

    with st.container(key=f"{key_prefix}_answercard"):
        st.markdown(
            f"<div class='rr-card'>"
            f"<div class='rr-headline'>{_esc(headline)}</div>"
            f"<div class='rr-meta'>{meta}</div>"
            f"{evidence_badges(result)}"
            f"{obs_html}{sections_html}{limits_html}"
            f"</div>", unsafe_allow_html=True)

        answer_md = _build_answer_markdown(result)
        _copy_button(answer_md, key=f"{key_prefix}_copy_answer")

    outputs = result.query_outputs
    titles = getattr(result, "analysis_titles", None) or []
    deep = len(outputs) > 1

    def _render_output(i: int, output) -> None:
        er = output.engine_result
        if output.chart_spec is not None:
            fig = build_figure(output.chart_spec, current_theme())
            with st.container(key=f"{key_prefix}_chartbox_{i}"):
                if output.chart_spec.title:
                    st.markdown(
                        f"<div class='rr-chart-title'>"
                        f"{_esc(output.chart_spec.title)}</div>",
                        unsafe_allow_html=True)
                st.plotly_chart(fig, width="stretch",
                                key=f"{key_prefix}_chart_{i}",
                                config={"displayModeBar": False})
                _download_chart_png(
                    fig, key=f"{key_prefix}_dlchart_{i}",
                    filename=_chart_filename(output.chart_spec.title))
        render_result_table(er.shaped.df, er.validated.dataset,
                            er.shaped.unit, er.shaped.period_labels,
                            er.validated.plan.measures)
        if er.shaped.total_row_count > len(er.shaped.df):
            st.caption(f"Showing {len(er.shaped.df)} of "
                       f"{er.shaped.total_row_count} rows (row limit applied).")

    if deep:
        # A battery: lead with the primary exhibit, keep the rest available
        # without burying the analysis under ten tables.
        _render_output(0, outputs[0])
        if titles:
            st.caption(titles[0])
        with st.expander(f"Supporting diagnostics ({len(outputs) - 1})"):
            for i, output in enumerate(outputs[1:], start=1):
                st.markdown(f"**{_esc(titles[i]) if i < len(titles) else f'Diagnostic {i + 1}'}**",
                            unsafe_allow_html=True)
                _render_output(i, output)
                st.markdown("---")
    else:
        for i, output in enumerate(outputs):
            _render_output(i, output)

    if result.slides:
        chips = st.columns(min(len(result.slides), 3) + 1)
        for i, slide in enumerate(result.slides[:3]):
            with chips[i]:
                if st.button(f"{slide.quarter_label} · slide {slide.slide_number}",
                             key=f"{key_prefix}_cite_{i}",
                             help=slide.title, width="stretch"):
                    st.session_state["open_slide"] = (slide.review_id,
                                                      slide.slide_number)
                    st.switch_page("pages/report.py")

    if result.diagnostic_id:
        with st.container(key=f"{key_prefix}_artifactrow"):
            _render_save_artifact_button(result, key_prefix)


def _render_save_artifact_button(result, key_prefix: str) -> None:
    """Save as artifact button — stores result in session state artifacts list."""
    ss = st.session_state
    artifacts = ss.get("artifacts", [])
    already_saved = any(a["diagnostic_id"] == result.diagnostic_id for a in artifacts)

    if already_saved:
        st.caption(":material/bookmark: Saved as artifact")
    elif st.button(":material/bookmark: Save as artifact", key=f"{key_prefix}_artifact"):
        from services.naming_service import generate_artifact_title
        headline = (result.draft.headline if result.draft else
                    result.answer_text.splitlines()[0][:60])
        source_question = ""
        messages = ss.get("messages", [])
        for i, msg in enumerate(messages):
            if (msg["role"] == "assistant" and msg.get("result")
                    and getattr(msg["result"], "diagnostic_id", None) == result.diagnostic_id):
                if i > 0 and messages[i - 1]["role"] == "user":
                    source_question = messages[i - 1]["content"]
                break

        title = generate_artifact_title(source_question or "Result", headline)
        artifact = {
            "id": str(uuid.uuid4()),
            "diagnostic_id": result.diagnostic_id,
            "title": title,
            "source_session_id": ss.get("active_session_id", ss.get("session_id")),
            "source_question": source_question,
            "result": result,
            "created_at": str(uuid.uuid4())[:8],
        }
        ss.artifacts.append(artifact)
        st.rerun()


def render_evidence_panel(result) -> None:
    """Right panel: Slides / Data provenance / Query details."""
    has_slides = bool(result.slides)
    has_provenance = bool(result.query_outputs)
    has_query = bool(result.query_outputs)

    tab_entries = [
        ("Provenance", has_provenance),
        ("Slides", has_slides),
        ("Query", has_query),
    ]
    tab_entries.sort(key=lambda entry: not entry[1])
    tab_labels = [label for label, _ in tab_entries]
    tabs = st.tabs(tab_labels)
    tab_map = {label: tab for label, tab in zip(tab_labels, tabs)}

    with tab_map["Slides"]:
        if not result.slides:
            st.caption("No report slides were cited for this answer.")
        for i, s in enumerate(result.slides):
            st.markdown(
                f"<div class='rr-evidence-item'>"
                f"<div class='src'>{_esc(s.quarter_label)} Reserve Review · "
                f"slide {s.slide_number} · {_esc(s.section)}</div>"
                f"<div class='title'>{_esc(s.title)}</div>"
                f"<div class='excerpt'>{_esc(s.excerpt[:280])}…</div>"
                f"</div>", unsafe_allow_html=True)
            if st.button("Open slide", key=f"ev_open_{result.diagnostic_id}_{i}"):
                st.session_state["open_slide"] = (s.review_id, s.slide_number)
                st.switch_page("pages/report.py")

    with tab_map["Provenance"]:
        if not result.query_outputs:
            st.caption("No data query was executed for this answer.")
        cat = get_catalogue()
        for output in result.query_outputs:
            er = output.engine_result
            plan = er.validated.plan
            ds = er.validated.dataset
            rows = [
                ("Source", f"{cat.dataset(ds).get('label', ds)} ({er.validated.table})"),
                ("Periods", ", ".join(quarter_label(r) for r in plan.review_ids)),
                ("Measures", ", ".join(cat.measure_label(ds, m) for m in plan.measures) or "–"),
                ("Grouping", ", ".join(cat.dimension_label(ds, g) for g in plan.group_by) or "None"),
                ("Filters", "; ".join(
                    f"{f.field} {f.operator} {f.value}" for f in plan.filters) or "None"),
                ("Operation", plan.operation),
                ("Rows", f"{er.shaped.total_row_count}"),
            ]
            for m in plan.measures:
                spec = cat.measures(ds).get(m, {})
                rows.append((f"Definition · {cat.measure_label(ds, m)}",
                             f"column {spec.get('column')} · unit {spec.get('unit')} · "
                             f"{'additive (sum)' if spec.get('additive', True) else 'non-additive'}"))
            for label, value in rows:
                st.markdown(f"<div class='rr-kv'><b>{_esc(label)}</b>{_esc(value)}</div>",
                            unsafe_allow_html=True)
            for note in er.validated.inferred_defaults:
                st.caption(f"Note: {note}")
            st.markdown("---")
        if result.warnings:
            for w in result.warnings:
                st.caption(f"Warning: {w}")

    with tab_map["Query"]:
        if not result.query_outputs:
            st.caption("No SQL was executed for this answer.")
        for output in result.query_outputs:
            er = output.engine_result
            st.code(er.compiled.sql, language="sql")
            st.markdown(f"<div class='rr-kv'><b>Parameters</b>"
                        f"{_esc(er.compiled.parameters)}</div>",
                        unsafe_allow_html=True)
            with st.expander("Validated plan (JSON)"):
                st.code(json.dumps(er.validated.plan.model_dump(), indent=2),
                        language="json")
        if result.diagnostic_id:
            record = audit_service.get_diagnostic(result.diagnostic_id)
            if record:
                st.markdown(
                    f"<div class='rr-kv'><b>Diagnostic</b>{_esc(record['title'])}"
                    f"</div><div class='rr-kv'><b>Status</b>{_esc(record['status'])}"
                    f" · {record['duration_ms']} ms</div>",
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Report slide rendering
# ---------------------------------------------------------------------------

def render_slide(slide: dict, key_prefix: str = "slide") -> None:
    content = slide["content"]
    parts = [
        f"<div class='rr-slide-section'>{_esc(slide['section'])}</div>",
        f"<div class='rr-slide-title'>{_esc(slide['title'])}</div>",
    ]
    headline = content.get("headline")
    if headline and headline != slide["title"]:
        parts.append(f"<div class='rr-slide-headline'>{_esc(headline)}</div>")
    st.markdown(f"<div class='rr-slide'>{''.join(parts)}</div>",
                unsafe_allow_html=True)

    for i, block in enumerate(content.get("blocks", [])):
        btype = block.get("type")
        if btype == "metrics":
            tiles = "".join(
                f"<div class='rr-metric'><div class='label'>{_esc(m['label'])}</div>"
                f"<div class='value'>{_esc(m['value'])}</div></div>"
                for m in block.get("items", []))
            st.markdown(f"<div class='rr-metricrow'>{tiles}</div>",
                        unsafe_allow_html=True)
        elif btype in ("bullets", "numbered"):
            tag = "ol" if btype == "numbered" else "ul"
            items = "".join(f"<li>{_esc(t)}</li>" for t in block.get("items", []))
            st.markdown(f"<div class='rr-slide' style='padding-top:0.9rem;"
                        f"padding-bottom:0.5rem'><{tag}>{items}</{tag}></div>",
                        unsafe_allow_html=True)
        elif btype == "table":
            df = pd.DataFrame(block.get("rows", []), columns=block.get("columns", []))
            year_cols = [c for c in df.columns
                         if "year" in str(c).lower() or is_integer_field(c)]
            num_cols = [c for c in df.columns
                        if df[c].dtype.kind in "if" and c not in year_cols]
            head = "".join(
                f"<th class='{'num' if (c in num_cols or c in year_cols) else ''}'>"
                f"{_esc(c)}</th>"
                for c in df.columns)
            body = []
            for _, row in df.iterrows():
                cells = []
                for c in df.columns:
                    v = row[c]
                    if c in year_cols and isinstance(v, (int, float)):
                        cells.append(f"<td class='num'>{_esc(fmt_year(v))}</td>")
                    elif c in num_cols and isinstance(v, (int, float)):
                        neg = " neg" if v < 0 else ""
                        cells.append(f"<td class='num{neg}'>{v:,.1f}</td>")
                    else:
                        cells.append(f"<td>{_esc(v)}</td>")
                cls = " class='total'" if str(row.iloc[0]).lower() == "total" else ""
                body.append(f"<tr{cls}>{''.join(cells)}</tr>")
            st.markdown(f"<div class='rr-tablewrap'><table class='rr-table'>"
                        f"<thead><tr>{head}</tr></thead>"
                        f"<tbody>{''.join(body)}</tbody></table></div>",
                        unsafe_allow_html=True)
        elif btype == "chart":
            fig = build_report_figure(block, current_theme())
            if fig is not None:
                st.plotly_chart(fig, width="stretch",
                                key=f"{key_prefix}_b{i}",
                                config={"displayModeBar": False})
        elif btype == "text":
            st.markdown(f"<div class='rr-slide' style='padding:0.9rem 2rem'>"
                        f"<p style='font-size:0.92rem;color:var(--ink2);"
                        f"line-height:1.55'>{_esc(block.get('text', ''))}</p></div>",
                        unsafe_allow_html=True)

    st.markdown(
        f"<div class='rr-slide-footer'>"
        f"<span>{_esc(quarter_label(slide['review_id']))} Reserve Review</span>"
        f"<span>Slide {slide['slide_number']}</span></div>",
        unsafe_allow_html=True)
