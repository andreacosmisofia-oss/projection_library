"""create method_configs table

Revision ID: d7c4e9b2a8f1
Revises: c5b9d2f4a1e7
Create Date: 2026-04-28 12:00:00.000000

M6 — method selection (Expert mode). One row per ``(project_id,
voice_id)`` storing the projection method chosen for that voice.
Persistence is lazy: only voices that have been touched (default
materialised or user-overridden) get a row; the GET endpoint merges
DB rows with ``voice.default_method`` from the registry for the
remainder.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7c4e9b2a8f1"
down_revision: Union[str, Sequence[str], None] = "c5b9d2f4a1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "method_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("method_id", sa.String(length=64), nullable=False),
        sa.Column(
            "method_technical_code", sa.String(length=32), nullable=True
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("method_configs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_method_configs_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_method_configs_project_voice",
            ["project_id", "voice_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("method_configs", schema=None) as batch_op:
        batch_op.drop_index("ix_method_configs_project_voice")
        batch_op.drop_index(batch_op.f("ix_method_configs_project_id"))
    op.drop_table("method_configs")
