"""Unit tests for backend.domain.override.policy + resolver (M11)."""

from __future__ import annotations

import pytest

from backend.domain.engine.value_resolver import ModelState, Override
from backend.domain.override.policy import (
    OverrideValidationError,
    is_one_shot_allowed,
    is_overridable,
    resolve_policy_class,
    validate_override_request,
)
from backend.domain.override.resolver import (
    apply_one_shot_suppression,
    voice_matches_targets,
)


# ---------------------------------------------------------------------------
# policy.resolve_policy_class
# ---------------------------------------------------------------------------


def test_resolve_policy_picks_first_specific_match(loaded_registries) -> None:
    match = resolve_policy_class("pl.rev.gross.product_sales", loaded_registries)
    assert match is not None
    assert match.policy_class == "revenue_organic"
    assert match.overridable is True
    assert match.one_shot_allowed is True
    assert "pl.cogs.*" in match.organic_targets
    assert "bs.nfp.cash" in match.one_shot_targets


def test_resolve_policy_classifies_derived_voice(loaded_registries) -> None:
    match = resolve_policy_class("pl.ebitda", loaded_registries)
    assert match is not None
    assert match.policy_class == "not_overridable_derived"
    assert match.overridable is False
    assert match.guidance_message


def test_resolve_policy_excluded_voice_falls_through(loaded_registries) -> None:
    # 'pl.rev.gross_total' is in revenue_organic.exclude_voices but matches
    # the not_overridable_derived list; the loader walks policies in order,
    # which means the derived class catches it first.
    match = resolve_policy_class("pl.rev.gross_total", loaded_registries)
    assert match is not None
    assert match.policy_class == "not_overridable_derived"


def test_is_overridable_helpers(loaded_registries) -> None:
    assert is_overridable("pl.rev.gross.product_sales", loaded_registries)
    assert is_one_shot_allowed("pl.rev.gross.product_sales", loaded_registries)
    assert not is_overridable("pl.ebitda", loaded_registries)


# ---------------------------------------------------------------------------
# policy.validate_override_request
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides):
    base = {
        "voice_id": "pl.rev.gross.product_sales",
        "year": "Y2",
        "delta_amount": 1000.0,
        "nature": "organic",
    }
    base.update(overrides)
    return base


def test_validate_accepts_well_formed_organic(loaded_registries) -> None:
    match = validate_override_request(
        registries=loaded_registries, **_valid_kwargs()
    )
    assert match.policy_class == "revenue_organic"


def test_validate_accepts_one_shot_when_policy_allows(loaded_registries) -> None:
    match = validate_override_request(
        registries=loaded_registries,
        **_valid_kwargs(nature="one_shot"),
    )
    assert match.policy_class == "revenue_organic"


def test_validate_rejects_invalid_year(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError, match="year"):
        validate_override_request(
            registries=loaded_registries, **_valid_kwargs(year="Y4")
        )


def test_validate_rejects_invalid_nature(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError, match="nature"):
        validate_override_request(
            registries=loaded_registries, **_valid_kwargs(nature="permanent")
        )


def test_validate_rejects_zero_delta(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError, match="below minimum"):
        validate_override_request(
            registries=loaded_registries, **_valid_kwargs(delta_amount=0.0)
        )


def test_validate_rejects_non_finite_delta(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError, match="finite"):
        validate_override_request(
            registries=loaded_registries,
            **_valid_kwargs(delta_amount=float("inf")),
        )


def test_validate_rejects_unknown_voice(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError, match="voice registry"):
        validate_override_request(
            registries=loaded_registries,
            **_valid_kwargs(voice_id="pl.does.not.exist"),
        )


def test_validate_rejects_derived_with_guidance(loaded_registries) -> None:
    with pytest.raises(OverrideValidationError) as exc:
        validate_override_request(
            registries=loaded_registries,
            **_valid_kwargs(voice_id="pl.ebitda"),
        )
    # The guidance message from the policy must surface verbatim so the
    # frontend can show it as-is.
    assert "derived" in str(exc.value).lower() or "componenti" in str(exc.value)


# ---------------------------------------------------------------------------
# resolver.voice_matches_targets
# ---------------------------------------------------------------------------


def test_voice_matches_targets_glob() -> None:
    assert voice_matches_targets("pl.cogs.materials.raw", ["pl.cogs.*"])
    assert not voice_matches_targets("pl.opex.travel", ["pl.cogs.*"])
    assert voice_matches_targets("bs.nfp.cash", ["bs.nfp.cash", "cf.*"])


# ---------------------------------------------------------------------------
# resolver.apply_one_shot_suppression
# ---------------------------------------------------------------------------


def _state_with_base(values: dict[str, dict[str, float]]) -> ModelState:
    state = ModelState()
    state.base_values = {
        voice: dict(by_year) for voice, by_year in values.items()
    }
    return state


def test_one_shot_suppression_resets_non_target_voices(loaded_registries) -> None:
    """Revenue one_shot: cogs (in organic_targets but NOT one_shot_targets)
    must keep its organic-baseline value; cash (in one_shot_targets) must
    keep its full-overrides value."""
    state_full = _state_with_base(
        {
            "pl.cogs.materials.raw": {"Y2": -1800.0},  # absorbed delta
            "bs.nfp.cash": {"Y2": 50.0},  # cash reflects delta
            "pl.rev.gross.product_sales": {"Y2": 2500.0},
        }
    )
    state_organic = _state_with_base(
        {
            "pl.cogs.materials.raw": {"Y2": -1000.0},  # baseline
            "bs.nfp.cash": {"Y2": 250.0},  # baseline
            "pl.rev.gross.product_sales": {"Y2": 2500.0},
        }
    )
    overrides = [
        Override(
            voice_id="pl.rev.gross.product_sales",
            year="Y2",
            delta_amount=2000.0,
            nature="one_shot",
        )
    ]

    apply_one_shot_suppression(
        state_full=state_full,
        state_organic=state_organic,
        overrides=overrides,
        registries=loaded_registries,
    )

    # cogs absorbed the delta in state_full (organic propagation), but the
    # override is one_shot → must be reset to baseline.
    assert state_full.base_values["pl.cogs.materials.raw"]["Y2"] == -1000.0
    # cash always reflects the delta via CF identity (one_shot target).
    assert state_full.base_values["bs.nfp.cash"]["Y2"] == 50.0
    # The override voice itself stays at full (it's the source of truth).
    assert state_full.base_values["pl.rev.gross.product_sales"]["Y2"] == 2500.0


def test_one_shot_suppression_no_op_when_no_one_shot(loaded_registries) -> None:
    """Pure organic overrides: no suppression should be applied."""
    state_full = _state_with_base({"pl.cogs.materials.raw": {"Y2": -1800.0}})
    state_organic = _state_with_base({"pl.cogs.materials.raw": {"Y2": -1000.0}})
    overrides = [
        Override(
            voice_id="pl.rev.gross.product_sales",
            year="Y2",
            delta_amount=2000.0,
            nature="organic",
        )
    ]

    apply_one_shot_suppression(
        state_full=state_full,
        state_organic=state_organic,
        overrides=overrides,
        registries=loaded_registries,
    )

    # Organic-only path: state_full is returned untouched.
    assert state_full.base_values["pl.cogs.materials.raw"]["Y2"] == -1800.0
