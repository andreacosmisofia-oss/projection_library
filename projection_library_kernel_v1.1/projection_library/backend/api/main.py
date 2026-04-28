"""FastAPI application entry-point.

Wires the registry loader (M1.9) into the app's lifespan: a successful
startup means the registries are loaded, validated, and cached; any
inconsistency aborts the boot with an explicit error.

Run locally:
    uvicorn backend.api.main:app --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from backend.infrastructure.registry import (
    RegistryLoadError,
    get_cache,
    register_lifespan,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)

app = FastAPI(
    title="Projection Library API",
    version="1.1.0-pilot",
    description=(
        "Backend API for the Projection Library pilot. Registries are "
        "loaded and validated at startup; the app refuses to boot on "
        "schema, cross-reference, or DAG inconsistencies."
    ),
)

register_lifespan(app)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness + registry-load probe.

    Returns ``status=ok`` and the cardinalities of the loaded registries
    once the lifespan startup has completed. If the cache is empty (the
    lifespan failed or hasn't run yet) the response surfaces a degraded
    status so an operator can spot it.
    """
    cache = get_cache()
    if not cache.is_loaded():
        return {"status": "degraded", "registries_loaded": False}
    return {
        "status": "ok",
        "registries_loaded": True,
        "registries": cache.get().counts(),
    }


__all__ = ["app", "RegistryLoadError"]
