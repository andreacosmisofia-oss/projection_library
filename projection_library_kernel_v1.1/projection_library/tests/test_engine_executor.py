"""Unit tests for backend.domain.engine.executor (M9.0 framework)."""

from __future__ import annotations

import logging
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.domain.engine.executor import (
    PHASE_SEQUENCE,
    PROJECTION_YEARS,
    ProjectNotReady,
    build_initial_state,
    run_engine,
)
from backend.infrastructure.db.database import Base
from backend.infrastructure.db.models import (
    Driver,
    HistoricalKPI,
    MethodConfig,
    Project,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
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
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_project(db: Session) -> str:
    project = Project(
        name="Acme Pilot",
        sector_pack="industrial",
        currency="EUR",
        horizon_years=3,
    )
    db.add(project)
    db.flush()
    return project.id


def test_executor_builds_state_from_db(db_session: Session) -> None:
    project_id = _seed_project(db_session)

    db_session.add_all(
        [
            HistoricalKPI(
                project_id=project_id,
                kpi_id="ebitda_margin",
                year="Y0",
                value=0.15,
            ),
            HistoricalKPI(
                project_id=project_id,
                kpi_id="ebitda_margin",
                year="Y-1",
                value=0.12,
            ),
            # AGG rows must NOT leak into historical_data
            HistoricalKPI(
                project_id=project_id,
                kpi_id="ebitda_margin",
                year="AGG",
                value=None,
                default_for_projection=0.16,
            ),
            # Skipped driver row must be ignored
            Driver(
                project_id=project_id,
                driver_id="skipped_driver",
                type="skip",
                year="",
                skipped=True,
            ),
            Driver(
                project_id=project_id,
                driver_id="capex",
                type="scalar_per_year",
                year="Y0",
                value=1000.0,
            ),
            Driver(
                project_id=project_id,
                driver_id="term_loan",
                type="static_parameters",
                year="",
                static_parameters={"rate": 0.05, "years": 10},
            ),
            MethodConfig(
                project_id=project_id,
                voice_id="pl.rev.net",
                method_id="growth",
                source="user_override",
                is_default=False,
            ),
        ]
    )
    db_session.flush()

    state = build_initial_state(
        project_id, db_session, registries="<registries-stub>"
    )

    assert state.project.id == project_id
    assert state.registries == "<registries-stub>"

    assert state.historical_data == {
        "ebitda_margin": {"Y0": 0.15, "Y-1": 0.12},
    }

    assert state.drivers["capex"] == {"Y0": 1000.0}
    assert state.drivers["term_loan"]["static_parameters"] == {
        "rate": 0.05,
        "years": 10,
    }
    assert "skipped_driver" not in state.drivers

    assert "pl.rev.net" in state.method_configs
    assert state.method_configs["pl.rev.net"].method_id == "growth"

    # M8 not built yet → assumptions empty by design
    assert state.assumptions == {}
    assert state.overrides == []
    assert state.base_values == {}


def test_build_initial_state_raises_when_project_missing(
    db_session: Session,
) -> None:
    with pytest.raises(ProjectNotReady):
        build_initial_state("does-not-exist", db_session, registries=None)


def test_executor_runs_all_phases(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = _seed_project(db_session)

    with caplog.at_level(logging.INFO):
        result = run_engine(project_id, db_session, registries=None)

    phase_logs = [m for m in caplog.messages if m.startswith("phase ")]

    # E0 once + (10 phases in PHASE_SEQUENCE) × 3 projection years
    expected = 1 + len(PHASE_SEQUENCE) * len(PROJECTION_YEARS)
    assert len(phase_logs) == expected
    assert expected == 31  # sanity: matches Flow 07 inventory

    # All 11 phases mentioned at least once
    for phase_id in ("E0", "E1", "E2", "E3", "E3.1", "E4", "E5", "E6", "E7", "E7.5", "E8"):
        assert any(f"phase {phase_id} stub" in m for m in phase_logs), phase_id

    assert result.status == "success"
    assert result.project_id == project_id
    assert result.duration_ms >= 0


def test_year_loop_sets_current_year(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = _seed_project(db_session)

    with caplog.at_level(logging.INFO):
        run_engine(project_id, db_session, registries=None)

    by_year: dict[str, int] = {}
    for msg in caplog.messages:
        if "stub year=" not in msg:
            continue
        year = msg.rsplit("year=", 1)[-1]
        by_year[year] = by_year.get(year, 0) + 1

    # E0 logged before any year is set → empty marker
    assert by_year.get("") == 1
    # Each projection year sees the full E1..E8 chain (10 phases)
    for year in PROJECTION_YEARS:
        assert by_year.get(year) == len(PHASE_SEQUENCE), (year, by_year)
