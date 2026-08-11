"""Tests for src/factors/illiquidity.py."""

import pandas as pd
import pytest

from src.factors.illiquidity import illiquidity_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ"] * 4,
        "Close": [100.0, 110.0, 99.0, 108.9],
        "Volume": [1000, 1000, 1000, 1000],
    }, index=pd.date_range("2024-06-25", periods=4, freq="B").tz_localize("America/New_York"))


def test_illiquidity_factor_averages_absolute_return_over_dollar_volume():
    prices = _toy_prices()
    result = illiquidity_factor(prices, "XYZ", "2024-06-28", lookback_days=3)
    expected = ((0.10 / 110000) + (0.10 / 99000) + (0.10 / 108900)) / 3
    assert result == pytest.approx(expected)


def test_illiquidity_factor_drops_zero_dollar_volume_days():
    prices = pd.DataFrame({
        "ticker": ["XYZ"] * 3,
        "Close": [100.0, 100.0, 110.0],
        "Volume": [1000, 0, 1000],
    }, index=pd.date_range("2024-06-26", periods=3, freq="B").tz_localize("America/New_York"))
    result = illiquidity_factor(prices, "XYZ", "2024-06-28", lookback_days=2)
    assert result == pytest.approx(0.10 / 110000)



def test_illiquidity_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert illiquidity_factor(prices, "ABC", "2024-06-28", lookback_days=3) is None
