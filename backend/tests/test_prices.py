from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models import InstrumentDailyPrice
from app.providers.base import Bar, ProviderError
from app.services.prices import GapFiller, current_closes, missing_sessions, store_bars
from tests.conftest import make_instrument

# Wed 2026-11-25, Thanksgiving Thu 11-26 (closed), Fri 11-27 (half day), Mon 11-30
WED, THU, FRI, MON = date(2026, 11, 25), date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30)
AFTER_MON_CLOSE = datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
V1 = datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
V2 = datetime(2026, 12, 1, 22, 0, tzinfo=UTC)


def bar(day: date, close: str) -> Bar:
    c = Decimal(close)
    return Bar(day, c, c, c, c, 1000)


def stored(session, iid):
    """Every stored version: (trade_date, close, data_version)."""
    rows = session.execute(
        select(
            InstrumentDailyPrice.trade_date,
            InstrumentDailyPrice.close,
            InstrumentDailyPrice.data_version,
        )
        .where(InstrumentDailyPrice.instrument_id == iid)
        .order_by(InstrumentDailyPrice.trade_date, InstrumentDailyPrice.data_version)
    ).all()
    return [(d, float(c), v) for d, c, v in rows]


def current(session, iid):
    return [(d, float(c)) for _, d, c in current_closes(session, [iid], WED, MON)]


class FakeSource:
    def __init__(self, bars=None, fail=False):
        self.bars, self.fail, self.calls = bars or [], fail, []

    def daily_bars(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if self.fail:
            raise ProviderError("down")
        return [b for b in self.bars if start <= b.trade_date <= end]


def test_unchanged_bars_are_not_stored_again(session):
    iid = make_instrument(session, "AAPL")
    assert store_bars(session, iid, [bar(WED, "100"), bar(FRI, "101")], V1) == 2
    assert store_bars(session, iid, [bar(WED, "100"), bar(FRI, "101")], V2) == 0
    session.commit()
    assert stored(session, iid) == [(WED, 100.0, V1), (FRI, 101.0, V1)]


def test_changed_bar_adds_a_version_and_keeps_the_old_one(session):
    """e.g. a split rescales history: the old version is kept, reads see the new one."""
    iid = make_instrument(session, "NVDA")
    store_bars(session, iid, [bar(WED, "1200"), bar(FRI, "1210")], V1)
    assert store_bars(session, iid, [bar(WED, "120"), bar(FRI, "121"), bar(MON, "122")], V2) == 3
    session.commit()

    assert stored(session, iid) == [
        (WED, 1200.0, V1),
        (WED, 120.0, V2),
        (FRI, 1210.0, V1),
        (FRI, 121.0, V2),
        (MON, 122.0, V2),
    ]
    assert current(session, iid) == [(WED, 120.0), (FRI, 121.0), (MON, 122.0)]


def test_missing_sessions_skips_holidays_and_unclosed_days(session):
    iid = make_instrument(session, "AAPL")
    store_bars(session, iid, [bar(WED, "100")], V1)
    session.commit()
    assert missing_sessions(session, iid, WED, MON, AFTER_MON_CLOSE) == [FRI, MON]
    monday_lunch = datetime(2026, 11, 30, 17, 0, tzinfo=UTC)
    assert missing_sessions(session, iid, WED, MON, monday_lunch) == [FRI]
    assert THU not in missing_sessions(session, iid, WED, MON, AFTER_MON_CLOSE)


def test_gap_filler_fetches_only_the_gap_and_respects_cooldown(session):
    iid = make_instrument(session, "AAPL")
    store_bars(session, iid, [bar(WED, "100")], V1)
    session.commit()
    primary = FakeSource([bar(WED, "100"), bar(FRI, "101"), bar(MON, "102")])
    filler = GapFiller(primary, cooldown=3600)

    assert filler.fill(session, iid, "AAPL", WED, MON, AFTER_MON_CLOSE, earliest=WED) == 2
    assert primary.calls == [("AAPL", FRI, MON)]
    session.execute(
        InstrumentDailyPrice.__table__.delete().where(InstrumentDailyPrice.trade_date == MON)
    )
    session.commit()
    assert filler.fill(session, iid, "AAPL", WED, MON, AFTER_MON_CLOSE, earliest=WED) == 0
    assert len(primary.calls) == 1  # still cooling down


def test_gap_filler_swallows_provider_failure(session):
    iid = make_instrument(session, "AAPL")
    filler = GapFiller(FakeSource(fail=True), cooldown=0)
    assert filler.fill(session, iid, "AAPL", WED, MON, AFTER_MON_CLOSE, earliest=WED) == 0


def test_gap_filler_first_attempt_runs_even_just_after_boot(session, monkeypatch):
    """time.monotonic() starts near zero in a fresh container; that must not look like a
    recent attempt."""
    monkeypatch.setattr("app.services.prices.time.monotonic", lambda: 5.0)
    iid = make_instrument(session, "AAPL")
    filler = GapFiller(FakeSource([bar(MON, "1")]), cooldown=900)
    assert filler.fill(session, iid, "AAPL", MON, MON, AFTER_MON_CLOSE, earliest=WED) == 1
