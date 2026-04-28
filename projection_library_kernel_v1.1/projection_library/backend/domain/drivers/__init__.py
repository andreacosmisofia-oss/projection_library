"""Driver intake domain (Milestone M7).

Pure helpers that turn ``method_configs`` × ``method_registry`` into
the list of historical drivers a project must collect, plus small
status helpers used by the route layer.
"""

from backend.domain.drivers.extractor import (
    DRIVER_PREFIX,
    DRIVER_TYPE_AGING_BUCKET,
    DRIVER_TYPE_SCALAR_PER_YEAR,
    DRIVER_TYPE_STATIC_PARAMETERS,
    DRIVER_TYPE_TIME_SERIES,
    DriverRequirement,
    STATUS_COMPLETE,
    STATUS_MISSING,
    STATUS_PARTIAL,
    STATUS_SKIPPED,
    compute_driver_status,
    compute_required_drivers,
    extract_driver_refs_from_formula,
    infer_driver_type,
)

__all__ = [
    "DRIVER_PREFIX",
    "DRIVER_TYPE_AGING_BUCKET",
    "DRIVER_TYPE_SCALAR_PER_YEAR",
    "DRIVER_TYPE_STATIC_PARAMETERS",
    "DRIVER_TYPE_TIME_SERIES",
    "DriverRequirement",
    "STATUS_COMPLETE",
    "STATUS_MISSING",
    "STATUS_PARTIAL",
    "STATUS_SKIPPED",
    "compute_driver_status",
    "compute_required_drivers",
    "extract_driver_refs_from_formula",
    "infer_driver_type",
]
