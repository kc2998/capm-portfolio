"""Tests for the pure, no-I/O logic in src/loaders/fundamentals.py.

Deliberately excludes anything that hits the network: fetch_company_facts
and build_fundamentals exist specifically to ask EDGAR a question, validated
empirically against real filers in notebooks/exploring_fundamentals.ipynb
and documented in notebooks/logs/fundamentals_construction.md, not mocked
here. What's covered below is the decision logic those functions wrap
around: tag alias resolution, point in time selection, and the two
derivation fallbacks, the same principle tests/test_prices.py and
tests/test_point_in_time.py already apply. Every synthetic fact below
includes "form", since concept_value_as_of unpacks it unconditionally,
matching the shape every real EDGAR fact always has.
"""

from src.loaders.fundamentals import (
    concept_value_as_of,
    gross_profit_as_of,
    load_company_facts,
    save_company_facts,
    total_liabilities_as_of,
)


# ---------------------------------------------------------------------------
# concept_value_as_of
# ---------------------------------------------------------------------------

def test_concept_value_as_of_resolves_per_period_not_once_per_company():
    # Mirrors Alphabet's real history: LongTermDebtNoncurrent used through
    # 2020, an undifferentiated LongTermDebt tag used instead for 2021.
    # concept_value_as_of must try every alias for the period being queried,
    # not commit to one tag for the whole company.
    facts = {"facts": {"us-gaap": {
        "LongTermDebtNoncurrent": {"units": {"USD": [
            {"end": "2020-12-31", "val": 500, "filed": "2021-02-01", "form": "10-K"},
        ]}},
        "LongTermDebt": {"units": {"USD": [
            {"end": "2021-12-31", "val": 700, "filed": "2022-02-01", "form": "10-K"},
        ]}},
    }}}
    assert concept_value_as_of(facts, "long_term_debt_noncurrent", "USD", "2020-12-31", "2021-06-01")[0] == 500
    assert concept_value_as_of(facts, "long_term_debt_noncurrent", "USD", "2021-12-31", "2022-06-01")[0] == 700


def test_concept_value_as_of_never_returns_a_value_filed_after_as_of_date():
    # Mirrors Apple's real fiscal year 2008 restatement: the same period
    # reported twice, at two different values, ten weeks apart.
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"end": "2020-12-31", "val": 100, "filed": "2021-02-01", "form": "10-K"},
        {"end": "2020-12-31", "val": 150, "filed": "2021-06-01", "form": "10-K/A"},
    ]}}}}}
    assert concept_value_as_of(facts, "net_income", "USD", "2020-12-31", "2021-03-01")[0] == 100
    assert concept_value_as_of(facts, "net_income", "USD", "2020-12-31", "2021-07-01")[0] == 150


def test_concept_value_as_of_returns_none_before_anything_was_filed():
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"end": "2020-12-31", "val": 100, "filed": "2021-02-01", "form": "10-K"},
    ]}}}}}
    assert concept_value_as_of(facts, "net_income", "USD", "2020-12-31", "2021-01-01") is None


def test_concept_value_as_of_returns_none_for_an_unreported_concept():
    facts = {"facts": {"us-gaap": {}}}
    assert concept_value_as_of(facts, "net_income", "USD", "2020-12-31", "2021-03-01") is None


# ---------------------------------------------------------------------------
# total_liabilities_as_of
# ---------------------------------------------------------------------------

def test_total_liabilities_as_of_prefers_the_direct_tag():
    facts = {"facts": {"us-gaap": {"Liabilities": {"units": {"USD": [
        {"end": "2020-12-31", "val": 900, "filed": "2021-02-01", "form": "10-K"},
    ]}}}}}
    assert total_liabilities_as_of(facts, "2020-12-31", "2021-03-01") == 900


def test_total_liabilities_as_of_falls_back_to_the_balance_sheet_identity():
    # McKesson, Whirlpool, Fastenal, and roughly a quarter of a random S&P
    # 500 sample report Assets and StockholdersEquity but no explicit
    # Liabilities total.
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2020-12-31", "val": 300, "filed": "2021-02-01", "form": "10-K"}]}},
    }}}
    assert total_liabilities_as_of(facts, "2020-12-31", "2021-03-01") == 700


def test_total_liabilities_as_of_returns_none_when_neither_path_resolves():
    facts = {"facts": {"us-gaap": {}}}
    assert total_liabilities_as_of(facts, "2020-12-31", "2021-03-01") is None


# ---------------------------------------------------------------------------
# gross_profit_as_of
# ---------------------------------------------------------------------------

def test_gross_profit_as_of_prefers_the_direct_tag():
    facts = {"facts": {"us-gaap": {"GrossProfit": {"units": {"USD": [
        {"end": "2020-12-31", "val": 400, "filed": "2021-02-01", "form": "10-K"},
    ]}}}}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01") == 400


def test_gross_profit_as_of_falls_back_to_revenue_minus_cost_of_revenue():
    # DoorDash's real shape: revenue and cost of revenue reported, no
    # GrossProfit tag at all.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
        "CostOfRevenue": {"units": {"USD": [{"end": "2020-12-31", "val": 600, "filed": "2021-02-01", "form": "10-K"}]}},
    }}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01") == 400


def test_gross_profit_as_of_returns_none_when_neither_path_resolves():
    facts = {"facts": {"us-gaap": {}}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01") is None


# ---------------------------------------------------------------------------
# save_company_facts / load_company_facts
# ---------------------------------------------------------------------------

def test_save_and_load_company_facts_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("src.loaders.fundamentals.FUNDAMENTALS_RAW_DIR", tmp_path)

    facts = {"entityName": "Test Co", "facts": {"us-gaap": {}}}
    save_company_facts(999999, facts)

    assert load_company_facts(999999) == facts


def test_load_company_facts_returns_none_when_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("src.loaders.fundamentals.FUNDAMENTALS_RAW_DIR", tmp_path)

    assert load_company_facts(123456789) is None
