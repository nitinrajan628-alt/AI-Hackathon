"""One-variable provider switching and per-provider configuration."""
import pytest

from models.ai_contracts import LLMNotConfiguredError
from services.llm_provider import get_llm_provider
from services.settings import LLMSettings


def test_gemini_selected_by_default_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = LLMSettings()
    assert s.provider == "gemini"
    assert s.key_env_var == "GEMINI_API_KEY"
    assert s.model.startswith("gemini")


def test_openai_selected_by_same_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    s = LLMSettings()
    assert s.provider == "openai"
    assert s.key_env_var == "OPENAI_API_KEY"
    assert s.model.startswith("gpt")


def test_switching_changes_only_configuration(monkeypatch):
    """The switch must not require different call sites: both providers
    expose the same generate_structured signature."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    gemini = get_llm_provider(LLMSettings())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    openai = get_llm_provider(LLMSettings())

    import inspect
    sig_g = inspect.signature(gemini.generate_structured)
    sig_o = inspect.signature(openai.generate_structured)
    assert list(sig_g.parameters) == list(sig_o.parameters)
    assert set(sig_g.parameters) == {"purpose", "system_instruction",
                                     "input_payload", "response_model"}


def test_model_override_precedence(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    assert LLMSettings().model == "gpt-4.1"
    monkeypatch.setenv("LLM_MODEL", "gpt-5")
    assert LLMSettings().model == "gpt-5"      # LLM_MODEL wins


def test_missing_key_reports_the_right_variable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(LLMNotConfiguredError) as err:
        get_llm_provider(LLMSettings())
    assert "OPENAI_API_KEY" in str(err.value)


def test_unknown_provider_lists_valid_options(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "notaprovider")
    with pytest.raises(LLMNotConfiguredError) as err:
        get_llm_provider(LLMSettings())
    message = str(err.value)
    assert "gemini" in message and "openai" in message and "fake" in message


def test_openai_billing_exhaustion_is_not_retried(monkeypatch):
    """A credit/quota exhaustion is permanent: it must surface as a
    configuration error, not a transient rate limit that gets retried."""
    from models.ai_contracts import LLMAuthenticationError, PlanningResponse
    from services.openai_provider import OpenAIProvider

    class FakeQuotaError(Exception):
        status_code = 429
        body = {"error": {"code": "insufficient_quota"}}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = OpenAIProvider(model="gpt-4.1-mini")

    def boom(**kwargs):
        raise FakeQuotaError("no credits")

    monkeypatch.setattr(provider.client.responses, "parse", boom)
    with pytest.raises(LLMAuthenticationError) as err:
        provider.generate_structured(purpose="planning", system_instruction="x",
                                     input_payload={}, response_model=PlanningResponse)
    assert "credit" in str(err.value).lower()


def test_openai_transient_rate_limit_is_retryable(monkeypatch):
    from models.ai_contracts import LLMRateLimitError, PlanningResponse
    from services.openai_provider import OpenAIProvider

    class FakeRateLimit(Exception):
        status_code = 429
        body = {"error": {"code": "rate_limit_exceeded"}}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider = OpenAIProvider(model="gpt-4.1-mini")
    monkeypatch.setattr(provider.client.responses, "parse",
                        lambda **kw: (_ for _ in ()).throw(FakeRateLimit("slow down")))
    with pytest.raises(LLMRateLimitError):
        provider.generate_structured(purpose="planning", system_instruction="x",
                                     input_payload={}, response_model=PlanningResponse)
