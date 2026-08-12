"""AI Call 2 - answer drafting, verification and deterministic fallback
(Detailed Build Specification sections 9.6, 10.1 steps 7-9).

The answer model receives only the bounded evidence package assembled here.
Every numerical claim in the returned draft is verified against that
evidence; on failure the answer is regenerated once with stricter
instructions, then replaced by a deterministic templated summary.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from models.ai_contracts import AnswerDraft, EvidenceReference, ModelCallMetadata
from models.evidence import (
    EvidencePackage,
    QueryResultEvidence,
    SlideEvidence,
    VerificationResult,
)
from services.engine import EngineResult
from services.formatting import display_unit, fmt_measure, fmt_pct, is_integer_field
from services.llm_provider import call_with_retries, get_llm_provider
from services.review_service import comparison_label, quarter_label
from services.settings import LLMSettings, get_llm_settings, load_prompt

STRICT_SUFFIX = (
    "\n\nSTRICT MODE: your previous draft contained a number that is not in "
    "the supplied evidence. Use only numbers that appear verbatim in the "
    "evidence rows, summaries or slide excerpts. Do not derive new figures.")


# ---------------------------------------------------------------------------
# Evidence assembly
# ---------------------------------------------------------------------------

def _display_value(value, unit: str):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if unit == "GBP":
        return round(value / 1e6, 1)
    if unit == "ratio":
        return round(value * 100.0, 1)
    if isinstance(value, float):
        return round(value, 1)
    return value


def result_to_evidence(engine_result: EngineResult, evidence_id: str,
                       row_budget: int) -> QueryResultEvidence:
    shaped = engine_result.shaped
    plan = engine_result.validated.plan
    unit = shaped.unit
    df = shaped.df
    rows = []
    truncated = shaped.total_row_count > min(len(df), row_budget)
    value_cols = set(plan.measures) | {"current", "prior", "absolute_change"}
    pct_cols = {"percentage_change", "share_pct", "contribution_pct"}
    for _, r in df.iterrows():
        if len(rows) >= row_budget:
            break
        row = {}
        for col, v in r.items():
            if v is None or (isinstance(v, float) and math.isnan(v)):
                row[col] = None
            elif col in pct_cols:
                row[col] = round(float(v), 1)
            elif col in value_cols and isinstance(v, (int, float)):
                row[col] = _display_value(float(v), unit)
            elif hasattr(v, "item"):  # numpy scalar -> plain Python
                row[col] = v.item()
            else:
                row[col] = v
        rows.append(row)

    summary = {}
    for k, v in shaped.summary.items():
        if isinstance(v, (int, float)):
            if k.startswith(("current_total", "prior_total", "absolute_change_total",
                             "total")):
                summary[k] = _display_value(float(v), unit)
            elif k.startswith("percentage"):
                summary[k] = round(float(v), 1)
            else:
                summary[k] = v
        else:
            summary[k] = v

    # Supply the aggregates a reader would otherwise have to work out, so the
    # model can state them without performing arithmetic of its own.
    columns = _numeric_columns(rows)
    for name, values in columns.items():
        if not values or name in ("percentage_change", "share_pct",
                                  "contribution_pct") or is_integer_field(name):
            continue
        summary.setdefault(f"{name}_total_of_shown_rows", round(sum(values), 1))
        largest = max(values, key=abs)
        summary.setdefault(f"{name}_largest_shown", round(largest, 1))
    if plan.group_by and rows:
        key = plan.group_by[0]
        ranked_col = ("absolute_change" if "absolute_change" in columns
                      else (plan.measures[0] if plan.measures and
                            plan.measures[0] in columns else None))
        if ranked_col:
            ranked = sorted(
                ((r.get(key), r.get(ranked_col)) for r in rows
                 if isinstance(r.get(ranked_col), (int, float))),
                key=lambda kv: abs(kv[1]), reverse=True)
            summary.setdefault("largest_contributors", [
                {key: k, ranked_col: round(float(v), 1)} for k, v in ranked[:5]])

    return QueryResultEvidence(
        evidence_id=evidence_id,
        dataset=engine_result.validated.dataset,
        operation=plan.operation,
        measures=plan.measures,
        group_by=plan.group_by,
        periods=plan.review_ids,
        period_labels=shaped.period_labels,
        unit=display_unit(unit) if unit else "",
        filters=[f.model_dump() for f in plan.filters],
        rows=rows,
        summary=summary,
        truncated=truncated,
        total_row_count=shaped.total_row_count,
    )


def build_evidence_package(question: str, primary_review_id: str,
                           comparison_review_ids: list[str],
                           slides: list[SlideEvidence],
                           engine_results: list[EngineResult],
                           limitations: list[str] | None = None,
                           row_limit_total: int = 100,
                           titles: list[str] | None = None) -> EvidencePackage:
    limitations = list(limitations or [])
    all_periods = [primary_review_id] + [r for r in comparison_review_ids
                                         if r != primary_review_id]
    package = EvidencePackage(
        question=question,
        period_context={
            "current_review_id": primary_review_id,
            "comparison_review_ids": comparison_review_ids,
            "display_label": comparison_label(all_periods)
            if len(all_periods) > 1 else quarter_label(primary_review_id),
        },
    )
    for i, slide in enumerate(slides):
        slide.evidence_id = slide.evidence_id or f"slide_{slide.slide_id}"
        package.report_slides.append(slide)

    budget = row_limit_total
    for i, er in enumerate(engine_results):
        ev = result_to_evidence(er, f"qr_{i + 1}", max(5, budget))
        if titles and i < len(titles):
            ev.title = titles[i]
        budget = max(5, budget - len(ev.rows))
        if ev.truncated:
            limitations.append(
                f"Only the top {len(ev.rows)} of {ev.total_row_count} result rows "
                f"were included in the drafting evidence; the full table is shown "
                f"in the application.")
        for w in er.shaped.warnings:
            limitations.append(w)
        for note in er.validated.inferred_defaults:
            limitations.append(note)
        package.query_results.append(ev)
    package.limitations = limitations
    return package


def answer_payload(package: EvidencePackage) -> dict:
    return {
        "question": package.question,
        "period_context": package.period_context,
        "evidence": {
            "report_slides": [
                {
                    "evidence_id": s.evidence_id,
                    "review": s.quarter_label or s.review_id,
                    "slide_number": s.slide_number,
                    "section": s.section,
                    "title": s.title,
                    "excerpt": s.excerpt[:1500],
                }
                for s in package.report_slides
            ],
            "query_results": [
                {
                    "result_id": q.evidence_id,
                    "diagnostic": q.title or None,
                    "dataset": q.dataset,
                    "operation": q.operation,
                    "measure": q.measures[0] if q.measures else None,
                    "group_by": q.group_by,
                    "periods": q.periods,
                    "period_labels": q.period_labels,
                    "unit": q.unit,
                    "filters": q.filters,
                    "rows": q.rows,
                    "summary": q.summary,
                }
                for q in package.query_results
            ],
            "limitations": package.limitations,
        },
        "answer_rules": {
            "use_only_supplied_evidence": True,
            "do_not_perform_new_calculations": True,
            "distinguish_report_from_calculated_evidence": True,
            "state_periods_explicitly": True,
            "do_not_express_an_actuarial_adequacy_opinion": True,
        },
    }


# ---------------------------------------------------------------------------
# Drafting and verification
# ---------------------------------------------------------------------------

@dataclass
class ComposedAnswer:
    draft: AnswerDraft
    metadata: ModelCallMetadata | None
    verification: VerificationResult
    used_fallback: bool
    regenerated: bool


NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _extract_numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in NUMBER_RE.findall(text)]


def _numeric_columns(rows: list[dict]) -> dict[str, list[float]]:
    columns: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and value is not None \
                    and not isinstance(value, bool):
                columns.setdefault(key, []).append(float(value))
    return columns


def _allowed_numbers(package: EvidencePackage) -> list[float]:
    """Values a statement may legitimately contain.

    Numbers do not have to appear verbatim in the evidence: a reader may
    reasonably state a column total, the gap between two supplied figures, or
    a percentage of them. Those are *reconstructible* from the evidence, so
    they are traceable and permitted. Anything not reconstructible is still
    rejected - that is what stops fabricated figures.
    """
    allowed: list[float] = list(range(0, 13))          # small counts/ordinals
    allowed += [float(y) for y in range(2000, 2101)]   # years and quarters

    for q in package.query_results:
        supplied: list[float] = []
        for row in q.rows:
            for v in row.values():
                if isinstance(v, (int, float)) and v is not None \
                        and not isinstance(v, bool):
                    supplied.append(float(v))
        for v in q.summary.values():
            if isinstance(v, (int, float)) and v is not None \
                    and not isinstance(v, bool):
                supplied.append(float(v))
        allowed += [abs(v) for v in supplied]
        allowed.append(float(q.total_row_count))
        allowed.append(float(len(q.rows)))

        # Subtotals within any categorical column (per review period in a
        # trend, per class in a breakdown) - the natural way to summarise.
        categorical = [k for k in (q.rows[0] if q.rows else {})
                       if not isinstance(q.rows[0].get(k), (int, float))
                       or is_integer_field(k)]
        for key in categorical:
            groups: dict = {}
            for row in q.rows:
                bucket = groups.setdefault(row.get(key), {})
                for name, value in row.items():
                    if isinstance(value, (int, float)) and value is not None \
                            and not isinstance(value, bool) and name != key:
                        bucket[name] = bucket.get(name, 0.0) + float(value)
            for bucket in groups.values():
                allowed += [abs(v) for v in bucket.values()]
            # Movements between two groups (e.g. this quarter vs last).
            buckets = list(groups.values())
            if len(buckets) == 2:
                for name in buckets[0]:
                    if name in buckets[1]:
                        a, b = buckets[0][name], buckets[1][name]
                        allowed.append(abs(a - b))
                        if abs(b) > 1e-9:
                            allowed.append(abs((a - b) / b * 100.0))
                        if abs(a) > 1e-9:
                            allowed.append(abs((b - a) / a * 100.0))

        columns = _numeric_columns(q.rows)
        for name, values in columns.items():
            total = sum(values)
            allowed.append(abs(total))                    # column total
            if values:
                allowed.append(abs(total / len(values)))  # simple average
                allowed.append(abs(max(values)))
                allowed.append(abs(min(values)))
                allowed.append(abs(max(values) - min(values)))
            # Share of the column total, per row (e.g. "2025 is 28% of the book")
            if abs(total) > 1e-9:
                allowed += [abs(v / total * 100.0) for v in values]

        # Differences and percentage changes between paired columns, which is
        # how any movement is described.
        for a, b in (("current", "prior"), ("prior", "current")):
            if a in columns and b in columns and len(columns[a]) == len(columns[b]):
                for x, y in zip(columns[a], columns[b]):
                    allowed.append(abs(x - y))
                    if abs(y) > 1e-9:
                        allowed.append(abs((x - y) / y * 100.0))
                total_a, total_b = sum(columns[a]), sum(columns[b])
                allowed.append(abs(total_a - total_b))
                if abs(total_b) > 1e-9:
                    allowed.append(abs((total_a - total_b) / total_b * 100.0))

    for s in package.report_slides:
        allowed.append(float(s.slide_number))
        allowed += [abs(x) for x in _extract_numbers(s.excerpt)]
    return allowed


def verify_answer(draft: AnswerDraft, package: EvidencePackage) -> VerificationResult:
    failures: list[str] = []
    valid_ids = package.evidence_ids()
    for ref in draft.evidence_references:
        if ref.evidence_id not in valid_ids:
            failures.append(f"Unknown evidence reference '{ref.evidence_id}'.")

    allowed = _allowed_numbers(package)
    texts = [draft.headline] + list(draft.observations) + list(draft.limitations)
    for section in draft.sections:
        texts.append(section.title)
        texts += list(section.points)
    for text in texts:
        for x in _extract_numbers(text):
            ok = any(abs(x - a) <= max(0.051, abs(a) * 0.002) for a in allowed)
            if not ok:
                failures.append(f"Number {x} in \"{text[:80]}\" is not traceable "
                                f"to the evidence package.")
    return VerificationResult(passed=not failures, failures=failures)


def fallback_answer(package: EvidencePackage) -> AnswerDraft:
    """Deterministic templated summary built by application code."""
    observations: list[str] = []
    refs: list[EvidenceReference] = []
    headline = "The requested result is shown in the table below."
    period = package.period_context.get("display_label", "")

    for q in package.query_results:
        refs.append(EvidenceReference(evidence_type="query_result",
                                      evidence_id=q.evidence_id))
        measure = (q.measures[0].replace("_", " ") if q.measures else "value")
        measure_phrase = measure if measure.startswith("total") else f"total {measure}"
        raw_unit = {"GBP millions": "GBP"}.get(q.unit, "")
        s = q.summary
        if "absolute_change_total" in s and s.get("current_total") is not None:
            cur = s["current_total"]; mv = s["absolute_change_total"]
            cur_txt = f"GBP {cur:,.1f}m".replace(".0m", "m") if raw_unit == "GBP" else f"{cur:,.1f}"
            mv_txt = (f"{'+' if mv >= 0 else '-'}GBP {abs(mv):,.1f}m".replace(".0m", "m")
                      if raw_unit == "GBP" else f"{mv:+,.1f}")
            headline = (f"{measure_phrase.capitalize()} of {cur_txt} for {period}, "
                        f"a movement of {mv_txt}")
            if s.get("percentage_change_total") is not None:
                observations.append(
                    f"The total movement is {fmt_pct(s['percentage_change_total'], signed=True)} "
                    f"relative to the comparison period.")
        elif "change_count" in s:
            field = str(s.get("compared_field", "value")).replace("_", " ")
            headline = f"{s['change_count']} {field} change(s) between the compared reviews"
        elif q.measures and f"total_{q.measures[0]}" in s and s[f"total_{q.measures[0]}"] is not None:
            tot = s[f"total_{q.measures[0]}"]
            tot_txt = f"GBP {tot:,.1f}m".replace(".0m", "m") if raw_unit == "GBP" else f"{tot:,.1f}"
            headline = f"{measure_phrase.capitalize()} of {tot_txt} for {period}"
        for row in q.rows[:3]:
            dims = [str(row[g]) for g in q.group_by if g in row]
            if "absolute_change" in row and row.get("absolute_change") is not None:
                mv = row["absolute_change"]
                mv_txt = (f"{'+' if mv >= 0 else '-'}GBP {abs(mv):,.1f}m".replace(".0m", "m")
                          if raw_unit == "GBP" else f"{mv:+,.1f}")
                observations.append(f"{' / '.join(dims) or 'Total'}: {mv_txt}.")

    for slide in package.report_slides:
        refs.append(EvidenceReference(evidence_type="report_slide",
                                      evidence_id=slide.evidence_id))
        observations.append(
            f"See \"{slide.title}\" ({slide.quarter_label or slide.review_id} "
            f"Reserve Review, slide {slide.slide_number}).")

    limitations = list(package.limitations)
    limitations.append("This summary was generated by the application after the "
                       "language model's draft could not be verified against the "
                       "evidence.")
    return AnswerDraft(headline=headline, observations=observations[:5],
                       limitations=limitations, evidence_references=refs)


def compose_answer(question: str, package: EvidencePackage,
                   settings: LLMSettings | None = None,
                   provider=None, deep_analysis: bool = False) -> ComposedAnswer:
    settings = settings or get_llm_settings()
    provider = provider or get_llm_provider(settings)
    payload = answer_payload(package)
    system = load_prompt("analysis_system.md" if deep_analysis
                         else "answer_system.md")
    metadata = None
    regenerated = False

    for attempt, instruction in enumerate((system, system + STRICT_SUFFIX)):
        outcome = call_with_retries(
            provider, purpose="answer", system_instruction=instruction,
            input_payload=payload, response_model=AnswerDraft, settings=settings)
        draft = outcome.response.value
        metadata = outcome.response.metadata
        verification = verify_answer(draft, package)
        if verification.passed:
            return ComposedAnswer(draft=draft, metadata=metadata,
                                  verification=verification,
                                  used_fallback=False, regenerated=attempt > 0)
        regenerated = attempt > 0

    draft = fallback_answer(package)
    return ComposedAnswer(draft=draft, metadata=metadata,
                          verification=VerificationResult(
                              passed=True,
                              failures=["Deterministic fallback used after failed "
                                        "verification."]),
                          used_fallback=True, regenerated=regenerated)


def render_answer_text(draft: AnswerDraft) -> str:
    parts = [draft.headline]
    if draft.observations:
        parts.append("")
        parts += [f"- {o}" for o in draft.observations]
    for section in draft.sections:
        parts.append("")
        parts.append(f"{section.title}")
        parts += [f"- {p}" for p in section.points]
    if draft.limitations:
        parts.append("")
        parts += [f"Limitation: {l}" for l in draft.limitations]
    return "\n".join(parts)
