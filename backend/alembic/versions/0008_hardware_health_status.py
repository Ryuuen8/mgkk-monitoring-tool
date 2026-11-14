"""Persist fan and power-supply health signals.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices", sa.Column("fan_speed_rpm", sa.Float(), nullable=True)
    )
    op.add_column("devices", sa.Column("fans_ok", sa.Boolean(), nullable=True))
    op.add_column(
        "devices", sa.Column("power_supplies_ok", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("devices", "power_supplies_ok")
    op.drop_column("devices", "fans_ok")
    op.drop_column("devices", "fan_speed_rpm")
