import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.providers.base import DataNotAvailable, ProviderError
from app.providers.polygon import PolygonClient
from tests.conftest import FIXTURES


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def polygon_with(handler) -> PolygonClient:
    http = httpx.Client(base_url="https://polygon.test", transport=httpx.MockTransport(handler))
    return PolygonClient("key", calls_per_minute=10_000, http=http)


def test_polygon_ticker_details_normalizes_fields():
    client = polygon_with(lambda req: httpx.Response(200, json=load("polygon_ticker_details.json")))
    record = client.ticker_details("AAPL")
    assert record is not None
    assert record.currency == "USD"
    assert record.listing_status == "ACTIVE"
    assert record.shares_outstanding == 14_840_390_000
    assert record.figi == "BBG000B9XRY4"  # composite_figi
    assert record.homepage_url == "https://www.apple.com"
    assert record.total_employees == 161_000
    assert record.list_date == date(1980, 12, 12)
    assert (record.hq_city, record.hq_state) == ("Cupertino", "CA")
    assert record.description and record.description.startswith("Apple designs")


def test_polygon_daily_bars_use_new_york_trade_date():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"], seen["params"] = req.url.path, dict(req.url.params)
        return httpx.Response(200, json=load("polygon_aggs.json"))

    bars = polygon_with(handler).daily_bars("AAPL", date(2025, 10, 13), date(2025, 10, 14))
    assert seen["path"] == "/v2/aggs/ticker/AAPL/range/1/day/2025-10-13/2025-10-14"
    assert seen["params"]["adjusted"] == "true"
    assert [b.trade_date for b in bars] == [date(2025, 10, 13), date(2025, 10, 14)]
    assert bars[0].close == Decimal("227.5") and bars[1].volume == 48_765_432


def test_polygon_grouped_daily_keys_by_ticker():
    client = polygon_with(lambda req: httpx.Response(200, json=load("polygon_grouped.json")))
    grouped = client.grouped_daily(date(2025, 10, 13))
    assert set(grouped) == {"AAPL", "BRK.B"}
    assert grouped["BRK.B"].trade_date == date(2025, 10, 13)


def test_polygon_404_is_none_and_errors_are_provider_errors():
    assert polygon_with(lambda req: httpx.Response(404)).ticker_details("NOPE") is None
    with pytest.raises(ProviderError):
        polygon_with(lambda req: httpx.Response(403)).ticker_details("AAPL")
    with pytest.raises(ProviderError, match="POLYGON_API_KEY"):
        PolygonClient("").ticker_details("AAPL")


def test_polygon_sends_the_key_in_a_header_not_the_url():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, json=load("polygon_ticker_details.json"))

    polygon_with(handler).ticker_details("AAPL")
    assert "key" not in seen["url"].lower()
    assert seen["auth"] == "Bearer key"


def test_polygon_403_means_not_available_yet_rather_than_an_outage():
    client = polygon_with(lambda req: httpx.Response(403, json={"status": "NOT_AUTHORIZED"}))
    with pytest.raises(DataNotAvailable) as raised:
        client.grouped_daily(date(2026, 10, 15))
    assert isinstance(raised.value, ProviderError)  # still caught wherever ProviderError is
    with pytest.raises(ProviderError) as other:
        polygon_with(lambda req: httpx.Response(401)).grouped_daily(date(2026, 10, 15))
    assert not isinstance(other.value, DataNotAvailable)
