"""Company profile fields on instrument_metadata, and an optional date on notes.

The profile fields come from the same Polygon ticker-details call as the existing metadata and are
versioned like it. Existing rows get NULLs; the next reference run fills them in as a new version.
A note's `note_date` is the day it refers to (e.g. an earnings date).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_COLUMNS = [
    ("description", "TEXT"),
    ("homepage_url", "TEXT"),
    ("total_employees", "INTEGER"),
    ("list_date", "DATE"),
    ("hq_city", "TEXT"),
    ("hq_state", "TEXT"),
]


def upgrade() -> None:
    for name, sql_type in PROFILE_COLUMNS:
        op.execute(f"ALTER TABLE instrument_metadata ADD COLUMN {name} {sql_type}")
    op.execute("ALTER TABLE note ADD COLUMN note_date DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE note DROP COLUMN note_date")
    for name, _ in reversed(PROFILE_COLUMNS):
        op.execute(f"ALTER TABLE instrument_metadata DROP COLUMN {name}")
