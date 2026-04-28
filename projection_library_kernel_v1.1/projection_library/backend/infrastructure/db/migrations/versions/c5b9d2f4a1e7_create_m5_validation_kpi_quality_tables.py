"""create M5 validation/kpi/quality tables

Revision ID: c5b9d2f4a1e7
Revises: 8a4f1c2d9e3b
Create Date: 2026-04-28 10:00:00.000000

M5 — historical validation + KPI calc + quality score. Adds:
- ``mappings`` (read by M5; M4 will populate)
- ``historical_kpis`` (per-year + AGG aggregate row)
- ``quality_scores`` (one active row per project)
- ``validation_reports`` (one row per project+phase)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5b9d2f4a1e7"
down_revision: Union[str, Sequence[str], None] = "8a4f1c2d9e3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_user_label", sa.String(length=255), nullable=False),
        sa.Column("voice_user_section", sa.String(length=32), nullable=True),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mappings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_mappings_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_mappings_voice_id"), ["voice_id"], unique=False
        )
        batch_op.create_index(
            "ix_mappings_project_label_section",
            ["project_id", "voice_user_label", "voice_user_section"],
            unique=True,
        )

    op.create_table(
        "historical_kpis",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("kpi_id", sa.String(length=128), nullable=False),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("not_computable_reason", sa.String(length=64), nullable=True),
        sa.Column("default_for_projection", sa.Float(), nullable=True),
        sa.Column("calibration_score", sa.Float(), nullable=True),
        sa.Column("lfl_warning", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("historical_kpis", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_historical_kpis_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_historical_kpis_project_kpi_year",
            ["project_id", "kpi_id", "year"],
            unique=True,
        )

    op.create_table(
        "quality_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("score_total", sa.Float(), nullable=False),
        sa.Column("score_history", sa.Float(), nullable=False),
        sa.Column("score_completeness", sa.Float(), nullable=False),
        sa.Column("score_consistency", sa.Float(), nullable=False),
        sa.Column("score_method_calibration", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("components_detail", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quality_scores", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_quality_scores_project_id"),
            ["project_id"],
            unique=True,
        )

    op.create_table(
        "validation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("can_proceed", sa.Boolean(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("validation_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_validation_reports_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_validation_reports_project_phase",
            ["project_id", "phase"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("validation_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_validation_reports_project_phase")
        batch_op.drop_index(batch_op.f("ix_validation_reports_project_id"))
    op.drop_table("validation_reports")

    with op.batch_alter_table("quality_scores", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quality_scores_project_id"))
    op.drop_table("quality_scores")

    with op.batch_alter_table("historical_kpis", schema=None) as batch_op:
        batch_op.drop_index("ix_historical_kpis_project_kpi_year")
        batch_op.drop_index(batch_op.f("ix_historical_kpis_project_id"))
    op.drop_table("historical_kpis")

    with op.batch_alter_table("mappings", schema=None) as batch_op:
        batch_op.drop_index("ix_mappings_project_label_section")
        batch_op.drop_index(batch_op.f("ix_mappings_voice_id"))
        batch_op.drop_index(batch_op.f("ix_mappings_project_id"))
    op.drop_table("mappings")
