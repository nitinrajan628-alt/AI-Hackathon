"""Deep-analysis battery: detection, focus, assembly and safety."""
import pytest

from services.analysis_service import (
    build_battery,
    detect_focus,
    is_analytical,
    run_analysis,
)
from services.catalogue import get_catalogue


@pytest.mark.parametrize("question", [
    "Analyse how Casualty has developed across accident years",
    "Why did Casualty increase?",
    "What's driving the movement?",
    "Deep dive into Property",
    "Explain the Marine release",
    "How has Casualty developed over the last two years?",
])
def test_analytical_questions_are_detected(question):
    assert is_analytical(question)


@pytest.mark.parametrize("question", [
    "How much did reserves change from last quarter?",
    "Show reserves by finance class",
    "What is the IBNR for Motor?",
    "Which projection methods changed from last quarter?",
])
def test_simple_questions_are_not_treated_as_analysis(question):
    assert not is_analytical(question)


def test_focus_detects_named_class():
    focus = detect_focus("Analyse Casualty across accident years", get_catalogue())
    assert [(f.field, f.value) for f in focus.filters] == [("reserving_class", "Casualty")]
    assert focus.breakdown == "accident_year"
    assert focus.label == "Casualty"


def test_focus_falls_back_to_conversation_filters():
    focus = detect_focus("why is it moving?", get_catalogue(),
                         inherited_filters=[{"field": "region", "operator": "eq",
                                             "value": "UK and Ireland"}])
    assert [(f.field, f.value) for f in focus.filters] == [("region", "UK and Ireland")]


def test_portfolio_focus_when_nothing_named():
    focus = detect_focus("what is driving the movement?", get_catalogue())
    assert focus.filters == [] and focus.label == "the portfolio"


def test_battery_covers_the_required_analytical_angles():
    focus = detect_focus("Analyse Casualty", get_catalogue())
    battery = build_battery("Analyse Casualty", "2026-Q2", focus)
    operations = {p.operation for _t, p in battery}
    datasets = {p.primary_dataset for _t, p in battery}
    assert {"aggregate", "compare", "contribution_to_movement", "trend",
            "list_changes"} <= operations
    assert {"results", "claims_latest", "assumptions"} <= datasets
    assert len(battery) >= 8


def test_battery_is_scoped_to_the_focus():
    focus = detect_focus("Analyse Casualty", get_catalogue())
    battery = build_battery("Analyse Casualty", "2026-Q2", focus)
    scoped = [p for t, p in battery if "comparison" not in t]
    for p in scoped:
        if p.primary_dataset == "assumptions":
            continue
        assert any(f.field == "reserving_class" and f.value == "Casualty"
                   for f in p.filters), p


def test_cross_class_comparators_are_unfiltered():
    focus = detect_focus("Analyse Casualty", get_catalogue())
    battery = build_battery("Analyse Casualty", "2026-Q2", focus)
    comparators = [p for t, p in battery if "comparison" in t]
    assert comparators, "cross-class comparison should be included"
    assert all(p.filters == [] for p in comparators)


def test_battery_can_be_run_without_cross_class():
    focus = detect_focus("Analyse Casualty", get_catalogue())
    battery = build_battery("Analyse Casualty", "2026-Q2", focus, cross_class=False)
    assert not [t for t, _p in battery if "comparison" in t]


def test_run_analysis_executes_and_reconciles():
    result = run_analysis("Analyse how Casualty has developed across accident years",
                          "2026-Q2")
    assert len(result.outputs) >= 8
    assert not result.skipped, result.skipped
    # The quarter-on-quarter diagnostic must reconcile to the seeded +18m.
    compare = [er for er in result.outputs
               if er.validated.plan.operation == "compare"
               and er.validated.plan.review_ids == ["2026-Q2", "2026-Q1"]
               and er.validated.plan.filters]
    assert compare
    movement = compare[0].shaped.summary["absolute_change_total"]
    assert movement == pytest.approx(18e6)


def test_analysis_for_a_first_review_skips_comparisons_gracefully():
    """2024 Q3 has no prior or prior-year review; the battery must degrade
    rather than fail."""
    result = run_analysis("Analyse Casualty", "2024-Q3")
    assert result.outputs, "position diagnostics should still run"
    for er in result.outputs:
        assert er.validated.plan.review_ids


def test_run_analysis_every_query_passes_policy_validation():
    """Nothing in the battery may bypass the catalogue/grain rules."""
    result = run_analysis("Analyse Casualty across accident years", "2026-Q2")
    for er in result.outputs:
        assert er.compiled.sql.startswith("SELECT")
        assert "Casualty" not in er.compiled.sql   # values are bound, not inlined
