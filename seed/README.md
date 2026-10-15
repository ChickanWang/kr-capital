# Seed snapshot

Compressed copies of the two market-data tables, restored automatically on first start when the
database is empty (`python -m app.etl bootstrap`, run by `docker compose up`):

- `instrument_metadata.csv.gz`: every stock's identifiers and company details, with their versions
- `instrument_daily_price.csv.gz`: split-adjusted daily bars, with their versions

Taken on **2026-10-15**, holding closes through **2026-10-14** for the S&P 100 (101 instruments).
Baskets and annotations are user data and are not included. With a Polygon key set, the start-up
`topup` then fetches the days since; without one the app serves the snapshot as it is.

Regenerate after a fresh `topup`:

```bash
docker compose run --rm etl python -m app.etl dump-seed
```

The data comes from Polygon.io's free plan; check its terms before sharing this repo publicly.
