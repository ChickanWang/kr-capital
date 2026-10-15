"""Notes can be edited and deleted by their author; record when one was last edited.

Notes are the user's own commentary, not market data, so unlike prices and reference data they are
not versioned: an edit replaces the text, and `edited_at` marks that it happened.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE note ADD COLUMN edited_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE note DROP COLUMN edited_at")
