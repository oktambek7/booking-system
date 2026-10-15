"""Operators limited to particular cinemas.

`users.cinema_scoped` makes an operator a scoped one: they see and manage only the cinemas listed for them in
`cinema_operators`. It is an explicit flag, not "has rows", so removing a scoped operator's last cinema leaves
them with access to nothing instead of silently promoting them to an owner. Existing operators stay owners.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("users", sa.Column("cinema_scoped", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        "cinema_operators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cinema_name", sa.String(160), nullable=False),
        sa.UniqueConstraint("user_id", "cinema_name", name="uq_cinema_operator"),
    )
    op.create_index("ix_cinema_operators_user_id", "cinema_operators", ["user_id"])

def downgrade() -> None:
    op.drop_table("cinema_operators")
    op.drop_column("users", "cinema_scoped")
