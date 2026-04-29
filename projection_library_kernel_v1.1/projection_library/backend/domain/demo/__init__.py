"""Demo helpers — Milestone M13.

One-click sample-project loader for demos. Until the M4 mapper API and
the M8 assumption-compilation pipeline land, the loader supplies a
hardcoded mapping table for ``tier2_industrial_clean.xlsx`` and runs
the engine with empty assumptions (the executor already supports that
path: ``ModelState.assumptions`` defaults to an empty dict).
"""

from backend.domain.demo.loader import (
    SAMPLE_FILENAME,
    SAMPLE_MAPPINGS,
    DemoLoadResult,
    load_sample_project,
)

__all__ = [
    "DemoLoadResult",
    "SAMPLE_FILENAME",
    "SAMPLE_MAPPINGS",
    "load_sample_project",
]
