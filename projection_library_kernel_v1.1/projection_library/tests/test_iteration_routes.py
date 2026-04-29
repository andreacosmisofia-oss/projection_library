"""Integration tests for the M12 iteration endpoints (Path 9.2 + 9.3).

Covers:

* ``GET /validation-report/latest`` — reads engine-time issues from the
  most recent snapshot;
* ``GET /approximation-log`` — reads the approximation log from the
  most recent snapshot;
* ``PATCH /balance/{bid}/voice/{vid}`` — Path 9.3: updates a raw voice,
  re-validates, re-computes KPIs + quality, and re-runs the engine
  unless validation blocks;
* ``PUT /methods/{voice_id}`` (M6 endpoint) — Path 9.2: re-runs the
  engine iff a snapshot already exists for the project.

Seeding follows the same minimal-but-E0-ready pattern as
``test_snapshots_routes`` and ``test_overrides_routes`` so the engine
runs successfully and produces a snapshot.
"""

from __future__ import annotations

import time
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import (
    Balance,
    HistoricalKPI,
    Mapping,
    MethodConfig,
    Project,
    QualityScore,
    RawVoice,
    Snapshot,
    ValidationReport,
)


# ---------------------------------------------------------------------------
# Bootstrap
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


def _seed_e0_ready(factory: sessionmaker) -> tuple[str, str]:
    """Return ``(project_id, balance_id)`` ready for engine + M5 cascade.

    Covers all five ``CRITICAL_VOICE_GROUPS`` from the M5 historical
    validator (DI_002), so :func:`iterate_historical_modify` produces a
    ``can_proceed=True`` report and the engine actually runs.
    """
    db = factory()
    try:
        project = Project(
            name="Acme Pilot",
            sector_pack="industrial",
            currency="EUR",
            perimeter="standalone",
            horizon_years=3,
        )
        db.add(project)
        db.flush()
        project_id = project.id

        balance = Balance(
            project_id=project_id,
            source_type="gestionale",
            raw_filename="seed.xlsx",
            years_present=["Y-1", "Y0"],
            voice_count=10,
        )
        db.add(balance)
        db.flush()
        balance_id = balance.id

        voices = (
            ("Ricavi", "PL", "pl.rev.net", 1000.0),
            ("Costi materie", "PL", "pl.cogs.total", -300.0),
            ("Cassa", "SP", "bs.nfp.cash", 200.0),
            ("Patrimonio Netto", "SP", "bs.equity.total_close", 500.0),
            ("Crediti commerciali", "SP", "bs.nwc.ar.close", 150.0),
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
            for idx, year in enumerate(("Y-1", "Y0")):
                db.add(
                    RawVoice(
                        balance_id=balance_id,
                        voice_user_label=label,
                        voice_user_section=section,
                        year=year,
                        amount=base + idx,
                        lfl_flag=True,
                    )
                )
        db.add(
            MethodConfig(
                project_id=project_id,
                voice_id="pl.rev.net",
                method_id="growth",
                source="user_override",
                is_default=False,
            )
        )
        db.commit()
        return project_id, balance_id
    finally:
        db.close()


def _get_raw_voice_id(
    factory: sessionmaker, balance_id: str, label: str, year: str
) -> str:
    db = factory()
    try:
        row = db.execute(
            select(RawVoice).where(
                RawVoice.balance_id == balance_id,
                RawVoice.voice_user_label == label,
                RawVoice.year == year,
            )
        ).scalars().first()
        assert row is not None
        return row.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /validation-report/latest
# ---------------------------------------------------------------------------


def test_validation_report_latest_404_when_no_snapshot(client_and_factory):
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)
    resp = client.get(f"/api/projects/{project_id}/validation-report/latest")
    assert resp.status_code == 404


def test_validation_report_latest_404_for_missing_project(client_and_factory):
    client, _ = client_and_factory
    resp = client.get("/api/projects/missing/validation-report/latest")
    assert resp.status_code == 404


def test_validation_report_latest_returns_engine_summary(client_and_factory):
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)

    run_resp = client.post(f"/api/projects/{project_id}/run")
    assert run_resp.status_code == 201, run_resp.text
    snapshot_id = run_resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/validation-report/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["snapshot_id"] == snapshot_id
    assert set(body["summary"].keys()) == {"block", "error", "warning", "info"}
    assert isinstance(body["issues"], list)
    assert body["status"] in {"success", "partial", "failed"}


# ---------------------------------------------------------------------------
# GET /approximation-log
# ---------------------------------------------------------------------------


def test_approximation_log_404_when_no_snapshot(client_and_factory):
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)
    resp = client.get(f"/api/projects/{project_id}/approximation-log")
    assert resp.status_code == 404


def test_approximation_log_returns_log_after_run(client_and_factory):
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)

    run_resp = client.post(f"/api/projects/{project_id}/run")
    assert run_resp.status_code == 201
    snapshot_id = run_resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/approximation-log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["snapshot_id"] == snapshot_id
    assert isinstance(body["approximation_log"], list)


# ---------------------------------------------------------------------------
# PATCH /balance/{bid}/voice/{vid} — Path 9.3
# ---------------------------------------------------------------------------


def test_patch_voice_404_for_missing_balance(client_and_factory):
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)
    resp = client.patch(
        f"/api/projects/{project_id}/balance/missing/voice/whatever",
        json={"year": "Y0", "value": 1.0},
    )
    assert resp.status_code == 404


def test_patch_voice_404_for_missing_raw_voice(client_and_factory):
    client, factory = client_and_factory
    project_id, balance_id = _seed_e0_ready(factory)
    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/voice/missing-id",
        json={"year": "Y0", "value": 1.0},
    )
    assert resp.status_code == 404


