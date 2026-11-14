"""Add stable public device UUIDs and enforce unique MAC addresses.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_devices_public_id", "devices", ["public_id"])
    op.drop_index("ix_devices_mac", table_name="devices")
    op.create_unique_constraint("uq_devices_mac", "devices", ["mac"])


def downgrade() -> None:
    op.drop_constraint("uq_devices_mac", "devices", type_="unique")
    op.create_index("ix_devices_mac", "devices", ["mac"], unique=False)
    op.drop_constraint("uq_devices_public_id", "devices", type_="unique")
    op.drop_column("devices", "public_id")
