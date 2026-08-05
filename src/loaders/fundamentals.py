"""Point in time fundamentals loader: raw EDGAR XBRL company facts.

Produces cached raw financial-statement data for every CIK that has ever been
a member of the S&P 500 (`src/universe/point_in_time.py`), one JSON file per
CIK, exactly as EDGAR's own `companyfacts` API returns it. Point in time
resolution (which tag a filer uses for a concept, and which value was known
as of a given date) happens at query time against this cached raw file, the
same division of labor as the price loader: this module caches the source of
truth, `src/factors/` derives an actual factor value from it (in particular,
joining this module's output to `src/loaders/prices.py` to compute market
capitalization and any price scaled ratio belongs there, not here, since it
needs a split-adjustment correction that has nothing to do with resolving
fundamentals data itself).

Full methodology, every tag-standardization and point in time complication
found while building this (the ASC 606 revenue tag change, the restated-value
mechanism, the per-period tag switch found in Alphabet's own filing history,
the balance-sheet-identity derivation for concepts some filers never tag
explicitly, and the split-adjustment bug found while joining to price data),
and the evidence behind every non-obvious decision are recorded in
`notebooks/logs/fundamentals_construction.md`. This module is the promoted,
clean implementation; that file is the reasoning behind it.
`notebooks/exploring_fundamentals.ipynb` is where this was originally built
and validated, kept as the historical record.
"""

import json
import logging
import time
from collections import Counter
from datetime import date, timedelta

import pandas as pd
import requests

from src.universe.point_in_time import DATA_PROCESSED, DATA_RAW, build_universe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths and vendor identification
# ---------------------------------------------------------------------------

FUNDAMENTALS_RAW_DIR = DATA_RAW / "fundamentals"
FUNDAMENTALS_COVERAGE_PATH = DATA_PROCESSED / "fundamentals_coverage.parquet"

# SEC requires a real, identifying User-Agent on every request or it blocks
# with a 403; same convention already established in
# src/universe/point_in_time.py for the other EDGAR endpoints used there.
SEC_HEADERS = {"User-Agent": "capm-portfolio-research kevin (contact: hongxianl957@gmail.com)"}

# A courtesy pause between requests during a batch build; SEC's own rate-limit
# guidance is a fair-use ask, not an enforced per-request limit.
REQUEST_PAUSE_SECONDS = 0.15


# ---------------------------------------------------------------------------
# Fetching and caching raw company facts
# ---------------------------------------------------------------------------

def fetch_company_facts(cik):
    """Fetch one CIK's raw XBRL company facts from EDGAR, unprocessed."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def save_company_facts(cik, facts):
    """Cache one CIK's raw company facts as-is, exactly as EDGAR returned them."""
    FUNDAMENTALS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = FUNDAMENTALS_RAW_DIR / f"{cik}.json"
    path.write_text(json.dumps(facts))


def load_company_facts(cik):
    """Load a CIK's cached raw company facts, or None if not yet fetched."""
    path = FUNDAMENTALS_RAW_DIR / f"{cik}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Tag resolution and point in time value lookup
