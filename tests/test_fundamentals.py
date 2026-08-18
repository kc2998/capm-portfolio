"""Tests for the pure, no-I/O logic in src/loaders/fundamentals.py.

Deliberately excludes anything that hits the network: fetch_company_facts
and build_fundamentals exist specifically to ask EDGAR a question, validated
empirically against real filers in notebooks/exploring_fundamentals.ipynb
and notebooks/validating_fundamentals.ipynb, not mocked here. What's covered
below is the decision logic those functions wrap around: tag alias
resolution, period classification, point in time selection, and the two
derivation fallbacks, the same principle tests/test_prices.py and
tests/test_point_in_time.py already apply.

Every synthetic fact includes "form", since concept_value_as_of unpacks it
unconditionally, and every fact for a duration concept includes "start",
matching the shape every real EDGAR fact of that kind always has. Each
fixture below mirrors a specific filing pattern found in a real company
rather than an invented one; the company is named in each test.
"""

import pytest

from src.loaders.fundamentals import (
    annual_duration,
    available_periods,
    concept_value_as_of,
    gross_profit_as_of,
    latest_value_as_of,
    load_company_facts,
    period_type,
    save_company_facts,
    shares_outstanding_as_of,
    total_liabilities_as_of,
)


def gaap(tag, points):
    """One us-gaap tag's worth of USD facts, in EDGAR's own nesting."""
    return {"facts": {"us-gaap": {tag: {"units": {"USD": points}}}}}


def annual(start, end, val, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


# ---------------------------------------------------------------------------
# annual_duration
# ---------------------------------------------------------------------------

def test_annual_duration_is_the_filers_own_year_not_365():
    # Apple's fiscal years are 52 or 53 weeks. end - start is one less than the
    # inclusive day count, so a 52 week year measures 363, never 365.
    facts = gaap("NetIncomeLoss", [
        annual("2019-09-29", "2020-09-26", 574_000_000_000, "2020-10-30"),
        annual("2020-09-27", "2021-09-25", 946_000_000_000, "2021-10-29"),
    ])
    assert annual_duration(facts) == 363


def test_annual_duration_breaks_ties_toward_the_longer_year():
    # A filer that moved its fiscal year end files one transition period
    # alongside its normal ones. Elite Express Holding has a 329 day year and a
    # 364 day year and nothing else, so the mode is tied. Left to Counter's
    # insertion order the answer would depend on the order facts appear in the
    # vendor's response, which would make a backtest unreplayable.
    facts = gaap("NetIncomeLoss", [
        annual("2023-12-01", "2024-10-25", 1_000, "2024-12-01"),   # 329 days
        annual("2024-12-01", "2025-11-30", 2_000, "2025-12-01"),   # 364 days
    ])
    assert annual_duration(facts) == 364


def test_annual_duration_spans_concepts_not_just_the_one_queried():
    # Boston Scientific tags net income only for 90, 91, 180 and 272 day periods
    # and never for a full year. Measuring from net income alone returns None and
    # renders every one of its net income facts unclassifiable; measuring across
    # the duration concepts finds the year length in revenue instead.
    facts = {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"USD": [
            annual("2020-10-01", "2020-12-31", 10, "2021-02-01", "10-Q"),   # 91 days
        ]}},
        "Revenues": {"units": {"USD": [
            annual("2020-01-01", "2020-12-31", 100, "2021-02-01"),          # 365 days
        ]}},
    }}}
    assert annual_duration(facts) == 365


def test_annual_duration_returns_none_when_no_annual_figure_exists():
    facts = gaap("NetIncomeLoss", [
        annual("2020-10-01", "2020-12-31", 10, "2021-02-01", "10-Q"),
    ])
    assert annual_duration(facts) is None


# ---------------------------------------------------------------------------
# period_type
# ---------------------------------------------------------------------------

def test_period_type_identifies_an_instant_structurally():
    # A balance sheet fact carries no "start" key at all. That absence is exact,
    # not a tolerance, and holds regardless of whether a year length is known.
    assert period_type({"end": "2020-12-31", "val": 1}, None) == "instant"


