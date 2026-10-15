# Case study writeup
Link to [README](../README.md).

## What I built

A watchlist and screener for the S&P 100, running locally with one `docker compose up`:

- **Data layer:** Postgres with a permanent ID per stock and versioned prices and reference data, so
  anything can be read "as is" or "as was".
- **Pipeline:** an ETL CLI (load, nightly refresh, catch-up) run by a cron container, each run logged in
  `job_run`, plus on-demand gap filling when a chart finds missing days.
- **API:** FastAPI with a typed OpenAPI contract that generates the frontend's types.
- **App:** a sortable, filterable grid; charts comparing up to five stocks; company cards with change
  history and annotations; baskets that become portfolios once they have quantities, with value,
  returns, volatility, drawdown and a holdings screener.

## Tradeoffs

- **Where I went deep: data modelling.** It's the hardest part to change later. A model that overwrites
  prices or keys on tickers silently corrupts history the first time a stock splits or renames. Cost:
  more complex queries (latest version per row), more storage, more tests.
- **One data source (Polygon).** More sources mean more integration work and per-source lineage. The
  provider interface leaves room for a fallback source later.
- **No live prices:** the free plan is end-of-day only.
- **One default "analyst" user:** multiple users added little to the core product.

## Data Modelling

| Table | Key columns | Rules |
|---|---|---|
| `instrument_metadata` | instrument_id (UUID), ticker, figi, name, SIC industry, shares outstanding, profile fields, data_version | PK (instrument_id, data_version); a FIGI can't belong to two instruments; ticker NULL = taken over by another stock |
| `instrument_daily_price` | instrument_id, trade_date, data_version, split-adjusted OHLC, volume | PK (instrument_id, trade_date, data_version); new version only when Polygon's bar changes |
| `basket`, `basket_member` | name, owner; member with optional target_quantity | UNIQUE (owner, name) |
| `annotation` | instrument_id, author, body, optional date | editable and deletable by its author only |
| `job_run` | job, status, timings, rows_written, error | one row per ETL run |
| `instrument_snapshot` (view) | the grid's columns | computed on read |

**Identity.** Each stock has a permanent UUID; ticker and FIGI are versioned because they can change.
The ETL matches by FIGI, then ticker, so a rename keeps its UUID. If a ticker moves to another company,
the old holder's ticker becomes NULL.

### Versioned data ("as is" and "as was")

Both market-data tables work the same way: **rows are never updated or deleted; a change is a new row.**
Each ETL run stamps everything it writes with one `data_version` timestamp, so a run is one version
across all stocks and lines up with `job_run`. A row is inserted only when Polygon's data differs from
the current version: a changed name or share count for reference data, a changed open, high, low, close
or volume for prices. A normal night adds one bar per stock and rewrites nothing.

**Why.** The versions are the audit trail, with nothing separate to keep in sync (a change-log table was
built and removed for restating them). An earlier price design overwrote bars and guessed at splits; it
was replaced because it rewrote history. `data_version` is a timestamp so two runs on one day don't
collide.

**Limits.** `data_version` is when the app *recorded* a change, not when it happened; Polygon gives no
effective dates. The free plan's 2 years of bars caps how far back a split can re-version.

## Constraints

Polygon's free tier allows 5 calls/min, 2 years of history and end-of-day data only. A full S&P 100 load
is ~200 calls, about **40 minutes** (the S&P 500 would take 3.3 hours). So: a fixed S&P 100 universe,
everything stored permanently, only missing days fetched on startup, and full refreshes overnight.

## Data sourcing

- **Hybrid loading:** ETL preload, nightly refreshes and on-demand gap fill. Pure ETL shows nothing new
  until the next run; pure on-the-fly leaves the grid empty and has no history to compare against.
- **Schedule: 06:00 ET, Tue–Sat.** Polygon serves a day's bars only after midnight ET, so each run stores
  the previous day's close.
- **Cron (Supercronic) over Airflow:** one daily chain doesn't justify several more containers.

### First load: seed snapshot + top-up

Goal: `docker compose up` shows a full grid in seconds, even without a Polygon key.

- **Seed snapshot.** `seed/` holds a gzipped copy of the two market-data tables (~1 MB), restored into an
  empty database in a few seconds. `dump-seed` refreshes it.
- **Top-up.** Fetches only the trading days after the newest stored bar, one grouped-daily call per day
  for all stocks. It stops at the first day Polygon refuses and the next run picks it up.

**Alternatives considered.** A full `prices` refresh on startup takes ~20 minutes; filling only on
demand leaves the grid empty.

## Assumptions

- **Universe:** the S&P 100 as listed on Wikipedia (fetched 2026-10-14). Later index changes aren't
  picked up.
- **Returns are price returns,** split-adjusted but excluding dividends. Total return is a next step.
- **Market cap** is close × share-class shares outstanding, so GOOG and GOOGL each show their own class.
- **Industries** are Polygon's SIC codes, not GICS sectors.

