"""M1.9 acceptance tests: loader green on real registries + endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.infrastructure.registry import load_registries


# Cardinalities pinned to audit_report.md §8 (M1.0).
EXPECTED_VOICES = 246
EXPECTED_METHODS = 62
EXPECTED_DERIVED_RULES = 19
EXPECTED_KPIS = 84
EXPECTED_VALIDATION_RULES = 73
EXPECTED_SECTOR_PACKS = 6


@pytest.fixture(scope="module")
def client() -> TestClient:
    """A TestClient enters the app's lifespan, which loads + caches the
    registries; exiting the context tears them down."""
    with TestClient(app) as c:
        yield c


def test_loader_green() -> None:
    """The loader must succeed against the real registries — no schema
    errors, no cross-reference errors, no DAG cycles, no whitelist."""
    reg = load_registries()
    counts = reg.counts()
    assert counts["voices"] == EXPECTED_VOICES
    assert counts["methods"] == EXPECTED_METHODS
    assert counts["derived_rules"] == EXPECTED_DERIVED_RULES
    assert counts["kpis"] == EXPECTED_KPIS
    assert counts["validation_rules"] == EXPECTED_VALIDATION_RULES
    assert counts["sector_packs"] == EXPECTED_SECTOR_PACKS


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["registries_loaded"] is True
    assert body["registries"]["voices"] == EXPECTED_VOICES


def test_voices_endpoint(client: TestClient) -> None:
    response = client.get("/api/registry/voices")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == EXPECTED_VOICES
    assert len(body["items"]) == EXPECTED_VOICES
    assert all("voice_id" in v for v in body["items"])


def test_voice_not_found(client: TestClient) -> None:
    response = client.get("/api/registry/voices/fake")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_methods_endpoint(client: TestClient) -> None:
    response = client.get("/api/registry/methods")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == EXPECTED_METHODS


def test_kpis_endpoint(client: TestClient) -> None:
    response = client.get("/api/registry/kpis")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == EXPECTED_KPIS
