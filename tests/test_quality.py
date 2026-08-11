"""Tests for src/factors/quality.py."""

from src.factors.quality import roe_factor


def _toy_facts():
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "StockholdersEquity": {
                    "units": {"USD": [
                        {"end": "2023-12-31", "val": 2500.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
            }
        }
    }


def test_roe_factor_divides_net_income_by_stockholders_equity():
    facts = _toy_facts()
    assert roe_factor(facts, "2024-06-28") == 500.0 / 2500.0


def test_roe_factor_does_not_filter_negative_equity():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["StockholdersEquity"]["units"]["USD"][0]["val"] = -2500.0
    assert roe_factor(facts, "2024-06-28") == 500.0 / -2500.0


def test_roe_factor_returns_none_when_net_income_cannot_be_resolved():
    facts = _toy_facts()
    del facts["facts"]["us-gaap"]["NetIncomeLoss"]
    assert roe_factor(facts, "2024-06-28") is None


def test_roe_factor_returns_none_when_equity_cannot_be_resolved():
    facts = _toy_facts()
    del facts["facts"]["us-gaap"]["StockholdersEquity"]
    assert roe_factor(facts, "2024-06-28") is None
