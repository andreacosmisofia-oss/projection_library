"""Unit tests for backend.domain.engine.formulas."""

from __future__ import annotations

import logging

from backend.domain.engine.formulas import evaluate, pmt, safe_div
from backend.domain.engine.value_resolver import ModelState


def test_evaluate_growth_formula():
    """Typical E1 growth formula: prev-year revenue * (1 + growth)."""
    state = ModelState(
        base_values={"pl.rev.net": {"Y0": 1000.0}},
        assumptions={"pl.rev.net": {"growth": {"Y1": 0.10}}},
        current_year="Y1",
    )

    formula = "resolve('pl.rev.net', prev_year) * (1 + assumptions['pl.rev.net']['growth'][year])"

    result = evaluate(formula, voice_id="pl.rev.net", year="Y1", state=state)

    assert result == 1100.0


def test_evaluate_safe_div_zero():
    """safe_div returns None on zero denominator; formula degrades to 0.0."""
    state = ModelState()

    # Direct check on the helper
    assert safe_div(10.0, 0) is None
    assert safe_div(10.0, None) is None
    assert safe_div(10.0, 4) == 2.5

    # When safe_div(...) returns None inside a formula, evaluate returns 0.0
    # (float(None) raises TypeError and the exception handler kicks in).
    result = evaluate("safe_div(10, 0)", voice_id="x", year="Y1", state=state)
    assert result == 0.0

    # Combined with a fallback: safe_div(...) or 0  → evaluates to 0.0 cleanly
    result_with_fallback = evaluate(
        "safe_div(10, 0) or 0", voice_id="x", year="Y1", state=state
    )
    assert result_with_fallback == 0.0


def test_evaluate_exception_returns_zero(caplog):
    """Any runtime exception inside the formula → 0.0 + logged warning."""
    state = ModelState(
        base_values={"pl.rev.net": {"Y1": 1000.0}},
    )

    with caplog.at_level(logging.WARNING, logger="backend.domain.engine.formulas"):
        # KeyError: missing assumption
        missing_assumption = evaluate(
            "assumptions['pl.rev.net']['growth']['Y1']",
            voice_id="pl.rev.net",
            year="Y1",
            state=state,
        )
        # NameError: identifier not in whitelist (e.g. __import__ stripped)
        forbidden_name = evaluate(
            "__import__('os').system('echo pwned')",
            voice_id="pl.rev.net",
            year="Y1",
            state=state,
        )
        # ZeroDivisionError: bare division by zero
        divide_by_zero = evaluate(
            "1 / 0", voice_id="pl.rev.net", year="Y1", state=state
        )

    assert missing_assumption == 0.0
    assert forbidden_name == 0.0
    assert divide_by_zero == 0.0
    assert any(
        "formula evaluation failed" in rec.message for rec in caplog.records
    )


def test_pmt_helper():
    """Sanity check on the annuity helper used by E4 term-loan methods."""
    # Zero rate degenerates to principal / n
    assert pmt(1000.0, 0.0, 10) == 100.0
    # Standard annuity: 1000 @ 5% over 10 periods ≈ 129.50
    payment = pmt(1000.0, 0.05, 10)
    assert abs(payment - 129.5046) < 1e-3
    # n <= 0 returns 0.0 (defensive)
    assert pmt(1000.0, 0.05, 0) == 0.0
