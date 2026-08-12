"""Acceptance demonstration script (16.3), executed end to end with the
deterministic fake provider. Step 1 opens with 2026 Q2 selected by default."""
import pytest

from services import audit_service
from services.context_service import ConversationContext
from services.orchestrator import handle_question, rerun_diagnostic
from services.review_service import default_review_id


@pytest.fixture(scope="module")
def flow(request):
    import uuid
    ctx = ConversationContext(current_review_id=default_review_id())
    sid = str(uuid.uuid4())
    from services.settings import LLMSettings
    import os
    os.environ["LLM_PROVIDER"] = "fake"
    return {"ctx": ctx, "sid": sid, "settings": LLMSettings(), "answers": {}}


def _ask(flow, question):
    r = handle_question(question, flow["sid"], flow["ctx"], settings=flow["settings"])
    flow["answers"][question] = r
    return r


def test_step0_default_review(flow):
    assert flow["ctx"].current_review_id == "2026-Q2"


def test_step1_key_messages(flow):
    r = _ask(flow, "What are the key messages from this quarter's reserve review?")
    assert r.status == "SUCCESS" and r.slides


def test_step2_reserve_change(flow):
    r = _ask(flow, "How much did reserves change from last quarter?")
    s = r.query_outputs[0].engine_result.shaped.summary
    assert s["absolute_change_total"] == pytest.approx(26e6)
    assert "2026 Q2" in r.period_label and "2026 Q1" in r.period_label


def test_step3_class_drivers(flow):
    r = _ask(flow, "Which Reserving Classes drove that?")
    df = r.query_outputs[0].engine_result.shaped.df
    moves = dict(zip(df["reserving_class"], df["absolute_change"]))
    assert moves == pytest.approx({"Casualty": 18e6, "Property": 7e6,
                                   "Motor": 4e6, "Marine": -3e6})


def test_step4_finance_class_reconciles(flow):
    r = _ask(flow, "Show the same movement by Finance Class instead.")
    df = r.query_outputs[0].engine_result.shaped.df
    assert df["absolute_change"].sum() == pytest.approx(26e6)
    assert set(df["finance_class"]) == {"Commercial Lines", "Specialty Lines",
                                        "Personal Lines", "Reinsurance"}


def test_step5_commercial_lines_split(flow):
    r = _ask(flow, "Split Commercial Lines by region and Loss Type.")
    er = r.query_outputs[0].engine_result
    plan = er.validated.plan
    assert set(plan.group_by) == {"region", "loss_type"}
    assert any(f.field == "finance_class" and f.value == "Commercial Lines"
               for f in plan.filters)
    # context carried forward the quarter comparison
    assert plan.review_ids[0] == "2026-Q2"


def test_step6_projection_method_changes(flow):
    r = _ask(flow, "Which projection methods changed from last quarter?")
    df = r.query_outputs[0].engine_result.shaped.df
    assert len(df) >= 3


def test_step7_paid_claims_yoy(flow):
    r = _ask(flow, "Show the change in paid claims between this year and last.")
    er = r.query_outputs[0].engine_result
    assert er.validated.dataset == "claims_latest"
    assert er.validated.plan.review_ids == ["2026-Q2", "2025-Q2"]


def test_step8_save_and_reopen_diagnostic(flow):
    r = flow["answers"]["How much did reserves change from last quarter?"]
    record = audit_service.get_diagnostic(r.diagnostic_id)
    assert record is not None
    outcome = rerun_diagnostic(r.diagnostic_id)
    assert outcome.ok and outcome.hash_matches


def test_step9_guardrail(flow):
    r = _ask(flow, "Should we strengthen Casualty reserves?")
    assert r.status == "BLOCKED"
    assert not r.query_outputs
    assert "actuarial judgement" in r.answer_text.lower()
    assert len(r.answer_text.splitlines()) >= 2  # includes useful alternative
