"""Tests for src/factors/profit_growth.py."""

from src.factors.profit_growth import profit_growth_factor


def _toy_facts():
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {"USD": [
                        {"start": "2022-01-01", "end": "2022-12-31", "val": 300.0, "filed": "2023-02-01", "form": "10-K"},
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "Assets": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": 1000.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
            }
        }
    }


def test_profit_growth_factor_scales_the_change_by_total_assets():
    assert profit_growth_factor(_toy_facts(), "2024-06-28") == (500.0 - 300.0) / 1000.0


def test_profit_growth_factor_returns_none_with_only_one_annual_period():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].pop(0)
    assert profit_growth_factor(facts, "2024-06-28") is None


def test_profit_growth_factor_returns_none_when_total_assets_is_non_positive():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = 0.0
    assert profit_growth_factor(facts, "2024-06-28") is None
