"""Tests for src/factors/accruals.py."""

from src.factors.accruals import accruals_factor


def _toy_facts():
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 500.0, "filed": "2024-02-01", "form": "10-K"},
                    ]}
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {"USD": [
                        {"start": "2023-01-01", "end": "2023-12-31", "val": 300.0, "filed": "2024-02-01", "form": "10-K"},
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


def test_accruals_factor_scales_the_gap_by_total_assets():
    assert accruals_factor(_toy_facts(), "2024-06-28") == (500.0 - 300.0) / 1000.0


def test_accruals_factor_returns_none_when_operating_cash_flow_cannot_be_resolved():
    facts = _toy_facts()
    del facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]
    assert accruals_factor(facts, "2024-06-28") is None


def test_accruals_factor_returns_none_when_total_assets_is_non_positive():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = -1000.0
    assert accruals_factor(facts, "2024-06-28") is None
