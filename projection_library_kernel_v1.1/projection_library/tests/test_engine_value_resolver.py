"""Unit tests for backend.domain.engine.value_resolver."""

from __future__ import annotations

from backend.domain.engine.value_resolver import (
    ModelState,
    Override,
    resolve_voice_value,
)


def test_resolve_no_overrides():
    state = ModelState(
        base_values={"pl.rev.net": {"Y1": 1000.0, "Y2": 1100.0}},
        overrides=[],
    )

    assert resolve_voice_value("pl.rev.net", "Y1", state) == 1000.0
    assert resolve_voice_value("pl.rev.net", "Y2", state) == 1100.0
    # Unknown voice / year fall back to 0.0
    assert resolve_voice_value("pl.rev.net", "Y3", state) == 0.0
    assert resolve_voice_value("missing.voice", "Y1", state) == 0.0


def test_resolve_with_override():
    state = ModelState(
        base_values={"pl.rev.net": {"Y1": 1000.0, "Y2": 1100.0}},
        overrides=[
            Override(voice_id="pl.rev.net", year="Y1", delta_amount=200.0),
            Override(voice_id="pl.rev.net", year="Y1", delta_amount=50.0),
            # Inactive override is ignored
            Override(
                voice_id="pl.rev.net",
                year="Y1",
                delta_amount=999.0,
                is_active=False,
            ),
            # Different year, must not leak into Y1
            Override(voice_id="pl.rev.net", year="Y2", delta_amount=10.0),
            # Different voice, must not leak
            Override(voice_id="pl.cogs.total", year="Y1", delta_amount=77.0),
        ],
    )

    assert resolve_voice_value("pl.rev.net", "Y1", state) == 1250.0
    assert resolve_voice_value("pl.rev.net", "Y2", state) == 1110.0
    # Voice with only an override but no base_value: 0 + delta
    assert resolve_voice_value("pl.cogs.total", "Y1", state) == 77.0
