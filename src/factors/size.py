"""Size factor: log market capitalization.

Market capitalization itself lives here, not in the fundamentals or price
loaders, because it needs a split-adjustment correction that belongs to
neither loader on its own (see src/loaders/fundamentals.py's own docstring).
value.py imports market_cap_as_of from here rather than duplicating the join,
since it needs the identical correction for any price-scaled ratio.

Built and validated in notebooks/exploring_factors.ipynb, Parts 2 and 5.
"""
import math
import pandas as pd

from src.loaders.fundamentals import shares_outstanding_as_of
from src.loaders.prices import close_on_or_before



def split_adjustment_ratio(prices, ticker, basis_date):
    """Cumulative split ratio between basis_date and the latest cached price date.

    Multiplying a basis-date share count by this ratio brings it onto the same
    split footing as any cached price, before or after basis_date, since split
    ratios compose across the whole interval regardless of where a query date
    falls in between. Confirmed against CMG (50.0, split before the query
    date), ORLY (15.0, split after it), and AAPL (1.0, no split at all).
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    basis_ts = pd.Timestamp(basis_date).tz_localize(ticker_prices.index.tz)
    later_splits = ticker_prices.loc[ticker_prices.index > basis_ts, "Stock Splits"]
    return later_splits[later_splits != 0].prod()


def market_cap_as_of(facts, prices, ticker, as_of):
    """Split-adjusted market capitalization as of a date, or None if shares
    or price cannot be resolved.

    Takes already-loaded facts and prices, and the ticker already resolved
    for this CIK and date, rather than a CIK and ticker_history. Matches
    concept_value_as_of and shares_outstanding_as_of's own convention: I/O
    (load_company_facts, ticker_on, load_cik_prices) is the caller's job,
    this function is pure given its inputs, which is what makes it testable
    without touching disk or network.
    """
    shares = shares_outstanding_as_of(facts, as_of)
    if shares is None:
        return None
    close = close_on_or_before(prices, ticker, as_of)
    if close is None:
        return None
    ratio = split_adjustment_ratio(prices, ticker, shares[4])
    return shares[0] * ratio * close


def size_factor(market_cap):
    """Raw size factor: log market capitalization, or None if market_cap is
    None or non-positive. A listed company's market cap should never
    actually be zero or negative, but a None from market_cap_as_of needs
    to propagate rather than crash math.log.

    Confirmed against exact cases (Part 6): log(e) = 1.0, log(1.0) = 0.0.
    """
    if market_cap is None or market_cap <= 0:
        return None
    return math.log(market_cap)

