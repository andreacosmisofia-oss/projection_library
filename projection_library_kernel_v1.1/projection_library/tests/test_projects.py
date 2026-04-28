"""M2 acceptance: CRUD endpoints for /api/projects.

Each test runs against a fresh in-memory SQLite so persistence between
tests is isolated. The FastAPI lifespan still loads the real registries
on startup (M1.9 contract); only the DB session dependency is
overridden.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db


def _make_test_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    factory = _make_test_session_factory()

    def _override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _valid_payload(**overrides) -> dict:
    base = {
        "name": "Acme Pilot",
        "company_name": "Acme S.p.A.",
        "sector_pack": "industrial",
        "perimeter": "consolidated",
        "currency": "EUR",
        "country": "IT",
        "accounting_standard": "IFRS",
        "horizon_years": 3,
        "tier_level": "TIER_2",
        "etr_default": 0.27,
    }
    base.update(overrides)
    return base


def test_create_project(client: TestClient) -> None:
    resp = client.post("/api/projects", json=_valid_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["name"] == "Acme Pilot"
    assert body["currency"] == "EUR"
    assert body["horizon_years"] == 3
    assert body["accounting_standard"] == "IFRS"
    assert body["deleted_at"] is None
    assert body["created_at"]
    assert body["updated_at"]


def test_create_project_rejects_non_eur(client: TestClient) -> None:
    resp = client.post("/api/projects", json=_valid_payload(currency="USD"))
    assert resp.status_code == 422


def test_create_project_rejects_horizon_other_than_3(client: TestClient) -> None:
    resp = client.post("/api/projects", json=_valid_payload(horizon_years=5))
    assert resp.status_code == 422


def test_list_projects(client: TestClient) -> None:
    for i in range(3):
        r = client.post("/api/projects", json=_valid_payload(name=f"P{i}"))
        assert r.status_code == 201

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["items"]) == 3

    paged = client.get("/api/projects?limit=2&offset=0")
    assert paged.status_code == 200
    assert len(paged.json()["items"]) == 2


def test_get_project(client: TestClient) -> None:
    created = client.post("/api/projects", json=_valid_payload()).json()
    resp = client.get(f"/api/projects/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_not_found(client: TestClient) -> None:
    resp = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_patch_project(client: TestClient) -> None:
    created = client.post("/api/projects", json=_valid_payload()).json()
    resp = client.patch(
        f"/api/projects/{created['id']}",
        json={"name": "Renamed", "tier_level": "TIER_3"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["tier_level"] == "TIER_3"
    # Unchanged fields stay put.
    assert body["sector_pack"] == "industrial"
    assert body["currency"] == "EUR"


def test_patch_unknown_field_rejected(client: TestClient) -> None:
    created = client.post("/api/projects", json=_valid_payload()).json()
    # currency is not in ProjectUpdate; pydantic ignores by default,
    # but horizon_years must not be patchable either.
    resp = client.patch(
        f"/api/projects/{created['id']}",
        json={"horizon_years": 5},
    )
    # pydantic v2 ignores unknown keys by default; the field must not
    # be persisted. Re-fetch and confirm.
    assert resp.status_code == 200
    refetched = client.get(f"/api/projects/{created['id']}").json()
    assert refetched["horizon_years"] == 3


def test_delete_project(client: TestClient) -> None:
    created = client.post("/api/projects", json=_valid_payload()).json()
    resp = client.delete(f"/api/projects/{created['id']}")
    assert resp.status_code == 204

    # Soft delete: no longer visible via list/detail.
    detail = client.get(f"/api/projects/{created['id']}")
    assert detail.status_code == 404
    listing = client.get("/api/projects").json()
    assert listing["count"] == 0


def test_delete_already_deleted_returns_404(client: TestClient) -> None:
    created = client.post("/api/projects", json=_valid_payload()).json()
    assert client.delete(f"/api/projects/{created['id']}").status_code == 204
    assert client.delete(f"/api/projects/{created['id']}").status_code == 404
