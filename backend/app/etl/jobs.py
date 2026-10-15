"""ETL jobs. Each is idempotent: re-running converges on the same state."""

import csv
import gzip
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal, engine
from app.models import InstrumentDailyPrice, InstrumentMetadata
from app.providers.base import DataNotAvailable, ProviderError
from app.providers.polygon import PolygonClient
from app.services import calendar
from app.services.jobs import track_job
from app.services.prices import history_start, latest_stored_date, store_bars
from app.services.versioning import apply_metadata, current_tickers, resolve

log = logging.getLogger(__name__)

# Seed tables in foreign-key order. Workspace data (baskets, annotations) is never seeded.
SEED_TABLES = ["instrument_metadata", "instrument_daily_price"]


def load_universe(path: Path) -> list[str]:
    with path.open() as f:
        return [row["ticker"].strip() for row in csv.DictReader(f)]


def _polygon() -> PolygonClient:
    return PolygonClient(
        settings.polygon_api_key, settings.polygon_base_url, settings.polygon_calls_per_minute
    )


def _now() -> datetime:
    """The run's `data_version`. Each job calls this once at the start, so everything one run
    stores shares a single version timestamp."""
    return datetime.now(UTC)


def load(tickers: list[str] | None = None) -> None:
    """Full live load: reference data, then 2 years of prices, per ticker. 2 Polygon calls per
    ticker: about 40 minutes for the S&P 100 on the free tier."""
    universe = load_universe(settings.universe_file)
    tickers = [t for t in universe if t in tickers] if tickers else universe
    polygon = _polygon()
    now = _now()
    end = calendar.last_complete_session(now)
    start = history_start(end, settings.history_years)

    with track_job(SessionLocal, "load", {"tickers": len(tickers)}) as progress:
        for i, ticker in enumerate(tickers, 1):
            log.info("load %s (%d/%d)", ticker, i, len(tickers))
            try:
                record = polygon.ticker_details(ticker)
                if record is None:
                    log.warning("load: %s not found upstream; skipped", ticker)
                    continue
                with SessionLocal() as s:
                    iid = resolve(s, record, now)
                    bars = polygon.daily_bars(ticker, start, end)
                    progress.rows_written += store_bars(s, iid, bars, now)
                    s.commit()
            except ProviderError as exc:
                log.warning("load: %s failed (%s); skipped, re-run load to retry", ticker, exc)


def prices() -> None:
    """Nightly full refresh: re-fetch every stock's 2-year history (one call per stock, ~20 minutes
    on the free tier) and store a new version of any bar that changed. A split rescales a stock's
    whole history, so it shows up here as new versions of its past bars; the old ones are kept."""
    polygon = _polygon()
    now = _now()
    end = calendar.last_complete_session(now)
    start = history_start(end, settings.history_years)
    failed = []
    with track_job(SessionLocal, "prices") as progress, SessionLocal() as s:
        for ticker, iid in current_tickers(s).items():
            try:
                bars = polygon.daily_bars(ticker, start, end)
            except ProviderError as exc:
                log.warning("prices: %s failed (%s)", ticker, exc)
                failed.append(ticker)
                continue
            progress.rows_written += store_bars(s, iid, bars, now)
            s.commit()
        if failed:  # the job is recorded as FAILED; everything else was still stored
            raise RuntimeError(f"prices: {len(failed)} tickers failed: {', '.join(failed)}")


def topup() -> None:
    """Fast catch-up for startup: fetch only the trading days missing since the latest stored bar,
    one grouped-daily call per day for all stocks at once. The free plan doesn't serve a day's bars
    until just after midnight New York time, so when a day is refused the catch-up stops there
    (later days would be refused too) and the next run picks it up."""
    polygon = _polygon()
    now = _now()
    with track_job(SessionLocal, "topup") as progress, SessionLocal() as s:
        last = latest_stored_date(s)
        if last is None:
            raise RuntimeError("no prices stored yet; run `load` or `bootstrap` first")
        tickers = current_tickers(s)
        end = calendar.last_complete_session(now)
        for day in [d for d in calendar.sessions(last, end) if d > last]:
            try:
                grouped = polygon.grouped_daily(day)
            except DataNotAvailable as exc:
                log.info("topup stopped at %s: %s", day, exc)
                break
            written = sum(
                store_bars(s, iid, [grouped[t]], now) for t, iid in tickers.items() if t in grouped
            )
            log.info("topup %s: %d bars", day, written)
            progress.rows_written += written
            s.commit()


def reference() -> None:
    """Re-fetch reference data for every instrument; store a new version where anything changed."""
    polygon = _polygon()
    now = _now()
    with track_job(SessionLocal, "reference") as progress, SessionLocal() as s:
        for ticker, iid in current_tickers(s).items():
            record = polygon.ticker_details(ticker)
            if record is None:
                log.warning("reference: %s not found upstream", ticker)
                continue
            if apply_metadata(s, iid, record, now):
                progress.rows_written += 1
            s.commit()


def bootstrap() -> None:
    """Startup: restore the committed seed if the database is empty (or do a live load if there is
    no seed), then top up the days missing since. Fast: the full refresh is left to the nightly
    `prices` job."""
    with SessionLocal() as s:
        empty = s.scalar(select(func.count()).select_from(InstrumentMetadata)) == 0
    if empty and (settings.seed_dir / "instrument_metadata.csv.gz").exists():
        restore_seed()
    elif empty:
        if not settings.polygon_api_key:
            log.error("empty database, no seed snapshot and no POLYGON_API_KEY: nothing to load")
            return
        load()
        return
    if settings.polygon_api_key:
        topup()
    else:
        log.warning("POLYGON_API_KEY not set; skipping the price top-up")


def dump_seed() -> None:
    settings.seed_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        for table in SEED_TABLES:
            path = settings.seed_dir / f"{table}.csv.gz"
            with (
                gzip.open(path, "wb") as out,
                cursor.copy(f"COPY {table} TO STDOUT WITH (FORMAT csv, HEADER true)") as copy,
            ):
                for chunk in copy:
                    out.write(chunk)
            log.info("wrote %s", path)


def restore_seed() -> None:
    with track_job(SessionLocal, "restore-seed"), engine.begin() as conn:
        cursor = conn.connection.cursor()
        for table in SEED_TABLES:
            path = settings.seed_dir / f"{table}.csv.gz"
            with (
                gzip.open(path, "rb") as src,
                cursor.copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as copy,
            ):
                while chunk := src.read(1 << 16):
                    copy.write(chunk)
            log.info("restored %s", table)
    with SessionLocal() as s:
        rows = s.scalar(select(func.count()).select_from(InstrumentDailyPrice))
    log.info("seed restored: %s price bars", rows)
