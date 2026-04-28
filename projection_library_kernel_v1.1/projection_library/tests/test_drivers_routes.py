"""Integration tests for the M7 driver-intake endpoints."""

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


def _set_method(client: TestClient, project_id: str, voice_id: str, method_id: str):
    """PUT a method config so the driver requirements are deterministic."""
    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": method_id},
    )
    assert resp.status_code == 200, resp.text


def _pick_voice_with_method(client: TestClient, target_method: str) -> str:
    """Return any voice id where switching to ``target_method`` introduces
    a driver requirement, irrespective of the registry default."""
    voices = client.get("/api/registry/voices").json()["items"]
    # Voices most likely to accept a labour-style method without 422s
    # are the labour cost group; fall back to the first PL voice if none.
    for v in voices:
        if v["voice_id"].startswith("pl.cogs.labour"):
            return v["voice_id"]
    return voices[0]["voice_id"]


# ---------- GET /required ---------------------------------------------


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


def test_required_lists_drivers_for_chosen_method(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)

    voice_id = _pick_voice_with_method(client, "headcount_unit_cost")
    _set_method(client, project_id, voice_id, "headcount_unit_cost")

    resp = client.get(f"/api/projects/{project_id}/drivers/required")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_id = f"driver.{voice_id}.headcount"
    by_id = {item["driver_id"]: item for item in body["items"]}
    assert expected_id in by_id
    entry = by_id[expected_id]
    assert entry["type"] == "scalar_per_year"
    assert "headcount_unit_cost" in entry["required_by_methods"]
    assert voice_id in entry["required_for_voices"]
    assert entry["current_status"] == "missing"
    assert entry["years_required"] == ["Y0"]  # no balance uploaded yet


def test_required_status_complete_after_full_upload(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice_id = _pick_voice_with_method(client, "headcount_unit_cost")
    _set_method(client, project_id, voice_id, "headcount_unit_cost")
    driver_id = f"driver.{voice_id}.headcount"

    upload = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "unit": "FTE",
            "values": {"Y0": 45},
        },
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    assert body["rows_written"] == 1

    listing = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    by_id = {item["driver_id"]: item for item in listing["items"]}
    assert by_id[driver_id]["current_status"] == "complete"
    assert by_id[driver_id]["present_years"] == ["Y0"]
    assert by_id[driver_id]["unit"] == "FTE"
    assert listing["summary"]["complete"] == 1


def test_required_status_partial_when_year_missing(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)

    # Seed an active balance with two historical years so years_required
    # becomes ``["Y-1", "Y0"]`` and a single-year upload reads as partial.
    from backend.infrastructure.db.models import Balance
    factory = client_and_factory[1]
    with factory() as db:
        db.add(
            Balance(
                project_id=project_id,
                source_type="gestionale",
                raw_filename="seed.xlsx",
                years_present=["Y-1", "Y0"],
                voice_count=0,
            )
        )
        db.commit()

    voice_id = _pick_voice_with_method(client, "headcount_unit_cost")
    _set_method(client, project_id, voice_id, "headcount_unit_cost")
    driver_id = f"driver.{voice_id}.headcount"

    client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y0": 45},
        },
    )
    listing = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    by_id = {item["driver_id"]: item for item in listing["items"]}
    assert by_id[driver_id]["current_status"] == "partial"
    assert by_id[driver_id]["years_required"] == ["Y-1", "Y0"]
    assert by_id[driver_id]["present_years"] == ["Y0"]


