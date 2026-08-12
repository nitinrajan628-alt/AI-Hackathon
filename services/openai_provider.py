"""OpenAI (ChatGPT) adapter implementing the same `LLMProvider` protocol as
the Gemini adapter (Detailed Build Specification sections 9.2, 9.9).

The only module permitted to import the OpenAI SDK. Uses the Responses API
with native JSON-schema structured output (`text_format=<PydanticModel>`),
so the application receives the identical validated contracts regardless of
which provider is configured. The key is read server-side from
OPENAI_API_KEY and is never stored, logged or echoed.
"""
from __future__ import annotations

import json
import time
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from models.ai_contracts import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    ModelCallMetadata,
    StructuredModelResponse,
)

T = TypeVar("T", bound=BaseModel)

# Billing/quota conditions that will not clear by retrying.
_PERMANENT_QUOTA_CODES = {"insufficient_quota", "credit_balance_exhausted",
                          "billing_hard_limit_reached"}


def _error_code(exc: Exception) -> str:
    """Best-effort extraction of the provider's machine-readable error code."""
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        for key in ("code", "type"):
            value = err.get(key)
            if isinstance(value, str):
                return value
    return ""


class OpenAIProvider:
    def __init__(self, model: str, timeout_seconds: int = 30,
                 reasoning_effort: str | None = None):
        from openai import OpenAI  # vendor import isolated here
        self.model = model
        self.reasoning_effort = reasoning_effort
        # max_retries=0: the application owns the retry policy so behaviour is
        # identical across providers.
        self.client = OpenAI(timeout=timeout_seconds, max_retries=0)

    def generate_structured(
        self,
        *,
        purpose: str,
        system_instruction: str,
        input_payload: dict,
        response_model: Type[T],
    ) -> StructuredModelResponse[T]:
        started = time.perf_counter()
        request: dict = {
            "model": self.model,
            "instructions": system_instruction,
            "input": json.dumps(input_payload, separators=(",", ":")),
            "text_format": response_model,
            "store": False,
        }
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}

        try:
            response = self.client.responses.parse(**request)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            name = type(exc).__name__.lower()
            code = _error_code(exc)
            exc_str = str(exc).lower()
            if ("ssl" in exc_str or "certificate" in exc_str
                    or "connect" in name or "connection" in name
                    or "apiconnectionerror" in name):
                raise LLMConnectionError(
                    "Could not reach the OpenAI API. This is typically caused "
                    "by a corporate proxy or firewall blocking "
                    "api.openai.com. Contact IT or try a direct "
                    "connection.") from exc
            if code in _PERMANENT_QUOTA_CODES:
                raise LLMAuthenticationError(
                    "The OpenAI account has no remaining credit or quota. Add "
                    "credits, or set LLM_PROVIDER=gemini in your .env file."
                ) from exc
            if status in (401, 403) or "authentication" in name or "permission" in name:
                raise LLMAuthenticationError(
                    "OpenAI rejected the configured credentials. Check "
                    "OPENAI_API_KEY.") from exc
            if status == 429 or "ratelimit" in name:
                raise LLMRateLimitError(f"OpenAI rate limit ({code or 429}).") from exc
            if status in (408, 504) or "timeout" in name:
                raise LLMTimeoutError("OpenAI call timed out.") from exc
            raise LLMProviderError(
                f"OpenAI API error ({status or type(exc).__name__})") from exc

        value = getattr(response, "output_parsed", None)
        if value is None:
            # Refusal or unparsable output: surface as an invalid-response so
            # the common retry policy applies one corrective attempt.
            text = getattr(response, "output_text", "") or ""
            try:
                value = response_model.model_validate_json(text)
            except (ValidationError, ValueError) as exc:
                raise LLMInvalidResponseError(
                    f"OpenAI returned output that failed "
                    f"{response_model.__name__} validation.") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        metadata = ModelCallMetadata(
            provider="openai",
            model=self.model,
            provider_request_id=getattr(response, "id", None) or None,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
            latency_ms=latency_ms,
        )
        return StructuredModelResponse(value=value, metadata=metadata)
