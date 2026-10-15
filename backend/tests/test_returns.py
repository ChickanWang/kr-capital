from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.analytics.returns import portfolio_values, transform

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)


def series(values: dict[date, float]) -> pd.Series:
    return pd.Series(values)


def test_transform_modes():
    closes = series({D1: 100.0, D2: 110.0, D3: 99.0})
    assert transform(closes, "price").tolist() == [100.0, 110.0, 99.0]
    assert transform(closes, "daily").tolist() == pytest.approx([0.10, -0.10])
    assert transform(closes, "cumulative").tolist() == pytest.approx([0.0, 0.10, -0.01])


def test_portfolio_is_fixed_quantity_and_hand_computed():
    # 10 x A (100 -> 110 -> 121) and 5 x B (50 -> 50 -> 40)
    closes = {1: series({D1: 100, D2: 110, D3: 121}), 2: series({D1: 50, D2: 50, D3: 40})}
    out = portfolio_values(closes, {1: Decimal(10), 2: Decimal(5)})

    assert out["value"].tolist() == [1250.0, 1350.0, 1410.0]
    assert out["daily_return"].tolist()[1:] == pytest.approx([1350 / 1250 - 1, 1410 / 1350 - 1])
    assert out["cumulative_return"].tolist() == pytest.approx([0.0, 0.08, 0.128])


def test_portfolio_skips_dates_where_a_holding_has_no_bar():
    closes = {1: series({D1: 100, D2: 110, D3: 121}), 2: series({D1: 50, D3: 40})}
    out = portfolio_values(closes, {1: Decimal(1), 2: Decimal(1)})
    assert list(out.index) == [D1, D3]


def test_short_positions_reduce_value():
    closes = {1: series({D1: 100, D2: 110})}
    out = portfolio_values(closes, {1: Decimal(-2)})
    assert out["value"].tolist() == [-200.0, -220.0]
