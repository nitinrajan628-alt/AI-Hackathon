"""Report viewer: displays pre-rendered PowerPoint slides as PNG images,
with navigation, download, and fallback to structured HTML rendering."""
from __future__ import annotations

import streamlit as st

from services.report_service import (
    get_pptx_bytes,
    get_report_manifest,
    get_slide_image_path,
    has_pptx_report,
    list_slides,
)
from services.review_service import quarter_label
from ui.components import render_slide

ss = st.session_state
review_id = ss.context.current_review_id

# A citation can deep-link to a specific slide (possibly in another review).
if target := ss.pop("open_slide", None):
    target_review, target_number = target
    if target_review != review_id:
        ss.context.current_review_id = target_review
        ss.context.reset_filters()
        review_id = target_review
    ss["slide_number"] = target_number

use_pptx = has_pptx_report(review_id)

if use_pptx:
    manifest = get_report_manifest(review_id)
    slide_entries = manifest["slides"]
    numbers = [e["slide_number"] for e in slide_entries]
else:
    slides = list_slides(review_id)
    if not slides:
        st.warning("No slides found for this review. Run scripts/build_reports.py "
                   "then scripts/build_pptx_reports.py.")
        st.stop()
    numbers = [s["slide_number"] for s in slides]

if ss.get("slide_number") not in numbers:
    ss["slide_number"] = numbers[0]
current_idx = numbers.index(ss["slide_number"])

# Header
head_col, dl_col = st.columns([4, 1.5])
with head_col:
    st.markdown(f"### {quarter_label(review_id)} Reserve Review")
    st.caption("Slides are searchable from the chat page and cited in answers.")
with dl_col:
    if use_pptx:
        pptx_data = get_pptx_bytes(review_id)
        if pptx_data:
            st.download_button(
                ":material/download: Download .pptx",
                data=pptx_data,
                file_name=f"{review_id}_Reserve_Review.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True)

# Navigation
nav_prev, nav_sel, nav_next = st.columns([1, 5, 1])
with nav_prev:
    if st.button(":material/chevron_left:", key="prev",
                 disabled=current_idx == 0, width="stretch"):
        ss["slide_number"] = numbers[current_idx - 1]
        st.rerun()
with nav_next:
    if st.button(":material/chevron_right:", key="next",
                 disabled=current_idx == len(numbers) - 1, width="stretch"):
        ss["slide_number"] = numbers[current_idx + 1]
        st.rerun()
with nav_sel:
    if use_pptx:
        format_fn = lambda n: (
            f"{n:02d} · {next(e for e in slide_entries if e['slide_number'] == n)['section']}"
            f" — {next(e for e in slide_entries if e['slide_number'] == n)['title']}")
    else:
        format_fn = lambda n: (
            f"{n:02d} · {next(s for s in slides if s['slide_number'] == n)['section']}"
            f" — {next(s for s in slides if s['slide_number'] == n)['title']}")
    chosen = st.selectbox("Slide", numbers, index=current_idx,
                          format_func=format_fn, label_visibility="collapsed")
    if chosen != ss["slide_number"]:
        ss["slide_number"] = chosen
        st.rerun()

# Slide display
if use_pptx:
    current_entry = next(e for e in slide_entries if e["slide_number"] == ss["slide_number"])
    # PNG index is slide_number + 1 (title slide is slide_01.png)
    png_index = ss["slide_number"] + 1
    png_path = get_slide_image_path(review_id, png_index)
    if png_path:
        st.image(png_path, use_container_width=True)
    else:
        # Fallback: show slide info as text if PNG not yet rendered
        st.info(f"**{current_entry['title']}**\n\n"
                f"*{current_entry.get('headline', '')}*\n\n"
                f"PNG not yet generated. Run `scripts/build_pptx_reports.py` "
                f"with PowerPoint available to render slide images.")
        # Also try structured fallback
        fallback_slides = list_slides(review_id)
        fallback = next((s for s in fallback_slides
                         if s["slide_number"] == ss["slide_number"]), None)
        if fallback:
            render_slide(fallback, key_prefix=f"rep_{review_id}_{ss['slide_number']}")
else:
    slide = next(s for s in slides if s["slide_number"] == ss["slide_number"])
    render_slide(slide, key_prefix=f"rep_{review_id}_{slide['slide_number']}")

# Slide list expander
with st.expander("All slides in this report"):
    if use_pptx:
        for e in slide_entries:
            cols = st.columns([1, 8, 2])
            cols[0].markdown(f"**{e['slide_number']:02d}**")
            cols[1].markdown(f"{e['title']}  \n"
                             f"<span style='color:var(--muted);font-size:0.78rem'>"
                             f"{e['section']}</span>", unsafe_allow_html=True)
            if cols[2].button("Open", key=f"open_{e['slide_number']}"):
                ss["slide_number"] = e["slide_number"]
                st.rerun()
    else:
        for s in slides:
            cols = st.columns([1, 8, 2])
            cols[0].markdown(f"**{s['slide_number']:02d}**")
            cols[1].markdown(f"{s['title']}  \n"
                             f"<span style='color:var(--muted);font-size:0.78rem'>"
                             f"{s['section']}</span>", unsafe_allow_html=True)
            if cols[2].button("Open", key=f"open_{s['slide_number']}"):
                ss["slide_number"] = s["slide_number"]
                st.rerun()
