"""Tests for src/factors/profitability.py."""

from src.factors.profitability import gross_profitability_factor


def _toy_facts_direct():
    return {
        "facts": {
            "us-gaap": {
                "GrossProfit": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 400.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "Assets": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": 2000.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
            }
        }
    }


def _toy_facts_derived():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 1000.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "CostOfRevenue": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 600.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "Assets": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": 2000.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
            }
        }
    }


def test_gross_profitability_factor_with_a_direct_gross_profit_tag():
    assert gross_profitability_factor(_toy_facts_direct(), "2024-06-28") == 400.0 / 2000.0


def test_gross_profitability_factor_falls_back_to_revenue_minus_cost_of_revenue():
    assert gross_profitability_factor(_toy_facts_derived(), "2024-06-28") == (1000.0 - 600.0) / 2000.0


def test_gross_profitability_factor_returns_none_when_total_assets_is_non_positive():
    facts = _toy_facts_direct()
    facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = -2000.0
    assert gross_profitability_factor(facts, "2024-06-28") is None


def test_gross_profitability_factor_returns_none_when_gross_profit_cannot_be_resolved():
    facts = _toy_facts_direct()
    del facts["facts"]["us-gaap"]["GrossProfit"]
    assert gross_profitability_factor(facts, "2024-06-28") is None
