"""Polygon.io (Massive) adapter: reference data and split-adjusted daily bars.

Free Stocks Basic tier: 5 calls/minute, 2 years of end-of-day history.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.base import Bar, DataNotAvailable, ProviderError, ReferenceRecord
from app.providers.ratelimit import RateLimiter, is_retryable

NEW_YORK = ZoneInfo("America/New_York")


class PolygonClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.polygon.io",
        calls_per_minute: int = 5,
        http: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        # The key goes in a header, not the URL: request URLs end up in logs, headers don't.
        self._http = http or httpx.Client(base_url=base_url, timeout=30)
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._limiter = RateLimiter(calls_per_minute, 60)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def ticker_details(self, ticker: str) -> ReferenceRecord | None:
        body = self._get(f"/v3/reference/tickers/{ticker}", {})
        if body is None:
            return None
        r = body.get("results") or {}
        shares = r.get("share_class_shares_outstanding")
        employees = r.get("total_employees")
        address = r.get("address") or {}
        return ReferenceRecord(
            ticker=r.get("ticker", ticker),
            figi=r.get("composite_figi"),
            name=r["name"],
            sic_code=r.get("sic_code"),
            sic_description=r.get("sic_description"),
            primary_exchange=r.get("primary_exchange"),
            currency=(r.get("currency_name") or "usd").upper(),
            shares_outstanding=int(shares) if shares else None,
            listing_status="ACTIVE" if r.get("active", True) else "DELISTED",
            description=r.get("description"),
            homepage_url=r.get("homepage_url"),
            total_employees=int(employees) if employees else None,
            list_date=date.fromisoformat(r["list_date"]) if r.get("list_date") else None,
            hq_city=_title(address.get("city")),
            hq_state=address.get("state"),
        )

    def daily_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        body = self._get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            {"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        if body is None:
            return []
        # `t` is the start of the daily window in Unix ms; its New York date is the trade date.
        return [
            _bar(datetime.fromtimestamp(row["t"] / 1000, tz=NEW_YORK).date(), row)
            for row in body.get("results") or []
        ]

    def grouped_daily(self, day: date) -> dict[str, Bar]:
        """Every US stock's bar for one day, in a single call."""
        body = self._get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}", {"adjusted": "true"}
        )
        if body is None:
            return {}
        return {row["T"]: _bar(day, row) for row in body.get("results") or []}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self._api_key:
            raise ProviderError("POLYGON_API_KEY is not set")
        try:
            return self._get_with_retry(path, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            if exc.response.status_code == 403:
                # The free plan serves a day's bars only from just after midnight New York time.
                raise DataNotAvailable(
                    f"polygon {path}: not available on this plan yet (HTTP 403)"
                ) from exc
            raise ProviderError(f"polygon {path}: HTTP {exc.response.status_code}") from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"polygon {path}: {exc}") from exc

    @retry(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=5, max=60),
        reraise=True,
    )
    def _get_with_retry(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._limiter.wait()
        response = self._http.get(path, params=params, headers=self._headers)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def _title(value: str | None) -> str | None:
    """Polygon returns cities in capitals (e.g. "SANTA CLARA")."""
    return value.title() if value else None


def _bar(day: date, row: dict[str, Any]) -> Bar:
    return Bar(
        trade_date=day,
        open=Decimal(str(row["o"])),
        high=Decimal(str(row["h"])),
        low=Decimal(str(row["l"])),
        close=Decimal(str(row["c"])),
        volume=int(round(row.get("v") or 0)),
    )
