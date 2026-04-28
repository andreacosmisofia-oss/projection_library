"""E5 — Provisions + Employee benefits.

~19 voci ``bs.provisions.{family}.*`` (4 famiglie: warranty,
restructuring, legal_other, other) + ``bs.employee_benefits.*`` +
re-aggregato ``pl.provisions.total`` / ``pl.ebitda``. See
flows/07_engine_execution.md §E5.

Sequence:

1. dispatch_method runs over every E5 voice via the registry —
   driver flows like ``bs.provisions.warranty.usage`` get whatever
   their default method computes. The explicit logic below
   overwrites the voices that need a roll-forward.

2. Provisions roll-forward, per family:
       balance_close = balance_open + accrual - usage - releases
   ``accrual`` comes either from
   ``state.assumptions['bs.provisions.{family}']['accrual'][year]``
   or from the ``pct_revenue`` shortcut
   (``pct × abs(pl.rev.net[year])``). Usage and releases default to
   0 when the assumption is missing. The corresponding P&L line
   ``pl.provisions.{family}`` carries the cost as a negative number
   (``-abs(accrual)``); ``pl.provisions.total`` and
   ``bs.provisions.total_close`` are aggregated last.

3. Employee benefits roll-forward (IAS 19 simplified):
       balance_close = balance_open + service_cost + interest_cost
                       - payments + actuarial
   where:
       service_cost  = pct_labour  × |pl.opex.labour.total[year]|
       interest_cost = rate         × |balance_open|       (sub-circular proxy)
       payments      = pct_turnover × |balance_open|
       actuarial     = assumption (default 0, seeded into bs.equity.oci_actuarial)
   The same logic is applied sign-agnostically: balances are
   ``abs()``-wrapped before the rate so the helper doesn't depend on
   whether the registry stores liabilities as negative or positive.

4. ``pl.ebitda`` is re-aggregated with the updated
   ``pl.provisions.total`` so the final value reflects E5.
   Re-aggregation reads ``pl.gross_profit`` (final from E3 / E3.1)
   directly so it stays consistent with whatever those phases left.
"""

from __future__ import annotations

import logging

from backend.domain.engine.phases._helpers import dispatch_method
from backend.domain.engine.value_resolver import (
    ModelState,
    get_prev_year,
    resolve_voice_value,
)

logger = logging.getLogger(__name__)


_PHASE_ID = "E5"

_PROVISION_FAMILIES: tuple[str, ...] = (
    "warranty",
    "restructuring",
    "legal_other",
    "other",
)

_EB_BALANCE = "bs.employee_benefits.balance_close"
_EB_SERVICE = "bs.employee_benefits.service_cost"
_EB_INTEREST = "bs.employee_benefits.interest_cost"
_EB_PAYMENTS = "bs.employee_benefits.payments_to_employees"
_EB_ACTUARIAL = "bs.employee_benefits.actuarial_changes"
_OCI_ACTUARIAL = "bs.equity.oci_actuarial"

_DEFAULT_EB_RATE = 0.03


def phase_e5(state: ModelState) -> ModelState:
    year = state.current_year
    logger.info("phase E5 year=%s", year)

    # Pass 1: registry-driven dispatch for every E5 voice (driver
    # methods like warranty.usage get their default values written).
    if state.registries is not None:
        voices = getattr(state.registries, "voices", None) or {}
        voice_ids = [
            vid
            for vid, meta in voices.items()
            if meta.get("calc_phase_final") == _PHASE_ID
        ]
        for vid in voice_ids:
            value = dispatch_method(vid, year, state)
            if value is None:
                continue
            state.base_values.setdefault(vid, {})[year] = value

    # Pass 2: explicit provisions roll-forward (overwrites P&L + BS).
    _process_provisions(year, state)

    # Pass 3: explicit employee benefits roll-forward.
    _process_employee_benefits(year, state)

    # Pass 4: re-aggregate pl.ebitda with the updated pl.provisions.total.
    _update_ebitda(year, state)

    return state


# ---------------------------------------------------------------------------
# Provisions
# ---------------------------------------------------------------------------


