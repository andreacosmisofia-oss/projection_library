"""Integration tests for the M13 demo loader.

Exercises ``POST /api/demo/load-sample`` end-to-end: the bundled
tier2 sample is read, parsed, mapped, and run through the engine in a
single request. The test relies on the real registry lifespan so the
mapping table is validated against the live ``voice_registry``.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.domain.demo import SAMPLE_MAPPINGS
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


def test_load_sample_creates_project_balance_mappings_and_snapshot(
    client_and_factory,
):
    client, factory = client_and_factory

    resp = client.post("/api/demo/load-sample")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["project_id"]
    assert body["snapshot_id"]
    assert body["balance_id"]
    assert body["voice_count"] > 0
    assert body["mapping_count"] == len(SAMPLE_MAPPINGS)
    assert body["method_config_count"] >= 1

    db = factory()
    try:
        project = db.get(Project, body["project_id"])
        assert project is not None
        assert project.sector_pack == "industrial"
        assert project.horizon_years == 3

        balance = db.get(Balance, body["balance_id"])
        assert balance is not None
        assert balance.project_id == project.id
        assert "Y0" in balance.years_present

        raw_voice_count = db.execute(
            select(func.count(RawVoice.id)).where(
                RawVoice.balance_id == balance.id
            )
        ).scalar_one()
        assert raw_voice_count > 0

        mappings = db.execute(
            select(Mapping).where(Mapping.project_id == project.id)
        ).scalars().all()
        assert len(mappings) == len(SAMPLE_MAPPINGS)
        assert all(m.confirmed_by_user for m in mappings)

        method_count = db.execute(
            select(func.count(MethodConfig.id)).where(
                MethodConfig.project_id == project.id
            )
        ).scalar_one()
        assert method_count >= 1

        snapshot = db.get(Snapshot, body["snapshot_id"])
        assert snapshot is not None
        assert snapshot.status == "success"
        assert snapshot.project_id == project.id

        snapshot_values = db.execute(
            select(SnapshotValue).where(
                SnapshotValue.snapshot_id == snapshot.id
            )
        ).scalars().all()
        assert len(snapshot_values) > 0

        # End-to-end check: at least one projection year must be present
        # (i.e. the engine actually ran the year loop).
        projection_years = {sv.year for sv in snapshot_values} & {
            "Y1",
            "Y2",
            "Y3",
        }
        assert projection_years, (
            "expected at least one projection year in snapshot_values, "
            f"got years={sorted({sv.year for sv in snapshot_values})}"
        )

        # And at least one revenue voice must carry a Y0 actual: that's
        # what made E0 happy.
        rev_y0 = [
            sv
            for sv in snapshot_values
            if sv.voice_id.startswith("pl.rev") and sv.year == "Y0"
        ]
        assert rev_y0
    finally:
        db.close()


def test_sample_mappings_resolve_to_known_voice_ids(client_and_factory):
    """Guard rail: every hardcoded mapping target must exist in the
    live voice_registry. If someone renames a voice in the YAML, this
    test fails before the loader silently ships a broken demo."""
    client, _ = client_and_factory  # triggers lifespan -> registries loaded

    from backend.infrastructure.registry import get_cache

    voices = get_cache().get().voices
    unknown = [
        voice_id
        for voice_id in SAMPLE_MAPPINGS.values()
        if voice_id not in voices
    ]
    assert not unknown, f"SAMPLE_MAPPINGS targets unknown voice_ids: {unknown}"