#
# Which XBRL tag a filer uses for a given concept is not standardized: revenue
# alone has carried three names in the panel's own history, "SalesRevenueNet"
# before roughly 2013 (Harley-Davidson: 8 points, 2008-2009, then nothing;
# 370 cached companies carry it at all), "Revenues" through 2018, and
# "RevenueFromContractWithCustomerExcludingAssessedTax" after, the tag
# introduced by that year's ASC 606 standard. A backtest reaching into the
# 1990s (the project's own universe horizon) needs the first of these as much
# as the other two. A single filer's own choice can also change
# across its own filing history (Alphabet used "LongTermDebtNoncurrent"
# through 2020, an undifferentiated "LongTermDebt" for 2021-2022, then
# reverted). A standard change can also move essentially every filer at once:
# ASU 2009-17 required noncontrolling interest to be reported as part of total
# equity starting in fiscal 2009, and most filers responded by switching from
# "StockholdersEquity" to "StockholdersEquityIncludingPortionAttributable-
# ToNoncontrollingInterest" around that date and never tagging the shorter
# name again (CSX: 4 points, all 2008-2009, under the old tag; 267 points
# through 2026 under the new one). ASC 842, effective 2019, did the same to the
# long term debt tags: filers folded finance lease obligations into
# "LongTermDebtAndCapitalLeaseObligations(Current)" and stopped tagging plain
# "LongTermDebtCurrent"/"LongTermDebtNoncurrent" (Home Depot: both plain tags
# stop in 2017; the combined ones carry 130+ points each through 2026).
# Independently, a large group of filers (Tyson, Danaher, Crown Castle, Trane,
# Xylem, Skyworks, ADP, Travelers among them) never adopted the lease-inclusive
# tag and instead tag the current portion under the shorter "DebtCurrent".
#
# What remains unresolved after all three current-debt aliases is not, for the
# most part, a further missing alias. A handful are banks, insurers, asset
# managers, and a REIT (Franklin Resources, Raymond James, Chubb, Hartford,
# MetLife, First Horizon, Northern Trust, Ameriprise, Digital Realty) whose debt
# is tagged by security type ("SecuredDebt", "SubordinatedDebt",
# "ShortTermBorrowings") rather than by maturity, the same way revenue does not
# exist as a concept for banks (see src/loaders/README.md). But most of the
# remainder, checked by value rather than by date alone, last tagged this
# concept at exactly 0 (Waters, ServiceNow, PayPal, DoorDash, Electronic Arts)
# or a genuine nonzero figure that was presumably repaid with nothing since due
# within a year (ANSYS, AutoZone, Regeneron, Take-Two). Current portion of
# long term debt is a lumpy figure that is legitimately zero for long stretches,
# and filers commonly tag it once and stop re-confirming the zero every
# quarter, so no alias surfaces a fact that was never filed. Treating a stale
# or absent value here as "probably near zero" rather than "still broken" is a
# factor-construction decision, not a loader one: this module returns None
# rather than guessing, per the missing-value caveat below.
#
# Aliases are therefore tried per period queried, never resolved once per
# company and reused.
# ---------------------------------------------------------------------------

TAG_ALIASES = {
    "revenue": [
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
    ],
    "cost_of_revenue": [
        ("us-gaap", "CostOfRevenue"),
        ("us-gaap", "CostOfGoodsAndServicesSold"),
        ("us-gaap", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"),
    ],
    "net_income": [
        ("us-gaap", "NetIncomeLoss"),
    ],
    "total_assets": [
        ("us-gaap", "Assets"),
    ],
    "total_liabilities": [
        ("us-gaap", "Liabilities"),
    ],
    "stockholders_equity": [
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
    ],
    "long_term_debt_noncurrent": [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "ConvertibleLongTermNotesPayable"),
        ("us-gaap", "LongTermDebt"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations"),
    ],
    "long_term_debt_current": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "ConvertibleNotesPayableCurrent"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        ("us-gaap", "DebtCurrent"),
    ],
    "gross_profit": [
        ("us-gaap", "GrossProfit"),
    ],
}

# Shares outstanding is deliberately not in TAG_ALIASES. It is not a
# period-matched concept, so it is resolved by shares_outstanding_as_of below
# rather than by concept_value_as_of. The cover page tag records how many shares
# existed when the filing was prepared, so its `end` is a date 20 to 54 days
# after the fiscal period closed (measured across the validation panel: Apple 20,
# Costco 30, Coca-Cola 49, Arch Capital 54), and never coincides with a period
# end. Matching a period end therefore reaches only the optional `us-gaap` tag,
# which silently returns nothing for the filers that tag only the mandatory
# disclosure. The two tags were checked against each other on 11 filers carrying
# both and agree to within 0.01 percent when dated the same day, so they are
# pooled rather than ordered.
SHARES_OUTSTANDING_TAGS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
]


# ---------------------------------------------------------------------------
# Period classification
#
# A balance sheet fact describes an instant and is identified by its end date
# alone. An income statement or cash flow fact describes a span, and several
# spans share an end date: Alphabet filed both a 90 day figure of $18,525,000,000
# and a 180 day year to date figure of $36,455,000,000 for end 2021-06-30, on the
# same day. Matching on end date alone returns whichever happens to sort last.
#
# Period type is derived from duration as a fraction of the filer's own fiscal
# year rather than from an absolute day count, because a quarter runs 83 days at
# Costco (a 12-12-12-16 week year), 89 to 91 at a calendar year filer, 97 at
# Apple in a 53 week year, and 111 or 118 at Costco's fourth quarter. EDGAR's own
# `fp` and `form` fields were tested and rejected: both label the filing a fact
# appeared in rather than the fact, and one Costco fact appears under `fp` values
# of Q3, Q4, and FY. Validated against 30,886 periods across 100 randomly drawn
# companies, of which 0.09 percent fitted no band, all of them stub periods
# shorter than a fifth of a year. Full evidence in
# notebooks/logs/fundamentals_construction.md, Parts 14 and 15.
# ---------------------------------------------------------------------------

