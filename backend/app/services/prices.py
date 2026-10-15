"""Daily price storage and gap filling.

Bars are split-adjusted and versioned: rows are insert-only, and a new version of a day's bar is
added only when Polygon's values for it change (e.g. a split rescales history). The latest
`data_version` per (instrument, trade_date) is current. Nothing is updated or deleted.
"""

import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import InstrumentDailyPrice
from app.providers.base import Bar, PriceSource, ProviderError
from app.services import calendar

log = logging.getLogger(__name__)
VALUE_FIELDS = ("open", "high", "low", "close", "volume")


def current_prices() -> Select[InstrumentDailyPrice]:
    """The latest version of every stored bar. Add `.where(...)` to narrow it."""
    return (
        select(InstrumentDailyPrice)
        .ext(distinct_on(InstrumentDailyPrice.instrument_id, InstrumentDailyPrice.trade_date))
        .order_by(
            InstrumentDailyPrice.instrument_id,
            InstrumentDailyPrice.trade_date,
            InstrumentDailyPrice.data_version.desc(),
        )
    )


def current_closes(
    session: Session,
    instrument_ids: list[uuid.UUID],
    start: date,
    end: date,
    as_of: datetime | None = None,
) -> list[tuple[uuid.UUID, date, Decimal]]:
    """(instrument_id, trade_date, close) from the latest version of each bar, in date order.
    With `as_of`, only versions recorded at or before it are considered."""
    query = current_prices().where(
        InstrumentDailyPrice.instrument_id.in_(instrument_ids),
        InstrumentDailyPrice.trade_date.between(start, end),
    )
    if as_of is not None:
        query = query.where(InstrumentDailyPrice.data_version <= as_of)
    rows = session.scalars(query)
    return [(r.instrument_id, r.trade_date, r.close) for r in rows]


def store_bars(session: Session, instrument_id: uuid.UUID, bars: list[Bar], now: datetime) -> int:
    """Store bars as new versions where they are new or differ from the current version.
    Returns how many versions were written."""
    if not bars:
        return 0
    dates = [b.trade_date for b in bars]
    current = {
        row.trade_date: row
        for row in session.scalars(
            current_prices().where(
                InstrumentDailyPrice.instrument_id == instrument_id,
                InstrumentDailyPrice.trade_date.between(min(dates), max(dates)),
            )
        )
    }
    new_rows = [
        InstrumentDailyPrice(
            instrument_id=instrument_id,
            trade_date=b.trade_date,
            data_version=now,
            **{field: getattr(b, field) for field in VALUE_FIELDS},
        )
        for b in bars
        if b.trade_date not in current or _differs(current[b.trade_date], b)
    ]
    session.add_all(new_rows)
    session.flush()
    return len(new_rows)


def _differs(row: InstrumentDailyPrice, bar: Bar) -> bool:
    return any(Decimal(getattr(row, f)) != Decimal(getattr(bar, f)) for f in VALUE_FIELDS)


def stored_dates(session: Session, instrument_id: uuid.UUID, start: date, end: date) -> set[date]:
    return set(
        session.scalars(
            select(InstrumentDailyPrice.trade_date).where(
                InstrumentDailyPrice.instrument_id == instrument_id,
                InstrumentDailyPrice.trade_date.between(start, end),
            )
        )
    )


def missing_sessions(
    session: Session, instrument_id: uuid.UUID, start: date, end: date, now: datetime
) -> list[date]:
    """Trading days in [start, end] with no stored bar, ignoring days not yet closed."""
    end = min(end, calendar.last_complete_session(now))
    have = stored_dates(session, instrument_id, start, end)
    return [d for d in calendar.sessions(start, end) if d not in have]


class GapFiller:
    """Fills missing days on read. A per-instrument cooldown stops a not-yet-published bar from
    triggering an upstream call on every request."""

    def __init__(self, source: PriceSource, cooldown: float) -> None:
        self._source = source
        self._cooldown = cooldown
        self._last_attempt: dict[uuid.UUID, float] = {}
        self._lock = threading.Lock()

    def fill(
        self,
        session: Session,
        instrument_id: uuid.UUID,
        ticker: str,
        start: date,
        end: date,
        now: datetime,
        earliest: date,
    ) -> int:
        start = max(start, earliest)  # the free tier only has ~2 years of history
        if start > end:
            return 0
        gaps = missing_sessions(session, instrument_id, start, end, now)
        if not gaps:
            return 0
        with self._lock:
            last = self._last_attempt.get(instrument_id)
            if last is not None and time.monotonic() - last < self._cooldown:
                return 0
            self._last_attempt[instrument_id] = time.monotonic()
        try:
            bars = self._source.daily_bars(ticker, gaps[0], gaps[-1])
        except ProviderError as exc:
            log.warning("gap fill failed for %s: %s", ticker, exc)
            return 0
        written = store_bars(session, instrument_id, bars, now)
        session.commit()
        return written


def latest_stored_date(session: Session) -> date | None:
    return session.scalar(select(func.max(InstrumentDailyPrice.trade_date)))


def history_start(today: date, years: int) -> date:
    return today - timedelta(days=365 * years)
