"""Unit tests for the M4 mapper.

Exercises the four pure modules in isolation: ``normalize``,
``synonyms``, ``fuzzy``, ``mapper``. The mapper tests use a tiny
hand-built voice/synonym fixture so the assertions don't depend on
the production registry size.
"""

from __future__ import annotations

import pytest

from backend.domain.intake.fuzzy import token_set_ratio, top_matches
from backend.domain.intake.mapper import (
    RawVoiceInput,
    auto_suggest,
)
from backend.domain.intake.normalize import normalize_text
from backend.domain.intake.synonyms import SynonymIndex, build_synonym_index


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_text():
    cases = {
        None: "",
        "": "",
        "  ": "",
        "Ricavi delle Vendite": "ricavi delle vendite",
        "RICAVI DELLE VENDITE": "ricavi delle vendite",
        "Ricavi  delle\tVendite": "ricavi delle vendite",
        "Ammortamento immateriali": "ammortamento immateriali",
        "Cassa & Banche": "cassa banche",
        "perdite/utili su cambi": "perdite utili su cambi",
        "Ricavi - prodotti.": "ricavi prodotti",
        "Acquisti materie prime (€)": "acquisti materie prime",
        "Crediti vs. clienti": "crediti vs clienti",
        "Utile d'esercizio": "utile d esercizio",
        "share_capital_close": "share capital close",
    }
    for raw, expected in cases.items():
        assert normalize_text(raw) == expected, raw


# ---------------------------------------------------------------------------
# synonyms
# ---------------------------------------------------------------------------


def test_synonym_lookup_it():
    """Strategy B: exact match on an Italian synonym from the production YAML."""
    index = build_synonym_index()
    # Hits across both letter case and accent stripping.
    assert index.lookup("Ricavi delle vendite") == "pl.rev.gross.product_sales"
    assert index.lookup("ACQUISTI MATERIE PRIME") == "pl.cogs.materials.raw"
    assert (
        index.lookup("Capitale Sociale finale")
        == "bs.equity.share_capital.close"
    )
    # Misses
    assert index.lookup("not a known label whatsoever") is None
    assert index.lookup("") is None
    assert index.lookup(None) is None


def test_synonym_lookup_en():
    """English synonyms are indexed alongside the Italian ones."""
    index = build_synonym_index()
    assert index.lookup("Net Revenue") == "pl.rev.net"
    assert index.lookup("EBITDA") == "pl.ebitda"
    assert index.lookup("Total Equity Closing") == "bs.equity.total_close"
    assert index.lookup("cash and cash equivalents") == "bs.nfp.cash"
    # Coverage sanity: at least 100 voices, ≥3 synonyms each (M4 floor).
    assert index.voice_count() >= 100
    for vid, syns in index.by_voice.items():
        assert len(syns) >= 3, f"{vid} has {len(syns)} synonyms"


# ---------------------------------------------------------------------------
# fuzzy
# ---------------------------------------------------------------------------


def test_fuzzy_exact_match():
    """Identical normalized inputs score 1.0."""
    assert token_set_ratio("Ricavi delle Vendite", "ricavi delle vendite") == 1.0
    assert token_set_ratio("EBITDA", "ebitda") == 1.0
    # Token-set is order-insensitive.
    assert (
        token_set_ratio("ricavi delle vendite prodotti", "vendite prodotti ricavi delle")
        == 1.0
    )


def test_fuzzy_partial_match():
    """Close-but-not-equal labels rank above unrelated ones."""
    score_typo = token_set_ratio("ricavi vendite", "ricavi vendita")
    score_random = token_set_ratio("ricavi vendite", "stipendi personale")
    assert score_typo > 0.6
    assert score_random < score_typo
    # top_matches respects the threshold + n cap.
    candidates = {
        "pl.rev.gross.product_sales": ["ricavi delle vendite", "ricavi prodotti"],
        "pl.opex.ga.personnel": ["personale amministrativo"],
        "pl.opex.sm.personnel": ["personale commerciale"],
    }
    matches = top_matches(
        "ricavi delle vendite",
        candidates,
        n=2,
        threshold=0.6,
    )
    assert len(matches) >= 1
    assert matches[0][0] == "pl.rev.gross.product_sales"
    assert matches[0][1] >= 0.95


