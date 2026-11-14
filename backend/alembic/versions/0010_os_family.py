"""Add the device OS family.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices", sa.Column("os_family", sa.String(length=20), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_devices_os_family"),
        "devices",
        "os_family IS NULL OR "
        "os_family IN ('routeros', 'ios', 'iosxe', 'nxos', 'linux')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_devices_os_family"), "devices", type_="check")
    op.drop_column("devices", "os_family")
