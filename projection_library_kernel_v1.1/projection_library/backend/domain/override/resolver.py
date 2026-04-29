"""Override resolver: load + propagate + one_shot suppression (M11).

Wire-up of the overlay pattern described in
``ARCHITECTURE.md`` §"Override layer pattern":

* :func:`load_active_overrides_into_state` hydrates
  ``state.overrides`` with the currently-active rows for a project.
  Once those are in place, every phase that reads inputs through
  :func:`backend.domain.engine.value_resolver.resolve_voice_value`
  composes the deltas automatically — that is the *organic*
  propagation path.

* :func:`run_with_overrides` runs the engine end-to-end. When at least
  one override has ``nature='one_shot'`` it re-runs the engine without
  the one_shot deltas (the *organic-baseline* run) and then merges the
  two ``base_values`` maps via :func:`apply_one_shot_suppression` so
  that voices outside the policy's ``one_shot_propagation_targets``
  keep their organic-baseline value (cash + the explicit targets
  always reflect the full delta because they're written by the
  full-overrides run).

* The propagation fixed-point loop the spec calls out is *implicit*
  in the engine's year-by-year sequencing: every phase reads via
  ``resolve_voice_value``, so a single full engine pass already
  converges. We still cap at :data:`PROPAGATION_MAX_ITER` as a guard
  for any future iterative refinement on top of the merged state.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import replace
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.engine.value_resolver import ModelState, Override
from backend.domain.override.policy import resolve_policy_class
from backend.infrastructure.db.models import Override as OverrideRow

logger = logging.getLogger(__name__)


# Spec cap on the propagation fixed-point loop (Flow 09 §"Pattern
# execution con override"). Single-pass rerun already converges at
# pilot scale; keeping the cap lets future refinements iterate without
# changing the public surface.
PROPAGATION_MAX_ITER: int = 10


# ---------------------------------------------------------------------------
# DB → state
# ---------------------------------------------------------------------------


def load_active_overrides_into_state(
    db: Session, project_id: str, state: ModelState
) -> ModelState:
    """Replace ``state.overrides`` with the currently-active rows.

    Idempotent: callable both inside ``build_initial_state`` and after
    any user mutation (POST/PATCH/DELETE) without leaving stale entries.
    Only ``is_active=True`` rows are pushed; deactivated rows stay in
    DB for audit but contribute zero delta on the next run.
    """
    rows = db.execute(
        select(OverrideRow).where(
            OverrideRow.project_id == project_id,
            OverrideRow.is_active.is_(True),
        )
    ).scalars().all()

    state.overrides = [
        Override(
            voice_id=row.voice_id,
            year=row.year,
            delta_amount=float(row.delta_amount),
            is_active=True,
            nature=row.nature,
        )
        for row in rows
    ]
    return state


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------


def voice_matches_targets(voice_id: str, targets: Iterable[str]) -> bool:
    """Return True when ``voice_id`` matches any of the glob-style targets."""
    return any(fnmatch.fnmatchcase(voice_id, p) for p in targets)


def _expand_one_shot_target_universe(
    overrides: Iterable[Override],
    registries: Any,
    voice_universe: Iterable[str],
) -> set[str]:
    """Return the set of voice_ids that ``one_shot`` overrides should
    keep at their full-overrides value.

    Includes:
    * the override voice itself (the user explicitly applied a delta on it),
    * every voice in the policy's ``one_shot_propagation_targets``
      (cash + any policy-specific carve-outs like
      ``bs.fa.tangible.gross_close`` for capex).

    All other voices are reset to their organic-baseline value, so the
    one_shot delta does not leak into upstream cogs / opex / NWC / tax.
    """
    keep: set[str] = set()
    universe = list(voice_universe)
    for ov in overrides:
        if ov.nature != "one_shot":
            continue
        keep.add(ov.voice_id)
        match = resolve_policy_class(ov.voice_id, registries)
        if match is None:
            continue
        for pattern in match.one_shot_targets:
            for voice_id in universe:
                if fnmatch.fnmatchcase(voice_id, pattern):
                    keep.add(voice_id)
    return keep


def apply_one_shot_suppression(
    *,
    state_full: ModelState,
    state_organic: ModelState,
    overrides: Iterable[Override],
    registries: Any,
) -> ModelState:
    """Merge ``state_organic`` into ``state_full`` for non-target voices.

    ``state_full`` is the run with every override active; ``state_organic``
    is the run with the one_shot overrides held back. For voices outside
    the union of one_shot propagation targets, replace
    ``state_full.base_values[voice][year]`` with the organic-baseline
    value — the one_shot delta no longer propagates into them.

    Cash (``bs.nfp.cash``) is in every policy's
    ``one_shot_propagation_targets``, so it always survives the merge
    with the full-overrides number; the CF identity in E8 has already
    absorbed every active delta on read.
    """
    overrides_list = list(overrides)
    one_shot_present = any(ov.nature == "one_shot" for ov in overrides_list)
    if not one_shot_present:
        return state_full

    voice_universe = set(state_full.base_values.keys()) | set(
        state_organic.base_values.keys()
    )
    keep = _expand_one_shot_target_universe(
        overrides_list, registries, voice_universe
    )

    for voice_id, by_year in state_organic.base_values.items():
        if voice_id in keep:
            continue
        target = state_full.base_values.setdefault(voice_id, {})
        for year, organic_value in by_year.items():
            target[year] = organic_value

    logger.info(
        "override one_shot suppression: kept=%d voices, reset=%d voices",
        len(keep),
        len(voice_universe) - len(keep),
    )
    return state_full


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def _strip_one_shot(overrides: list[Override]) -> list[Override]:
    return [ov for ov in overrides if ov.nature != "one_shot"]


def run_with_overrides(
    project_id: str,
    db: Session,
    registries: Any,
    *,
    run_engine_fn: Callable[..., Any] | None = None,
):
    """Run the engine with overrides applied.

    Always runs once (``state_full``) with every active override loaded
    via the overlay; that single pass implements organic propagation.
    When at least one active override is ``one_shot``, runs the engine
    a second time after stripping the one_shot deltas
    (``state_organic``) and merges the two states with
    :func:`apply_one_shot_suppression`.

    ``run_engine_fn`` is injectable for tests; the default deferred
    import keeps :mod:`backend.domain.override` independent of the
    engine package at module-load time (the engine imports
    :func:`load_active_overrides_into_state`, so a top-level reverse
    import would close a cycle).
    """
    if run_engine_fn is None:
        from backend.domain.engine.executor import run_engine  # noqa: WPS433

        run_engine_fn = run_engine

    result_full = run_engine_fn(project_id, db, registries)
    state_full = result_full.final_state
    if state_full is None:
        return result_full

    has_one_shot = any(ov.nature == "one_shot" for ov in state_full.overrides)
    if not has_one_shot:
        return result_full

    # Re-run with one_shot deltas stripped. We rebuild the state from
    # scratch via run_engine_fn to avoid sharing mutable maps with the
    # full-overrides run, then put the stripped override list back in.
    organic_only = _strip_one_shot(state_full.overrides)
    result_organic = run_engine_fn(
        project_id,
        db,
        registries,
        overrides_override=organic_only,
    )
    state_organic = result_organic.final_state
    if state_organic is None:
        return result_full

    apply_one_shot_suppression(
        state_full=state_full,
        state_organic=state_organic,
        overrides=state_full.overrides,
        registries=registries,
    )
    # ProjectionResult is a dataclass; rebuild so callers see the
    # merged final_state without mutating other fields.
    return replace(result_full, final_state=state_full)


__all__ = [
    "PROPAGATION_MAX_ITER",
    "apply_one_shot_suppression",
    "load_active_overrides_into_state",
    "run_with_overrides",
    "voice_matches_targets",
]
