"""Tests for src/factors/debt_issuance.py."""

from src.factors.debt_issuance import debt_issuance_factor


def _toy_facts():
    return {
        "facts": {
            "us-gaap": {
                "LongTermDebtNoncurrent": {
                    "units": {"USD": [
                        {"end": "2023-03-31", "val": 800.0, "filed": "2023-05-01", "form": "10-Q"},
                        {"end": "2023-06-30", "val": 820.0, "filed": "2023-08-01", "form": "10-Q"},
                        {"end": "2023-09-30", "val": 850.0, "filed": "2023-11-01", "form": "10-Q"},
                        {"end": "2023-12-31", "val": 900.0, "filed": "2024-02-01", "form": "10-K"},
                        {"end": "2024-03-31", "val": 1000.0, "filed": "2024-05-01", "form": "10-Q"},
                    ]}
                },
            }
        }
    }


def test_debt_issuance_factor_compares_against_four_periods_back():
    assert debt_issuance_factor(_toy_facts(), "2024-06-28") == (1000.0 - 800.0) / 800.0


def test_debt_issuance_factor_treats_a_missing_current_debt_tag_as_zero():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["LongTermDebtCurrent"] = {
        "units": {"USD": [
            {"end": "2024-03-31", "val": 50.0, "filed": "2024-05-01", "form": "10-Q"},
        ]}
    }
    # Only one current-debt point exists (offset=4 finds none there, treated as zero).
    assert debt_issuance_factor(facts, "2024-06-28") == (1050.0 - 800.0) / 800.0


def test_debt_issuance_factor_returns_none_when_prior_debt_is_zero():
    facts = _toy_facts()
    facts["facts"]["us-gaap"]["LongTermDebtNoncurrent"]["units"]["USD"][0]["val"] = 0.0
    assert debt_issuance_factor(facts, "2024-06-28") is None


def test_debt_issuance_factor_returns_none_when_no_debt_tag_resolves():
    assert debt_issuance_factor({"facts": {"us-gaap": {}}}, "2024-06-28") is None
