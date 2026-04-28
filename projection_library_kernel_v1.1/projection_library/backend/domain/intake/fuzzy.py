"""Fuzzy matching for the M4 mapper.

Pure stdlib (`difflib`) per the M4 design note: the synonym table is
expected to absorb most variation; fuzzy is the last-mile strategy
for typos and word-order shuffles. If profiling later shows the
threshold-filtered scan is too slow, swap in ``rapidfuzz`` behind the
same API.

The two public helpers are intentionally minimal:

* :func:`token_set_ratio` — order-insensitive similarity of two
  normalized strings (returns 0..1).
* :func:`top_matches` — ranked best-of-K against a candidate dict
  whose values are the *strings to compare against* and whose keys
  are arbitrary (typically ``voice_id``).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Mapping

from backend.domain.intake.normalize import normalize_text


def _tokens(s: str) -> set[str]:
    return {tok for tok in s.split() if tok}


def token_set_ratio(a: str | None, b: str | None) -> float:
    """Return a 0..1 similarity score between two strings.

    Implementation follows the spirit of `rapidfuzz.fuzz.token_set_ratio`:

    1. Normalise both sides (NFKD, lower, ws-collapsed, no punctuation).
    2. Split into token sets and compute *intersection* and *diffs*.
    3. Compare three reconstructions:

       * ``intersection`` vs. ``intersection ∪ diff_a``
       * ``intersection`` vs. ``intersection ∪ diff_b``
       * ``intersection ∪ diff_a`` vs. ``intersection ∪ diff_b``

       and take the max ratio (so "ricavi delle vendite prodotti" and
       "ricavi prodotti vendite" score 1.0 even though raw character
       similarity is lower).

    Returns 0.0 if either side is empty.
    """
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0

    ta = _tokens(na)
    tb = _tokens(nb)
    if not ta or not tb:
        return 0.0

    inter = sorted(ta & tb)
    diff_a = sorted(ta - tb)
    diff_b = sorted(tb - ta)

    s_inter = " ".join(inter)
    s_a = " ".join(inter + diff_a)
    s_b = " ".join(inter + diff_b)

    candidates = (
        (s_inter, s_a),
        (s_inter, s_b),
        (s_a, s_b),
    )
    best = 0.0
    for left, right in candidates:
        if not left and not right:
            continue
        ratio = SequenceMatcher(a=left, b=right, autojunk=False).ratio()
        if ratio > best:
            best = ratio
    return best


def top_matches(
    query: str,
    candidates: Mapping[str, list[str]],
    *,
    n: int = 5,
    threshold: float = 0.6,
) -> list[tuple[str, float]]:
    """Return the top-``n`` ``(voice_id, score)`` matches for ``query``.

    ``candidates`` maps a voice_id to one or more strings to compare
    against (typically the synonyms). For each voice the best score
    across its strings wins, and only voices clearing ``threshold``
    survive. Output is sorted by descending score; voice_id is the
    deterministic tie-breaker so the same input always produces the
    same order.
    """
    if not query or not candidates:
        return []
    scored: dict[str, float] = {}
    for voice_id, strings in candidates.items():
        if not strings:
            continue
        best = 0.0
        for s in strings:
            ratio = token_set_ratio(query, s)
            if ratio > best:
                best = ratio
        if best >= threshold:
            scored[voice_id] = best
    if not scored:
        return []
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]


__all__ = ["token_set_ratio", "top_matches"]
