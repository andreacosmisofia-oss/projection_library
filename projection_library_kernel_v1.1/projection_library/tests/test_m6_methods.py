"""Integration tests for the M6 method-selection endpoints (Expert)."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db


def _make_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    return engine, factory


@pytest.fixture()
def client_and_factory() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine, factory = _make_factory()

    def _override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c, factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _create_project(client: TestClient, **overrides) -> str:
    payload = {
        "name": "Acme Pilot",
        "sector_pack": "industrial",
        "currency": "EUR",
        "horizon_years": 3,
    }
    payload.update(overrides)
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _registry_voices(client: TestClient) -> list[dict]:
    resp = client.get("/api/registry/voices")
    assert resp.status_code == 200
    return resp.json()["items"]


def _pick_voice_with_default(client: TestClient) -> dict:
    """Pick a voice whose default_method points to a real method_id."""
    resp = client.get("/api/registry/methods")
    assert resp.status_code == 200
    method_ids = {m["method_id"] for m in resp.json()["items"]}
    for v in _registry_voices(client):
        dm = v.get("default_method")
        if isinstance(dm, str) and dm in method_ids:
            return v
    raise AssertionError("no voice with method default found in registry")


def _pick_voice_with_derived_default(client: TestClient) -> dict | None:
    """Pick a voice whose default_method points to a derived_rule_id."""
    resp = client.get("/api/registry/methods")
    method_ids = {m["method_id"] for m in resp.json()["items"]}
    resp = client.get("/api/registry/derived-rules")
    derived_ids = {r["derived_rule_id"] for r in resp.json()["items"]}
    for v in _registry_voices(client):
        dm = v.get("default_method")
        if isinstance(dm, str) and dm in derived_ids and dm not in method_ids:
            return v
    return None


def _pick_user_choice_voice(client: TestClient) -> dict | None:
    for v in _registry_voices(client):
        if v.get("default_method") in ("(utente sceglie)", "(user choice)"):
            return v
    return None


# ---------- GET -------------------------------------------------------


def test_get_methods_returns_registry_defaults_for_fresh_project(
    client_and_factory,
):
    client, _ = client_and_factory
    project_id = _create_project(client)

    resp = client.get(f"/api/projects/{project_id}/methods")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    voices = _registry_voices(client)
    assert body["count"] == len(voices)
    assert body["project_id"] == project_id

    # Every entry comes from the registry (no DB rows yet).
    sources = {entry["source"] for entry in body["items"]}
    assert sources == {"registry_default"}
    assert body["summary"]["registry_default"] == len(voices)
    assert body["summary"]["user_override"] == 0

    # All entries are flagged as default; configured_at is null
    # because nothing has been persisted yet.
    for entry in body["items"]:
        assert entry["is_default"] is True
        assert entry["configured_at"] is None


def test_get_methods_filters_by_statement(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)

    resp = client.get(
        f"/api/projects/{project_id}/methods", params={"statement": "PL"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] > 0
    assert all(entry["voice_statement"] == "PL" for entry in body["items"])


def test_get_methods_marks_user_choice_voices(client_and_factory):
    client, _ = client_and_factory
    voice = _pick_user_choice_voice(client)
    if voice is None:
        pytest.skip("no '(utente sceglie)' sentinel in registry")
    project_id = _create_project(client)

    resp = client.get(f"/api/projects/{project_id}/methods")
    assert resp.status_code == 200
    by_voice = {e["voice_id"]: e for e in resp.json()["items"]}
    entry = by_voice[voice["voice_id"]]
    assert entry["method_id"] is None
    assert entry["requires_user_choice"] is True
    assert entry["is_default"] is True


def test_get_methods_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/does-not-exist/methods")
    assert resp.status_code == 404


def test_get_methods_404_for_soft_deleted_project(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    assert (
        client.delete(f"/api/projects/{project_id}").status_code == 204
    )
    resp = client.get(f"/api/projects/{project_id}/methods")
    assert resp.status_code == 404


# ---------- PUT -------------------------------------------------------


def test_put_method_changes_voice(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice = _pick_voice_with_default(client)
    voice_id = voice["voice_id"]

    # Pick a method different from the current default.
    resp = client.get("/api/registry/methods")
    methods = resp.json()["items"]
    new_method = next(
        m for m in methods if m["method_id"] != voice["default_method"]
    )

    put = client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": new_method["method_id"]},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["voice_id"] == voice_id
    assert body["method_id"] == new_method["method_id"]
    assert body["method_technical_code"] == new_method["tech_code"]
    assert body["is_default"] is False
    assert body["source"] == "user_override"
    assert body["configured_at"] is not None

    # GET reflects the override and the summary counts shift by one.
    listing = client.get(f"/api/projects/{project_id}/methods").json()
    by_voice = {e["voice_id"]: e for e in listing["items"]}
    assert by_voice[voice_id]["method_id"] == new_method["method_id"]
    assert by_voice[voice_id]["source"] == "user_override"
    assert listing["summary"]["user_override"] == 1
    assert listing["summary"]["registry_default"] == listing["count"] - 1


def test_put_method_back_to_default_marks_is_default_true(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice = _pick_voice_with_default(client)
    voice_id = voice["voice_id"]
    default_method = voice["default_method"]

    # Override to something else, then revert to the original default.
    resp = client.get("/api/registry/methods")
    other = next(
        m for m in resp.json()["items"] if m["method_id"] != default_method
    )
    client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": other["method_id"]},
    )

    revert = client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": default_method},
    )
    assert revert.status_code == 200
    body = revert.json()
    assert body["method_id"] == default_method
    assert body["is_default"] is True
    assert body["source"] == "registry_default"

    # Summary now back to all-defaults.
    listing = client.get(f"/api/projects/{project_id}/methods").json()
    assert listing["summary"]["user_override"] == 0


def test_put_unknown_voice_returns_404(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.put(
        f"/api/projects/{project_id}/methods/not.a.real.voice",
        json={"method_id": "flat"},
    )
    assert resp.status_code == 404


def test_put_unknown_method_returns_422(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice = _pick_voice_with_default(client)
    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice['voice_id']}",
        json={"method_id": "not_a_real_method"},
    )
    assert resp.status_code == 422


def test_put_accepts_derived_rule_id(client_and_factory):
    client, _ = client_and_factory
    voice = _pick_voice_with_derived_default(client)
    if voice is None:
        pytest.skip(
            "no voice with derived_rule_id default in registry"
        )
    project_id = _create_project(client)

    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice['voice_id']}",
        json={"method_id": voice["default_method"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method_id"] == voice["default_method"]
    assert body["is_default"] is True


def test_put_on_deleted_project_returns_404(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    resp = client.put(
        f"/api/projects/{project_id}/methods/pl.rev.gross.product_sales",
        json={"method_id": "flat"},
    )
    assert resp.status_code == 404


def test_put_empty_method_id_returns_422(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice = _pick_voice_with_default(client)
    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice['voice_id']}",
        json={"method_id": ""},
    )
    assert resp.status_code == 422
