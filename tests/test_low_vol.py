"""Tests for src/factors/low_vol.py."""

import pytest
import pandas as pd



from src.factors.low_vol import low_vol_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ"] * 5,
        "Close": [100.0, 110.0, 99.0, 108.9, 98.01],
    }, index=pd.date_range("2024-06-24", periods=5, freq="B").tz_localize("America/New_York"))


def test_low_vol_factor_computes_the_std_of_trailing_daily_returns():
    prices = _toy_prices()
    result = low_vol_factor(prices, "XYZ", "2024-06-28", lookback_days=4)
    expected = pd.Series([0.1, -0.1, 0.1, -0.1]).std()
    assert result == pytest.approx(expected)



def test_low_vol_factor_returns_none_when_fewer_than_half_the_window_is_present():
    prices = _toy_prices()
    # Only 4 returns available; lookback_days=10 requires at least 5.
    assert low_vol_factor(prices, "XYZ", "2024-06-28", lookback_days=10) is None


def test_low_vol_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert low_vol_factor(prices, "ABC", "2024-06-28", lookback_days=4) is None
