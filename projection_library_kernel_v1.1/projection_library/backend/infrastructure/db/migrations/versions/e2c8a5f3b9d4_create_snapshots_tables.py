"""create snapshots and snapshot_values tables

Revision ID: e2c8a5f3b9d4
Revises: b3e1f7a4d6c2
Create Date: 2026-04-28 16:00:00.000000

M10 — output dashboard MVP backend (``flows/08_output_presentation.md``).
``snapshots`` is the engine run header (one row per ``POST /run``);
``snapshot_values`` carries the normalised per-voice/per-year numbers
the dashboard reads. History is preserved (no upsert): ``GET
/snapshot/latest`` selects by ``created_at DESC``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2c8a5f3b9d4"
down_revision: Union[str, Sequence[str], None] = "b3e1f7a4d6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("validation_summary", sa.JSON(), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("approximation_log", sa.JSON(), nullable=False),
        sa.Column("pl_data", sa.JSON(), nullable=False),
        sa.Column("sp_data", sa.JSON(), nullable=False),
        sa.Column("cf_data", sa.JSON(), nullable=False),
        sa.Column("projected_kpis", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_snapshots_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_snapshots_project_created",
            ["project_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "snapshot_values",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("base_value", sa.Float(), nullable=True),
        sa.Column(
            "override_delta",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("snapshot_values", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_snapshot_values_snapshot_id"),
            ["snapshot_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_snapshot_values_snapshot_voice_year",
            ["snapshot_id", "voice_id", "year"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("snapshot_values", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshot_values_snapshot_voice_year")
        batch_op.drop_index(batch_op.f("ix_snapshot_values_snapshot_id"))
    op.drop_table("snapshot_values")

    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshots_project_created")
        batch_op.drop_index(batch_op.f("ix_snapshots_project_id"))
    op.drop_table("snapshots")
