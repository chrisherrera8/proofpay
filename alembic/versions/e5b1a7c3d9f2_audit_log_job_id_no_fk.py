"""audit_log.job_id: no foreign key, so a job can be deleted while its audit rows stay

The audit log is append-only and hash-chained, so its rows can't be updated or removed. Deleting a job (the
24-hour purge) used to be blocked by the foreign key. The rows hold ids, statuses and counts, never names or
emails, so they stay as an anonymous record and the chain still verifies.

Revision ID: e5b1a7c3d9f2
Revises: d7b2e5a8c1f4
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e5b1a7c3d9f2'
down_revision: Union[str, Sequence[str], None] = 'd7b2e5a8c1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('audit_log_job_id_fkey', 'audit_log', type_='foreignkey')


def downgrade() -> None:
    # Fails if purged jobs have left orphaned audit rows: they can't be removed, so there is no way back then.
    op.create_foreign_key('audit_log_job_id_fkey', 'audit_log', 'jobs', ['job_id'], ['id'])
