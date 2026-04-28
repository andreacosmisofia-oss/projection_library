"""Integration tests for the M7 driver-intake endpoints.

Mirrors the testing convention of ``test_m6_methods.py``: the registry
loads against the real YAML files and the DB is an in-memory SQLite
shared per test via the ``StaticPool`` trick. Each test seeds the
needed ``method_configs`` rows by calling the M6 PUT endpoint, so the
M7 surface is exercised exactly as the UI would.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.domain.methods.compatibility import (
    DRIVER_TYPE_SCALAR,
    DRIVER_TYPE_STATIC_PARAMETERS,
    compute_required_drivers,
)
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import MethodConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _put_method(
    client: TestClient, project_id: str, voice_id: str, method_id: str
) -> None:
    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": method_id},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# GET /drivers/required
# ---------------------------------------------------------------------------


def test_required_empty_for_fresh_project(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["project_id"] == project_id
    assert body["count"] == 0
    assert body["items"] == []
    assert body["summary"] == {
        "total": 0,
        "complete": 0,
        "partial": 0,
        "missing": 0,
        "skipped": 0,
    }


def test_required_exposes_voice_scoped_driver_after_method_config(
    client_and_factory,
):
    client, _ = client_and_factory
    project_id = _create_project(client)

    voice_id = "pl.cogs.labour.direct"
    _put_method(client, project_id, voice_id, "headcount_unit_cost")

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    assert resp.status_code == 200
    body = resp.json()

    expected_id = f"driver.{voice_id}.headcount"
    by_id = {item["driver_id"]: item for item in body["items"]}
    assert expected_id in by_id

    entry = by_id[expected_id]
    assert entry["type"] == DRIVER_TYPE_SCALAR
    assert entry["required_by_methods"] == ["headcount_unit_cost"]
    assert entry["required_for_voices"] == [voice_id]
    assert entry["years_required"] == ["Y-1", "Y0"]
    assert entry["current_status"] == "missing"
    assert entry["values"] is None

    assert body["summary"]["missing"] >= 1


def test_required_exposes_literal_drivers_for_arr_bridge(client_and_factory):
    """``arr_bridge`` references 4 literal SaaS driver ids — they must
    surface as global, *non* voice-scoped ids."""
    client, _ = client_and_factory
    project_id = _create_project(client)

    _put_method(client, project_id, "pl.rev.gross.subscription", "arr_bridge")

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    assert resp.status_code == 200
    items = {item["driver_id"]: item for item in resp.json()["items"]}

    expected = {
        "driver.saas.new_arr",
        "driver.saas.expansion_arr",
        "driver.saas.churn_arr",
        "driver.saas.contraction_arr",
    }
    assert expected.issubset(items.keys())
    for driver_id in expected:
        entry = items[driver_id]
        assert entry["type"] == DRIVER_TYPE_SCALAR
        assert entry["required_for_voices"] == ["pl.rev.gross.subscription"]
        assert entry["required_by_methods"] == ["arr_bridge"]


def test_required_classifies_term_loan_as_static_parameters(
    client_and_factory,
):
    client, _ = client_and_factory
    project_id = _create_project(client)

    voice_id = "bs.nfp.borrowings.term_loan_repayments"
    _put_method(client, project_id, voice_id, "term_loan_amortization_linear")

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    body = resp.json()
    items = {item["driver_id"]: item for item in body["items"]}

    for key in ("initial_principal", "term_years"):
        driver_id = f"driver.{voice_id}.{key}"
        assert driver_id in items
        entry = items[driver_id]
        assert entry["type"] == DRIVER_TYPE_STATIC_PARAMETERS
        assert entry["years_required"] == []


def test_required_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/does-not-exist/drivers/required")
    assert resp.status_code == 404


def test_required_404_for_soft_deleted_project(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    assert client.delete(f"/api/projects/{project_id}").status_code == 204

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /drivers/upload
# ---------------------------------------------------------------------------


def test_upload_full_history_marks_complete(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    driver_id = "driver.pl.cogs.labour.direct.headcount"
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "values": {"Y-1": 42, "Y0": 45},
            "unit": "FTE",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["driver_id"] == driver_id
    assert body["current_status"] == "complete"
    assert body["values"] == {"Y-1": 42, "Y0": 45}
    assert body["unit"] == "FTE"
    assert body["uploaded_at"] is not None

    listing = client.get(f"/api/projects/{project_id}/drivers/required").json()
    assert listing["summary"]["complete"] >= 1
    by_id = {item["driver_id"]: item for item in listing["items"]}
    assert by_id[driver_id]["current_status"] == "complete"


def test_upload_partial_marks_partial(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    driver_id = "driver.pl.cogs.labour.direct.headcount"
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={"driver_id": driver_id, "values": {"Y0": 45}},
    )
    assert resp.status_code == 200
    assert resp.json()["current_status"] == "partial"


def test_upload_static_parameters_marks_complete(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice_id = "bs.nfp.borrowings.term_loan_repayments"
    _put_method(client, project_id, voice_id, "term_loan_amortization_linear")

    driver_id = f"driver.{voice_id}.initial_principal"
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "static_parameters": {
                "initial_principal": 5000,
                "term_years": 7,
                "rate": 0.045,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_status"] == "complete"
    assert body["static_parameters"]["term_years"] == 7
    assert body["values"] is None


def test_upload_rejects_unknown_year_for_scalar(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": "driver.pl.cogs.labour.direct.headcount",
            "values": {"Y0": 45, "Y1": 50},
        },
    )
    assert resp.status_code == 422
    assert "Y1" in resp.json()["detail"]


def test_upload_rejects_static_payload_on_scalar(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": "driver.pl.cogs.labour.direct.headcount",
            "static_parameters": {"foo": 1},
        },
    )
    assert resp.status_code == 422


def test_upload_rejects_values_on_static_parameters(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice_id = "bs.nfp.borrowings.term_loan_repayments"
    _put_method(client, project_id, voice_id, "term_loan_amortization_linear")

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": f"driver.{voice_id}.initial_principal",
            "values": {"Y0": 1000},
        },
    )
    assert resp.status_code == 422


def test_upload_rejects_unrequired_driver_id(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": "driver.totally.unrelated.thing",
            "values": {"Y0": 1},
        },
    )
    assert resp.status_code == 422


def test_upload_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.post(
        "/api/projects/nope/drivers/upload",
        json={"driver_id": "driver.x.y", "values": {"Y0": 1}},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /drivers/{driver_id}/skip
# ---------------------------------------------------------------------------


def test_skip_marks_skipped_and_can_be_unskipped_by_upload(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    _put_method(client, project_id, "pl.cogs.labour.direct", "headcount_unit_cost")

    driver_id = "driver.pl.cogs.labour.direct.headcount"
    resp = client.patch(
        f"/api/projects/{project_id}/drivers/{driver_id}/skip"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_status"] == "skipped"

    summary = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()["summary"]
    assert summary["skipped"] >= 1

    # Re-uploading flips status back to active/complete.
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={"driver_id": driver_id, "values": {"Y-1": 40, "Y0": 42}},
    )
    assert resp.status_code == 200
    assert resp.json()["current_status"] == "complete"


def test_skip_404_for_unrequired_driver(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)

    resp = client.patch(
        f"/api/projects/{project_id}/drivers/driver.x.y/skip"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Unit test for the pure compatibility function
# ---------------------------------------------------------------------------


def test_compute_required_drivers_aggregates_across_voices(loaded_registries):
    configs = [
        MethodConfig(
            project_id="p1",
            voice_id="pl.cogs.labour.direct",
            method_id="headcount_unit_cost",
            method_technical_code="M_OPD_006",
            is_default=True,
            source="registry_default",
        ),
        MethodConfig(
            project_id="p1",
            voice_id="pl.opex.sm.personnel",
            method_id="headcount_unit_cost",
            method_technical_code="M_OPD_006",
            is_default=True,
            source="registry_default",
        ),
        MethodConfig(
            project_id="p1",
            voice_id="pl.rev.gross.subscription",
            method_id="arr_bridge",
            method_technical_code="M_BRG_002",
            is_default=False,
            source="user_override",
        ),
    ]
    result = compute_required_drivers(configs, loaded_registries)
    by_id = {r.driver_id: r for r in result}

    # Voice-scoped drivers stay distinct per voice.
    assert "driver.pl.cogs.labour.direct.headcount" in by_id
    assert "driver.pl.opex.sm.personnel.headcount" in by_id

    # SaaS literal drivers are not voice-scoped.
    assert "driver.saas.new_arr" in by_id
    assert by_id["driver.saas.new_arr"].required_by_methods == ["arr_bridge"]
    assert by_id["driver.saas.new_arr"].required_for_voices == [
        "pl.rev.gross.subscription"
    ]
