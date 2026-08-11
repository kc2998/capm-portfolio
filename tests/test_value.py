"""Tests for src/factors/value.py."""

import pandas as pd

from src.factors.value import earnings_yield_factor


def _toy_facts():
    return {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"end": "2024-04-22", "val": 1000.0, "filed": "2024-04-25", "form": "10-Q"}]}
                }
            },
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                }
            },
        }
    }


def _toy_prices():
    return pd.DataFrame({
        "ticker": ["XYZ", "XYZ", "XYZ"],
        "Close": [100.0, 2.0, 2.1],
        "Stock Splits": [0.0, 50.0, 0.0],
    }, index=pd.to_datetime(["2024-04-22", "2024-06-26", "2024-06-28"]).tz_localize("America/New_York"))


def test_earnings_yield_factor_divides_net_income_by_split_adjusted_market_cap():
    facts = _toy_facts()
    prices = _toy_prices()
    assert earnings_yield_factor(facts, prices, "XYZ", "2024-06-28") == 500.0 / (1000.0 * 50.0 * 2.1)


def test_earnings_yield_factor_returns_none_when_net_income_cannot_be_resolved():
    facts = _toy_facts()
    facts["facts"]["us-gaap"] = {}
    prices = _toy_prices()
    assert earnings_yield_factor(facts, prices, "XYZ", "2024-06-28") is None


def test_earnings_yield_factor_returns_none_when_market_cap_cannot_be_resolved():
    facts = _toy_facts()
    prices = _toy_prices()
    assert earnings_yield_factor(facts, prices, "NOT_A_TICKER", "2024-06-28") is None
