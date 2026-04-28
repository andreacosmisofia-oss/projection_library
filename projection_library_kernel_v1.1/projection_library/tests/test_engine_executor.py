"""Unit tests for backend.domain.engine.executor (M9.0 framework + M9.1 E0)."""

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
    Balance,
    Driver,
    HistoricalKPI,
    Mapping,
    MethodConfig,
    Project,
    RawVoice,
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
    lfl_years: tuple[str, ...] | None = None,
) -> str:
    """Seed Balance + RawVoice + Mapping rows so E0's critical voice
    validation passes for the requested years.

    Returns the balance id (caller may attach more raw voices to it).
    """
    if lfl_years is None:
        lfl_years = years

    balance = Balance(
        project_id=project_id,
        source_type="gestionale",
        raw_filename="seed.xlsx",
        years_present=list(years),
        voice_count=3 * len(years),
    )
    db.add(balance)
    db.flush()

    voices_to_seed = (
        ("Ricavi", "PL", "pl.rev.net", 1000.0),
        ("Cassa", "SP", "bs.nfp.cash", 200.0),
        ("Patrimonio Netto", "SP", "bs.equity.total_close", 500.0),
    )
    for label, section, voice_id, base_amount in voices_to_seed:
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
                    amount=base_amount + idx,
                    lfl_flag=year in lfl_years,
                )
            )
    db.flush()
    return balance.id


def _seed_method_config(
    db: Session, project_id: str, *, voice_id: str = "pl.rev.net"
) -> None:
    db.add(
        MethodConfig(
            project_id=project_id,
            voice_id=voice_id,
            method_id="growth",
            source="user_override",
            is_default=False,
        )
    )
    db.flush()


def _seed_e0_ready_project(db: Session) -> str:
    """Seed the minimum needed for E0 to pass without blocks."""
    project_id = _seed_project(db)
    _seed_critical_voices(db, project_id)
    _seed_method_config(db, project_id)
    return project_id


# ---------------------------------------------------------------------------
# build_initial_state
# ---------------------------------------------------------------------------


