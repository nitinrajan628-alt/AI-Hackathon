"""AI boundary contracts (Detailed Build Specification sections 9.2-9.6).

These models define everything that crosses the provider-agnostic LLM
boundary: the planning response (AI Call 1), the answer draft (AI Call 2)
and common call metadata. Extra fields are rejected.
"""
from __future__ import annotations

from typing import Generic, Literal, Protocol, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from models.query_plan import FilterSpec, QueryPlan

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

class ModelCallMetadata(BaseModel):
    provider: str
    model: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int


class StructuredModelResponse(BaseModel, Generic[T]):
    value: T
    metadata: ModelCallMetadata


class LLMProviderProtocol(Protocol):
    """Provider-neutral structured-output interface."""

    def generate_structured(
        self,
        *,
        purpose: str,
        system_instruction: str,
        input_payload: dict,
        response_model: Type[T],
    ) -> StructuredModelResponse[T]: ...


# ---------------------------------------------------------------------------
# AI Call 1 - planning response
# ---------------------------------------------------------------------------

class ReportSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_ids: list[str]
    query: str
    limit: int = Field(default=5, ge=1, le=5)


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ALLOW", "BLOCK", "UNSUPPORTED"]
    category: str | None = None
    user_message_key: str | None = None


class ContextUpdates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_review_id: str | None = None
    comparison_review_ids: list[str] = Field(default_factory=list)
    active_filters: list[FilterSpec] = Field(default_factory=list)
    last_group_by: list[str] = Field(default_factory=list)
    last_measure: str | None = None
    last_dataset: str | None = None


class PlanningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "REPORT_QA", "STRUCTURED_QUERY", "PERIOD_COMPARISON", "TREND",
        "ASSUMPTION_CHANGES", "MIXED_REPORT_DATA", "DIAGNOSTIC_REOPEN",
        "OUT_OF_SCOPE", "UNSUPPORTED", "META",
    ]
    report_searches: list[ReportSearchRequest] = Field(default_factory=list)
    query_plans: list[QueryPlan] = Field(default_factory=list)
    policy: PolicyDecision
    context_updates: ContextUpdates = Field(default_factory=ContextUpdates)


# ---------------------------------------------------------------------------
# AI Call 2 - answer draft
# ---------------------------------------------------------------------------

class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_type: Literal["report_slide", "query_result"]
    evidence_id: str


class AnalysisSection(BaseModel):
    """One themed part of a multi-part analysis (deep-dive answers only)."""
    model_config = ConfigDict(extra="forbid")
    title: str
    points: list[str] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    observations: list[str] = Field(default_factory=list)
    # Populated only for deep-dive analyses; ordinary answers leave it empty.
    sections: list[AnalysisSection] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Common provider exceptions (section 9.10)
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base class for provider-boundary errors."""


class LLMAuthenticationError(LLMError):
    pass


class LLMConnectionError(LLMError):
    """Network-level failure: DNS, SSL, proxy block, or unreachable host."""
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMInvalidResponseError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMNotConfiguredError(LLMAuthenticationError):
    """Raised when no API key / provider configuration is present."""
