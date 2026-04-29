"""create assumptions tables

Revision ID: a4d8e3c1b6f5
Revises: f1a3b8d6c4e2
Create Date: 2026-04-29 12:00:00.000000

M8 — assumption compilation (``flows/06_assumption_compilation.md``).
Two tables:

* ``assumptions`` — per-year forward parameter (Y1/Y2/Y3) keyed on
  ``(project_id, voice_id, method_id, assumption_name, year)``;
* ``assumption_curve_configs`` — curve shape (flat / linear_drift /
  custom) keyed on the same tuple minus the year.

Runtime fields (calibration_score, validation_status) are derived at
read time and intentionally not persisted (registry audit §12).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4d8e3c1b6f5"
down_revision: Union[str, Sequence[str], None] = "f1a3b8d6c4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assumptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("method_id", sa.String(length=64), nullable=False),
        sa.Column("assumption_name", sa.String(length=64), nullable=False),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("default_kpi_id", sa.String(length=128), nullable=True),
        sa.Column("validation_range", sa.JSON(), nullable=True),
        sa.Column(
            "user_modified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "year IN ('Y1', 'Y2', 'Y3')", name="ck_assumptions_year"
        ),
        sa.CheckConstraint(
            "source IN ('default_kpi', 'user_input', 'fallback')",
            name="ck_assumptions_source",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("assumptions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assumptions_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_assumptions_project_voice_method_name_year",
            ["project_id", "voice_id", "method_id", "assumption_name", "year"],
            unique=True,
        )

    op.create_table(
        "assumption_curve_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("method_id", sa.String(length=64), nullable=False),
        sa.Column("assumption_name", sa.String(length=64), nullable=False),
        sa.Column(
            "curve_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'flat'"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "curve_type IN ('flat', 'linear_drift', 'custom')",
            name="ck_assumption_curve_type",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "assumption_curve_configs", schema=None
    ) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assumption_curve_configs_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_assumption_curves_project_voice_method_name",
            ["project_id", "voice_id", "method_id", "assumption_name"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "assumption_curve_configs", schema=None
    ) as batch_op:
        batch_op.drop_index("ix_assumption_curves_project_voice_method_name")
        batch_op.drop_index(
            batch_op.f("ix_assumption_curve_configs_project_id")
        )
    op.drop_table("assumption_curve_configs")

    with op.batch_alter_table("assumptions", schema=None) as batch_op:
        batch_op.drop_index("ix_assumptions_project_voice_method_name_year")
        batch_op.drop_index(batch_op.f("ix_assumptions_project_id"))
    op.drop_table("assumptions")
