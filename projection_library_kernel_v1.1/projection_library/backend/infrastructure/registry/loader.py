"""Registry loader (Milestone M1.9).

Loads every YAML registry under ``registries/`` into memory at FastAPI
startup, validates each one against its JSON Schema in
``data_contracts/registries/``, runs cross-reference and DAG checks, and
fails with an aggregated, explicit error if anything is incoherent.

Design notes
------------
* The loader is the single source of truth for registry data; after a
  successful load the result is cached via
  :class:`backend.infrastructure.registry.cache.RegistryCache`.
* Validation is layered: structural (JSON Schema) → referential
  (cross-registry id resolution) → topological (DAG of voice
  dependencies). Each layer is fully evaluated so the operator sees
  every issue in one shot rather than chasing them one by one.
* Errors are aggregated in :class:`RegistryLoadError`; raising it short-
  circuits FastAPI startup, which is the contract M1.9 acceptance asks
  for.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

import yaml
from jsonschema import Draft202012Validator

from backend.domain.intake.synonyms import SynonymIndex, build_synonym_index
from backend.infrastructure.registry.cache import RegistryCache, get_cache

if TYPE_CHECKING:
    from fastapi import FastAPI


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryLoadError(RuntimeError):
    """Raised when the registry layer cannot be loaded coherently.

    The exception groups every detected issue (schema, cross-reference,
    DAG) so a single FastAPI startup failure surfaces the full picture.
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors: list[str] = list(errors or [])
        if self.errors:
            detail = "\n  - " + "\n  - ".join(self.errors)
            super().__init__(f"{message}{detail}")
        else:
            super().__init__(message)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryPaths:
    """Filesystem locations of the registry artefacts."""

    registries_dir: Path
    schemas_dir: Path
    sector_packs_dir: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "RegistryPaths":
        registries_dir = repo_root / "registries"
        return cls(
            registries_dir=registries_dir,
            schemas_dir=repo_root / "data_contracts" / "registries",
            sector_packs_dir=registries_dir / "sector_packs",
        )

    @classmethod
    def from_env(cls) -> "RegistryPaths":
        """Resolve paths from ``REGISTRY_REPO_ROOT`` env var or sensible default.

        The default walks up from this file: ``backend/infrastructure/registry``
        is three levels deep, so the repo root is ``parents[3]``.
        """
        env_root = os.environ.get("REGISTRY_REPO_ROOT")
        if env_root:
            return cls.from_repo_root(Path(env_root).resolve())
        return cls.from_repo_root(Path(__file__).resolve().parents[3])


