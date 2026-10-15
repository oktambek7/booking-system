"""Refund ledger and refund details on bookings.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("bookings", sa.Column("refund_amount", sa.Numeric(12, 2), server_default="0", nullable=False))
    op.add_column("bookings", sa.Column("refund_percent", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "refunds",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("points_restored", sa.Integer(), server_default="0", nullable=False),
        sa.Column("points_clawed_back", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("initiated_by", sa.String(12), nullable=False),
        sa.Column("provider_reference", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0 AND percent BETWEEN 1 AND 100", name="ck_refund_positive"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"], unique=True)   # one refund per payment, ever
    op.create_index("ix_refunds_booking_id", "refunds", ["booking_id"])

def downgrade() -> None:
    op.drop_table("refunds")
    op.drop_column("bookings", "refunded_at")
    op.drop_column("bookings", "refund_percent")
    op.drop_column("bookings", "refund_amount")