def test_period_type_measures_against_the_filers_own_year():
    # Costco divides its year 12-12-12-16 weeks, so three of its quarters run 83
    # days and the fourth runs 111. Both are quarters. An absolute day band wide
    # enough for both would have to span 35 days.
    assert period_type(annual("2019-09-02", "2019-11-24", 1, "2020-01-01"), 363) == "quarterly"
    assert period_type(annual("2020-05-11", "2020-08-30", 1, "2020-10-01"), 363) == "quarterly"
    # Apple's 53 week years open with a 14 week quarter, 97 days.
    assert period_type(annual("2016-09-25", "2016-12-31", 1, "2017-02-01"), 370) == "quarterly"


def test_period_type_returns_none_without_a_year_to_measure_against():
    # A filer with no annual figure anywhere is left unclassified rather than
    # guessed at, consistent with the module's rule that a missing value is never
    # inferred.
    assert period_type(annual("2020-01-01", "2020-03-31", 1, "2020-05-01"), None) is None


def test_period_type_returns_none_for_a_period_matching_no_band():
    # Invitation Homes reports its predecessor entity's January 2017 alone, a 30
    # day period that is not a quarter, a half year, or a year.
    assert period_type(annual("2017-01-01", "2017-01-31", 1, "2017-05-01"), 364) is None


# ---------------------------------------------------------------------------
# concept_value_as_of: the period argument
# ---------------------------------------------------------------------------

def test_concept_value_as_of_requires_a_period_for_a_duration_concept():
    facts = gaap("NetIncomeLoss", [annual("2020-01-01", "2020-12-31", 100, "2021-02-01")])
    with pytest.raises(ValueError, match="span of time"):
        concept_value_as_of(facts, "net_income", "USD", "2020-12-31", "2021-03-01")


def test_concept_value_as_of_rejects_a_period_for_an_instant_concept():
    facts = gaap("Assets", [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}])
    with pytest.raises(ValueError, match="instant"):
        concept_value_as_of(facts, "total_assets", "USD", "2020-12-31", "2021-03-01", "annual")


# ---------------------------------------------------------------------------
# concept_value_as_of: period selection
# ---------------------------------------------------------------------------

