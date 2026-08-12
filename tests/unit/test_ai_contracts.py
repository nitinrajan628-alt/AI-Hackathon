"""AI contract validation: extra-field rejection, mocked bad model output,
evidence verification and provider contract (16.1, 9.13)."""
import os

import pytest
from pydantic import ValidationError

from models.ai_contracts import AnswerDraft, PlanningResponse
from models.evidence import EvidencePackage, QueryResultEvidence
from models.query_plan import QueryPlan
from services.answer_service import fallback_answer, verify_answer
from services.fake_provider import FakeProvider


def test_planning_response_rejects_extra_fields():
    with pytest.raises(ValidationError):
        PlanningResponse(intent="REPORT_QA", policy={"status": "ALLOW"},
                         surprise_field="x")


def test_answer_draft_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AnswerDraft(headline="h", html="<b>nope</b>")


def test_query_plan_rejects_raw_sql_dataset():
    with pytest.raises(ValidationError):
        QueryPlan(intent="STRUCTURED_QUERY",
                  primary_dataset="SELECT * FROM result_snapshot",
                  review_ids=["2026-Q2"], operation="aggregate")


def test_unknown_field_from_mocked_model_rejected_before_compilation():
    from services.catalogue import get_catalogue
    from services.policy import PlanValidationError, validate_plan
    from services.review_service import review_ids
    plan = QueryPlan(intent="STRUCTURED_QUERY", primary_dataset="results",
                     review_ids=["2026-Q2"],
                     measures=["total_reserve; DROP TABLE result_snapshot"],
                     operation="aggregate")
    with pytest.raises(PlanValidationError):
        validate_plan(plan, get_catalogue(), review_ids())


def _package(rows=None, summary=None) -> EvidencePackage:
    return EvidencePackage(
        question="q",
        period_context={"display_label": "2026 Q2 compared with 2026 Q1"},
        query_results=[QueryResultEvidence(
            evidence_id="qr_1", dataset="results", operation="compare",
            measures=["total_reserve"], group_by=["finance_class"],
            periods=["2026-Q2", "2026-Q1"],
            period_labels=["2026 Q2", "2026 Q1"], unit="GBP millions",
            rows=rows or [{"finance_class": "Commercial Lines",
                           "current": 293.0, "prior": 279.0,
                           "absolute_change": 14.0, "percentage_change": 5.0}],
            summary=summary or {"current_total": 640.0, "prior_total": 614.0,
                                "absolute_change_total": 26.0},
        )])


def test_fabricated_evidence_id_rejected():
    draft = AnswerDraft(headline="Total reserves are GBP 640m",
                        evidence_references=[{"evidence_type": "query_result",
                                              "evidence_id": "qr_999"}])
    result = verify_answer(draft, _package())
    assert not result.passed
    assert any("qr_999" in f for f in result.failures)


def test_invented_number_fails_verification():
    draft = AnswerDraft(headline="Reserves rose GBP 999.9m in the quarter",
                        evidence_references=[{"evidence_type": "query_result",
                                              "evidence_id": "qr_1"}])
    result = verify_answer(draft, _package())
    assert not result.passed


def test_evidence_grounded_numbers_pass():
    draft = AnswerDraft(
        headline="Total reserves of GBP 640m at 2026 Q2, up GBP 26m",
        observations=["Commercial Lines rose GBP 14m to GBP 293m (5.0%)."],
        evidence_references=[{"evidence_type": "query_result",
                              "evidence_id": "qr_1"}])
    result = verify_answer(draft, _package())
    assert result.passed, result.failures


def test_fallback_answer_is_deterministic_and_grounded():
    package = _package()
    draft = fallback_answer(package)
    assert "640" in draft.headline and "26" in draft.headline
    verification = verify_answer(draft, package)
    assert verification.passed, verification.failures


def test_provider_contract_and_no_credential_leakage(fake_settings):
    provider = FakeProvider()
    response = provider.generate_structured(
        purpose="planning", system_instruction="x",
        input_payload={"question": "How much did reserves change from last quarter?",
                       "conversation_context": {"current_review_id": "2026-Q2"},
                       "available_reviews": ["2026-Q1", "2026-Q2"]},
        response_model=PlanningResponse)
    assert response.metadata.provider == "fake"
    assert response.metadata.latency_ms >= 0
    key = os.environ.get("GEMINI_API_KEY", "")
    dump = response.model_dump_json()
    if key:
        assert key not in dump


def test_switching_provider_is_configuration_only(monkeypatch):
    """Acceptance 9.13 #10: swapping Gemini for the fake provider requires
    only configuration, not code changes."""
    from services.llm_provider import get_llm_provider
    from services.settings import LLMSettings
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    provider = get_llm_provider(LLMSettings())
    assert isinstance(provider, FakeProvider)
