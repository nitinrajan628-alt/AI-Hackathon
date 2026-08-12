"""Database access. Review data is opened read-only; diagnostics/audit
records live in a separate writable SQLite file so the packaged review
snapshots stay immutable."""
from __future__ import annotations

import sqlite3

from services.settings import DIAGNOSTICS_DB_PATH, REVIEW_DB_PATH

DIAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnostic (
  diagnostic_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  title TEXT NOT NULL,
  user_question TEXT NOT NULL,
  primary_review_id TEXT NOT NULL,
  comparison_review_ids_json TEXT,
  intent TEXT NOT NULL,
  query_plan_json TEXT,
  compiled_query TEXT,
  query_parameters_json TEXT,
  result_json TEXT,
  chart_spec_json TEXT,
  evidence_json TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  status TEXT NOT NULL,
  query_hash TEXT,
  duration_ms INTEGER,
  in_library INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_session (
  session_id TEXT PRIMARY KEY,
  current_review_id TEXT NOT NULL,
  active_context_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_message (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  intent TEXT,
  diagnostic_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_call_log (
  call_id TEXT PRIMARY KEY,
  purpose TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  provider_request_id TEXT,
  started_at TEXT NOT NULL,
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  schema_name TEXT,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  error_category TEXT,
  input_hash TEXT,
  output_hash TEXT
);
"""


def get_review_connection() -> sqlite3.Connection:
    """Read-only connection to the packaged review database."""
    con = sqlite3.connect(f"file:{REVIEW_DB_PATH}?mode=ro", uri=True,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def get_diagnostics_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DIAGNOSTICS_DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(DIAG_SCHEMA)
    return con
