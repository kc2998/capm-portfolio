"""Tests for src/factors/volume_shock.py."""

import pandas as pd

from src.factors.volume_shock import volume_shock_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ"] * 6,
        "Volume": [100, 100, 100, 100, 100, 300],
    }, index=pd.date_range("2024-06-21", periods=6, freq="B").tz_localize("America/New_York"))


def test_volume_shock_factor_divides_recent_volume_by_the_trailing_average():
    prices = _toy_prices()
    assert volume_shock_factor(prices, "XYZ", "2024-06-28", lookback_days=5) == 3.0


def test_volume_shock_factor_returns_none_when_baseline_volume_is_zero():
    prices = pd.DataFrame({
        "ticker": ["XYZ"] * 3,
        "Volume": [0, 0, 300],
    }, index=pd.date_range("2024-06-26", periods=3, freq="B").tz_localize("America/New_York"))
    assert volume_shock_factor(prices, "XYZ", "2024-06-28", lookback_days=2) is None


def test_volume_shock_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert volume_shock_factor(prices, "ABC", "2024-06-28", lookback_days=5) is None
