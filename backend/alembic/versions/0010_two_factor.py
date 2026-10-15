"""Two-step verification (TOTP) with recovery codes, and a per-session record that the second step was done.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "user_totp",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_step", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "totp_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_totp_recovery_codes_user_id", "totp_recovery_codes", ["user_id"])
    op.create_index("ix_totp_recovery_codes_code_hash", "totp_recovery_codes", ["code_hash"])
    op.add_column("refresh_tokens", sa.Column("mfa", sa.Boolean(), server_default=sa.false(), nullable=False))

def downgrade() -> None:
    op.drop_column("refresh_tokens", "mfa")
    op.drop_table("totp_recovery_codes")
    op.drop_table("user_totp")
