"""M5 — Quality score computation (4 sub-scores + classification)."""

from backend.domain.quality.scorer import (
    QualityScoreResult,
    compute_quality_score,
)

__all__ = ["QualityScoreResult", "compute_quality_score"]
