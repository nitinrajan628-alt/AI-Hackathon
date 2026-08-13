"""Reserve Review Intelligence - Streamlit application entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import uuid

import streamlit as st

st.set_page_config(
    page_title="Interactive Reserve Report",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from services.context_service import ConversationContext
from services.review_service import default_review_id, list_reviews, quarter_label
from services.settings import get_llm_settings
from ui.theme import THEMES, inject_css


def _new_session() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "title": "New chat",
        "messages": [],
        "context": ConversationContext(current_review_id=default_review_id()),
        "created_at": str(uuid.uuid4())[:8],
    }


def _init_state() -> None:
    ss = st.session_state
    if "chat_sessions" not in ss:
        try:
            from services.demo_seed import seed_demo_sessions
            sessions, artifacts = seed_demo_sessions()
            ss.chat_sessions = sessions
            ss.artifacts = artifacts
            ss.active_session_id = sessions[0]["id"]
        except Exception:
            first = _new_session()
            ss.chat_sessions = [first]
            ss.active_session_id = first["id"]
            ss.artifacts = []
    if ss.get("theme") not in THEMES:
        ss.theme = "light"
    if "show_evidence" not in ss:
        ss.show_evidence = True
    if "artifacts" not in ss:
        ss.artifacts = []

    active = _get_active_session()
    ss.session_id = active["id"]
    ss.context = active["context"]
    ss.messages = active["messages"]


def _get_active_session() -> dict:
    ss = st.session_state
    for s in ss.chat_sessions:
        if s["id"] == ss.active_session_id:
            return s
    return ss.chat_sessions[0]


def _switch_review() -> None:
    """Changing the review starts a new conversation context (the selected
    review is the context for 'this quarter')."""
    ss = st.session_state
    new_review = ss.review_selector
    ctx = ss.context
    if new_review != ctx.current_review_id:
        ctx.current_review_id = new_review
        ctx.reset_filters()
        ss.messages.append({
            "role": "system",
            "content": f"Switched to the {quarter_label(new_review)} review. "
                       f"Conversation context has been reset.",
            "result": None,
        })


_init_state()
inject_css()

pages = [
    st.Page("pages/report.py", title="Report", icon=":material/description:", default=True),
    st.Page("pages/chat.py", title="Chat", icon=":material/forum:"),
    st.Page("pages/artifacts.py", title="Artifacts", icon=":material/bookmark:"),
]
nav = st.navigation(pages, position="hidden")

with st.sidebar:
    st.markdown(
        "<div class='rr-brand'>Interactive Reserve Report"
        "<small>View the report as you would like to see it</small></div>",
        unsafe_allow_html=True)

    st.markdown("<div class='rr-sectionlabel'>Reserving quarter</div>",
                unsafe_allow_html=True)
    reviews = list_reviews()
    ids = [r["review_id"] for r in reviews]
    st.selectbox(
        "Selected review", ids,
        index=ids.index(st.session_state.context.current_review_id),
        format_func=quarter_label, key="review_selector",
        on_change=_switch_review, label_visibility="collapsed")

    st.markdown("<div class='rr-sectionlabel'>Navigate</div>",
                unsafe_allow_html=True)
    for p in pages:
        st.page_link(p, label=p.title, icon=p.icon)

    ctx = st.session_state.context
    st.markdown("<div class='rr-sectionlabel'>Context</div>", unsafe_allow_html=True)
    chips = [f"Review: {quarter_label(ctx.current_review_id)}"]
    chips += [f"vs {quarter_label(r)}" for r in ctx.comparison_review_ids]
    for f in ctx.active_filters:
        value = ", ".join(map(str, f["value"])) if isinstance(f.get("value"), list) \
            else f.get("value")
        chips.append(f"{str(f['field']).replace('_', ' ').title()}: {value}")
    if ctx.last_group_by:
        chips.append("By " + ", ".join(g.replace("_", " ").title()
                                       for g in ctx.last_group_by))
    st.markdown("".join(f"<span class='rr-chip'>{c}</span>" for c in chips),
                unsafe_allow_html=True)
    if len(chips) > 1 and st.button("Reset context", key="reset_ctx"):
        ctx.reset_filters()
        st.rerun()

    st.markdown("<div class='rr-sectionlabel'>Appearance</div>",
                unsafe_allow_html=True)
    labels = {"light": "Light", "dark": "Dark", "rainbow": "Rainbow"}
    chosen = st.radio(
        "Appearance", list(THEMES), horizontal=True,
        index=list(THEMES).index(st.session_state.theme),
        format_func=lambda t: labels[t], key="theme_choice",
        label_visibility="collapsed")
    if chosen != st.session_state.theme:
        st.session_state.theme = chosen
        st.rerun()

    settings = get_llm_settings()
    st.markdown(
        f"<div class='rr-sectionlabel'>Model provider</div>"
        f"<div style='font-size:0.78rem;color:var(--muted)'>"
        f"{settings.provider_label}<br>{settings.model}</div>",
        unsafe_allow_html=True)
    if not settings.key_present():
        st.caption(f"⚠ {settings.key_env_var} not set")

nav.run()
