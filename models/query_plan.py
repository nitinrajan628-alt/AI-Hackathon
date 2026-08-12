"""Typed query-plan contract (Detailed Build Specification section 7.2).

QueryPlan is the canonical contract for one structured data task. It never
contains raw SQL or Python; the policy validator performs semantic checks
against the catalogue before compilation.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scalar = str | int | float | bool


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    operator: Literal["eq", "in", "between", "gte", "lte"]
    value: Scalar | list[Scalar]


class SortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    direction: Literal["asc", "desc"]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "STRUCTURED_QUERY", "PERIOD_COMPARISON", "TREND",
        "ASSUMPTION_CHANGES",
    ]
    primary_dataset: Literal[
        "claims_latest", "claims_triangle", "premium", "assumptions", "results"
    ]
    review_ids: list[str] = Field(min_length=1, max_length=8)
    measures: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    operation: Literal[
        "aggregate", "compare", "trend", "rank", "share_of_total",
        "contribution_to_movement", "list_changes", "pivot",
    ]
    sort: list[SortSpec] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=200)
    chart: Literal[
        "none", "auto", "bar", "grouped_bar", "diverging_bar",
        "line", "stacked_bar",
    ] = "auto"
