"""Conversation workspace: chat, answer cards, evidence panel."""
from __future__ import annotations

import uuid

import streamlit as st

from services.naming_service import generate_chat_title
from services.orchestrator import handle_question
from services.review_service import quarter_label
from services.settings import get_llm_settings
from ui.components import render_answer_card, render_evidence_panel

EXAMPLE_PROMPTS = [
    "What are the key messages from this quarter's reserve review?",
    "How much did reserves change from last quarter?",
    "Show the reserve movement by Finance Class.",
    "Which projection methods changed from last quarter?",
]

FOLLOW_UPS = {
    "PERIOD_COMPARISON": [
        "Which Reserving Classes drove that?",
        "Show the same movement by Finance Class instead.",
        "Now split that by Region.",
    ],
    "STRUCTURED_QUERY": [
        "Compare that with last quarter.",
        "Show the same view by Business Unit.",
    ],
    "REPORT_QA": [
        "How much did reserves change from last quarter?",
        "What does the report say about uncertainty?",
    ],
    "ASSUMPTION_CHANGES": [
        "How much reserve is held for Casualty?",
        "What does the report say about assumption changes?",
    ],
    "TREND": ["Show the same trend by Reserving Class."],
    "MIXED_REPORT_DATA": ["Now split that by Region."],
}

ss = st.session_state
ctx = ss.context


def _select_session(session_id: str) -> None:
    active = next((s for s in ss.chat_sessions if s["id"] == session_id), None)
    if active is None:
        return
    ss.active_session_id = session_id
    ss.session_id = active["id"]
    ss.context = active["context"]
    ss.messages = active["messages"]


def _new_chat() -> None:
    from services.context_service import ConversationContext
    from services.review_service import default_review_id
    session = {
        "id": str(uuid.uuid4()),
        "title": "New chat",
        "messages": [],
        "context": ConversationContext(current_review_id=default_review_id()),
        "created_at": str(uuid.uuid4())[:8],
    }
    ss.chat_sessions.insert(0, session)
    ss.active_session_id = session["id"]
    ss.session_id = session["id"]
    ss.context = session["context"]
    ss.messages = session["messages"]


def _delete_session(session_id: str) -> None:
    if len(ss.chat_sessions) <= 1:
        return
    ss.chat_sessions = [s for s in ss.chat_sessions if s["id"] != session_id]
    if ss.active_session_id == session_id:
        active = ss.chat_sessions[0]
        ss.active_session_id = active["id"]
        ss.session_id = active["id"]
        ss.context = active["context"]
        ss.messages = active["messages"]


def _first_question(session: dict) -> str:
    for msg in session["messages"]:
        if msg["role"] == "user":
            return msg["content"][:80]
    return "No messages yet"


# Layout: left history panel | main chat | optional evidence panel
history_col, chat_col, *evidence_cols = st.columns(
    [1.2, 3, 1.3] if ss.show_evidence else [1.2, 4.8])

with history_col:
    if st.button(":material/add: New chat", key="new_chat_btn", use_container_width=True):
        _new_chat()
        st.rerun()

    st.markdown("<div class='rr-sectionlabel'>Chats</div>", unsafe_allow_html=True)

    for session in ss.chat_sessions:
        is_active = session["id"] == ss.active_session_id
        preview = _first_question(session)
        active_class = " active" if is_active else ""
        truncated_preview = preview[:60] + ("…" if len(preview) > 60 else "")
        is_renaming = ss.get("renaming_session") == session["id"]

        if is_renaming:
            new_name = st.text_input(
                "Rename", value=session["title"],
                key=f"rename_input_{session['id']}",
                label_visibility="collapsed",
            )
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("Save", key=f"save_rename_{session['id']}"):
                    session["title"] = new_name
                    ss["renaming_session"] = None
                    st.rerun()
            with rc2:
                if st.button("Cancel", key=f"cancel_rename_{session['id']}"):
                    ss["renaming_session"] = None
                    st.rerun()
        else:
            with st.container(key=f"tile_{session['id']}"):
                st.markdown(
                    f"<div class='rr-chat-tile{active_class}'>"
                    f"<div class='tile-title'>{session['title']}</div>"
                    f"<div class='tile-preview'>{truncated_preview}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if st.button(
                    "Open",
                    key=f"sess_{session['id']}",
                    use_container_width=True,
                ):
                    _select_session(session["id"])
                    st.rerun()
                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button(":material/edit:", key=f"rename_{session['id']}"):
                        ss["renaming_session"] = session["id"]
                        st.rerun()
                with ac2:
                    if len(ss.chat_sessions) > 1:
                        if st.button(":material/close:", key=f"del_{session['id']}"):
                            _delete_session(session["id"])
                            st.rerun()