def test_executor_builds_state_from_db(db_session: Session) -> None:
    project_id = _seed_project(db_session)
    _seed_critical_voices(db_session, project_id, years=("Y-1", "Y0"))

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
            # AGG rows must NOT leak into historical_kpis
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

    # historical_data is voice-keyed (per Flow 07 §"Stato del modello")
    assert state.historical_data["pl.rev.net"] == {"Y-1": 1000.0, "Y0": 1001.0}
    assert state.historical_data["bs.nfp.cash"] == {"Y-1": 200.0, "Y0": 201.0}
    assert state.historical_data["bs.equity.total_close"] == {
        "Y-1": 500.0,
        "Y0": 501.0,
    }
    assert state.lfl_years == ["Y-1", "Y0"]

    # KPIs land in the dedicated historical_kpis slot
    assert state.historical_kpis == {
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


# ---------------------------------------------------------------------------
# Year loop orchestration
# ---------------------------------------------------------------------------


def test_executor_runs_all_phases(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = _seed_e0_ready_project(db_session)

    with caplog.at_level(logging.INFO):
        result = run_engine(project_id, db_session, registries=None)

    phase_logs = [m for m in caplog.messages if m.startswith("phase ")]

    # E0 once + (10 phases in PHASE_SEQUENCE) × 3 projection years
    expected = 1 + len(PHASE_SEQUENCE) * len(PROJECTION_YEARS)
    assert len(phase_logs) == expected
    assert expected == 31  # sanity: matches Flow 07 inventory

    for phase_id in (
        "E0",
        "E1",
        "E2",
        "E3",
        "E3.1",
        "E4",
        "E5",
        "E6",
        "E7",
        "E7.5",
        "E8",
    ):
        assert any(
            f"phase {phase_id} year=" in m for m in phase_logs
        ), phase_id

    assert result.status == "success"
    assert result.project_id == project_id
    assert result.duration_ms >= 0


def test_year_loop_sets_current_year(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = _seed_e0_ready_project(db_session)

    with caplog.at_level(logging.INFO):
        run_engine(project_id, db_session, registries=None)

    by_year: dict[str, int] = {}
    for msg in caplog.messages:
        if not msg.startswith("phase "):
            continue
        if "year=" not in msg:
            continue
        year = msg.rsplit("year=", 1)[-1]
        by_year[year] = by_year.get(year, 0) + 1

    # E0 logs before any year is set → empty marker
    assert by_year.get("") == 1
    # Each projection year sees the full E1..E8 chain (10 phases)
    for year in PROJECTION_YEARS:
        assert by_year.get(year) == len(PHASE_SEQUENCE), (year, by_year)


# ---------------------------------------------------------------------------
# E0 setup behaviour
# ---------------------------------------------------------------------------


def test_e0_marks_historical_years(db_session: Session) -> None:
    project_id = _seed_project(db_session)
    _seed_critical_voices(
        db_session,
        project_id,
        years=("Y-1", "Y0"),
        lfl_years=("Y0",),
    )
    _seed_method_config(db_session, project_id)

    result = run_engine(project_id, db_session, registries=None)

    # state isn't returned by run_engine; rebuild it via the same helper
    # and run only E0 to inspect post-E0 fields.
    from backend.domain.engine.phases import phase_e0_setup

    state = build_initial_state(project_id, db_session, registries=None)
    state = phase_e0_setup(state)

    assert state.historical_years == ["Y-1", "Y0"]
    assert state.lfl_years == ["Y0"]
    # No block issue because critical voices are present and methods configured
    assert all(i.severity != "block" for i in state.validation_issues)
    # And run_engine succeeded end-to-end
    assert result.status == "success"


def test_e0_block_on_missing_method_configs(db_session: Session) -> None:
    project_id = _seed_project(db_session)
    # Critical voices ARE seeded so E0_001 passes; method_configs left empty
    # so only E0_002 should fire.
    _seed_critical_voices(db_session, project_id)

    with pytest.raises(ProjectNotReady) as excinfo:
        run_engine(project_id, db_session, registries=None)

    msg = str(excinfo.value)
    assert "E0_002" not in msg or "method" in msg.lower()
    # The exception aggregates block messages — check the substantive content
    assert "method configurations" in msg.lower()

    # Inspect the captured issues directly via a fresh state
    from backend.domain.engine.phases import phase_e0_setup

    state = build_initial_state(project_id, db_session, registries=None)
    state = phase_e0_setup(state)
    blocks = [i for i in state.validation_issues if i.severity == "block"]
    rule_ids = {i.rule_id for i in blocks}
    assert "E0_002_method_configs_present" in rule_ids
    assert "E0_001_y0_critical_voices" not in rule_ids


def test_e0_block_on_missing_critical_voices(db_session: Session) -> None:
    project_id = _seed_project(db_session)
    _seed_method_config(db_session, project_id)
    # No critical voices seeded → all 3 critical groups should block.

    with pytest.raises(ProjectNotReady):
        run_engine(project_id, db_session, registries=None)

    from backend.domain.engine.phases import phase_e0_setup

    state = build_initial_state(project_id, db_session, registries=None)
    state = phase_e0_setup(state)
    block_groups = {
        i.context.get("group")
        for i in state.validation_issues
        if i.severity == "block" and i.rule_id == "E0_001_y0_critical_voices"
    }
    assert block_groups == {"revenue", "cash", "equity"}


def test_e0_sector_pack_applied(
    db_session: Session,
    loaded_registries,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_id = _seed_e0_ready_project(db_session)

    from backend.domain.engine.phases import phase_e0_setup

    with caplog.at_level(logging.INFO):
        state = build_initial_state(
            project_id, db_session, registries=loaded_registries
        )
        state = phase_e0_setup(state)

    assert state.active_sector_pack == "industrial"

    pack = loaded_registries.sector_packs["industrial"]
    overrides = pack.get("method_overrides_examples") or []
    assert overrides, "expected industrial pack to ship method override examples"

    # Each override is logged on its own line
    logged_overrides = [
        m for m in caplog.messages if m.startswith("  override_example: ")
    ]
    assert len(logged_overrides) == len(overrides)
    # And the summary line carries the pack id + count
    assert any(
        "E0 sector_pack: applied industrial" in m for m in caplog.messages
    )
