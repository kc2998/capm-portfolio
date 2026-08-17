import pandas as pd
import yfinance as yf

from src.universe.point_in_time import DATA_RAW

MARKET_RAW_DIR = DATA_RAW / "market"

def fetch_market_prices(ticker="SPY", start=None, end=None):
    """Fetch daily OHLCV for the market proxy from yfinance."""
    if start is None and end is None:
        return yf.Ticker(ticker).history(period="max")
    return yf.Ticker(ticker).history(start=start, end=end)

def save_market_prices(ticker, prices):
    """Cache as one parquet file, same shape as a CIK price cache
    (a 'ticker' column), so close_on_or_before works unmodified.

    Returns the tagged frame actually written, not the caller's original.
    """
    MARKET_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tagged = prices.assign(ticker=ticker)
    tagged.to_parquet(MARKET_RAW_DIR / f"{ticker}.parquet")
    return tagged

def build_market(ticker="SPY", force_refresh=False):
    """Same two branch contract as build_prices: load cache if present,
    else fetch, cache, and return."""
    if not force_refresh:
        cached = load_market_prices(ticker)
        if cached is not None:
            return cached
    prices = fetch_market_prices(ticker)
    return save_market_prices(ticker, prices)

def load_market_prices(ticker="SPY"):
    path = MARKET_RAW_DIR / f"{ticker}.parquet"
    return pd.read_parquet(path) if path.exists() else None