# ---------------------------------------------------------------------------
# mapper
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_voices() -> dict[str, dict]:
    return {
        "pl.rev.gross.product_sales": {"statement": "PL", "section": "rev.gross"},
        "pl.cogs.materials.raw": {"statement": "PL", "section": "cogs"},
        "bs.nfp.cash": {"statement": "BS", "section": "nfp"},
    }


@pytest.fixture()
def fixture_synonyms() -> SynonymIndex:
    by_synonym = {
        normalize_text("ricavi delle vendite"): "pl.rev.gross.product_sales",
        normalize_text("vendite prodotti"): "pl.rev.gross.product_sales",
        normalize_text("acquisti materie prime"): "pl.cogs.materials.raw",
        normalize_text("cassa"): "bs.nfp.cash",
        normalize_text("disponibilita liquide"): "bs.nfp.cash",
    }
    by_voice: dict[str, list[str]] = {}
    for syn, vid in by_synonym.items():
        by_voice.setdefault(vid, []).append(syn)
    return SynonymIndex(by_synonym=by_synonym, by_voice=by_voice)


def test_auto_suggest_returns_candidates(fixture_voices, fixture_synonyms):
    raw = [
        RawVoiceInput(user_label="Ricavi delle vendite", user_section="P&L"),
        RawVoiceInput(user_label="Acquisti materie prime", user_section="P&L"),
        RawVoiceInput(user_label="Cassa", user_section="SP_assets"),
        RawVoiceInput(user_label="voce esoterica sconosciuta", user_section=None),
    ]
    suggestions, stats = auto_suggest(
        raw,
        sector_pack="industrial",
        company_name=None,
        synonyms=fixture_synonyms,
        voices=fixture_voices,
    )
    assert stats.total_voices == 4
    assert suggestions[0].candidates[0].voice_id == "pl.rev.gross.product_sales"
    # Synonym hit (0.95) plus matching P&L section (+0.10) clamped to 1.0.
    assert suggestions[0].candidates[0].confidence >= 0.95
    assert suggestions[0].candidates[0].reason == "synonym_match"
    assert suggestions[1].candidates[0].voice_id == "pl.cogs.materials.raw"
    assert suggestions[2].candidates[0].voice_id == "bs.nfp.cash"
    # Section penalty makes "Cassa" with section "SP_assets" still a hit
    # (BS statement matches), confidence stays high.
    assert suggestions[2].candidates[0].confidence >= 0.95
    # Unknown label produces no candidates.
    assert suggestions[3].candidates == []
    assert stats.high_confidence == 3
    assert stats.no_match == 1


def test_company_history_priority(fixture_voices, fixture_synonyms):
    """Strategy A wins over a synonym hit pointing at a different voice."""

    class StubMapping:
        voice_id_system = "pl.cogs.materials.raw"  # deliberately "wrong"

    class StubScalars:
        def first(self):
            return StubMapping()

    class StubResult:
        def scalars(self):
            return StubScalars()

    class StubSession:
        def execute(self, _stmt):
            return StubResult()

    raw = [
        RawVoiceInput(user_label="Ricavi delle vendite", user_section="P&L"),
    ]
    suggestions, _ = auto_suggest(
        raw,
        sector_pack="industrial",
        company_name="Acme SpA",
        synonyms=fixture_synonyms,
        voices=fixture_voices,
        db=StubSession(),
    )
    top = suggestions[0].candidates[0]
    # company_history takes precedence (1.0) over the synonym match (0.95+).
    assert top.reason == "company_history"
    assert top.voice_id == "pl.cogs.materials.raw"
    assert top.confidence == 1.0
