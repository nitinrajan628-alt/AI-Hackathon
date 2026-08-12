"""Deterministic rule-based provider.

Implements the LLMProvider protocol without any network call. Used by the
automated tests and available as an offline demonstration mode
(LLM_PROVIDER=fake). Planning decisions follow simple keyword rules; answer
drafts are assembled verbatim from the supplied evidence, so the provider
can never introduce numbers that are not in the evidence package.
"""
from __future__ import annotations

import re
import time
from typing import Type, TypeVar

from pydantic import BaseModel

from models.ai_contracts import (
    AnswerDraft,
    EvidenceReference,
    ModelCallMetadata,
    PlanningResponse,
    StructuredModelResponse,
)

T = TypeVar("T", bound=BaseModel)

BLOCK_RULES = [
    ("reserve_recommendation", r"(what reserve should|should we (hold|book|strengthen|release|increase|reduce)|recommend\w* (a )?reserve)"),
    ("adequacy_opinion", r"(adequate|adequacy|sufficient (margin|reserve)|do you think)"),
    ("recalculation", r"(recalculat|re-calculat|rerun|re-run|recompute|with \d+(\.\d+)?% inflation)"),
    ("assumption_selection", r"(which (projection )?method should|what (loss ratio|inflation) should)"),
    ("forecast", r"(what will .* be|forecast|predict|next quarter'?s reserve)"),
    ("arbitrary_code", r"(run (this|the|some) (sql|python|code|script|query)|\bselect\b.+\bfrom\b|drop table)"),
]

DIM_PATTERNS = [
    ("finance_class", r"finance class"),
    ("business_unit", r"business unit"),
    ("region", r"\bregion"),
    ("loss_type", r"loss type"),
    ("accident_year", r"accident year"),
    ("entity", r"\bentity|\blegal entity"),
    ("reserving_class", r"reserving class|by class"),
]

CLASS_VALUES = ["Motor", "Property", "Casualty", "Marine"]
FC_VALUES = ["Personal Lines", "Commercial Lines", "Specialty Lines", "Reinsurance"]

MEASURES = [
    ("ibnr", r"\bibnr\b"),
    ("case_reserves", r"case reserve"),
    ("ultimate_claims", r"ultimate"),
    ("paid_claims", r"paid claim|paid\b"),
    ("incurred_claims", r"incurred"),
    ("earned_premium", r"earned premium"),
    ("written_premium", r"written premium|\bpremium\b"),
    ("total_reserve", r"reserve"),
]


