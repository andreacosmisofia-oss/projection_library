#!/usr/bin/env python3
"""Generate registries/required_data_matrix.yaml from voice/method/override registries."""

from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRIES = ROOT / "registries"

VOICE_REGISTRY = REGISTRIES / "voice_registry.yaml"
METHOD_REGISTRY = REGISTRIES / "method_registry.yaml"
OVERRIDE_POLICY = REGISTRIES / "override_policy.yaml"
OUTPUT = REGISTRIES / "required_data_matrix.yaml"

NATURE_TO_TYPE = {
    "driver": "actual_voice",
    "driver_placeholder": "driver",
    "driver_slot": "driver",
}


def infer_tier(voice_id: str) -> str:
    if voice_id.startswith("pl.rev.") or voice_id.startswith("pl.cogs."):
        return "TIER_1"
    if voice_id.startswith("bs.provisions.") or voice_id.startswith("bs.employee_benefits."):
        return "TIER_3"
    if (
        voice_id.startswith("pl.opex.")
        or voice_id.startswith("bs.nwc.")
        or voice_id.startswith("bs.fa.")
        or voice_id.startswith("bs.nfp.")
    ):
        return "TIER_2"
    return "TIER_2"


def derive_record(voice: dict) -> dict | None:
    nature = voice.get("nature")
    if nature not in NATURE_TO_TYPE:
        return None

    voice_id = voice["voice_id"]
    record_type = NATURE_TO_TYPE[nature]
    method_id = voice.get("default_method")
    tier = voice.get("is_required_by_tier") or infer_tier(voice_id)
    sector_scope = voice.get("sector_scope", "all")

    if record_type == "actual_voice":
        if method_id and method_id != "(utente sceglie)":
            required_if = f"method_id == '{method_id}'"
        else:
            required_if = "always"
        default_policy = "fallback_to_default"
    else:
        required_if = "always" if sector_scope == "all" else f"sector == '{sector_scope}'"
        default_policy = "skip_if_missing"

    return {
        "required_data_id": f"{voice_id}_{tier}",
        "type": record_type,
        "voice_id": voice_id,
        "method_id": method_id,
        "tier": tier,
        "sector_scope": sector_scope,
        "required_if": required_if,
        "default_policy": default_policy,
    }


def main() -> None:
    with VOICE_REGISTRY.open() as f:
        voice_data = yaml.safe_load(f)
    # Load to validate referenced files exist (no functional dependency in derivation).
    with METHOD_REGISTRY.open() as f:
        yaml.safe_load(f)
    with OVERRIDE_POLICY.open() as f:
        yaml.safe_load(f)

    records = []
    for voice in voice_data["voices"]:
        rec = derive_record(voice)
        if rec is not None:
            records.append(rec)

    with OUTPUT.open("w") as f:
        yaml.safe_dump(
            {"required_data": records},
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )

    tier_counts = Counter(r["tier"] for r in records)
    type_counts = Counter(r["type"] for r in records)

    print(f"Generated {len(records)} required_data records → {OUTPUT.relative_to(ROOT)}")
    print("\nCount per tier:")
    for tier in sorted(tier_counts):
        print(f"  {tier}: {tier_counts[tier]}")
    print("\nCount per type:")
    for t in sorted(type_counts):
        print(f"  {t}: {type_counts[t]}")


if __name__ == "__main__":
    main()
