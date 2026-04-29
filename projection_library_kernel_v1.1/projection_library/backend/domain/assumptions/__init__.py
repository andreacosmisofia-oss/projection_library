"""M8 — assumption compilation domain (``flows/06_assumption_compilation.md``)."""

from backend.domain.assumptions.curve import apply_curve
from backend.domain.assumptions.populator import (
    PopulateReport,
    populate_defaults,
)
from backend.domain.assumptions.service import (
    AssumptionRowDTO,
    compose_assumption_list,
)
from backend.domain.assumptions.validator import classify_value

__all__ = [
    "AssumptionRowDTO",
    "PopulateReport",
    "apply_curve",
    "classify_value",
    "compose_assumption_list",
    "populate_defaults",
]
