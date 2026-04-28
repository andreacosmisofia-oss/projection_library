"""Read-only registry endpoints (M1.9 task 2).

Every handler reads from the in-memory :class:`RegistryCache` populated
by the FastAPI lifespan. List endpoints return ``{"count": N, "items":
[...]}``; lookup endpoints return the underlying spec dict and 404 on
miss.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.infrastructure.registry import Registries, get_cache

router = APIRouter(prefix="/api/registry", tags=["registry"])


def _registries() -> Registries:
    return get_cache().get()


def _list(items: list[Any]) -> dict[str, Any]:
    return {"count": len(items), "items": items}


@router.get("/voices")
def list_voices() -> dict[str, Any]:
    return _list(list(_registries().voices.values()))


@router.get("/voices/{voice_id:path}")
def get_voice(voice_id: str) -> dict[str, Any]:
    voices = _registries().voices
    if voice_id not in voices:
        raise HTTPException(status_code=404, detail=f"voice '{voice_id}' not found")
    return voices[voice_id]


@router.get("/methods")
def list_methods() -> dict[str, Any]:
    return _list(list(_registries().methods.values()))


@router.get("/methods/{method_id}")
def get_method(method_id: str) -> dict[str, Any]:
    methods = _registries().methods
    if method_id not in methods:
        raise HTTPException(
            status_code=404, detail=f"method '{method_id}' not found"
        )
    return methods[method_id]


@router.get("/derived-rules")
def list_derived_rules() -> dict[str, Any]:
    return _list(list(_registries().derived_rules.values()))


@router.get("/kpis")
def list_kpis() -> dict[str, Any]:
    return _list(list(_registries().kpis.values()))


@router.get("/validation-rules")
def list_validation_rules() -> dict[str, Any]:
    return _list(list(_registries().validation_rules.values()))


@router.get("/sector-packs")
def list_sector_packs() -> dict[str, Any]:
    reg = _registries()
    return {
        "count": len(reg.sector_packs),
        "items": list(reg.sector_packs.values()),
        "custom_kpis": reg.sector_custom_kpis,
    }


@router.get("/voice-dependencies")
def list_voice_dependencies() -> dict[str, Any]:
    return _list(list(_registries().voice_dependencies.values()))


@router.get("/override-policy")
def list_override_policy() -> dict[str, Any]:
    return _list(_registries().override_policies)


@router.get("/required-data")
def list_required_data() -> dict[str, Any]:
    return _list(_registries().required_data)


__all__ = ["router"]
