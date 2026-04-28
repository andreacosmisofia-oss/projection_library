"""Assumption compilation (M8) — public API.

Mirror of the M7 layout: a thin ``__init__`` re-exports the helpers the
route layer composes. The domain is split into three pure modules:

* ``extractor`` — parse ``formula_python`` to discover the assumption
  parameter names a method consumes (the registry has no first-class
  ``assumptions:`` field, so the formula is the source of truth).
* ``populator`` — turn the extracted names into per-year default values
  by resolving the method's ``default_kpi_example`` against the
  project's ``historical_kpis`` (with a small inline fallback for the
  parametric ``<voice>``-templated KPIs that M5 leaves uncomputed).
* ``curves`` — apply the three pilot curve shapes (flat / linear_drift
  / custom) and stamp a validation status against the inferred range.
"""

from __future__ import annotations

from backend.domain.assumptions.curves import (
    CURVE_CUSTOM,
    CURVE_FLAT,
    CURVE_LINEAR_DRIFT,
    VALIDATION_OK,
    VALIDATION_WARNING_RANGE,
    apply_curve,
    validate_value_in_range,
)
from backend.domain.assumptions.extractor import (
    AssumptionRef,
    assumption_refs_for_method,
    extract_assumption_refs_from_formula,
    infer_validation_range,
)
from backend.domain.assumptions.populator import (
    SOURCE_DEFAULT_KPI,
    SOURCE_FALLBACK,
    SOURCE_USER_INPUT,
    AssumptionDefault,
    compute_assumption_defaults,
    compute_template_kpi_fallback,
    resolve_default_kpi,
)


__all__ = [
    "AssumptionDefault",
    "AssumptionRef",
    "CURVE_CUSTOM",
    "CURVE_FLAT",
    "CURVE_LINEAR_DRIFT",
    "SOURCE_DEFAULT_KPI",
    "SOURCE_FALLBACK",
    "SOURCE_USER_INPUT",
    "VALIDATION_OK",
    "VALIDATION_WARNING_RANGE",
    "apply_curve",
    "assumption_refs_for_method",
    "compute_assumption_defaults",
    "compute_template_kpi_fallback",
    "extract_assumption_refs_from_formula",
    "infer_validation_range",
    "resolve_default_kpi",
    "validate_value_in_range",
]
