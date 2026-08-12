"""Deterministic guardrail pre-checks. AI Call 1 remains the authoritative
typed planner; these regex checks catch obvious prohibited requests before
any model call and guarantee consistent blocking even if the model errs."""
from __future__ import annotations

import re
from functools import lru_cache

from services.settings import load_yaml


@lru_cache(maxsize=1)
def _compiled_rules() -> list[tuple[str, list[re.Pattern]]]:
    guardrails = load_yaml("guardrails.yaml")
    rules = []
    for category, spec in guardrails.get("categories", {}).items():
        patterns = [re.compile(p, re.IGNORECASE) for p in spec.get("patterns", [])]
        rules.append((category, patterns))
    return rules


def precheck_guardrails(question: str) -> str | None:
    """Return a guardrail category if the question obviously requires
    prohibited actuarial judgement, recalculation or code execution."""
    text = question.strip()
    for category, patterns in _compiled_rules():
        for pattern in patterns:
            if pattern.search(text):
                return category
    return None
