"""NYSE trading calendar: which dates should have a daily bar."""

from datetime import date, datetime

import exchange_calendars as xcals
import pandas as pd

# Built once at import: it is slow to construct and never changes while the process runs.
_XNYS = xcals.get_calendar("XNYS")


def sessions(start: date, end: date) -> list[date]:
    """Trading days in [start, end], clipped to the calendar's bounds."""
    cal = _XNYS
    lo = max(pd.Timestamp(start), cal.first_session)
    hi = min(pd.Timestamp(end), cal.last_session)
    if lo > hi:
        return []
    return [ts.date() for ts in cal.sessions_in_range(lo, hi)]


def last_complete_session(now: datetime) -> date:
    """Most recent session whose close has passed at `now` (a tz-aware datetime)."""
    cal = _XNYS
    ts = pd.Timestamp(now)
    today = ts.tz_convert(cal.tz).date()
    session = cal.date_to_session(pd.Timestamp(today), direction="previous")
    if cal.session_close(session) > ts:
        session = cal.previous_session(session)
    return session.date()


def is_market_open(now: datetime) -> bool:
    return bool(_XNYS.is_open_on_minute(pd.Timestamp(now)))
