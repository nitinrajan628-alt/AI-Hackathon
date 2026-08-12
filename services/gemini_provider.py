"""Google Gemini adapter (Detailed Build Specification section 9.8).

The only module permitted to import the Google Gen AI SDK. Implements the
LLMProvider protocol using the Gemini Interactions API with JSON-schema
structured output. Authentication uses GEMINI_API_KEY server-side via the
SDK's environment lookup; the key is never stored, logged or echoed.
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


class GeminiProvider:
    def __init__(self, model: str, api_version: str = "v1",
                 timeout_seconds: int = 30, thinking_level: str = "low"):
        from google import genai  # vendor import isolated here
        self.model = model
        self.thinking_level = thinking_level
        self.client = genai.Client(http_options={
            "api_version": api_version,
            "timeout": timeout_seconds * 1000,
        })

    def generate_structured(
        self,
        *,
        purpose: str,
        system_instruction: str,
        input_payload: dict,
        response_model: Type[T],
    ) -> StructuredModelResponse[T]:
        started = time.perf_counter()
        try:
            interaction = self.client.interactions.create(
                model=self.model,
                system_instruction=system_instruction,
                input=json.dumps(input_payload, separators=(",", ":")),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_model.model_json_schema(),
                },
                generation_config={"thinking_level": self.thinking_level},
                store=False,
            )
        except Exception as exc:
            # The SDK raises several exception families (google.genai.errors
            # APIError plus the interactions API's compat errors); classify by
            # status code and class name rather than one base class.
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            name = type(exc).__name__.lower()
            exc_str = str(exc).lower()
            message = f"Gemini API error ({status or type(exc).__name__})"
            if ("ssl" in exc_str or "certificate" in exc_str
                    or "connect" in name or "connection" in name
                    or "connecterror" in name):
                raise LLMConnectionError(
                    "Could not reach the Gemini API. This is typically caused "
                    "by a corporate proxy or firewall blocking "
                    "generativelanguage.googleapis.com. Contact IT or try a "
                    "direct connection.") from exc
            if status in (401, 403) or "authentication" in name or "permission" in name:
                raise LLMAuthenticationError(
                    "Gemini rejected the configured credentials. Check "
                    "GEMINI_API_KEY.") from exc
            if status == 429 or "ratelimit" in name:
                raise LLMRateLimitError(message) from exc
            if status in (408, 504) or "timeout" in name:
                raise LLMTimeoutError("Gemini call timed out.") from exc
            raise LLMProviderError(message) from exc

        text = getattr(interaction, "output_text", None) or ""
        if text.lstrip().startswith("<!") or text.lstrip().startswith("<html"):
            raise LLMConnectionError(
                "The Gemini API returned an HTML page instead of a model "
                "response. A corporate proxy or firewall is likely "
                "intercepting requests to generativelanguage.googleapis.com.")
        try:
            value = response_model.model_validate_json(text)
        except ValidationError as exc:
            raise LLMInvalidResponseError(
                f"Gemini returned JSON that failed {response_model.__name__} "
                f"validation.") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(interaction, "usage", None)
        metadata = ModelCallMetadata(
            provider="gemini",
            model=self.model,
            provider_request_id=getattr(interaction, "id", None) or None,
            input_tokens=getattr(usage, "total_input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "total_output_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
            latency_ms=latency_ms,
        )
        return StructuredModelResponse(value=value, metadata=metadata)
