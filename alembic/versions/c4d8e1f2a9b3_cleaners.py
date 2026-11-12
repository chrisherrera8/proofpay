"""Cleaners table; jobs get cleaner_id and service_date

Revision ID: c4d8e1f2a9b3
Revises: a1f3c9d2e7b4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4d8e1f2a9b3'
down_revision: Union[str, Sequence[str], None] = 'a1f3c9d2e7b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cleaners',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('paypal_email', sa.String(length=320), nullable=False),
        sa.Column('is_seed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_cleaners_one_seed', 'cleaners', ['is_seed'], unique=True, postgresql_where=sa.text('is_seed'))
    op.add_column('jobs', sa.Column('cleaner_id', sa.Uuid(), nullable=True))
    op.add_column('jobs', sa.Column('service_date', sa.Date(), nullable=True))
    op.create_index(op.f('ix_jobs_cleaner_id'), 'jobs', ['cleaner_id'], unique=False)
    op.create_foreign_key('fk_jobs_cleaner_id', 'jobs', 'cleaners', ['cleaner_id'], ['id'], ondelete='SET NULL')
    # Existing jobs get a display date (UTC day of scheduled_at); they have no cleaner, so they block nobody.
    op.execute("UPDATE jobs SET service_date = (scheduled_at AT TIME ZONE 'UTC')::date")


def downgrade() -> None:
    op.drop_constraint('fk_jobs_cleaner_id', 'jobs', type_='foreignkey')
    op.drop_index(op.f('ix_jobs_cleaner_id'), table_name='jobs')
    op.drop_column('jobs', 'service_date')
    op.drop_column('jobs', 'cleaner_id')
    op.drop_index('uq_cleaners_one_seed', table_name='cleaners', postgresql_where=sa.text('is_seed'))
    op.drop_table('cleaners')
