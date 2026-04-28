"""Balance file parser — flow ``flows/01_data_intake.md``.

Pipeline:

1. Detect format from filename (``.xlsx`` / ``.xls`` / ``.csv``).
2. Read sheets via :mod:`readers`. Each sheet is searched for a header
   row containing ``voice_label`` plus at least one ``Y…`` column.
3. Each data row produces a :class:`ParsedVoice`. Numbers are coerced
   via :func:`normalize_amount` (Italian formats, parentheses-as-minus
   supported).
4. Post-parse checks (``BC_001..BC_005``) populate the validation
   report. ``BC_001`` (no Y0) and ``BC_002`` (<5 voices) raise
   :class:`BalanceValidationError` so the caller can answer 422.
"""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from backend.api.schemas.balance import (
    BalanceValidationItem,
    BalanceValidationReport,
    ParsedBalance,
    ParsedVoice,
    SourceType,
)
from backend.domain.intake.exceptions import (
    BalanceValidationError,
    ParseError,
)
from backend.domain.intake.normalizers import (
    YEAR_KEYS,
    coerce_amount,
    normalize_section,
    normalize_year_label,
)
from backend.domain.intake.readers import (
    RawSheet,
    detect_format,
    read_csv,
    read_xlsx,
)

_LABEL_KEYS = ("voice_label", "voce", "label", "voice")
_SECTION_KEYS = ("voice_section", "section", "sezione")
_MIN_VOICES = 5


def parse_balance(
    file_bytes: bytes,
    filename: str,
    source_type: SourceType,
    unit: str = "units",
) -> ParsedBalance:
    """Parse the uploaded file into a :class:`ParsedBalance`.

    Raises :class:`ParseError` for unrecoverable file-level failures
    and :class:`BalanceValidationError` (carrying the partial parsed
    object) for block-level post-checks.
    """
    fmt = detect_format(filename)
    if fmt == "xlsx":
        sheets = read_xlsx(file_bytes)
    else:
        sheets = read_csv(file_bytes)

    report = BalanceValidationReport()
    voices = _extract_voices_from_sheets(sheets, report, unit)
    voices = _merge_duplicates(voices, report)

    years_present = _detect_years(voices)

    if not voices:
        report.errors.append(
            BalanceValidationItem(
                code="BC_002",
                severity="block",
                message="no parsable rows were found in the file",
            )
        )

    parsed = ParsedBalance(
        source_type=source_type,
        raw_filename=filename,
        years_present=years_present,
        voice_count=len(voices),
        voices=voices,
        validation=report,
    )

    _post_parse_checks(parsed, report)

    if any(item.severity == "block" for item in report.errors):
        raise BalanceValidationError("balance file failed block-level checks", parsed)

    return parsed


def _extract_voices_from_sheets(
    sheets: list[RawSheet],
    report: BalanceValidationReport,
    unit: str,
) -> list[ParsedVoice]:
    """Walk every sheet, locate the header, materialise rows."""
    out: list[ParsedVoice] = []
    used_any_sheet = False

    for sheet in sheets:
        header_idx, columns = _find_header(sheet)
        if header_idx is None or columns is None:
            continue
        used_any_sheet = True
        section_hint = _section_hint_from_sheet_name(sheet.name)

        for row_idx in range(header_idx + 1, len(sheet.rows)):
            row = sheet.rows[row_idx]
            if not row or all(cell is None or _is_blank(cell) for cell in row):
                continue
            voice = _row_to_voice(row, columns, section_hint, unit, report)
            if voice is not None:
                out.append(voice)

    if not used_any_sheet:
        raise ParseError(
            "no sheet contains a recognisable header "
            "(expected 'voice_label' plus at least one Y… column)"
        )
    return out


def _find_header(
    sheet: RawSheet,
) -> tuple[int | None, "_HeaderColumns | None"]:
    """Locate the first row that looks like the schema header."""
    for idx, row in enumerate(sheet.rows[:50]):  # cap scan to first 50 rows
        if not row:
            continue
        label_col: int | None = None
        section_col: int | None = None
        year_cols: dict[str, int] = {}

        for col_idx, cell in enumerate(row):
            if cell is None:
                continue
            text = str(cell).strip().lower()
            if not text:
                continue
            if label_col is None and text in _LABEL_KEYS:
                label_col = col_idx
                continue
            if section_col is None and text in _SECTION_KEYS:
                section_col = col_idx
                continue
            year = normalize_year_label(cell)
            if year and year not in year_cols:
                year_cols[year] = col_idx

        if label_col is not None and year_cols:
            return idx, _HeaderColumns(label_col, section_col, year_cols)
    return None, None


