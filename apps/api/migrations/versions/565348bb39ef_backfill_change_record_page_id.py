"""backfill_change_record_page_id

Revision ID: 565348bb39ef
Revises: f3c93aa152ee
Create Date: 2026-11-18 20:06:23.497290

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '565348bb39ef'
down_revision: Union[str, None] = 'f3c93aa152ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Change records were written without their page. Fill it in from the task's opportunity so per-page fix history,
    # progress counts and measurement see them. Rows that cannot be resolved stay NULL (nothing is invented).
    op.execute("""
        UPDATE change_records AS c
        SET page_id = o.page_id
        FROM seo_tasks AS t
        JOIN seo_opportunities AS o ON o.id = t.opportunity_id
        WHERE c.seo_task_id = t.id AND c.page_id IS NULL AND o.page_id IS NOT NULL
    """)


def downgrade() -> None:
    pass  # the filled-in page links are correct data; there is nothing to undo
