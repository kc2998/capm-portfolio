"""Seasonality factor: average historical return for the current calendar month.

Built and validated in notebooks/exploring_factors.ipynb, Part 3g.
"""

import pandas as pd

from src.loaders.prices import close_on_or_before


def seasonality_factor(prices, ticker, as_of, min_years=3):
    """Raw seasonality factor: average historical return in this ticker's
    own history for the current calendar month, across every complete
    prior occurrence of that month.

    Deliberately excludes the current, in-progress occurrence of the
    target month: only full month-end-to-month-end returns from strictly
    earlier years count, never a partial return from the month currently
    underway, which would look ahead into data not yet known as of as_of.

    Requires at least min_years complete prior occurrences before
    returning a value, since one or two data points make for an
    unreliable average of what's meant to be a genuinely repeating
    pattern, not a single company-specific event mistaken for one.
    Checked against a real 56-company sample (Part 3g): mean 0.005, range
    -0.038 to 0.113, both tails tapering smoothly, no outlier disconnected
    from its neighbors.

    Returns None if fewer than min_years complete occurrences exist.
    """
    as_of_ts = pd.Timestamp(as_of)

    returns = []
    # 40 years comfortably exceeds the universe's own ~28 year horizon
    # (1996 to present); years with no data simply contribute nothing.
    for years_back in range(1, 41):
        month_end = (as_of_ts - pd.DateOffset(years=years_back)).replace(day=1) + pd.offsets.MonthEnd(0)
        prior_month_end = month_end - pd.offsets.MonthEnd(1)
        end_close = close_on_or_before(prices, ticker, month_end)
        start_close = close_on_or_before(prices, ticker, prior_month_end)
        if end_close is None or start_close is None:
            continue
        returns.append(end_close / start_close - 1)

    if len(returns) < min_years:
        return None
    return sum(returns) / len(returns)
