"""Add isolated, durable self-service authorization state.

Revision ID: 20261014_0005
Revises: 20261011_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0005"
down_revision = "20261011_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )
    for field in ("kind", "owner", "family", "expires_at"):
        op.create_index(f"ix_oauth_states_{field}", "oauth_states", [field])


def downgrade() -> None:
    op.drop_table("oauth_states")
