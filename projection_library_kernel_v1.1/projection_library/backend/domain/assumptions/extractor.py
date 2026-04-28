"""Assumption-name extraction from ``formula_python`` (M8).

The method registry does not expose a first-class ``assumptions:`` field
(see ``data_contracts/registries/method_registry.schema.json``); the
parameter names a method consumes are encoded inside the
``formula_python`` expression as ``assumptions[voice]['<name>'][year]``.
This module scans those expressions with a focused regex, mirroring the
M7 driver extractor (`backend/domain/drivers/extractor.py`).

Two reference shapes are recognised:

* ``assumptions[voice]['name']``        — literal name
* ``assumptions[voice][f'name_{x}']``   — parameterised on a runtime
  index (e.g. ``f'bom_{m}_price'``); the survivor placeholder is
  surfaced separately so the populator can skip it (the user shouldn't
  be asked for an assumption with ``{m}`` in its name).

The ``infer_validation_range`` helper applies a coarse heuristic on the
assumption name to seed ``validation_range``. The flow doc (§3) treats
``RP_xxx`` as runtime warnings — non-blocking — so a wrong guess never
prevents a user from saving a value; it just won't surface a warning
icon for that one parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from backend.infrastructure.registry import Registries


# Captures the inner string of ``assumptions[voice][...]``. Both quoted
# styles and the ``f''`` prefix are accepted — the latter is how the
# registry expresses parameterised names. The first group is the quote
# character (back-referenced to close), the second is the raw template.
_ASSUMPTION_LOOKUP_RE = re.compile(
    r"assumptions\[voice\]\[\s*f?(['\"])([^'\"]+)\1\s*\]"
)

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


# ---------------------------------------------------------------------------
# Validation range heuristic
# ---------------------------------------------------------------------------


# Suffix / token tables used to guess plausibility ranges at write time.
# The mapping is intentionally small — the user-facing warning is
# non-blocking, so a missing entry just yields ``None`` (no warning at
# all for that parameter, which is a softer failure mode than a wrong
# range).
_PCT_LIKE_TOKENS: frozenset[str] = frozenset(
    {
        "pct",
        "rate",
        "ecl_rate",
        "vat_rate",
        "warranty_rate",
        "payout",
        "utilization_rate",
        "load_factor",
        "retention_rate",
        "renewal_rate",
        "conversion_rate",
        "partial_conversion_rate",
        "b2b_ratio",
        "turnover",
        "win_rate",
        "probability",
        "uplift",
        "drift_progress",
        "pct_start",
        "pct_target",
    }
)

_GROWTH_LIKE_TOKENS: frozenset[str] = frozenset(
    {
        "growth_rate",
        "cagr",
        "drift",
        "cpi_rate",
        "volume_growth",
        "price_growth",
    }
)

_DAYS_LIKE_TOKENS: frozenset[str] = frozenset(
    {
        "days",
        "days_start",
        "days_target",
        "cycle_days",
        "dso",
        "dpo",
        "dio",
        "avg_periods_unpaid",
    }
)


@dataclass(frozen=True)
class AssumptionRef:
    """One assumption parameter referenced by a method's formula.

    ``parameterized`` is True when the resolved name still carries a
    ``{...}`` placeholder (e.g. ``bom_{m}_price``). The route surfaces
    those separately so the UI can skip them — they only resolve at
    runtime once the user provides the index list (e.g. via a driver).
    """

    name: str
    parameterized: bool = False
    unresolved_placeholders: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Low-level extraction
# ---------------------------------------------------------------------------


def _iter_raw_assumption_refs(formula_python: str) -> Iterable[str]:
    if not formula_python:
        return
    for match in _ASSUMPTION_LOOKUP_RE.finditer(formula_python):
        yield match.group(2)


def _placeholders_in(template: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(template)


def extract_assumption_refs_from_formula(
    formula_python: str | None,
) -> list[AssumptionRef]:
    """Return one :class:`AssumptionRef` per *distinct* parameter name.

    Order-preserving deduplication: the first occurrence wins so the
    registry author's reading order shows up in the UI unchanged. The
    caller is expected to be a single ``(voice_id, method_id)`` pair —
    voice substitution isn't applied here because the registry uses
    ``assumptions[voice][...]`` (literal token ``voice``) as the
    addressing convention; the *value* of ``voice`` is the row key in
    persistence, not a substitution target inside the name.
    """
    if not formula_python:
        return []
    seen: set[str] = set()
    out: list[AssumptionRef] = []
    for raw in _iter_raw_assumption_refs(formula_python):
        if raw in seen:
            continue
        seen.add(raw)
        unresolved = tuple(_placeholders_in(raw))
        out.append(
            AssumptionRef(
                name=raw,
                parameterized=bool(unresolved),
                unresolved_placeholders=unresolved,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Method-id → list of assumption refs
# ---------------------------------------------------------------------------


def _formula_for_method(
    method_id: str, registries: "Registries"
) -> str | None:
    """Look up ``formula_python`` for a method or derived rule id.

    Mirrors :func:`backend.domain.drivers.extractor._formula_for_method`
    so the M8 layer behaves consistently with M7 when the user has
    selected a derived rule as the projection method (some voices, e.g.
    pl.gross_profit, project via a derived_rule).
    """
    method = registries.methods.get(method_id)
    if method is not None:
        return method.get("formula_python")
    derived = registries.derived_rules.get(method_id)
    if derived is not None:
        return derived.get("formula_python")
    return None


def assumption_refs_for_method(
    method_id: str, registries: "Registries"
) -> list[AssumptionRef]:
    """Convenience: pull the formula and extract refs in one call."""
    return extract_assumption_refs_from_formula(
        _formula_for_method(method_id, registries)
    )


# ---------------------------------------------------------------------------
# Validation range heuristic
# ---------------------------------------------------------------------------


def infer_validation_range(
    assumption_name: str,
) -> tuple[float | None, float | None]:
    """Best-effort plausibility range from the assumption name alone.

    Returns ``(None, None)`` when the name doesn't match any known
    bucket — the route layer treats that as "no range", which yields
    ``validation_status=ok`` regardless of the value. The buckets are:

    * growth-like (e.g. ``growth_rate``, ``cagr``, ``drift``):
      ``[-0.50, 2.00]`` (mirrors RP_001/RP_022).
    * pct-like (e.g. ``pct``, ``payout``, ``*_rate``): ``[0.0, 1.0]``.
    * days-like (e.g. ``days``, ``cycle_days``, ``dso``): ``[0.0, 730.0]``
      (matches RP_004/RP_005 envelopes).
    """
    if not assumption_name:
        return (None, None)

    # Exact-token match wins (handles `pct`, `cagr`, `dso`, etc.).
    if assumption_name in _GROWTH_LIKE_TOKENS:
        return (-0.50, 2.00)
    if assumption_name in _PCT_LIKE_TOKENS:
        return (0.0, 1.0)
    if assumption_name in _DAYS_LIKE_TOKENS:
        return (0.0, 730.0)

    # Suffix-based fallback for compound names (e.g. ``bom_X_price``,
    # ``win_rate_qualified``, ``case_3_probability``).
    suffix = assumption_name.rsplit("_", 1)[-1]
    if suffix in {"rate", "pct", "probability", "ratio"}:
        return (0.0, 1.0)
    if suffix in {"growth", "cagr", "drift"}:
        return (-0.50, 2.00)
    if suffix in {"days"}:
        return (0.0, 730.0)

    # Substring match as a last resort — cheap and good enough for the
    # pilot. Matches names like ``volume_growth`` or ``price_growth``
    # that aren't covered by the exact-token table because the prefix
    # changes the token shape.
    for token in _GROWTH_LIKE_TOKENS:
        if token in assumption_name:
            return (-0.50, 2.00)
    for token in _PCT_LIKE_TOKENS:
        if token in assumption_name:
            return (0.0, 1.0)
    for token in _DAYS_LIKE_TOKENS:
        if token in assumption_name:
            return (0.0, 730.0)

    return (None, None)


__all__ = [
    "AssumptionRef",
    "assumption_refs_for_method",
    "extract_assumption_refs_from_formula",
    "infer_validation_range",
]
