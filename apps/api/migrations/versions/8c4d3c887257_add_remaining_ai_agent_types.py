"""add remaining AI agent types

Revision ID: 8c4d3c887257
Revises: 744a4f57936b
Create Date: 2026-11-02 09:50:35.734839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c4d3c887257'
down_revision: Union[str, None] = '744a4f57936b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic's autogenerate doesn't detect enum value additions; added by
    # hand (same pattern as 744a4f57936b).
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'post_change_qa'")
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'seo_strategy'")
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'internal_linking'")


def downgrade() -> None:
    # Not reverting: Postgres has no DROP VALUE for enums.
    pass