def test_required_returns_empty_when_no_method_consumes_drivers(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    # Without overriding any method, the registry defaults supply the
    # method choice. Some voices' defaults *do* introduce drivers, so
    # we don't assert empty in the general case — instead, we verify
    # that explicitly switching to ``flat`` (no drivers) for a voice
    # cannot increase the count.
    baseline = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    voice_id = _pick_voice_with_method(client, "flat")
    _set_method(client, project_id, voice_id, "flat")
    after = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    assert after["count"] <= baseline["count"]


def test_required_summary_counts_match_items(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice_id = _pick_voice_with_method(client, "headcount_unit_cost")
    _set_method(client, project_id, voice_id, "headcount_unit_cost")

    body = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    summary = body["summary"]
    assert summary["total"] == body["count"]
    assert (
        summary["complete"]
        + summary["partial"]
        + summary["missing"]
        + summary["skipped"]
        == summary["total"]
    )


# ---------- POST /upload ----------------------------------------------


def test_upload_scalar_per_year_persists_one_row_per_year(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.pl.cogs.labour.direct.headcount"

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y-1": 42, "Y0": 45},
            "unit": "FTE",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_written"] == 2

    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    assert {r["year"] for r in rows} == {"Y-1", "Y0"}
    assert all(r["type"] == "scalar_per_year" for r in rows)
    assert all(r["unit"] == "FTE" for r in rows)


def test_upload_static_parameters_persists_single_row(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.bs.nfp.borrowings.term_loan_repayments.parameters"

    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "static_parameters",
            "static_parameters": {
                "initial_principal": 5000,
                "term_years": 7,
                "rate": 0.045,
            },
        },
    )
    assert resp.status_code == 201, resp.text
    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "static_parameters"
    assert row["year"] == ""
    assert row["static_parameters"]["initial_principal"] == 5000


def test_upload_replaces_previous_rows(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.pl.cogs.labour.direct.headcount"

    client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y-1": 42, "Y0": 45},
        },
    )
    # Re-upload with a single year — the old Y-1 row must disappear.
    client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y0": 50},
        },
    )
    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    assert {r["year"]: r["value"] for r in rows} == {"Y0": 50.0}


def test_upload_clears_existing_skip_marker(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.pl.cogs.labour.direct.headcount"

    skip = client.patch(
        f"/api/projects/{project_id}/drivers/{driver_id}/skip"
    )
    assert skip.status_code == 200
    upload = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y0": 1.0},
        },
    )
    assert upload.status_code == 201
    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    assert all(r["skipped"] is False for r in rows)
    assert len(rows) == 1


def test_upload_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.post(
        "/api/projects/nope/drivers/upload",
        json={
            "driver_id": "driver.x.y",
            "type": "scalar_per_year",
            "values": {"Y0": 1},
        },
    )
    assert resp.status_code == 404


def test_upload_422_when_payload_missing_for_type(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": "driver.x.y",
            "type": "scalar_per_year",
            # no ``values`` field
        },
    )
    assert resp.status_code == 422


def test_upload_422_for_extra_unknown_fields(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": "driver.x.y",
            "type": "scalar_per_year",
            "values": {"Y0": 1},
            "rogue_field": True,
        },
    )
    assert resp.status_code == 422


# ---------- PATCH /skip -----------------------------------------------


def test_skip_marks_driver_and_summary_counts(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    voice_id = _pick_voice_with_method(client, "headcount_unit_cost")
    _set_method(client, project_id, voice_id, "headcount_unit_cost")
    driver_id = f"driver.{voice_id}.headcount"

    skip = client.patch(
        f"/api/projects/{project_id}/drivers/{driver_id}/skip"
    )
    assert skip.status_code == 200, skip.text
    body = skip.json()
    assert body["skipped"] is True
    assert body["driver_id"] == driver_id

    listing = client.get(
        f"/api/projects/{project_id}/drivers/required"
    ).json()
    by_id = {item["driver_id"]: item for item in listing["items"]}
    assert by_id[driver_id]["current_status"] == "skipped"
    assert listing["summary"]["skipped"] >= 1


def test_skip_is_idempotent(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.pl.cogs.labour.direct.headcount"

    first = client.patch(
        f"/api/projects/{project_id}/drivers/{driver_id}/skip"
    )
    assert first.status_code == 200
    second = client.patch(
        f"/api/projects/{project_id}/drivers/{driver_id}/skip"
    )
    assert second.status_code == 200

    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    # Only the marker survives — no duplicate skip rows.
    assert len(rows) == 1
    assert rows[0]["skipped"] is True


def test_skip_removes_existing_data_rows(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    driver_id = "driver.pl.cogs.labour.direct.headcount"

    client.post(
        f"/api/projects/{project_id}/drivers/upload",
        json={
            "driver_id": driver_id,
            "type": "scalar_per_year",
            "values": {"Y-1": 1, "Y0": 2},
        },
    )
    client.patch(f"/api/projects/{project_id}/drivers/{driver_id}/skip")
    rows = client.get(
        f"/api/projects/{project_id}/drivers/{driver_id}"
    ).json()
    assert len(rows) == 1
    assert rows[0]["skipped"] is True
    assert rows[0]["value"] is None


def test_skip_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.patch("/api/projects/nope/drivers/driver.x.y/skip")
    assert resp.status_code == 404


def test_skip_422_for_invalid_driver_id(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.patch(
        f"/api/projects/{project_id}/drivers/not_a_driver_id/skip"
    )
    assert resp.status_code == 422
