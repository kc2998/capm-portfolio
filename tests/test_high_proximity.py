"""Tests for src/factors/high_proximity.py."""

import pandas as pd

from src.factors.high_proximity import high_proximity_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ"] * 5,
        "Close": [100.0, 120.0, 90.0, 80.0, 96.0],
    }, index=pd.date_range("2024-06-24", periods=5, freq="B").tz_localize("America/New_York"))


def test_high_proximity_factor_divides_current_price_by_the_trailing_max():
    prices = _toy_prices()
    assert high_proximity_factor(prices, "XYZ", "2024-06-28", lookback_days=5) == 96.0 / 120.0


def test_high_proximity_factor_is_1_when_current_price_is_the_trailing_max():
    prices = pd.DataFrame({
        "ticker": ["XYZ"] * 3,
        "Close": [80.0, 90.0, 100.0],
    }, index=pd.date_range("2024-06-26", periods=3, freq="B").tz_localize("America/New_York"))
    assert high_proximity_factor(prices, "XYZ", "2024-06-28", lookback_days=3) == 1.0


def test_high_proximity_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert high_proximity_factor(prices, "ABC", "2024-06-28", lookback_days=5) is None
