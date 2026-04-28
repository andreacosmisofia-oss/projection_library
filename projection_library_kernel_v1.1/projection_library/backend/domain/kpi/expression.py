"""Tiny parser for KPI numerator / denominator expressions.

The kpi_registry uses three families of formulas:

1. Simple voice reference: ``pl.rev.net[t]``, ``pl.cogs.total[t-1]``,
   ``pl.rev.net[t-3]``. M5 supports these.
2. Compound expressions: ``DSO + DIO_total - DPO``,
   ``abs(borrowings) - cash``, ``(arr + expansion - contr - churn)``.
   M5 marks these as ``unsupported_formula`` — M9's safe formula
   evaluator will pick them up later.
3. Constant ``null`` denominator (e.g. CCC has ``null`` denominator
   because the whole expression is in the numerator). Treated as
   "single-term" by the calculator.

The parser is intentionally narrow: it accepts only the strict pattern
``<voice_id>[<offset>]`` where ``<offset>`` ∈ ``{t, t-1, t-2, t-3}``.
Anything else returns ``None`` and the calculator skips the KPI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SIMPLE_REF = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_.<>]*?)\s*\[\s*(t(?:\s*-\s*[123])?)\s*\]\s*$"
)


@dataclass(frozen=True)
class VoiceRef:
    """Reference to a voice value with a relative year offset.

    ``offset == 0`` means current year ``t``; ``offset == 3`` means
    ``t-3``. The calculator resolves it against the actual sequence of
    historical years for the project.
    """

    voice_id: str
    offset: int

    def shifted(self, anchor_index: int) -> int:
        """Return the absolute index in the year list for this ref.

        ``anchor_index`` is the index of ``t`` (current year). Negative
        results signal "before the available history" → unresolved.
        """
        return anchor_index - self.offset


def parse_voice_ref(expression: str | None) -> VoiceRef | None:
    """Parse ``voice_id[t-k]``-style references; return None on failure."""
    if expression is None:
        return None
    match = _SIMPLE_REF.match(expression)
    if not match:
        return None
    voice_id, lag = match.groups()
    if "<" in voice_id or ">" in voice_id:
        # template placeholder (e.g. "<voice>") — not concrete
        return None
    lag_clean = lag.replace(" ", "")
    if lag_clean == "t":
        offset = 0
    else:
        offset = int(lag_clean.split("-")[1])
    return VoiceRef(voice_id=voice_id, offset=offset)


__all__ = ["VoiceRef", "parse_voice_ref"]
