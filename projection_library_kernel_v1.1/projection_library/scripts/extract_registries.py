"""Extract registry YAMLs from Projection_Library_Spec_v1.1.xlsx.

M1.2 — currently extracts only 02_voices → registries/voice_registry.yaml.
Validates each record against data_contracts/registries/voice_registry.schema.json.
Records that fail validation are reported and skipped; valid records are emitted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = ROOT / "Projection_Library_Spec_v1.1.xlsx"
SCHEMA_DIR = ROOT / "data_contracts" / "registries"
OUT_DIR = ROOT / "registries"

# Audit M1.0 §8.2 — composite Excel values → atomic enum.
NATURE_MAP = {
    "driver": "driver",
    "driver (placeholder)": "driver_placeholder",
    "driver (slot)": "driver_slot",
    "derived": "derived",
    "derived (identity)": "derived_identity",
    "reference": "reference",
    "placeholder": "placeholder",
}

# Audit M1.0 §8.3 — composite calc_phase → (proxy, final).
CALC_PHASE_MAP = {
    "E1": (None, "E1"),
    "E2": (None, "E2"),
    "E3": (None, "E3"),
    "E3.1": (None, "E3_1"),
    "E4": (None, "E4"),
    "E5": (None, "E5"),
    "E6": (None, "E6"),
    "E7": (None, "E7"),
    "E7.5": (None, "E7_5"),
    "E8": (None, "E8"),
    "E1 proxy / E3 final": ("E1", "E3"),
    "E1 proxy / E3.1 final": ("E1", "E3_1"),
    "E4 proxy / E8 check": ("E4", "E8"),
    "E7.5 final (E3 proxy)": ("E3", "E7_5"),
}

VOICES_SHEET = "02_voices"
VOICES_HEADER_ROW = 4
VOICES_DATA_START = 5
FOOTER_PREFIXES = ("Totali", "•", "Note")


def _clean(value):
    """Normalize cell values: strip strings, treat empty / em-dash as None."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if v == "" or v == "—":
            return None
        return v
    return value


def _is_footer(voice_id: str | None) -> bool:
    if voice_id is None:
        return False
    return any(voice_id.startswith(p) for p in FOOTER_PREFIXES)


def extract_voices(ws) -> list[dict]:
    headers = [c.value for c in ws[VOICES_HEADER_ROW]]
    expected = [
        "voice_id", "statement", "section", "nature", "sign", "default_method",
        "calc_phase", "denominator/flow voice", "recurrence", "note",
    ]
    if headers[: len(expected)] != expected:
        raise RuntimeError(f"Unexpected headers in {VOICES_SHEET}: {headers}")

    records: list[dict] = []
    for row in ws.iter_rows(min_row=VOICES_DATA_START, values_only=True):
        voice_id = _clean(row[0])
        if voice_id is None:
            break  # first empty row → stop
        if _is_footer(voice_id):
            continue

        statement = _clean(row[1])
        section = _clean(row[2])
        nature_raw = _clean(row[3])
        sign = _clean(row[4])
        default_method = _clean(row[5])
        calc_phase_raw = _clean(row[6])
        denom = _clean(row[7])
        recurrence = _clean(row[8])
        note = _clean(row[9])

        nature = NATURE_MAP.get(nature_raw, nature_raw)
        if calc_phase_raw is None:
            calc_phase_proxy, calc_phase_final = None, None
        elif calc_phase_raw in CALC_PHASE_MAP:
            calc_phase_proxy, calc_phase_final = CALC_PHASE_MAP[calc_phase_raw]
        else:
            # Unknown composite → leave raw in final to surface the issue via schema validation.
            calc_phase_proxy, calc_phase_final = None, calc_phase_raw

        records.append({
            "voice_id": voice_id,
            "statement": statement,
            "section": section,
            "nature": nature,
            "sign": sign,
            "default_method": default_method,
            "calc_phase_proxy": calc_phase_proxy,
            "calc_phase_final": calc_phase_final,
            "denominator_flow_voice": denom,
            "recurrence": recurrence,
            "note": note,
        })
    return records


def validate(records: list[dict], schema: dict) -> tuple[list[dict], list[tuple[dict, str]]]:
    item_validator = Draft202012Validator(schema["$defs"]["VoiceEntry"])
    valid: list[dict] = []
    invalid: list[tuple[dict, str]] = []
    for rec in records:
        errors = sorted(item_validator.iter_errors(rec), key=lambda e: e.path)
        if errors:
            msg = "; ".join(f"{list(e.path) or '<root>'}: {e.message}" for e in errors)
            invalid.append((rec, msg))
        else:
            valid.append(rec)
    return valid, invalid


def main() -> int:
    schema_path = SCHEMA_DIR / "voice_registry.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb[VOICES_SHEET]
    records = extract_voices(ws)
    valid, invalid = validate(records, schema)

    if invalid:
        print(f"VALIDATION FAILURES — {len(invalid)} record(s):", file=sys.stderr)
        for rec, msg in invalid:
            print(f"  - voice_id={rec.get('voice_id')!r}: {msg}", file=sys.stderr)
            print(f"    record: {rec}", file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "voice_registry.yaml"
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"voices": valid},
            f,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    print(f"02_voices: {len(valid)}/{len(records)} record validi → {out_path.relative_to(ROOT)}")
    return 0 if not invalid else 1


if __name__ == "__main__":
    sys.exit(main())
