"""Tests for ``GET /api/health/full`` (M13)."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health_full_returns_status_uptime_registries_and_db(client):
    resp = client.get("/api/health/full")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "ok"

    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], (int, float))
    assert body["uptime_seconds"] >= 0

    registries = body["registries"]
    assert isinstance(registries, dict)
    assert registries.get("voices", 0) > 0
    assert registries.get("methods", 0) > 0
    assert registries.get("kpis", 0) > 0

    db = body["db"]
    assert isinstance(db, dict)
    assert isinstance(db["tables"], int)
    assert db["tables"] >= 0
    # last_migration is either None (fresh DB without alembic_version)
    # or a string revision id; both are valid.
    assert db["last_migration"] is None or isinstance(
        db["last_migration"], str
    )


def test_health_full_uptime_is_monotonic(client):
    """Two consecutive calls must report non-decreasing uptime."""
    first = client.get("/api/health/full").json()["uptime_seconds"]
    second = client.get("/api/health/full").json()["uptime_seconds"]
    assert second >= first
