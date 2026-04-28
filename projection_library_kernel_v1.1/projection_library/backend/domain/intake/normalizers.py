"""Pure helpers used by the parser.

Kept separate so they can be unit-tested without spinning up the
file-reading pipeline.
"""

from __future__ import annotations

import math
import re

YEAR_KEYS: tuple[str, ...] = ("Y-3", "Y-2", "Y-1", "Y0")

_SECTION_ALIASES: dict[str, str] = {
    "P&L": "P&L",
    "PL": "P&L",
    "P&L_PL": "P&L",
    "INCOME_STATEMENT": "P&L",
    "INCOMESTATEMENT": "P&L",
    "CONTO_ECONOMICO": "P&L",
    "CONTOECONOMICO": "P&L",
    "SP_ASSETS": "SP_assets",
    "SP_ASSET": "SP_assets",
    "ASSETS": "SP_assets",
    "ATTIVO": "SP_assets",
    "STATO_PATRIMONIALE_ATTIVO": "SP_assets",
    "SP_LIABILITIES": "SP_liabilities",
    "SP_LIAB": "SP_liabilities",
    "LIABILITIES": "SP_liabilities",
    "PASSIVO": "SP_liabilities",
    "STATO_PATRIMONIALE_PASSIVO": "SP_liabilities",
    "SP_EQUITY": "SP_equity",
    "EQUITY": "SP_equity",
    "PATRIMONIO_NETTO": "SP_equity",
    "PN": "SP_equity",
    "CF_OPERATING": "CF_operating",
    "CF_OP": "CF_operating",
    "OPERATING": "CF_operating",
    "CF_INVESTING": "CF_investing",
    "CF_INV": "CF_investing",
    "INVESTING": "CF_investing",
    "CF_FINANCING": "CF_financing",
    "CF_FIN": "CF_financing",
    "FINANCING": "CF_financing",
    "OTHER": "OTHER",
    "ALTRO": "OTHER",
}

_VALID_SECTIONS: frozenset[str] = frozenset(
    {
        "P&L",
        "SP_assets",
        "SP_liabilities",
        "SP_equity",
        "CF_operating",
        "CF_investing",
        "CF_financing",
        "OTHER",
    }
)

_UNIT_MULTIPLIER: dict[str, float] = {
    "units": 1.0,
    "thousands": 1_000.0,
    "millions": 1_000_000.0,
}


def normalize_year_label(label: str) -> str | None:
    """Map a header cell to one of ``Y-3 | Y-2 | Y-1 | Y0``.

    Tolerates ``"Y0"``, ``"Y 0"``, ``"y-1"``, ``"Y -1"`` and full-width
    spaces. Returns ``None`` if the cell is not a year column.
    """
    if label is None:
        return None
    s = str(label).strip().upper().replace(" ", "").replace(" ", "")
    if not s:
        return None
    m = re.fullmatch(r"Y([+-]?\d+)", s)
    if not m:
        return None
    n = int(m.group(1))
    if n == 0:
        return "Y0"
    if -3 <= n <= -1:
        return f"Y{n}"
    return None


def normalize_section(value: object, sheet_hint: str | None = None) -> str | None:
    """Return a canonical ``voice_section`` enum value.

    Lookup order: explicit cell value, then sheet-name hint. Unknown
    free-text falls through to ``OTHER`` so the parser never drops a
    row only because the section label is exotic — the mapper (M4)
    will deal with it.
    """
    candidates: list[str] = []
    if value is not None:
        s = str(value).strip()
        if s:
            candidates.append(s)
    if sheet_hint is not None:
        s = str(sheet_hint).strip()
        if s:
            candidates.append(s)

    for raw in candidates:
        if raw in _VALID_SECTIONS:
            return raw
        key = re.sub(r"[\s\-/]+", "_", raw.upper())
        if raw.upper().replace(" ", "") == "P&L":
            return "P&L"
        if key in _SECTION_ALIASES:
            return _SECTION_ALIASES[key]

    if candidates:
        return "OTHER"
    return None


_PAREN_NUMBER = re.compile(r"^\((.*)\)$")


def coerce_amount(raw: object, unit: str = "units") -> float | None:
    """Convert a cell value to a float.

    Accepts:
      * native ``int`` / ``float`` (NaN → ``None``)
      * empty / whitespace strings → ``None``
      * Italian formatted numbers ``"1.500,00"`` → 1500.0
      * Plain decimal ``"1500.5"`` → 1500.5
      * Parenthesised negatives ``"(890)"`` → -890.0
      * Trailing currency symbol ``"1.234,50 €"`` → 1234.5

    Anything else returns ``None`` (the row will trigger an
    ``EMPTY_LABEL`` / ``UNPARSABLE_AMOUNT`` warning in the caller).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and math.isnan(raw):
            return None
        return float(raw) * _UNIT_MULTIPLIER.get(unit, 1.0)

    s = str(raw).strip()
    if not s:
        return None

    s = s.replace(" ", " ").replace("€", "").replace("EUR", "").strip()
    negative = False
    m = _PAREN_NUMBER.match(s)
    if m:
        negative = True
        s = m.group(1).strip()

    if not s:
        return None
    if s.startswith("-"):
        negative = not negative
        s = s[1:].strip()
    if s.startswith("+"):
        s = s[1:].strip()

    s = s.replace(" ", "")

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")

    try:
        value = float(s)
    except ValueError:
        return None

    if negative:
        value = -value
    return value * _UNIT_MULTIPLIER.get(unit, 1.0)


__all__ = [
    "YEAR_KEYS",
    "coerce_amount",
    "normalize_section",
    "normalize_year_label",
]
