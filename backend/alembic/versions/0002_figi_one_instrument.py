"""A FIGI may belong to only one instrument.

instrument_metadata is versioned, so the same FIGI legitimately appears in many rows (every version
of a stock). What must never happen is the same FIGI under two different instrument_ids, e.g. two
loads racing to create the same stock. This exclusion constraint rejects a row whose FIGI is already
used by a *different* instrument_id. Rows without a FIGI (NULL) are not checked.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # btree_gist lets a GiST index compare plain values (text, uuid) with = and <>.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        "ALTER TABLE instrument_metadata ADD CONSTRAINT ex_metadata_figi_one_instrument "
        "EXCLUDE USING gist (figi WITH =, instrument_id WITH <>)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE instrument_metadata DROP CONSTRAINT ex_metadata_figi_one_instrument")
