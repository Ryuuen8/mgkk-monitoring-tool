"""Add alerting, maintenance windows, syslog history, and PSU counts.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "devices", sa.Column("power_supplies_total", sa.Integer(), nullable=True)
    )
    op.add_column(
        "devices", sa.Column("power_supplies_failed", sa.Integer(), nullable=True)
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("alertname", sa.String(length=120), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("site", sa.String(length=32), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=120), nullable=True),
        sa.Column(
            "suppressed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "last_received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.CheckConstraint(
            "status IN ('firing', 'resolved')",
            name="ck_alert_events_valid_alert_status",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at >= starts_at",
            name="ck_alert_events_valid_alert_window",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fingerprint", "starts_at", name="uq_alert_events_fingerprint_starts_at"
        ),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_alert_events_fingerprint", "alert_events", ["fingerprint"])
    op.create_index("ix_alert_events_alertname", "alert_events", ["alertname"])
    op.create_index("ix_alert_events_device_id", "alert_events", ["device_id"])
    op.create_index("ix_alert_events_site", "alert_events", ["site"])
    op.create_index("ix_alert_events_status", "alert_events", ["status"])
    op.create_index("ix_alert_events_suppressed", "alert_events", ["suppressed"])

    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=True),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("site_id", sa.BigInteger(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "suppress_notifications",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("silence_ids", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
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
        sa.CheckConstraint(
            "scope_type IN ('device', 'group', 'site')",
            name="ck_maintenance_windows_valid_maintenance_scope",
        ),
        sa.CheckConstraint(
            "(scope_type = 'device' AND device_id IS NOT NULL AND "
            "group_id IS NULL AND site_id IS NULL) OR "
            "(scope_type = 'group' AND group_id IS NOT NULL AND "
            "device_id IS NULL AND site_id IS NULL) OR "
            "(scope_type = 'site' AND site_id IS NOT NULL AND "
            "device_id IS NULL AND group_id IS NULL)",
            name="ck_maintenance_windows_valid_maintenance_target",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name="ck_maintenance_windows_valid_maintenance_window",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["device_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_maintenance_windows_device_id", "maintenance_windows", ["device_id"]
    )
    op.create_index(
        "ix_maintenance_windows_group_id", "maintenance_windows", ["group_id"]
    )
    op.create_index(
        "ix_maintenance_windows_site_id", "maintenance_windows", ["site_id"]
    )

    op.create_table(
        "syslog_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("device_id", sa.BigInteger(), nullable=True),
        sa.Column("source_ip", postgresql.INET(), nullable=False),
        sa.Column("facility", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("app_name", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_syslog_events_device_id", "syslog_events", ["device_id"])
    op.create_index("ix_syslog_events_source_ip", "syslog_events", ["source_ip"])
    op.create_index("ix_syslog_events_severity", "syslog_events", ["severity"])
    op.create_index("ix_syslog_events_event_type", "syslog_events", ["event_type"])
    op.create_index(
        "ix_syslog_events_device_occurred",
        "syslog_events",
        ["device_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("syslog_events")
    op.drop_table("maintenance_windows")
    op.drop_table("alert_events")
    op.drop_column("devices", "power_supplies_failed")
    op.drop_column("devices", "power_supplies_total")
