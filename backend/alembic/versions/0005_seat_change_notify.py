"""Tell listeners (the live seat map) whenever a seat's availability changes.

A trigger on booking_seats sends NOTIFY seat_changes with the screening id when a seat is taken
(INSERT) or released/re-taken (active flips). Doing it in the database catches every source of change
(new holds, cancellations, hold expiry run by any instance or job) and delivers only on commit.
Identical notifications inside one transaction are folded by PostgreSQL.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION notify_seat_change() RETURNS trigger AS $$
    BEGIN
      PERFORM pg_notify('seat_changes', NEW.screening_id::text);
      RETURN NULL;
    END
    $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER booking_seats_notify_insert AFTER INSERT ON booking_seats "
               "FOR EACH ROW EXECUTE FUNCTION notify_seat_change()")
    op.execute("CREATE TRIGGER booking_seats_notify_update AFTER UPDATE OF active ON booking_seats "
               "FOR EACH ROW WHEN (OLD.active IS DISTINCT FROM NEW.active) EXECUTE FUNCTION notify_seat_change()")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS booking_seats_notify_update ON booking_seats")
    op.execute("DROP TRIGGER IF EXISTS booking_seats_notify_insert ON booking_seats")
    op.execute("DROP FUNCTION IF EXISTS notify_seat_change()")