def test_concept_value_as_of_separates_a_quarter_from_the_year_to_date():
    # Alphabet's 2021-06-30 carries a 90 day figure of $18,525,000,000 and a 180
    # day year to date figure of $36,455,000,000, both filed the same day. This
    # is the defect the period argument exists to fix: matching on end date alone
    # returned whichever happened to sort last, roughly doubling the quarter.
    facts = gaap("NetIncomeLoss", [
        annual("2020-01-01", "2020-12-31", 40_269_000_000, "2021-02-02"),
        annual("2021-04-01", "2021-06-30", 18_525_000_000, "2021-07-28", "10-Q"),
        annual("2021-01-01", "2021-06-30", 36_455_000_000, "2021-07-28", "10-Q"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2021-06-30", "2022-01-01", "quarterly")[0] == 18_525_000_000
    assert concept_value_as_of(
        facts, "net_income", "USD", "2021-06-30", "2022-01-01", "half_year")[0] == 36_455_000_000


def test_concept_value_as_of_handles_a_twelve_twelve_twelve_sixteen_week_year():
    # Costco's fiscal 2020: 83 day quarters, a 167 day half year, a 363 day year.
    # Asking for the quarter ending 2020-02-16 must not return the half year
    # figure that ends on the same date.
    facts = gaap("NetIncomeLoss", [
        annual("2019-09-02", "2020-08-30", 4_002_000_000, "2020-10-07"),
        annual("2019-11-25", "2020-02-16", 931_000_000, "2020-03-11", "10-Q"),
        annual("2019-09-02", "2020-02-16", 1_775_000_000, "2020-03-11", "10-Q"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-02-16", "2021-01-01", "quarterly")[0] == 931_000_000


def test_concept_value_as_of_merges_a_period_whose_start_was_retagged():
    # Coca-Cola revised its second quarter 2011 net income from $2,797,000,000 to
    # $2,800,000,000, and in the same filing shifted the period's tagged start by
    # one day. Without treating nearby starts as one period the two look like
    # different periods, their filing dates are never compared, and the
    # superseded figure is returned forever.
    facts = gaap("NetIncomeLoss", [
        annual("2011-01-01", "2011-12-31", 8_572_000_000, "2012-02-28"),
        annual("2011-04-02", "2011-07-01", 2_797_000_000, "2011-08-01", "10-Q"),
        annual("2011-04-03", "2011-07-01", 2_800_000_000, "2012-07-26", "10-Q"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2011-07-01", "2013-01-01", "quarterly")[0] == 2_800_000_000


def test_concept_value_as_of_keeps_two_reporting_bases_apart():
    # Invitation Homes reports a predecessor and a successor entity either side
    # of a 2017 reorganization, so 2017-12-31 carries both a 364 day combined
    # calendar year and a 333 day successor year. Their starts are 31 days apart,
    # too far to be one period retagged, so the one closest to a full year wins.
    facts = gaap("NetIncomeLoss", [
        annual("2017-01-01", "2017-12-31", -105_337_000, "2018-02-22"),
        annual("2017-02-01", "2017-12-31", -88_458_000, "2018-02-22"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2017-12-31", "2019-01-01", "annual")[0] == -105_337_000


def test_concept_value_as_of_returns_none_when_the_year_length_is_unknown():
    # A filer with no annual figure for any duration concept cannot have a period
    # classified, so a duration query returns None rather than a guess.
    facts = gaap("NetIncomeLoss", [
        annual("2020-10-01", "2020-12-31", 10, "2021-02-01", "10-Q"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-12-31", "2021-06-01", "quarterly") is None


# ---------------------------------------------------------------------------
# concept_value_as_of: alias resolution and point in time selection
# ---------------------------------------------------------------------------

def test_concept_value_as_of_resolves_per_period_not_once_per_company():
    # Mirrors Alphabet's real history: LongTermDebtNoncurrent used through 2020,
    # an undifferentiated LongTermDebt tag used instead for 2021.
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
    facts = gaap("NetIncomeLoss", [
        annual("2020-01-01", "2020-12-31", 100, "2021-02-01"),
        annual("2020-01-01", "2020-12-31", 150, "2021-06-01", "10-K/A"),
    ])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-12-31", "2021-03-01", "annual")[0] == 100
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-12-31", "2021-07-01", "annual")[0] == 150


def test_concept_value_as_of_returns_none_before_anything_was_filed():
    facts = gaap("NetIncomeLoss", [annual("2020-01-01", "2020-12-31", 100, "2021-02-01")])
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-12-31", "2021-01-01", "annual") is None


def test_concept_value_as_of_returns_none_for_an_unreported_concept():
    facts = {"facts": {"us-gaap": {}}}
    assert concept_value_as_of(
        facts, "net_income", "USD", "2020-12-31", "2021-03-01", "annual") is None


# ---------------------------------------------------------------------------
# total_liabilities_as_of
# ---------------------------------------------------------------------------

def test_total_liabilities_as_of_prefers_the_direct_tag():
    facts = gaap("Liabilities", [
        {"end": "2020-12-31", "val": 900, "filed": "2021-02-01", "form": "10-K"},
    ])
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
    facts = gaap("GrossProfit", [annual("2020-01-01", "2020-12-31", 400, "2021-02-01")])
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01", "annual") == 400


def test_gross_profit_as_of_falls_back_to_revenue_minus_cost_of_revenue():
    # DoorDash's real shape: revenue and cost of revenue reported, no
    # GrossProfit tag at all.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [annual("2020-01-01", "2020-12-31", 1000, "2021-02-01")]}},
        "CostOfRevenue": {"units": {"USD": [annual("2020-01-01", "2020-12-31", 600, "2021-02-01")]}},
    }}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01", "annual") == 400


def test_gross_profit_as_of_derives_from_matching_periods_only():
    # Both sides of the subtraction must describe the same span. A quarterly
    # revenue minus an annual cost of revenue would produce a number describing
    # no period at all, so the quarterly query returns None rather than mixing.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            annual("2020-01-01", "2020-12-31", 1000, "2021-02-01"),
            annual("2020-10-01", "2020-12-31", 250, "2021-02-01", "10-Q"),
        ]}},
        "CostOfRevenue": {"units": {"USD": [
            annual("2020-01-01", "2020-12-31", 600, "2021-02-01"),
        ]}},
    }}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01", "annual") == 400
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01", "quarterly") is None


def test_gross_profit_as_of_returns_none_when_neither_path_resolves():
    facts = {"facts": {"us-gaap": {}}}
    assert gross_profit_as_of(facts, "2020-12-31", "2021-03-01", "annual") is None


# ---------------------------------------------------------------------------
# shares_outstanding_as_of
# ---------------------------------------------------------------------------

def count(end, val, filed, form="10-K", accn="acc-1"):
    return {"end": end, "val": val, "filed": filed, "form": form, "accn": accn}


def shares_doc(dei_points=(), gaap_points=()):
    """A facts document carrying share counts under either or both tags."""
    facts = {"facts": {}}
    if dei_points:
        facts["facts"]["dei"] = {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": list(dei_points)}}}
    if gaap_points:
        facts["facts"]["us-gaap"] = {
            "CommonStockSharesOutstanding": {"units": {"shares": list(gaap_points)}}}
    return facts


def test_shares_outstanding_pools_both_tags_and_takes_the_freshest():
    # Apple's real shape. Its cover page count is dated 2025-10-17, twenty days
    # after the fiscal year ended, while its balance sheet count is dated to the
    # year end itself. The cover page figure is the more recent of the two and is
    # the one a rebalance on any later date should use.
    # Both tags come from the same 10-K, hence the shared accn: a cover page
    # count and a balance sheet count filed together, not two filings.
    facts = shares_doc(
        dei_points=[count("2025-10-17", 14_840_000_000, "2025-10-31", accn="0000320193-25-000100")],
        gaap_points=[count("2025-09-27", 14_800_000_000, "2025-10-31", accn="0000320193-25-000100")],
    )
    val, _, _, tag, end = shares_outstanding_as_of(facts, "2025-12-01")
    assert val == 14_840_000_000
    assert tag == "EntityCommonStockSharesOutstanding"
    assert end == "2025-10-17"


def test_shares_outstanding_resolves_with_only_the_cover_page_tag():
    # Coca-Cola, Chipotle, and McKesson report only the mandatory cover page
    # disclosure and never the optional balance sheet tag. A period-matched query
    # cannot reach any of their share counts, which is why this function exists.
    facts = shares_doc(dei_points=[count("2026-02-18", 4_300_000_000, "2026-02-20")])
    assert shares_outstanding_as_of(facts, "2026-06-01")[0] == 4_300_000_000


def test_shares_outstanding_prefers_the_later_filing_for_the_same_date():
    # An amendment supersedes the filing it amends, the same rule applied
    # everywhere else in this module.
    facts = shares_doc(dei_points=[
        count("2026-02-18", 4_300_000_000, "2026-02-20", accn="acc-original"),
        count("2026-02-18", 4_310_000_000, "2026-05-01", "10-K/A", accn="acc-amendment"),
    ])
    assert shares_outstanding_as_of(facts, "2026-06-01")[0] == 4_310_000_000


def test_shares_outstanding_ignores_a_count_not_yet_filed():
    # The fresher figure exists in the cached document but had not been filed as
    # of the query date, so the older one is what was actually knowable.
    facts = shares_doc(
        dei_points=[count("2025-10-17", 14_840_000_000, "2025-10-31", accn="acc-q3")],
        gaap_points=[count("2025-06-28", 14_900_000_000, "2025-08-01", accn="acc-q2")],
    )
    assert shares_outstanding_as_of(facts, "2025-09-01")[0] == 14_900_000_000


def test_shares_outstanding_returns_none_when_neither_tag_exists():
    # Meta and DoorDash report their share counts only per share class, and the
    # bulk companyfacts endpoint serves only undimensioned facts, so neither tag
    # is present at all. No interface change reaches a fact that does not exist.
    assert shares_outstanding_as_of({"facts": {"us-gaap": {}}}, "2026-01-01") is None


def averaged_doc(wa_points, seed_year=True):
    """A filer reporting no actual share count, only the period average, plus an
    annual revenue figure so that a fiscal year length can be measured."""
    facts = {"facts": {"us-gaap": {
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": list(wa_points)}},
    }}}
    if seed_year:
        facts["facts"]["us-gaap"]["Revenues"] = {"units": {"USD": [
            annual("2025-01-01", "2025-12-31", 1_000, "2026-01-29")]}}
    return facts


def test_shares_outstanding_falls_back_to_the_period_average():
    # Meta, DoorDash, Ralph Lauren and eight others report their count only per
    # share class, so companyfacts holds no undimensioned count at all. Earnings
    # per share requires a weighted average, so that is available instead.
    facts = averaged_doc([annual("2026-01-01", "2026-03-31", 2_534_000_000, "2026-05-01", "10-Q")])
    val, _, _, tag, _ = shares_outstanding_as_of(facts, "2026-06-01")
    assert val == 2_534_000_000
    assert tag == "WeightedAverageNumberOfSharesOutstandingBasic"


def test_shares_outstanding_prefers_the_quarterly_average_to_the_annual_one():
    # The annual average lags the valuation date by about ten months and the
    # quarterly by about three. Measured on 5,271 observations, the annual figure
    # carries a +0.37% median skew, being an average over a period in which a
    # repurchasing company had more shares outstanding than it does now; the
    # quarterly figure's median is 0.00%. Preferring quarterly is what keeps the
    # value factor from penalising repurchasers.
    facts = averaged_doc([
        annual("2025-01-01", "2025-12-31", 2_600_000_000, "2026-01-29"),
        annual("2026-01-01", "2026-03-31", 2_534_000_000, "2026-05-01", "10-Q"),
    ])
    assert shares_outstanding_as_of(facts, "2026-06-01")[0] == 2_534_000_000


def test_shares_outstanding_does_not_fall_back_when_a_real_count_exists():
    # The approximation is a last resort, never pooled with genuine counts.
    facts = shares_doc(dei_points=[count("2026-04-30", 4_300_000_000, "2026-05-01")])
    facts["facts"]["us-gaap"] = {
        "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [
            annual("2026-01-01", "2026-03-31", 9_999_999_999, "2026-05-01", "10-Q")]}},
        "Revenues": {"units": {"USD": [annual("2025-01-01", "2025-12-31", 1_000, "2026-01-29")]}},
    }
    val, _, _, tag, _ = shares_outstanding_as_of(facts, "2026-06-01")
    assert val == 4_300_000_000
    assert tag == "EntityCommonStockSharesOutstanding"


def test_shares_outstanding_can_refuse_the_approximation():
    # A sensitivity check on the approximation needs to be able to exclude the
    # companies relying on it, rather than only to detect them afterwards.
    facts = averaged_doc([annual("2026-01-01", "2026-03-31", 2_534_000_000, "2026-05-01", "10-Q")])
    assert shares_outstanding_as_of(facts, "2026-06-01", allow_weighted_average=False) is None


def test_shares_outstanding_average_respects_the_staleness_bound():
    # Sunoco is a limited partnership reporting units rather than shares, and a
    # filer whose average is as stale as its count is no better off. The bound
    # applies to the fall back exactly as it does to a real count.
    facts = averaged_doc([annual("2019-01-01", "2019-03-31", 500_000_000, "2019-05-01", "10-Q")])
    assert shares_outstanding_as_of(facts, "2026-06-01") is None


def test_concept_value_as_of_rejects_shares_outstanding():
    # Routing it through the period-matched interface is the defect this function
    # was introduced to fix, so it fails loudly rather than returning None.
    with pytest.raises(ValueError, match="shares_outstanding_as_of"):
        concept_value_as_of(shares_doc(dei_points=[count("2026-02-18", 1, "2026-02-20")]),
                            "shares_outstanding", "shares", "2025-12-31", "2026-06-01")


# ---------------------------------------------------------------------------
# available_periods / latest_value_as_of
# ---------------------------------------------------------------------------

def test_available_periods_only_counts_periods_already_filed():
    # Apple's fiscal 2021 ended 2021-09-25 but was not filed until 2021-10-29.
    # A query on 2021-10-01 must not see it yet, the same look ahead boundary
    # concept_value_as_of enforces one period at a time.
    facts = gaap("NetIncomeLoss", [
        annual("2019-09-29", "2020-09-26", 100, "2020-10-30"),
        annual("2020-09-27", "2021-09-25", 200, "2021-10-29"),
    ])
    assert available_periods(facts, "net_income", "USD", "2021-10-01", "annual") == ["2020-09-26"]
    assert available_periods(facts, "net_income", "USD", "2021-10-29", "annual") == \
        ["2020-09-26", "2021-09-25"]


def test_available_periods_reaches_the_derived_route_for_total_liabilities():
    # Dover Corp's real shape: no direct Liabilities tag since 2009, but Assets
    # and StockholdersEquity both current, so the period is available through
    # DERIVED_FALLBACK even though no Liabilities fact exists at all.
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2020-12-31", "val": 300, "filed": "2021-02-01", "form": "10-K"}]}},
    }}}
    assert available_periods(facts, "total_liabilities", "USD", "2021-03-01") == ["2020-12-31"]


def test_available_periods_requires_both_derived_components_at_the_same_period():
    # One component alone cannot derive a figure, so the period is not
    # available through the derived route until both sides describe it.
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
    }}}
    assert available_periods(facts, "total_liabilities", "USD", "2021-03-01") == []


