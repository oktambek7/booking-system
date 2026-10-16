"""Let customers hide notifications they cleared, without cancelling the messages still to be sent.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TABLES = ("booking_notifications", "waitlist_notifications", "movie_watchlist_notifications")

def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMP WITH TIME ZONE")

def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS dismissed_at")
