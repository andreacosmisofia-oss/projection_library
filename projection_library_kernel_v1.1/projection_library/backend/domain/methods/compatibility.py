"""Driver requirements derived from method configs (M7).

The method registry encodes driver dependencies inside ``formula_python``
strings rather than via a declarative ``inputs.drivers`` field. Two
patterns appear:

* **Voice-scoped** — ``drivers[f'driver.{voice}.<key>'][year]``: the
  ``driver_id`` is composed at runtime from the voice the method is
  applied to. Example: ``driver.pl.cogs.labour.direct.headcount`` for
  the ``headcount_unit_cost`` method on ``pl.cogs.labour.direct``.
* **Global literal** — ``drivers['driver.<scope>.<key>'][year]``: the
  ``driver_id`` is a fixed string regardless of the host voice.
  Examples: ``driver.headcount.total``, ``driver.saas.new_arr``.

This module extracts both patterns via regex and aggregates them per
``driver_id``, deduplicating ``required_by_methods`` and
``required_for_voices``. Pure function: no DB / HTTP coupling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from backend.infrastructure.db.models import MethodConfig
    from backend.infrastructure.registry import Registries


DRIVER_TYPE_SCALAR = "scalar_per_year"
DRIVER_TYPE_STATIC_PARAMETERS = "static_parameters"

# Methods whose driver inputs are not time-varying. The flow lists term
# loan setup as the canonical example. Everything else is treated as
# scalar_per_year for the pilot.
_STATIC_PARAMETER_FAMILIES = frozenset({"debt_schedule"})

# Years required for scalar drivers in the pilot. Matches the canonical
# Y-1 / Y0 historical window used by every sample dataset.
SCALAR_YEARS_REQUIRED: tuple[str, ...] = ("Y-1", "Y0")


# ``drivers[f'driver.{voice}.<key>'][year]`` — voice-scoped. Capture the
# tail key (``headcount``, ``volume``, ``initial_principal``...). The
# inner curly braces are the literal Python f-string syntax stored in the
# YAML formula; we match them verbatim. The key is a simple identifier
# (no nested ``{...}`` placeholders, which exist in a couple of methods
# like ``bom_{m}_qty`` — those are dynamic per-assumption and not exposed
# as required drivers in M7 v1).
_VOICE_DRIVER_RE = re.compile(
    r"drivers\[f['\"]driver\.\{voice\}\.([a-zA-Z0-9_]+)['\"]\]"
)

# ``drivers['driver.<scope>.<...>'][year]`` — literal id, no f-string.
_LITERAL_DRIVER_RE = re.compile(
    r"drivers\[['\"](driver\.[a-zA-Z0-9_.]+)['\"]\]"
)


@dataclass
class RequiredDriver:
    """One aggregated entry produced by :func:`compute_required_drivers`."""

    driver_id: str
    type: str
    required_by_methods: list[str] = field(default_factory=list)
    required_for_voices: list[str] = field(default_factory=list)
    years_required: list[str] = field(default_factory=list)
    unit: str | None = None


def _classify_driver_type(method: dict) -> str:
    """Return ``scalar_per_year`` or ``static_parameters`` from method family.

    Pilot v1.1 only models these two types (``time_series`` and
    ``aging_bucket`` are out of scope). The mapping is intentionally
    coarse: a single method family decides the bucket rather than per
    driver, which matches the granularity of the registry.
    """
    family = method.get("family")
    if family in _STATIC_PARAMETER_FAMILIES:
        return DRIVER_TYPE_STATIC_PARAMETERS
    return DRIVER_TYPE_SCALAR


def _years_for_type(driver_type: str) -> list[str]:
    if driver_type == DRIVER_TYPE_SCALAR:
        return list(SCALAR_YEARS_REQUIRED)
    return []


def _extract_driver_ids(formula: str, voice_id: str) -> list[str]:
    """Return the ``driver_id`` strings referenced by ``formula``."""
    out: list[str] = []
    for key in _VOICE_DRIVER_RE.findall(formula):
        out.append(f"driver.{voice_id}.{key}")
    for literal in _LITERAL_DRIVER_RE.findall(formula):
        out.append(literal)
    return out


def compute_required_drivers(
    method_configs: Iterable["MethodConfig"],
    registries: "Registries",
) -> list[RequiredDriver]:
    """Aggregate the driver requirements for a project's method configs.

    For every ``(voice_id, method_id)`` pair, parse the method's
    ``formula_python`` and collect both voice-scoped and literal
    ``driver_id`` references. Aggregate by ``driver_id``, deduplicating
    ``required_by_methods`` and ``required_for_voices``. Method configs
    pointing at derived rules or at unknown method ids are skipped (a
    derived rule never owns a driver requirement; unknown ids are a
    config drift that the registry loader has already flagged).
    """
    by_driver: dict[str, RequiredDriver] = {}

    for config in method_configs:
        method = registries.methods.get(config.method_id)
        if method is None:
            # Either a derived_rule_id or an unknown method — no driver
            # contribution. The route layer already validates method ids
            # against both registries; we just stay silent here.
            continue
        formula = method.get("formula_python") or ""
        if not formula:
            continue

        driver_type = _classify_driver_type(method)
        years_required = _years_for_type(driver_type)

        for driver_id in _extract_driver_ids(formula, config.voice_id):
            entry = by_driver.get(driver_id)
            if entry is None:
                entry = RequiredDriver(
                    driver_id=driver_id,
                    type=driver_type,
                    required_by_methods=[config.method_id],
                    required_for_voices=[config.voice_id],
                    years_required=list(years_required),
                    unit=None,
                )
                by_driver[driver_id] = entry
                continue
            if config.method_id not in entry.required_by_methods:
                entry.required_by_methods.append(config.method_id)
            if config.voice_id not in entry.required_for_voices:
                entry.required_for_voices.append(config.voice_id)
            # Stable type: if any contributing method is a static
            # parameters family, the aggregated type stays static — the
            # storage shape is incompatible with scalar-per-year, so the
            # stricter form wins. In practice this never happens because
            # static-parameters methods are voice-scoped (term loan).
            if (
                entry.type == DRIVER_TYPE_SCALAR
                and driver_type == DRIVER_TYPE_STATIC_PARAMETERS
            ):
                entry.type = DRIVER_TYPE_STATIC_PARAMETERS
                entry.years_required = []

    # Deterministic ordering: alphabetical on driver_id so the API
    # response (and the UI grouping) is stable across reruns.
    return sorted(by_driver.values(), key=lambda r: r.driver_id)


__all__ = [
    "DRIVER_TYPE_SCALAR",
    "DRIVER_TYPE_STATIC_PARAMETERS",
    "RequiredDriver",
    "SCALAR_YEARS_REQUIRED",
    "compute_required_drivers",
]
