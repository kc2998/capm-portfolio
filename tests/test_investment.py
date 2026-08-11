"""Tests for src/factors/investment.py."""

from src.factors.investment import investment_factor


def _toy_facts():
    return {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {"USD": [
                        {"end": "2023-03-31", "val": 900.0, "filed": "2023-05-01", "form": "10-Q"},
                        {"end": "2023-06-30", "val": 950.0, "filed": "2023-08-01", "form": "10-Q"},
                        {"end": "2023-09-30", "val": 980.0, "filed": "2023-11-01", "form": "10-Q"},
                        {"end": "2023-12-31", "val": 1000.0, "filed": "2024-02-01", "form": "10-K"},
                        {"end": "2024-03-31", "val": 1100.0, "filed": "2024-05-01", "form": "10-Q"},
                    ]}
                },
            }
        }
    }


def test_investment_factor_compares_against_four_periods_back():
    assert investment_factor(_toy_facts(), "2024-06-28") == (1100.0 - 900.0) / 900.0


def test_investment_factor_respects_a_custom_periods_back():
    # One period back (the immediately preceding quarter): 1100 vs 1000.
    assert investment_factor(_toy_facts(), "2024-06-28", periods_back=1) == (1100.0 - 1000.0) / 1000.0


def test_investment_factor_returns_none_when_not_enough_history_exists():
    facts = _toy_facts()
    assert investment_factor(facts, "2024-06-28", periods_back=10) is None
