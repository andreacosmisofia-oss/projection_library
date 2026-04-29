"""Integration tests for the M8 assumption endpoints.

Exercises POST/GET/PATCH/POST-curve under
``/api/projects/{id}/assumptions`` against an in-memory SQLite. The
fixtures seed a minimal project with one ``method_configs`` row and
one ``historical_kpis`` AGG row so the populator has something to
read.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import (
    Assumption,
    HistoricalKPI,
    MethodConfig,
    Project,
)


def _make_factory() -> tuple[object, sessionmaker]:
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


def _seed_growth_voice(
    factory: sessionmaker,
    *,
    voice_id: str = "pl.rev.gross.product_sales",
    method_id: str = "historical_avg_growth",
    kpi_value: float | None = 0.10,
) -> str:
    """Seed a project with one method_config + matching KPI AGG row.

    ``method_id`` defaults to ``historical_avg_growth`` because it has
    a populated ``default_kpi_example`` and a single assumption name
    (``growth_rate``) — the canonical happy path.
    """
    db: Session = factory()
    try:
        project = Project(
            name="Acme M8",
            sector_pack="industrial",
            currency="EUR",
            horizon_years=3,
        )
        db.add(project)
        db.flush()

        db.add(
            MethodConfig(
                project_id=project.id,
                voice_id=voice_id,
                method_id=method_id,
                source="user_override",
                is_default=False,
            )
        )

        # AGG row matches the resolved template for historical_avg_growth:
        # kpi.growth.<voice>_yoy → kpi.growth.pl.rev.gross.product_sales_yoy
        if kpi_value is not None:
            db.add(
                HistoricalKPI(
                    project_id=project.id,
                    kpi_id=f"kpi.growth.{voice_id}_yoy",
                    year="AGG",
                    value=None,
                    default_for_projection=kpi_value,
                    calibration_score=0.83,
                )
            )

        db.commit()
        return project.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /populate-defaults
# ---------------------------------------------------------------------------


def test_populate_defaults_seeds_three_years(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["populated"] == 3
    assert body["kpi_default_used"] == 3
    assert body["fallback_used"] == 0

    db = factory()
    try:
        rows = db.execute(
            select(Assumption).where(Assumption.project_id == project_id)
        ).scalars().all()
        assert len(rows) == 3
        assert {r.year for r in rows} == {"Y1", "Y2", "Y3"}
        assert all(r.source == "default_kpi" for r in rows)
        assert all(r.value == pytest.approx(0.10) for r in rows)
        assert all(
            r.default_kpi_id
            == "kpi.growth.pl.rev.gross.product_sales_yoy"
            for r in rows
        )
    finally:
        db.close()


def test_populate_defaults_fallback_when_kpi_missing(
    client_and_factory,
) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory, kpi_value=None)

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] == 3
    assert body["kpi_default_used"] == 0

    db = factory()
    try:
        rows = db.execute(
            select(Assumption).where(Assumption.project_id == project_id)
        ).scalars().all()
        assert all(r.source == "fallback" for r in rows)
        assert all(r.value == 0.0 for r in rows)
    finally:
        db.close()


def test_populate_defaults_preserves_user_input(
    client_and_factory,
) -> None:
    """Re-running populate must not clobber rows the user has edited."""
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)

    # First populate seeds Y1/Y2/Y3 = 0.10
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # User edits Y2 to 0.25
    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/Y2",
        json={"value": 0.25},
    )
    assert resp.status_code == 200

    # Re-populate
    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    assert resp.json()["user_input_preserved"] >= 1

    db = factory()
    try:
        y2 = db.execute(
            select(Assumption).where(
                Assumption.project_id == project_id,
                Assumption.year == "Y2",
            )
        ).scalars().one()
        assert y2.value == pytest.approx(0.25)
        assert y2.source == "user_input"
        assert y2.user_modified_at is not None
    finally:
        db.close()


def test_populate_defaults_drops_orphan_pairs(client_and_factory) -> None:
    """Switching method on a voice purges the old assumption rows."""
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    # Swap method on the voice (M6 PUT would do this; we mutate
    # method_configs directly to keep the test focused on M8).
    db = factory()
    try:
        config = db.execute(
            select(MethodConfig).where(
                MethodConfig.project_id == project_id
            )
        ).scalars().one()
        config.method_id = "flat"
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/populate-defaults"
    )
    assert resp.status_code == 200
    body = resp.json()
    # One orphan pair (voice, method) → three rows (Y1/Y2/Y3) deleted.
    assert body["pairs_deleted"] == 3

    db = factory()
    try:
        rows = db.execute(
            select(Assumption).where(Assumption.project_id == project_id)
        ).scalars().all()
        # `flat` references no assumption in its formula, so the
        # populator writes nothing for the new method either.
        assert rows == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /assumptions
# ---------------------------------------------------------------------------


def test_get_returns_collapsed_triplet(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.get(f"/api/projects/{project_id}/assumptions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["voice_id"] == "pl.rev.gross.product_sales"
    assert item["method_id"] == "historical_avg_growth"
    assert item["assumption_name"] == "growth_rate"
    assert item["values"] == {"Y1": 0.10, "Y2": 0.10, "Y3": 0.10}
    assert item["source"] == "default_kpi"
    assert item["calibration_score"] == pytest.approx(0.83)
    assert item["validation_status"] == "ok"
    assert item["curve_type"] == "flat"


def test_get_returns_404_for_missing_project(client_and_factory) -> None:
    client, _ = client_and_factory
    resp = client.get("/api/projects/does-not-exist/assumptions")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /assumptions/{voice}/{name}/{year}
# ---------------------------------------------------------------------------


def test_patch_flips_source_to_user_input(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/Y1",
        json={"value": 0.42},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["values"]["Y1"] == pytest.approx(0.42)
    assert body["source"] == "user_input"
    assert body["user_modified_at"] is not None


def test_patch_invalid_year_returns_422(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/Y5",
        json={"value": 0.42},
    )
    assert resp.status_code == 422


def test_patch_unknown_assumption_returns_404(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/nonexistent/Y1",
        json={"value": 0.42},
    )
    assert resp.status_code == 404


def test_patch_voice_without_method_returns_422(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.patch(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.unknown.voice/growth_rate/Y1",
        json={"value": 0.42},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /assumptions/{voice}/{name}/curve
# ---------------------------------------------------------------------------


def test_curve_linear_drift_interpolates_y2(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/curve",
        json={"curve_type": "linear_drift", "y1": 0.10, "y3": 0.05},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["curve_type"] == "linear_drift"
    assert body["values"]["Y1"] == pytest.approx(0.10)
    assert body["values"]["Y2"] == pytest.approx(0.075)
    assert body["values"]["Y3"] == pytest.approx(0.05)
    assert body["source"] == "user_input"


def test_curve_flat_overwrites_all_years(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/curve",
        json={"curve_type": "flat", "y1": 0.20},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["values"] == {"Y1": 0.20, "Y2": 0.20, "Y3": 0.20}
    assert body["curve_type"] == "flat"


def test_curve_linear_drift_missing_y3_returns_422(
    client_and_factory,
) -> None:
    client, factory = client_and_factory
    project_id = _seed_growth_voice(factory)
    client.post(f"/api/projects/{project_id}/assumptions/populate-defaults")

    resp = client.post(
        f"/api/projects/{project_id}/assumptions/"
        f"pl.rev.gross.product_sales/growth_rate/curve",
        json={"curve_type": "linear_drift", "y1": 0.10},
    )
    assert resp.status_code == 422