# Whether a concept's facts describe a span of time or a balance at an instant.
# Recorded rather than inferred, so that a caller asking for a balance sheet
# figure need not supply a period type, and so that the fiscal year length can be
# measured from the duration concepts alone.
CONCEPT_KIND = {
    "revenue": "duration",
    "cost_of_revenue": "duration",
    "net_income": "duration",
    "operating_cash_flow": "duration",
    "gross_profit": "duration",
    "total_assets": "instant",
    "total_liabilities": "instant",
    "stockholders_equity": "instant",
    "long_term_debt_noncurrent": "instant",
    "long_term_debt_current": "instant",
}

# The one absolute band in the rule, used only to find the filer's year length.
# It is the boundary with the widest clear space either side: observed annual
# durations run 363 to 370, and the nearest shorter period found was 333.
ANNUAL_SEED_DAYS = (340, 380)

RATIO_BANDS = [
    ("quarterly", 0.18, 0.35),
    ("half_year", 0.40, 0.55),
    ("nine_month", 0.60, 0.80),
    ("annual", 0.90, 1.05),
]

CANONICAL_RATIO = {"quarterly": 0.25, "half_year": 0.5, "nine_month": 0.75, "annual": 1.0}

# Start dates within this many days of each other are treated as one reporting
# period tagged inconsistently between filings. Measured, not chosen: competing
# start dates are either 1 to 8 days apart (18 of 19 pairs carrying identical
# values) or 31 days apart (3 of 3 carrying different values), with nothing in
# between. Any value from 9 to 30 gives identical results.
START_TOLERANCE_DAYS = 15


def _period_days(point):
    """Length in days of the period a fact covers, or None for an instant."""
    if "start" not in point:
        return None
    return (date.fromisoformat(point["end"]) - date.fromisoformat(point["start"])).days


def annual_duration(facts):
    """The filer's own fiscal year length in days, or None if it files no annual
    figure for any duration concept.

    Measured across every duration concept rather than the one being queried,
    because a filer can report one concept only quarterly while reporting others
    annually. Boston Scientific tags net income for 90, 91, 180, and 272 day
    periods and never for a full year, so a net income only measurement returns
    None and every net income fact for that company becomes unclassifiable. Nine
    such company and concept pairs appeared in a 100 company sample, and all nine
    resolve once the measurement spans concepts. Scanning the five duration
    concepts gives the same answer as scanning all 500-odd tags in every case
    tested, at roughly a sixtieth of the cost.

    Not a fixed 365, because `end - start` is one less than the inclusive day
    count: a 52 week year measures 363, a calendar year 364, a leap calendar year
    365, and a 53 week year 370.
    """
    lengths = []
    for concept, kind in CONCEPT_KIND.items():
        if kind != "duration":
            continue
        for taxonomy, tag in TAG_ALIASES[concept]:
            units = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {})
            for points in units.values():
                for point in points:
                    length = _period_days(point)
                    if length is not None and ANNUAL_SEED_DAYS[0] <= length <= ANNUAL_SEED_DAYS[1]:
                        lengths.append(length)
    if not lengths:
        return None
    # Ties are broken toward the longer duration rather than left to the order
    # facts happen to appear in the vendor's response, which would make the
    # result depend on document ordering and so not replayable. A filer that
    # changed its fiscal year end files one transition period alongside its
    # normal ones; Elite Express Holding has a 329 day year and a 364 day year
    # and nothing else, and the longer is the one to treat as its norm.
    counts = Counter(lengths)
    return max(counts, key=lambda length: (counts[length], length))


def period_type(point, year_days):
    """Classify one fact as "instant", "quarterly", "half_year", "nine_month",
    "annual", or None when no band applies.

    A fact with no `start` key is an instant, decided structurally rather than by
    tolerance. Everything else is measured against `year_days`, so a filer with
    no annual figure anywhere classifies as None rather than being guessed at.
    """
    if "start" not in point:
        return "instant"
    if year_days is None:
        return None
    ratio = _period_days(point) / year_days
    for name, low, high in RATIO_BANDS:
        if low <= ratio <= high:
            return name
    return None


