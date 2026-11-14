"""Add the Cisco collector, RESTCONF checks, and topology neighbours.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- devices: collector, check type, and credential pairing -------------
    op.drop_constraint(
        op.f("ck_devices_collector_type"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_collector_type"),
        "devices",
        "collector IN ('generic_snmp', 'mikrotik', 'cisco')",
    )

    op.drop_constraint(
        op.f("ck_devices_device_check_type"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_device_check_type"),
        "devices",
        "check_type IN ('ping_only', 'snmp', 'routeros_api', 'restconf')",
    )

    op.drop_constraint(
        op.f("ck_devices_check_credentials"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_check_credentials"),
        "devices",
        "(check_type = 'ping_only' AND credential_profile_id IS NULL) OR "
        "(check_type IN ('snmp', 'routeros_api', 'restconf') AND "
        "credential_profile_id IS NOT NULL)",
    )

    # --- credential_profiles: Cisco RESTCONF and SSH credentials ------------
    op.drop_constraint(
        op.f("ck_credential_profiles_credential_type"),
        "credential_profiles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_credential_profiles_credential_type"),
        "credential_profiles",
        "credential_type IN ("
        "'snmp_v2c', 'snmp_v3', 'routeros_api', "
        "'cisco_restconf', 'cisco_ssh')",
    )

    op.drop_constraint(
        op.f("ck_credential_profiles_valid_username"),
        "credential_profiles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_credential_profiles_valid_username"),
        "credential_profiles",
        "(credential_type = 'snmp_v2c' AND username IS NULL AND "
        "auth_protocol IS NULL AND privacy_protocol IS NULL) OR "
        "(credential_type = 'snmp_v3' AND username IS NOT NULL AND "
        "auth_protocol IN ('sha', 'sha256') AND "
        "privacy_protocol IN ('none', 'aes128')) OR "
        "(credential_type IN ('routeros_api', 'cisco_restconf', 'cisco_ssh') "
        "AND username IS NOT NULL AND "
        "auth_protocol IS NULL AND privacy_protocol IS NULL)",
    )

    # --- routeros_snapshots becomes the collector-agnostic snapshots table --
    op.rename_table("routeros_snapshots", "device_snapshots")
    op.drop_constraint(
        op.f("ck_routeros_snapshots_valid_snapshot_type"),
        "device_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_device_snapshots_valid_snapshot_type"),
        "device_snapshots",
        "snapshot_type IN ("
        "'dhcp_leases', 'arp_entries', 'wireless_clients', 'stack_members')",
    )
    op.execute(
        "ALTER TABLE device_snapshots "
        "RENAME CONSTRAINT uq_routeros_snapshots_device_type "
        "TO uq_device_snapshots_device_type"
    )
    op.execute(
        "ALTER INDEX ix_routeros_snapshots_device_id "
        "RENAME TO ix_device_snapshots_device_id"
    )
    op.execute(
        "ALTER TABLE device_snapshots RENAME CONSTRAINT pk_routeros_snapshots "
        "TO pk_device_snapshots"
    )

    # --- discovered topology adjacencies ------------------------------------
    op.create_table(
        "device_neighbors",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("local_interface", sa.String(length=255), nullable=False),
        sa.Column("remote_device", sa.String(length=255), nullable=True),
        sa.Column("remote_interface", sa.String(length=255), nullable=True),
        sa.Column("remote_platform", sa.String(length=255), nullable=True),
        sa.Column("remote_address", sa.String(length=64), nullable=True),
        sa.Column("capabilities", sa.String(length=255), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "device_id",
            "protocol",
            "local_interface",
            "remote_device",
            "remote_interface",
            name="uq_device_neighbors_identity",
        ),
    )
    op.create_index(
        op.f("ix_device_neighbors_device_id"),
        "device_neighbors",
        ["device_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_device_neighbors_device_id"), table_name="device_neighbors"
    )
    op.drop_table("device_neighbors")

    op.execute(
        "ALTER TABLE device_snapshots RENAME CONSTRAINT pk_device_snapshots "
        "TO pk_routeros_snapshots"
    )
    op.execute(
        "ALTER INDEX ix_device_snapshots_device_id "
        "RENAME TO ix_routeros_snapshots_device_id"
    )
    op.execute(
        "ALTER TABLE device_snapshots "
        "RENAME CONSTRAINT uq_device_snapshots_device_type "
        "TO uq_routeros_snapshots_device_type"
    )
    op.drop_constraint(
        op.f("ck_device_snapshots_valid_snapshot_type"),
        "device_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_routeros_snapshots_valid_snapshot_type"),
        "device_snapshots",
        "snapshot_type IN ("
        "'dhcp_leases', 'arp_entries', 'wireless_clients')",
    )
    op.rename_table("device_snapshots", "routeros_snapshots")

    op.drop_constraint(
        op.f("ck_credential_profiles_valid_username"),
        "credential_profiles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_credential_profiles_valid_username"),
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
        op.f("ck_credential_profiles_credential_type"),
        "credential_profiles",
        "credential_type IN ('snmp_v2c', 'snmp_v3', 'routeros_api')",
    )

    op.drop_constraint(
        op.f("ck_devices_check_credentials"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_check_credentials"),
        "devices",
        "(check_type = 'ping_only' AND credential_profile_id IS NULL) OR "
        "(check_type IN ('snmp', 'routeros_api') AND "
        "credential_profile_id IS NOT NULL)",
    )
    op.drop_constraint(
        op.f("ck_devices_device_check_type"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_device_check_type"),
        "devices",
        "check_type IN ('ping_only', 'snmp', 'routeros_api')",
    )
    op.drop_constraint(
        op.f("ck_devices_collector_type"), "devices", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_devices_collector_type"),
        "devices",
        "collector IN ('generic_snmp', 'mikrotik')",
    )
