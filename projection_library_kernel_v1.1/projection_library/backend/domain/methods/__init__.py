"""Method selection domain (Milestone M6).

Pure helpers for resolving ``voice → method`` defaults and for looking
up registry metadata. The Expert-mode subset (this milestone) has no
compatibility check, sector pack overlay, or guided/ambition logic
yet — those land alongside the corresponding endpoints.
"""

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
    "SOURCE_REGISTRY_DEFAULT",
    "SOURCE_SECTOR_PACK",
    "SOURCE_USER_OVERRIDE",
    "USER_CHOICE_SENTINELS",
    "is_user_choice_sentinel",
    "resolve_default_method",
    "resolve_method_tech_code",
    "validate_method_id",
]
