"""Unit tests for the M3 parser (no DB, no FastAPI)."""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest

from backend.domain.intake import (
    BalanceValidationError,
    ParseError,
    parse_balance,
)
from backend.domain.intake.normalizers import (
    coerce_amount,
    normalize_section,
    normalize_year_label,
)

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _build_xlsx(rows: list[list[object]], sheet_name: str = "Balance") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- normalizers --------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Y0", "Y0"),
        ("y0", "Y0"),
        ("Y-1", "Y-1"),
        ("Y -1", "Y-1"),
        ("Y -3", "Y-3"),
        ("Y1", None),  # future years rejected for intake
        ("Q1", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_year_label(raw, expected):
    assert normalize_year_label(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1500, 1500.0),
        (1500.5, 1500.5),
        ("1500", 1500.0),
        ("1.500,00", 1500.0),
        ("1.500.000,50", 1500000.5),
        ("(890)", -890.0),
        ("(1.234,50)", -1234.5),
        ("-1.234,50", -1234.5),
        ("1,234.56", 1234.56),
        ("1234.56", 1234.56),
        ("1.234,56 €", 1234.56),
        ("", None),
        (None, None),
        ("not a number", None),
    ],
)
def test_coerce_amount(raw, expected):
    assert coerce_amount(raw) == expected


def test_coerce_amount_unit_thousands():
    assert coerce_amount(1500, unit="thousands") == 1_500_000.0


def test_normalize_section_canonical_passes_through():
    assert normalize_section("P&L") == "P&L"
    assert normalize_section("SP_assets") == "SP_assets"


def test_normalize_section_via_alias_and_hint():
    assert normalize_section("Conto Economico") == "P&L"
    assert normalize_section(None, sheet_hint="P&L") == "P&L"
    assert normalize_section("attivo") == "SP_assets"


def test_normalize_section_unknown_falls_to_other():
    assert normalize_section("alien") == "OTHER"
    assert normalize_section(None) is None


# ---------- parser on sample files --------------------------------------


def test_parse_tier2_industrial_clean():
    data = (SAMPLE_DIR / "tier2_industrial_clean.xlsx").read_bytes()
    parsed = parse_balance(data, "tier2_industrial_clean.xlsx", "gestionale")
    assert parsed.voice_count == 24
    assert parsed.years_present == ["Y-1", "Y0"]
    assert parsed.validation.errors == []
    labels = {v.user_label for v in parsed.voices}
    assert "Ricavi delle vendite" in labels
    sections = {v.user_section for v in parsed.voices}
    assert {"P&L", "SP_assets", "SP_liabilities", "SP_equity"} <= sections


def test_parse_tier1_minimal_balance_only_y0():
    data = (SAMPLE_DIR / "tier1_minimal_balance.xlsx").read_bytes()
    parsed = parse_balance(data, "tier1_minimal_balance.xlsx", "gestionale")
    assert parsed.years_present == ["Y0"]
    info_codes = {item.code for item in parsed.validation.info}
    assert "BC_005" in info_codes  # Y-1/Y-2/Y-3 missing → info entry


# ---------- parser block-level errors -----------------------------------


def test_parse_blocks_when_no_y0():
    rows = [
        ["voice_label", "voice_section", "Y-1"],
        ["Ricavi", "P&L", 100],
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Cassa", "SP_assets", 50],
    ]
    data = _build_xlsx(rows)
    with pytest.raises(BalanceValidationError) as exc:
        parse_balance(data, "no_y0.xlsx", "gestionale")
    codes = {i.code for i in exc.value.parsed.validation.errors}
    assert "BC_001" in codes


def test_parse_blocks_when_too_few_voices():
    rows = [
        ["voice_label", "voice_section", "Y0"],
        ["Ricavi", "P&L", 100],
        ["COGS", "P&L", -40],
    ]
    data = _build_xlsx(rows)
    with pytest.raises(BalanceValidationError) as exc:
        parse_balance(data, "few.xlsx", "gestionale")
    codes = {i.code for i in exc.value.parsed.validation.errors}
    assert "BC_002" in codes


