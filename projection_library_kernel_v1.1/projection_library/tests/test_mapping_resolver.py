"""Unit tests for ``mapping_resolver`` (M5)."""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.domain.intake.mapping_resolver import resolve_mapped_values
from backend.infrastructure.db.database import Base
from backend.infrastructure.db.models import Balance, Mapping, Project, RawVoice


@pytest.fixture()
def session() -> Iterator:
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
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_basic(db) -> str:
    project = Project(name="Acme", sector_pack="industrial")
    db.add(project)
    db.flush()
    balance = Balance(
        project_id=project.id,
        source_type="gestionale",
        raw_filename="x.xlsx",
        years_present=["Y-1", "Y0"],
        voice_count=3,
    )
    db.add(balance)
    db.flush()
    db.add_all(
        [
            RawVoice(
                balance_id=balance.id,
                voice_user_label="Ricavi",
                voice_user_section="P&L",
                year="Y-1",
                amount=1000.0,
                lfl_flag=True,
            ),
            RawVoice(
                balance_id=balance.id,
                voice_user_label="Ricavi",
                voice_user_section="P&L",
                year="Y0",
                amount=1100.0,
                lfl_flag=True,
            ),
            RawVoice(
                balance_id=balance.id,
                voice_user_label="Materie prime",
                voice_user_section="P&L",
                year="Y0",
                amount=-400.0,
                lfl_flag=True,
            ),
        ]
    )
    db.add(
        Mapping(
            project_id=project.id,
            voice_user_label="Ricavi",
            voice_user_section="P&L",
            voice_id="pl.rev.net",
            confirmed_by_user=True,
        )
    )
    db.commit()
    return project.id


def test_resolve_basic_mapping(session):
    project_id = _seed_basic(session)
    values = resolve_mapped_values(session, project_id)

    assert values.has("pl.rev.net")
    assert values.get("pl.rev.net", "Y-1") == 1000.0
    assert values.get("pl.rev.net", "Y0") == 1100.0
    assert values.years_present == ["Y-1", "Y0"]
    assert values.years_lfl == ["Y-1", "Y0"]
    assert ("Materie prime", "P&L") in values.unmapped_labels


def test_resolve_collects_raw_by_section(session):
    project_id = _seed_basic(session)
    values = resolve_mapped_values(session, project_id)
    pl_rows = values.raw_by_section.get("P&L", [])
    labels = {row[0] for row in pl_rows}
    assert {"Ricavi", "Materie prime"} <= labels


def test_resolve_sums_when_multiple_labels_share_voice_id(session):
    project = Project(name="Foo", sector_pack="industrial")
    session.add(project)
    session.flush()
    balance = Balance(
        project_id=project.id,
        source_type="gestionale",
        raw_filename="x.xlsx",
        years_present=["Y0"],
        voice_count=2,
    )
    session.add(balance)
    session.flush()
    session.add_all(
        [
            RawVoice(
                balance_id=balance.id,
                voice_user_label="Materie prime",
                voice_user_section="P&L",
                year="Y0",
                amount=-300.0,
            ),
            RawVoice(
                balance_id=balance.id,
                voice_user_label="Manodopera",
                voice_user_section="P&L",
                year="Y0",
                amount=-200.0,
            ),
        ]
    )
    session.add_all(
        [
            Mapping(
                project_id=project.id,
                voice_user_label="Materie prime",
                voice_user_section="P&L",
                voice_id="pl.cogs.total",
                confirmed_by_user=True,
            ),
            Mapping(
                project_id=project.id,
                voice_user_label="Manodopera",
                voice_user_section="P&L",
                voice_id="pl.cogs.total",
                confirmed_by_user=True,
            ),
        ]
    )
    session.commit()

    values = resolve_mapped_values(session, project.id)
    assert values.get("pl.cogs.total", "Y0") == -500.0


def test_no_active_balance_raises(session):
    project = Project(name="Bar", sector_pack="industrial")
    session.add(project)
    session.commit()
    with pytest.raises(LookupError):
        resolve_mapped_values(session, project.id)


def test_unconfirmed_mapping_is_ignored(session):
    project = Project(name="Bar", sector_pack="industrial")
    session.add(project)
    session.flush()
    balance = Balance(
        project_id=project.id,
        source_type="gestionale",
        raw_filename="x.xlsx",
        years_present=["Y0"],
        voice_count=1,
    )
    session.add(balance)
    session.flush()
    session.add(
        RawVoice(
            balance_id=balance.id,
            voice_user_label="Ricavi",
            voice_user_section="P&L",
            year="Y0",
            amount=100.0,
        )
    )
    session.add(
        Mapping(
            project_id=project.id,
            voice_user_label="Ricavi",
            voice_user_section="P&L",
            voice_id="pl.rev.net",
            confirmed_by_user=False,
        )
    )
    session.commit()

    values = resolve_mapped_values(session, project.id)
    assert not values.has("pl.rev.net")
    assert ("Ricavi", "P&L") in values.unmapped_labels
