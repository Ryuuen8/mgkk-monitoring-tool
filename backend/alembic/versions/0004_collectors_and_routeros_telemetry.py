"""Add collector selection and RouterOS resource telemetry.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "collector",
            sa.String(length=20),
            server_default="generic",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_devices_collector_type"),
        "devices",
        "collector IN ('generic', 'mikrotik')",
    )
    op.execute(
        "UPDATE devices SET collector = 'mikrotik' "
        "WHERE check_type = 'routeros_api' OR lower(coalesce(vendor, '')) = 'mikrotik'"
    )
    op.add_column("devices", sa.Column("disk_total_bytes", sa.BigInteger()))
    op.add_column("devices", sa.Column("disk_used_bytes", sa.BigInteger()))
    op.add_column("devices", sa.Column("temperature_celsius", sa.Float()))
    op.add_column("devices", sa.Column("voltage_volts", sa.Float()))
    op.add_column("devices", sa.Column("dhcp_lease_count", sa.Integer()))
    op.add_column("devices", sa.Column("arp_entry_count", sa.Integer()))


def downgrade() -> None:
    op.drop_column("devices", "arp_entry_count")
    op.drop_column("devices", "dhcp_lease_count")
    op.drop_column("devices", "voltage_volts")
    op.drop_column("devices", "temperature_celsius")
    op.drop_column("devices", "disk_used_bytes")
    op.drop_column("devices", "disk_total_bytes")
    op.drop_constraint(
        op.f("ck_devices_collector_type"), "devices", type_="check"
    )
    op.drop_column("devices", "collector")
