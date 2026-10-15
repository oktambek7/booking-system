"""Audit log of operator and security-relevant actions.

Append-only: a trigger rejects DELETE and any UPDATE other than clearing the actor reference
(which PostgreSQL performs itself when an account is deleted).

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

GUARD_FUNCTION = """
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
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])
    op.execute(GUARD_FUNCTION)
    op.execute("CREATE TRIGGER audit_log_guard BEFORE UPDATE OR DELETE ON audit_log "
               "FOR EACH ROW EXECUTE FUNCTION audit_log_guard()")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_guard ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_guard()")
    op.drop_table("audit_log")
