"""LLM-powered title generation for chat sessions and artifacts."""
from __future__ import annotations

from pydantic import BaseModel

from services.llm_provider import get_llm_provider
from services.settings import get_llm_settings


class TitleResponse(BaseModel):
    title: str


_SYSTEM_PROMPT = (
    "Generate a short, descriptive title (3-8 words) for a conversation or "
    "saved result. Return JSON with a single 'title' field. The title should "
    "capture the core topic without filler words like 'Analysis of' or "
    "'Question about'. Be specific to the actuarial/reserving domain where "
    "relevant."
)


def generate_chat_title(question: str, headline: str) -> str:
    try:
        settings = get_llm_settings()
        provider = get_llm_provider(settings)
        response = provider.generate_structured(
            purpose="title_generation",
            system_instruction=_SYSTEM_PROMPT,
            input_payload={"question": question, "answer_headline": headline},
            response_model=TitleResponse,
        )
        return response.value.title[:60]
    except Exception:
        return question[:50]


def generate_artifact_title(question: str, headline: str) -> str:
    try:
        settings = get_llm_settings()
        provider = get_llm_provider(settings)
        response = provider.generate_structured(
            purpose="artifact_title_generation",
            system_instruction=_SYSTEM_PROMPT,
            input_payload={
                "question": question,
                "saved_result_headline": headline,
                "context": "This is a saved artifact from an actuarial reserve review tool.",
            },
            response_model=TitleResponse,
        )
        return response.value.title[:60]
    except Exception:
        return headline[:50] if headline else question[:50]
