"""Typed exceptions raised by the intake parser.

Two flavours:

* ``ParseError`` — the bytes are unreadable / no usable header found.
  Surfaces as HTTP 422 with ``detail`` only.
* ``BalanceValidationError`` — file parsed cleanly but a *block*-level
  post-check failed (BC_001 missing Y0, BC_002 too few voices). The
  parser still produces a partial ``ParsedBalance`` so the API can
  echo the validation report back to the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.api.schemas.balance import ParsedBalance


class ParseError(Exception):
    """Unrecoverable parsing failure (corrupt file, no header, etc.)."""


class BalanceValidationError(Exception):
    """Parsed file violates a block-level post-check."""

    def __init__(self, message: str, parsed: "ParsedBalance") -> None:
        super().__init__(message)
        self.parsed = parsed


__all__ = ["BalanceValidationError", "ParseError"]
