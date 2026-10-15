"""Tests run against a real Postgres (the schema relies on partial indexes, an EXCLUDE constraint
and a materialized view). Start one with `docker compose up -d db`; the suite creates and migrates
a separate `kr_test` database."""

import os
import uuid

TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg://kr:kr@localhost:5432/kr_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # must be set before `app` is imported

from collections.abc import Iterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.providers.base import ReferenceRecord  # noqa: E402
from app.services.versioning import resolve  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
TABLES = [
    "annotation",
    "basket_member",
    "basket",
    "instrument_daily_price",
    "instrument_metadata",
    "job_run",
]


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def make_instrument(session: Session, ticker: str, now: datetime | None = None) -> uuid.UUID:
    """Create an instrument with a first metadata row (FIGI derived from the ticker)."""
    iid = resolve(
        session,
        reference(ticker=ticker, figi=f"FIGI-{ticker}", name=ticker),
        now or datetime.now(UTC),
    )
    session.commit()
    return iid


def reference(**overrides: object) -> ReferenceRecord:
    fields: dict[str, object] = {
        "ticker": "AAPL",
        "figi": "BBG000B9XRY4",
        "name": "Apple Inc.",
        "sic_code": "3571",
        "sic_description": "ELECTRONIC COMPUTERS",
        "primary_exchange": "XNAS",
        "currency": "USD",
        "shares_outstanding": 15_000_000_000,
        "listing_status": "ACTIVE",
    }
    fields.update(overrides)
    return ReferenceRecord(**fields)  # type: ignore[arg-type]