def _cluster_by_start(points, tolerance=START_TOLERANCE_DAYS):
    """Group facts into reporting periods by start date proximity.

    Two facts belong to the same period when their start dates fall within
    `tolerance` days, which covers a filer tagging one period's first day
    inconsistently between filings: Coca-Cola shifted a quarter's start by one
    day when it revised the figure, and Costco by eight. Genuinely different
    periods sharing an end date stay separate, as at Invitation Homes, which
    reports a predecessor and a successor basis whose starts are 31 days apart.
    """
    if not points:
        return []
    ordered = sorted(points, key=lambda point: point["start"])
    clusters, current = [], [ordered[0]]
    for previous, point in zip(ordered, ordered[1:]):
        gap = (date.fromisoformat(point["start"]) - date.fromisoformat(previous["start"])).days
        if gap <= tolerance:
            current.append(point)
        else:
            clusters.append(current)
            current = [point]
    clusters.append(current)
    return clusters


def concept_value_as_of(facts, concept, unit, period_end, as_of_date, period=None):
    """Return the value known for `concept` as of `as_of_date`, for the period
    ending `period_end`, as (val, filed, form, tag), or None.

    `period` names which kind of period is wanted: "quarterly", "half_year",
    "nine_month", or "annual". It is required for a concept whose facts describe
    a span of time and must be omitted for one describing an instant, per
    `CONCEPT_KIND`. It exists because an end date does not identify a fact:
    Alphabet's 2021-06-30 carries both a 90 day figure of $18,525,000,000 and a
    180 day year to date figure of $36,455,000,000, filed on the same day.

    Resolution proceeds in four steps, each of which exists to handle a real
    filing pattern found in the validation panel (see
    notebooks/logs/fundamentals_construction.md, Part 14):

    1. Aliases are tried in order, for this specific period, because a filer's
       choice of tag can change across its own history.
    2. Facts are kept only if they classify as the requested period type, which
       is measured as a fraction of the filer's own fiscal year rather than in
       absolute days, since a quarter runs from 83 to 118 days across filers.
    3. Facts whose start dates lie within `START_TOLERANCE_DAYS` of each other
       are treated as one period tagged inconsistently between filings. Where
       distinct periods remain, the one closest to the canonical ratio is kept,
       which resolves a filer reporting two entity bases over the same dates.
    4. Among the surviving facts, the latest filed on or before `as_of_date`
       wins, which is what makes a restatement resolvable point in time.

    Steps 3 and 4 are ordered deliberately. Reversed, Coca-Cola's superseded
    second quarter 2011 figure would be returned indefinitely, because it was
    revised in a filing that also shifted the period's tagged start date by one
    day, and the older vintage has the ratio marginally closer to a quarter.

    Returns None, never an inferred zero, if nothing qualifies: a missing tag
    might mean a genuinely zero balance, or might mean the figure simply had not
    been filed yet as of the queried date, and conflating the two would
    misrepresent what was actually known on a given date. A filer for whom no
    fiscal year length can be measured at all also returns None for every
    duration concept, rather than being classified by guesswork.
    """
    if concept == "shares_outstanding":
        raise ValueError(
            "shares outstanding is not a period-matched concept; call "
            "shares_outstanding_as_of(facts, as_of_date) instead. The cover page "
            "tag is dated 20 to 54 days after the period end, so no period end "
            "matches it and this function would silently return None."
        )

    kind = CONCEPT_KIND[concept]
    if kind == "instant":
        if period not in (None, "instant"):
            raise ValueError(
                f"{concept!r} describes a balance at an instant, so `period` does "
                f"not apply; got {period!r}."
            )
        period = "instant"
    elif period is None:
        raise ValueError(
            f"{concept!r} describes a span of time, so `period` is required: one "
            f"of {sorted(CANONICAL_RATIO)}. Several spans share an end date, and "
            f"choosing between them is what this argument is for."
        )

    # Measured once per call rather than per alias, and skipped entirely for an
    # instant concept, where the absence of a `start` key is the classification.
    year_days = None if kind == "instant" else annual_duration(facts)

    for taxonomy, tag in TAG_ALIASES[concept]:
        points = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, [])
        candidates = [p for p in points
                      if p["end"] == period_end
                      and p["filed"] <= as_of_date
                      and period_type(p, year_days) == period]
        if not candidates:
            continue

        if period == "instant":
            chosen = max(candidates, key=lambda p: p["filed"])
        else:
            clusters = _cluster_by_start(candidates)
            if len(clusters) > 1:
                target = CANONICAL_RATIO[period]
                clusters.sort(key=lambda c: abs(_period_days(c[0]) / year_days - target))
            chosen = max(clusters[0], key=lambda p: p["filed"])
        return chosen["val"], chosen["filed"], chosen["form"], tag
    return None


