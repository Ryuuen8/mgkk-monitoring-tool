"""Use the public generic_snmp collector value in storage.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_devices_collector_type"), "devices", type_="check"
    )
    op.execute(
        "UPDATE devices SET collector = 'generic_snmp' "
        "WHERE collector = 'generic'"
    )
    op.alter_column(
        "devices",
        "collector",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default="generic_snmp",
    )
    op.create_check_constraint(
        op.f("ck_devices_collector_type"),
        "devices",
        "collector IN ('generic_snmp', 'mikrotik')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_devices_collector_type"), "devices", type_="check"
    )
    op.execute(
        "UPDATE devices SET collector = 'generic' "
        "WHERE collector = 'generic_snmp'"
    )
    op.alter_column(
        "devices",
        "collector",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default="generic",
    )
    op.create_check_constraint(
        op.f("ck_devices_collector_type"),
        "devices",
        "collector IN ('generic', 'mikrotik')",
    )
