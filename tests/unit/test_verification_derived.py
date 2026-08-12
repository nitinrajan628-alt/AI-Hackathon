"""Verification accepts reconstructible figures but still rejects invention."""
import pytest

from models.ai_contracts import AnswerDraft
from models.evidence import EvidencePackage, QueryResultEvidence
from services.answer_service import verify_answer


def package(rows, summary=None) -> EvidencePackage:
    return EvidencePackage(
        question="q",
        period_context={"display_label": "2026 Q2 compared with 2026 Q1"},
        query_results=[QueryResultEvidence(
            evidence_id="qr_1", dataset="results", operation="compare",
            measures=["total_reserve"], group_by=["accident_year"],
            periods=["2026-Q2", "2026-Q1"],
            period_labels=["2026 Q2", "2026 Q1"], unit="GBP millions",
            rows=rows, summary=summary or {})])


ROWS = [
    {"accident_year": 2024, "current": 117.2, "prior": 114.2, "absolute_change": 3.0},
    {"accident_year": 2025, "current": 178.8, "prior": 174.7, "absolute_change": 4.1},
    {"accident_year": 2026, "current": 121.8, "prior": 110.6, "absolute_change": 11.2},
]


def draft(text: str) -> AnswerDraft:
    return AnswerDraft(headline=text,
                       evidence_references=[{"evidence_type": "query_result",
                                             "evidence_id": "qr_1"}])


def test_literal_row_value_passes():
    assert verify_answer(draft("Accident year 2026 rose GBP 11.2m"), package(ROWS)).passed


def test_column_total_is_reconstructible_and_passes():
    """417.8 = 117.2 + 178.8 + 121.8: a total the reader may legitimately state."""
    result = verify_answer(draft("The three years total GBP 417.8m"), package(ROWS))
    assert result.passed, result.failures


def test_movement_total_is_reconstructible():
    result = verify_answer(draft("Together they moved GBP 18.3m"), package(ROWS))
    assert result.passed, result.failures


def test_share_of_total_is_reconstructible():
    """11.2 of the 18.3m movement is 61.2%."""
    result = verify_answer(
        draft("Accident year 2026 accounts for 61.2% of the movement"),
        package(ROWS))
    assert result.passed, result.failures


def test_percentage_change_is_reconstructible():
    """121.8 vs 110.6 is a 10.1% increase."""
    result = verify_answer(draft("Accident year 2026 rose 10.1%"), package(ROWS))
    assert result.passed, result.failures


def test_subtotal_within_a_category_is_reconstructible():
    rows = [
        {"review": "2026 Q2", "accident_year": 2025, "total_reserve": 178.8},
        {"review": "2026 Q2", "accident_year": 2026, "total_reserve": 121.8},
        {"review": "2026 Q1", "accident_year": 2025, "total_reserve": 174.7},
        {"review": "2026 Q1", "accident_year": 2026, "total_reserve": 110.6},
    ]
    result = verify_answer(draft("2026 Q2 totals GBP 300.6m"), package(rows))
    assert result.passed, result.failures


def test_invented_number_still_fails():
    result = verify_answer(draft("Reserves rose GBP 987.6m"), package(ROWS))
    assert not result.passed


def test_plausible_but_unsupported_number_still_fails():
    """A figure of the right magnitude that is not reconstructible is rejected."""
    result = verify_answer(draft("Accident year 2023 rose GBP 47.3m"), package(ROWS))
    assert not result.passed


def test_fabricated_evidence_id_still_fails():
    d = AnswerDraft(headline="Fine",
                    evidence_references=[{"evidence_type": "query_result",
                                          "evidence_id": "qr_99"}])
    assert not verify_answer(d, package(ROWS)).passed


def test_numbers_inside_analysis_sections_are_verified():
    d = AnswerDraft(
        headline="Casualty rose",
        sections=[{"title": "Concentration",
                   "points": ["Accident year 2026 contributed GBP 999.9m"]}],
        evidence_references=[{"evidence_type": "query_result",
                              "evidence_id": "qr_1"}])
    result = verify_answer(d, package(ROWS))
    assert not result.passed
    assert any("999.9" in f for f in result.failures)
