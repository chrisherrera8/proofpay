"""cleaners.last_used_at: the 24-hour expiry now counts from last use, not from sign-up

Revision ID: d7b2e5a8c1f4
Revises: c4d8e1f2a9b3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd7b2e5a8c1f4'
down_revision: Union[str, Sequence[str], None] = 'c4d8e1f2a9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cleaners', sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))
    # Existing cleaners keep their current expiry: their clock started at sign-up.
    op.execute('UPDATE cleaners SET last_used_at = created_at')
    op.alter_column('cleaners', 'last_used_at', nullable=False, server_default=sa.text('now()'))


def downgrade() -> None:
    op.drop_column('cleaners', 'last_used_at')