# ---------------------------------------------------------------------------
# Derived concepts: some filers never tag these directly
# ---------------------------------------------------------------------------

# A filer reports its share count at least annually, so a count older than this
# relative to the query date means the filer stopped tagging it rather than that
# it is the latest available. Measured: 4 of 117 cached companies are still
# filing while their undimensioned share count froze years earlier, all four
# multi-class filers that switched to per-class tagging partway through their
# history, which the bulk companyfacts endpoint then drops. Mastercard's count
# froze in 2010 at 122,530,193 against an actual count near 905,000,000, which
# would understate its market capitalisation sevenfold and silently.
MAX_SHARE_COUNT_AGE_DAYS = 400

# A last resort when no actual share count can be resolved, which is the case for
# roughly 9 percent of filers: those reporting the count only per share class,
# whose facts therefore all carry a dimension and are dropped by the bulk
# companyfacts endpoint. Earnings per share requires a weighted average, so this
# exists for almost all of them.
#
# It answers a different question. The weighted average is the number of shares
# outstanding across a reporting period, weighted by how long each was
# outstanding, which is the correct denominator for earnings per share and the
# wrong one for market capitalisation, where the count at the valuation date is
# what matters.
#
# The quarterly figure is preferred over the annual one by a wide margin.
# Measured against a true count on 5,271 observations where both were available:
#
#   annual     median error +0.37%, median absolute 1.74%, 5th-95th -9.9% to +8.1%
#   quarterly  median error +0.00%, median absolute 0.43%, 5th-95th -2.7% to +3.1%
#
# with the quarterly figure closer in 83 percent of cases. The annual figure's
# positive median is systematic rather than noise: an average over the past year
# exceeds the current count whenever the count has been falling, which for large
# companies usually means share repurchase. That matters because repurchase
# intensity correlates with the profitability and value characteristics these
# factors measure, so an annual average would penalise exactly the companies
# those factors are meant to favour. Preferring the quarterly figure cuts the lag
# from roughly ten months to roughly three and removes the skew.
#
# The SEC's Financial Statement Data Sets were investigated as an exact
# alternative and cover less: 8 of the 11 affected filers rather than 10, at far
# greater cost, and requiring a segment normalisation layer that would itself
# have returned a figure 123 percent too high for Ralph Lauren. See
# notebooks/logs/fundamentals_construction.md, Part 17.
WEIGHTED_AVERAGE_SHARES_TAG = ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")

# A minority of filers, Tyson Foods among them, never tag the basic count at all
# and report only the diluted figure. Tried second, after the basic tag comes up
# empty: diluted already includes the effect of options and awards and so
# slightly overstates the true count, which is why basic is preferred whenever
# it exists.
DILUTED_WEIGHTED_AVERAGE_SHARES_TAG = ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")


