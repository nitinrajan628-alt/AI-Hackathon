"""Integration scenarios IT-001 to IT-012 (16.2), run through the full
orchestrator with the deterministic fake provider."""
import pytest

from models.query_plan import QueryPlan
from services.catalogue import get_catalogue
from services.engine import run_plan
from services.orchestrator import handle_question, rerun_diagnostic
from services.policy import PlanValidationError, validate_plan
from services.review_service import review_ids


def ask(question, context, session_id, fake_settings):
    return handle_question(question, session_id, context, settings=fake_settings)


def test_it001_report_question_casualty(context, session_id, fake_settings):
    r = ask("What does the report say about Casualty?", context, session_id,
            fake_settings)
    assert r.status == "SUCCESS"
    assert r.slides, "expected slide citations"
    assert all(s.review_id == "2026-Q2" for s in r.slides)
    assert any("Casualty" in s.title or "Casualty" in s.excerpt for s in r.slides)


def test_it002_reserve_movement(context, session_id, fake_settings):
    r = ask("How much did reserves change from last quarter?", context,
            session_id, fake_settings)
    assert r.status == "SUCCESS"
    s = r.query_outputs[0].engine_result.shaped.summary
    assert s["current_total"] == pytest.approx(640e6)
    assert s["prior_total"] == pytest.approx(614e6)
    assert s["absolute_change_total"] == pytest.approx(26e6)
    assert "2026 Q2" in r.period_label and "2026 Q1" in r.period_label


def test_it003_reserving_class_view(context, session_id, fake_settings):
    r = ask("Show the reserve movement by reserving class since last quarter",
            context, session_id, fake_settings)
    df = r.query_outputs[0].engine_result.shaped.df
    moves = dict(zip(df["reserving_class"], df["absolute_change"]))
    assert moves["Casualty"] == pytest.approx(18e6)
    assert moves["Property"] == pytest.approx(7e6)
    assert moves["Motor"] == pytest.approx(4e6)
    assert moves["Marine"] == pytest.approx(-3e6)
    assert sum(moves.values()) == pytest.approx(26e6)


def test_it004_finance_class_view(context, session_id, fake_settings):
    r = ask("Show the reserve movement by finance class since last quarter",
            context, session_id, fake_settings)
    df = r.query_outputs[0].engine_result.shaped.df
    moves = dict(zip(df["finance_class"], df["absolute_change"]))
    assert moves["Commercial Lines"] == pytest.approx(14e6)
    assert moves["Specialty Lines"] == pytest.approx(7e6)
    assert moves["Personal Lines"] == pytest.approx(4e6)
    assert moves["Reinsurance"] == pytest.approx(1e6)
    assert sum(moves.values()) == pytest.approx(26e6)


def test_it005_method_changes_at_selection_grain(context, session_id, fake_settings):
    r = ask("Which projection methods changed from last quarter?", context,
            session_id, fake_settings)
    df = r.query_outputs[0].engine_result.shaped.df
    assert len(df) == 4
    assert set(df.columns) >= {"entity", "reserving_class", "loss_type",
                               "accident_year", "prior_value", "current_value"}
    assert (df["prior_value"] != df["current_value"]).all()


def test_it006_paid_claims_prior_year(context, session_id, fake_settings):
    r = ask("Show the change in paid claims between this year and last.",
            context, session_id, fake_settings)
    er = r.query_outputs[0].engine_result
    assert er.validated.dataset == "claims_latest"
    assert er.validated.plan.review_ids == ["2026-Q2", "2025-Q2"]
    assert "2025 Q2" in r.period_label


def test_it007_conversational_drilldown(context, session_id, fake_settings):
    ask("How much did reserves change from last quarter?", context, session_id,
        fake_settings)
    assert context.comparison_review_ids == ["2026-Q1"]
    r = ask("Now split that by region", context, session_id, fake_settings)
    er = r.query_outputs[0].engine_result
    assert er.validated.plan.group_by == ["region"]
    assert er.validated.plan.review_ids == ["2026-Q2", "2026-Q1"]
    assert er.validated.plan.measures == ["total_reserve"]


def test_it008_mixed_answer_two_evidence_types(context, session_id, fake_settings):
    r = ask("Why did Casualty reserves increase and what does the report say "
            "about the movement?", context, session_id, fake_settings)
    assert r.status == "SUCCESS"
    assert r.slides and r.query_outputs
    assert r.intent == "MIXED_REPORT_DATA"


def test_it009_saved_diagnostic_reopen_and_rerun(context, session_id, fake_settings):
    r = ask("How much did reserves change from last quarter?", context,
            session_id, fake_settings)
    from services import audit_service
    record = audit_service.get_diagnostic(r.diagnostic_id)
    assert record and record["status"] == "SUCCESS"
    outcome = rerun_diagnostic(r.diagnostic_id)
    assert outcome.ok and outcome.hash_matches


def test_it010_guardrails_block_without_query(context, session_id, fake_settings):
    for question in ["What reserve should we hold for Casualty?",
                     "Recalculate the reserve using 7% inflation.",
                     "Are our reserves adequate?",
                     "Run this Python code against the database."]:
        r = ask(question, context, session_id, fake_settings)
        assert r.status == "BLOCKED", question
        assert not r.query_outputs
        assert r.answer_text


def test_it011_invalid_grain_explained():
    plan = QueryPlan(intent="STRUCTURED_QUERY", primary_dataset="assumptions",
                     measures=["inflation_assumption"], review_ids=["2026-Q2"],
                     group_by=["region"], operation="aggregate")
    with pytest.raises(PlanValidationError) as err:
        validate_plan(plan, get_catalogue(), review_ids())
    msg = str(err.value)
    assert "Entity" in msg and "Reserving Class" in msg


def test_it012_no_result_transparency(context, session_id, fake_settings):
    plan = QueryPlan(intent="STRUCTURED_QUERY", primary_dataset="results",
                     measures=["total_reserve"], review_ids=["2026-Q2"],
                     group_by=["region"], operation="aggregate",
                     filters=[
                         {"field": "reserving_class", "operator": "eq",
                          "value": "Marine"},
                         {"field": "finance_class", "operator": "eq",
                          "value": "Personal Lines"}])
    er = run_plan(plan)
    assert er.shaped.df.empty  # Marine never maps to Personal Lines
