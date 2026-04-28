"""In-memory registry cache.

Holds the immutable Registries instance produced by the loader, so the
domain and API layers can fetch it without re-reading YAML.
"""

from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.infrastructure.registry.loader import Registries


class RegistryCache:
    """Thread-safe holder for the loaded Registries.

    Single source of truth for registry data once the FastAPI app has
    completed its startup lifecycle.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._registries: Optional["Registries"] = None

    def set(self, registries: "Registries") -> None:
        with self._lock:
            self._registries = registries

    def get(self) -> "Registries":
        with self._lock:
            if self._registries is None:
                raise RuntimeError(
                    "Registry cache is empty. The FastAPI lifespan startup "
                    "must run load_registries() before any handler reads it."
                )
            return self._registries

    def clear(self) -> None:
        with self._lock:
            self._registries = None

    def is_loaded(self) -> bool:
        with self._lock:
            return self._registries is not None


_cache = RegistryCache()


def get_cache() -> RegistryCache:
    """Return the process-wide registry cache."""
    return _cache
