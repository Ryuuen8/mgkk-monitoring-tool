"""Persist CRC counters and latest RouterOS operational snapshots.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "network_interfaces",
        sa.Column("last_crc_errors", sa.Numeric(20, 0), nullable=True),
    )
    op.create_table(
        "routeros_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "snapshot_type IN ('dhcp_leases', 'arp_entries', 'wireless_clients')",
            name=op.f("ck_routeros_snapshots_valid_snapshot_type"),
        ),
        sa.UniqueConstraint(
            "device_id",
            "snapshot_type",
            name="uq_routeros_snapshots_device_type",
        ),
    )
    op.create_index(
        op.f("ix_routeros_snapshots_device_id"),
        "routeros_snapshots",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_routeros_snapshots_device_id"), table_name="routeros_snapshots"
    )
    op.drop_table("routeros_snapshots")
    op.drop_column("network_interfaces", "last_crc_errors")
