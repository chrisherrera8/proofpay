"""initial schema

Revision ID: 11ad39a14edc
Revises: 
Create Date: 2026-11-04 19:46:55.134656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '11ad39a14edc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('customer_name', sa.String(length=200), nullable=False),
    sa.Column('customer_email', sa.String(length=320), nullable=False),
    sa.Column('address', sa.String(length=500), nullable=False),
    sa.Column('service_type', sa.String(length=64), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('BOOKED', 'AUTHORIZED', 'SUBMITTED', 'VERIFIED', 'PENDING_APPROVAL', 'RELEASED', 'REJECTED', 'CAPTURED', 'PAID_OUT')", name='ck_jobs_status'),
    sa.CheckConstraint('amount > 0', name='ck_jobs_amount_positive'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('mandates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monthly_cap', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('approved_subcontractors', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('auto_release_ceiling', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('min_score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('required_items', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.String(length=200), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approvals_job_id'), 'approvals', ['job_id'], unique=False)
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('actor', sa.String(length=100), nullable=False),
    sa.Column('event', sa.String(length=100), nullable=False),
    sa.Column('from_status', sa.String(length=32), nullable=True),
    sa.Column('to_status', sa.String(length=32), nullable=True),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hash')
    )
    op.create_index(op.f('ix_audit_log_job_id'), 'audit_log', ['job_id'], unique=False)
    # Append-only: block UPDATE and DELETE on the audit log at the database level.
    op.execute("""
        CREATE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation()
    """)
    op.create_table('checklist_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checklist_items_job_id'), 'checklist_items', ['job_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.String(length=64), nullable=False),
    sa.Column('authorization_id', sa.String(length=64), nullable=True),
    sa.Column('capture_id', sa.String(length=64), nullable=True),
    sa.Column('authorized_amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id'),
    sa.UniqueConstraint('order_id')
    )
    op.create_table('payouts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('batch_id', sa.String(length=64), nullable=True),
    sa.Column('item_id', sa.String(length=64), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payouts_batch_id'), 'payouts', ['batch_id'], unique=False)
    op.create_index(op.f('ix_payouts_job_id'), 'payouts', ['job_id'], unique=False)
    op.create_table('photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_photos_job_id'), 'photos', ['job_id'], unique=False)
    op.create_table('verifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('results', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_verifications_job_id'), 'verifications', ['job_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_verifications_job_id'), table_name='verifications')
    op.drop_table('verifications')
    op.drop_index(op.f('ix_photos_job_id'), table_name='photos')
    op.drop_table('photos')
    op.drop_index(op.f('ix_payouts_job_id'), table_name='payouts')
    op.drop_index(op.f('ix_payouts_batch_id'), table_name='payouts')
    op.drop_table('payouts')
    op.drop_table('payments')
    op.drop_index(op.f('ix_checklist_items_job_id'), table_name='checklist_items')
    op.drop_table('checklist_items')
    op.drop_index(op.f('ix_audit_log_job_id'), table_name='audit_log')
    op.execute("DROP TRIGGER audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION audit_log_block_mutation()")
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_approvals_job_id'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_table('mandates')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_table('jobs')
