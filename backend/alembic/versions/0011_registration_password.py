"""Bind the password chosen at registration to the e-mail code it was sent with.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("email_otp_challenges", sa.Column("password_hash", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("email_otp_challenges", "password_hash")
