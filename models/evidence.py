"""Internal response objects (Detailed Build Specification section 13.3)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from models.query_plan import QueryPlan


class PeriodResolution(BaseModel):
    primary_review_id: str
    comparison_review_ids: list[str] = Field(default_factory=list)
    interpretation_label: str = ""
    warnings: list[str] = Field(default_factory=list)


class SlideEvidence(BaseModel):
    evidence_id: str = ""
    slide_id: int
    review_id: str
    quarter_label: str = ""
    slide_number: int
    title: str
    section: str
    excerpt: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        label = self.quarter_label or self.review_id.replace("-", " ")
        return f"{label} Reserve Review - slide {self.slide_number}, {self.title}"


class ValidatedPlan(BaseModel):
    plan: QueryPlan
    dataset: str
    table: str
    measure_columns: dict[str, str] = Field(default_factory=dict)
    group_by_columns: dict[str, str] = Field(default_factory=dict)
    attribute_columns: dict[str, str] = Field(default_factory=dict)
    inferred_defaults: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompiledQuery(BaseModel):
    sql: str
    parameters: list[Any] = Field(default_factory=list)
    source_tables: list[str] = Field(default_factory=list)
    selected_fields: list[str] = Field(default_factory=list)
    measure_metadata: dict[str, dict] = Field(default_factory=dict)


class QueryResultEvidence(BaseModel):
    """Bounded, model-facing view of one executed query result."""
    evidence_id: str
    title: str = ""          # what this diagnostic is, for analysis batteries
    dataset: str
    operation: str
    measures: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    period_labels: list[str] = Field(default_factory=list)
    unit: str = ""
    filters: list[dict] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    truncated: bool = False
    total_row_count: int = 0


class EvidencePackage(BaseModel):
    question: str
    period_context: dict = Field(default_factory=dict)
    report_slides: list[SlideEvidence] = Field(default_factory=list)
    query_results: list[QueryResultEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def evidence_ids(self) -> set[str]:
        ids = {s.evidence_id for s in self.report_slides}
        ids |= {q.evidence_id for q in self.query_results}
        return ids


class VerificationResult(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)


class ChartSpec(BaseModel):
    chart_type: Literal[
        "bar", "grouped_bar", "diverging_bar", "line", "stacked_bar"
    ]
    title: str = ""
    x_field: str
    x_label: str = ""
    y_fields: list[str]
    y_label: str = ""
    unit: str = ""
    orientation: Literal["v", "h"] = "v"
    data: list[dict] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")
