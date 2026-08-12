"""Application settings: paths, environment and non-secret LLM defaults."""
from __future__ import annotations

import os
from functools import lru_cache

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REVIEW_DB_PATH = os.path.join(DATA_DIR, "reserve_review.db")
DIAGNOSTICS_DB_PATH = os.path.join(DATA_DIR, "diagnostics.db")
PROMPTS_DIR = os.path.join(CONFIG_DIR, "prompts")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(os.path.join(CONFIG_DIR, name), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


class LLMSettings:
    """Resolved provider configuration.

    One variable switches provider: set `LLM_PROVIDER` to `gemini`, `openai`
    or `fake`. The model, key variable and provider-specific options are then
    resolved from config/llm.yaml, so no other setting has to change.

    Precedence for the model: LLM_MODEL (explicit override for any provider)
    -> the provider's own env var (e.g. OPENAI_MODEL) -> the catalogue
    default. The API key itself is read only by the provider adapter via the
    SDK's environment lookup, and is never stored on this object, logged or
    persisted.
    """

    def __init__(self) -> None:
        cfg = load_yaml("llm.yaml")
        defaults = cfg.get("defaults", {})
        self.providers: dict = cfg.get("providers", {})

        self.provider = os.environ.get(
            "LLM_PROVIDER", defaults.get("provider", "gemini")).strip().lower()
        spec = self.providers.get(self.provider, {})
        self.provider_label = spec.get("label", self.provider)
        self.key_env_var = spec.get("key_env_var")

        provider_model_var = spec.get("model_env_var")
        self.model = (
            os.environ.get("LLM_MODEL")
            or (os.environ.get(provider_model_var) if provider_model_var else None)
            or spec.get("model", "")
        )

        self.timeout_seconds = int(os.environ.get("LLM_TIMEOUT_SECONDS",
                                                  defaults.get("timeout_seconds", 30)))
        self.max_retries = int(os.environ.get("LLM_MAX_RETRIES",
                                              defaults.get("max_retries", 2)))
        self.api_version = str(spec.get("api_version", "v1"))
        self.thinking_level = spec.get("thinking_level")
        self.reasoning_effort = spec.get("reasoning_effort")
        self.answer_evidence_row_limit = int(cfg.get("answer_evidence_row_limit", 100))
        self.max_query_plans_per_message = int(cfg.get("max_query_plans_per_message", 3))
        self.log_model_payloads = os.environ.get("LOG_MODEL_PAYLOADS", "false").lower() == "true"

    def key_present(self) -> bool:
        """True when the configured provider's credential is available (or
        the provider needs none)."""
        if not self.key_env_var:
            return True
        return bool(os.environ.get(self.key_env_var, "").strip())

    def gemini_key_present(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def openai_key_present(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def get_llm_settings() -> LLMSettings:
    return LLMSettings()
