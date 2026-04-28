"""Text normalization for the M4 mapper.

Single helper used by both :mod:`synonyms` and :mod:`fuzzy` so the
synonym index and the similarity scoring share the exact same notion
of "same string". Italian bilancio labels mix accents, punctuation,
trailing whitespace and inconsistent casing — normalization absorbs
all of that before any equality or token comparison runs.

stdlib only (`unicodedata`, `re`).
"""

from __future__ import annotations

import re
import unicodedata

# Strip everything that isn't a letter, digit, or whitespace. Keeping
# digits matters for labels like "y0", "ifrs 15", "ias 40".
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_UNDERSCORE_RE = re.compile(r"_+")


def normalize_text(s: str | None) -> str:
    """Return a canonical lower-case, accent-stripped, ws-collapsed form.

    Steps:
      1. NFKD decompose then drop combining marks (è → e, ñ → n).
      2. Lowercase.
      3. Replace underscores with spaces (``share_capital`` and ``share
         capital`` collapse to the same string).
      4. Drop punctuation (``&``, ``/``, ``.``, ``,``, ``(``, ``)`` …);
         the ``\\w`` class keeps letters and digits.
      5. Collapse runs of whitespace to a single space and trim.

    ``None`` and the empty string both return ``""``.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(s))
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = no_marks.lower()
    underscored = _UNDERSCORE_RE.sub(" ", lowered)
    no_punct = _PUNCT_RE.sub(" ", underscored)
    collapsed = _WHITESPACE_RE.sub(" ", no_punct).strip()
    return collapsed


__all__ = ["normalize_text"]
