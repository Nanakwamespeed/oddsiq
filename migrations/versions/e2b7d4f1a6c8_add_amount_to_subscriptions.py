"""add amount to subscriptions

Revision ID: e2b7d4f1a6c8
Revises: aa1350648c1e
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e2b7d4f1a6c8'
down_revision = 'aa1350648c1e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('subscriptions', sa.Column('amount', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('subscriptions', 'amount')
