import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.main import app
from app.providers.base import Bar
from app.services.prices import GapFiller, store_bars
from app.services.versioning import apply_metadata, resolve
from tests.conftest import reference

T0 = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
DAYS = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]


class NoUpstream:
    def daily_bars(self, ticker, start, end):
        return []


@pytest.fixture
def client():
    app.dependency_overrides[deps.gap_filler] = lambda: GapFiller(NoUpstream(), 0)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def metadata(ticker, name):
    return reference(ticker=ticker, figi=f"FIGI-{ticker}", name=name)


@pytest.fixture
def universe(session):
    """AAPL with prices and two metadata versions; MSFT with prices."""
    ids = {}
    for ticker, closes in {"AAPL": ["100", "110", "99"], "MSFT": ["200", "200", "220"]}.items():
        iid = resolve(session, metadata(ticker, f"{ticker} old"), T0)
        store_bars(
            session,
            iid,
            [
                Bar(d, Decimal(c), Decimal(c), Decimal(c), Decimal(c), 10)
                for d, c in zip(DAYS, closes, strict=True)
            ],
            T0,
        )
        ids[ticker] = iid
    apply_metadata(session, ids["AAPL"], metadata("AAPL", "AAPL new"), T1)
    session.commit()
    return ids


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_grid_lists_snapshot_rows(client, universe):
    rows = {r["ticker"]: r for r in client.get("/instruments").json()}
    assert set(rows) == {"AAPL", "MSFT"}
    assert rows["AAPL"]["last_price"] == 99.0
    assert rows["AAPL"]["ret_1d"] == pytest.approx(-0.1)
    assert rows["AAPL"]["as_of"] == "2026-01-07"
    assert rows["AAPL"]["name"] == "AAPL new"
    assert rows["MSFT"]["market_cap"] == pytest.approx(220 * 15_000_000_000)


def test_prices_modes(client, universe):
    params = {"start": "2026-01-05", "end": "2026-01-07"}
    price = client.get("/instruments/AAPL/prices", params=params).json()
    assert [p["value"] for p in price["points"]] == [100.0, 110.0, 99.0]
    daily = client.get("/instruments/aapl/prices", params={**params, "mode": "daily"}).json()
    assert [p["value"] for p in daily["points"]] == pytest.approx([0.1, -0.1])
    cum = client.get("/instruments/AAPL/prices", params={**params, "mode": "cumulative"}).json()
    assert cum["points"][-1]["value"] == pytest.approx(-0.01)


def test_reference_history_as_is_and_as_was(client, universe):
    current = client.get("/instruments/AAPL").json()
    assert (current["name"], current["figi"]) == ("AAPL new", "FIGI-AAPL")
    assert current["instrument_id"] == str(universe["AAPL"])
    as_was = client.get(
        "/instruments/AAPL/versions", params={"as_of": (T0 + timedelta(hours=1)).isoformat()}
    ).json()
    assert [v["name"] for v in as_was] == ["AAPL old"]
    assert len(client.get("/instruments/AAPL/versions").json()) == 2


def test_notes_are_attributed_and_newest_first(client, universe):
    client.post("/instruments/AAPL/annotations", json={"body": "first"})
    client.post(
        "/instruments/AAPL/annotations", json={"body": "second"}, headers={"X-User-Id": "pm"}
    )
    annotations = client.get("/instruments/AAPL/annotations").json()
    assert [(n["body"], n["author"]) for n in annotations] == [
        ("second", "pm"),
        ("first", "analyst"),
    ]
    assert client.post("/instruments/AAPL/annotations", json={"body": ""}).status_code == 422


def test_basket_membership(client, universe):
    basket = client.post("/baskets", json={"name": "AI"}).json()
    url = f"/baskets/{basket['id']}/members"
    added = client.post(url, json={"ticker": "AAPL"})
    assert added.status_code == 201
    assert added.json()["instrument_id"] == str(universe["AAPL"])
    assert client.post(url, json={"ticker": "NOPE"}).status_code == 404
    assert client.post("/baskets", json={"name": "AI"}).status_code == 409
    client.delete(f"{url}/AAPL")
    assert client.get(f"/baskets/{basket['id']}").json()["members"] == []


def test_portfolio_returns(client, universe):
    basket = client.post("/baskets", json={"name": "Book"}).json()
    url = f"/baskets/{basket['id']}/members"
    returns_url = f"/baskets/{basket['id']}/returns"
    params = {"start": "2026-01-05", "end": "2026-01-07"}
    assert client.get(returns_url, params=params).status_code == 422  # no members yet
    client.post(url, json={"ticker": "AAPL"})
    assert client.get(returns_url, params=params).status_code == 422  # AAPL has no quantity
    client.post(url, json={"ticker": "AAPL", "target_quantity": 10})  # updates the member
    client.post(url, json={"ticker": "MSFT", "target_quantity": 5})

    points = client.get(returns_url, params=params).json()
    # 10 x (100, 110, 99) + 5 x (200, 200, 220) = 2000, 2100, 2090
    assert [p["value"] for p in points] == [2000.0, 2100.0, 2090.0]
    assert points[0]["daily_return"] is None
    assert points[-1]["cumulative_return"] == pytest.approx(0.045)


