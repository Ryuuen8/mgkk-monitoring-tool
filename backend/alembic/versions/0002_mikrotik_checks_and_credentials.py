"""MikroTik checks and encrypted credential profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "credential_type",
            sa.Enum(
                "snmp_v2c",
                "routeros_api",
                name="credential_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column(
            "verify_tls",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="valid_port"),
        sa.CheckConstraint(
            "(credential_type = 'snmp_v2c' AND username IS NULL) OR "
            "(credential_type = 'routeros_api' AND username IS NOT NULL)",
            name="valid_username",
        ),
        sa.UniqueConstraint("name", name="uq_credential_profiles_name"),
    )

    # Do not begin polling devices that were explicitly configured ping-off.
    op.execute("UPDATE devices SET is_active = false WHERE ping_enabled = false")
    op.add_column(
        "devices",
        sa.Column(
            "check_type",
            sa.Enum(
                "ping_only",
                "snmp",
                "routeros_api",
                name="device_check_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="ping_only",
            nullable=False,
        ),
    )
    op.drop_column("devices", "ping_enabled")
    op.drop_column("devices", "snmp_enabled")
    op.drop_column("devices", "snmp_profile_id")
    op.add_column(
        "devices", sa.Column("credential_profile_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_devices_credential_profile_id_credential_profiles",
        "devices",
        "credential_profiles",
        ["credential_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_devices_credential_profile_id",
        "devices",
        ["credential_profile_id"],
    )
    op.create_check_constraint(
        "check_credentials",
        "devices",
        "(check_type = 'ping_only' AND credential_profile_id IS NULL) OR "
        "(check_type IN ('snmp', 'routeros_api') AND "
        "credential_profile_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("check_credentials", "devices", type_="check")
    op.drop_constraint("device_check_type", "devices", type_="check")
    op.drop_index("ix_devices_credential_profile_id", table_name="devices")
    op.drop_constraint(
        "fk_devices_credential_profile_id_credential_profiles",
        "devices",
        type_="foreignkey",
    )
    op.drop_column("devices", "credential_profile_id")
    op.drop_column("devices", "check_type")
    op.add_column(
        "devices",
        sa.Column("ping_enabled", sa.Boolean(), server_default=sa.text("true")),
    )
    op.add_column(
        "devices",
        sa.Column("snmp_enabled", sa.Boolean(), server_default=sa.text("false")),
    )
    op.add_column("devices", sa.Column("snmp_profile_id", sa.BigInteger()))
    op.drop_table("credential_profiles")
