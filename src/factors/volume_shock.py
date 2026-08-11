"""Volume shock factor: recent volume over trailing average volume.

Built and validated in notebooks/exploring_factors.ipynb, Part 3i.
"""

import pandas as pd


def volume_shock_factor(prices, ticker, as_of, lookback_days=20):
    """Raw volume shock factor: the most recent day's volume divided by the
    trailing lookback_days average volume immediately before it.

    The trailing average excludes the most recent day itself, so the
    numerator and denominator describe genuinely distinct periods: "is
    today's volume unusual relative to the recent past," not partly
    compared against itself.

    20 trading days (about a month) by default: this factor lives in the
    README's weekly horizon table, a much shorter baseline than momentum
    or low_vol's 252 day window, since a volume shock is inherently a
    fast-changing signal, not a slow-moving one.

    Requires at least half of lookback_days worth of trailing days
    actually present in the baseline window, same reasoning as
    low_vol_factor/high_proximity_factor. Returns None below that, or if
    the ticker has no data at all, or if the trailing average volume is
    zero (a genuinely halted or untraded name, where the ratio is
    undefined rather than infinite).

    Checked against a real 60-company sample (Part 3i): mean 1.84, median
    1.62, systematically above 1.0 across nearly every name. Not a bug:
    the sample's AS_OF (2024-06-28) is the Russell US Indexes annual
    reconstitution date, a genuinely elevated-volume day market-wide, not
    an ordinary one. A check on a non-reconstitution date should center
    closer to 1.0.
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window = ticker_prices.loc[:as_of_ts].tail(lookback_days + 1)["Volume"]
    if len(window) < 2:
        return None
    recent = window.iloc[-1]
    baseline = window.iloc[:-1]
    if len(baseline) < lookback_days // 2:
        return None
    baseline_avg = baseline.mean()
    if baseline_avg == 0:
        return None
    return recent / baseline_avg
