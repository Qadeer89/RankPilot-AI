"""add connector_type sanity

Revision ID: a1c3e9f0b2d4
Revises: efd132153f72
Create Date: 2026-11-03 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3e9f0b2d4'
down_revision: Union[str, None] = 'efd132153f72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values; add manually.
    op.execute("ALTER TYPE connector_type ADD VALUE IF NOT EXISTS 'sanity'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; leaving 'sanity' in place is harmless.
    pass
