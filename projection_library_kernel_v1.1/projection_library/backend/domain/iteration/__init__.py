"""M12 — Iteration paths cascade (``flows/09_iteration.md``).

Path 9.3 (historical data modify) and Path 9.2 (method change) require
re-running a fixed sequence of upstream computations. The cascade
helpers here keep that orchestration in one place so the route layer
stays thin and the same logic is testable without HTTP.
"""

from backend.domain.iteration.cascade import (
    IterationResult,
    iterate_historical_modify,
    iterate_method_change,
)

__all__ = [
    "IterationResult",
    "iterate_historical_modify",
    "iterate_method_change",
]