def test_unknown_tickers_and_baskets_are_404(client):
    assert client.get("/instruments/NOPE").status_code == 404
    assert client.get("/instruments/NOPE/prices").status_code == 404
    assert client.get(f"/baskets/{uuid.uuid4()}").status_code == 404
    assert client.get("/baskets/not-a-uuid").status_code == 422


def test_as_of_accepts_a_date_meaning_end_of_that_day_in_new_york(client, universe):
    # T0 = 2026-01-05 22:00 UTC (17:00 in New York); T1 is the next day.
    assert [v["name"] for v in versions(client, "2026-01-05")] == ["AAPL old"]
    assert [v["name"] for v in versions(client, "2026-01-06")] == ["AAPL new"]
    assert versions(client, "2026-01-04") == []
    assert client.get("/instruments/AAPL/versions", params={"as_of": "soon"}).status_code == 422


def test_prices_as_of_reads_the_version_stored_then(client, universe, session):
    # A later version of AAPL's first bar, e.g. history rescaled the next day.
    c = Decimal("50")
    store_bars(session, universe["AAPL"], [Bar(DAYS[0], c, c, c, c, 10)], T1)
    session.commit()
    params = {"start": "2026-01-05", "end": "2026-01-07"}

    latest = client.get("/instruments/AAPL/prices", params=params).json()
    assert [p["value"] for p in latest["points"]] == [50.0, 110.0, 99.0]
    as_was = client.get("/instruments/AAPL/prices", params={**params, "as_of": "2026-01-05"}).json()
    assert [p["value"] for p in as_was["points"]] == [100.0, 110.0, 99.0]


def versions(client, as_of):
    return client.get("/instruments/AAPL/versions", params={"as_of": as_of}).json()


def test_dated_notes_and_annotation_counts(client, universe):
    created = client.post(
        "/instruments/AAPL/annotations",
        json={"body": "Q4 earnings beat", "annotation_date": "2026-01-06"},
    )
    assert created.status_code == 201
    assert created.json()["annotation_date"] == "2026-01-06"
    client.post("/instruments/AAPL/annotations", json={"body": "undated thought"})
    annotations = client.get("/instruments/AAPL/annotations").json()
    assert [n["annotation_date"] for n in annotations] == [None, "2026-01-06"]
    counts = {r["ticker"]: r["annotation_count"] for r in client.get("/instruments").json()}
    assert counts == {"AAPL": 2, "MSFT": 0}


def test_metadata_includes_company_profile(client, session):
    from tests.conftest import reference

    resolve(
        session,
        reference(
            ticker="ACME",
            figi="FIGI-ACME",
            description="Makes anvils.",
            homepage_url="https://acme.test",
            total_employees=42,
            list_date=date(1999, 1, 4),
            hq_city="Phoenix",
            hq_state="AZ",
        ),
        T0,
    )
    session.commit()
    m = client.get("/instruments/ACME").json()
    assert (m["description"], m["total_employees"], m["list_date"], m["hq_city"]) == (
        "Makes anvils.",
        42,
        "1999-01-04",
        "Phoenix",
    )


def test_authors_can_edit_and_delete_their_own_annotations(client, universe):
    annotation = client.post(
        "/instruments/AAPL/annotations",
        json={"body": "frist draft", "annotation_date": "2026-01-06"},
    ).json()
    assert annotation["can_edit"] is True and annotation["edited_at"] is None
    url = f"/instruments/AAPL/annotations/{annotation['id']}"

    edited = client.patch(url, json={"body": "first draft"}).json()
    assert edited["body"] == "first draft"
    assert edited["annotation_date"] == "2026-01-06"  # untouched when not sent
    assert edited["edited_at"] is not None

    assert (
        client.patch(url, json={"annotation_date": None}).json()["annotation_date"] is None
    )  # cleared
    assert client.patch(url, json={"body": ""}).status_code == 422

    assert client.delete(url).status_code == 204
    assert client.get("/instruments/AAPL/annotations").json() == []
    assert client.delete(url).status_code == 404


def test_other_users_notes_are_read_only(client, universe):
    annotation = client.post(
        "/instruments/AAPL/annotations", json={"body": "mine"}, headers={"X-User-Id": "pm"}
    ).json()
    url = f"/instruments/AAPL/annotations/{annotation['id']}"

    as_analyst = client.get("/instruments/AAPL/annotations").json()[0]
    assert (as_analyst["author"], as_analyst["can_edit"]) == ("pm", False)
    assert client.patch(url, json={"body": "hijack"}).status_code == 403
    assert client.delete(url).status_code == 403
    assert client.get("/instruments/AAPL/annotations", headers={"X-User-Id": "pm"}).json()[0][
        "can_edit"
    ]
    assert client.get("/instruments/AAPL/annotations").json()[0]["body"] == "mine"


def test_a_note_cannot_be_changed_through_another_stock(client, universe):
    annotation = client.post("/instruments/AAPL/annotations", json={"body": "apple only"}).json()
    other = f"/instruments/MSFT/annotations/{annotation['id']}"
    assert client.patch(other, json={"body": "x"}).status_code == 404
    assert client.delete(other).status_code == 404
