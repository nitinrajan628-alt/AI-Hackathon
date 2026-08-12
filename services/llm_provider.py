"""Provider-neutral LLM boundary: provider registry, factory and the common
retry/error policy (Detailed Build Specification sections 9.2, 9.9, 9.10).

Only provider adapter modules may import vendor SDKs. Everything else in the
application depends on the LLMProvider protocol and Pydantic contracts.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Type, TypeVar

from pydantic import BaseModel

from models.ai_contracts import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredModelResponse,
)
from services.settings import LLMSettings

T = TypeVar("T", bound=BaseModel)

_REGISTRY: dict[str, Callable[[LLMSettings], object]] = {}


def register_provider(name: str, factory: Callable[[LLMSettings], object]) -> None:
    _REGISTRY[name.lower()] = factory


def get_llm_provider(settings: LLMSettings):
    """Instantiate the configured provider adapter.

    Switching providers is a single configuration change (LLM_PROVIDER);
    no planning, validation, execution, retrieval or UI code is aware of
    which adapter is in use.
    """
    name = (settings.provider or "").lower()

    if name == "fake":
        from services.fake_provider import FakeProvider
        return FakeProvider()

    if name in ("gemini", "openai", "chatgpt"):
        if not settings.key_present():
            raise LLMNotConfiguredError(
                f"{settings.key_env_var} is not configured. Set it in your "
                f".env file, or switch LLM_PROVIDER to another provider.")
        if not settings.model:
            raise LLMNotConfiguredError(
                f"No model is configured for provider '{name}'. Set LLM_MODEL "
                f"or a default in config/llm.yaml.")
        if name == "gemini":
            from services.gemini_provider import GeminiProvider  # lazy vendor import
            return GeminiProvider(
                model=settings.model,
                api_version=settings.api_version,
                timeout_seconds=settings.timeout_seconds,
                thinking_level=settings.thinking_level or "low")
        from services.openai_provider import OpenAIProvider  # lazy vendor import
        return OpenAIProvider(
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            reasoning_effort=settings.reasoning_effort)

    if name in _REGISTRY:
        return _REGISTRY[name](settings)
    known = "gemini, openai, fake"
    raise LLMNotConfiguredError(
        f"Unknown LLM provider '{settings.provider}'. Set LLM_PROVIDER to one "
        f"of: {known}.")


class RetryOutcome:
    def __init__(self, response: StructuredModelResponse, retry_count: int):
        self.response = response
        self.retry_count = retry_count


CORRECTION_INSTRUCTION = (
    "\n\nYour previous response was not valid JSON for the required schema. "
    "Return only a single JSON object that conforms exactly to the schema. "
    "No markdown, no commentary, no extra fields.")


def call_with_retries(
    provider,
    *,
    purpose: str,
    system_instruction: str,
    input_payload: dict,
    response_model: Type[T],
    settings: LLMSettings,
) -> RetryOutcome:
    """Apply the common failure policy: no retry on authentication errors,
    exponential backoff for transient failures, one corrective retry for
    invalid structured output."""
    max_retries = max(0, settings.max_retries)
    attempt = 0
    invalid_retried = False
    instruction = system_instruction
    last_error: Exception | None = None

    while True:
        try:
            response = provider.generate_structured(
                purpose=purpose,
                system_instruction=instruction,
                input_payload=input_payload,
                response_model=response_model,
            )
            return RetryOutcome(response, attempt)
        except LLMAuthenticationError:
            raise
        except LLMConnectionError:
            raise
        except LLMInvalidResponseError as exc:
            last_error = exc
            if invalid_retried:
                raise
            invalid_retried = True
            instruction = system_instruction + CORRECTION_INSTRUCTION
            attempt += 1
        except LLMTimeoutError as exc:
            last_error = exc
            if attempt >= 1:  # one timeout retry within budget
                raise
            attempt += 1
        except LLMRateLimitError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            # Provider quotas are typically per-minute; back off long enough
            # for the window to roll.
            backoff = (5.0 * (attempt + 1)) + random.uniform(0, 1.5)
            time.sleep(backoff)
            attempt += 1
        except LLMProviderError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            backoff = (0.6 * (2 ** attempt)) + random.uniform(0, 0.4)
            time.sleep(backoff)
            attempt += 1