def test_parse_unsupported_extension_raises_parse_error():
    with pytest.raises(ParseError):
        parse_balance(b"some bytes", "balance.pdf", "gestionale")


def test_parse_no_header_raises_parse_error():
    rows = [
        ["just", "random", "stuff"],
        ["nothing", "to", "see"],
    ]
    data = _build_xlsx(rows)
    with pytest.raises(ParseError):
        parse_balance(data, "blank.xlsx", "gestionale")


# ---------- parser warnings/info -----------------------------------------


def test_parse_warns_on_duplicate_label():
    rows = [
        ["voice_label", "voice_section", "Y0"],
        ["Ricavi", "P&L", 100],
        ["Ricavi", "P&L", 50],  # duplicate within section
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Cassa", "SP_assets", 50],
    ]
    data = _build_xlsx(rows)
    parsed = parse_balance(data, "dup.xlsx", "gestionale")
    codes = {w.code for w in parsed.validation.warnings}
    assert "BC_003" in codes


def test_parse_warns_on_unparsable_amount():
    rows = [
        ["voice_label", "voice_section", "Y0"],
        ["Ricavi", "P&L", "not-a-number"],
        ["COGS", "P&L", -40],
        ["Personale", "P&L", -20],
        ["PPE", "SP_assets", 200],
        ["Crediti", "SP_assets", 80],
        ["Cassa", "SP_assets", 50],
    ]
    data = _build_xlsx(rows)
    parsed = parse_balance(data, "bad_amount.xlsx", "gestionale")
    codes = {w.code for w in parsed.validation.warnings}
    assert "UNPARSABLE_AMOUNT" in codes


def test_parse_csv_with_italian_numbers_and_semicolon():
    csv_body = (
        "voice_label;voice_section;Y-1;Y0\n"
        "Ricavi;P&L;1.890,00;2.100,50\n"
        "COGS;P&L;(990,00);(1.100,00)\n"
        "Personale;P&L;-378,00;-420,00\n"
        "PPE;SP_assets;828;920\n"
        "Crediti;SP_assets;342;380\n"
        "Cassa;SP_assets;197;217\n"
    ).encode("utf-8")
    parsed = parse_balance(csv_body, "balance.csv", "gestionale")
    assert parsed.voice_count == 6
    assert parsed.years_present == ["Y-1", "Y0"]
    ricavi = next(v for v in parsed.voices if v.user_label == "Ricavi")
    assert ricavi.values == {"Y-1": 1890.0, "Y0": 2100.5}
    cogs = next(v for v in parsed.voices if v.user_label == "COGS")
    assert cogs.values == {"Y-1": -990.0, "Y0": -1100.0}


def test_parse_emits_info_when_no_section_provided():
    rows = [
        ["voice_label", "Y0"],
        ["Ricavi", 100],
        ["COGS", -40],
        ["Personale", -20],
        ["PPE", 200],
        ["Crediti", 80],
        ["Cassa", 50],
    ]
    data = _build_xlsx(rows, sheet_name="Sheet1")
    parsed = parse_balance(data, "no_section.xlsx", "gestionale")
    codes = {i.code for i in parsed.validation.info}
    assert "BC_004" in codes


def test_parse_uses_sheet_name_as_section_hint():
    rows = [
        ["voice_label", "Y0"],
        ["Ricavi", 100],
        ["COGS", -40],
        ["Personale", -20],
        ["PPE", 200],
        ["Crediti", 80],
        ["Cassa", 50],
    ]
    data = _build_xlsx(rows, sheet_name="P&L")
    parsed = parse_balance(data, "from_sheet.xlsx", "gestionale")
    assert all(v.user_section == "P&L" for v in parsed.voices)
