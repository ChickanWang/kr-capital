"""Normalized shapes every provider adapter returns. Nothing outside `app.providers` sees a
provider's own response format."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class ProviderError(Exception):
    """An upstream call failed after retries (or returned something unusable)."""


class DataNotAvailable(ProviderError):
    """The provider refuses this data for the current plan, e.g. the free tier's most recent day.
    Unlike an outage this is expected, and later calls will succeed once the data is released."""


@dataclass(frozen=True)
class Bar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class ReferenceRecord:
    """Slowly changing attributes for one instrument, as of the fetch."""

    ticker: str
    figi: str | None
    name: str
    sic_code: str | None
    sic_description: str | None
    primary_exchange: str | None
    currency: str
    shares_outstanding: int | None
    listing_status: str
    description: str | None = None
    homepage_url: str | None = None
    total_employees: int | None = None
    list_date: date | None = None
    hq_city: str | None = None
    hq_state: str | None = None

    def attributes(self) -> dict[str, str | int | date | None]:
        """Every versioned field of an `instrument_metadata` row."""
        return {
            "ticker": self.ticker,
            "figi": self.figi,
            "name": self.name,
            "sic_code": self.sic_code,
            "sic_description": self.sic_description,
            "primary_exchange": self.primary_exchange,
            "currency": self.currency,
            "shares_outstanding": self.shares_outstanding,
            "listing_status": self.listing_status,
            "description": self.description,
            "homepage_url": self.homepage_url,
            "total_employees": self.total_employees,
            "list_date": self.list_date,
            "hq_city": self.hq_city,
            "hq_state": self.hq_state,
        }


class PriceSource(Protocol):
    def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]: ...
