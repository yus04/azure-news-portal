"""Portal テストの共通フィクスチャ。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "cosmos" / "articles.json"

os.environ.setdefault("PORTAL_OFFLINE_MODE", "1")
os.environ.setdefault("PORTAL_OFFLINE_DATA", str(SAMPLES))
os.environ.pop("COSMOS_ENDPOINT", None)


@pytest.fixture(scope="session")
def documents() -> list[dict[str, Any]]:
    return json.loads(SAMPLES.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def repository(documents: list[dict[str, Any]]):
    from app.repository import InMemoryArticleRepository

    return InMemoryArticleRepository(documents)
