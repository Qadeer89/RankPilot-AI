"""add webhook crawl trigger and deploy webhook secret

Revision ID: 2d4360873455
Revises: 857507003304
Create Date: 2026-11-14 20:10:23.720214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d4360873455'
down_revision: Union[str, None] = '857507003304'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autogenerate doesn't detect new enum values; add manually.
    op.execute("ALTER TYPE crawl_trigger ADD VALUE IF NOT EXISTS 'webhook'")
    op.add_column('websites', sa.Column('deploy_webhook_secret_hash', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('websites', 'deploy_webhook_secret_hash')
    # Postgres has no DROP VALUE for enums; leaving 'webhook' in place is harmless.
