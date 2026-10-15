"""Baseline: the schema as built by every release before Alembic.

Fresh databases get the whole schema; databases created by earlier releases are brought
forward by the same idempotent statements, then stamped. See app/legacy_schema.py.

Revision ID: 0001
Revises:
"""
from alembic import op
from app.legacy_schema import apply_legacy_schema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    apply_legacy_schema(op.get_bind())

def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded; restore a database backup instead")
