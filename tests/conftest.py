import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("LLM_PROVIDER", "fake")

import pytest

from services.context_service import ConversationContext
from services.settings import LLMSettings


@pytest.fixture()
def fake_settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    return LLMSettings()


@pytest.fixture()
def context():
    return ConversationContext(current_review_id="2026-Q2")


@pytest.fixture()
def session_id():
    import uuid
    return str(uuid.uuid4())
