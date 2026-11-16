"""add crawl trigger post_change

Revision ID: a7d2c9e4b1f0
Revises: 44533486c7d9
Create Date: 2026-11-16 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7d2c9e4b1f0'
down_revision: Union[str, None] = '44533486c7d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values; add manually.
    op.execute("ALTER TYPE crawl_trigger ADD VALUE IF NOT EXISTS 'post_change'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; leaving it in place is harmless.
    pass