def shares_outstanding_as_of(facts, as_of_date, max_age_days=MAX_SHARE_COUNT_AGE_DAYS,
                             allow_weighted_average=True):
    """The most recently reported common shares outstanding known as of
    `as_of_date`, as (val, filed, form, tag, end), or None.

    `allow_weighted_average` permits a last-resort fall back to the period
    average share count for the roughly 9 percent of filers that report their
    actual count only per share class, which the bulk companyfacts endpoint then
    drops. It is on by default because the alternative is losing those companies
    from every market capitalisation and price scaled ratio, which is a larger
    and more systematic distortion than the approximation: the affected filers
    are concentrated in dual class governance structures rather than scattered.
    Pass False to restrict the result to genuine point in time counts, which is
    what a sensitivity check on that approximation would want. The returned tag
    names the source either way, so a caller can tell which companies relied on
    it without turning it off.

    `end` is returned alongside the value because it is the date the count refers
    to, and a caller computing market capitalisation needs to know how current
    the figure is. `max_age_days` bounds that: a count dated more than this far
    before `as_of_date` is treated as unavailable rather than returned, since a
    filer that has genuinely stopped tagging is indistinguishable, from the value
    alone, from one whose latest figure is simply old. Non-positive counts are
    discarded for the same reason: a listed company does not have zero common
    shares, and both Datadog and Robinhood report exactly that.

    Takes no period end, unlike every other concept in this module, because the
    question a factor asks is "how many shares were outstanding as of this
    rebalance date, according to the most recent filing available by then". That
    question has no reporting period in it. The two source tags carry different
    kinds of date and neither is a period end a caller would hold:
    `dei:EntityCommonStockSharesOutstanding` is dated to the cover page of the
    filing, 20 to 54 days after the period closed, and
    `us-gaap:CommonStockSharesOutstanding` is dated to the period end but is
    optional, so filers such as Coca-Cola, Chipotle, and McKesson report only the
    former. Requiring a period end reached 12 of 18 validation panel members;
    dropping it reaches 15, the remaining 3 being filers with no undimensioned
    share count at all (see the caveat in src/loaders/README.md).

    Both tags are pooled rather than tried in order, and the fact with the latest
    `end` wins, so the freshest available count is returned whichever tag it came
    from. This is safe because the two agree closely on what they count: across
    11 panel filers carrying both, the closest dated pair agrees to within 0.01
    percent where the dates coincide, and the largest divergence, 0.79 percent at
    JPMorgan, comes from a pair 31 days apart and is ordinary drift in the share
    count rather than a difference in scope.

    Ties on `end` are broken by the latest `filed`, so an amendment supersedes
    the filing it amends. Facts filed after `as_of_date` are discarded first, as
    everywhere else in this module.
    """
    oldest_allowed = (date.fromisoformat(as_of_date) - timedelta(days=max_age_days)).isoformat()

    candidates = []
    for taxonomy, tag in SHARES_OUTSTANDING_TAGS:
        points = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {}).get("shares", [])
        candidates += [(p, tag) for p in points
                       if p["filed"] <= as_of_date
                       and p["end"] >= oldest_allowed
                       and p["val"] > 0]
    if candidates:
        point, tag = max(candidates, key=lambda pair: (pair[0]["end"], pair[0]["filed"]))
        return point["val"], point["filed"], point["form"], tag, point["end"]

    if not allow_weighted_average:
        return None
    return _weighted_average_shares_as_of(facts, as_of_date, oldest_allowed)


def _weighted_average_shares_as_of(facts, as_of_date, oldest_allowed):
    """The period average share count, as a last resort. See
    WEIGHTED_AVERAGE_SHARES_TAG for why this is used and what it costs.

    Quarterly is tried before annual because it lags the valuation date by about
    three months rather than ten, which removes the repurchase-related skew
    rather than merely shrinking it. The basic tag is tried in full, quarterly
    then annual, before the diluted-only tag is tried at all, since basic is
    preferred whenever a filer reports it.
    """
    year_days = annual_duration(facts)
    for taxonomy, tag in (WEIGHTED_AVERAGE_SHARES_TAG, DILUTED_WEIGHTED_AVERAGE_SHARES_TAG):
        points = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {}).get("shares", [])
        if not points:
            continue
        for wanted in ("quarterly", "annual"):
            eligible = [p for p in points
                        if p["filed"] <= as_of_date
                        and p["end"] >= oldest_allowed
                        and p["val"] > 0
                        and period_type(p, year_days) == wanted]
            if eligible:
                best = max(eligible, key=lambda p: (p["end"], p["filed"]))
                return best["val"], best["filed"], best["form"], tag, best["end"]
    return None


def total_liabilities_as_of(facts, period_end, as_of_date):
    """Total liabilities as of a date, falling back to the balance sheet
    identity (Assets - StockholdersEquity) when a filer has no explicit
    `Liabilities` tag. True for roughly a quarter of a random sample of S&P
    500 filers checked (McKesson, Whirlpool, Fastenal, and others report
    Assets and StockholdersEquity directly but never an explicit Liabilities
    total), not a rare edge case.
    """
    direct = concept_value_as_of(facts, "total_liabilities", "USD", period_end, as_of_date)
    if direct is not None:
        return direct[0]
    assets = concept_value_as_of(facts, "total_assets", "USD", period_end, as_of_date)
    equity = concept_value_as_of(facts, "stockholders_equity", "USD", period_end, as_of_date)
    if assets is not None and equity is not None:
        return assets[0] - equity[0]
    return None


