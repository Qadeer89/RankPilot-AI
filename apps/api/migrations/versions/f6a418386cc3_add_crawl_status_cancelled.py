"""add crawl status cancelled

Revision ID: f6a418386cc3
Revises: 4985786fd162
Create Date: 2026-11-02 16:50:00.813435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a418386cc3'
down_revision: Union[str, None] = '4985786fd162'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values; add manually.
    op.execute("ALTER TYPE crawl_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; leaving 'cancelled' in place is harmless.
    pass