def test_available_periods_derives_gross_profit_from_matching_periods_only():
    # Mirrors gross_profit_as_of's own rule: a quarterly revenue and an annual
    # cost of revenue must not be combined into a period describing neither.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            annual("2020-01-01", "2020-12-31", 1000, "2021-02-01"),
            annual("2020-10-01", "2020-12-31", 250, "2021-02-01", "10-Q"),
        ]}},
        "CostOfRevenue": {"units": {"USD": [
            annual("2020-01-01", "2020-12-31", 600, "2021-02-01"),
        ]}},
    }}}
    assert available_periods(facts, "gross_profit", "USD", "2021-03-01", "annual") == ["2020-12-31"]
    assert available_periods(facts, "gross_profit", "USD", "2021-03-01", "quarterly") == []


def test_latest_value_as_of_returns_the_most_recent_period():
    facts = gaap("NetIncomeLoss", [
        annual("2019-01-01", "2019-12-31", 100, "2020-02-01"),
        annual("2020-01-01", "2020-12-31", 150, "2021-02-01"),
    ])
    assert latest_value_as_of(facts, "net_income", "USD", "2021-06-01", "annual") == \
        (150, "2021-02-01", "10-K", "NetIncomeLoss", "2020-12-31")


def test_latest_value_as_of_offset_steps_back_one_period():
    # A growth factor comparing this year against last needs offset=1.
    facts = gaap("NetIncomeLoss", [
        annual("2019-01-01", "2019-12-31", 100, "2020-02-01"),
        annual("2020-01-01", "2020-12-31", 150, "2021-02-01"),
    ])
    got = latest_value_as_of(facts, "net_income", "USD", "2021-06-01", "annual", offset=1)
    assert got[0] == 100 and got[4] == "2019-12-31"


