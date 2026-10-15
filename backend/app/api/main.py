import logging

from fastapi import FastAPI

from app.api.routers import baskets, instruments, ops

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx logs every request URL at INFO; keep it quiet so request details stay out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(
    title="KR Capital Watchlist API",
    description="S&P 100 watchlist and screener: prices, versioned reference data, baskets.",
    version="0.1.0",
)
app.include_router(instruments.router)
app.include_router(baskets.router)
app.include_router(ops.router)
