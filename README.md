# KR Capital – S&P 100 Watchlist & Screener

A watchlist and basic screener for the S&P 100: a sortable grid of the universe, price charts, company
cards with versioned reference data and annotations, and baskets / mock portfolios with return analytics.
FastAPI + Postgres backend, React + TypeScript frontend, Polygon.io as the only data source.

The case study writeup is in [docs/case-study-writeup.md](docs/case-study-writeup.md).

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

## API

Stocks are addressed by their current ticker. `as_of` takes a date (end of that day, New York time) or a
timestamp and reads the data as it was stored then.

| Method | Route | Purpose |
|---|---|---|
| GET | `/instruments` | The grid: one row per stock (last close, 1D / 1M / YTD return, market cap, annotation count) |
| GET | `/instruments/{ticker}` | Current details ("as is") |
| GET | `/instruments/{ticker}/versions?as_of` | Every reference-data version, oldest first; with `as_of`, the version current then ("as was") |
| GET | `/instruments/{ticker}/prices?start&end&mode&as_of` | Split-adjusted daily bars; `mode` = `price` (default), `daily` or `cumulative` returns. Missing days are fetched and stored first, unless `as_of` is given |
| GET | `/instruments/{ticker}/annotations` | Annotations, newest first |
| POST | `/instruments/{ticker}/annotations` | Add an annotation (optionally dated) |
| PATCH | `/instruments/{ticker}/annotations/{annotation_id}` | Edit your own annotation |
| DELETE | `/instruments/{ticker}/annotations/{annotation_id}` | Delete your own annotation |
| GET | `/baskets` | List baskets |
| POST | `/baskets` | Create a basket |
| GET | `/baskets/{basket_id}` | A basket and its members |
| DELETE | `/baskets/{basket_id}` | Delete a basket |
| POST | `/baskets/{basket_id}/members` | Add a stock, or update its `target_quantity` |
| DELETE | `/baskets/{basket_id}/members/{ticker}` | Remove a stock |
| GET | `/baskets/{basket_id}/returns?start&end&as_of` | Portfolio value and daily / cumulative returns (every member needs a quantity) |
| GET | `/jobs?limit` | Recent ETL runs (default 20) |
| GET | `/health` | Health check |

Interactive docs at `localhost:8000/docs`; spec in `backend/openapi.json`, from which the frontend's types
are generated.