def test_latest_value_as_of_returns_none_past_the_last_available_offset():
    facts = gaap("NetIncomeLoss", [annual("2020-01-01", "2020-12-31", 150, "2021-02-01")])
    assert latest_value_as_of(facts, "net_income", "USD", "2021-06-01", "annual", offset=1) is None


def test_latest_value_as_of_resolves_the_derived_route_with_provenance():
    # Dover Corp's shape again: the returned tag names both components since
    # the value comes from two facts rather than one, and filed/form come from
    # whichever of the two was filed later.
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2020-12-31", "val": 300, "filed": "2021-02-15", "form": "10-K/A"}]}},
    }}}
    got = latest_value_as_of(facts, "total_liabilities", "USD", "2021-03-01")
    assert got == (700, "2021-02-15", "10-K/A", "derived: total_assets - stockholders_equity", "2020-12-31")


def test_latest_value_as_of_prefers_the_direct_tag_over_the_derived_route():
    # A period with both a direct Liabilities fact and derivable components
    # uses the direct one, matching total_liabilities_as_of's own precedence.
    facts = {"facts": {"us-gaap": {
        "Liabilities": {"units": {"USD": [{"end": "2020-12-31", "val": 650, "filed": "2021-02-01", "form": "10-K"}]}},
        "Assets": {"units": {"USD": [{"end": "2020-12-31", "val": 1000, "filed": "2021-02-01", "form": "10-K"}]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2020-12-31", "val": 300, "filed": "2021-02-01", "form": "10-K"}]}},
    }}}
    got = latest_value_as_of(facts, "total_liabilities", "USD", "2021-03-01")
    assert got == (650, "2021-02-01", "10-K", "Liabilities", "2020-12-31")


def test_latest_value_as_of_returns_none_for_an_unreported_concept():
    facts = {"facts": {"us-gaap": {}}}
    assert latest_value_as_of(facts, "net_income", "USD", "2021-06-01", "annual") is None


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
