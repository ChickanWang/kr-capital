"""Rename note to annotation.

A note on a stock is an annotation: the user's own commentary attached to a security. Renames the
table, its date column, and its constraint and index names in place, so existing rows are kept.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE note RENAME TO annotation")
    op.execute("ALTER TABLE annotation RENAME COLUMN note_date TO annotation_date")
    op.execute("ALTER TABLE annotation RENAME CONSTRAINT note_pkey TO annotation_pkey")
    op.execute("ALTER TABLE annotation RENAME CONSTRAINT ck_note_body TO ck_annotation_body")
    op.execute("ALTER INDEX ix_note_instrument_time RENAME TO ix_annotation_instrument_time")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_annotation_instrument_time RENAME TO ix_note_instrument_time")
    op.execute("ALTER TABLE annotation RENAME CONSTRAINT ck_annotation_body TO ck_note_body")
    op.execute("ALTER TABLE annotation RENAME CONSTRAINT annotation_pkey TO note_pkey")
    op.execute("ALTER TABLE annotation RENAME COLUMN annotation_date TO note_date")
    op.execute("ALTER TABLE annotation RENAME TO note")
