"""drop catalog active flags

The import now deletes rows the source no longer has instead of flagging them, so rows still
flagged inactive are removed first.

Revision ID: 575f9cbe59da
Revises: 9eaf69edda9d
Create Date: 2026-11-04 22:59:51.928490

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "575f9cbe59da"
down_revision: str | Sequence[str] | None = "9eaf69edda9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DELETE FROM section_professors WHERE section_id IN "
        "(SELECT id FROM sections WHERE NOT active) "
        "OR professor_id IN (SELECT id FROM professors WHERE NOT active)"
    )
    op.execute("DELETE FROM sections WHERE NOT active")
    op.execute(
        "DELETE FROM courses WHERE NOT active AND id NOT IN (SELECT course_id FROM sections)"
    )
    op.execute("DELETE FROM professors WHERE NOT active")
    op.drop_column("courses", "active")
    op.drop_column("professors", "active")
    op.drop_column("sections", "active")


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("sections", "professors", "courses"):
        op.add_column(
            table,
            sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        )
        op.alter_column(table, "active", server_default=None)
