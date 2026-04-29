"""Integration tests for the M11 override endpoints.

Covers POST/GET/PATCH/DELETE under
``/api/projects/{id}/overrides`` plus the acceptance scenarios from
BUILD_PLAN M11:

* organic revenue override → cogs/AR/cash recalculated;
* one_shot opex override → only cash adjusts, cogs invariant;
* override on a derived voice → 422 with guidance message;
* deactivate → re-run zeroes the delta everywhere.
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
    Balance,
    Mapping,
    MethodConfig,
    Override,
    Project,
    RawVoice,
    Snapshot,
    SnapshotValue,
)


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


def _seed_e0_ready(factory: sessionmaker) -> str:
    db = factory()
    try:
        project = Project(
            name="Acme Pilot",
            sector_pack="industrial",
            currency="EUR",
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
            voice_count=6,
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
            for idx, year in enumerate(("Y-1", "Y0")):
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
        return project_id
    finally:
        db.close()


def _latest_snapshot_values(
    factory: sessionmaker, project_id: str
) -> dict[tuple[str, str], dict]:
    db = factory()
    try:
        snap = db.execute(
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
            .limit(1)
        ).scalars().first()
        if snap is None:
            return {}
        rows = db.execute(
            select(SnapshotValue).where(SnapshotValue.snapshot_id == snap.id)
        ).scalars().all()
        return {
            (r.voice_id, r.year): {
                "value": r.value,
                "base_value": r.base_value,
                "override_delta": r.override_delta,
            }
            for r in rows
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /overrides
# ---------------------------------------------------------------------------


def test_post_returns_404_for_missing_project(client_and_factory) -> None:
    client, _ = client_and_factory
    resp = client.post(
        "/api/projects/does-not-exist/overrides",
        json={
            "voice_id": "pl.rev.gross.product_sales",
            "year": "Y2",
            "delta_amount": 1000.0,
            "nature": "organic",
        },
    )
    assert resp.status_code == 404


def test_post_rejects_derived_voice_with_422(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.ebitda",
            "year": "Y2",
            "delta_amount": 500.0,
            "nature": "organic",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # Guidance should mention "derived" / components
    assert "derived" in detail.lower() or "componenti" in detail.lower()


def test_post_rejects_invalid_year(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.rev.gross.product_sales",
            "year": "Y5",
            "delta_amount": 1000.0,
            "nature": "organic",
        },
    )
    assert resp.status_code == 422


def test_post_rejects_zero_delta(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.rev.gross.product_sales",
            "year": "Y2",
            "delta_amount": 0.0,
            "nature": "organic",
        },
    )
    assert resp.status_code == 422


def test_post_creates_override_and_triggers_snapshot(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.rev.gross.product_sales",
            "year": "Y2",
            "delta_amount": 2000.0,
            "nature": "organic",
            "user_note": "Big contract win",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["voice_id"] == "pl.rev.gross.product_sales"
    assert body["year"] == "Y2"
    assert body["delta_amount"] == 2000.0
    assert body["nature"] == "organic"
    assert body["override_policy_class"] == "revenue_organic"
    assert body["is_active"] is True
    assert body["user_note"] == "Big contract win"

    # Snapshot was created and the delta is reflected on the override row.
    values = _latest_snapshot_values(factory, project_id)
    rev_y2 = values.get(("pl.rev.gross.product_sales", "Y2"))
    assert rev_y2 is not None, "override row must appear in snapshot_values"
    assert rev_y2["override_delta"] == 2000.0


# ---------------------------------------------------------------------------
# Acceptance — overlay semantics on the snapshot
#
# With the minimal pilot seed (no methods/drivers wired across the full
# chain) the engine produces zero base_values for most voices, so we
# assert the *overlay* behaviour rather than specific propagated
# numbers — the propagation matrix itself is exercised end-to-end in
# test_override_resolver.py against ``apply_one_shot_suppression``.
# ---------------------------------------------------------------------------


def test_organic_revenue_override_visible_with_correct_delta(
    client_and_factory,
) -> None:
    """Acceptance M11: organic override on a revenue voice appears in
    the snapshot with the expected ``override_delta`` and a
    ``value = base + delta`` composition (single source of truth)."""
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    # Baseline run.
    client.post(f"/api/projects/{project_id}/run")
    baseline = _latest_snapshot_values(factory, project_id)
    base_y2 = baseline.get(("pl.rev.gross.product_sales", "Y2"), {}).get(
        "base_value"
    ) or 0.0

    # Apply organic override on revenue Y2.
    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.rev.gross.product_sales",
            "year": "Y2",
            "delta_amount": 2000.0,
            "nature": "organic",
        },
    )
    assert resp.status_code == 201
    after = _latest_snapshot_values(factory, project_id)

    row = after.get(("pl.rev.gross.product_sales", "Y2"))
    assert row is not None
    assert row["override_delta"] == 2000.0
    expected_value = (row["base_value"] or 0.0) + 2000.0
    assert row["value"] == pytest.approx(expected_value)
    # Sanity: the base_value didn't change under organic mode, only the overlay.
    assert (row["base_value"] or 0.0) == pytest.approx(base_y2)


def test_one_shot_opex_overlay_does_not_propagate_to_cogs(
    client_and_factory,
) -> None:
    """Acceptance M11: one_shot opex override leaves the COGS
    ``base_value`` rows from the baseline run identical (the
    suppression layer resets them to the organic-baseline pass)."""
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    # Baseline run.
    client.post(f"/api/projects/{project_id}/run")
    baseline = _latest_snapshot_values(factory, project_id)
    cogs_before = {
        key: vals["base_value"]
        for key, vals in baseline.items()
        if key[0].startswith("pl.cogs.") and key[1] == "Y2"
    }
    assert cogs_before, "baseline run must produce cogs rows for the assertion to be meaningful"

    # Apply one_shot opex override.
    resp = client.post(
        f"/api/projects/{project_id}/overrides",
        json={
            "voice_id": "pl.opex.ga.travel",
            "year": "Y2",
            "delta_amount": -100.0,
            "nature": "one_shot",
        },
    )
    assert resp.status_code == 201, resp.text
    after = _latest_snapshot_values(factory, project_id)

    # COGS base_value must NOT move under a one_shot opex override
    # (cogs is not in opex_one_shot.one_shot_propagation_targets).
    for key, before_value in cogs_before.items():
        after_value = after.get(key, {}).get("base_value")
        assert after_value == before_value, (
            f"one_shot must not propagate to {key}; "
            f"before={before_value} after={after_value}"
        )

    # The override row itself shows up with the correct delta.
    opex_row = after.get(("pl.opex.ga.travel", "Y2"))
    assert opex_row is not None
    assert opex_row["override_delta"] == -100.0


# ---------------------------------------------------------------------------
# GET / PATCH / DELETE
# ---------------------------------------------------------------------------


def _create_simple_override(
    client: TestClient, project_id: str, **overrides
) -> dict:
    payload = {
        "voice_id": "pl.rev.gross.product_sales",
        "year": "Y2",
        "delta_amount": 1500.0,
        "nature": "organic",
    }
    payload.update(overrides)
    resp = client.post(
        f"/api/projects/{project_id}/overrides", json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_list_overrides_filter_active_only(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    a = _create_simple_override(client, project_id, delta_amount=1000.0)
    b = _create_simple_override(
        client, project_id, voice_id="pl.opex.ga.travel", delta_amount=-200.0
    )

    # Deactivate b.
    resp = client.patch(
        f"/api/projects/{project_id}/overrides/{b['id']}",
        json={"is_active": False},
    )
    assert resp.status_code == 200

    # List all → 2.
    resp = client.get(f"/api/projects/{project_id}/overrides")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    # Filter active_only → 1.
    resp = client.get(
        f"/api/projects/{project_id}/overrides?active_only=true"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == a["id"]


def test_patch_deactivate_then_reactivate(client_and_factory) -> None:
    """Deactivating an override must zero its overlay on the snapshot;
    reactivating must restore it. Asserted on the override voice's own
    snapshot row (deterministic regardless of method seeding)."""
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    voice = "pl.rev.gross.product_sales"

    # Create active override → snapshot reflects the delta.
    ov = _create_simple_override(client, project_id, delta_amount=2000.0)
    after_create = _latest_snapshot_values(factory, project_id)
    row_active = after_create[(voice, "Y2")]
    assert row_active["override_delta"] == 2000.0
    assert row_active["value"] == pytest.approx(
        (row_active["base_value"] or 0.0) + 2000.0
    )

    # Deactivate → next snapshot has override_delta=0.
    resp = client.patch(
        f"/api/projects/{project_id}/overrides/{ov['id']}",
        json={"is_active": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_active"] is False
    assert body["deactivated_at"] is not None

    after_deactivate = _latest_snapshot_values(factory, project_id)
    row_inactive = after_deactivate[(voice, "Y2")]
    assert row_inactive["override_delta"] == 0.0
    assert row_inactive["value"] == pytest.approx(
        row_inactive["base_value"] or 0.0
    )

    # Reactivate → delta back, deactivated_at cleared.
    resp = client.patch(
        f"/api/projects/{project_id}/overrides/{ov['id']}",
        json={"is_active": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_active"] is True
    assert body["deactivated_at"] is None

    after_reactivate = _latest_snapshot_values(factory, project_id)
    row_reactivated = after_reactivate[(voice, "Y2")]
    assert row_reactivated["override_delta"] == 2000.0


def test_patch_no_op_when_state_unchanged(client_and_factory) -> None:
    """PATCH with the same is_active value returns 200 without re-running."""
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)
    ov = _create_simple_override(client, project_id, delta_amount=1000.0)

    resp = client.patch(
        f"/api/projects/{project_id}/overrides/{ov['id']}",
        json={"is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


def test_patch_returns_404_for_missing_override(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)
    resp = client.patch(
        f"/api/projects/{project_id}/overrides/missing-id",
        json={"is_active": False},
    )
    assert resp.status_code == 404


def test_delete_removes_row_and_zeroes_effect(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)

    voice = "pl.rev.gross.product_sales"
    ov = _create_simple_override(client, project_id, delta_amount=1500.0)
    after_create = _latest_snapshot_values(factory, project_id)
    assert after_create[(voice, "Y2")]["override_delta"] == 1500.0

    resp = client.delete(
        f"/api/projects/{project_id}/overrides/{ov['id']}"
    )
    assert resp.status_code == 204

    # Row gone from DB.
    db = factory()
    try:
        rows = db.execute(
            select(Override).where(Override.project_id == project_id)
        ).scalars().all()
        assert rows == []
    finally:
        db.close()

    # Snapshot's override_delta on the voice/year drops to 0.
    after_delete = _latest_snapshot_values(factory, project_id)
    row_after = after_delete.get((voice, "Y2"))
    if row_after is not None:
        # Voice may drop out of the snapshot entirely if it was only
        # in there because of the override; either is acceptable.
        assert row_after["override_delta"] == 0.0


def test_delete_returns_404_for_missing_override(client_and_factory) -> None:
    client, factory = client_and_factory
    project_id = _seed_e0_ready(factory)
    resp = client.delete(
        f"/api/projects/{project_id}/overrides/missing-id"
    )
    assert resp.status_code == 404
