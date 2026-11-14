"""add auto_merged_at to change_records

Revision ID: a1f3c9d02b4e
Revises: 78d1e92686b2
Create Date: 2026-11-14 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d02b4e'
down_revision: Union[str, None] = '78d1e92686b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'change_records', sa.Column('auto_merged_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('change_records', 'auto_merged_at')
