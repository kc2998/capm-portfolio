"""Tests for src/factors/leverage.py."""

from src.factors.leverage import leverage_factor


def _toy_facts(noncurrent=400.0, current=100.0, equity=500.0):
    return {
        "facts": {
            "us-gaap": {
                "LongTermDebtNoncurrent": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": noncurrent, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "LongTermDebtCurrent": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": current, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "StockholdersEquity": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": equity, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
            }
        }
    }


def test_leverage_factor_sums_current_and_noncurrent_debt_over_equity():
    assert leverage_factor(_toy_facts(), "2024-06-28") == (400.0 + 100.0) / 500.0


def test_leverage_factor_treats_a_missing_current_debt_tag_as_zero():
    facts = _toy_facts()
    del facts["facts"]["us-gaap"]["LongTermDebtCurrent"]
    assert leverage_factor(facts, "2024-06-28") == 400.0 / 500.0


def test_leverage_factor_does_not_filter_negative_equity():
    assert leverage_factor(_toy_facts(equity=-500.0), "2024-06-28") == (400.0 + 100.0) / -500.0


def test_leverage_factor_returns_none_when_equity_is_exactly_zero():
    assert leverage_factor(_toy_facts(equity=0.0), "2024-06-28") is None


def test_leverage_factor_returns_none_when_no_debt_tag_resolves():
    facts = _toy_facts()
    del facts["facts"]["us-gaap"]["LongTermDebtNoncurrent"]
    del facts["facts"]["us-gaap"]["LongTermDebtCurrent"]
    assert leverage_factor(facts, "2024-06-28") is None
