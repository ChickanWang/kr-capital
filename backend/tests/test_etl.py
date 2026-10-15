"""ETL price jobs with a fake Polygon: the startup `topup` and the nightly full `prices` refresh."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.etl import jobs
from app.models import InstrumentDailyPrice, JobRun
from app.providers.base import Bar, DataNotAvailable, ProviderError
from app.services.prices import current_closes, store_bars
from tests.conftest import make_instrument

THU, FRI, MON, TUE = date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 12), date(2026, 1, 13)
V0 = datetime(2026, 1, 9, 23, 0, tzinfo=UTC)
AFTER_TUE_CLOSE = datetime(2026, 1, 13, 23, 0, tzinfo=UTC)


def bar(day: date, close: str) -> Bar:
    c = Decimal(close)
    return Bar(day, c, c, c, c, 100)


class FakePolygon:
    """NVDA splits 10-for-1 effective Monday, so Polygon now returns its history divided by 10.
    AAPL is unchanged."""

    def __init__(self, failing=(), refused=(), broken=()):
        self.grouped_calls, self.history_calls, self.failing = [], [], failing
        self.refused, self.broken = refused, broken  # days refused by the plan / failing outright

    def grouped_daily(self, day):
        self.grouped_calls.append(day)
        if day in self.refused:
            raise DataNotAvailable("not available on this plan yet (HTTP 403)")
        if day in self.broken:
            raise ProviderError("polygon down")
        table = {
            MON: {"AAPL": bar(MON, "101"), "NVDA": bar(MON, "121")},
            TUE: {"AAPL": bar(TUE, "102"), "NVDA": bar(TUE, "122")},
        }
        return table.get(day, {})

    def daily_bars(self, ticker, start, end):
        self.history_calls.append(ticker)
        if ticker in self.failing:
            raise ProviderError("down")
        return {
            "AAPL": [bar(FRI, "100"), bar(MON, "101"), bar(TUE, "102")],
            "NVDA": [bar(THU, "119"), bar(FRI, "120"), bar(MON, "121"), bar(TUE, "122")],
        }[ticker]


@pytest.fixture
def stored_until_friday(session):
    """AAPL and NVDA (pre-split prices) stored up to Friday."""
    aapl, nvda = make_instrument(session, "AAPL"), make_instrument(session, "NVDA")
    store_bars(session, aapl, [bar(FRI, "100")], V0)
    store_bars(session, nvda, [bar(THU, "1190"), bar(FRI, "1200")], V0)
    session.commit()
    return aapl, nvda


def run(monkeypatch, job, fake):
    monkeypatch.setattr(jobs, "_polygon", lambda: fake)
    monkeypatch.setattr(jobs, "_now", lambda: AFTER_TUE_CLOSE)
    job()


def closes(session, iid):
    session.expire_all()
    return [(d, float(c)) for _, d, c in current_closes(session, [iid], THU, TUE)]


def versions(session, iid):
    return session.scalar(select(func.count()).where(InstrumentDailyPrice.instrument_id == iid))


def test_topup_fetches_only_missing_days_one_call_each(session, monkeypatch, stored_until_friday):
    aapl, nvda = stored_until_friday
    fake = FakePolygon()
    run(monkeypatch, jobs.topup, fake)

    assert fake.grouped_calls == [MON, TUE]
    assert fake.history_calls == []
    assert closes(session, aapl) == [(FRI, 100.0), (MON, 101.0), (TUE, 102.0)]
    job = session.scalars(select(JobRun)).one()
    assert (job.job, job.status, job.rows_written) == ("topup", "SUCCEEDED", 4)


def test_full_refresh_versions_split_history_and_keeps_old_versions(
    session, monkeypatch, stored_until_friday
):
    aapl, nvda = stored_until_friday
    run(monkeypatch, jobs.prices, FakePolygon())

    # NVDA's rescaled history becomes the current version; the pre-split bars are kept.
    assert closes(session, nvda) == [(THU, 119.0), (FRI, 120.0), (MON, 121.0), (TUE, 122.0)]
    assert versions(session, nvda) == 6  # 2 pre-split + 4 new
    # AAPL's Friday bar didn't change, so it isn't stored again.
    assert closes(session, aapl) == [(FRI, 100.0), (MON, 101.0), (TUE, 102.0)]
    assert versions(session, aapl) == 3
    job = session.scalars(select(JobRun)).one()
    assert (job.status, job.rows_written) == ("SUCCEEDED", 6)


def test_full_refresh_stores_what_it_can_and_records_failure(
    session, monkeypatch, stored_until_friday
):
    aapl, nvda = stored_until_friday
    with pytest.raises(RuntimeError, match="NVDA"):
        run(monkeypatch, jobs.prices, FakePolygon(failing={"NVDA"}))

    assert closes(session, aapl) == [(FRI, 100.0), (MON, 101.0), (TUE, 102.0)]
    assert closes(session, nvda) == [(THU, 1190.0), (FRI, 1200.0)]
    assert session.scalars(select(JobRun)).one().status == "FAILED"


def test_topup_stops_at_a_day_the_plan_does_not_serve_yet(
    session, monkeypatch, stored_until_friday
):
    """The free plan refuses the latest day: keep what came before and finish cleanly, so the next
    run picks the refused day up."""
    aapl, _ = stored_until_friday
    fake = FakePolygon(refused={TUE})
    run(monkeypatch, jobs.topup, fake)

    assert fake.grouped_calls == [MON, TUE]
    assert closes(session, aapl) == [(FRI, 100.0), (MON, 101.0)]  # Tuesday not stored yet
    job = session.scalars(select(JobRun)).one()
    assert (job.status, job.rows_written) == ("SUCCEEDED", 2)


def test_topup_still_fails_on_a_real_outage(session, monkeypatch, stored_until_friday):
    with pytest.raises(ProviderError):
        run(monkeypatch, jobs.topup, FakePolygon(broken={MON}))
    assert session.scalars(select(JobRun)).one().status == "FAILED"
