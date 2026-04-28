"""Driver requirement extraction (M7).

A method's ``formula_python`` is the single source of truth for which
historical drivers it consumes. This module scans those expressions
with a focused regex, normalises the resolved ``driver_id`` against the
voice that owns the formula, and aggregates the result into a per-
project requirement list.

Two reference shapes are recognised:

* ``drivers['driver.foo.bar']``         — literal id
* ``drivers[f'driver.{voice}.suffix']`` — templated on the owning voice
* ``resolve('driver.foo', year)``       — same lookup, different syntax
* ``resolve(f'driver.{voice}.x', year)``

After substituting ``{voice}`` with the owning voice, an id that still
contains ``{...}`` is *parameterized* (e.g. ``driver.{voice}.bom_{m}_qty``
where ``m`` only resolves at runtime from assumptions). M7 surfaces
those as a flagged side-channel rather than as collectable rows; the
default required-list is the fully resolved ids the user can actually
enter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from backend.infrastructure.registry import Registries


DRIVER_PREFIX = "driver."

DRIVER_TYPE_SCALAR_PER_YEAR = "scalar_per_year"
DRIVER_TYPE_STATIC_PARAMETERS = "static_parameters"
DRIVER_TYPE_TIME_SERIES = "time_series"
DRIVER_TYPE_AGING_BUCKET = "aging_bucket"

STATUS_MISSING = "missing"
STATUS_PARTIAL = "partial"
STATUS_COMPLETE = "complete"
STATUS_SKIPPED = "skipped"


# Suffix tokens that, when present in a driver_id, point at the
# static_parameters family. Heuristics, not authoritative — the upload
# endpoint accepts whatever ``type`` the client supplies.
_STATIC_PARAMETER_SUFFIXES: frozenset[str] = frozenset(
    {
        "parameters",
        "initial_principal",
        "term_years",
        "rate",
        "remaining_years",
    }
)

_TIME_SERIES_SUFFIXES: frozenset[str] = frozenset({"cohort_data"})

_AGING_BUCKET_SUFFIXES: frozenset[str] = frozenset({"aging", "aging_buckets"})


# Captures both ``drivers['…']`` / ``drivers["…"]`` (with optional
# ``f``-prefix on the literal) and ``resolve('driver.…', …)``. The
# inner group is the raw string between the quotes — left intact so
# the caller can decide how to substitute templates.
_DRIVERS_LOOKUP_RE = re.compile(
    r"drivers\[\s*f?(['\"])([^'\"]+)\1\s*\]"
)
_RESOLVE_DRIVER_RE = re.compile(
    r"resolve\(\s*f?(['\"])(driver\.[^'\"]+)\1\s*,"
)


@dataclass(frozen=True)
class DriverRequirement:
    """One historical driver a project must collect.

    ``parameterized`` is True when the resolved id still carries a
    ``{...}`` placeholder after substituting ``{voice}`` (e.g. nested
    cohort indices). The route layer surfaces those separately so the
    UI can warn rather than asking the user to type a literal id with
    a template in it.
    """

    driver_id: str
    type: str
    required_by_methods: tuple[str, ...] = ()
    required_for_voices: tuple[str, ...] = ()
    parameterized: bool = False
    unresolved_placeholders: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Low-level extraction
# ---------------------------------------------------------------------------


def _iter_raw_driver_refs(formula_python: str) -> Iterable[str]:
    """Yield every quoted string that targets a driver lookup.

    The lookups can repeat inside a single formula (``sum(...)``,
    composite expressions); duplicates are not deduplicated here so the
    caller can decide on aggregation.
    """
    if not formula_python:
        return
    for match in _DRIVERS_LOOKUP_RE.finditer(formula_python):
        raw = match.group(2)
        if raw.startswith(DRIVER_PREFIX):
            yield raw
    for match in _RESOLVE_DRIVER_RE.finditer(formula_python):
        yield match.group(2)


def _substitute_voice(template: str, voice_id: str) -> str:
    """Replace ``{voice}`` (the only first-class placeholder) with the
    owning voice's id. Other ``{...}`` survive unchanged so the caller
    can detect them as runtime-parameterized."""
    return template.replace("{voice}", voice_id)


_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _placeholders_in(template: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(template)


def extract_driver_refs_from_formula(
    formula_python: str | None, voice_id: str
) -> list[tuple[str, bool, tuple[str, ...]]]:
    """Return ``(resolved_id, parameterized, unresolved_placeholders)`` triples.

    ``resolved_id`` has ``{voice}`` substituted with ``voice_id``. If
    additional ``{...}`` placeholders survive, ``parameterized`` is
    True and the surviving names are returned for diagnostics.
    Order-preserving deduplication: the first occurrence wins.
    """
    if not formula_python:
        return []
    seen: set[str] = set()
    out: list[tuple[str, bool, tuple[str, ...]]] = []
    for raw in _iter_raw_driver_refs(formula_python):
        resolved = _substitute_voice(raw, voice_id)
        unresolved = tuple(_placeholders_in(resolved))
        parameterized = bool(unresolved)
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append((resolved, parameterized, unresolved))
    return out


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


def infer_driver_type(driver_id: str) -> str:
    """Best-effort guess of the driver category from its id.

    Used only as the default the API returns alongside the requirement
    list — the upload endpoint accepts whatever ``type`` the client
    sends, so a wrong guess never blocks an intake.
    """
    suffix = driver_id.rsplit(".", 1)[-1] if "." in driver_id else driver_id
    if suffix in _STATIC_PARAMETER_SUFFIXES:
        return DRIVER_TYPE_STATIC_PARAMETERS
    if suffix in _TIME_SERIES_SUFFIXES:
        return DRIVER_TYPE_TIME_SERIES
    if suffix in _AGING_BUCKET_SUFFIXES:
        return DRIVER_TYPE_AGING_BUCKET
    return DRIVER_TYPE_SCALAR_PER_YEAR


# ---------------------------------------------------------------------------
# Aggregation across method_configs
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    methods: list[str] = field(default_factory=list)
    voices: list[str] = field(default_factory=list)
    parameterized: bool = False
    unresolved: set[str] = field(default_factory=set)


def _formula_for_method(
    method_id: str, registries: "Registries"
) -> str | None:
    """Look up ``formula_python`` for a method or derived rule id."""
    method = registries.methods.get(method_id)
    if method is not None:
        return method.get("formula_python")
    derived = registries.derived_rules.get(method_id)
    if derived is not None:
        return derived.get("formula_python")
    return None


def compute_required_drivers(
    method_configs: Iterable[tuple[str, str]],
    registries: "Registries",
) -> list[DriverRequirement]:
    """Aggregate driver requirements across a project's ``(voice, method)`` pairs.

    Inputs are intentionally minimal — a sequence of ``(voice_id,
    method_id)`` tuples — so the function stays trivially testable
    without a database. Voices for which ``method_id`` is not in the
    registry are skipped silently: the caller (route) is responsible
    for guaranteeing the configs are well-formed (the M6 validator
    already enforces it on write).

    Output is sorted by ``driver_id`` to make the response stable.
    """
    buckets: dict[str, _Bucket] = {}
    for voice_id, method_id in method_configs:
        formula = _formula_for_method(method_id, registries)
        if not formula:
            continue
        for resolved, parameterized, unresolved in (
            extract_driver_refs_from_formula(formula, voice_id)
        ):
            bucket = buckets.setdefault(resolved, _Bucket())
            if method_id not in bucket.methods:
                bucket.methods.append(method_id)
            if voice_id not in bucket.voices:
                bucket.voices.append(voice_id)
            if parameterized:
                bucket.parameterized = True
                bucket.unresolved.update(unresolved)

    return sorted(
        (
            DriverRequirement(
                driver_id=did,
                type=infer_driver_type(did),
                required_by_methods=tuple(b.methods),
                required_for_voices=tuple(b.voices),
                parameterized=b.parameterized,
                unresolved_placeholders=tuple(sorted(b.unresolved)),
            )
            for did, b in buckets.items()
        ),
        key=lambda r: r.driver_id,
    )


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def compute_driver_status(
    *,
    driver_type: str,
    skipped: bool,
    present_years: set[str],
    required_years: set[str],
    has_static_parameters: bool,
    has_time_series: bool,
    has_aging_buckets: bool,
) -> str:
    """Collapse the per-driver state into the four-value status enum.

    The status drives the UI summary counters. ``skipped`` always wins:
    even if some rows happen to be present, the user has explicitly
    opted out.
    """
    if skipped:
        return STATUS_SKIPPED
    if driver_type == DRIVER_TYPE_SCALAR_PER_YEAR:
        if not present_years:
            return STATUS_MISSING
        if required_years and required_years.issubset(present_years):
            return STATUS_COMPLETE
        return STATUS_PARTIAL
    if driver_type == DRIVER_TYPE_STATIC_PARAMETERS:
        return STATUS_COMPLETE if has_static_parameters else STATUS_MISSING
    if driver_type == DRIVER_TYPE_TIME_SERIES:
        return STATUS_COMPLETE if has_time_series else STATUS_MISSING
    if driver_type == DRIVER_TYPE_AGING_BUCKET:
        return STATUS_COMPLETE if has_aging_buckets else STATUS_MISSING
    return STATUS_MISSING
