"""Integration tests for the M5 endpoints (validation / KPI / quality)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.repositories.m5_repos import upsert_mapping

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


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
        "perimeter": "consolidated",
    }
    payload.update(overrides)
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload_sample(client: TestClient, project_id: str, filename: str) -> dict:
    data = (SAMPLE_DIR / filename).read_bytes()
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={
            "file": (
                filename,
                data,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"source_type": "gestionale"},
    )
    return resp.json() if resp.status_code in (200, 201, 422) else {}


# Mapping table for the cleaned tier2_industrial sample. Mirrors the
# labels the file actually contains; only the 7 voices the M5 KPI/score
# pipelines actually care about are mapped (rest stays unmapped, which
# is fine for a TIER 2 project).
_TIER2_MAPPINGS: dict[tuple[str, str], str] = {
    ("Ricavi delle vendite", "P&L"): "pl.rev.net",
    ("Costo del venduto", "P&L"): "pl.cogs.total",
    ("Cassa e disponibilità", "SP_assets"): "bs.nfp.cash",
    ("Capitale sociale", "SP_equity"): "bs.equity.share_capital.close",
    ("Riserve e utili a nuovo", "SP_equity"): "bs.equity.retained_earnings.close",
    ("Crediti commerciali", "SP_assets"): "bs.nwc.ar.close",
    ("Rimanenze", "SP_assets"): "bs.nwc.inventory.close",
    ("Immobilizzazioni nette", "SP_assets"): "bs.fa.tangible.gross_close",
}


def _seed_mappings(factory, project_id: str, mapping: dict[tuple[str, str], str]):
    with factory() as db:
        for (label, section), voice_id in mapping.items():
            upsert_mapping(
                db,
                project_id=project_id,
                voice_user_label=label,
                voice_user_section=section,
                voice_id=voice_id,
                confirmed_by_user=True,
            )
        db.commit()


# ---------- validation endpoint ---------------------------------------


def test_validate_clean_tier2_can_proceed(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    resp = client.post(f"/api/projects/{project_id}/validate-historical")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_proceed"] is True
    assert body["summary"]["block"] == 0
    rule_ids = {issue["rule_id"] for issue in body["issues"]}
    assert "DI_013_balance_check_historical" not in rule_ids


def test_validate_unbalanced_blocks(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_unbalanced.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    resp = client.post(f"/api/projects/{project_id}/validate-historical")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rule_ids = {issue["rule_id"] for issue in body["issues"] if issue["severity"] == "block"}
    assert "DI_013_balance_check_historical" in rule_ids
    assert body["can_proceed"] is False


def test_validation_get_returns_persisted(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    client.post(f"/api/projects/{project_id}/validate-historical")
    resp = client.get(f"/api/projects/{project_id}/validation-report/historical")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "historical"


def test_validate_404_when_no_balance(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.post(f"/api/projects/{project_id}/validate-historical")
    assert resp.status_code == 409


# ---------- KPI endpoints ---------------------------------------------


def test_kpi_compute_and_list(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    resp = client.post(f"/api/projects/{project_id}/kpi-historical")
    assert resp.status_code == 200, resp.text
    counts = resp.json()["counts"]
    assert counts["computed"] >= 1
    assert counts["total"] >= counts["computed"]

    list_resp = client.get(f"/api/projects/{project_id}/kpi-historical")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert any(k["kpi_id"] == "kpi.growth.revenue_yoy" for k in body["kpis"])

    yoy = next(k for k in body["kpis"] if k["kpi_id"] == "kpi.growth.revenue_yoy")
    # tier2_industrial_clean: 1890 → 2100 → 11.11%
    assert yoy["values"]["Y0"] == pytest.approx((2100 - 1890) / 1890, rel=1e-3)


def test_kpi_idempotent(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)
    first = client.post(f"/api/projects/{project_id}/kpi-historical").json()
    second = client.post(f"/api/projects/{project_id}/kpi-historical").json()
    assert first["counts"] == second["counts"]


# ---------- Quality score endpoint ------------------------------------


def test_quality_score_clean_dataset(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    resp = client.post(f"/api/projects/{project_id}/quality-score")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert 0 <= body["score_total"] <= 100
    assert body["classification"] in {
        "Full",
        "Solid",
        "Acceptable",
        "Directional",
        "Insufficient",
    }
    assert body["score_method_calibration"] is None
    assert body["weights"]["history"] == pytest.approx(0.25)


def test_quality_score_block_zeroes_consistency(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_unbalanced.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)

    resp = client.post(f"/api/projects/{project_id}/quality-score")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score_consistency"] == 0.0


def test_quality_score_get_after_post(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_sample(client, project_id, "tier2_industrial_clean.xlsx")
    _seed_mappings(factory, project_id, _TIER2_MAPPINGS)
    client.post(f"/api/projects/{project_id}/quality-score")

    resp = client.get(f"/api/projects/{project_id}/quality-score")
    assert resp.status_code == 200
    assert "components_detail" in resp.json()


def test_quality_404_before_post(client_and_factory):
    client, _ = client_and_factory
    project_id = _create_project(client)
    resp = client.get(f"/api/projects/{project_id}/quality-score")
    assert resp.status_code == 404
