"""52 week high proximity factor: price over its own trailing 252 day maximum.

Built and validated in notebooks/exploring_factors.ipynb, Part 3h.
"""

import pandas as pd


def high_proximity_factor(prices, ticker, as_of, lookback_days=252):
    """Raw 52 week high proximity factor: price divided by its own trailing
    lookback_days maximum, inclusive of the current price itself.

    A value of 1.0 means today's close is the trailing high; values below
    1.0 measure how far the current price sits below it. Requires at least
    half of lookback_days worth of trading days actually present, same
    threshold and reasoning as low_vol_factor: too few observations means
    the window doesn't really cover a year.

    Confirmed against a real 60-company sample (Part 3h): max exactly
    1.0 (a price can never exceed its own trailing max, by construction),
    min 0.389 (PAYC, matching its real, documented 2023-2024 decline).
    FDX sitting exactly at 1.0 here independently confirms the same June
    2024 earnings rally that made it the extreme case in
    short_term_reversal_factor's own real-data check.

    Returns None if fewer than half of lookback_days trading days are
    present, or if the ticker has no data at all.
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window = ticker_prices.loc[:as_of_ts].tail(lookback_days)["Close"]
    if len(window) < lookback_days // 2:
        return None
    return window.iloc[-1] / window.max()
