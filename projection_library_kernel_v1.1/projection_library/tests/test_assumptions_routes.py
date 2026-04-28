"""Integration tests for the M8 assumption-compilation endpoints."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import (
    Assumption,
    AssumptionCurveConfig,
    Balance,
    HistoricalKPI,
)


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


def _set_method(
    client: TestClient, project_id: str, voice_id: str, method_id: str
) -> None:
    resp = client.put(
        f"/api/projects/{project_id}/methods/{voice_id}",
        json={"method_id": method_id},
    )
    assert resp.status_code == 200, resp.text


def _seed_kpi_agg(
    factory,
    project_id: str,
    kpi_id: str,
    default: float,
    calibration: float = 0.85,
) -> None:
    """Insert one ``year='AGG'`` row so populate-defaults can pull it."""
    from datetime import datetime, timezone

    with factory() as db:
        db.add(
            HistoricalKPI(
                project_id=project_id,
                kpi_id=kpi_id,
                year="AGG",
                value=None,
                not_computable_reason=None,
                default_for_projection=default,
                calibration_score=calibration,
                lfl_warning=False,
                computed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()


# ---------- 404 / project-not-found ------------------------------------


def test_populate_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.post(
        "/api/projects/missing-project/assumptions/populate-defaults"
    )
    assert resp.status_code == 404


def test_get_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/missing-project/assumptions")
    assert resp.status_code == 404


# ---------- POST /populate-defaults ------------------------------------


def test_populate_writes_three_years_per_assumption(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    # Use ``dividend_payout_ratio`` because (a) its formula has one
    # assumption (``payout``), (b) its default_kpi_example is a literal
    # KPI we can seed directly. We attach it to ``bs.equity.dividends``.
    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.30, 0.85)

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At least the three-row triple for our deliberately-set assumption.
    assert body["populated"] >= 3
    assert body["preserved_user_input"] == 0

    # DB inspection: verify the three (Y1/Y2/Y3) rows exist.
    with factory() as db:
        rows = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == project_id,
                Assumption.voice_id == voice,
                Assumption.method_id == "dividend_payout_ratio",
                Assumption.assumption_name == "payout",
            )
            .all()
        )
    years = {r.year for r in rows}
    assert years == {"Y1", "Y2", "Y3"}
    assert all(r.value == 0.30 for r in rows)
    assert all(r.source == "default_kpi" for r in rows)
    assert all(r.calibration_score == 0.85 for r in rows)


def test_populate_is_idempotent_and_preserves_user_input(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.30)

    # Seed the defaults.
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # User overrides Y1.
    patch = client.patch(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/Y1",
        json={"value": 0.55},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["source"] == "user_input"

    # Populate again — Y1 user_input must be preserved, Y2/Y3 refreshed.
    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preserved_user_input"] >= 1

    listing = client.get(
        f"/api/projects/{project_id}/assumptions"
    ).json()
    payout_entry = next(
        e for e in listing["items"] if e["assumption_name"] == "payout"
    )
    assert payout_entry["values"]["Y1"] == 0.55
    assert payout_entry["source"]["Y1"] == "user_input"
    assert payout_entry["values"]["Y2"] == 0.30
    assert payout_entry["source"]["Y2"] == "default_kpi"


def test_populate_falls_back_to_zero_when_no_kpi(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    # No KPI seeded → fallback path with value=0.0 on the payout rows.
    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] >= 3

    with factory() as db:
        rows = (
            db.query(Assumption)
            .filter(
                Assumption.project_id == project_id,
                Assumption.voice_id == voice,
                Assumption.assumption_name == "payout",
            )
            .all()
        )
    assert all(r.value == 0.0 for r in rows)
    assert all(r.source == "fallback" for r in rows)


# ---------- GET / ------------------------------------------------------


def test_get_returns_pivoted_entries(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.get(f"/api/projects/{project_id}/assumptions")
    assert resp.status_code == 200
    body = resp.json()
    payout_entry = next(
        e for e in body["items"] if e["assumption_name"] == "payout"
    )
    assert payout_entry["voice_id"] == voice
    assert payout_entry["method_id"] == "dividend_payout_ratio"
    assert payout_entry["values"] == {"Y1": 0.25, "Y2": 0.25, "Y3": 0.25}
    assert payout_entry["validation_range"] == [0.0, 1.0]
    assert payout_entry["curve_type"] == "flat"


def test_get_filter_by_voice(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.get(
        f"/api/projects/{project_id}/assumptions",
        params={"voice_id": voice},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(e["voice_id"] == voice for e in body["items"])


# ---------- PATCH ------------------------------------------------------


def test_patch_updates_value_and_marks_user_input(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/Y2",
        json={"value": 0.40},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 0.40
    assert body["source"] == "user_input"
    assert body["validation_status"] == "ok"
    assert body["user_modified_at"] is not None


def test_patch_out_of_range_returns_warning_not_block(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # ``payout`` heuristic range is (0.0, 1.0). 2.5 is outside but the
    # endpoint must still 200 — warnings are non-blocking.
    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/Y1",
        json={"value": 2.5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 2.5
    assert body["validation_status"] == "warning_range"


def test_patch_404_when_assumption_does_not_exist(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/some.voice/some_name/Y1",
        json={"value": 0.0},
    )
    assert resp.status_code == 404


def test_patch_invalid_year_returns_422(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")
    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/Y4",
        json={"value": 0.10},
    )
    assert resp.status_code == 422


# ---------- POST /curve ------------------------------------------------


def test_curve_linear_drift_interpolates_y2(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)

    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/curve",
        json={"curve_type": "linear_drift", "y1": 0.10, "y3": 0.40},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["values"]["Y1"] == pytest.approx(0.10)
    assert body["values"]["Y2"] == pytest.approx(0.25)
    assert body["values"]["Y3"] == pytest.approx(0.40)
    assert body["curve_type"] == "linear_drift"

    # Curve config persisted.
    with factory() as db:
        curve = (
            db.query(AssumptionCurveConfig)
            .filter(
                AssumptionCurveConfig.project_id == project_id,
                AssumptionCurveConfig.voice_id == voice,
                AssumptionCurveConfig.assumption_name == "payout",
            )
            .one()
        )
        assert curve.curve_type == "linear_drift"


def test_curve_custom_passes_through_values(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/curve",
        json={
            "curve_type": "custom",
            "values": {"Y1": 0.10, "Y2": 0.30, "Y3": 0.05},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["values"] == {"Y1": 0.10, "Y2": 0.30, "Y3": 0.05}


def test_curve_validation_failure_returns_422(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    voice = "bs.equity.capital.dividends_paid"
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # Linear drift requires both y1 and y3 — missing y3 → 422 from
    # Pydantic before the route body even runs.
    resp = client.post(
        f"/api/projects/{project_id}/assumptions/{voice}/payout/curve",
        json={"curve_type": "linear_drift", "y1": 0.10},
    )
    assert resp.status_code == 422


# ---------- Method swap rebuilds defaults ------------------------------


def test_populate_after_method_change_drops_stale_assumptions(
    client_and_factory,
):
    client, factory = client_and_factory
    project_id = _create_project(client)
    voice = "bs.equity.capital.dividends_paid"

    # First method: dividend_payout_ratio → assumption ``payout``.
    _set_method(client, project_id, voice, "dividend_payout_ratio")
    _seed_kpi_agg(factory, project_id, "kpi.equity.payout_ratio", 0.25)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # Switch to dividend_per_share → assumption ``dps`` (different name).
    _set_method(client, project_id, voice, "dividend_per_share")
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    listing = client.get(
        f"/api/projects/{project_id}/assumptions",
        params={"voice_id": voice},
    ).json()
    names = {e["assumption_name"] for e in listing["items"]}
    assert "dps" in names
    assert "payout" not in names
