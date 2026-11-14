"""add automation mode crawl frequency and ai budget override

Revision ID: 78d1e92686b2
Revises: 2d4360873455
Create Date: 2026-11-14 20:35:28.862578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78d1e92686b2'
down_revision: Union[str, None] = '2d4360873455'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Unlike a brand-new table's CREATE TABLE (which embeds CREATE TYPE
    # automatically), adding an enum column to an existing table needs
    # the type created explicitly first.
    automation_mode_enum = sa.Enum('audit', 'copilot', 'autopilot', name='website_automation_mode')
    automation_mode_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'websites',
        sa.Column('automation_mode', automation_mode_enum, nullable=False, server_default='autopilot'),
    )
    op.alter_column('websites', 'automation_mode', server_default=None)

    op.add_column(
        'websites', sa.Column('crawl_frequency_hours', sa.Integer(), nullable=False, server_default='24')
    )
    op.alter_column('websites', 'crawl_frequency_hours', server_default=None)

    op.add_column('websites', sa.Column('ai_daily_budget_usd_override', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('websites', 'ai_daily_budget_usd_override')
    op.drop_column('websites', 'crawl_frequency_hours')
    op.drop_column('websites', 'automation_mode')
    sa.Enum(name='website_automation_mode').drop(op.get_bind(), checkfirst=True)
