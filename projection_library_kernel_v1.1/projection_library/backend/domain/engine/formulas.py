"""Safe formula evaluator for method_registry formula_expression.

ARCHITECTURE invariant 6: "no eval() libero". eval is invoked here with
``__builtins__`` stripped and a whitelisted namespace, so formula authors
can only reach ``resolve``, ``safe_div``, ``pmt``, the basic math
reductions, and the read-only state dicts.

A single bad formula must never crash the engine run (Flow 07, "Edge
cases"). Failure modes are differentiated:

* ``KeyError`` — a missing assumption / driver / kpi key is the typical
  symptom of a partially configured project. We log, append a structured
  entry to ``state.approximation_log`` and return the previous-year
  value of the voice (flat fallback). For Y1 the previous year is Y0
  (historical), so the projection silently rolls last year's actual
  forward.
* ``ZeroDivisionError`` — legitimate division by zero in the formula;
  collapse to 0.0 without polluting the approximation log.
* Any other exception — log and return ``None`` so the caller (the
  phase dispatcher) can decide whether to apply the flat fallback or
  skip the voice.
"""

from __future__ import annotations

import logging
from typing import Optional

from .value_resolver import ModelState, get_prev_year, resolve_voice_value

logger = logging.getLogger(__name__)


def safe_div(num: float, den: float) -> Optional[float]:
    """Division returning None when the denominator is zero/None."""
    if den is None or den == 0:
        return None
    return num / den


def pmt(principal: float, rate: float, n: int) -> float:
    """Annuity payment for ``principal`` over ``n`` periods at ``rate``.

    Returns the per-period payment as a positive number; sign convention
    is applied by the caller.
    """
    if n <= 0:
        return 0.0
    if rate == 0:
        return principal / n
    return rate * principal / (1 - (1 + rate) ** (-n))


def evaluate(
    formula_python: str,
    voice_id: str,
    year: str,
    state: ModelState,
) -> Optional[float]:
    """Evaluate a formula string in a whitelisted namespace.

    Returns the numeric result, the flat-fallback value on ``KeyError``,
    ``0.0`` on ``ZeroDivisionError``, or ``None`` for any other exception
    (logged as warning). The namespace is intentionally narrow:
      * ``resolve(v, y)`` — effective voice value with override overlay
      * ``safe_div``, ``pmt`` — finance helpers
      * ``abs``, ``max``, ``min``, ``sum`` — basic reductions
      * ``assumptions``, ``drivers``, ``kpis`` — read-only state dicts
        (``kpis`` points to ``historical_kpis`` so the namespace stays
        consistent with KPI references in formulas)
      * ``year``, ``prev_year``, ``voice`` — context constants
    """
    prev_year = get_prev_year(year)
    namespace = {
        "__builtins__": {},
        "resolve": lambda v, y: resolve_voice_value(v, y, state),
        "safe_div": safe_div,
        "pmt": pmt,
        "abs": abs,
        "max": max,
        "min": min,
        "sum": sum,
        "assumptions": state.assumptions,
        "drivers": state.drivers,
        "kpis": state.historical_kpis,
        "year": year,
        "prev_year": prev_year,
        "voice": voice_id,
    }
    try:
        result = eval(formula_python, namespace)  # noqa: S307 - whitelisted namespace
        if result is None:
            return 0.0
        return float(result)
    except KeyError as exc:
        logger.warning(
            "%s missing key %s in %s", voice_id, exc, year
        )
        fallback = resolve_voice_value(voice_id, prev_year, state)
        state.approximation_log.append(
            {
                "type": "missing_key_flat_fallback",
                "voice_id": voice_id,
                "year": year,
                "missing_key": str(exc),
                "fallback_value": fallback,
            }
        )
        return fallback
    except ZeroDivisionError:
        return 0.0
    except Exception as exc:
        logger.warning(
            "formula evaluation failed: voice=%s year=%s formula=%r error=%s",
            voice_id,
            year,
            formula_python,
            exc,
        )
        return None


__all__ = ["safe_div", "pmt", "evaluate"]
