"""Tests for src/factors/momentum.py."""

import pandas as pd

from src.factors.momentum import momentum_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ", "XYZ"],
        "Close": [100.0, 150.0],
    }, index=pd.to_datetime(["2023-06-28", "2024-05-28"]).tz_localize("America/New_York"))


def test_momentum_factor_computes_the_trailing_return_skipping_the_last_month():
    prices = _toy_prices()
    assert momentum_factor(prices, "XYZ", "2024-06-28") == 0.5


def test_momentum_factor_returns_none_when_the_start_of_the_window_has_no_data():
    prices = pd.DataFrame({
        "ticker": ["XYZ"],
        "Close": [150.0],
    }, index=pd.to_datetime(["2024-05-28"]).tz_localize("America/New_York"))
    assert momentum_factor(prices, "XYZ", "2024-06-28") is None


def test_momentum_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert momentum_factor(prices, "ABC", "2024-06-28") is None
