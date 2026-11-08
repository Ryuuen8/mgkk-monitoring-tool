"""SNMPv3 profiles and interface telemetry

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credential_profiles", sa.Column("auth_protocol", sa.String(20), nullable=True)
    )
    op.add_column(
        "credential_profiles",
        sa.Column("privacy_protocol", sa.String(20), nullable=True),
    )
    op.add_column(
        "credential_profiles",
        sa.Column("privacy_secret_ciphertext", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "snmp_auth_protocol",
        "credential_profiles",
        "auth_protocol IS NULL OR auth_protocol IN ('sha', 'sha256')",
    )
    op.create_check_constraint(
        "snmp_privacy_protocol",
        "credential_profiles",
        "privacy_protocol IS NULL OR privacy_protocol IN ('none', 'aes128')",
    )
    op.drop_constraint(
        op.f("ck_credential_profiles_valid_username"),
        "credential_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "valid_username",
        "credential_profiles",
        "(credential_type = 'snmp_v2c' AND username IS NULL AND "
        "auth_protocol IS NULL AND privacy_protocol IS NULL) OR "
        "(credential_type = 'snmp_v3' AND username IS NOT NULL AND "
        "auth_protocol IN ('sha', 'sha256') AND "
        "privacy_protocol IN ('none', 'aes128')) OR "
        "(credential_type = 'routeros_api' AND username IS NOT NULL AND "
        "auth_protocol IS NULL AND privacy_protocol IS NULL)",
    )
    op.drop_constraint(
        op.f("ck_credential_profiles_credential_type"),
        "credential_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "credential_type",
        "credential_profiles",
        "credential_type IN ('snmp_v2c', 'snmp_v3', 'routeros_api')",
    )
    op.create_check_constraint(
        "valid_privacy",
        "credential_profiles",
        "(credential_type != 'snmp_v3' AND privacy_protocol IS NULL AND "
        "privacy_secret_ciphertext IS NULL) OR "
        "(credential_type = 'snmp_v3' AND privacy_protocol = 'none' AND "
        "privacy_secret_ciphertext IS NULL) OR "
        "(credential_type = 'snmp_v3' AND privacy_protocol = 'aes128' AND "
        "privacy_secret_ciphertext IS NOT NULL)",
    )

    op.add_column("devices", sa.Column("snmp_system_name", sa.String(255)))
    op.add_column("devices", sa.Column("snmp_system_description", sa.Text()))
    op.add_column("devices", sa.Column("uptime_seconds", sa.BigInteger()))
    op.add_column("devices", sa.Column("cpu_usage_percent", sa.Float()))
    op.add_column("devices", sa.Column("memory_total_bytes", sa.BigInteger()))
    op.add_column("devices", sa.Column("memory_used_bytes", sa.BigInteger()))

    op.create_table(
        "network_interfaces",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(255)),
        sa.Column("admin_status", sa.Integer()),
        sa.Column("oper_status", sa.Integer()),
        sa.Column("link_speed_mbps", sa.BigInteger()),
        sa.Column("link_speed_override_mbps", sa.BigInteger()),
        sa.Column("last_in_octets", sa.Numeric(20, 0)),
        sa.Column("last_out_octets", sa.Numeric(20, 0)),
        sa.Column("last_in_errors", sa.Numeric(20, 0)),
        sa.Column("last_out_errors", sa.Numeric(20, 0)),
        sa.Column("last_in_discards", sa.Numeric(20, 0)),
        sa.Column("last_out_discards", sa.Numeric(20, 0)),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("device_id", "if_index", name="uq_interface_device_index"),
        sa.CheckConstraint(
            "link_speed_override_mbps IS NULL OR link_speed_override_mbps > 0",
            name="valid_link_speed_override",
        ),
    )
    op.create_index(
        "ix_network_interfaces_device_id", "network_interfaces", ["device_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_network_interfaces_device_id", table_name="network_interfaces")
    op.drop_table("network_interfaces")
    op.drop_column("devices", "memory_used_bytes")
    op.drop_column("devices", "memory_total_bytes")
    op.drop_column("devices", "cpu_usage_percent")
    op.drop_column("devices", "uptime_seconds")
    op.drop_column("devices", "snmp_system_description")
    op.drop_column("devices", "snmp_system_name")
    op.drop_constraint("valid_privacy", "credential_profiles", type_="check")
    op.drop_constraint(
        "snmp_privacy_protocol", "credential_profiles", type_="check"
    )
    op.drop_constraint("snmp_auth_protocol", "credential_profiles", type_="check")
    op.drop_constraint("credential_type", "credential_profiles", type_="check")
    op.create_check_constraint(
        "credential_type",
        "credential_profiles",
        "credential_type IN ('snmp_v2c', 'routeros_api')",
    )
    op.drop_constraint("valid_username", "credential_profiles", type_="check")
    op.create_check_constraint(
        "valid_username",
        "credential_profiles",
        "(credential_type = 'snmp_v2c' AND username IS NULL) OR "
        "(credential_type = 'routeros_api' AND username IS NOT NULL)",
    )
    op.drop_column("credential_profiles", "privacy_secret_ciphertext")
    op.drop_column("credential_profiles", "privacy_protocol")
    op.drop_column("credential_profiles", "auth_protocol")
