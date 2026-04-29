"""Override layer (Milestone M11, ``flows/09_iteration.md``).

Three responsibilities split across modules:

* :mod:`backend.domain.override.policy` — resolve a voice → policy
  class via ``registries/override_policy.yaml`` and validate user
  override requests against the matrix.
* :mod:`backend.domain.override.resolver` — load active overrides
  into a :class:`~backend.domain.engine.value_resolver.ModelState` and
  apply post-engine ``one_shot`` suppression so non-target voices keep
  their pre-override base values (cash always recomputes via the CF
  identity).
* :mod:`backend.domain.override.store` — thin wrapper over the
  override repository for callers that don't want to import the SQL
  layer directly.
"""

from backend.domain.override.policy import (
    OverrideValidationError,
    PolicyMatch,
    is_one_shot_allowed,
    is_overridable,
    resolve_policy_class,
    validate_override_request,
)
from backend.domain.override.resolver import (
    PROPAGATION_MAX_ITER,
    apply_one_shot_suppression,
    load_active_overrides_into_state,
    voice_matches_targets,
)
from backend.domain.override.store import (
    list_active_overrides_for_state,
)

__all__ = [
    "PROPAGATION_MAX_ITER",
    "OverrideValidationError",
    "PolicyMatch",
    "apply_one_shot_suppression",
    "is_one_shot_allowed",
    "is_overridable",
    "list_active_overrides_for_state",
    "load_active_overrides_into_state",
    "resolve_policy_class",
    "validate_override_request",
    "voice_matches_targets",
]
