"""add opportunity_status resolved

Revision ID: b4d6f1a2c8e9
Revises: a1c3e9f0b2d4
Create Date: 2026-11-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d6f1a2c8e9'
down_revision: Union[str, None] = 'a1c3e9f0b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values; add manually.
    op.execute("ALTER TYPE opportunity_status ADD VALUE IF NOT EXISTS 'resolved'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; leaving 'resolved' in place is harmless.
    pass
