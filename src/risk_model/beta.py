import pandas as pd

def _weekly_returns(prices, ticker, as_of, window_weeks):
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window_start = as_of_ts - pd.DateOffset(weeks=window_weeks)
    closes = ticker_prices.loc[window_start:as_of_ts, "Close"]
    weekly = closes.resample("W-FRI").last().dropna()
    return weekly.pct_change().dropna()

def beta_as_of(prices, ticker, market_prices, as_of, market_ticker="SPY", window_weeks=104):
    """Trailing beta: weekly returns, 104 week window, refit fresh at as_of."""
    stock_returns = _weekly_returns(prices, ticker, as_of, window_weeks)
    market_returns = _weekly_returns(market_prices, market_ticker, as_of, window_weeks)
    if stock_returns is None or market_returns is None:
        return None

    aligned = pd.concat([stock_returns, market_returns], axis=1, join="inner")
    aligned.columns = ["stock", "market"]
    if len(aligned) < window_weeks // 2:
        return None

    x, y = aligned["market"], aligned["stock"]
    return x.cov(y) / x.var()
