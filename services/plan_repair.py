"""Deterministic scope repair applied between planning and validation.

A language model occasionally expresses scope in the wrong field - naming an
accident year in prose but omitting the filter, or putting a dimension in
`sort` when it meant `group_by`. Left alone, the plan still validates and
executes, but it answers a *wider* question than the user asked while the
answer text describes the narrow one. That is the one failure mode the
numerical verifier cannot catch, because every figure returned is genuine.

These repairs are conservative, deterministic and always recorded so they
appear in the provenance panel; they never widen a plan, only restore scope
the user explicitly asked for.
"""
from __future__ import annotations

import re

from models.query_plan import FilterSpec, QueryPlan, SortSpec
from services.catalogue import Catalogue

# Accident-year phrasing that makes a bare four-digit number unambiguous.
_AY_LANGUAGE = re.compile(
    r"\b(accident\s+year|accident\s+years|\bay\b|origin\s+year|underwriting\s+year)\b",
    re.IGNORECASE)
# Quarter tokens ("2026 Q2", "Q3 2025", "2025-Q3") whose year is a review
# period, not an accident year.
_QUARTER = re.compile(r"(\b\d{4}\s*[-\s]?\s*q[1-4]\b)|(\bq[1-4]\s*[-\s]?\s*\d{4}\b)",
                      re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _named_accident_years(question: str, valid: set[int]) -> list[int]:
    """Four-digit years the user explicitly framed as accident years."""
    if not _AY_LANGUAGE.search(question):
        return []
    masked = _QUARTER.sub(" ", question)          # drop review-period tokens
    years = {int(m.group(0)) for m in _YEAR.finditer(masked)}
    return sorted(y for y in years if y in valid)


# "by region", "split by loss type", "broken down by finance class and region"
_BY_PHRASE = re.compile(
    r"\b(?:split\s+by|broken\s+down\s+by|grouped\s+by|by|per|across)\s+"
    r"(?P<tail>[a-z][a-z ,&]{2,60})", re.IGNORECASE)
_CHUNK_SPLIT = re.compile(r"\s+and\s+|\s*,\s*|\s*&\s*", re.IGNORECASE)


def _requested_groupings(question: str, dataset: str,
                         cat: Catalogue) -> list[str]:
    """Dimensions the question explicitly asked to group by.

    Handles multi-word names ("finance class") and lists ("by region and
    loss type") by resolving the longest matching prefix of each chunk.
    """
    dims = set(cat.dimensions(dataset)) | set(cat.attributes(dataset))
    found: list[str] = []
    for match in _BY_PHRASE.finditer(question):
        for chunk in _CHUNK_SPLIT.split(match.group("tail")):
            words = chunk.strip().lower().split()
            if not words:
                continue
            # Longest prefix first, so "finance class" beats "finance".
            for size in range(min(len(words), 3), 0, -1):
                resolved = cat.resolve_dimension(" ".join(words[:size]))
                if resolved and resolved in dims and resolved != "review_id":
                    if resolved not in found:
                        found.append(resolved)
                    break
    return found


# Values whose names are ordinary English words and so cannot be treated as a
# filter on sight ("large movements", "commercial terms", "property damage").
_AMBIGUOUS_VALUES = {"Large", "Cat", "Commercial", "Specialty", "Retail",
                     "Property", "International"}


def _named_dimension_values(question: str, dataset: str,
                            cat: Catalogue) -> list[tuple[str, str]]:
    """Canonical dimension members stated verbatim in the question.

    Only unambiguous members are returned: values that double as ordinary
    English words would produce false filters, so they are left to the model.
    """
    text = (question or "").lower()
    dims = set(cat.dimensions(dataset))
    found: list[tuple[str, str]] = []
    for dim, values in cat.dimension_values.items():
        if dim not in dims:
            continue
        for value in values:
            if value in _AMBIGUOUS_VALUES:
                continue
            if re.search(rf"\b{re.escape(value.lower())}\b", text):
                found.append((dim, value))
                break            # one value per dimension
    return found


def repair_plan_scope(question: str, plan: QueryPlan,
                      cat: Catalogue) -> tuple[QueryPlan, list[str]]:
    """Return a scope-corrected copy of the plan plus human-readable notes."""
    notes: list[str] = []
    dataset = plan.primary_dataset
    dims = set(cat.dimensions(dataset)) | set(cat.attributes(dataset))
    filtered_fields = {cat.resolve_dimension(f.field) or f.field for f in plan.filters}
    grouped_fields = {cat.resolve_dimension(g) or g for g in plan.group_by}
    filters = list(plan.filters)
    group_by = list(plan.group_by)

    # 1. An accident year named in the question must scope the query.
    if "accident_year" in dims and "accident_year" not in filtered_fields \
            and "accident_year" not in grouped_fields:
        valid_years = _valid_accident_years(cat)
        named = _named_accident_years(question, valid_years)
        if named:
            if len(named) == 1:
                filters.append(FilterSpec(field="accident_year", operator="eq",
                                          value=named[0]))
                notes.append(f"Applied the accident year {named[0]} named in the "
                             f"question as a filter.")
            else:
                filters.append(FilterSpec(field="accident_year", operator="in",
                                          value=named))
                notes.append("Applied the accident years "
                             f"{', '.join(str(y) for y in named)} named in the "
                             f"question as a filter.")
            filtered_fields.add("accident_year")

    # 2. A canonical dimension member named in the question scopes the query.
    #    "Analyse Casualty ..." must not return the whole portfolio.
    for dim, value in _named_dimension_values(question, dataset, cat):
        if dim in filtered_fields or dim in grouped_fields:
            continue
        filters.append(FilterSpec(field=dim, operator="eq", value=value))
        filtered_fields.add(dim)
        notes.append(f"Applied {cat.dimension_label(dataset, dim)} = {value} "
                     f"named in the question as a filter.")

    # 3. "by <dimension>" / "split by <dimension>" names the grouping
    #    explicitly. If the plan came back with no grouping at all, restore it.
    if not group_by:
        for field in _requested_groupings(question, dataset, cat):
            if field not in grouped_fields and field not in filtered_fields:
                group_by.append(field)
                grouped_fields.add(field)
                notes.append(f"Grouped by "
                             f"{cat.dimension_label(dataset, field)} because the "
                             f"question asked for it explicitly.")

    # 4. A dimension the plan only sorts by was almost certainly meant as the
    #    grouping: an aggregate with no grouping has a single row to sort.
    if not group_by:
        for s in plan.sort:
            field = cat.resolve_dimension(s.field) or s.field
            if (field in dims and field not in grouped_fields
                    and field not in filtered_fields
                    and field not in plan.attributes
                    and field != "review_id"):
                group_by.append(field)
                grouped_fields.add(field)
                notes.append(
                    f"Grouped by {cat.dimension_label(dataset, field)} because the "
                    f"plan ordered by it without grouping.")

    if not notes:
        return plan, []
    repaired = plan.model_copy(update={
        "filters": filters,
        "group_by": group_by,
        "sort": [SortSpec(**s.model_dump()) for s in plan.sort],
    })
    return repaired, notes


def _valid_accident_years(cat: Catalogue) -> set[int]:
    from services.review_service import list_reviews
    years = [int(r["review_id"][:4]) for r in list_reviews()]
    first = 2017
    return set(range(first, max(years) + 1)) if years else set()
