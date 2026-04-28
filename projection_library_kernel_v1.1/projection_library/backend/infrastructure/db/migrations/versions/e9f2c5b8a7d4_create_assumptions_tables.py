"""create assumptions and assumption_curve_configs tables

Revision ID: e9f2c5b8a7d4
Revises: b3e1f7a4d6c2
Create Date: 2026-04-28 16:00:00.000000

M8 — assumption compilation (``flows/06_assumption_compilation.md``).

Two tables:

* ``assumptions`` stores one row per ``(project, voice, method,
  assumption_name, year)`` where ``year ∈ {Y1, Y2, Y3}``. Per-year
  rather than per-(voice, name) because the UI edits one cell at a
  time and ``source`` (default_kpi / user_input / fallback) is tracked
  per cell.
* ``assumption_curve_configs`` carries the curve shape (flat /
  linear_drift / custom) at the ``(voice, method, assumption_name)``
  grain — the audit M1.0 §12 puts it above the per-year layer, and
  including ``method_id`` in the unique key keeps the row scoped to
  the active method choice (a method swap clears the curve, populate-
  defaults rebuilds).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f2c5b8a7d4"
down_revision: Union[str, Sequence[str], None] = "b3e1f7a4d6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assumptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("method_id", sa.String(length=64), nullable=False),
        sa.Column("assumption_name", sa.String(length=128), nullable=False),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("default_kpi_id", sa.String(length=255), nullable=True),
        sa.Column("calibration_score", sa.Float(), nullable=True),
        sa.Column("validation_range_min", sa.Float(), nullable=True),
        sa.Column("validation_range_max", sa.Float(), nullable=True),
        sa.Column(
            "parameterized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("user_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("assumption_name", sa.String(length=128), nullable=False),
        sa.Column("curve_type", sa.String(length=32), nullable=False),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=False),
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
