"""Tests for src/factors/short_term_reversal.py."""

import pandas as pd

from src.factors.short_term_reversal import short_term_reversal_factor


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ", "XYZ"],
        "Close": [100.0, 90.0],
    }, index=pd.to_datetime(["2024-06-21", "2024-06-28"]).tz_localize("America/New_York"))


def test_short_term_reversal_factor_negates_the_trailing_return():
    prices = _toy_prices()
    result = short_term_reversal_factor(prices, "XYZ", "2024-06-28")
    assert result == -(90.0 / 100.0 - 1)


def test_short_term_reversal_factor_returns_none_when_start_of_window_has_no_data():
    prices = pd.DataFrame({
        "ticker": ["XYZ"],
        "Close": [90.0],
    }, index=pd.to_datetime(["2024-06-28"]).tz_localize("America/New_York"))
    assert short_term_reversal_factor(prices, "XYZ", "2024-06-28") is None


def test_short_term_reversal_factor_returns_none_for_a_ticker_not_present():
    prices = _toy_prices()
    assert short_term_reversal_factor(prices, "ABC", "2024-06-28") is None
