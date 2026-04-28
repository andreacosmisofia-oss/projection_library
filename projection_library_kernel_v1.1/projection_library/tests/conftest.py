"""pytest config: ensure the project root is on sys.path so ``import
backend...`` resolves regardless of the directory pytest is invoked
from.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(scope="session")
def loaded_registries():
    """Load the real registries once per test session (M5 unit tests)."""
    from backend.infrastructure.registry import load_registries

    return load_registries()
