"""ETL command line.

    python -m app.etl load         full live load: identities, reference data, 2y of prices
    python -m app.etl prices       nightly full price refresh; changed bars become new versions
    python -m app.etl topup        fetch only the days missing since the latest stored bar
    python -m app.etl reference    re-fetch reference data; changed records become new versions
    python -m app.etl bootstrap    startup: restore the seed (or live load), then top up
    python -m app.etl dump-seed    write the seed snapshot from the current database
    python -m app.etl restore-seed load the seed snapshot into an empty database

Every step is idempotent and recorded in `job_run`.
"""

import argparse
import logging
import sys

from app.etl import jobs


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs every request URL at INFO; keep it quiet so request details stay out of logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.etl")
    parser.add_argument(
        "command",
        choices=[
            "load",
            "prices",
            "topup",
            "reference",
            "bootstrap",
            "dump-seed",
            "restore-seed",
        ],
    )
    parser.add_argument("--tickers", help="comma-separated subset of the universe (load only)")
    args = parser.parse_args(argv)

    tickers = args.tickers.split(",") if args.tickers else None
    commands = {
        "load": lambda: jobs.load(tickers),
        "prices": jobs.prices,
        "topup": jobs.topup,
        "reference": jobs.reference,
        "bootstrap": jobs.bootstrap,
        "dump-seed": jobs.dump_seed,
        "restore-seed": jobs.restore_seed,
    }
    commands[args.command]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