def test_patch_voice_updates_raw_amount(client_and_factory):
    client, factory = client_and_factory
    project_id, balance_id = _seed_e0_ready(factory)
    raw_id = _get_raw_voice_id(factory, balance_id, "Ricavi", "Y0")

    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/voice/{raw_id}",
        json={"year": "Y0", "value": 4242.0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balance_id"] == balance_id
    assert body["raw_voice_id"] == raw_id
    assert body["voice_user_label"] == "Ricavi"
    assert body["year"] == "Y0"
    assert body["value"] == 4242.0
    assert body["validation_blocked"] is False

    db = factory()
    try:
        row = db.get(RawVoice, raw_id)
        assert row is not None
        assert row.amount == 4242.0
    finally:
        db.close()


def test_patch_voice_creates_full_cascade(client_and_factory):
    """Path 9.3 acceptance: validation + KPI + quality + snapshot all refreshed."""
    client, factory = client_and_factory
    project_id, balance_id = _seed_e0_ready(factory)
    raw_id = _get_raw_voice_id(factory, balance_id, "Ricavi", "Y0")

    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/voice/{raw_id}",
        json={"year": "Y0", "value": 1234.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshot_id"] is not None
    assert body["engine_block_message"] is None
    assert set(body["validation_summary"].keys()) >= {
        "block",
        "error",
        "warning",
        "info",
    }

    db = factory()
    try:
        # Validation report persisted
        vr = db.execute(
            select(ValidationReport).where(
                ValidationReport.project_id == project_id,
                ValidationReport.phase == "historical",
            )
        ).scalars().first()
        assert vr is not None

        # KPI rows exist (calculator ran)
        kpis = db.execute(
            select(HistoricalKPI).where(HistoricalKPI.project_id == project_id)
        ).scalars().all()
        assert len(kpis) > 0

        # Quality score persisted
        qs = db.execute(
            select(QualityScore).where(QualityScore.project_id == project_id)
        ).scalars().first()
        assert qs is not None

        # Snapshot created
        snap = db.get(Snapshot, body["snapshot_id"])
        assert snap is not None
        assert snap.project_id == project_id
    finally:
        db.close()


def test_patch_voice_creates_row_for_missing_year(client_and_factory):
    """Backfilling Y-2 (no row exists) creates a new RawVoice."""
    client, factory = client_and_factory
    project_id, balance_id = _seed_e0_ready(factory)
    raw_id = _get_raw_voice_id(factory, balance_id, "Ricavi", "Y0")

    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/voice/{raw_id}",
        json={"year": "Y-2", "value": 800.0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["year"] == "Y-2"
    assert body["value"] == 800.0
    # The patch returned the *new* row, not the original Y0 row
    assert body["raw_voice_id"] != raw_id

    db = factory()
    try:
        row = db.execute(
            select(RawVoice).where(
                RawVoice.balance_id == balance_id,
                RawVoice.voice_user_label == "Ricavi",
                RawVoice.year == "Y-2",
            )
        ).scalars().first()
        assert row is not None
        assert row.amount == 800.0
    finally:
        db.close()


def test_patch_voice_blocked_skips_engine_run(client_and_factory):
    """Setting cash to zero triggers DI_002 block (cash missing for Y0)."""
    client, factory = client_and_factory
    project_id, balance_id = _seed_e0_ready(factory)
    cash_raw_id = _get_raw_voice_id(factory, balance_id, "Cassa", "Y0")

    # Delete cash Y0 entirely so DI_002 fires (no Y0 actual on a critical voice).
    db = factory()
    try:
        row = db.get(RawVoice, cash_raw_id)
        assert row is not None
        db.delete(row)
        db.commit()
    finally:
        db.close()

    # Re-fetch a still-existing raw voice to PATCH (any voice triggers cascade).
    rev_raw_id = _get_raw_voice_id(factory, balance_id, "Ricavi", "Y0")
    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/voice/{rev_raw_id}",
        json={"year": "Y0", "value": 1100.0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # DI_002 should fire and block engine
    assert body["validation_blocked"] is True
    assert body["snapshot_id"] is None
    assert body["validation_summary"].get("block", 0) >= 1


# ---------------------------------------------------------------------------
# PUT /methods/{voice_id} — Path 9.2 trigger
# ---------------------------------------------------------------------------


def test_put_method_no_rerun_when_no_snapshot(client_and_factory):
    """M6 contract preserved: PUT before any /run does not auto-trigger."""
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)

    resp = client.put(
        f"/api/projects/{project_id}/methods/pl.rev.net",
        json={"method_id": "cagr_extrapolation"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triggered_snapshot_id"] is None

    db = factory()
    try:
        count = len(
            db.execute(
                select(Snapshot).where(Snapshot.project_id == project_id)
            ).scalars().all()
        )
        assert count == 0
    finally:
        db.close()


def test_put_method_triggers_rerun_when_snapshot_exists(client_and_factory):
    """Path 9.2 acceptance: after a first run, PUT auto-creates a new snapshot."""
    client, factory = client_and_factory
    project_id, _ = _seed_e0_ready(factory)

    first = client.post(f"/api/projects/{project_id}/run")
    assert first.status_code == 201
    first_snapshot_id = first.json()["id"]
    time.sleep(0.01)

    resp = client.put(
        f"/api/projects/{project_id}/methods/pl.rev.net",
        json={"method_id": "cagr_extrapolation"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triggered_snapshot_id"] is not None
    assert body["triggered_snapshot_id"] != first_snapshot_id

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
