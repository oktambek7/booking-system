"""Hosted-checkout payments: provider references, idempotency keys and a webhook event ledger.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("payments", sa.Column("provider_reference", sa.String(80), nullable=True))
    op.add_column("payments", sa.Column("idempotency_key", sa.String(80), nullable=True))
    op.create_index("uq_payment_provider_reference", "payments", ["provider", "provider_reference"], unique=True,
                    postgresql_where=sa.text("provider_reference IS NOT NULL"))
    op.create_index("uq_payment_idempotency_key", "payments", ["booking_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.drop_index("uq_open_payment_per_booking", table_name="payments")
    op.create_index("uq_open_payment_per_booking", "payments", ["booking_id"], unique=True,
                    postgresql_where=sa.text("status IN ('awaiting_verification', 'awaiting_provider')"))
    op.create_table(
        "payment_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_event"),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])

def downgrade() -> None:
    op.drop_table("payment_events")
    op.drop_index("uq_open_payment_per_booking", table_name="payments")
    op.create_index("uq_open_payment_per_booking", "payments", ["booking_id"], unique=True,
                    postgresql_where=sa.text("status = 'awaiting_verification'"))
    op.drop_index("uq_payment_idempotency_key", table_name="payments")
    op.drop_index("uq_payment_provider_reference", table_name="payments")
    op.drop_column("payments", "idempotency_key")
    op.drop_column("payments", "provider_reference")
