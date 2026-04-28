"""E2 — Fixed assets + D&A + impairment + IP fair value.

~39 voci ``bs.fa.*`` + ``pl.da.*`` + ``pl.impairment.*`` +
``pl.other.fair_value_gain_loss_investment_property``. See
flows/07_engine_execution.md §E2.

Per-voice dispatch:

1. **FA gross_close roll-forward** for tangible / intangible families
   uses ``roll_forward`` against the family's primary capex inflow and
   gross disposals outflow. Other inflows (expansion_capex, M&A) and
   outflows (carve-outs) are computed by their own driver methods and
   stay in ``base_values`` as standalone voices for downstream
   consumption — extending the roll-forward to aggregate them is a
   later milestone.

2. **D&A mid-year convention** for ``pl.da.{ppe|intangibles|rou}``:
   ``-max(0, gross_avg - non_depreciable) / useful_life`` where
   ``gross_avg = (gross_open + gross_close) / 2``. Default useful
   lives: 20 years (PPE), 5 years (intangibles), assumption-only for
   ROU (lease term is project-specific). Both ``useful_life`` and
   ``non_depreciable_pct`` come from
   ``state.assumptions[pl.da.{family}]``; ``non_depreciable_pct`` is
   applied against ``gross_avg`` so the carve-out scales with the
   asset base.

3. **Investment property fair value**: ``fv_close = fv_open +
   revaluation`` where the revaluation amount lives in
   ``assumptions['bs.fa.investment_property.gross_close']
   ['fv_revaluation'][year]``. Unlike depreciable families, IP carries
   no acc_depr leg.

4. **Driver voices** (capex, disposals, acquisitions, etc.) and
   aggregate voices that ship a registry-driven ``default_method``
   fall through to ``dispatch_method`` — the same path as E1.
"""

from __future__ import annotations

import logging

from backend.domain.engine.phases._helpers import dispatch_method, roll_forward
from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


_PHASE_ID = "E2"

# pl.da.{group} -> (FA family path segment, default useful life in years).
# ROU has no static default: lease terms vary per contract, so the
# assumption is required and we fall through to 0.0 if it's missing.
_DA_TO_FA_FAMILY: dict[str, tuple[str, int | None]] = {
    "pl.da.ppe": ("tangible", 20),
    "pl.da.intangibles": ("intangible", 5),
    "pl.da.rou": ("rou", None),
}

_IP_VOICE = "bs.fa.investment_property.gross_close"
_IP_FV_GAIN_VOICE = "pl.other.fair_value_gain_loss_investment_property"


def phase_e2(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E2 year=%s", year)

    if state.registries is None:
        return state

    voices = getattr(state.registries, "voices", None) or {}
    voice_ids = [
        vid
        for vid, meta in voices.items()
        if meta.get("calc_phase_final") == _PHASE_ID
    ]

    for voice_id in voice_ids:
        value = _compute_voice(voice_id, year, state)
        if value is None:
            continue
        state.base_values.setdefault(voice_id, {})[year] = value

    return state


def _compute_voice(voice_id: str, year: str, state: ModelState) -> float | None:
    if voice_id == "bs.fa.tangible.gross_close":
        return roll_forward(
            voice_id,
            year,
            state,
            additions_voice="bs.fa.tangible.maintenance_capex",
            disposals_voice="bs.fa.tangible.disposals_gross",
        )

    if voice_id == "bs.fa.intangible.gross_close":
        return roll_forward(
            voice_id,
            year,
            state,
            additions_voice="bs.fa.intangible.software_capex",
            disposals_voice="bs.fa.intangible.disposals_gross",
        )

    if voice_id == _IP_VOICE:
        return _ip_fv_close(year, state)

    if voice_id == _IP_FV_GAIN_VOICE:
        return _ip_fv_gain(year, state)

    if voice_id in _DA_TO_FA_FAMILY:
        return _da_mid_year(voice_id, year, state)

    # Driver voices and aggregate voices with registry defaults
    # (capex, disposals, acc_depr_close via R_DRV_015, etc.)
    return dispatch_method(voice_id, year, state)


def _ip_fv_close(year: str, state: ModelState) -> float:
    prev = get_prev_year(year)
    fv_open = resolve_voice_value(_IP_VOICE, prev, state)
    revaluation = (
        state.assumptions.get(_IP_VOICE, {})
        .get("fv_revaluation", {})
        .get(year, 0.0)
    )
    return fv_open + revaluation


def _ip_fv_gain(year: str, state: ModelState) -> float:
    """The P&L line mirrors the IP revaluation booked on the BS."""
    return (
        state.assumptions.get(_IP_VOICE, {})
        .get("fv_revaluation", {})
        .get(year, 0.0)
    )


def _da_mid_year(voice_id: str, year: str, state: ModelState) -> float:
    fa_family, default_useful_life = _DA_TO_FA_FAMILY[voice_id]
    gross_voice = f"bs.fa.{fa_family}.gross_close"
    prev = get_prev_year(year)

    gross_open = resolve_voice_value(gross_voice, prev, state)
    gross_close = resolve_voice_value(gross_voice, year, state)
    gross_avg = (gross_open + gross_close) / 2

    voice_assumptions = state.assumptions.get(voice_id, {})
    useful_life = voice_assumptions.get("useful_life", {}).get(
        year, default_useful_life
    )
    if useful_life is None or useful_life <= 0:
        return 0.0

    non_depreciable_pct = voice_assumptions.get("non_depreciable_pct", {}).get(
        year, 0.0
    )
    non_depreciable_value = gross_avg * non_depreciable_pct

    return -max(0.0, gross_avg - non_depreciable_value) / useful_life


__all__ = ["phase_e2"]
