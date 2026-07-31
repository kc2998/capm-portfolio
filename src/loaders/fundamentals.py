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
# Which XBRL tag a filer uses for a given concept is not standardized:
# revenue alone is reported as "Revenues" (older filers) or
# "RevenueFromContractWithCustomerExcludingAssessedTax" (the tag introduced
# by the 2018 ASC 606 standard), and a single filer's own choice can change
# across its own filing history (Alphabet used "LongTermDebtNoncurrent"
# through 2020, an undifferentiated "LongTermDebt" for 2021-2022, then
# reverted). Aliases are therefore tried per period queried, never resolved
# once per company and reused.
# ---------------------------------------------------------------------------

TAG_ALIASES = {
    "revenue": [
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
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
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
    ],
    "long_term_debt_noncurrent": [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "ConvertibleLongTermNotesPayable"),
        ("us-gaap", "LongTermDebt"),
    ],
    "long_term_debt_current": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "ConvertibleNotesPayableCurrent"),
    ],
    "shares_outstanding": [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ],
    "gross_profit": [
        ("us-gaap", "GrossProfit"),
    ],
}


def concept_value_as_of(facts, concept, unit, period_end, as_of_date):
    """Return the value known for `concept` as of `as_of_date`, for the period
    ending `period_end`, as (val, filed, form, tag), or None.

    Tries every alias in `TAG_ALIASES[concept]` in order, for this specific
    period, taking the first one with a value at all; then, among that tag's
    data points for this period, takes the one with the latest `filed` date
    that is still on or before `as_of_date`. Returns None, never an inferred
    zero, if nothing qualifies: a missing tag might mean a genuinely zero
    balance, or might mean the figure simply had not been filed yet as of the
    queried date, and conflating the two would misrepresent what was actually
    known on a given date.
    """
    for taxonomy, tag in TAG_ALIASES[concept]:
        points = facts["facts"].get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, [])
        candidates = [p for p in points if p["end"] == period_end and p["filed"] <= as_of_date]
        if candidates:
            latest = max(candidates, key=lambda p: p["filed"])
            return latest["val"], latest["filed"], latest["form"], tag
    return None


# ---------------------------------------------------------------------------
# Derived concepts: some filers never tag these directly
# ---------------------------------------------------------------------------

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


def gross_profit_as_of(facts, period_end, as_of_date):
    """Gross profit as of a date, falling back to revenue minus cost of
    revenue when a filer has no explicit `GrossProfit` tag (e.g. DoorDash,
    which reports revenue and cost of revenue but never a gross profit
    line).
    """
    direct = concept_value_as_of(facts, "gross_profit", "USD", period_end, as_of_date)
    if direct is not None:
        return direct[0]
    revenue = concept_value_as_of(facts, "revenue", "USD", period_end, as_of_date)
    cost = concept_value_as_of(facts, "cost_of_revenue", "USD", period_end, as_of_date)
    if revenue is not None and cost is not None:
        return revenue[0] - cost[0]
    return None


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

    Returns the coverage DataFrame (`cik`, `fetched`), one row per CIK.
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
            coverage.append({"cik": cik, "fetched": True})
        except requests.HTTPError:
            coverage.append({"cik": cik, "fetched": False})

        if (i + 1) % 50 == 0:
            logger.info("%d/%d CIKs done", i + 1, len(all_ciks))
        time.sleep(REQUEST_PAUSE_SECONDS)

    coverage_df = pd.DataFrame(coverage)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    coverage_df.to_parquet(FUNDAMENTALS_COVERAGE_PATH, index=False)
    return coverage_df