def gross_profit_as_of(facts, period_end, as_of_date, period):
    """Gross profit as of a date, falling back to revenue minus cost of
    revenue when a filer has no explicit `GrossProfit` tag (e.g. DoorDash,
    which reports revenue and cost of revenue but never a gross profit
    line).

    All three concepts describe a span of time, so `period` is required and is
    applied identically to each. Deriving a figure from a revenue and a cost of
    revenue covering different spans would silently produce a number that
    describes no period at all.
    """
    direct = concept_value_as_of(facts, "gross_profit", "USD", period_end, as_of_date, period)
    if direct is not None:
        return direct[0]
    revenue = concept_value_as_of(facts, "revenue", "USD", period_end, as_of_date, period)
    cost = concept_value_as_of(facts, "cost_of_revenue", "USD", period_end, as_of_date, period)
    if revenue is not None and cost is not None:
        return revenue[0] - cost[0]
    return None


# ---------------------------------------------------------------------------
# Period discovery
#
# Every function above needs a period end the caller supplies, but a factor at
# a rebalance date holds 500 companies and none of their fiscal calendars:
# Apple's year ends in late September, Costco's in late August, McKesson's in
# March, and each shifts by a few days a year. These derive the period from
# the filings themselves, validated in notebooks/validating_fundamentals.ipynb
# against the fixed panel and the fixes above (cells 38-47).
# ---------------------------------------------------------------------------

# total_liabilities and gross_profit are each resolvable two ways: a direct
# tag, or a figure derived from two other concepts (total_liabilities_as_of
# and gross_profit_as_of above). A period counts as available if either route
# reaches it, or a filer relying entirely on the derived route, roughly a
# quarter of the sample for total_liabilities, would be undercounted here even
# though the two functions above already resolve it fine (Dover Corp: no
# direct Liabilities tag since 2009, but Assets and StockholdersEquity both
# current, so the derived route reaches 2026).
DERIVED_FALLBACK = {
    "total_liabilities": ("total_assets", "stockholders_equity"),
    "gross_profit": ("revenue", "cost_of_revenue"),
}


def available_periods(facts, concept, unit, as_of_date, period=None):
    """Period end dates for which `concept` resolves, as known on `as_of_date`.

    Sorted oldest first. `period` names the kind wanted for a concept describing a
    span of time and is ignored for one describing an instant, matching
    concept_value_as_of's contract so the two compose.

    A period is included only if some fact for it had been filed by the query
    date. That is what separates "the most recent period that has ended" from
    "the most recent period anybody could read", and the gap between them is
    weeks. Apple's fiscal 2021 ended 2021-09-25 and was filed 2021-10-29, so on
    2021-10-01 the most recent available annual period is fiscal 2020. Selecting
    on the end date instead would price a portfolio using a figure published four
    weeks later, which is look ahead of exactly the kind that is invisible in the
    result because the number returned looks entirely reasonable.

    Only facts that concept_value_as_of would itself consider are collected, so a
    caller never receives a period end that then resolves to None, except through
    DERIVED_FALLBACK, where latest_value_as_of resolves the value the same way
    total_liabilities_as_of and gross_profit_as_of do.
    """
    kind = CONCEPT_KIND[concept]
    period = "instant" if kind == "instant" else period
    year_days = None if kind == "instant" else annual_duration(facts)

    ends = set()
    for taxonomy, tag in TAG_ALIASES[concept]:
        points = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, [])
        for p in points:
            if p["filed"] <= as_of_date and period_type(p, year_days) == period:
                ends.add(p["end"])

    if concept in DERIVED_FALLBACK:
        comp_a, comp_b = DERIVED_FALLBACK[concept]
        ends_a = set(available_periods(facts, comp_a, unit, as_of_date, period))
        ends_b = set(available_periods(facts, comp_b, unit, as_of_date, period))
        ends |= ends_a & ends_b

    return sorted(ends)


