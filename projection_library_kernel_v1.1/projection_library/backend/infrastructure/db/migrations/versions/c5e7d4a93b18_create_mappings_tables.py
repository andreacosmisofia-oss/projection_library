"""create mappings and company_mappings tables

Revision ID: c5e7d4a93b18
Revises: 8a4f1c2d9e3b
Create Date: 2026-04-28 12:00:00.000000

M4 — mapper. ``mappings`` stores confirmed (or explicitly skipped)
user-voice → system-voice rows; ``company_mappings`` is the
per-company memory used by strategy A of the auto-suggest pipeline.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e7d4a93b18"
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
        sa.Column("voice_id_system", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("auto_suggested", sa.Boolean(), nullable=False),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column("sign_flip_applied", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            "ux_mappings_project_label_section",
            ["project_id", "voice_user_label", "voice_user_section"],
            unique=True,
        )

    op.create_table(
        "company_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_name_norm", sa.String(length=255), nullable=False),
        sa.Column(
            "voice_user_label_norm", sa.String(length=255), nullable=False
        ),
        sa.Column("voice_id_system", sa.String(length=255), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("company_mappings", schema=None) as batch_op:
        batch_op.create_index(
            "ux_company_mappings_company_label",
            ["company_name_norm", "voice_user_label_norm"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("company_mappings", schema=None) as batch_op:
        batch_op.drop_index("ux_company_mappings_company_label")
    op.drop_table("company_mappings")

    with op.batch_alter_table("mappings", schema=None) as batch_op:
        batch_op.drop_index("ux_mappings_project_label_section")
        batch_op.drop_index(batch_op.f("ix_mappings_project_id"))
    op.drop_table("mappings")
