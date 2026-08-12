"""Review metadata: list reviews, resolve relative periods, labels."""
from __future__ import annotations

from functools import lru_cache

from models.evidence import PeriodResolution
from services.db import get_review_connection


@lru_cache(maxsize=1)
def list_reviews() -> list[dict]:
    con = get_review_connection()
    rows = con.execute(
        "SELECT * FROM review_period ORDER BY sequence_no").fetchall()
    con.close()
    return [dict(r) for r in rows]


def review_ids() -> list[str]:
    return [r["review_id"] for r in list_reviews()]


def get_review(review_id: str) -> dict | None:
    for r in list_reviews():
        if r["review_id"] == review_id:
            return r
    return None


def default_review_id() -> str:
    for r in list_reviews():
        if r["is_default"]:
            return r["review_id"]
    return list_reviews()[-1]["review_id"]


def quarter_label(review_id: str | None) -> str:
    if not review_id:
        return ""
    r = get_review(review_id)
    return r["quarter_label"] if r else review_id.replace("-", " ")


def prior_review_id(review_id: str) -> str | None:
    r = get_review(review_id)
    return r["prior_review_id"] if r else None


def prior_year_review_id(review_id: str) -> str | None:
    r = get_review(review_id)
    return r["prior_year_review_id"] if r else None


def sequence_map() -> dict[str, int]:
    return {r["review_id"]: r["sequence_no"] for r in list_reviews()}


def comparison_label(review_ids_: list[str]) -> str:
    """Human label such as '2026 Q2 compared with 2026 Q1'."""
    labels = [quarter_label(r) for r in review_ids_]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} compared with {labels[1]}"
    ordered = sorted(review_ids_, key=lambda r: sequence_map().get(r, 0))
    return f"{quarter_label(ordered[0])} to {quarter_label(ordered[-1])}"


def resolve_periods(question: str, current_review_id: str) -> PeriodResolution:
    """Deterministic relative-period resolution used as planner context and
    as a fallback check. The AI planning call remains authoritative."""
    q = question.lower()
    comparisons: list[str] = []
    warnings: list[str] = []
    prior = prior_review_id(current_review_id)
    prior_year = prior_year_review_id(current_review_id)
    if any(p in q for p in ("last quarter", "previous quarter", "prior quarter",
                            "since last quarter", "quarter on quarter")):
        if prior:
            comparisons.append(prior)
        else:
            warnings.append("No prior review is available for the selected review.")
    if any(p in q for p in ("same quarter last year", "last year", "prior year",
                            "year on year", "this year versus last",
                            "this year vs last")):
        if prior_year:
            comparisons.append(prior_year)
        else:
            warnings.append("No prior-year review is available for the selected review.")
    label = quarter_label(current_review_id)
    if comparisons:
        label = comparison_label([current_review_id, comparisons[0]])
    return PeriodResolution(
        primary_review_id=current_review_id,
        comparison_review_ids=comparisons,
        interpretation_label=label,
        warnings=warnings,
    )
