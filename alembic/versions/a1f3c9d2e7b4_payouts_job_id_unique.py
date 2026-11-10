"""One payout per job: make ix_payouts_job_id unique

Revision ID: a1f3c9d2e7b4
Revises: 11ad39a14edc
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1f3c9d2e7b4'
down_revision: Union[str, Sequence[str], None] = '11ad39a14edc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_payouts_job_id'), table_name='payouts')
    op.create_index(op.f('ix_payouts_job_id'), 'payouts', ['job_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_payouts_job_id'), table_name='payouts')
    op.create_index(op.f('ix_payouts_job_id'), 'payouts', ['job_id'], unique=False)
