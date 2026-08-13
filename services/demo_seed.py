"""Pre-populate demo chat sessions and artifacts on first app load.

Runs each question through the real LLM so responses are generated fresh,
not hard-coded.  A Streamlit status widget shows progress while seeding.
"""
from __future__ import annotations

import uuid
import logging

import streamlit as st

from services.context_service import ConversationContext
from services.naming_service import generate_artifact_title, generate_chat_title
from services.orchestrator import handle_question
from services.review_service import default_review_id
from services.settings import get_llm_settings

log = logging.getLogger(__name__)

DEMO_CHATS: list[list[str]] = [
    [
        "What can you do?",
    ],
    [
        "What are the main areas of uncertainty highlighted by the report?",
    ],
    [
        "Show me the IBNR by reserving class.",
        "What are the Outstanding Claims by accident year?",
        "Has there been a change in projection method used for Casualty "
        "between last quarter's review?",
        "Show me the IBNR by finance class instead of reserving class.",
    ],
]

ARTIFACT_CHAT_INDEX = 2
ARTIFACT_QUESTION_INDEX = -1


def seed_demo_sessions() -> tuple[list[dict], list[dict]]:
    """Create demo chat sessions with live LLM responses.

    Returns (chat_sessions, artifacts).
    """
    settings = get_llm_settings()
    sessions: list[dict] = []
    artifacts: list[dict] = []
    total_questions = sum(len(chat) for chat in DEMO_CHATS)
    question_number = 0

    with st.status("Preparing demo content…", expanded=True) as status:
        for chat_index, questions in enumerate(DEMO_CHATS):
            session = {
                "id": str(uuid.uuid4()),
                "title": "New chat",
                "messages": [],
                "context": ConversationContext(
                    current_review_id=default_review_id()
                ),
                "created_at": str(uuid.uuid4())[:8],
            }

            for q_index, question in enumerate(questions):
                question_number += 1
                status.update(
                    label=f"Preparing demo — Chat {chat_index + 1}/{len(DEMO_CHATS)}, "
                          f"Question {q_index + 1}/{len(questions)} "
                          f"({question_number}/{total_questions})"
                )

                try:
                    result = handle_question(
                        question,
                        session["id"],
                        session["context"],
                        settings=settings,
                    )
                except Exception:
                    log.exception("Demo seed failed for %r", question)
                    continue

                session["messages"].append(
                    {"role": "user", "content": question, "result": None}
                )
                session["messages"].append(
                    {"role": "assistant", "content": result.answer_text,
                     "result": result}
                )

                if session["title"] == "New chat":
                    headline = (
                        result.draft.headline
                        if result.draft
                        else result.answer_text.splitlines()[0][:60]
                    )
                    try:
                        session["title"] = generate_chat_title(
                            question, headline
                        )
                    except Exception:
                        session["title"] = question[:50]

                if (chat_index == ARTIFACT_CHAT_INDEX
                        and q_index == len(questions) + ARTIFACT_QUESTION_INDEX):
                    headline = (
                        result.draft.headline
                        if result.draft
                        else result.answer_text.splitlines()[0][:60]
                    )
                    try:
                        title = generate_artifact_title(question, headline)
                    except Exception:
                        title = question[:50]
                    artifacts.append({
                        "id": str(uuid.uuid4()),
                        "diagnostic_id": result.diagnostic_id,
                        "title": title,
                        "source_session_id": session["id"],
                        "source_question": question,
                        "result": result,
                        "created_at": str(uuid.uuid4())[:8],
                    })

            sessions.append(session)

        status.update(label="Demo ready", state="complete")

    return sessions, artifacts


def seed_demo_sessions_headless() -> tuple[list[dict], list[dict]]:
    """Same as seed_demo_sessions but without Streamlit UI calls.

    Suitable for running in a background thread where st.status() is
    unavailable.
    """
    settings = get_llm_settings()
    sessions: list[dict] = []
    artifacts: list[dict] = []

    for chat_index, questions in enumerate(DEMO_CHATS):
        session = {
            "id": str(uuid.uuid4()),
            "title": "New chat",
            "messages": [],
            "context": ConversationContext(
                current_review_id=default_review_id()
            ),
            "created_at": str(uuid.uuid4())[:8],
        }

        for q_index, question in enumerate(questions):
            try:
                result = handle_question(
                    question,
                    session["id"],
                    session["context"],
                    settings=settings,
                )
            except Exception:
                log.exception("Background seed failed for %r", question)
                continue

            session["messages"].append(
                {"role": "user", "content": question, "result": None}
            )
            session["messages"].append(
                {"role": "assistant", "content": result.answer_text,
                 "result": result}
            )

            if session["title"] == "New chat":
                headline = (
                    result.draft.headline
                    if result.draft
                    else result.answer_text.splitlines()[0][:60]
                )
                try:
                    session["title"] = generate_chat_title(
                        question, headline
                    )
                except Exception:
                    session["title"] = question[:50]

            if (chat_index == ARTIFACT_CHAT_INDEX
                    and q_index == len(questions) + ARTIFACT_QUESTION_INDEX):
                headline = (
                    result.draft.headline
                    if result.draft
                    else result.answer_text.splitlines()[0][:60]
                )
                try:
                    title = generate_artifact_title(question, headline)
                except Exception:
                    title = question[:50]
                artifacts.append({
                    "id": str(uuid.uuid4()),
                    "diagnostic_id": result.diagnostic_id,
                    "title": title,
                    "source_session_id": session["id"],
                    "source_question": question,
                    "result": result,
                    "created_at": str(uuid.uuid4())[:8],
                })

        sessions.append(session)

    log.info("Background demo seed complete: %d sessions, %d artifacts",
             len(sessions), len(artifacts))
    return sessions, artifacts
