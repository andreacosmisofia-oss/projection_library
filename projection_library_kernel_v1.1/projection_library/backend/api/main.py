"""FastAPI application entry-point.

Wires the registry loader (M1.9) into the app's lifespan: a successful
startup means the registries are loaded, validated, and cached; any
inconsistency aborts the boot with an explicit error.

Run locally:
    uvicorn backend.api.main:app --reload
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from backend.api.routes.demo import router as demo_router
from backend.api.routes.drivers import router as drivers_router
from backend.api.routes.exports import router as exports_router
from backend.api.routes.intake import router as intake_router
from backend.api.routes.kpi import router as kpi_router
from backend.api.routes.methods import router as methods_router
from backend.api.routes.overrides import router as overrides_router
from backend.api.routes.projects import router as projects_router
from backend.api.routes.quality import router as quality_router
from backend.api.routes.registry import router as registry_router
from backend.api.routes.snapshots import router as snapshots_router
from backend.api.routes.validation import router as validation_router
from backend.infrastructure.db.database import engine as _db_engine
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
app.include_router(registry_router)
app.include_router(projects_router)
app.include_router(intake_router)
app.include_router(validation_router)
app.include_router(kpi_router)
app.include_router(quality_router)
app.include_router(methods_router)
app.include_router(drivers_router)
app.include_router(snapshots_router)
app.include_router(overrides_router)
app.include_router(demo_router)
app.include_router(exports_router)


# Wall-clock baseline used by /api/health/full.uptime_seconds. Captured
# at module import (i.e. process start) so the metric reflects the
# server lifetime, not the time since the first request.
_BOOT_TIME = time.monotonic()


def _read_alembic_revision() -> str | None:
    """Return the current Alembic revision, or ``None`` if unknown.

    The ``alembic_version`` table only exists if the project has been
    upgraded at least once. We swallow SQLAlchemy errors so the health
    endpoint stays useful on a fresh DB (e.g. the in-memory test
    fixture where the schema is created via ``Base.metadata.create_all``).
    """
    try:
        with _db_engine.connect() as conn:
            from alembic.runtime.migration import MigrationContext

            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    except (SQLAlchemyError, ImportError):
        return None


def _count_db_tables() -> int:
    try:
        return len(inspect(_db_engine).get_table_names())
    except SQLAlchemyError:
        return 0


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


@app.get("/api/health/full", tags=["meta"])
def health_full() -> dict[str, object]:
    """Extended health probe (M13).

    Bundles four signals an operator typically wants in one shot:

    * ``registries`` — same cardinalities as ``/health``, or ``None``
      when the cache is empty (degraded state).
    * ``db.tables`` — number of tables visible to SQLAlchemy.
    * ``db.last_migration`` — current Alembic revision, or ``None``
      when the ``alembic_version`` table is absent.
    * ``uptime_seconds`` — wall-clock seconds since the module loaded.
    """
    cache = get_cache()
    registries: dict[str, int] | None = (
        cache.get().counts() if cache.is_loaded() else None
    )
    return {
        "status": "ok" if registries is not None else "degraded",
        "uptime_seconds": round(time.monotonic() - _BOOT_TIME, 3),
        "registries": registries,
        "db": {
            "tables": _count_db_tables(),
            "last_migration": _read_alembic_revision(),
        },
    }


__all__ = ["app", "RegistryLoadError"]
