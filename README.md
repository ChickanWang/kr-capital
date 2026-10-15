# KR Capital – S&P 100 Watchlist & Screener

A watchlist and basic screener for the S&P 100: a sortable grid of the universe, price charts, company
cards with versioned reference data and annotations, and baskets / mock portfolios with return analytics.
FastAPI + Postgres backend, React + TypeScript frontend, Polygon.io as the only data source.

The full design log (schema, every decision, and what was tried and replaced) is in
[docs/design-decisions.md](docs/design-decisions.md).

## Run it

Requirements: Docker. A free [Polygon.io](https://polygon.io) API key is needed only to refresh data.

```bash
cp .env.example .env          # set POLYGON_API_KEY
docker compose up --build     # web :5173 · API :8000 (docs at /docs)
```

On first start `migrate` creates the schema and `etl` loads data: it restores the committed snapshot in
`seed/` (101 stocks, 2 years of closes through 2026-10-14, a few seconds), then tops up missing days if a
key is set. Without a key the app serves the snapshot as it is. With an empty `seed/` it falls back to a
full live load (~40 min on the free tier, 5 calls/min). `scheduler` runs the nightly jobs (06:00 ET, Tue–Sat).

```bash
docker compose run --rm etl python -m app.etl load [--tickers AAPL,MSFT]   # initial load
docker compose run --rm etl python -m app.etl prices | topup | reference   # nightly / catch-up jobs
docker compose run --rm etl python -m app.etl dump-seed                    # write seed/ from the DB
cd backend && uv sync && uv run pytest        # tests; needs `docker compose up -d db`
cd frontend && npm ci && npm run dev          # frontend outside Docker; `npm run gen:types` after API changes
```

## What it does

- **Grid:** ticker, name, last close, 1D / 1M / YTD return, market cap, annotation count; sort, filter,
  ★ to add to the active basket, ⓘ for details.
- **Chart:** price ($, $ log, YoY %), daily return or cumulative return; 1M to All; compare up to 5 stocks;
  dots mark dated annotations (click for the full text).
- **Company card:** overview, key figures, identifiers, change history ("as was"), annotations.
- **Baskets:** named groups of stocks; add quantities and a basket becomes a portfolio with value, returns,
  volatility, drawdown, holdings, weights and per-stock contribution.

## Architecture

```
Polygon.io ──▶ ETL (CLI, run by cron) ──▶ Postgres ◀── FastAPI ◀── React (Vite, /api proxy)
                 load · prices · topup · reference        ▲
                 scheduler container: Supercronic ────────┘ job_run records every run
```

The API answers from Postgres. The one exception is on-demand gap filling: a chart request that finds
missing trading days fetches them from Polygon, stores them, then reads from the database.

## Data model

| Table | Holds |
|---|---|
| `instrument_metadata` | Per stock: UUID, ticker, FIGI, name, industry, shares, profile. Insert-only, versioned |
| `instrument_daily_price` | Split-adjusted daily bars. Insert-only, versioned |
| `basket`, `basket_member` | Named groups of stocks, with optional target quantities |
| `annotation` | A user's note on a stock, optionally dated; editable by its author |
| `job_run` | One row per ETL run |
| `instrument_snapshot` (view) | The grid's rows, computed on read |

Rows in the two versioned tables are never updated: a change inserts a new row stamped with `data_version`
(the start time of the ETL run). The latest row is "as is"; `?as_of=<date|timestamp>` on versions, prices
and portfolio returns reads the data "as was", so an analysis pinned to one `as_of` stays consistent.
`instrument_id` is a UUID, so a ticker change (FB → META) keeps its history; a FIGI can't belong to two
instruments (database constraint).

## API

`GET /instruments` · `/instruments/{ticker}` · `…/prices?start&end&mode&as_of` · `…/versions?as_of` ·
`…/annotations` (+ `PATCH`/`DELETE …/{id}`) · `/baskets` (+ members, `…/returns`) · `/jobs` · `/health`.
Spec in `backend/openapi.json`; the frontend's types are generated from it.

## Key decisions

- **One data source (Polygon).** An earlier multi-source build (OpenFIGI, yfinance fallback, intraday
  quotes) tripled the integration surface; Polygon's ticker details already include the FIGI.
- **Hybrid loading:** a one-off load, nightly refreshes, and on-demand gap fill. Pure ETL or pure on-the-fly
  each fail the screener (nothing new until the next run / an empty grid until each name is viewed).
- **Versioned, insert-only data** instead of a change-log table or a valid-to column: the versions are the
  audit trail, and a split shows up as new versions of past bars rather than rewritten history.
- **Split-adjusted prices only,** exclusive of dividends (price returns).
- **No live quotes.** The free plan is end-of-day and releases a day's bars just after midnight ET (the
  current day is refused with HTTP 403), so the app shows the last stored close, and the nightly jobs run
  at 06:00 ET Tue–Sat to store the previous day's close as early as the plan allows.
- **Fixed S&P 100 universe,** sized to the free tier (5 calls/min, 2 years of history).
- **Computed on read:** returns, portfolio values, market cap and the grid view; nothing derived is stored.
- **One basket model** for themes, watchlists and portfolios; quantities decide what the app can do.
- **Cron (Supercronic) over Airflow:** one daily chain doesn't justify an orchestrator.

## Assumptions and known limitations

- Prices are the previous close, stored by the 06:00 ET run; the page loads data once, so refresh to see them.
- Polygon free tier: 5 calls/min and 2 years of history, so a split can't re-version bars older than that.
- Polygon is a single point of failure: the app keeps serving stored data, but nothing new arrives.
- No authentication: one mock user id is stamped on writes. ETL jobs are not prevented from overlapping.
- Industry is Polygon's SIC classification, not GICS sectors.

## How it was checked

- **41 backend tests** (pytest, real Postgres, Polygon fixtures): versioning and ticker rename/reuse, price
  versioning and splits, startup top-up and nightly refresh, returns and portfolio math, annotations, API.
- **Spot checks against hand calculation:** NVDA year-over-year (+21.35% = $228.52 ÷ $188.32 − 1), portfolio
  value against its holdings, and contributions summing to the portfolio's daily return.
- **CI** (GitHub Actions): ruff, mypy, pytest, migrations match the models, OpenAPI spec and generated
  frontend types up to date, frontend lint and build.
- **Gaps:** no frontend tests (the UI was checked by hand in the browser); prices were not cross-checked
  against a second source.

## Next steps

- A Polygon plan with intraday data for live prices; refresh the seed snapshot on a schedule.
- A second source as a backup; GICS sectors; an index benchmark for portfolios; a screen-wide "as of" picker.
- Authentication and per-user workspaces; an ETL lock; frontend tests; Redis/Celery or Airflow as jobs grow.
- Platform: treat instruments and prices as a shared service that portfolio, risk and research apps read by UUID.
