"""create balances and raw_voices tables

Revision ID: 8a4f1c2d9e3b
Revises: 66e0e2087e0d
Create Date: 2026-04-28 09:00:00.000000

M3 — intake bilancio (Case 1: gestionale). One ``balances`` row per
upload (soft-deleted on re-upload), N ``raw_voices`` rows per balance,
one per (voice_label, year).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a4f1c2d9e3b"
down_revision: Union[str, Sequence[str], None] = "66e0e2087e0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "balances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("raw_filename", sa.String(length=255), nullable=False),
        sa.Column("years_present", sa.JSON(), nullable=False),
        sa.Column("voice_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("balances", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_balances_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_balances_deleted_at"), ["deleted_at"], unique=False
        )

    op.create_table(
        "raw_voices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("balance_id", sa.String(length=36), nullable=False),
        sa.Column("voice_user_label", sa.String(length=255), nullable=False),
        sa.Column("voice_user_section", sa.String(length=32), nullable=True),
        sa.Column("year", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("lfl_flag", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["balance_id"], ["balances.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("raw_voices", schema=None) as batch_op:
        batch_op.create_index(
            "ix_raw_voices_balance_year",
            ["balance_id", "year"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("raw_voices", schema=None) as batch_op:
        batch_op.drop_index("ix_raw_voices_balance_year")
    op.drop_table("raw_voices")

    with op.batch_alter_table("balances", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_balances_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_balances_project_id"))
    op.drop_table("balances")
