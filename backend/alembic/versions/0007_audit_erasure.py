"""Let the audit log honour an erasure request without becoming editable.

The append-only trigger now also allows exactly two changes to an existing entry: replacing the actor's e-mail
with the `deleted-user-<id>@deleted.invalid` tombstone, and clearing the caller address. Everything else, and every
DELETE, is still rejected.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NEW_GUARD = """
CREATE OR REPLACE FUNCTION audit_log_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'audit_log is append-only';
  END IF;
  IF (NEW.id, NEW.created_at, NEW.action, NEW.target_type, NEW.target_id, NEW.details, NEW.request_id)
     IS DISTINCT FROM
     (OLD.id, OLD.created_at, OLD.action, OLD.target_type, OLD.target_id, OLD.details, OLD.request_id)
     OR (NEW.actor_email IS DISTINCT FROM OLD.actor_email
         AND (NEW.actor_email IS NULL OR NEW.actor_email NOT LIKE 'deleted-user-%@deleted.invalid'))
     OR (NEW.ip IS DISTINCT FROM OLD.ip AND NEW.ip IS NOT NULL) THEN
    RAISE EXCEPTION 'audit_log is append-only';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

OLD_GUARD = """
CREATE OR REPLACE FUNCTION audit_log_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'audit_log is append-only';
  END IF;
  IF (NEW.id, NEW.created_at, NEW.actor_email, NEW.action, NEW.target_type, NEW.target_id, NEW.details, NEW.request_id, NEW.ip)
     IS DISTINCT FROM
     (OLD.id, OLD.created_at, OLD.actor_email, OLD.action, OLD.target_type, OLD.target_id, OLD.details, OLD.request_id, OLD.ip) THEN
    RAISE EXCEPTION 'audit_log is append-only';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

def upgrade() -> None:
    op.execute(NEW_GUARD)

def downgrade() -> None:
    op.execute(OLD_GUARD)
