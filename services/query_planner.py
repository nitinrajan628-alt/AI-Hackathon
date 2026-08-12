"""AI Call 1 - structured planning (Detailed Build Specification section 9.4).

Builds the bounded planning payload (catalogue/context metadata, never data
rows), calls the configured provider through the neutral boundary and
returns a validated PlanningResponse.
"""
from __future__ import annotations

from dataclasses import dataclass

from models.ai_contracts import ModelCallMetadata, PlanningResponse
from services.catalogue import get_catalogue
from services.llm_provider import call_with_retries, get_llm_provider
from services.review_service import review_ids
from services.settings import LLMSettings, get_llm_settings, load_prompt, load_yaml

SCOPE_POLICY = {
    "allowed": [
        "report retrieval", "filtering", "aggregation", "comparison",
        "ranking", "approved assumption change listing", "trend",
        "meta question",
    ],
    "prohibited": [
        "reserve recalculation", "reserve adequacy opinion",
        "actuarial recommendation", "assumption selection",
        "forecasting", "arbitrary SQL", "arbitrary Python",
    ],
}


def build_planning_payload(question: str, conversation_context: dict) -> dict:
    cat = get_catalogue()
    return {
        "question": question,
        "conversation_context": conversation_context,
        "available_reviews": review_ids(),
        "catalogue": cat.condensed(),
        "scope_policy": SCOPE_POLICY,
    }


@dataclass
class PlanningResult:
    response: PlanningResponse
    metadata: ModelCallMetadata
    retry_count: int


def plan_request(question: str, conversation_context: dict,
                 settings: LLMSettings | None = None,
                 provider=None) -> PlanningResult:
    settings = settings or get_llm_settings()
    provider = provider or get_llm_provider(settings)
    payload = build_planning_payload(question, conversation_context)
    outcome = call_with_retries(
        provider,
        purpose="planning",
        system_instruction=load_prompt("planning_system.md"),
        input_payload=payload,
        response_model=PlanningResponse,
        settings=settings,
    )
    return PlanningResult(response=outcome.response.value,
                          metadata=outcome.response.metadata,
                          retry_count=outcome.retry_count)


def guardrail_message(category: str | None) -> tuple[str, str]:
    """Return (message, alternative) for a guardrail category."""
    guardrails = load_yaml("guardrails.yaml")
    cats = guardrails.get("categories", {})
    if category and category in cats:
        c = cats[category]
        return c["message"].strip(), c.get("alternative", "").strip()
    return (
        "That request requires actuarial judgement or capabilities outside "
        "the scope of this application. I can show stored report content, "
        "data, assumptions and results instead.",
        "Ask about the stored reviews, movements, assumptions or report commentary.",
    )
