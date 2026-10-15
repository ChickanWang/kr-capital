"""Reference-data versioning and change capture for `instrument_metadata`.

Rows are insert-only and stamped with `data_version`. The latest row per instrument is current
("as is"); the latest row at or before time T is what we knew at T ("as was"). A change inserts a
new row; nothing is updated or deleted. Comparing consecutive rows shows what changed.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import InstrumentMetadata
from app.providers.base import ReferenceRecord

Attributes = dict[str, str | int | date | None]
# The versioned fields of a row (everything except bookkeeping columns).
FIELDS = [
    "ticker",
    "figi",
    "name",
    "sic_code",
    "sic_description",
    "primary_exchange",
    "currency",
    "shares_outstanding",
    "listing_status",
    "description",
    "homepage_url",
    "total_employees",
    "list_date",
    "hq_city",
    "hq_state",
]


def current_metadata() -> Select[InstrumentMetadata]:
    """The latest row per instrument."""
    return (
        select(InstrumentMetadata)
        .ext(distinct_on(InstrumentMetadata.instrument_id))
        .order_by(InstrumentMetadata.instrument_id, InstrumentMetadata.data_version.desc())
    )


def current_version(session: Session, instrument_id: uuid.UUID) -> InstrumentMetadata | None:
    return session.scalar(
        select(InstrumentMetadata)
        .where(InstrumentMetadata.instrument_id == instrument_id)
        .order_by(InstrumentMetadata.data_version.desc())
        .limit(1)
    )


def version_as_of(
    session: Session, instrument_id: uuid.UUID, as_of: datetime
) -> InstrumentMetadata | None:
    return session.scalar(
        select(InstrumentMetadata)
        .where(
            InstrumentMetadata.instrument_id == instrument_id,
            InstrumentMetadata.data_version <= as_of,
        )
        .order_by(InstrumentMetadata.data_version.desc())
        .limit(1)
    )


def instrument_for_ticker(session: Session, ticker: str) -> uuid.UUID | None:
    """The instrument whose *current* ticker is `ticker`."""
    current = current_metadata().subquery()
    return session.scalar(select(current.c.instrument_id).where(current.c.ticker == ticker))


def instrument_for_figi(session: Session, figi: str) -> uuid.UUID | None:
    current = current_metadata().subquery()
    return session.scalar(select(current.c.instrument_id).where(current.c.figi == figi))


def current_tickers(session: Session) -> dict[str, uuid.UUID]:
    """{ticker: instrument_id} for every instrument that currently has a ticker."""
    current = current_metadata().subquery()
    rows = session.execute(
        select(current.c.ticker, current.c.instrument_id).where(current.c.ticker.is_not(None))
    )
    return {ticker: iid for ticker, iid in rows}


def resolve(session: Session, record: ReferenceRecord, now: datetime) -> uuid.UUID:
    """Find the instrument a fetched record belongs to, or create a new one, and record the data.

    Matching by FIGI first means a renamed ticker (FB -> META) keeps its instrument_id. The ticker
    is only used when FIGIs don't contradict it: a ticker held by a stock with a *different* FIGI
    has been reused by another company, so the record gets a new instrument."""
    instrument_id = record.figi and instrument_for_figi(session, record.figi)
    if not instrument_id:
        holder = instrument_for_ticker(session, record.ticker)
        if holder is not None:
            holder_row = current_version(session, holder)
            if record.figi is None or holder_row is None or holder_row.figi is None:
                instrument_id = holder
    instrument_id = instrument_id or uuid.uuid4()
    apply_metadata(session, instrument_id, record, now)
    return instrument_id


def apply_metadata(
    session: Session, instrument_id: uuid.UUID, record: ReferenceRecord, now: datetime
) -> bool:
    """Record a freshly fetched record. Inserts a new row only if something changed; returns
    whether it did."""
    attrs = record.attributes()
    current = current_version(session, instrument_id)
    if current is not None and all(_text(getattr(current, f)) == _text(attrs[f]) for f in FIELDS):
        return False
    _release_ticker(session, record.ticker, instrument_id, now)
    _insert(session, instrument_id, attrs, now)
    return True


def _release_ticker(session: Session, ticker: str, new_holder: uuid.UUID, now: datetime) -> None:
    """If another instrument currently has this ticker (a reused ticker), give it a new row
    without one."""
    holder = instrument_for_ticker(session, ticker)
    if holder is None or holder == new_holder:
        return
    old = current_version(session, holder)
    assert old is not None
    _insert(
        session, holder, {field: getattr(old, field) for field in FIELDS} | {"ticker": None}, now
    )


def _insert(
    session: Session, instrument_id: uuid.UUID, attrs: Attributes, now: datetime
) -> InstrumentMetadata:
    row = InstrumentMetadata(instrument_id=instrument_id, data_version=now, **attrs)
    session.add(row)
    session.flush()
    return row


def _text(value: object) -> str | None:
    return None if value is None else str(value)
