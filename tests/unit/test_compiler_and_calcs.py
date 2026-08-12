"""SQL compilation allow-listing, deterministic calculations and hash
stability (16.1)."""
import re

import pandas as pd
import pytest

from models.query_plan import QueryPlan
from services import audit_service
from services.catalogue import get_catalogue
from services.diagnostics import apply as shape
from services.engine import run_plan
from services.policy import validate_plan
from services.query_compiler import compile_query
from services.review_service import list_reviews, review_ids


def compiled(**kwargs):
    base = dict(intent="STRUCTURED_QUERY", primary_dataset="results",
                review_ids=["2026-Q2"], measures=["total_reserve"],
                operation="aggregate")
    base.update(kwargs)
    vp = validate_plan(QueryPlan(**base), get_catalogue(), review_ids())
    return vp, compile_query(vp)


ALLOWED_TOKENS = re.compile(
    r"^SELECT [A-Za-z0-9_,()\s.]+ FROM [A-Za-z_]+ WHERE [A-Za-z0-9_?,()\s=<>]+"
    r"( GROUP BY [A-Za-z0-9_,\s]+)?( LIMIT \d+)?$")


def test_sql_uses_only_allowlisted_identifiers():
    cat = get_catalogue()
    vp, cq = compiled(group_by=["finance_class"],
                      filters=[{"field": "reserving_class", "operator": "eq",
                                "value": "Casualty"}])
    assert cq.sql.startswith("SELECT")
    assert "result_snapshot" in cq.sql
    assert ALLOWED_TOKENS.match(cq.sql), cq.sql
    # user value is bound, never interpolated
    assert "Casualty" not in cq.sql
    assert "Casualty" in cq.parameters


def test_filter_values_bound_as_parameters():
    _, cq = compiled(filters=[{"field": "accident_year", "operator": "between",
                               "value": [2022, 2024]}])
    assert "BETWEEN ? AND ?" in cq.sql
    assert 2022 in cq.parameters and 2024 in cq.parameters


def test_row_cap_always_applied():
    _, cq = compiled()
    assert "LIMIT" in cq.sql


def _shape(plan_kwargs, df):
    vp = validate_plan(QueryPlan(**plan_kwargs), get_catalogue(), review_ids())
    reviews = {r["review_id"]: r for r in list_reviews()}
    return shape(vp, df, reviews, get_catalogue().measures(vp.dataset))


def test_compare_movement_and_percentage():
    df = pd.DataFrame({
        "review_id": ["2026-Q2", "2026-Q1"],
        "finance_class": ["Commercial Lines", "Commercial Lines"],
        "total_reserve": [293e6, 279e6],
    })
    result = _shape(dict(intent="PERIOD_COMPARISON", primary_dataset="results",
                         review_ids=["2026-Q2", "2026-Q1"],
                         measures=["total_reserve"], group_by=["finance_class"],
                         operation="compare"), df)
    row = result.df.iloc[0]
    assert row["absolute_change"] == pytest.approx(14e6)
    assert row["percentage_change"] == pytest.approx(14 / 279 * 100, rel=1e-6)


def test_percentage_change_none_when_prior_zero():
    df = pd.DataFrame({
        "review_id": ["2026-Q2", "2026-Q1"],
        "finance_class": ["A", "A"],
        "total_reserve": [10.0, 0.0],
    })
    result = _shape(dict(intent="PERIOD_COMPARISON", primary_dataset="results",
                         review_ids=["2026-Q2", "2026-Q1"],
                         measures=["total_reserve"], group_by=["finance_class"],
                         operation="compare"), df)
    assert result.df.iloc[0]["percentage_change"] is None


def test_contribution_zero_total_movement():
    df = pd.DataFrame({
        "review_id": ["2026-Q2", "2026-Q1", "2026-Q2", "2026-Q1"],
        "finance_class": ["A", "A", "B", "B"],
        "total_reserve": [10.0, 5.0, 0.0, 5.0],
    })
    result = _shape(dict(intent="PERIOD_COMPARISON", primary_dataset="results",
                         review_ids=["2026-Q2", "2026-Q1"],
                         measures=["total_reserve"], group_by=["finance_class"],
                         operation="contribution_to_movement"), df)
    assert result.df["contribution_pct"].isna().all() or \
        (result.df["contribution_pct"] is not None and result.warnings)
    assert result.warnings  # zero total movement stated, not fabricated


def test_missing_group_filled_with_zero_for_additive():
    df = pd.DataFrame({
        "review_id": ["2026-Q2", "2026-Q1", "2026-Q2"],
        "finance_class": ["A", "A", "B"],   # B absent in prior review
        "total_reserve": [10.0, 8.0, 4.0],
    })
    result = _shape(dict(intent="PERIOD_COMPARISON", primary_dataset="results",
                         review_ids=["2026-Q2", "2026-Q1"],
                         measures=["total_reserve"], group_by=["finance_class"],
                         operation="compare"), df)
    b = result.df[result.df["finance_class"] == "B"].iloc[0]
    assert b["prior"] == 0.0 and b["absolute_change"] == pytest.approx(4.0)


def test_result_arithmetic_reconciliation():
    from services.db import get_review_connection
    con = get_review_connection()
    bad = con.execute(
        """SELECT COUNT(*) FROM result_snapshot
           WHERE ABS(case_reserves-(incurred_claims-paid_claims))>1
              OR ABS(ibnr-(ultimate_claims-incurred_claims))>1
              OR ABS(total_reserve-(ultimate_claims-paid_claims))>1""").fetchone()[0]
    con.close()
    assert bad == 0


def test_query_hash_stability():
    plan = dict(intent="PERIOD_COMPARISON", primary_dataset="results",
                review_ids=["2026-Q2", "2026-Q1"], measures=["total_reserve"],
                group_by=["finance_class"], operation="compare")
    h1 = audit_service.query_hash(plan)
    h2 = audit_service.query_hash(dict(plan))
    assert h1 == h2
    plan2 = dict(plan, group_by=["region"])
    assert audit_service.query_hash(plan2) != h1


def test_read_only_connection_blocks_writes():
    import sqlite3
    from services.db import get_review_connection
    con = get_review_connection()
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM result_snapshot")
    con.close()


def test_engine_reserve_movement_reconciles():
    plan = QueryPlan(intent="PERIOD_COMPARISON", primary_dataset="results",
                     review_ids=["2026-Q2", "2026-Q1"],
                     measures=["total_reserve"], group_by=[],
                     operation="compare")
    er = run_plan(plan)
    s = er.shaped.summary
    assert s["current_total"] == pytest.approx(640e6)
    assert s["prior_total"] == pytest.approx(614e6)
    assert s["absolute_change_total"] == pytest.approx(26e6)
