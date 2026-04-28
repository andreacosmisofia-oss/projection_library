"""Integration tests for the M10 snapshot endpoints.

Covers ``POST /run`` (E0-ready run + E0-blocked run) and the two read
endpoints (``GET /snapshot/latest`` + ``GET /snapshots``). Seeding is
shared with ``test_engine_executor`` in spirit but duplicated here to
keep route-level tests self-contained — the engine tests already
exercise the same fixtures from the unit-test side.
"""

from __future__ import annotations

import time
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import (
    Balance,
    Mapping,
    MethodConfig,
    Project,
    RawVoice,
    Snapshot,
    SnapshotValue,
)


# ---------------------------------------------------------------------------
# Test bootstrap
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


# ---------------------------------------------------------------------------
# Seed helpers (mirrors test_engine_executor seeding)
# ---------------------------------------------------------------------------


def _seed_project(db: Session, *, sector_pack: str = "industrial") -> str:
    project = Project(
        name="Acme Pilot",
        sector_pack=sector_pack,
        currency="EUR",
        horizon_years=3,
    )
    db.add(project)
    db.flush()
    return project.id


def _seed_critical_voices(
    db: Session,
    project_id: str,
    *,
    years: tuple[str, ...] = ("Y0",),
) -> None:
    balance = Balance(
        project_id=project_id,
        source_type="gestionale",
        raw_filename="seed.xlsx",
        years_present=list(years),
        voice_count=3 * len(years),
    )
    db.add(balance)
    db.flush()

    voices = (
        ("Ricavi", "PL", "pl.rev.net", 1000.0),
        ("Cassa", "SP", "bs.nfp.cash", 200.0),
        ("Patrimonio Netto", "SP", "bs.equity.total_close", 500.0),
    )
    for label, section, voice_id, base in voices:
        db.add(
            Mapping(
                project_id=project_id,
                voice_user_label=label,
                voice_user_section=section,
                voice_id=voice_id,
                confidence=1.0,
                confirmed_by_user=True,
            )
        )
        for idx, year in enumerate(years):
            db.add(
                RawVoice(
                    balance_id=balance.id,
                    voice_user_label=label,
                    voice_user_section=section,
                    year=year,
                    amount=base + idx,
                    lfl_flag=True,
                )
            )
    db.flush()


def _seed_method_config(db: Session, project_id: str) -> None:
    db.add(
        MethodConfig(
            project_id=project_id,
            voice_id="pl.rev.net",
            method_id="growth",
            source="user_override",
            is_default=False,
        )
    )
    db.flush()


def _seed_e0_ready(factory: sessionmaker) -> str:
    db = factory()
    try:
        project_id = _seed_project(db)
        _seed_critical_voices(db, project_id, years=("Y-1", "Y0"))
        _seed_method_config(db, project_id)
        db.commit()
        return project_id
    finally:
        db.close()


def _seed_project_only(factory: sessionmaker) -> str:
    """Project with no critical voices and no method configs — E0 will block."""
    db = factory()
    try:
        project_id = _seed_project(db)
        db.commit()
        return project_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /run
# ---------------------------------------------------------------------------


def test_run_returns_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.post("/api/projects/does-not-exist/run")
    assert resp.status_code == 404


def test_run_returns_404_for_soft_deleted_project(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)
    db = factory()
    try:
        project = db.get(Project, project_id)
        from datetime import datetime, timezone

        project.deleted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/projects/{project_id}/run")
    assert resp.status_code == 404


def test_run_returns_422_when_e0_blocks(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_project_only(factory)

    resp = client.post(f"/api/projects/{project_id}/run")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "E0 validation block" in detail


def test_run_creates_snapshot_and_values(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.post(f"/api/projects/{project_id}/run")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["project_id"] == project_id
    assert body["status"] == "success"
    assert body["duration_ms"] >= 0
    assert body["error_message"] is None
    summary = body["validation_summary"]
    # Canonical four severities always present
    assert set(summary.keys()) == {"block", "error", "warning", "info"}
    # Successful runs have no block issues by construction
    assert summary["block"] == 0

    # Verify persistence: one snapshot, with normalised value rows.
    db = factory()
    try:
        snapshots = db.execute(
            select(Snapshot).where(Snapshot.project_id == project_id)
        ).scalars().all()
        assert len(snapshots) == 1

        rows = db.execute(
            select(SnapshotValue).where(
                SnapshotValue.snapshot_id == snapshots[0].id
            )
        ).scalars().all()
        # Three critical voices × two historical years ("Y-1", "Y0") at minimum
        by_voice = {(r.voice_id, r.year) for r in rows}
        for voice_id in ("pl.rev.net", "bs.nfp.cash", "bs.equity.total_close"):
            for year in ("Y-1", "Y0"):
                assert (voice_id, year) in by_voice

        # Historical rows: base_value None, override_delta 0.0
        for r in rows:
            if r.year in {"Y-1", "Y0"}:
                assert r.base_value is None
                assert r.override_delta == 0.0
                assert r.value is not None
    finally:
        db.close()


def test_run_appends_snapshot_history(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    first = client.post(f"/api/projects/{project_id}/run")
    assert first.status_code == 201
    # Sleep beyond SQLite's datetime resolution so the second row sorts after
    # the first regardless of clock granularity.
    time.sleep(0.01)
    second = client.post(f"/api/projects/{project_id}/run")
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    db = factory()
    try:
        count = len(
            db.execute(
                select(Snapshot).where(Snapshot.project_id == project_id)
            ).scalars().all()
        )
        assert count == 2
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /snapshot/latest
# ---------------------------------------------------------------------------


def test_latest_returns_404_when_no_snapshot(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.get(f"/api/projects/{project_id}/snapshot/latest")
    assert resp.status_code == 404


def test_latest_returns_most_recent_with_values(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    first = client.post(f"/api/projects/{project_id}/run").json()
    time.sleep(0.01)
    second = client.post(f"/api/projects/{project_id}/run").json()

    resp = client.get(f"/api/projects/{project_id}/snapshot/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == second["id"]
    assert body["id"] != first["id"]

    # Values payload populated and shaped correctly
    assert isinstance(body["values"], list)
    assert len(body["values"]) > 0
    sample = body["values"][0]
    assert set(sample.keys()) == {
        "voice_id",
        "year",
        "value",
        "base_value",
        "override_delta",
    }


def test_latest_returns_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/does-not-exist/snapshot/latest")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /snapshots
# ---------------------------------------------------------------------------


def test_list_returns_empty_when_no_runs(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.get(f"/api/projects/{project_id}/snapshots")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"project_id": project_id, "count": 0, "items": []}


def test_list_caps_at_five_and_orders_desc(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    created_ids: list[str] = []
    for _ in range(7):
        resp = client.post(f"/api/projects/{project_id}/run")
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])
        time.sleep(0.01)

    resp = client.get(f"/api/projects/{project_id}/snapshots")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 5
    returned_ids = [item["id"] for item in body["items"]]
    # Most recent first; the last 5 created should match in reverse order.
    assert returned_ids == list(reversed(created_ids[-5:]))

    # No values key in the summary payload
    for item in body["items"]:
        assert "values" not in item


def test_list_respects_explicit_limit(client_and_factory):
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    for _ in range(3):
        client.post(f"/api/projects/{project_id}/run")
        time.sleep(0.01)

    resp = client.get(f"/api/projects/{project_id}/snapshots?limit=2")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_list_returns_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/does-not-exist/snapshots")
    assert resp.status_code == 404
