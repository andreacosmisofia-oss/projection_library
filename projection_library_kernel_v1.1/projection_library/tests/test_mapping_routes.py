"""Integration tests for the M4 mapping endpoints.

The FastAPI lifespan boots against the real registries (so the
synonym index is loaded). The DB session is overridden with an
in-memory SQLite that's created from the SQLAlchemy metadata —
mirroring the M3 test harness so we don't ship a separate
migration runner here.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.infrastructure.db.database import Base, get_db
from backend.infrastructure.db.models import CompanyMapping, Mapping

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _make_test_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )


@pytest.fixture()
def client_and_factory() -> Iterator[tuple[TestClient, sessionmaker]]:
    engine, factory = _make_test_session_factory()

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


@pytest.fixture()
def client(client_and_factory) -> TestClient:
    return client_and_factory[0]


def _create_project(client: TestClient, name: str = "Acme Pilot") -> str:
    payload = {
        "name": name,
        "company_name": name,
        "sector_pack": "industrial",
        "currency": "EUR",
        "horizon_years": 3,
    }
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _build_xlsx(rows: list[list[object]], sheet: str = "Balance") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_balance(client: TestClient, project_id: str) -> None:
    rows = [
        ["voice_label", "voice_section", "Y-1", "Y0"],
        ["Ricavi delle vendite", "P&L", 1000, 1100],
        ["Acquisti materie prime", "P&L", -400, -440],
        ["Costo del personale amministrativo", "P&L", -100, -110],
        ["Ammortamento immobilizzazioni materiali", "P&L", -50, -55],
        ["Cassa", "SP_assets", 200, 220],
        ["Capitale sociale finale", "SP_equity", 500, 500],
        ["voce esoterica sconosciuta", None, 1, 1],
    ]
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={
            "file": (
                "balance.xlsx",
                _build_xlsx(rows),
                "application/octet-stream",
            )
        },
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 201, resp.text


# ---------- TC-04-01 suggest produces candidates ------------------------


def test_suggest_returns_suggestions(client):
    project_id = _create_project(client)
    _upload_balance(client, project_id)

    resp = client.post(f"/api/projects/{project_id}/mapping/suggest")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    suggestions = {s["user_label"]: s for s in body["suggestions"]}
    # Strategy B (synonym) must hit the well-known IT labels.
    rev = suggestions["Ricavi delle vendite"]
    assert rev["candidates"][0]["voice_id"] == "pl.rev.gross.product_sales"
    assert rev["candidates"][0]["confidence"] >= 0.95
    assert rev["candidates"][0]["reason"] == "synonym_match"

    cogs = suggestions["Acquisti materie prime"]
    assert cogs["candidates"][0]["voice_id"] == "pl.cogs.materials.raw"

    cash = suggestions["Cassa"]
    assert cash["candidates"][0]["voice_id"] == "bs.nfp.cash"

    # Unknown label → no candidates passing the 0.6 threshold.
    unknown = suggestions["voce esoterica sconosciuta"]
    assert unknown["candidates"] == []


# ---------- TC-04-02 stats break down by confidence band ----------------


def test_suggest_stats(client):
    project_id = _create_project(client)
    _upload_balance(client, project_id)

    resp = client.post(f"/api/projects/{project_id}/mapping/suggest")
    body = resp.json()
    stats = body["stats"]
    assert stats["total_voices"] == 7
    # 6 well-known IT labels (incl. equity + ammortamento) hit ≥0.85.
    assert stats["high_confidence"] >= 5
    # Exactly one label has no match.
    assert stats["no_match"] == 1
    assert (
        stats["high_confidence"]
        + stats["medium_confidence"]
        + stats["low_confidence"]
        + stats["no_match"]
        == stats["total_voices"]
    )


# ---------- TC-04-03 PUT persists mappings ------------------------------


def test_save_mapping(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    _upload_balance(client, project_id)

    payload = {
        "mappings": [
            {
                "user_label": "Ricavi delle vendite",
                "user_section": "P&L",
                "voice_id_system": "pl.rev.gross.product_sales",
                "confidence": 0.95,
                "auto_suggested": True,
            },
            {
                "user_label": "Acquisti materie prime",
                "user_section": "P&L",
                "voice_id_system": "pl.cogs.materials.raw",
                "confidence": 0.95,
                "auto_suggested": True,
            },
            {
                "user_label": "Cassa",
                "user_section": "SP_assets",
                "voice_id_system": "bs.nfp.cash",
                "confidence": 0.95,
                "auto_suggested": True,
            },
            {
                "user_label": "Capitale sociale finale",
                "user_section": "SP_equity",
                "voice_id_system": "bs.equity.share_capital.close",
                "confidence": 0.95,
                "auto_suggested": True,
            },
            {
                "user_label": "voce esoterica sconosciuta",
                "user_section": None,
                "voice_id_system": None,
                "skipped": True,
            },
        ],
        "sign_flip_applied": False,
    }
    resp = client.put(f"/api/projects/{project_id}/mapping", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["saved"] == 5
    assert body["validation_issues"] == []
    assert body["ready_for_validation"] is True

    with factory() as db:
        rows = db.execute(
            select(Mapping).where(Mapping.project_id == project_id)
        ).scalars().all()
        assert len(rows) == 5
        skipped = [r for r in rows if r.skipped]
        assert len(skipped) == 1
        assert skipped[0].voice_id_system is None


# ---------- TC-04-04 GET returns saved mappings -------------------------


def test_get_mapping(client):
    project_id = _create_project(client)
    _upload_balance(client, project_id)

    # Save a minimal viable mapping (revenue + cogs so the post-mapping
    # check does not block).
    payload = {
        "mappings": [
            {
                "user_label": "Ricavi delle vendite",
                "user_section": "P&L",
                "voice_id_system": "pl.rev.gross.product_sales",
                "auto_suggested": True,
            },
            {
                "user_label": "Acquisti materie prime",
                "user_section": "P&L",
                "voice_id_system": "pl.cogs.materials.raw",
                "auto_suggested": True,
            },
        ],
        "sign_flip_applied": False,
    }
    client.put(f"/api/projects/{project_id}/mapping", json=payload)
    resp = client.get(f"/api/projects/{project_id}/mapping")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    voice_ids = {item["voice_id_system"] for item in body["items"]}
    assert "pl.rev.gross.product_sales" in voice_ids
    assert "pl.cogs.materials.raw" in voice_ids
    assert all(item["confirmed_by_user"] for item in body["items"])


# ---------- TC-04-05 second project for same company uses history -------


def test_company_history_used_on_second_project(client_and_factory):
    client, factory = client_and_factory

    # First project: confirm a mapping, which seeds company_mappings.
    first_id = _create_project(client, name="Acme SpA")
    _upload_balance(client, first_id)
    client.put(
        f"/api/projects/{first_id}/mapping",
        json={
            "mappings": [
                {
                    "user_label": "Ricavi delle vendite",
                    "user_section": "P&L",
                    # User intentionally diverges from the synonym suggestion
                    # so we can see strategy A win on the second project.
                    "voice_id_system": "pl.rev.gross.subscription",
                    "confidence": 0.7,
                    "auto_suggested": False,
                },
                {
                    "user_label": "Acquisti materie prime",
                    "user_section": "P&L",
                    "voice_id_system": "pl.cogs.materials.raw",
                    "auto_suggested": True,
                },
            ],
            "sign_flip_applied": False,
        },
    )

    with factory() as db:
        seeded = db.execute(select(CompanyMapping)).scalars().all()
        assert any(
            row.voice_id_system == "pl.rev.gross.subscription" for row in seeded
        )

    # Second project for the same company.
    second_id = _create_project(client, name="Acme SpA")
    _upload_balance(client, second_id)
    resp = client.post(f"/api/projects/{second_id}/mapping/suggest")
    body = resp.json()
    suggestions = {s["user_label"]: s for s in body["suggestions"]}
    top = suggestions["Ricavi delle vendite"]["candidates"][0]
    assert top["reason"] == "company_history"
    assert top["voice_id"] == "pl.rev.gross.subscription"
    assert top["confidence"] == 1.0
