"""add elo column to team_xg_stats

Revision ID: c7f4a2e8b1d3
Revises: b5e2f1a3c9d7
Create Date: 2026-05-26 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7f4a2e8b1d3'
down_revision = 'b5e2f1a3c9d7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('team_xg_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('elo', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('team_xg_stats', schema=None) as batch_op:
        batch_op.drop_column('elo')
