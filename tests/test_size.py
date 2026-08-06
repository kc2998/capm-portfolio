"""Tests for src/factors/size.py."""

import pandas as pd

from src.factors.size import market_cap_as_of, split_adjustment_ratio


def _toy_prices():
    # A pre-split close, a 50-for-1 split, then a post-split close, the same
    # shape as the real CMG case that motivated this correction.
    return pd.DataFrame({
        "ticker": ["XYZ", "XYZ", "XYZ"],
        "Close": [100.0, 2.0, 2.1],
        "Stock Splits": [0.0, 50.0, 0.0],
    }, index=pd.to_datetime(["2024-04-22", "2024-06-26", "2024-06-28"]).tz_localize("America/New_York"))


def _toy_facts(shares=1000.0, end="2024-04-22", filed="2024-04-25"):
    return {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"end": end, "val": shares, "filed": filed, "form": "10-Q"}]}
                }
            }
        }
    }


def test_split_adjustment_ratio_picks_up_a_split_after_the_basis_date():
    prices = _toy_prices()
    assert split_adjustment_ratio(prices, "XYZ", "2024-04-22") == 50.0


def test_split_adjustment_ratio_is_1_when_no_split_happens_after_the_basis_date():
    prices = _toy_prices()
    assert split_adjustment_ratio(prices, "XYZ", "2024-06-28") == 1.0


def test_market_cap_as_of_applies_the_split_ratio_to_a_pre_split_share_count():
    # Mirrors the real CMG bug: shares filed before a split, price cached
    # after it, so shares times price alone would understate market cap by
    # the split ratio.
    facts = _toy_facts()
    prices = _toy_prices()
    assert market_cap_as_of(facts, prices, "XYZ", "2024-06-28") == 1000.0 * 50.0 * 2.1


def test_market_cap_as_of_returns_none_when_shares_cannot_be_resolved():
    facts = {"facts": {"dei": {}}}
    prices = _toy_prices()
    assert market_cap_as_of(facts, prices, "XYZ", "2024-06-28") is None


def test_market_cap_as_of_returns_none_when_price_cannot_be_resolved():
    facts = _toy_facts()
    prices = _toy_prices()
    assert market_cap_as_of(facts, prices, "NOT_A_TICKER", "2024-06-28") is None