# Re-bind ctx after potential session switch
ctx = ss.context

with chat_col:
    head_l, head_r = st.columns([3, 1.15])
    with head_l:
        st.caption(f"Questions run against the {quarter_label(ctx.current_review_id)} "
                   f"review unless you name another period.")
    with head_r:
        ss.show_evidence = st.toggle("Evidence panel", value=ss.show_evidence)
        ss.deep_mode = st.selectbox(
            "Analysis depth", ["Auto", "Deep analysis", "Single query"],
            index=["Auto", "Deep analysis", "Single query"].index(
                ss.get("deep_mode", "Auto")),
            help="Auto runs a full diagnostic battery when a question asks for "
                 "analysis. Deep analysis forces it on for every question; "
                 "Single query forces the quick single-result route.")

_DEEP_FLAG = {"Auto": None, "Deep analysis": True, "Single query": False}


def _submit(question: str) -> None:
    deep = _DEEP_FLAG[ss.get("deep_mode", "Auto")]
    with chat_col:
        with st.status("Interpreting question", expanded=False) as status:
            settings = get_llm_settings()
            result = handle_question(question, ss.session_id, ctx, settings=settings,
                                     deep_analysis=deep)
            if len(result.query_outputs) > 1:
                status.update(label=f"Ran {len(result.query_outputs)} diagnostics "
                                    f"from stored review data")
            elif result.query_outputs:
                status.update(label="Calculating from stored review data")
            status.update(label="Done", state="complete")
    ss.messages.append({"role": "user", "content": question, "result": None})
    ss.messages.append({"role": "assistant", "content": result.answer_text,
                        "result": result})

    active = next((s for s in ss.chat_sessions if s["id"] == ss.active_session_id), None)
    if active and active["title"] == "New chat":
        headline = (result.draft.headline if result.draft else
                    result.answer_text.splitlines()[0][:60])
        title = generate_chat_title(question, headline)
        active["title"] = title

    st.rerun()


if pending := ss.pop("pending_q", None):
    _submit(pending)

with chat_col:
    if not ss.messages:
        st.markdown("<div class='rr-sectionlabel'>Example questions</div>",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, prompt in enumerate(EXAMPLE_PROMPTS):
            with cols[i % 2]:
                if st.button(prompt, key=f"example_{i}", width="stretch"):
                    ss["pending_q"] = prompt
                    st.rerun()

    last_result = None
    for i, msg in enumerate(ss.messages):
        if msg["role"] == "system":
            st.caption(f"— {msg['content']} —")
            continue
        with st.chat_message(msg["role"],
                             avatar=":material/person:" if msg["role"] == "user"
                             else ":material/analytics:"):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                result = msg["result"]
                if result is None:
                    st.markdown(msg["content"])
                elif result.status in ("BLOCKED", "ERROR", "NO_RESULT"):
                    st.markdown(msg["content"])
                    if result.guardrail_category:
                        st.caption(f"Out of scope · {result.guardrail_category.replace('_', ' ')}")
                else:
                    render_answer_card(result, key_prefix=f"msg{i}")
                    last_result = result

    if last_result is not None and ss.messages:
        suggestions = FOLLOW_UPS.get(last_result.intent, [])[:3]
        if suggestions:
            st.markdown("<div class='rr-sectionlabel'>Follow up</div>",
                        unsafe_allow_html=True)
            cols = st.columns(len(suggestions))
            for i, sugg in enumerate(suggestions):
                with cols[i]:
                    if st.button(sugg, key=f"fu_{len(ss.messages)}_{i}",
                                 width="stretch"):
                        ss["pending_q"] = sugg
                        st.rerun()

if evidence_cols:
    with evidence_cols[0]:
        st.markdown("<div class='rr-sectionlabel'>Evidence</div>",
                    unsafe_allow_html=True)
        latest = next((m["result"] for m in reversed(ss.messages)
                       if m["role"] == "assistant" and m["result"] is not None
                       and m["result"].status == "SUCCESS"), None)
        if latest is None:
            st.caption("Ask a question to see cited slides, data provenance "
                       "and query details here.")
        else:
            render_evidence_panel(latest)

with chat_col:
    if question := st.chat_input(
            f"Ask about the {quarter_label(ctx.current_review_id)} review…"):
        _submit(question)
