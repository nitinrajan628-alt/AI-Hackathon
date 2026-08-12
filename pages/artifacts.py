"""Artifacts library: saved responses with their source questions and links
back to the originating chat session."""
from __future__ import annotations

import streamlit as st

from ui.components import render_answer_card

ss = st.session_state

artifacts = ss.get("artifacts", [])

if not artifacts:
    st.markdown("### Artifacts")
    st.info("No artifacts saved yet. Use the 'Save as artifact' button on any "
            "chat response to add it here.")
    st.stop()


def _first_line(artifact: dict) -> str:
    q = artifact.get("source_question", "")
    return q[:70] if q else "Saved result"


# Layout: left artifact list | main content
list_col, detail_col = st.columns([1.2, 4.8])

with list_col:
    st.markdown("<div class='rr-sectionlabel'>Artifacts</div>", unsafe_allow_html=True)

    search = st.text_input("Search", key="artifact_search",
                           placeholder="Filter…", label_visibility="collapsed")

    filtered = artifacts
    if search:
        query = search.lower()
        filtered = [a for a in artifacts
                    if query in a["title"].lower()
                    or query in a.get("source_question", "").lower()]

    for artifact in reversed(filtered):
        is_open = ss.get("open_artifact") == artifact["id"]
        preview = _first_line(artifact)
        active_class = " active" if is_open else ""
        truncated_preview = preview[:55] + ("…" if len(preview) > 55 else "")
        is_renaming = ss.get("renaming_artifact") == artifact["id"]

        if is_renaming:
            new_name = st.text_input(
                "Rename", value=artifact["title"],
                key=f"rename_input_{artifact['id']}",
                label_visibility="collapsed",
            )
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("Save", key=f"save_artrename_{artifact['id']}"):
                    artifact["title"] = new_name
                    ss["renaming_artifact"] = None
                    st.rerun()
            with rc2:
                if st.button("Cancel", key=f"cancel_artrename_{artifact['id']}"):
                    ss["renaming_artifact"] = None
                    st.rerun()
        else:
            with st.container(key=f"tile_{artifact['id']}"):
                st.markdown(
                    f"<div class='rr-chat-tile{active_class}'>"
                    f"<div class='tile-title'>{artifact['title']}</div>"
                    f"<div class='tile-preview'>{truncated_preview}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if st.button(
                    "Open",
                    key=f"artbtn_{artifact['id']}",
                    use_container_width=True,
                ):
                    ss["open_artifact"] = (None if is_open else artifact["id"])
                    st.rerun()
                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button(":material/edit:", key=f"artrename_{artifact['id']}"):
                        ss["renaming_artifact"] = artifact["id"]
                        st.rerun()
                with ac2:
                    if st.button(":material/close:", key=f"artdel_{artifact['id']}"):
                        ss.artifacts = [a for a in ss.artifacts if a["id"] != artifact["id"]]
                        if ss.get("open_artifact") == artifact["id"]:
                            ss["open_artifact"] = None
                        st.rerun()

with detail_col:
    open_id = ss.get("open_artifact")
    selected = next((a for a in artifacts if a["id"] == open_id), None)

    if selected is None:
        st.markdown("### Artifacts")
        st.caption("Select an artifact from the list to view it.")
        st.stop()

    st.markdown(f"### {selected['title']}")

    new_title = st.text_input("Rename", value=selected["title"],
                              key=f"artitle_{selected['id']}",
                              label_visibility="collapsed")
    if new_title != selected["title"]:
        selected["title"] = new_title

    if selected.get("source_question"):
        st.markdown(f"**Question:** {selected['source_question']}")

    result = selected.get("result")
    if result:
        render_answer_card(result, key_prefix=f"art_{selected['id']}")

    action1, action2, _sp = st.columns([1.5, 1.5, 3])
    with action1:
        source_session = selected.get("source_session_id")
        if source_session:
            sessions = ss.get("chat_sessions", [])
            matching = [s for s in sessions if s["id"] == source_session]
            if matching:
                if st.button(f":material/forum: View full chat",
                             key=f"goto_{selected['id']}",
                             use_container_width=True):
                    ss.active_session_id = source_session
                    active = matching[0]
                    ss.session_id = active["id"]
                    ss.context = active["context"]
                    ss.messages = active["messages"]
                    st.switch_page("pages/chat.py")
    with action2:
        if st.button(":material/delete: Remove",
                     key=f"del_{selected['id']}",
                     use_container_width=True):
            ss.artifacts = [a for a in ss.artifacts if a["id"] != selected["id"]]
            ss["open_artifact"] = None
            st.rerun()
