"""Audit and diagnostics persistence (Detailed Build Specification
sections 5.9, 9.11, 12). Writes go to the separate diagnostics database so
review snapshots stay immutable."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

from models.ai_contracts import ModelCallMetadata
from models.diagnostic import DiagnosticRecord
from services.db import get_diagnostics_connection
from services.settings import REVIEW_DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_version() -> str:
    """Stable identifier of the packaged review database version."""
    try:
        stat = os.stat(REVIEW_DB_PATH)
        basis = f"{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        basis = "missing"
    return hashlib.sha256(basis.encode()).hexdigest()[:12]


def query_hash(plan_dict: dict | None) -> str | None:
    if not plan_dict:
        return None
    canonical = json.dumps(plan_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{canonical}|{data_version()}".encode()).hexdigest()[:16]


def result_hash(result_json: dict | None) -> str | None:
    if result_json is None:
        return None
    canonical = json.dumps(result_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Sessions and messages
# ---------------------------------------------------------------------------

def ensure_session(session_id: str, review_id: str, context: dict | None = None):
    con = get_diagnostics_connection()
    try:
        row = con.execute("SELECT session_id FROM chat_session WHERE session_id=?",
                          (session_id,)).fetchone()
        if row:
            con.execute(
                "UPDATE chat_session SET current_review_id=?, active_context_json=?,"
                " updated_at=? WHERE session_id=?",
                (review_id, json.dumps(context or {}), _now(), session_id))
        else:
            con.execute(
                "INSERT INTO chat_session VALUES (?,?,?,?,?)",
                (session_id, review_id, json.dumps(context or {}), _now(), _now()))
        con.commit()
    finally:
        con.close()


def log_message(session_id: str, role: str, content: str,
                intent: str | None = None, diagnostic_id: str | None = None) -> str:
    message_id = str(uuid.uuid4())
    con = get_diagnostics_connection()
    try:
        con.execute("INSERT INTO chat_message VALUES (?,?,?,?,?,?,?)",
                    (message_id, session_id, role, content, intent,
                     diagnostic_id, _now()))
        con.commit()
    finally:
        con.close()
    return message_id


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def save_diagnostic(record: DiagnosticRecord, in_library: bool) -> str:
    con = get_diagnostics_connection()
    try:
        con.execute(
            """INSERT OR REPLACE INTO diagnostic
               (diagnostic_id, session_id, created_at, title, user_question,
                primary_review_id, comparison_review_ids_json, intent,
                query_plan_json, compiled_query, query_parameters_json,
                result_json, chart_spec_json, evidence_json, answer_text,
                status, query_hash, duration_ms, in_library)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (record.diagnostic_id, record.session_id, record.created_at,
             record.title, record.user_question, record.primary_review_id,
             json.dumps(record.comparison_review_ids),
             record.intent,
             json.dumps(record.query_plan) if record.query_plan else None,
             record.compiled_query,
             json.dumps(record.query_parameters) if record.query_parameters is not None else None,
             json.dumps(record.result) if record.result is not None else None,
             json.dumps(record.chart_spec) if record.chart_spec is not None else None,
             json.dumps(record.evidence), record.answer_text, record.status,
             record.query_hash, record.duration_ms, 1 if in_library else 0))
        con.commit()
    finally:
        con.close()
    return record.diagnostic_id


def set_in_library(diagnostic_id: str, in_library: bool = True):
    con = get_diagnostics_connection()
    try:
        con.execute("UPDATE diagnostic SET in_library=? WHERE diagnostic_id=?",
                    (1 if in_library else 0, diagnostic_id))
        con.commit()
    finally:
        con.close()


def rename_diagnostic(diagnostic_id: str, title: str):
    con = get_diagnostics_connection()
    try:
        con.execute("UPDATE diagnostic SET title=? WHERE diagnostic_id=?",
                    (title, diagnostic_id))
        con.commit()
    finally:
        con.close()


def list_diagnostics(search: str | None = None, library_only: bool = True) -> list[dict]:
    con = get_diagnostics_connection()
    try:
        sql = "SELECT * FROM diagnostic"
        clauses, params = [], []
        if library_only:
            clauses.append("in_library=1")
        if search:
            clauses.append("(title LIKE ? OR user_question LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT 200"
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def get_diagnostic(diagnostic_id: str) -> dict | None:
    con = get_diagnostics_connection()
    try:
        row = con.execute("SELECT * FROM diagnostic WHERE diagnostic_id=?",
                          (diagnostic_id,)).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Model-call audit
# ---------------------------------------------------------------------------

def log_model_call(purpose: str, metadata: ModelCallMetadata | None,
                   status: str, retry_count: int = 0,
                   schema_name: str = "", error_category: str | None = None,
                   input_payload: dict | None = None,
                   output_value: dict | None = None):
    con = get_diagnostics_connection()
    try:
        def _hash(obj) -> str | None:
            if obj is None:
                return None
            return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                             default=str).encode()).hexdigest()[:16]
        con.execute(
            "INSERT INTO model_call_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), purpose,
             metadata.provider if metadata else "n/a",
             metadata.model if metadata else "n/a",
             metadata.provider_request_id if metadata else None,
             _now(),
             metadata.latency_ms if metadata else None,
             metadata.input_tokens if metadata else None,
             metadata.output_tokens if metadata else None,
             metadata.total_tokens if metadata else None,
             schema_name, status, retry_count, error_category,
             _hash(input_payload), _hash(output_value)))
        con.commit()
    finally:
        con.close()


def new_diagnostic_id() -> str:
    return str(uuid.uuid4())


def created_at_now() -> str:
    return _now()
