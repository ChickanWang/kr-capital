"""Return calculations on split-adjusted closes. These are price returns: dividends are excluded."""

import uuid
from decimal import Decimal
from typing import Literal

import pandas as pd

Mode = Literal["price", "daily", "cumulative"]


def transform(closes: pd.Series, mode: Mode) -> pd.Series:
    """`closes` is indexed by date in ascending order."""
    closes = closes.astype(float)
    if mode == "price":
        return closes
    if mode == "daily":
        return closes.pct_change().dropna()
    return closes / closes.iloc[0] - 1


def portfolio_values(
    closes: dict[uuid.UUID, pd.Series], quantities: dict[uuid.UUID, Decimal]
) -> pd.DataFrame:
    """Fixed-quantity portfolio: value_t = sum(quantity * close_t). Only dates on which every
    holding has a close are used, so a missing bar never looks like a position going to zero.

    Returns columns value, daily_return, cumulative_return indexed by date.
    """
    if not quantities:
        return pd.DataFrame(columns=["value", "daily_return", "cumulative_return"])
    frame = pd.DataFrame({iid: closes[iid].astype(float) for iid in quantities}).dropna()
    weights = pd.Series({iid: float(q) for iid, q in quantities.items()})
    value = (frame * weights).sum(axis=1)
    return pd.DataFrame(
        {
            "value": value,
            "daily_return": value.pct_change(),
            "cumulative_return": value / value.iloc[0] - 1 if len(value) else value,
        }
    )
