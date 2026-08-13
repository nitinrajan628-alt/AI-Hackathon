"""Reserve Review Intelligence - Streamlit application entry point.

Run locally with:  streamlit run app.py
"""
from __future__ import annotations

import threading
import time
import uuid

import streamlit as st
import streamlit.components.v1 as components

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


# ---------------------------------------------------------------------------
# Background demo seeding (runs in a thread while intro video plays)
# ---------------------------------------------------------------------------

@st.cache_resource
def _start_background_seed() -> dict:
    """Kick off demo chat seeding in a background thread.

    Returns a shared result dict that the thread populates when done.
    Cached so the thread only starts once per server process.
    """
    result = {"done": False, "sessions": None, "artifacts": None, "error": None}

    def _run():
        try:
            from services.demo_seed import seed_demo_sessions_headless
            sessions, artifacts = seed_demo_sessions_headless()
            result["sessions"] = sessions
            result["artifacts"] = artifacts
        except Exception as exc:
            result["error"] = exc
        finally:
            result["done"] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return result


# ---------------------------------------------------------------------------
# Intro video overlay
# ---------------------------------------------------------------------------

_VIDEO_END_JS = """
<script>
(function() {
    // Poll until the video element appears in the parent document, then
    // listen for 'ended' to auto-advance past the intro.
    var poll = setInterval(function() {
        var v = window.parent.document.querySelector('video');
        if (!v) return;
        clearInterval(poll);
        v.addEventListener('ended', function() {
            // Click the hidden skip-trigger button in the Streamlit DOM
            var el = window.parent.document.querySelector(
                '[data-testid="stButton"] button');
            if (el) el.click();
        });
    }, 300);
})();
</script>
"""

_INTRO_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&display=swap');

/* Hide all app chrome during intro */
[data-testid="stSidebar"], [data-testid="stHeader"],
[data-testid="stToolbar"], footer,
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {
    display: none !important;
}
.stApp { background: #000 !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }
[data-testid="stBottomBlockContainer"] { padding: 0 !important; }

/* Full-viewport video */
[data-testid="stVideo"] {
    position: fixed !important; inset: 0 !important;
    width: 100vw !important; height: 100vh !important;
    z-index: 999990 !important; background: #000 !important;
}
[data-testid="stVideo"] video {
    width: 100% !important; height: 100% !important;
    object-fit: cover !important;
}

/* Star Wars skip button (Streamlit button restyled) */
[data-testid="stButton"] {
    position: fixed !important;
    bottom: 40px !important; right: 40px !important;
    z-index: 999999 !important;
    width: auto !important;
    opacity: 0;
    animation: introFadeIn 0.8s ease-out 3s forwards;
}
[data-testid="stButton"] button {
    position: relative !important;
    z-index: 999999 !important;
    font-family: 'Orbitron', sans-serif !important;
    font-weight: 700 !important; font-size: 0.95rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.25em !important;
    color: #FFE81F !important;
    background: rgba(0, 0, 0, 0.6) !important;
    border: 1.5px solid rgba(255, 232, 31, 0.6) !important;
    border-radius: 4px !important;
    padding: 12px 28px !important;
    cursor: pointer !important;
    text-shadow: 0 0 8px rgba(255, 232, 31, 0.4) !important;
    width: auto !important;
    transition: transform 0.2s, text-shadow 0.2s, border-color 0.2s !important;
}
[data-testid="stButton"] button:hover {
    transform: scale(1.05) !important;
    text-shadow: 0 0 14px rgba(255, 232, 31, 0.8) !important;
    border-color: #FFE81F !important;
    color: #FFE81F !important;
    background: rgba(0, 0, 0, 0.8) !important;
}
[data-testid="stButton"] button p {
    font-family: 'Orbitron', sans-serif !important;
    font-weight: 700 !important;
    color: #FFE81F !important;
    text-transform: uppercase !important;
    letter-spacing: 0.25em !important;
}

/* Hide the zero-height JS helper iframe */
[data-testid="stIFrame"] { display: none !important; }

@keyframes introFadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
</style>
"""


def _render_intro() -> None:
    """Render the full-screen intro video overlay and stop the app."""
    st.markdown(_INTRO_CSS, unsafe_allow_html=True)

    st.video("static/intro.mp4", autoplay=True, muted=True)

    if st.button("SKIP INTRO  \u25B6\u25B6", key="_intro_skip"):
        st.session_state.intro_complete = True
        st.rerun()

    components.html(_VIDEO_END_JS, height=0)
    st.stop()


# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------

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
    if "intro_complete" not in ss:
        ss.intro_complete = False
    if ss.get("theme") not in THEMES:
        ss.theme = "light"
    if "show_evidence" not in ss:
        ss.show_evidence = True
    if "artifacts" not in ss:
        ss.artifacts = []


def _populate_demo_sessions() -> None:
    """Populate chat sessions from the background seed result."""
    ss = st.session_state
    if "chat_sessions" in ss:
        return

    seed_result = _start_background_seed()

    if not seed_result["done"]:
        with st.spinner("Preparing demo content…"):
            while not seed_result["done"]:
                time.sleep(0.3)

    if seed_result["sessions"]:
        ss.chat_sessions = seed_result["sessions"]
        ss.artifacts = seed_result.get("artifacts") or []
        ss.active_session_id = seed_result["sessions"][0]["id"]
    else:
        first = _new_session()
        ss.chat_sessions = [first]
        ss.active_session_id = first["id"]
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


def _sync_active_session() -> None:
    """Ensure session_id / context / messages point at the active session."""
    ss = st.session_state
    if "chat_sessions" not in ss:
        return
    active = _get_active_session()
    ss.session_id = active["id"]
    ss.context = active["context"]
    ss.messages = active["messages"]


def _switch_review() -> None:
    """Changing the review starts a new conversation context."""
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


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

_start_background_seed()
_init_state()

if not st.session_state.intro_complete:
    _render_intro()

# Intro is done — show the main app
_populate_demo_sessions()
_sync_active_session()
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