def _row_to_voice(
    row: list[object | None],
    columns: "_HeaderColumns",
    section_hint: str | None,
    unit: str,
    report: BalanceValidationReport,
) -> ParsedVoice | None:
    label_raw = row[columns.label] if columns.label < len(row) else None
    if label_raw is None:
        return None
    label = str(label_raw).strip()
    if not label or _is_numeric(label_raw):
        report.warnings.append(
            BalanceValidationItem(
                code="EMPTY_LABEL",
                severity="warning",
                message="row skipped: voice_label is empty or numeric",
                context={"label": str(label_raw)},
            )
        )
        return None

    section_raw: object | None = None
    if columns.section is not None and columns.section < len(row):
        section_raw = row[columns.section]
    section = normalize_section(section_raw, section_hint)

    values: dict[str, float | None] = {}
    for year, col_idx in columns.years.items():
        if col_idx >= len(row):
            continue
        cell = row[col_idx]
        amount = coerce_amount(cell, unit=unit)
        if amount is None and cell is not None and not _is_blank(cell):
            report.warnings.append(
                BalanceValidationItem(
                    code="UNPARSABLE_AMOUNT",
                    severity="warning",
                    message=(
                        f"could not parse value for '{label}' / {year} "
                        f"({cell!r}); treated as missing"
                    ),
                    context={"label": label, "year": year, "raw": str(cell)},
                )
            )
        values[year] = amount

    if not any(v is not None for v in values.values()):
        return None

    return ParsedVoice(user_label=label, user_section=section, values=values)


def _merge_duplicates(
    voices: list[ParsedVoice],
    report: BalanceValidationReport,
) -> list[ParsedVoice]:
    """Detect duplicate ``(label, section)`` pairs.

    Per BC_003 we emit a warning but do **not** drop or merge the rows:
    the user might have intended manual aggregation. The mapper (M4)
    is the right place to disambiguate.
    """
    seen: dict[tuple[str, str | None], int] = defaultdict(int)
    for v in voices:
        key = (v.user_label.strip().lower(), v.user_section)
        seen[key] += 1

    duplicates = {k: c for k, c in seen.items() if c > 1}
    for (label, section), count in duplicates.items():
        report.warnings.append(
            BalanceValidationItem(
                code="BC_003",
                severity="warning",
                message=(
                    f"voice_label '{label}' appears {count} times in section "
                    f"{section!r}"
                ),
                context={"label": label, "section": section, "count": count},
            )
        )
    return voices


def _detect_years(voices: list[ParsedVoice]) -> list[str]:
    seen = {
        year
        for voice in voices
        for year, value in voice.values.items()
        if value is not None
    }
    return [y for y in YEAR_KEYS if y in seen]


def _post_parse_checks(
    parsed: ParsedBalance, report: BalanceValidationReport
) -> None:
    has_y0 = "Y0" in parsed.years_present
    if not has_y0:
        report.errors.append(
            BalanceValidationItem(
                code="BC_001",
                severity="block",
                message="Y0 is mandatory: no voice has a non-null Y0 value",
            )
        )
    if parsed.voice_count > 0 and parsed.voice_count < _MIN_VOICES:
        report.errors.append(
            BalanceValidationItem(
                code="BC_002",
                severity="block",
                message=(
                    f"balance has only {parsed.voice_count} voices "
                    f"(minimum is {_MIN_VOICES})"
                ),
                context={"voice_count": parsed.voice_count},
            )
        )

    sections = {v.user_section for v in parsed.voices}
    if not sections or sections == {None}:
        report.info.append(
            BalanceValidationItem(
                code="BC_004",
                severity="info",
                message="no voice_section provided — mapper confidence will be reduced",
            )
        )

    missing_years = [y for y in YEAR_KEYS if y not in parsed.years_present]
    if missing_years:
        report.info.append(
            BalanceValidationItem(
                code="BC_005",
                severity="info",
                message=f"years not present in the file: {missing_years}",
                context={"missing": missing_years},
            )
        )


_GENERIC_SHEET_NAMES = frozenset({"sheet", "sheet1", "foglio", "foglio1", "csv"})


def _section_hint_from_sheet_name(name: str) -> str | None:
    """Promote a sheet name to a section hint only if it is meaningful.

    Generic names (``Sheet``, ``Foglio1``, ``Balance``, etc.) and the
    placeholder ``"csv"`` are deliberately ignored: a hint that resolves
    to ``OTHER`` would suppress the BC_004 'no section provided' info
    item even though the user effectively didn't tag any voice.
    """
    if not name:
        return None
    cleaned = name.strip().lower()
    if cleaned in _GENERIC_SHEET_NAMES:
        return None
    if cleaned in {"balance", "bilancio"}:
        return None
    canonical = normalize_section(name)
    if canonical in (None, "OTHER"):
        return None
    return cast(str | None, canonical)


def _is_numeric(value: object) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    s = str(value).strip()
    if not s:
        return False
    try:
        float(s.replace(",", "."))
        return True
    except ValueError:
        return False


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


class _HeaderColumns:
    __slots__ = ("label", "section", "years")

    def __init__(
        self,
        label: int,
        section: int | None,
        years: dict[str, int],
    ) -> None:
        self.label = label
        self.section = section
        self.years = years


__all__ = ["parse_balance"]
