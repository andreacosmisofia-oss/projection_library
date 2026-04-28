"""Synonym index for the M4 mapper.

Loads ``registries/voice_synonyms.yaml`` and exposes O(1) lookup from
a normalized human label to a canonical ``voice_id``. The index is
the backbone of strategy B (synonym-match → confidence 0.95) in
:mod:`backend.domain.intake.mapper`.

Construction is cheap (a few thousand dict inserts) so we don't cache
across requests; build it once at app startup, or on-demand inside a
test fixture.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from backend.domain.intake.normalize import normalize_text

logger = logging.getLogger(__name__)


def _default_synonyms_path() -> Path:
    """Resolve the production ``voice_synonyms.yaml`` location.

    Honours ``REGISTRY_REPO_ROOT`` for the same reasons the registry
    loader does (test harnesses can point at a fixture root).
    """
    env_root = os.environ.get("REGISTRY_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve() / "registries" / "voice_synonyms.yaml"
    # backend/domain/intake/synonyms.py is three levels deep under repo root.
    return (
        Path(__file__).resolve().parents[3]
        / "registries"
        / "voice_synonyms.yaml"
    )


@dataclass(frozen=True)
class SynonymIndex:
    """Bidirectional view of the synonym table.

    ``by_synonym`` answers "which voice does this label belong to?" in
    O(1); ``by_voice`` answers "what synonyms do we know for this
    voice?" so the fuzzy strategy can build its candidate set from the
    same source of truth as the exact-match strategy.
    """

    by_synonym: dict[str, str] = field(default_factory=dict)
    by_voice: dict[str, list[str]] = field(default_factory=dict)

    def lookup(self, text: str | None) -> str | None:
        """Return the matching ``voice_id`` for ``text``, or ``None``.

        The lookup normalises the input the same way authoring time
        normalises every synonym, so callers don't need to pre-process.
        """
        key = normalize_text(text)
        if not key:
            return None
        return self.by_synonym.get(key)

    def synonyms_for(self, voice_id: str) -> list[str]:
        return list(self.by_voice.get(voice_id, ()))

    def all_synonyms(self) -> Iterable[tuple[str, str]]:
        """Yield ``(normalized_synonym, voice_id)`` pairs."""
        return self.by_synonym.items()

    def voice_count(self) -> int:
        return len(self.by_voice)

    def synonym_count(self) -> int:
        return len(self.by_synonym)


def build_synonym_index(path: Path | None = None) -> SynonymIndex:
    """Parse the YAML and return a frozen :class:`SynonymIndex`.

    Duplicate normalized synonyms across different voices are logged at
    WARNING and the **first** voice wins — silently overwriting would
    let typos propagate into mis-mappings. The index is still returned
    so the loader doesn't refuse to start; the warning is the signal
    to clean up the YAML.
    """
    target = path or _default_synonyms_path()
    if not target.exists():
        raise FileNotFoundError(f"voice_synonyms.yaml not found at {target}")
    with target.open("r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)

    if not isinstance(doc, dict) or not isinstance(
        doc.get("voice_synonyms"), list
    ):
        raise ValueError(
            f"{target.name}: top-level must be a mapping with "
            f"'voice_synonyms: [...]'"
        )

    by_synonym: dict[str, str] = {}
    by_voice: dict[str, list[str]] = {}

    for entry in doc["voice_synonyms"]:
        voice_id = entry.get("voice_id")
        if not isinstance(voice_id, str) or not voice_id:
            raise ValueError(f"{target.name}: missing or invalid voice_id")
        synonyms = (entry.get("synonyms_it") or []) + (
            entry.get("synonyms_en") or []
        )
        normalized: list[str] = []
        for raw in synonyms:
            if not isinstance(raw, str):
                continue
            key = normalize_text(raw)
            if not key:
                continue
            existing = by_synonym.get(key)
            if existing is not None and existing != voice_id:
                logger.warning(
                    "voice_synonyms: duplicate synonym %r across "
                    "%r and %r; keeping the first",
                    raw,
                    existing,
                    voice_id,
                )
                continue
            by_synonym[key] = voice_id
            normalized.append(key)
        if normalized:
            by_voice.setdefault(voice_id, []).extend(normalized)

    return SynonymIndex(by_synonym=by_synonym, by_voice=by_voice)


__all__ = ["SynonymIndex", "build_synonym_index"]