def latest_value_as_of(facts, concept, unit, as_of_date, period=None, offset=0):
    """The most recent value of `concept` knowable on `as_of_date`, as
    (val, filed, form, tag, period_end), or None.

    This is the call a factor actually makes: it names a rebalance date and a
    concept, never a fiscal period, because it does not know the filer's calendar.

    `offset` steps back through the available periods, 0 being the most recent and
    1 the one before it, which is what a growth factor comparing this year against
    last needs. Note that it counts periods that are actually available rather
    than calendar periods: a filer that does not tag its fourth quarter separately
    has three quarterly periods a year, so offset=4 is not reliably "the same
    quarter a year ago". A seasonal comparison such as PEAD should match on the
    period end's month rather than step back a fixed count.

    `period_end` is returned so the caller can see how current the answer is, the
    same reason shares_outstanding_as_of returns it. A company that keeps filing
    while ceasing to tag one concept will return an old period here, and nothing
    in this function bounds that yet.

    For a period reached only through DERIVED_FALLBACK, `filed` and `form` come
    from whichever of the two components was filed later, and `tag` names both,
    since the value comes from two facts rather than one.
    """
    ends = available_periods(facts, concept, unit, as_of_date, period)
    if len(ends) <= offset:
        return None

    period_end = ends[-1 - offset]
    got = concept_value_as_of(facts, concept, unit, period_end, as_of_date, period)
    if got is None and concept in DERIVED_FALLBACK:
        comp_a, comp_b = DERIVED_FALLBACK[concept]
        a = concept_value_as_of(facts, comp_a, unit, period_end, as_of_date, period)
        b = concept_value_as_of(facts, comp_b, unit, period_end, as_of_date, period)
        if a is not None and b is not None:
            later = a if a[1] >= b[1] else b
            got = (a[0] - b[0], later[1], later[2], f"derived: {comp_a} - {comp_b}")
    if got is None:
        return None
    val, filed, form, tag = got
    return val, filed, form, tag, period_end


# ---------------------------------------------------------------------------
# The build: expensive, network-bound, meant to be run occasionally
# ---------------------------------------------------------------------------

def build_fundamentals(force_refresh=False):
    """Fetch (or load) raw company facts for every CIK that ever appears in
    `ticker_history`.

    Loads `data/processed/fundamentals_coverage.parquet` directly if present
    and `force_refresh` is False, mirroring `build_prices`'s own two branch
    contract. A CIK that returns a 404 (no XBRL company facts at all,
    expected for filers that delisted before EDGAR's 2009 XBRL mandate) is
    recorded as a coverage failure rather than silently skipped, the same
    discipline the price loader applies to delisted tickers.

    Returns the coverage DataFrame (`cik`, `fetched`, `usable`), one row per
    CIK. `fetched` means the request succeeded; `usable` means the response
    carries `us-gaap` facts at all, which `fetched` alone does not guarantee.
    A foreign private issuer filing form 20-F reports under `ifrs-full`
    instead and returns nothing for every concept in `TAG_ALIASES` despite a
    successful fetch (two such filers found: CIK 888746, and Pacific Airport
    Group and Lufax Holding besides, all three reached through the universe
    module's known ticker-to-CIK misattribution rather than genuine index
    membership). A `fetched` CIK can also hold only an unrelated, minor
    taxonomy: CIK 2115436, a stale `ticker_history` entry for XOM predating
    Exxon's real CIK, carries only `ffd` fee-disclosure tags and no `us-gaap`
    or `dei` facts at all. Before this column existed, `usable` had to be
    recomputed locally by every caller that needed it (see
    notebooks/validating_fundamentals.ipynb, cells checking `if not
    facts["facts"].get("us-gaap")`), which this makes unnecessary.
    """
    _, ticker_history = build_universe()

    if not force_refresh and FUNDAMENTALS_COVERAGE_PATH.exists():
        return pd.read_parquet(FUNDAMENTALS_COVERAGE_PATH)

    all_ciks = ticker_history["cik"].dropna().unique()
    coverage = []
    for i, cik in enumerate(all_ciks):
        try:
            facts = fetch_company_facts(cik)
            save_company_facts(cik, facts)
            usable = bool(facts.get("facts", {}).get("us-gaap"))
            coverage.append({"cik": cik, "fetched": True, "usable": usable})
        except requests.HTTPError:
            coverage.append({"cik": cik, "fetched": False, "usable": False})

        if (i + 1) % 50 == 0:
            logger.info("%d/%d CIKs done", i + 1, len(all_ciks))
        time.sleep(REQUEST_PAUSE_SECONDS)

    coverage_df = pd.DataFrame(coverage)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    coverage_df.to_parquet(FUNDAMENTALS_COVERAGE_PATH, index=False)
    return coverage_df
