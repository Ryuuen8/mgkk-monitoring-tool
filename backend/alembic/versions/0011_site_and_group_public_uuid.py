"""Add stable public UUIDs to sites and device groups.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_public_id(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(f"uq_{table}_public_id", table, ["public_id"])


def upgrade() -> None:
    _add_public_id("sites")
    _add_public_id("device_groups")


def downgrade() -> None:
    op.drop_constraint("uq_device_groups_public_id", "device_groups", type_="unique")
    op.drop_column("device_groups", "public_id")
    op.drop_constraint("uq_sites_public_id", "sites", type_="unique")
    op.drop_column("sites", "public_id")
