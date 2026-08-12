"""Deep-analysis battery.

A single question such as "analyse how Casualty has developed across accident
years" cannot be answered from one table. This service runs a *battery* of
approved, deterministic diagnostics around the detected focus and hands the
whole set to the answer model at once, so the model reasons across evidence
instead of reading a single result back.

Every query in the battery goes through the same catalogue validation, SQL
compilation and read-only execution as any other question - nothing here
bypasses the policy layer, and no figure is calculated outside SQL or the
tested comparison functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from models.query_plan import FilterSpec, QueryPlan
from services.catalogue import Catalogue, get_catalogue
from services.engine import EngineResult, run_plan
from services.policy import PlanValidationError
from services.query_executor import QueryExecutionError
from services.review_service import (
    prior_review_id,
    prior_year_review_id,
    review_ids,
    sequence_map,
)

# Phrasing that asks for interpretation rather than a single figure.
ANALYTICAL_LANGUAGE = re.compile(
    r"\b(analyse|analyze|analysis|deep\s*dive|deep-dive|drill\s*(in|into|down)|"
    r"why\b|what(?:'s| is| are)?\s+driving|drivers?\b|explain|"
    r"investigate|assess|review\s+in\s+detail|break\s*down\s+.*\b(fully|in detail)|"
    r"tell\s+me\s+about|walk\s+me\s+through|story|develop(?:ed|ment|ing)\s+over|"
    r"how\s+has\s+.*\b(develop|evolve|change)|what\s+is\s+going\s+on)\b",
    re.IGNORECASE)

# Focus dimensions the battery can pivot on, in preference order.
_FOCUS_DIMENSIONS = ["reserving_class", "finance_class", "region",
                     "business_unit", "loss_type", "entity"]


@dataclass
class AnalysisFocus:
    """What the analysis is about."""
    filters: list[FilterSpec] = field(default_factory=list)
    breakdown: str = "accident_year"        # primary dimension to analyse across
    label: str = "the portfolio"

    def filter_dicts(self) -> list[dict]:
        return [f.model_dump() for f in self.filters]


@dataclass
class AnalysisResult:
    focus: AnalysisFocus
    outputs: list[EngineResult] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def as_pairs(self):
        return list(zip(self.titles, self.outputs))


def is_analytical(question: str) -> bool:
    return bool(ANALYTICAL_LANGUAGE.search(question or ""))


def detect_focus(question: str, cat: Catalogue,
                 inherited_filters: list[dict] | None = None) -> AnalysisFocus:
    """Work out what the user wants analysed, from named dimension values."""
    text = (question or "").lower()
    filters: list[FilterSpec] = []
    labels: list[str] = []

    for dim in _FOCUS_DIMENSIONS:
        for value in cat.dimension_values.get(dim, []):
            if re.search(rf"\b{re.escape(value.lower())}\b", text):
                filters.append(FilterSpec(field=dim, operator="eq", value=value))
                labels.append(value)
                break
        if filters and dim == "reserving_class":
            break   # a named reserving class is the strongest signal

    if not filters and inherited_filters:
        for f in inherited_filters:
            try:
                spec = FilterSpec(**f)
            except Exception:
                continue
            if spec.field in _FOCUS_DIMENSIONS:
                filters.append(spec)
                labels.append(str(spec.value))

    breakdown = "accident_year"
    if re.search(r"\b(by|across|per)\s+(reserving\s+)?class", text) and not filters:
        breakdown = "reserving_class"
    elif re.search(r"\bregion", text) and not any(f.field == "region" for f in filters):
        breakdown = "region"
    elif re.search(r"\bfinance\s+class", text) and not any(
            f.field == "finance_class" for f in filters):
        breakdown = "finance_class"

    label = " / ".join(labels) if labels else "the portfolio"
    return AnalysisFocus(filters=filters, breakdown=breakdown, label=label)


def _plan(**kwargs) -> QueryPlan:
    base = dict(intent="STRUCTURED_QUERY", primary_dataset="results",
                measures=["total_reserve"], operation="aggregate", limit=60)
    base.update(kwargs)
    return QueryPlan(**base)


def build_battery(question: str, current_review_id: str,
                  focus: AnalysisFocus,
                  cross_class: bool = True) -> list[tuple[str, QueryPlan]]:
    """The deterministic set of diagnostics that constitutes an analysis."""
    prior = prior_review_id(current_review_id)
    prior_year = prior_year_review_id(current_review_id)
    filters = focus.filter_dicts()
    dim = focus.breakdown
    battery: list[tuple[str, QueryPlan]] = []

    # 1. Current position across the breakdown dimension.
    battery.append((
        f"Reserve by {dim.replace('_', ' ')} ({focus.label})",
        _plan(review_ids=[current_review_id], group_by=[dim], filters=filters,
              operation="aggregate", chart="bar")))

    # 2. Quarter-on-quarter movement across the breakdown dimension.
    if prior:
        battery.append((
            f"Quarter-on-quarter movement by {dim.replace('_', ' ')}",
            _plan(intent="PERIOD_COMPARISON", review_ids=[current_review_id, prior],
                  group_by=[dim], filters=filters, operation="compare",
                  sort=[{"field": "absolute_change", "direction": "desc"}],
                  chart="diverging_bar")))
        # 3. Contribution of each group to the total movement.
        battery.append((
            f"Contribution to the total movement by {dim.replace('_', ' ')}",
            _plan(intent="PERIOD_COMPARISON", review_ids=[current_review_id, prior],
                  group_by=[dim], filters=filters,
                  operation="contribution_to_movement",
                  sort=[{"field": "absolute_change", "direction": "desc"}],
                  chart="none")))

    # 4. Year-on-year movement, which separates development from seasonality.
    if prior_year:
        battery.append((
            f"Year-on-year movement by {dim.replace('_', ' ')}",
            _plan(intent="PERIOD_COMPARISON",
                  review_ids=[current_review_id, prior_year],
                  group_by=[dim], filters=filters, operation="compare",
                  sort=[{"field": "absolute_change", "direction": "desc"}],
                  chart="none")))

    # 5. Full-history trend of the total for the focus.
    all_reviews = review_ids()
    battery.append((
        "Reserve trend across the review history",
        _plan(intent="TREND", review_ids=all_reviews, group_by=[], filters=filters,
              operation="trend", limit=8, chart="line")))

    # 6. Reserve composition: IBNR versus case reserves.
    battery.append((
        f"IBNR and case reserves by {dim.replace('_', ' ')}",
        _plan(review_ids=[current_review_id], group_by=[dim], filters=filters,
              measures=["ibnr", "case_reserves", "ultimate_claims"],
              operation="aggregate", chart="none")))

    # 7. Claims development on the latest diagonal (paid and incurred).
    battery.append((
        f"Paid and incurred claims by {dim.replace('_', ' ')}",
        _plan(primary_dataset="claims_latest", review_ids=[current_review_id],
              group_by=[dim], filters=filters,
              measures=["paid_claims", "incurred_claims"],
              operation="aggregate", chart="none")))

    # 8. Assumption changes at the selection grain for the same focus.
    if prior:
        assumption_filters = [f for f in filters
                              if f["field"] in ("entity", "reserving_class",
                                                "loss_type")]
        battery.append((
            "Projection-method changes since the prior review",
            _plan(intent="ASSUMPTION_CHANGES", primary_dataset="assumptions",
                  review_ids=[current_review_id, prior], measures=[],
                  attributes=["projection_method"],
                  group_by=["entity", "reserving_class", "loss_type",
                            "accident_year"],
                  filters=assumption_filters, operation="list_changes",
                  limit=200, chart="none")))

    # 9-10. Cross-class comparison: is this focus-specific or portfolio-wide?
    if cross_class and prior:
        battery.append((
            "Whole-portfolio movement by Reserving Class (for comparison)",
            _plan(intent="PERIOD_COMPARISON", review_ids=[current_review_id, prior],
                  group_by=["reserving_class"], filters=[], operation="compare",
                  sort=[{"field": "absolute_change", "direction": "desc"}],
                  chart="none")))
        battery.append((
            "Whole-portfolio movement by accident year (for comparison)",
            _plan(intent="PERIOD_COMPARISON", review_ids=[current_review_id, prior],
                  group_by=["accident_year"], filters=[], operation="compare",
                  sort=[{"field": "absolute_change", "direction": "desc"}],
                  chart="none")))

    return battery


def run_analysis(question: str, current_review_id: str,
                 inherited_filters: list[dict] | None = None,
                 cross_class: bool = True) -> AnalysisResult:
    """Execute the battery, skipping any diagnostic that is not valid for the
    detected focus rather than failing the whole analysis."""
    cat = get_catalogue()
    focus = detect_focus(question, cat, inherited_filters)
    result = AnalysisResult(focus=focus)
    if focus.filters:
        result.notes.append(
            "Analysis scoped to " + ", ".join(
                f"{f.field.replace('_', ' ')} = {f.value}" for f in focus.filters))

    for title, plan in build_battery(question, current_review_id, focus,
                                     cross_class=cross_class):
        try:
            engine_result = run_plan(plan)
        except (PlanValidationError, QueryExecutionError) as exc:
            result.skipped.append(f"{title}: {exc}")
            continue
        if engine_result.shaped.df.empty:
            result.skipped.append(f"{title}: no matching rows")
            continue
        result.outputs.append(engine_result)
        result.titles.append(title)
    return result
