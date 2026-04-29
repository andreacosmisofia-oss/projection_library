"""create overrides table

Revision ID: f1a3b8d6c4e2
Revises: e2c8a5f3b9d4
Create Date: 2026-04-29 10:00:00.000000

M11 — override layer (``flows/09_iteration.md`` §"Override Layer"). One
row per user-applied delta on a (voice, year) pair; the engine reads
active rows on every run and composes them with ``base_values`` via
:func:`backend.domain.engine.value_resolver.resolve_voice_value`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a3b8d6c4e2"
down_revision: Union[str, Sequence[str], None] = "e2c8a5f3b9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("voice_id", sa.String(length=128), nullable=False),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("delta_amount", sa.Float(), nullable=False),
        sa.Column("nature", sa.String(length=16), nullable=False),
        sa.Column(
            "override_policy_class", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("user_note", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "deactivated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.CheckConstraint(
            "nature IN ('organic', 'one_shot')", name="ck_overrides_nature"
        ),
        sa.CheckConstraint(
            "year IN ('Y1', 'Y2', 'Y3')", name="ck_overrides_year"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("overrides", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_overrides_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_overrides_project_active",
            ["project_id", "is_active"],
            unique=False,
        )
        batch_op.create_index(
            "ix_overrides_project_voice_year",
            ["project_id", "voice_id", "year"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("overrides", schema=None) as batch_op:
        batch_op.drop_index("ix_overrides_project_voice_year")
        batch_op.drop_index("ix_overrides_project_active")
        batch_op.drop_index(batch_op.f("ix_overrides_project_id"))
    op.drop_table("overrides")
