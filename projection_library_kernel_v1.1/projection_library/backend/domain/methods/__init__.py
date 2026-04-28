"""Method selection domain (Milestones M6 + M7).

M6 ships pure helpers for resolving ``voice → method`` defaults and for
looking up registry metadata. M7 adds :mod:`.compatibility`, which
derives the list of drivers required by a project's method configs by
parsing the ``formula_python`` strings exposed by the method registry.
"""

from backend.domain.methods.compatibility import (
    DRIVER_TYPE_SCALAR,
    DRIVER_TYPE_STATIC_PARAMETERS,
    RequiredDriver,
    SCALAR_YEARS_REQUIRED,
    compute_required_drivers,
)
from backend.domain.methods.selector import (
    SOURCE_REGISTRY_DEFAULT,
    SOURCE_SECTOR_PACK,
    SOURCE_USER_OVERRIDE,
    USER_CHOICE_SENTINELS,
    is_user_choice_sentinel,
    resolve_default_method,
    resolve_method_tech_code,
    validate_method_id,
)

__all__ = [
    "DRIVER_TYPE_SCALAR",
    "DRIVER_TYPE_STATIC_PARAMETERS",
    "RequiredDriver",
    "SCALAR_YEARS_REQUIRED",
    "SOURCE_REGISTRY_DEFAULT",
    "SOURCE_SECTOR_PACK",
    "SOURCE_USER_OVERRIDE",
    "USER_CHOICE_SENTINELS",
    "compute_required_drivers",
    "is_user_choice_sentinel",
    "resolve_default_method",
    "resolve_method_tech_code",
    "validate_method_id",
]
