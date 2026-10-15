"""Telegram notification links.

A customer links a Telegram chat to their account with a single-use, expiring token; the chat id is the
only Telegram data kept, and unlinking (or deleting the account) removes it.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_links_user_id", "telegram_links", ["user_id"], unique=True)
    op.create_index("ix_telegram_links_chat_id", "telegram_links", ["chat_id"], unique=True)
    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_link_tokens_user_id", "telegram_link_tokens", ["user_id"])
    op.create_index("ix_telegram_link_tokens_token_hash", "telegram_link_tokens", ["token_hash"], unique=True)

def downgrade() -> None:
    op.drop_table("telegram_link_tokens")
    op.drop_table("telegram_links")