# ---------------------------------------------------------------------------
# Registry data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Registries:
    """In-memory snapshot of every registry artefact."""

    voices: dict[str, dict[str, Any]]
    methods: dict[str, dict[str, Any]]
    methods_by_tech_code: dict[str, str]
    derived_rules: dict[str, dict[str, Any]]
    derived_rules_by_tech_code: dict[str, str]
    kpis: dict[str, dict[str, Any]]
    validation_rules: dict[str, dict[str, Any]]
    validation_rules_by_phase: dict[str, list[dict[str, Any]]]
    sector_packs: dict[str, dict[str, Any]]
    sector_custom_kpis: list[dict[str, Any]]
    voice_dependencies: dict[str, dict[str, Any]]
    override_policies: list[dict[str, Any]]
    required_data: list[dict[str, Any]]
    synonyms: SynonymIndex = field(default_factory=SynonymIndex)

    def counts(self) -> dict[str, int]:
        """Cardinalities of the loaded artefacts (debug / health output)."""
        return {
            "voices": len(self.voices),
            "methods": len(self.methods),
            "derived_rules": len(self.derived_rules),
            "kpis": len(self.kpis),
            "validation_rules": len(self.validation_rules),
            "sector_packs": len(self.sector_packs),
            "sector_custom_kpis": len(self.sector_custom_kpis),
            "voice_dependencies": len(self.voice_dependencies),
            "override_policies": len(self.override_policies),
            "required_data": len(self.required_data),
            "synonym_voices": self.synonyms.voice_count(),
            "synonym_strings": self.synonyms.synonym_count(),
        }


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise RegistryLoadError(f"Missing registry file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise RegistryLoadError(f"Invalid YAML in {path}: {exc}") from exc


def _read_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RegistryLoadError(f"Missing JSON Schema file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise RegistryLoadError(f"Invalid JSON Schema in {path}: {exc}") from exc


def _validate_schema(
    data: Any, schema: dict[str, Any], source: str
) -> list[str]:
    """Return a list of human-readable schema violation messages."""
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(
        validator.iter_errors(data), key=lambda e: list(e.absolute_path)
    ):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"[schema] {source} :: {loc}: {err.message}")
    return errors


def _index_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    """Index a list of dicts by a unique key, raising on duplicates."""
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        k = item[key]
        if k in out:
            raise RegistryLoadError(
                f"Duplicate '{key}'='{k}' in registry list"
            )
        out[k] = item
    return out


# ---------------------------------------------------------------------------
# Sector pack aggregation
# ---------------------------------------------------------------------------


def _load_sector_packs_aggregated(packs_dir: Path) -> dict[str, Any]:
    """Aggregate ``sector_packs/<sector>.yaml`` into the schema-required shape.

    Each per-sector file is ``{pack: {...}, custom_kpis: [...]}``; the
    schema (sector_pack.schema.json) expects a single document with
    ``packs: [...]`` + ``custom_kpis: [...]`` arrays.
    """
    if not packs_dir.exists() or not packs_dir.is_dir():
        raise RegistryLoadError(f"Missing sector_packs directory: {packs_dir}")

    aggregated_packs: list[dict[str, Any]] = []
    aggregated_kpis: list[dict[str, Any]] = []
    for path in sorted(packs_dir.glob("*.yaml")):
        doc = _read_yaml(path)
        if not isinstance(doc, dict):
            raise RegistryLoadError(
                f"Sector pack {path.name}: top-level must be a mapping"
            )
        pack = doc.get("pack")
        if not isinstance(pack, dict):
            raise RegistryLoadError(
                f"Sector pack {path.name}: missing 'pack' mapping"
            )
        aggregated_packs.append(pack)
        for kpi in doc.get("custom_kpis", []) or []:
            aggregated_kpis.append(kpi)
    return {"packs": aggregated_packs, "custom_kpis": aggregated_kpis}


# ---------------------------------------------------------------------------
# Cross-reference checks
# ---------------------------------------------------------------------------


_SENTINEL_NULL = {"—", "-", ""}

# Sentinel values declaring "the user must choose at runtime" rather than
# pointing at a registry id. Treated as resolved for cross-reference
# purposes (the runtime selector enforces a real choice later).
_USER_CHOICE_SENTINELS = {"(utente sceglie)", "(user choice)"}


def _is_meaningful(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or value not in _SENTINEL_NULL)


def _check_cross_references(reg: Registries) -> list[str]:
    errors: list[str] = []
    voice_ids = set(reg.voices.keys())
    method_ids = set(reg.methods.keys())
    method_tech_codes = set(reg.methods_by_tech_code.keys())
    derived_ids = set(reg.derived_rules.keys())
    derived_tech_codes = set(reg.derived_rules_by_tech_code.keys())

    # voice.default_method → method.method_id OR derived_rule.derived_rule_id.
    # Derived voices (e.g. pl.gross_profit, pl.da.ppe) legitimately have a
    # derived_rule as their default projection logic; the executor dispatches
    # accordingly. Sentinels like "(utente sceglie)" are deferred to runtime
    # selection.
    for vid, voice in reg.voices.items():
        dm = voice.get("default_method")
        if not _is_meaningful(dm):
            continue
        if dm in _USER_CHOICE_SENTINELS:
            continue
        if dm not in method_ids and dm not in derived_ids:
            errors.append(
                f"[xref] voice_registry: voice '{vid}' default_method='{dm}' "
                f"is neither a known method_id nor a known derived_rule_id"
            )

    # method.fallback → method.method_id
    for mid, method in reg.methods.items():
        fb = method.get("fallback")
        if _is_meaningful(fb) and fb not in method_ids:
            errors.append(
                f"[xref] method_registry: method '{mid}' fallback='{fb}' is "
                f"not a known method_id"
            )

    # voice_dependencies.voice_id must exist in voice_registry
    for vid in reg.voice_dependencies:
        if vid not in voice_ids:
            errors.append(
                f"[xref] voice_dependencies: '{vid}' is not in voice_registry"
            )

    # voice_dependencies.depends_on_voices must resolve
    for vid, dep in reg.voice_dependencies.items():
        for target in dep.get("depends_on_voices", []) or []:
            if not isinstance(target, str):
                errors.append(
                    f"[xref] voice_dependencies '{vid}' depends_on_voices: "
                    f"non-string entry {target!r}"
                )
                continue
            # Templated refs (e.g. 'driver.{voice}.volume') are deferred to
            # runtime resolution; allow them through.
            if "{" in target and "}" in target:
                continue
            if target not in voice_ids:
                errors.append(
                    f"[xref] voice_dependencies '{vid}' depends_on_voices: "
                    f"unknown voice '{target}'"
                )

    # voice_dependencies.formula_rule_id → derived_rules (id or tech_code)
    for vid, dep in reg.voice_dependencies.items():
        rule = dep.get("formula_rule_id")
        if rule is None:
            continue
        if (
            rule not in derived_ids
            and rule not in derived_tech_codes
            and rule not in method_ids
            and rule not in method_tech_codes
        ):
            errors.append(
                f"[xref] voice_dependencies '{vid}' formula_rule_id "
                f"'{rule}' is not in derived_rules nor in method_registry"
            )

    # override_policy.applies_to_voices_pattern: every policy must match >=1 voice
    for policy in reg.override_policies:
        patterns = policy.get("applies_to_voices_pattern")
        if patterns is None:
            continue
        if isinstance(patterns, str):
            patterns_list = [patterns]
        elif isinstance(patterns, list):
            patterns_list = [p for p in patterns if isinstance(p, str)]
        else:
            errors.append(
                f"[xref] override_policy '{policy.get('policy_class')}': "
                f"applies_to_voices_pattern must be string or list"
            )
            continue
        for pat in patterns_list:
            if not any(fnmatch.fnmatchcase(v, pat) for v in voice_ids):
                errors.append(
                    f"[xref] override_policy '{policy.get('policy_class')}': "
                    f"pattern '{pat}' matches no voice"
                )

    # override_policy.exclude_voices: every entry must exist (literal voice_id)
    for policy in reg.override_policies:
        for excluded in policy.get("exclude_voices", []) or []:
            if not isinstance(excluded, str):
                continue
            # Exclusions can be exact ids; tolerate glob-style too.
            if any(ch in excluded for ch in "*?["):
                if not any(fnmatch.fnmatchcase(v, excluded) for v in voice_ids):
                    errors.append(
                        f"[xref] override_policy "
                        f"'{policy.get('policy_class')}': exclude_voices "
                        f"pattern '{excluded}' matches no voice"
                    )
            elif excluded not in voice_ids:
                errors.append(
                    f"[xref] override_policy '{policy.get('policy_class')}': "
                    f"exclude_voices '{excluded}' is not a known voice"
                )

    # required_data: voice_id and method_id, where present, must exist
    for entry in reg.required_data:
        vid = entry.get("voice_id")
        if _is_meaningful(vid) and vid not in voice_ids:
            errors.append(
                f"[xref] required_data '{entry.get('required_data_id')}': "
                f"voice_id '{vid}' is not a known voice"
            )
        mid = entry.get("method_id")
        if not _is_meaningful(mid) or mid in _USER_CHOICE_SENTINELS:
            continue
        if mid not in method_ids and mid not in derived_ids:
            errors.append(
                f"[xref] required_data '{entry.get('required_data_id')}': "
                f"method_id '{mid}' is neither a known method nor "
                f"derived_rule"
            )

    # sector_packs.custom_kpis: kpi_id must be unique within the pack
    seen: set[tuple[str, str]] = set()
    for kpi in reg.sector_custom_kpis:
        key = (kpi.get("pack", ""), kpi.get("kpi_id", ""))
        if key in seen:
            errors.append(
                f"[xref] sector_packs custom_kpis: duplicate "
                f"(pack='{key[0]}', kpi_id='{key[1]}')"
            )
        seen.add(key)

    return errors


# ---------------------------------------------------------------------------
# DAG check on voice_dependencies
# ---------------------------------------------------------------------------


def _detect_cycles(
    deps: dict[str, dict[str, Any]],
    voices: set[str],
) -> list[list[str]]:
    """Return all simple cycles found in the voice dependency graph.

    Templated and unknown ids are ignored (cross-reference layer flags
    them separately); only edges between known voices participate in the
    DAG check.
    """
    graph: dict[str, list[str]] = {v: [] for v in voices}
    for vid, dep in deps.items():
        if vid not in graph:
            continue
        for target in dep.get("depends_on_voices", []) or []:
            if isinstance(target, str) and target in graph:
                graph[vid].append(target)

    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {v: WHITE for v in graph}
    stack: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == GRAY:
                idx = stack.index(nxt)
                cycle = stack[idx:] + [nxt]
                key = tuple(sorted(cycle[:-1]))
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(cycle)
            elif color[nxt] == WHITE:
                dfs(nxt)
        stack.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)
    return cycles


