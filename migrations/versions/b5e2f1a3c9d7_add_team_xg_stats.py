"""add team_xg_stats table

Revision ID: b5e2f1a3c9d7
Revises: 4133f0db3aa8
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b5e2f1a3c9d7'
down_revision = '4133f0db3aa8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_xg_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('season', sa.String(length=10), nullable=False),
        sa.Column('matches', sa.Integer(), nullable=True),
        sa.Column('xg_for', sa.Float(), nullable=True),
        sa.Column('xg_against', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id')
    )
    op.create_index('ix_team_xg_stats_team_id', 'team_xg_stats', ['team_id'])


def downgrade():
    op.drop_index('ix_team_xg_stats_team_id', table_name='team_xg_stats')
    op.drop_table('team_xg_stats')
