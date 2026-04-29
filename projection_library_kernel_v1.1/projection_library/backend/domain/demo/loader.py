"""One-click sample-project loader (M13).

Pipeline executed by ``load_sample_project``:

1. Read ``sample_data/tier2_industrial_clean.xlsx`` from disk and run
   it through the M3 ``parse_balance`` + ``replace_active_balance``
   pipeline (the same path used by ``POST /api/projects/{id}/balance/upload``).
2. Insert one ``Mapping(confirmed_by_user=True)`` row per
   ``(label, section)`` declared in :data:`SAMPLE_MAPPINGS` so
   ``resolve_mapped_values`` can build a voice-keyed view.
3. Materialise the registry-default ``MethodConfig`` for each mapped
   ``voice_id`` whose voice carries a real ``default_method`` (sentinels
   like ``(utente sceglie)`` are skipped). E0 only requires *one*
   method config; we materialise the full set so the engine can
   project every mapped voice deterministically.
4. Walk the M5/M6/M8 pre-engine pipeline (validation → KPIs → quality
   score → assumption defaults) so ``state.assumptions`` is populated
   before the engine runs.
5. Run ``run_engine`` and persist the resulting snapshot via
   ``create_snapshot`` (same call site as ``POST /run``).

The mapping table below is intentionally hardcoded and tier2-specific.
M4 will replace it with synonym-driven auto-mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.assumptions.populator import populate_defaults
from backend.domain.engine.executor import run_engine
from backend.domain.engine.snapshot_builder import (
    build_snapshot_values,
    build_validation_summary,
    serialise_validation_issues,
)
from backend.domain.intake import (
    parse_balance,
    resolve_mapped_values,
    run_historical_validation,
)
from backend.domain.kpi import compute_historical_kpis
from backend.domain.methods import (
    SOURCE_REGISTRY_DEFAULT,
    resolve_default_method,
    resolve_method_tech_code,
)
from backend.domain.quality import compute_quality_score
from backend.infrastructure.db.models import Mapping, MethodConfig, Project
from backend.infrastructure.db.repositories.balance_repo import (
    replace_active_balance,
)
from backend.infrastructure.db.repositories.m5_repos import (
    replace_historical_kpis,
    upsert_quality_score,
    upsert_validation_report,
)
from backend.infrastructure.db.repositories.snapshots_repo import create_snapshot
from backend.infrastructure.registry import Registries


SAMPLE_FILENAME = "tier2_industrial_clean.xlsx"

# Repo root used to locate ``sample_data/``: ``backend/domain/demo`` →
# parents[3] is the project root that also hosts ``sample_data/``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_PATH = _REPO_ROOT / "sample_data" / SAMPLE_FILENAME


# (voice_user_label, voice_user_section) → voice_id.
# Sections must match the parser's normalised values
# (``P&L``, ``SP_assets``, ``SP_liabilities``, ``SP_equity``).
SAMPLE_MAPPINGS: dict[tuple[str, str], str] = {
    # P&L base
    ("Ricavi delle vendite", "P&L"): "pl.rev.net",
    ("Costo del venduto", "P&L"): "pl.cogs.total",
    ("Costi del personale", "P&L"): "pl.opex.ga.personnel",
    ("Altri costi operativi", "P&L"): "pl.opex.other_recurring",
    ("Ammortamenti", "P&L"): "pl.da.ppe",
    ("Proventi/oneri finanziari", "P&L"): "pl.financial.interest_expense",
    # P&L granular (tier2 extra)
    ("Ricavi prodotti", "P&L"): "pl.rev.gross.product_sales",
    ("Ricavi servizi", "P&L"): "pl.rev.gross.service_revenue",
    ("Materie prime", "P&L"): "pl.cogs.materials.raw",
    ("Manodopera diretta", "P&L"): "pl.cogs.labour.direct",
    ("Costi commerciali", "P&L"): "pl.opex.sm.commissions",
    ("Costi generali e amministrativi", "P&L"): "pl.opex.ga.professional_fees",
    # SP assets
    ("Immobilizzazioni nette", "SP_assets"): "bs.fa.tangible.net_close",
    ("Crediti commerciali", "SP_assets"): "bs.nwc.ar.trade_gross",
    ("Rimanenze", "SP_assets"): "bs.nwc.inventory.total",
    ("Altre attività correnti", "SP_assets"): "bs.nwc.other_current_assets",
    ("Cassa e disponibilità", "SP_assets"): "bs.nfp.cash",
    ("Crediti per imposte anticipate", "SP_assets"): "bs.tax.dta_close",
    # SP liabilities
    ("Debiti commerciali", "SP_liabilities"): "bs.nwc.ap.trade",
    ("Debiti finanziari", "SP_liabilities"): "bs.nfp.net_debt",
    ("Altre passività correnti", "SP_liabilities"): "bs.nwc.other_current_liab",
    ("Fondi rischi", "SP_liabilities"): "bs.provisions.legal_other.balance_close",
    # SP equity
    ("Capitale sociale", "SP_equity"): "bs.equity.share_capital.close",
    ("Riserve e utili a nuovo", "SP_equity"): "bs.equity.retained_earnings.close",
}


@dataclass(frozen=True)
class DemoLoadResult:
    project_id: str
    snapshot_id: str
    balance_id: str
    voice_count: int
    mapping_count: int
    method_config_count: int


def _read_sample_bytes() -> bytes:
    if not _SAMPLE_PATH.exists():
        raise FileNotFoundError(
            f"Sample dataset not found at {_SAMPLE_PATH}. "
            f"Run scripts/build_sample_data.py to regenerate it."
        )
    return _SAMPLE_PATH.read_bytes()


def _seed_mappings(db: Session, project_id: str) -> int:
    rows = [
        Mapping(
            project_id=project_id,
            voice_user_label=label,
            voice_user_section=section,
            voice_id=voice_id,
            confidence=1.0,
            confirmed_by_user=True,
        )
        for (label, section), voice_id in SAMPLE_MAPPINGS.items()
    ]
    db.add_all(rows)
    db.flush()
    return len(rows)


def _seed_method_configs(
    db: Session, project_id: str, registries: Registries
) -> int:
    """Materialise registry-default methods for every mapped voice.

    Voices whose ``default_method`` resolves to ``None`` (sentinels or
    null values) are skipped — the engine handles the absence the same
    way it would for an unmapped voice.
    """
    seen: set[str] = set()
    count = 0
    for voice_id in SAMPLE_MAPPINGS.values():
        if voice_id in seen:
            continue
        seen.add(voice_id)
        voice = registries.voices.get(voice_id)
        if voice is None:
            continue
        method_id = resolve_default_method(voice)
        if method_id is None:
            continue
        tech_code = resolve_method_tech_code(method_id, registries)
        db.add(
            MethodConfig(
                project_id=project_id,
                voice_id=voice_id,
                method_id=method_id,
                method_technical_code=tech_code,
                is_default=True,
                source=SOURCE_REGISTRY_DEFAULT,
            )
        )
        count += 1
    db.flush()
    return count


def load_sample_project(
    db: Session,
    registries: Registries,
    *,
    project_name: str = "Demo Industrial (tier2)",
    sector_pack: str = "industrial",
) -> DemoLoadResult:
    """Create and run a fully-wired demo project.

    Returns a :class:`DemoLoadResult` carrying the new ids. Caller
    owns the commit boundary (the route layer commits once at the end).
    """
    project = Project(
        name=project_name,
        company_name="Demo Industrial S.p.A.",
        sector_pack=sector_pack,
        currency="EUR",
        accounting_standard="IFRS",
        horizon_years=3,
        tier_level="tier2",
    )
    db.add(project)
    db.flush()

    file_bytes = _read_sample_bytes()
    parsed = parse_balance(
        file_bytes=file_bytes,
        filename=SAMPLE_FILENAME,
        source_type="gestionale",
    )
    balance = replace_active_balance(db, project.id, parsed)
    db.flush()

    mapping_count = _seed_mappings(db, project.id)
    method_count = _seed_method_configs(db, project.id, registries)

    # M5/M6/M8 pre-engine pipeline: validation → KPIs → quality score →
    # assumption defaults. Mirrors the order the UI walks through and
    # populates the rows the engine reads on startup.
    mapped = resolve_mapped_values(db, project.id)
    validation_report = run_historical_validation(mapped, registries, project)
    upsert_validation_report(
        db, project.id, "historical", validation_report
    )
    kpi_snapshot = compute_historical_kpis(mapped, registries)
    replace_historical_kpis(db, project.id, kpi_snapshot)
    quality_result = compute_quality_score(
        mapped, validation_report, registries, project.tier_level
    )
    upsert_quality_score(db, project.id, quality_result)
    populate_defaults(db, project.id, registries)
    db.flush()

    result = run_engine(project.id, db, registries)
    state: Any = result.final_state
    snapshot = create_snapshot(
        db,
        project_id=project.id,
        run_timestamp=result.run_timestamp,
        status=result.status,
        duration_ms=result.duration_ms,
        validation_summary=build_validation_summary(state),
        validation_issues=serialise_validation_issues(state),
        approximation_log=list(result.approximation_log),
        pl_data=result.pl_data,
        sp_data=result.sp_data,
        cf_data=result.cf_data,
        projected_kpis=result.projected_kpis,
        error_message=None,
        values=build_snapshot_values(state),
    )
    db.flush()

    return DemoLoadResult(
        project_id=project.id,
        snapshot_id=snapshot.id,
        balance_id=balance.id,
        voice_count=parsed.voice_count,
        mapping_count=mapping_count,
        method_config_count=method_count,
    )


__all__ = [
    "DemoLoadResult",
    "SAMPLE_FILENAME",
    "SAMPLE_MAPPINGS",
    "load_sample_project",
]
