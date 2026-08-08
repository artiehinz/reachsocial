"""Initial ReachSocial schema.

Revision ID: 20260808_0001
Revises:
Create Date: 2026-08-08
"""

from alembic import op

from reachsocial import models  # noqa: F401
from reachsocial.db import Base

revision = "20260808_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
