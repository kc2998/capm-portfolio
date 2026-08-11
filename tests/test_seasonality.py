"""Tests for src/factors/seasonality.py."""

import pytest
import pandas as pd

from src.factors.seasonality import seasonality_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ"] * 6,
        "Close": [100.0, 110.0, 100.0, 90.0, 100.0, 120.0],
    }, index=pd.to_datetime([
        "2021-05-31", "2021-06-30",
        "2022-05-31", "2022-06-30",
        "2023-05-31", "2023-06-30",
    ]))


def test_seasonality_factor_averages_complete_prior_occurrences():
    prices = _toy_prices()
    result = seasonality_factor(prices, "XYZ", "2024-06-28")
    assert result == pytest.approx((0.10 + (-0.10) + 0.20) / 3)



def test_seasonality_factor_returns_none_below_min_years():
    prices = _toy_prices()
    assert seasonality_factor(prices, "XYZ", "2024-06-28", min_years=4) is None


def test_seasonality_factor_returns_none_with_no_history():
    prices = pd.DataFrame({
        "ticker": ["XYZ"],
        "Close": [100.0],
    }, index=pd.to_datetime(["2024-06-28"]))
    assert seasonality_factor(prices, "XYZ", "2024-06-28") is None