## Product

- **Baskets.** Themes, watchlists and portfolios are all named groups in one table; a basket where every
  member has a quantity is a portfolio.
- **Holdings screener.** A portfolio's holdings are a grid of their own: sort or filter by industry,
  weight, returns or contribution, or search, and a running total shows what share of the portfolio and
  of today's return the filtered holdings are. Click a holding to open its company card.
- **Annotations.** Free text, optionally dated. Authors can edit or delete their own.
- **Analytics on request.** ~100 stocks × 500 days computes in milliseconds and is never stale.

## AI Usage

Before any code, I talked the design through with Claude: the data model, then the endpoints it needed,
then the frontend. The [grill-me](https://www.aihero.dev/skills-grill-me) skill helped here: it questions
you until the design holds up. The data model was settled before coding; the UI and some ETL details
changed as I used the app.

**How I divided the work.** I made the data-model and product decisions and reviewed every change. Claude
drafted code, tests and docs in small steps, so each change was small enough to review fully.

### AI log

First versions that review or testing caught, and what changed:

| First version | Problem found | Change |
|---|---|---|
| Change-log table and `/changes` endpoint | Restated what the versioned rows already show | Removed |
| Prices overwritten, splits detected from one day's close | Rewrote history, relied on a heuristic | Versioned bars |
| Nightly run at 17:00 on weekdays | Polygon serves a day's bars only after midnight, so the grid lagged a day | 06:00 Tue–Sat |
| Append-only annotations | Typos were permanent | Authors can edit and delete |
| "% change since range start" chart view | Easy to misread; duplicated cumulative return | Removed |
| Layout fix for a wide sidebar | Measuring in the browser showed it made the overflow worse | Fixed the column width at its cause |
| One ticked stock | The chart stayed empty (found in manual testing) | Ticking one stock charts it |

## Rubric for Success

To decide whether Claude's output was good enough, I checked two things:

- **The code reads like a PR I'd approve.** If I couldn't explain or justify a change, it went back.
- **The product works for someone using it.** Most UI changes came from using the app myself.

## How I tested

1. **Unit tests where errors would be silent:** versioning (renames, ticker reuse), splits, `topup`
   (including a refused day), gap detection, and returns and portfolio math.
2. **API tests against a real Postgres,** with Polygon faked from recorded fixtures, so constraints and
   SQL are exercised but tests never touch the network.
3. **Numbers checked by hand:** returns and portfolio figures recalculated and compared with the API.
4. **Bugs reproduced before fixing:** for UI bugs, measured in the browser before and after the fix.
5. **CI gates every push:** ruff, mypy, pytest, migration/model and OpenAPI/type drift checks, and the
   frontend lint and build.

The frontend has no automated tests; it was checked by hand.

## Data Validation

There's no automated scan of the stored data yet; it's the most important gap before production. Checks
the ETL could run after each job, flagging rows rather than blocking the load:

- **Price jumps:** a daily move over a threshold (e.g. 50%) that no split explains.
- **Bar sanity:** low ≤ open, close ≤ high; prices above zero; no zero volume on a trading day.
- **Gaps:** a stock missing a day the other stocks have (`topup` doesn't fill these).
- **Stale data:** the same close and volume for several days, usually a frozen feed.
- **Coverage:** every universe ticker has a current instrument row and recent prices.

## Next steps

- **Data validation** (above).
- **Coverage:** user-added tickers, the S&P 500 on a paid tier, dated index membership.
- **Data:** total return with dividends, live prices, a backup source, raw responses stored for lineage,
  and bitemporal history (when a change happened, not just when it was recorded).
- **Product:** a screen-wide "as of" picker, saved screens, authentication.
- **Infrastructure:** an ETL lock, progress logging in long jobs, Airflow as jobs grow, hosted Postgres,
  frontend tests.

## Growing into a platform

The pieces built here become shared services that new products build on:

- **Security master:** `instrument_id` becomes the one ID every product uses, with CUSIP/ISIN, corporate
  actions and dated index membership.
- **More data sources** behind the provider interface (`app/providers/base.py`), each row tagged with its
  source.
- **Users and teams:** permissions, shared baskets and annotations.
- **Data quality and lineage:** automated checks, and every number traceable to its run and source.

**Scaling per use case.**

- **Portfolios.** Baskets become accounts with trade and position history, so returns come from actual
  trades and include cash. Daily figures are computed once by a job and stored.
- **Risk.** Factor exposures, correlations, VaR and stress tests are heavy batch work: an orchestrator
  (Airflow or Dagster) and an analytics store (Polars or DuckDB, then a warehouse). Versioned data means
  any risk report can be rerun as of the date it was produced.

**Infrastructure.** Run the ETL separately from the API; use events or a queue so new prices trigger the
jobs that depend on them; add a warehouse or read replicas for analytics and caching for busy endpoints;
alert on job failures and stale data.
