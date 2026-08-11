"""Low volatility factor: standard deviation of trailing daily returns.

Built and validated in notebooks/exploring_factors.ipynb, Part 10.
"""

import pandas as pd


def low_vol_factor(prices, ticker, as_of, lookback_days=252):
    """Raw low volatility factor: standard deviation of daily returns over
    the trailing lookback_days trading days.

    252 trading days (about a year), not a shorter window: more
    observations give a materially less noisy standard deviation estimate,
    same reasoning as momentum's own 12 month lookback.

    Returns the raw standard deviation, not its negative. Same convention
    as size_factor: which direction to bet is a decision for the alpha
    model and optimizer, not baked into the raw factor's sign here.

    Requires at least half of lookback_days worth of trading days actually
    present, so a recent IPO or a name near the start of its cached history
    doesn't get a wildly noisy estimate from a handful of days. Returns
    None below that, or if the ticker has no data at all.

    Confirmed against a real 58-company sample (Part 10): mean 0.0166,
    range 0.0081 to 0.0388, matching real defensive-versus-growth sector
    patterns (RSG, MCD, YUM in the low tail; ANET, AMD, ENPH in the high
    one).
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window = ticker_prices.loc[:as_of_ts].tail(lookback_days + 1)["Close"]
    returns = window.pct_change().dropna()
    if len(returns) < lookback_days // 2:
        return None
    return returns.std()