def _check_dag(
    reg: Registries,
    known_cycles: frozenset[frozenset[str]] = frozenset(),
) -> list[str]:
    cycles = _detect_cycles(reg.voice_dependencies, set(reg.voices.keys()))
    errors: list[str] = []
    for cycle in cycles:
        members = frozenset(cycle[:-1])
        if members in known_cycles:
            logger.info(
                "registry: skipping known voice_dependency cycle %s",
                " -> ".join(cycle),
            )
            continue
        errors.append(
            "[dag] voice_dependencies cycle detected: " + " -> ".join(cycle)
        )
    return errors


# ---------------------------------------------------------------------------
# Top-level loader
# ---------------------------------------------------------------------------


# Filename → (top-level YAML key, schema filename, schema-doc top-level key)
_REGISTRY_FILES: dict[str, tuple[str, str]] = {
    "voice_registry.yaml": ("voices", "voice_registry.schema.json"),
    "method_registry.yaml": ("methods", "method_registry.schema.json"),
    "kpi_registry.yaml": ("kpis", "kpi_registry.schema.json"),
    "validation_rules.yaml": ("validation_rules", "validation_rule.schema.json"),
}


def load_registries(
    paths: RegistryPaths | None = None,
    *,
    known_cycles: frozenset[frozenset[str]] = frozenset(),
) -> Registries:
    """Load every registry, validate it, and return an immutable snapshot.

    Raises
    ------
    RegistryLoadError
        If any YAML is missing, any document fails JSON Schema validation,
        any cross-registry reference is unresolved, or
        ``voice_dependencies`` is not a DAG (modulo ``known_cycles``).
    """
    paths = paths or RegistryPaths.from_env()
    schema_errors: list[str] = []

    # Schemas
    schemas: dict[str, dict[str, Any]] = {}
    for _, schema_name in _REGISTRY_FILES.values():
        schemas[schema_name] = _read_schema(paths.schemas_dir / schema_name)
    schemas["sector_pack.schema.json"] = _read_schema(
        paths.schemas_dir / "sector_pack.schema.json"
    )

    # Standalone registries
    docs: dict[str, Any] = {}
    for filename, (_, schema_name) in _REGISTRY_FILES.items():
        doc = _read_yaml(paths.registries_dir / filename)
        schema_errors.extend(_validate_schema(doc, schemas[schema_name], filename))
        docs[filename] = doc

    # Sector packs (aggregated from sector_packs/*.yaml)
    sector_doc = _load_sector_packs_aggregated(paths.sector_packs_dir)
    schema_errors.extend(
        _validate_schema(
            sector_doc, schemas["sector_pack.schema.json"], "sector_packs/*.yaml"
        )
    )

    # YAMLs without JSON Schema yet (M1.4/M1.5/M1.6) — load + light shape check.
    deps_doc = _read_yaml(paths.registries_dir / "voice_dependencies.yaml")
    if not isinstance(deps_doc, dict) or not isinstance(deps_doc.get("voices"), list):
        schema_errors.append(
            "[shape] voice_dependencies.yaml: top-level must be {voices: [...]}"
        )

    override_doc = _read_yaml(paths.registries_dir / "override_policy.yaml")
    if not isinstance(override_doc, dict) or not isinstance(
        override_doc.get("policies"), list
    ):
        schema_errors.append(
            "[shape] override_policy.yaml: top-level must be {policies: [...]}"
        )

    required_doc = _read_yaml(paths.registries_dir / "required_data_matrix.yaml")
    if not isinstance(required_doc, dict) or not isinstance(
        required_doc.get("required_data"), list
    ):
        schema_errors.append(
            "[shape] required_data_matrix.yaml: top-level must be "
            "{required_data: [...]}"
        )

    if schema_errors:
        raise RegistryLoadError(
            f"Registry schema validation failed ({len(schema_errors)} issue(s))",
            schema_errors,
        )

    # Build indexed views
    try:
        voices = _index_by(docs["voice_registry.yaml"]["voices"], "voice_id")
        methods = _index_by(docs["method_registry.yaml"]["methods"], "method_id")
        derived_rules = _index_by(
            docs["method_registry.yaml"]["derived_rules"], "derived_rule_id"
        )
        kpis = _index_by(docs["kpi_registry.yaml"]["kpis"], "kpi_id")
        validation_rules = _index_by(
            docs["validation_rules.yaml"]["validation_rules"], "rule_id"
        )
        sector_packs = _index_by(sector_doc["packs"], "sector_pack")
        voice_dependencies = _index_by(deps_doc["voices"], "voice_id")
    except RegistryLoadError:
        raise
    except KeyError as exc:
        raise RegistryLoadError(f"Missing expected key while indexing: {exc}") from exc

    methods_by_tech_code = {m["tech_code"]: mid for mid, m in methods.items()}
    derived_rules_by_tech_code = {
        r["tech_code"]: rid for rid, r in derived_rules.items()
    }

    rules_by_phase: dict[str, list[dict[str, Any]]] = {}
    for rule in validation_rules.values():
        for phase in rule.get("trigger_phases", []) or []:
            rules_by_phase.setdefault(phase, []).append(rule)

    # Synonyms (M4). Loaded after the voice index so we can xref every
    # voice_id appearing in voice_synonyms.yaml against the registry.
    synonyms_path = paths.registries_dir / "voice_synonyms.yaml"
    if synonyms_path.exists():
        try:
            synonyms = build_synonym_index(synonyms_path)
        except Exception as exc:  # pragma: no cover - defensive
            raise RegistryLoadError(
                f"voice_synonyms.yaml: failed to build index ({exc})"
            ) from exc
    else:
        synonyms = SynonymIndex()

    reg = Registries(
        voices=voices,
        methods=methods,
        methods_by_tech_code=methods_by_tech_code,
        derived_rules=derived_rules,
        derived_rules_by_tech_code=derived_rules_by_tech_code,
        kpis=kpis,
        validation_rules=validation_rules,
        validation_rules_by_phase=rules_by_phase,
        sector_packs=sector_packs,
        sector_custom_kpis=list(sector_doc.get("custom_kpis") or []),
        voice_dependencies=voice_dependencies,
        override_policies=list(override_doc.get("policies") or []),
        required_data=list(required_doc.get("required_data") or []),
        synonyms=synonyms,
    )

    # Referential + topological checks (run together so the operator sees both)
    semantic_errors: list[str] = []
    semantic_errors.extend(_check_cross_references(reg))
    semantic_errors.extend(_check_dag(reg, known_cycles=known_cycles))

    # Synonym xref: every voice_id mentioned in voice_synonyms must exist in
    # voice_registry. Caught here so the operator sees one consolidated
    # error log on startup.
    for voice_id in reg.synonyms.by_voice:
        if voice_id not in reg.voices:
            semantic_errors.append(
                f"[xref] voice_synonyms.yaml: voice_id '{voice_id}' is not "
                f"in voice_registry"
            )

    if semantic_errors:
        raise RegistryLoadError(
            f"Registry consistency checks failed "
            f"({len(semantic_errors)} issue(s))",
            semantic_errors,
        )

    logger.info("registry: loaded %s", reg.counts())
    return reg


# ---------------------------------------------------------------------------
# FastAPI lifespan integration
# ---------------------------------------------------------------------------


def register_lifespan(
    app: "FastAPI",
    *,
    paths: RegistryPaths | None = None,
    cache: RegistryCache | None = None,
    known_cycles: frozenset[frozenset[str]] = frozenset(),
) -> None:
    """Attach a lifespan handler that loads the registries on startup.

    The handler runs ``load_registries`` synchronously inside the async
    context: a failure raises :class:`RegistryLoadError` and aborts
    startup, which is the M1.9 acceptance contract.
    """
    target_cache = cache or get_cache()

    @asynccontextmanager
    async def _lifespan(_app: "FastAPI") -> AsyncIterator[None]:
        registries = load_registries(paths, known_cycles=known_cycles)
        target_cache.set(registries)
        try:
            yield
        finally:
            target_cache.clear()

    # Attach to the FastAPI app. ``router.lifespan_context`` is the
    # supported hook for programmatic registration.
    app.router.lifespan_context = _lifespan


__all__ = [
    "Registries",
    "RegistryLoadError",
    "RegistryPaths",
    "load_registries",
    "register_lifespan",
]
