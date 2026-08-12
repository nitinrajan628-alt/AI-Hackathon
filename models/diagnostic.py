"""Diagnostic persistence record (Detailed Build Specification section 5.9)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DiagnosticRecord(BaseModel):
    diagnostic_id: str
    session_id: str
    created_at: str
    title: str
    user_question: str
    primary_review_id: str
    comparison_review_ids: list[str] = Field(default_factory=list)
    intent: str
    query_plan: dict | None = None
    compiled_query: str | None = None
    query_parameters: list | None = None
    result: dict | None = None
    chart_spec: dict | None = None
    evidence: dict = Field(default_factory=dict)
    answer_text: str
    status: str  # SUCCESS, BLOCKED, NO_RESULT or ERROR
    query_hash: str | None = None
    duration_ms: int | None = None