def _process_provisions(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)

    for family in _PROVISION_FAMILIES:
        balance_voice = f"bs.provisions.{family}.balance_close"
        pl_voice = f"pl.provisions.{family}"

        accrual = _resolve_provision_accrual(family, year, state)
        usage = _provision_assumption(family, "usage", year, state)
        releases = _provision_assumption(family, "releases", year, state)

        balance_open = resolve_voice_value(balance_voice, prev, state)
        balance_close = (
            balance_open + abs(accrual) - abs(usage) - abs(releases)
        )

        state.base_values.setdefault(balance_voice, {})[year] = balance_close
        state.base_values.setdefault(pl_voice, {})[year] = -abs(accrual)

    # pl.provisions.total = sum of P&L family accruals (already signed negative)
    pl_total = sum(
        state.base_values.get(f"pl.provisions.{f}", {}).get(year, 0.0)
        for f in _PROVISION_FAMILIES
    )
    state.base_values.setdefault("pl.provisions.total", {})[year] = pl_total

    # bs.provisions.total_close = sum of BS family closes
    bs_total = sum(
        state.base_values.get(f"bs.provisions.{f}.balance_close", {}).get(year, 0.0)
        for f in _PROVISION_FAMILIES
    )
    state.base_values.setdefault("bs.provisions.total_close", {})[year] = bs_total


def _resolve_provision_accrual(
    family: str, year: str, state: ModelState
) -> float:
    """Direct accrual amount; fallback to ``pct_revenue × |pl.rev.net|``."""
    cfg = state.assumptions.get(f"bs.provisions.{family}", {})

    direct = cfg.get("accrual", {}).get(year)
    if direct is not None:
        return float(direct)

    pct = cfg.get("pct_revenue", {}).get(year)
    if pct is not None:
        rev_net = resolve_voice_value("pl.rev.net", year, state)
        return pct * abs(rev_net)

    return 0.0


def _provision_assumption(
    family: str, key: str, year: str, state: ModelState
) -> float:
    return float(
        state.assumptions.get(f"bs.provisions.{family}", {})
        .get(key, {})
        .get(year, 0.0)
    )


# ---------------------------------------------------------------------------
# Employee benefits
# ---------------------------------------------------------------------------


def _process_employee_benefits(year: str, state: ModelState) -> None:
    prev = get_prev_year(year)
    cfg = state.assumptions.get(_EB_BALANCE, {})

    pct_labour = cfg.get("pct_labour", {}).get(year, 0.0)
    rate = cfg.get("rate", {}).get(year, _DEFAULT_EB_RATE)
    pct_turnover = cfg.get("pct_turnover", {}).get(year, 0.0)
    actuarial = float(cfg.get("actuarial", {}).get(year, 0.0))

    balance_open = resolve_voice_value(_EB_BALANCE, prev, state)
    open_magnitude = abs(balance_open)

    labour_total = abs(resolve_voice_value("pl.opex.labour.total", year, state))

    service_cost = pct_labour * labour_total
    interest_cost = rate * open_magnitude
    payments = pct_turnover * open_magnitude

    balance_close = (
        balance_open + service_cost + interest_cost - payments + actuarial
    )

    state.base_values.setdefault(_EB_SERVICE, {})[year] = service_cost
    state.base_values.setdefault(_EB_INTEREST, {})[year] = interest_cost
    state.base_values.setdefault(_EB_PAYMENTS, {})[year] = -payments
    state.base_values.setdefault(_EB_ACTUARIAL, {})[year] = actuarial
    state.base_values.setdefault(_EB_BALANCE, {})[year] = balance_close

    # OCI seed for E6. The voice id is intentionally outside the registry
    # for now; E6 will pick it up via base_values lookup.
    state.base_values.setdefault(_OCI_ACTUARIAL, {})[year] = actuarial


# ---------------------------------------------------------------------------
# pl.ebitda re-aggregation
# ---------------------------------------------------------------------------


def _update_ebitda(year: str, state: ModelState) -> None:
    gross_profit = resolve_voice_value("pl.gross_profit", year, state)
    opex_total = resolve_voice_value("pl.opex.total", year, state)
    provisions_total = resolve_voice_value("pl.provisions.total", year, state)
    state.base_values.setdefault("pl.ebitda", {})[year] = (
        gross_profit + opex_total + provisions_total
    )


__all__ = ["phase_e5"]
