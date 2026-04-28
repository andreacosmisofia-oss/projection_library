"""Integration tests for the M3 intake endpoints.

The FastAPI lifespan runs against the real registries (M1.9 contract);
only the DB session is overridden with an in-memory SQLite so the
``balances`` / ``raw_voices`` schema is created via SQLAlchemy
metadata (the Alembic migration is exercised separately).
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
from backend.infrastructure.db.models import Balance, RawVoice

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


def _project_payload() -> dict:
    return {
        "name": "Acme Pilot",
        "sector_pack": "industrial",
        "currency": "EUR",
        "horizon_years": 3,
    }


def _build_xlsx(rows: list[list[object]], sheet_name: str = "Balance") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _create_project(client: TestClient) -> str:
    resp = client.post("/api/projects", json=_project_payload())
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------- TC-01-01 happy path -----------------------------------------


def test_upload_sample_xlsx_persists_voices(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={
            "file": (
                "tier2_industrial_clean.xlsx",
                data,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["voice_count"] == 24
    assert body["years_present"] == ["Y-1", "Y0"]
    assert body["raw_filename"] == "tier2_industrial_clean.xlsx"
    assert len(body["voices"]) == 24
    assert body["validation"]["errors"] == []

    with factory() as db:
        balances = db.execute(
            select(Balance).where(Balance.deleted_at.is_(None))
        ).scalars().all()
        assert len(balances) == 1
        voices = db.execute(
            select(RawVoice).where(RawVoice.balance_id == balances[0].id)
        ).scalars().all()
        # 24 voices × 2 years (no nulls in sample) = 48 rows
        assert len(voices) == 48
        assert all(v.lfl_flag for v in voices)


# ---------- TC-01-02 missing Y0 → 422 -----------------------------------


def test_upload_without_y0_returns_422_with_bc001(client):
    project_id = _create_project(client)
    rows = [
        ["voice_label", "voice_section", "Y-1"],
        ["Ricavi", "P&L", 100],
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Cassa", "SP_assets", 50],
    ]
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("no_y0.xlsx", _build_xlsx(rows), "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    codes = {item["code"] for item in detail["validation"]["errors"]}
    assert "BC_001" in codes


# ---------- TC-01-03 CSV with ; and Italian numbers ---------------------


def test_upload_csv_italian_format(client):
    project_id = _create_project(client)
    csv_body = (
        "voice_label;voice_section;Y-1;Y0\n"
        "Ricavi;P&L;1.890,00;2.100,50\n"
        "COGS;P&L;(990,00);(1.100,00)\n"
        "Personale;P&L;-378,00;-420,00\n"
        "PPE;SP_assets;828;920\n"
        "Crediti;SP_assets;342;380\n"
        "Cassa;SP_assets;197;217\n"
    ).encode("utf-8")
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("balance.csv", csv_body, "text/csv")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["voice_count"] == 6
    ricavi = next(v for v in body["voices"] if v["user_label"] == "Ricavi")
    assert ricavi["values"]["Y-1"] == 1890.0
    assert ricavi["values"]["Y0"] == 2100.5


# ---------- TC-01-04 duplicate label warning ----------------------------


def test_upload_with_duplicate_label_returns_warning(client):
    project_id = _create_project(client)
    rows = [
        ["voice_label", "voice_section", "Y0"],
        ["Ricavi", "P&L", 100],
        ["Ricavi", "P&L", 50],
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Crediti", "SP_assets", 80],
        ["Cassa", "SP_assets", 50],
    ]
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("dup.xlsx", _build_xlsx(rows), "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 201
    body = resp.json()
    codes = {w["code"] for w in body["validation"]["warnings"]}
    assert "BC_003" in codes


# ---------- TC-01-05 re-upload replaces previous ------------------------


def test_reupload_soft_deletes_previous_balance(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()

    first = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("first.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert first.status_code == 201
    first_id = first.json()["balance_id"]

    second = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("second.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert second.status_code == 201
    second_id = second.json()["balance_id"]
    assert first_id != second_id

    with factory() as db:
        first_row = db.get(Balance, first_id)
        second_row = db.get(Balance, second_id)
        assert first_row.deleted_at is not None
        assert second_row.deleted_at is None

    active = client.get(f"/api/projects/{project_id}/balance")
    assert active.status_code == 200
    assert active.json()["balance_id"] == second_id


# ---------- GET active balance ------------------------------------------


def test_get_active_balance_404_when_none(client):
    project_id = _create_project(client)
    resp = client.get(f"/api/projects/{project_id}/balance")
    assert resp.status_code == 404


def test_get_active_balance_pivots_voices(client):
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()
    client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("balance.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    resp = client.get(f"/api/projects/{project_id}/balance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voice_count"] == 24
    assert len(body["voices"]) == 24
    for v in body["voices"]:
        assert set(v["values"].keys()) <= {"Y-3", "Y-2", "Y-1", "Y0"}


# ---------- DELETE balance -----------------------------------------------


def test_delete_balance_soft_deletes(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()
    upload = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("balance.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    balance_id = upload.json()["balance_id"]

    resp = client.delete(f"/api/projects/{project_id}/balance/{balance_id}")
    assert resp.status_code == 204

    follow_up = client.get(f"/api/projects/{project_id}/balance")
    assert follow_up.status_code == 404

    with factory() as db:
        row = db.get(Balance, balance_id)
        assert row.deleted_at is not None


# ---------- PATCH lfl ----------------------------------------------------


def test_patch_lfl_flips_rows_for_year(client_and_factory):
    client, factory = client_and_factory
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()
    upload = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("balance.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    balance_id = upload.json()["balance_id"]

    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/lfl",
        json={"year": "Y-1", "lfl": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == "Y-1"
    assert body["lfl"] is False
    assert body["rows_updated"] == 24

    with factory() as db:
        rows = db.execute(
            select(RawVoice).where(
                RawVoice.balance_id == balance_id,
                RawVoice.year == "Y-1",
            )
        ).scalars().all()
        assert all(r.lfl_flag is False for r in rows)
        rows_y0 = db.execute(
            select(RawVoice).where(
                RawVoice.balance_id == balance_id,
                RawVoice.year == "Y0",
            )
        ).scalars().all()
        assert all(r.lfl_flag is True for r in rows_y0)


def test_patch_lfl_unknown_year_returns_422(client):
    project_id = _create_project(client)
    data = (SAMPLE_DIR / "tier1_minimal_balance.xlsx").read_bytes()
    upload = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("only_y0.xlsx", data, "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    balance_id = upload.json()["balance_id"]
    resp = client.patch(
        f"/api/projects/{project_id}/balance/{balance_id}/lfl",
        json={"year": "Y-1", "lfl": False},
    )
    assert resp.status_code == 422


# ---------- Misc edge cases ---------------------------------------------


def test_upload_unknown_project_404(client):
    resp = client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/balance/upload",
        files={"file": ("x.xlsx", b"abc", "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 404


def test_upload_unsupported_extension_returns_422(client):
    project_id = _create_project(client)
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("balance.pdf", b"pdfbytes", "application/pdf")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 422


def test_upload_civilistico_rejected_in_m3(client):
    project_id = _create_project(client)
    rows = [
        ["voice_label", "voice_section", "Y0"],
        ["Ricavi", "P&L", 100],
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Cassa", "SP_assets", 50],
    ]
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("b.xlsx", _build_xlsx(rows), "application/octet-stream")},
        data={"source_type": "civilistico"},
    )
    assert resp.status_code == 422


def test_upload_empty_file_returns_422(client):
    project_id = _create_project(client)
    resp = client.post(
        f"/api/projects/{project_id}/balance/upload",
        files={"file": ("empty.xlsx", b"", "application/octet-stream")},
        data={"source_type": "gestionale"},
    )
    assert resp.status_code == 422
