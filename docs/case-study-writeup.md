# Case study writeup
Link to [README](../README.md).


## AI Usage Throughout the Case Study

Before getting started prompting Claude to start on coding, I chatted with it about how to model the data, subsequently which endpoints were needed from the data, and finally, what frontend features would exist. It was an iterative process, where I would let it draft a first pass, then review it and ask for changes. The data model was settled before coding; the UI and some ETL details changed as I used the app.

A helpful Claude skill that I used was [grill-me](https://www.aihero.dev/skills-grill-me), where I essentially rubber-ducked to Claude until the mental model for the app I would build became fleshed out.

## Rubric for Success

To decide whether Claude's output was good enough, I checked 2 things:

- **The code reads like a PR I'd approve.** I reviewed each change like a PR, if I couldn't explain or justify it, it went back for changes.
- **The product works for someone using it.** I did a lot of manual testing, which is where most of the UI changes in the Frontend section came from.

I also kept the scope small and expanded it step by step, rather than asking for everything at once and
reviewing a large change I couldn't fully check.

## Tradeoffs

**Where I went deep: data modelling.** I spent the most time on the schema, because it's the hardest part
to get right and change. A naive model that overwrites prices or keys on tickers
silently corrupts history the first time a stock splits or renames. Cost: more complex queries (latest
version per row), more storage and more tests.

**What I didn't dig into, and why:**

I ended up choosing to use a single data source for this project, Polygon, since multiple sources needed more integration work, as well as more storage as a "dataset" in regards to data lineage. This is easily extensible if we were to productionize this, and we could have fallback sources.

I also compromised on including live prices, due to free plan restrictions and the data delay.

Finally, I decided to skip creating multiple users, and set it to a default "analyst" user, since I didn't think it added much value to the core product.

## Data Modelling

| Table | Columns | Rules |
|---|---|---|
| `instrument_metadata` | instrument_id (UUID), ticker, figi, name, sic_code, sic_description, primary_exchange, currency, shares_outstanding, listing_status, profile fields, data_version | PK (instrument_id, data_version); a FIGI can't belong to two instrument_ids (EXCLUDE constraint); ticker NULL = taken over by another stock |
| `instrument_daily_price` | instrument_id, trade_date, data_version, OHLC (split-adjusted), volume | PK (instrument_id, trade_date, data_version); a new version only when Polygon's bar changes |
| `basket`, `basket_member` | name, owner; member with optional target_quantity | UNIQUE (owner, name); removing a member is a hard delete |
| `annotation` | instrument_id, author, body, optional annotation_date, created/edited times | editable and deletable by its author only |
| `job_run` | job, params, status, timings, rows_written, error | one row per ETL run |
| `instrument_snapshot` (view) | the grid's columns | regular view, computed on read |


- **Identity.** Each stock has a permanent UUID; ticker and FIGI are versioned since they can change. 
  The ETL matches by FIGI, then ticker, so a rename keeps its UUID; If a ticker moves to another company, the old holder's ticker becomes NULL. 

### Versioned data ("as is" and "as was")

The brief asks to see data both as it is now and as it was at an earlier point. Both market-data tables
(`instrument_metadata` and `instrument_daily_price`) do this the same way: **rows are never updated or
deleted. A change is a new row.**

**How a version is written.** Every ETL run takes one timestamp when it starts, its `data_version`, and
stamps every row it writes with it. So one nightly run is one version across all 101 stocks, and the
runs in `job_run` line up with the versions. The run compares what Polygon returns with the current row
and only inserts when something differs:
- **Reference data:** the nightly `reference` job re-fetches each stock's details. If any field differs
  from the latest row (name, ticker, shares outstanding, description, ...), the whole record is inserted
  as a new row; if nothing changed, nothing is written.
- **Prices:** the nightly `prices` job re-fetches each stock's 2-year history. A bar becomes a new version
  only if its open, high, low, close or volume differ from the stored one. A normal night adds one new
  bar per stock and rewrites nothing.

**Why this design.**
- The versions are the audit trail, so there is nothing separate to keep in sync. A change-log table
  and a `/changes` endpoint were built first and removed because they restated what the versions show.
- An earlier price design overwrote bars and spotted splits by re-checking one day's close. It was
  replaced because it rewrote history and relied on a heuristic.
- `data_version` is a timestamp, not a date: two runs on one day (e.g. a manual re-run) would otherwise
  collide and force an overwrite.

**Limits.**
- `data_version` is when the app *recorded* a change, not when it happened. Polygon gives no effective
  dates, so a rename shows up on the night it was first fetched. Full bitemporal history is a next step.
- The free plan serves 2 years of bars, so a split can't re-version anything older than that.

## Constraints

Polygon's free tier allows 5 calls/min, 2 years of history and end-of-day data only. Loading the S&P 100
(101 tickers) takes ~200 calls, about **40 minutes**; the S&P 500 would take 3.3 hours. This is why I chose a fixed
S&P 100 universe (user-chosen tickers leave a screener with nothing to screen), store everything
permanently, fetch only missing days on startup via grouped-daily (one call = every stock for one day),
and run full refreshes overnight.

## Assumptions
- **Universe:** the S&P 100 as listed on Wikipedia (page dated 2026-09-21, fetched 2026-10-14). Later
  index changes aren't picked up.
- **Market cap** is the latest close × Polygon's share-class shares outstanding, so GOOG and GOOGL each
  show their own class, not Alphabet's total.
- **`data_version`** is when the app learned of a change, not when it happened.

## Data sourcing

- **Hybrid loading:** an ETL preload, nightly refreshes, and on-demand gap fill. Pure ETL shows nothing
  new until the next run; pure on-the-fly leaves the grid empty and has no history to detect changes in.
- **No live quotes.** The free plan delivers data on a 1 day delay; a day's bars are served from just
  after midnight ET. So the app shows the last stored close.
- **Schedule: 06:00 ET, Tue–Sat,** storing the previous day's close. The first schedule (weekdays 17:00)
  assumed same-evening availability and left the grid about 11 hours staler than necessary.
- **Cron (Supercronic) over Airflow.** The ETL is a CLI sharing code with the API; a scheduler container
  runs it nightly and `job_run` records history. Airflow is several containers for one daily chain.

### First load: seed snapshot + top-up

The goal was that `docker compose up` shows a full grid within seconds, even for a reviewer without a
Polygon key. A live first load can't do that: ~200 calls at 5/min is ~40 minutes of an empty grid, and
nothing at all without a key. So startup (`bootstrap`) works in two steps:

- **Seed snapshot.** `seed/` holds a gzipped copy of the two market-data tables,
  restored into an empty database in a few seconds.
- **Top-up.** The snapshot is out of date as soon as it's committed, so `topup` fetches only the trading
  days after the newest stored bar. It stops at the first day Polygon refuses (the free plan serves a day's bars only after midnight ET) and the next run picks it
  up.

**Alternatives Considered.** Running the full `prices` refresh on startup is correct but takes ~20
minutes (one call per stock). Filling only on demand would leave the grid empty, because the grid needs
every stock's latest close. The snapshot is ~1 MB in git and has to be refreshed by hand with `dump-seed`.

## Product

- **Baskets.** Themes, watchlists and portfolios are all named groups: one table, optional quantities; a
  basket where every member has one is a portfolio
- **Annotations.** Free text, optionally dated, newest first. They began append-only, but that made typos
  permanent, so authors can edit or delete their own.
- **Analytics on request.** ~100 stocks × 500 days computes in milliseconds and is never stale.

## Frontend

One screen (grid, chart, basket sidebar, company card drawer), built with Vite + React +
TypeScript, plain CSS, AG Grid Community, TradingView Lightweight Charts, plain `fetch` (TanStack Query
is unnecessary for a handful of endpoints).

- **Chart:** compare up to five stocks. Price axis $, $ log (default when comparing:
  equal distances are equal % moves) or YoY %. A "% change since range start" view was replaced: easy to
  misread and duplicated cumulative return.
- **Annotations on the chart** are clickable dots; text labels were tried and piled up.
- **Company card** opens from ⓘ, the chart button or the annotations column (double-click alone was too
  hidden). History compares consecutive versions, grouping first-time fields into one "Added:" line.
- **Adding to baskets** went through "select rows, then add" (an empty basket filtered every row out),
  then search only (one at a time), then ★ in the grid with a Members only / All stocks toggle.
- **Portfolio panel** in the bottom area (the sidebar had no room): value, return, volatility (σ × √252),
  max drawdown, best/worst day, holdings with weight and contribution (contributions sum to the daily
  return). Panels resize; sizes reset on refresh because remembered sizes made awkward layouts stick.

## Testing

Tests cover what is most likely to be silently wrong: versioning (renames, ticker reuse), price
versioning and splits, `topup` and refresh (including a refused day), returns and portfolio math,
annotations and gap detection. Polygon is faked with fixtures; API tests use a real Postgres. CI runs
ruff, mypy, pytest, migration/model and OpenAPI/type drift checks, and the frontend lint and build. The
frontend was checked by hand; it has no tests.

## Next steps

Given more time to productionize this project, next steps could include

- Coverage: user-added tickers, the S&P 500 on a paid tier, dated index membership.

- Data: live prices, a backup source

- Product: a screen-wide "as of" picker to show historical price data, saved screens, authentication.

- Infrastructure: an ETL lock, Celery or Airflow as jobs grow, hosted Postgres, frontend tests.

## Data Validation

Checking for data errors stopped at unit tests and hand calculations; there isn't an automated scan of the
data itself. The cheapest fix with the biggest payoff would be an automated data-quality check in the ETL, 
for example flagging any daily move over 50%.

Examples of checks it could run after each job, flagging rows instead of blocking the load:

- **Price jumps:** a daily move over a threshold (e.g. 50%) that no known split explains.
- **Bar sanity:** low ≤ open, close ≤ high; prices above zero; volume not negative and not zero on a
  trading day.
- **Gaps:** a stock missing a trading day that the other stocks have (`topup` doesn't fill these)
- **Stale data:** the same close and volume for several days in a row, which usually means a frozen feed.
- **Coverage:** every ticker in the universe file has a current instrument row and recent prices.

This is probably the most important step before productionizing.
