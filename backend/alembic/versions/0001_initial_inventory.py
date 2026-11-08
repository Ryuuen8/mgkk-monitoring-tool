"""initial inventory

Revision ID: 0001
Revises: 
Create Date: 2026-11-08 02:49:29.710711
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('device_groups',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_device_groups')),
    sa.UniqueConstraint('name', name=op.f('uq_device_groups_name'))
    )
    op.create_table('sites',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sites')),
    sa.UniqueConstraint('code', name=op.f('uq_sites_code'))
    )
    op.create_table('devices',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('site_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('hostname', sa.String(length=255), nullable=True),
    sa.Column('mgmt_ip', postgresql.INET(), nullable=False),
    sa.Column('mac', postgresql.MACADDR(), nullable=True),
    sa.Column('device_type', sa.Enum('router', 'switch', 'firewall', 'server', 'access_point', 'other', name='device_type', native_enum=False, create_constraint=True, length=20), server_default='other', nullable=False),
    sa.Column('vendor', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('os_version', sa.String(length=64), nullable=True),
    sa.Column('serial_number', sa.String(length=120), nullable=True),
    sa.Column('parent_device_id', sa.BigInteger(), nullable=True),
    sa.Column('ping_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('snmp_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('poll_interval_seconds', sa.Integer(), server_default=sa.text('60'), nullable=False),
    sa.Column('snmp_profile_id', sa.BigInteger(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('parent_device_id <> id', name=op.f('ck_devices_no_self_parent')),
    sa.CheckConstraint('poll_interval_seconds >= 10', name=op.f('ck_devices_min_poll_interval')),
    sa.ForeignKeyConstraint(['parent_device_id'], ['devices.id'], name=op.f('fk_devices_parent_device_id_devices'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_devices_site_id_sites'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_devices')),
    sa.UniqueConstraint('name', name=op.f('uq_devices_name'))
    )
    op.create_index(op.f('ix_devices_is_active'), 'devices', ['is_active'], unique=False)
    op.create_index(op.f('ix_devices_mac'), 'devices', ['mac'], unique=False)
    op.create_index(op.f('ix_devices_mgmt_ip'), 'devices', ['mgmt_ip'], unique=False)
    op.create_index(op.f('ix_devices_parent_device_id'), 'devices', ['parent_device_id'], unique=False)
    op.create_index(op.f('ix_devices_site_id'), 'devices', ['site_id'], unique=False)
    op.create_table('device_group_members',
    sa.Column('device_id', sa.BigInteger(), nullable=False),
    sa.Column('group_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_device_group_members_device_id_devices'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['device_groups.id'], name=op.f('fk_device_group_members_group_id_device_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('device_id', 'group_id', name=op.f('pk_device_group_members'))
    )
    op.create_index('ix_device_group_members_group_id', 'device_group_members', ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_device_group_members_group_id', table_name='device_group_members')
    op.drop_table('device_group_members')
    op.drop_index(op.f('ix_devices_site_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_parent_device_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_mgmt_ip'), table_name='devices')
    op.drop_index(op.f('ix_devices_mac'), table_name='devices')
    op.drop_index(op.f('ix_devices_is_active'), table_name='devices')
    op.drop_table('devices')
    op.drop_table('sites')
    op.drop_table('device_groups')
