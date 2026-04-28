"""Method-selection helpers (M6 Expert mode).

The functions here are pure: they take dicts pulled from the registry
cache and return primitives, with no DB or HTTP coupling. The route
layer composes them with the repository.

A ``method_id`` is "valid" if it resolves either to an entry in
``method_registry`` or to a ``derived_rule_id`` — the registry loader
treats both as legitimate values for ``voice.default_method`` (some
voices, e.g. subtotals, project via a derived rule), so the API layer
follows the same contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.infrastructure.registry import Registries


SOURCE_REGISTRY_DEFAULT = "registry_default"
SOURCE_SECTOR_PACK = "sector_pack"
SOURCE_USER_OVERRIDE = "user_override"

# Mirror of ``loader._USER_CHOICE_SENTINELS``: voice defaults that
# explicitly defer to the user. Treated as "no default" by the API.
USER_CHOICE_SENTINELS = frozenset({"(utente sceglie)", "(user choice)"})

_NULL_SENTINELS = frozenset({"—", "-", ""})


def is_user_choice_sentinel(value: str | None) -> bool:
    return isinstance(value, str) and value in USER_CHOICE_SENTINELS


def _is_meaningful(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value in _NULL_SENTINELS:
        return False
    return True


def resolve_default_method(voice: dict) -> str | None:
    """Return the registry default for ``voice``, or None for sentinels.

    No sector-pack overlay yet (sector packs are still text-only). The
    function intentionally does not raise on unknown method ids: the
    loader has already validated cross-references, so any value
    returned here is either a known method/derived-rule id, a user-
    choice sentinel, or an empty/null marker.
    """
    dm = voice.get("default_method")
    if not _is_meaningful(dm):
        return None
    if is_user_choice_sentinel(dm):
        return None
    return dm


def validate_method_id(method_id: str, registries: "Registries") -> bool:
    """True iff ``method_id`` exists as method or derived rule."""
    return (
        method_id in registries.methods
        or method_id in registries.derived_rules
    )


def resolve_method_tech_code(
    method_id: str, registries: "Registries"
) -> str | None:
    """Snapshot the tech_code for ``method_id`` so the row stays
    readable even if the registry shifts ids later."""
    method = registries.methods.get(method_id)
    if method is not None:
        return method.get("tech_code")
    derived = registries.derived_rules.get(method_id)
    if derived is not None:
        return derived.get("tech_code")
    return None


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