class FakeProvider:
    """Keyword-rule planning and evidence-echo answer drafting."""

    def generate_structured(
        self,
        *,
        purpose: str,
        system_instruction: str,
        input_payload: dict,
        response_model: Type[T],
    ) -> StructuredModelResponse[T]:
        started = time.perf_counter()
        if response_model is PlanningResponse:
            value = self._plan(input_payload)
        elif response_model is AnswerDraft:
            value = self._answer(input_payload)
        else:
            raise ValueError(f"FakeProvider cannot produce {response_model.__name__}")
        metadata = ModelCallMetadata(
            provider="fake", model="rule-based",
            latency_ms=int((time.perf_counter() - started) * 1000))
        return StructuredModelResponse(value=value, metadata=metadata)

    # ------------------------------------------------------------- planning

    def _plan(self, payload: dict) -> PlanningResponse:
        q = payload.get("question", "").lower()
        ctx = payload.get("conversation_context", {}) or {}
        current = ctx.get("current_review_id") or "2026-Q2"
        reviews = payload.get("available_reviews", [])
        idx = reviews.index(current) if current in reviews else len(reviews) - 1
        prior = reviews[idx - 1] if idx > 0 else None
        prior_year = reviews[idx - 4] if idx >= 4 else None

        for category, pattern in BLOCK_RULES:
            if re.search(pattern, q):
                return PlanningResponse(
                    intent="OUT_OF_SCOPE", policy={"status": "BLOCK", "category": category})

        report_q = bool(re.search(
            r"report (say|says|state|highlight)|key messages|summar|commentary|"
            r"what does the report|according to the report|uncertaint", q))
        wants_data = bool(re.search(
            r"how much|movement|change|compare|breakdown|break .*down|split|"
            r"show|trend|top |largest|drove|driver|increas|decreas|why", q))

        # Follow-up: inherit context ("now split that by region")
        inherit = bool(re.search(r"\b(that|same|it|instead|now)\b", q)) and ctx.get("last_dataset")

        group_by: list[str] = []
        for dim, pattern in DIM_PATTERNS:
            if re.search(pattern, q) and dim not in group_by:
                group_by.append(dim)

        filters = []
        for cv in CLASS_VALUES:
            if re.search(rf"\b{cv.lower()}\b", q):
                filters.append({"field": "reserving_class", "operator": "eq", "value": cv})
                break
        for fv in FC_VALUES:
            if fv.lower() in q:
                filters.append({"field": "finance_class", "operator": "eq", "value": fv})
                break

        measure = next((m for m, p in MEASURES if re.search(p, q)), "total_reserve")
        dataset = "results"
        if measure in ("paid_claims", "incurred_claims") and "result" not in q:
            dataset = "claims_latest"
        if measure in ("earned_premium", "written_premium"):
            dataset = "premium"

        method_changes = bool(re.search(r"(method|assumption)s? .*(chang|differ)|"
                                        r"chang\w+ .*(method|assumption)", q))
        trend = bool(re.search(r"trend|over the last|history|evolved|eight quarters|"
                               r"across (all )?quarters|develop over", q))
        yoy = bool(re.search(r"(this year (versus|vs|and) last|year.on.year|"
                             r"same quarter last year|between this year and last)", q))
        qoq = bool(re.search(r"last quarter|previous quarter|prior quarter", q))

        plans = []
        searches = []
        ctx_updates: dict = {}
        if method_changes and prior:
            plans.append({
                "intent": "ASSUMPTION_CHANGES", "primary_dataset": "assumptions",
                "review_ids": [current, prior], "measures": [],
                "attributes": ["projection_method"],
                "group_by": ["entity", "reserving_class", "loss_type", "accident_year"],
                "filters": [], "operation": "list_changes",
                "sort": [{"field": "reserving_class", "direction": "asc"}],
                "limit": 200, "chart": "none"})
            intent = "ASSUMPTION_CHANGES"
        elif trend:
            plans.append({
                "intent": "TREND", "primary_dataset": dataset,
                "review_ids": reviews, "measures": [measure], "attributes": [],
                "group_by": group_by[:1], "filters": filters, "operation": "trend",
                "sort": [], "limit": 20, "chart": "line"})
            intent = "TREND"
        elif inherit and wants_data:
            last_ds = ctx.get("last_dataset") or dataset
            last_measure = ctx.get("last_measure") or measure
            comparisons = ctx.get("comparison_review_ids") or ([prior] if prior else [])
            rids = [current] + comparisons[:1] if comparisons else [current]
            op = "compare" if len(rids) == 2 else "aggregate"
            plans.append({
                "intent": "PERIOD_COMPARISON" if op == "compare" else "STRUCTURED_QUERY",
                "primary_dataset": last_ds, "review_ids": rids,
                "measures": [last_measure], "attributes": [],
                "group_by": group_by or (ctx.get("last_group_by") or []),
                "filters": filters or (ctx.get("active_filters") or []),
                "operation": op,
                "sort": [{"field": "absolute_change", "direction": "desc"}] if op == "compare" else [],
                "limit": 20, "chart": "auto"})
            intent = plans[0]["intent"]
        elif wants_data and (yoy or qoq) and (prior or prior_year):
            comparison = prior_year if (yoy and prior_year) else prior
            plans.append({
                "intent": "PERIOD_COMPARISON", "primary_dataset": dataset,
                "review_ids": [current, comparison], "measures": [measure],
                "attributes": [], "group_by": group_by, "filters": filters,
                "operation": "compare",
                "sort": [{"field": "absolute_change", "direction": "desc"}],
                "limit": 20, "chart": "auto"})
            intent = "PERIOD_COMPARISON"
        elif wants_data:
            movementish = bool(re.search(r"increas|decreas|movement|change|why", q))
            if movementish and prior:
                plans.append({
                    "intent": "PERIOD_COMPARISON", "primary_dataset": dataset,
                    "review_ids": [current, prior], "measures": [measure],
                    "attributes": [], "group_by": group_by, "filters": filters,
                    "operation": "compare",
                    "sort": [{"field": "absolute_change", "direction": "desc"}],
                    "limit": 20, "chart": "auto"})
                intent = "PERIOD_COMPARISON"
            else:
                plans.append({
                    "intent": "STRUCTURED_QUERY", "primary_dataset": dataset,
                    "review_ids": [current], "measures": [measure], "attributes": [],
                    "group_by": group_by or ["reserving_class"], "filters": filters,
                    "operation": "aggregate", "sort": [], "limit": 20, "chart": "auto"})
                intent = "STRUCTURED_QUERY"
        else:
            intent = "REPORT_QA"

        if report_q:
            terms = re.sub(r"[^a-z0-9 ]", " ", q)
            stop = {"what", "does", "the", "report", "say", "says", "about", "are",
                    "this", "quarter", "from", "key", "of", "s"}
            words = [w for w in terms.split() if w not in stop][:6]
            searches.append({"review_ids": [current], "query": " ".join(words) or "summary",
                             "limit": 5})
            if plans:
                intent = "MIXED_REPORT_DATA"

        if plans:
            p0 = plans[0]
            ctx_updates = {
                "comparison_review_ids": [r for r in p0["review_ids"][1:]],
                "active_filters": p0["filters"],
                "last_group_by": p0["group_by"],
                "last_measure": (p0["measures"] or [None])[0],
                "last_dataset": p0["primary_dataset"],
            }

        return PlanningResponse(
            intent=intent, report_searches=searches, query_plans=plans,
            policy={"status": "ALLOW"},
            context_updates=ctx_updates or {})

    # -------------------------------------------------------------- answers

    def _answer(self, payload: dict) -> AnswerDraft:
        evidence = payload.get("evidence", {})
        period = payload.get("period_context", {}).get("display_label", "")
        observations: list[str] = []
        refs: list[EvidenceReference] = []
        headline = "Result calculated from the stored review data"

        for qr in evidence.get("query_results", []):
            refs.append(EvidenceReference(evidence_type="query_result",
                                          evidence_id=qr["result_id"]))
            unit = qr.get("unit", "")
            summary = qr.get("summary", {})
            measure = (qr.get("measure") or "value").replace("_", " ")
            measure = measure if measure.startswith("total") else f"total {measure}"
            if "current_total" in summary:
                cur, mv = summary["current_total"], summary.get("absolute_change_total")
                headline = (f"{measure.capitalize()} of {_fmt(cur, unit)} for {period}, "
                            f"a movement of {_fmt(mv, unit, signed=True)}")
            elif f"total_{qr.get('measure')}" in summary:
                headline = (f"{measure.capitalize()} of "
                            f"{_fmt(summary[f'total_{qr.get('measure')}'], unit)} for {period}")
            elif "change_count" in summary:
                headline = (f"{summary['change_count']} {summary.get('compared_field', 'value').replace('_', ' ')} "
                            f"changes for {period}")
            for row in qr.get("rows", [])[:3]:
                dims = [str(v) for k, v in row.items()
                        if k in qr.get("group_by", [])]
                if "absolute_change" in row:
                    observations.append(
                        f"{' / '.join(dims) or 'Total'}: {_fmt(row.get('current'), unit)} "
                        f"({_fmt(row.get('absolute_change'), unit, signed=True)}).")
                elif "current_value" in row:
                    observations.append(
                        f"{' / '.join(str(v) for v in row.values())}")

        for slide in evidence.get("report_slides", []):
            refs.append(EvidenceReference(evidence_type="report_slide",
                                          evidence_id=slide["evidence_id"]))
            first = slide.get("excerpt", "").split("\n")
            snippet = next((t for t in first if t.strip()), "")[:200]
            observations.append(
                f"The report states: \"{snippet}\" (slide {slide.get('slide_number')}).")
            if headline == "Result calculated from the stored review data":
                headline = f"From the report: {slide.get('title', '')}"

        limitations = [str(l) for l in evidence.get("limitations", [])]
        return AnswerDraft(headline=headline, observations=observations[:5],
                           limitations=limitations, evidence_references=refs)


def _fmt(value, unit: str, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if unit == "GBP millions":
        sign = "+" if (signed and value > 0) else ("-" if value < 0 else "")
        return f"{sign}GBP {abs(value):,.1f}m".replace(".0m", "m")
    if unit == "percent":
        return f"{value:.1f}%"
    return f"{value:,.0f}"
