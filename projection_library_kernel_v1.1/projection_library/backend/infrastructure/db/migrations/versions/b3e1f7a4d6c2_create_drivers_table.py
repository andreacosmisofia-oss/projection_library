"""create drivers table

Revision ID: b3e1f7a4d6c2
Revises: d7c4e9b2a8f1
Create Date: 2026-04-28 14:30:00.000000

M7 — driver intake (``flows/05_driver_intake.md``). One physical
table covers the four polymorphic driver types declared in
``driver_registry.schema.json`` (scalar_per_year, static_parameters,
time_series, aging_bucket). For non-time-varying types ``year`` is the
empty string so the unique index on
``(project_id, driver_id, year)`` stays effective on SQLite (where
NULLs are not equal). The skip flag is a row-level marker, not a
separate table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e1f7a4d6c2"
down_revision: Union[str, Sequence[str], None] = "d7c4e9b2a8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "year", sa.String(length=8), nullable=False, server_default=""
        ),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("static_parameters", sa.JSON(), nullable=True),
        sa.Column("time_series", sa.JSON(), nullable=True),
        sa.Column("aging_buckets", sa.JSON(), nullable=True),
        sa.Column(
            "skipped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("drivers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_drivers_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_drivers_driver_id"),
            ["driver_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_drivers_project_driver_year",
            ["project_id", "driver_id", "year"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("drivers", schema=None) as batch_op:
        batch_op.drop_index("ix_drivers_project_driver_year")
        batch_op.drop_index(batch_op.f("ix_drivers_driver_id"))
        batch_op.drop_index(batch_op.f("ix_drivers_project_id"))
    op.drop_table("drivers")
