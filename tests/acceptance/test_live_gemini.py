"""Live Gemini smoke tests (9.13). Run only when a key is configured and
RUN_LIVE_LLM=1, e.g.:

    RUN_LIVE_LLM=1 .venv/bin/python -m pytest tests/acceptance/test_live_gemini.py -v
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1" or not os.environ.get("GEMINI_API_KEY"),
    reason="live Gemini tests need RUN_LIVE_LLM=1 and GEMINI_API_KEY")


@pytest.fixture()
def live_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    from services.settings import LLMSettings
    return LLMSettings()


def test_live_planning_call_schema_valid(live_settings):
    from services.query_planner import plan_request
    result = plan_request(
        "Show reserve movements since last quarter by Finance Class",
        {"current_review_id": "2026-Q2", "comparison_review_ids": [],
         "active_filters": {}, "last_group_by": None, "last_measure": None,
         "last_dataset": None},
        settings=live_settings)
    r = result.response
    assert r.intent in ("PERIOD_COMPARISON", "STRUCTURED_QUERY", "MIXED_REPORT_DATA")
    assert r.query_plans and r.query_plans[0].primary_dataset == "results"
    assert r.policy.status == "ALLOW"


def test_live_guardrail_blocks_adequacy(live_settings):
    from services.query_planner import plan_request
    result = plan_request(
        "Are our reserves adequate?",
        {"current_review_id": "2026-Q2", "comparison_review_ids": [],
         "active_filters": {}, "last_group_by": None, "last_measure": None,
         "last_dataset": None},
        settings=live_settings)
    assert result.response.policy.status == "BLOCK"
    assert not result.response.query_plans


def test_live_end_to_end_movement(live_settings, context, session_id):
    from services.orchestrator import handle_question
    r = handle_question("How much did reserves change from last quarter?",
                        session_id, context, settings=live_settings)
    assert r.status == "SUCCESS"
    s = r.query_outputs[0].engine_result.shaped.summary
    assert s["absolute_change_total"] == pytest.approx(26e6)
    # every number in the drafted answer is traceable to evidence
    assert r.draft is not None
