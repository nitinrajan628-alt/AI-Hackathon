"""Facade running one validated query end to end: validate -> compile ->
execute (read-only) -> approved deterministic shaping."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from models.evidence import CompiledQuery, ValidatedPlan
from models.query_plan import QueryPlan
from services import diagnostics as diag
from services.catalogue import get_catalogue
from services.plan_repair import repair_plan_scope
from services.policy import validate_plan
from services.query_compiler import compile_query
from services.query_executor import execute_query
from services.review_service import list_reviews


@dataclass
class EngineResult:
    validated: ValidatedPlan
    compiled: CompiledQuery
    shaped: diag.ShapedResult


def run_plan(plan: QueryPlan, con: sqlite3.Connection | None = None,
             question: str | None = None) -> EngineResult:
    cat = get_catalogue()
    reviews = {r["review_id"]: r for r in list_reviews()}
    repair_notes: list[str] = []
    if question:
        plan, repair_notes = repair_plan_scope(question, plan, cat)
    vp = validate_plan(plan, cat, list(reviews))
    vp.inferred_defaults = repair_notes + vp.inferred_defaults
    compiled = compile_query(vp)
    raw = execute_query(compiled, con)
    shaped = diag.apply(vp, raw.df, reviews, cat.measures(vp.dataset))
    return EngineResult(validated=vp, compiled=compiled, shaped=shaped)
