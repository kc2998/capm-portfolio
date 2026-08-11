"""Illiquidity factor (Amihud 2002): mean absolute return over dollar volume.

Built and validated in notebooks/exploring_factors.ipynb, Part 3j.
"""

import pandas as pd


def illiquidity_factor(prices, ticker, as_of, lookback_days=20):
    """Raw illiquidity factor (Amihud 2002): mean of daily absolute return
    divided by dollar volume, over a trailing window.

    Higher values mean a given dollar of trading moves the price more,
    i.e. less liquid. Same 20 trading day window as volume_shock_factor:
    like that factor, this lives in the README's weekly horizon table, a
    fast-changing signal rather than a slow one.

    Requires at least half of lookback_days worth of trailing days
    actually present, same reasoning as every other rolling-window factor
    here. A day with zero dollar volume is dropped from the average
    rather than producing an infinite ratio, since a halted or untraded
    day says nothing about liquidity on days that did trade.

    Confirmed against a real 60-company sample (Part 3j): the most liquid
    names (TSLA, AVGO, LLY, COST, ORCL) are genuine mega-caps, the least
    liquid (JKHY, SYF, ROL, TPR, MKTX) comparatively smaller, matching
    the well documented inverse relationship between size and Amihud
    illiquidity.

    Returns None if fewer than half of lookback_days days remain after
    dropping zero-volume days, or if the ticker has no data at all.
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window = ticker_prices.loc[:as_of_ts].tail(lookback_days + 1)
    if len(window) < 2:
        return None

    returns = window["Close"].pct_change().dropna()
    dollar_volume = (window["Close"] * window["Volume"]).reindex(returns.index)

    ratios = (returns.abs() / dollar_volume)[dollar_volume > 0]
    if len(ratios) < lookback_days // 2:
        return None
    return ratios.mean()
