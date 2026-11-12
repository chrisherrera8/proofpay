"""jobs.strict_check: a customer can ask that unseen checklist items fail the vision check

Revision ID: f2c6a9d4b7e1
Revises: e5b1a7c3d9f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f2c6a9d4b7e1'
down_revision: Union[str, Sequence[str], None] = 'e5b1a7c3d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('strict_check', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('jobs', 'strict_check')
