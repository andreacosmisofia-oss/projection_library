"""Pre-populate assumption defaults from historical KPIs (M8).

For every ``(voice_id, method_id)`` in a project's method configuration
we look at the method's ``default_kpi_example`` template, resolve the
``<voice>`` placeholder against the owning voice, and fetch the
aggregated default from the project's ``historical_kpis`` (the M5
calculator persists ``default_for_projection`` and ``calibration_score``
on the ``year='AGG'`` row).

When the resolved KPI is one of the parametric ``<voice>`` templates
(``kpi.growth.<voice>_yoy``, ``kpi.margin.<voice>_pct_revenue``) the M5
calculator deliberately leaves those rows non-computable
(``not_computable_reason='template'``). Two compact in-line fallbacks
recover the most common shapes from :class:`MappedValues` so the user
sees a meaningful default rather than zero. Anything outside those two
shapes falls through to ``source='fallback'`` with value ``0.0``.

The populator is pure: callers feed in the registry, the persisted
KPI aggregates and (optionally) the mapped values; the route layer
owns DB writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from backend.domain.assumptions.extractor import (
    AssumptionRef,
    assumption_refs_for_method,
    infer_validation_range,
)

if TYPE_CHECKING:
    from backend.domain.intake.mapping_resolver import MappedValues
    from backend.infrastructure.registry import Registries


SOURCE_DEFAULT_KPI = "default_kpi"
SOURCE_USER_INPUT = "user_input"
SOURCE_FALLBACK = "fallback"

PROJECTION_YEARS: tuple[str, ...] = ("Y1", "Y2", "Y3")

_VOICE_PLACEHOLDER = "<voice>"


@dataclass(frozen=True)
class AssumptionDefault:
    """Three-year flat default emitted for one ``(voice, method, name)``.

    Y1/Y2/Y3 carry the same value (the flow-doc "flat" curve) — drift
    toward a target is left to the user via ``POST /curve``. Persistence
    is per-year so the column shape mirrors how the user edits.
    """

    voice_id: str
    method_id: str
    assumption_name: str
    value: float
    source: str
    default_kpi_id: str | None
    calibration_score: float | None
    validation_range: tuple[float | None, float | None]
    parameterized: bool = False
    unresolved_placeholders: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# KPI template resolution
# ---------------------------------------------------------------------------


def resolve_default_kpi(
    default_kpi_example: str | None, voice_id: str
) -> str | None:
    """Substitute ``<voice>`` in the method's ``default_kpi_example``.

    Returns ``None`` when there's no example to resolve, when the entry
    is one of the registry's null markers (``—`` / empty), or when the
    template carries an unsupported placeholder (other than ``<voice>``)
    that we can't resolve from a voice id alone.
    """
    if default_kpi_example is None:
        return None
    raw = default_kpi_example.strip()
    if not raw or raw in {"—", "-"}:
        return None
    # Some entries carry a parenthetical comment, e.g.
    # ``"kpi.saas.new_arr_rate (e altri)"`` — keep only the leading id.
    head = raw.split(" ", 1)[0]
    head = head.replace(_VOICE_PLACEHOLDER, voice_id)
    # If any other ``<...>`` survives we can't resolve it from a voice
    # id alone — bail out so the populator falls back gracefully.
    if "<" in head and ">" in head:
        return None
    return head


# ---------------------------------------------------------------------------
# Inline fallback: compute a value for the two common <voice> templates
# ---------------------------------------------------------------------------


def _y0_yminus1_ratio_growth(
    voice_id: str, mapped: "MappedValues"
) -> float | None:
    """YoY growth at Y0 reproducing ``kpi.growth.<voice>_yoy``.

    Returns ``None`` when either anchor is missing or the prior-year
    value is zero (the M5 calculator skips these too — fractional
    growth on a zero base is undefined).
    """
    y0 = mapped.get(voice_id, "Y0")
    ym1 = mapped.get(voice_id, "Y-1")
    if y0 is None or ym1 is None or ym1 == 0:
        return None
    return (y0 - ym1) / abs(ym1)


def _voice_pct_of_revenue(
    voice_id: str, mapped: "MappedValues"
) -> float | None:
    """``voice@Y0 / pl.rev.net@Y0`` reproducing the margin template.

    Used as the fallback for ``kpi.margin.<voice>_pct_revenue``; sign is
    abs on the numerator (matches ``sign_handling=abs_num`` in the
    canonical margin KPIs) so cost voices don't return a negative pct.
    """
    num = mapped.get(voice_id, "Y0")
    den = mapped.get("pl.rev.net", "Y0")
    if num is None or den is None or den == 0:
        return None
    return abs(num) / den


def _calibration_for_lfl(mapped: "MappedValues") -> float:
    """Mirror the M5 ``_calibration_for_kpi`` heuristic, simplified.

    Three full LFL years → 1.0; two → 0.7; one → 0.4; zero → 0.0. The
    pilot UI shows this as a 5-dot strength indicator and an exact
    match with M5 isn't a contract — what matters is that the template
    fallback flags itself as *less* trustworthy than a real KPI value
    when years are sparse.
    """
    n_lfl = len(mapped.years_lfl)
    if n_lfl >= 3:
        return 1.0
    if n_lfl == 2:
        return 0.7
    if n_lfl == 1:
        return 0.4
    return 0.0


def compute_template_kpi_fallback(
    kpi_id: str | None,
    voice_id: str,
    mapped_values: "MappedValues | None",
) -> tuple[float, float] | None:
    """Compute a default for the two <voice>-templated KPIs M5 skips.

    Returns ``(value, calibration_score)`` or ``None`` when the shape
    is unrecognised or the underlying voices aren't in
    ``mapped_values``. Kept tiny on purpose — anything more elaborate
    belongs in a future expansion of the M5 calculator, not here.
    """
    if kpi_id is None or mapped_values is None:
        return None
    if kpi_id == f"kpi.growth.{voice_id}_yoy":
        value = _y0_yminus1_ratio_growth(voice_id, mapped_values)
        if value is None:
            return None
        return (value, _calibration_for_lfl(mapped_values))
    if kpi_id == f"kpi.margin.{voice_id}_pct_revenue":
        value = _voice_pct_of_revenue(voice_id, mapped_values)
        if value is None:
            return None
        return (value, _calibration_for_lfl(mapped_values))
    return None


# ---------------------------------------------------------------------------
# Default emission
# ---------------------------------------------------------------------------


def _default_for_one(
    voice_id: str,
    method_id: str,
    ref: AssumptionRef,
    method_default_kpi: str | None,
    kpi_index: dict[str, tuple[float | None, float | None]],
    mapped_values: "MappedValues | None",
) -> AssumptionDefault:
    """Build the :class:`AssumptionDefault` for one ``(voice, method, name)``.

    ``kpi_index`` is the precomputed view of ``historical_kpis`` AGG
    rows: ``{kpi_id: (default_for_projection, calibration_score)}``.
    """
    range_min, range_max = infer_validation_range(ref.name)

    if ref.parameterized:
        # Parameterised names (e.g. ``bom_{m}_price``) can't be
        # populated without the runtime index list. Surface a fallback
        # row at zero so the UI can show the stub; the user fills in
        # via the eventual sector-pack flow.
        return AssumptionDefault(
            voice_id=voice_id,
            method_id=method_id,
            assumption_name=ref.name,
            value=0.0,
            source=SOURCE_FALLBACK,
            default_kpi_id=None,
            calibration_score=0.0,
            validation_range=(range_min, range_max),
            parameterized=True,
            unresolved_placeholders=ref.unresolved_placeholders,
        )

    resolved_kpi = resolve_default_kpi(method_default_kpi, voice_id)
    if resolved_kpi is not None:
        # Path 1: the resolved KPI is a literal computed by M5.
        agg = kpi_index.get(resolved_kpi)
        if agg is not None:
            value, calibration = agg
            if value is not None:
                return AssumptionDefault(
                    voice_id=voice_id,
                    method_id=method_id,
                    assumption_name=ref.name,
                    value=value,
                    source=SOURCE_DEFAULT_KPI,
                    default_kpi_id=resolved_kpi,
                    calibration_score=calibration,
                    validation_range=(range_min, range_max),
                )

        # Path 2: <voice>-templated KPI that M5 left non-computable.
        # Reproduce the two common shapes inline so the user sees a
        # meaningful seed rather than zero on day-one projects.
        template_fallback = compute_template_kpi_fallback(
            resolved_kpi, voice_id, mapped_values
        )
        if template_fallback is not None:
            value, calibration = template_fallback
            return AssumptionDefault(
                voice_id=voice_id,
                method_id=method_id,
                assumption_name=ref.name,
                value=value,
                source=SOURCE_DEFAULT_KPI,
                default_kpi_id=resolved_kpi,
                calibration_score=calibration,
                validation_range=(range_min, range_max),
            )

    # Path 3: nothing computable — emit a zero fallback the user must
    # confirm. Persisting it (rather than skipping) keeps the UI shape
    # uniform: every (voice, method, assumption) has a row.
    return AssumptionDefault(
        voice_id=voice_id,
        method_id=method_id,
        assumption_name=ref.name,
        value=0.0,
        source=SOURCE_FALLBACK,
        default_kpi_id=resolved_kpi,
        calibration_score=0.0,
        validation_range=(range_min, range_max),
    )


def compute_assumption_defaults(
    method_configs: Iterable[tuple[str, str]],
    registries: "Registries",
    kpi_index: dict[str, tuple[float | None, float | None]],
    mapped_values: "MappedValues | None" = None,
) -> list[AssumptionDefault]:
    """Materialise the per-(voice, method, name) default emitted for Y1-Y3.

    The flow doc treats Y1/Y2/Y3 as a flat default — the same value
    is replicated three times at write time. This function returns one
    :class:`AssumptionDefault` per ``(voice, method, assumption_name)``;
    the route layer expands each into three persisted rows so a single
    PATCH on one year doesn't have to touch the others.

    Voices whose method has no formula or no extracted assumptions
    (e.g. ``flat``, ``manual_zero_placeholder``) yield no entries —
    they have nothing to compile.
    """
    out: list[AssumptionDefault] = []
    for voice_id, method_id in method_configs:
        method_spec = registries.methods.get(method_id)
        # Derived rules can also be dispatched as a method via the user-
        # choice sentinel path (see M6); they have no ``default_kpi_example``
        # field, so the lookup falls through to fallback. ``None`` here is
        # safe because ``resolve_default_kpi`` already handles it.
        method_default_kpi = (
            method_spec.get("default_kpi_example") if method_spec else None
        )
        for ref in assumption_refs_for_method(method_id, registries):
            out.append(
                _default_for_one(
                    voice_id,
                    method_id,
                    ref,
                    method_default_kpi,
                    kpi_index,
                    mapped_values,
                )
            )
    return out


__all__ = [
    "AssumptionDefault",
    "PROJECTION_YEARS",
    "SOURCE_DEFAULT_KPI",
    "SOURCE_FALLBACK",
    "SOURCE_USER_INPUT",
    "compute_assumption_defaults",
    "compute_template_kpi_fallback",
    "resolve_default_kpi",
]
