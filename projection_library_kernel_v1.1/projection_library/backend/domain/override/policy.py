"""Override policy matrix lookup + request validation (M11).

Encapsulates the YAML-driven matching defined in
``flows/11_override_policy_matrix.md``: for any voice_id, walk the
ordered policies in ``registries/override_policy.yaml`` and return the
first one whose ``applies_to_voices_pattern`` matches and whose
``exclude_voices`` doesn't. The fallback ``default_organic`` (pattern
``*``) ensures every voice resolves to *some* class, which the route
layer can then inspect for ``overridable=False`` and reject with the
policy's ``guidance_message``.

The validator is the single gate run by ``POST /overrides``:
* year ∈ {Y1, Y2, Y3}
* delta_amount finite, non-zero (> ``MIN_DELTA``)
* policy.overridable
* nature ∈ {organic, one_shot}
* one_shot ⇒ policy.one_shot_allowed
"""

from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass
from typing import Any, Iterable

VALID_YEARS: frozenset[str] = frozenset({"Y1", "Y2", "Y3"})
VALID_NATURES: frozenset[str] = frozenset({"organic", "one_shot"})

# Below this absolute threshold the delta is treated as noise and
# rejected. Mirrors the §"Validazione pre-creation" guidance in
# ``flows/09_iteration.md``: numbers smaller than 0.01 in the working
# unit don't move the model materially and clutter the override list.
MIN_DELTA: float = 0.01


class OverrideValidationError(ValueError):
    """User-facing error raised by :func:`validate_override_request`.

    The route layer translates this into HTTP 422 with the message body
    so the UI can surface the policy ``guidance_message`` for derived
    voices verbatim.
    """


@dataclass(frozen=True)
class PolicyMatch:
    """Result of matching a voice_id against the policy matrix."""

    policy_class: str
    overridable: bool
    one_shot_allowed: bool
    organic_targets: tuple[str, ...]
    one_shot_targets: tuple[str, ...]
    guidance_message: str | None
    raw: dict[str, Any]


def _to_pattern_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [p for p in value if isinstance(p, str)]
    return []


def _matches_any(voice_id: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(voice_id, p) for p in patterns)


def _is_excluded(voice_id: str, exclude: list[Any]) -> bool:
    for entry in exclude or []:
        if not isinstance(entry, str):
            continue
        if any(ch in entry for ch in "*?["):
            if fnmatch.fnmatchcase(voice_id, entry):
                return True
        elif voice_id == entry:
            return True
    return False


def resolve_policy_class(voice_id: str, registries: Any) -> PolicyMatch | None:
    """Return the policy that governs ``voice_id``, or ``None``.

    Iterates ``registries.override_policies`` in declaration order and
    returns the first match. ``None`` is reserved for callers that
    pass a registry view without override policies (defensive only —
    M1.9 fails startup if the file is missing).
    """
    policies = list(getattr(registries, "override_policies", []) or [])
    for policy in policies:
        patterns = _to_pattern_list(policy.get("applies_to_voices_pattern"))
        if not patterns:
            continue
        if not _matches_any(voice_id, patterns):
            continue
        if _is_excluded(voice_id, policy.get("exclude_voices") or []):
            continue
        return PolicyMatch(
            policy_class=str(policy.get("policy_class", "")),
            overridable=bool(policy.get("overridable", True)),
            one_shot_allowed=bool(policy.get("one_shot_allowed", False)),
            organic_targets=tuple(
                p
                for p in policy.get("organic_propagation_targets") or []
                if isinstance(p, str)
            ),
            one_shot_targets=tuple(
                p
                for p in policy.get("one_shot_propagation_targets") or []
                if isinstance(p, str)
            ),
            guidance_message=policy.get("guidance_message"),
            raw=dict(policy),
        )
    return None


def is_overridable(voice_id: str, registries: Any) -> bool:
    """Return True when the voice resolves to an overridable policy."""
    match = resolve_policy_class(voice_id, registries)
    return bool(match and match.overridable)


def is_one_shot_allowed(voice_id: str, registries: Any) -> bool:
    """Return True when the voice's policy admits one_shot overrides."""
    match = resolve_policy_class(voice_id, registries)
    return bool(match and match.one_shot_allowed)


def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def validate_override_request(
    *,
    voice_id: str,
    year: str,
    delta_amount: Any,
    nature: str,
    registries: Any,
) -> PolicyMatch:
    """Validate the inputs of ``POST /overrides`` and return the policy.

    Raises :class:`OverrideValidationError` on any rule violation. The
    returned :class:`PolicyMatch` is the single source of truth for
    ``override_policy_class`` to persist on the row, so the route does
    not need to re-resolve the policy a second time.
    """
    if year not in VALID_YEARS:
        raise OverrideValidationError(
            f"year must be one of {sorted(VALID_YEARS)}, got '{year}'"
        )
    if nature not in VALID_NATURES:
        raise OverrideValidationError(
            f"nature must be one of {sorted(VALID_NATURES)}, got '{nature}'"
        )
    if not _is_finite_number(delta_amount):
        raise OverrideValidationError(
            "delta_amount must be a finite number"
        )
    if abs(float(delta_amount)) < MIN_DELTA:
        raise OverrideValidationError(
            f"delta_amount {delta_amount!r} below minimum threshold "
            f"({MIN_DELTA})"
        )

    voices = getattr(registries, "voices", {}) or {}
    if voice_id not in voices:
        raise OverrideValidationError(
            f"voice_id '{voice_id}' is not in the voice registry"
        )

    match = resolve_policy_class(voice_id, registries)
    if match is None:
        raise OverrideValidationError(
            f"voice_id '{voice_id}' has no override policy class "
            f"in override_policy.yaml"
        )

    if not match.overridable:
        guidance = match.guidance_message or (
            "This voice is derived (subtotal or accounting identity). "
            "Apply the override on one of its components instead."
        )
        raise OverrideValidationError(guidance)

    if nature == "one_shot" and not match.one_shot_allowed:
        raise OverrideValidationError(
            f"policy '{match.policy_class}' does not allow one_shot overrides"
        )

    return match


__all__ = [
    "MIN_DELTA",
    "OverrideValidationError",
    "PolicyMatch",
    "VALID_NATURES",
    "VALID_YEARS",
    "is_one_shot_allowed",
    "is_overridable",
    "resolve_policy_class",
    "validate_override_request",
]
