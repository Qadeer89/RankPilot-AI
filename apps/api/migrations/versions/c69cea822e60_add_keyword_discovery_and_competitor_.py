"""add keyword_discovery and competitor_content_analysis agent types

Revision ID: c69cea822e60
Revises: 8d3a0fdcddae
Create Date: 2026-11-15 21:39:38.213559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c69cea822e60'
down_revision: Union[str, None] = '8d3a0fdcddae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic's autogenerate doesn't detect enum value additions; added by
    # hand (same pattern as 8c4d3c887257).
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'keyword_discovery'")
    op.execute("ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'competitor_content_analysis'")


def downgrade() -> None:
    # Not reverting: Postgres has no DROP VALUE for enums.
    pass
