"""create drivers table

Revision ID: e8a3f1c5b9d2
Revises: d7c4e9b2a8f1
Create Date: 2026-04-28 14:30:00.000000

M7 — driver intake (flows/05_driver_intake.md). One row per
``(project_id, driver_id)``. ``values`` is a JSON blob for
``scalar_per_year`` drivers (``{"Y-1": 42, "Y0": 45}``);
``static_parameters`` is the JSON blob for non-time-varying drivers
(term loan setup, BoM components, etc.). ``status`` distinguishes
``active`` from ``skipped`` rows so the GET endpoint can surface the
``missing | partial | complete | skipped`` lifecycle without a
separate table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a3f1c5b9d2"
down_revision: Union[str, Sequence[str], None] = "d7c4e9b2a8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("driver_type", sa.String(length=32), nullable=False),
        sa.Column("values", sa.JSON(), nullable=True),
        sa.Column("static_parameters", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            "ix_drivers_project_driver",
            ["project_id", "driver_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("drivers", schema=None) as batch_op:
        batch_op.drop_index("ix_drivers_project_driver")
        batch_op.drop_index(batch_op.f("ix_drivers_project_id"))
    op.drop_table("drivers")
