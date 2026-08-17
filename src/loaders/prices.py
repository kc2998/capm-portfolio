"""Point in time price loader: daily OHLCV prices for the S&P 500 universe.

Produces cached daily prices for every CIK that has ever been a member of the
S&P 500 (`src/universe/point_in_time.py`), keyed by (cik, ticker) rather than
cik alone: a single CIK can hold more than one concurrently priced security
(a dual class share, e.g. News Corp's NWSA/NWS) as well as more than one
ticker over time (a rename, e.g. Priceline to Booking Holdings).

Full methodology, every `yfinance` behavior discovered while building this
(ticker recycling, the delisted coverage gap, dual class shares, a CIK
misattribution found in the universe module along the way), and the
evidence behind every non-obvious decision are recorded in
`notebooks/logs/loaders_construction.md`. This module is the promoted, clean
implementation; that file is the reasoning behind it.
`notebooks/exploring_loaders.ipynb` is where this was originally built and
validated, kept as the historical record.
"""

import logging

import pandas as pd
import yfinance as yf

from src.universe.point_in_time import DATA_PROCESSED, DATA_RAW, base_ticker, build_universe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths, resolved relative to the project root via the universe module's own
# constants, rather than duplicated, so both loaders share one convention.
# ---------------------------------------------------------------------------

PRICES_RAW_DIR = DATA_RAW / "prices"
PRICES_COVERAGE_PATH = DATA_PROCESSED / "prices_coverage.parquet"

# Ordinary weekend/holiday slack around a requested start date, not genuine
# ambiguity: BKNG landing on 2018-04-02 for a requested 2018-03-31 is this;
# PCLN's real gap (over a decade) is not.
CLASSIFY_TOLERANCE_DAYS = 45


# ---------------------------------------------------------------------------
# Ticker translation
# ---------------------------------------------------------------------------

def to_yfinance_ticker(ticker):
    """Translate a universe ticker to the format `yfinance` expects.

    Strips the book CSV's BASE-YYYYMM disambiguation suffix (`base_ticker`,
    already built for the universe module) before translating whatever
    period based multi class notation remains to `yfinance`'s hyphen
    convention (`BRK.B` -> `BRK-B`). The suffix carries no information this
    translation needs to preserve: the date range for a vendor call always
    comes from `ticker_history`'s own `start_date`/`end_date` columns, never
    from parsing the ticker string itself.
    """
    return base_ticker(ticker).replace(".", "-")


# ---------------------------------------------------------------------------
# Classifying a ticker's real, current vendor status
# ---------------------------------------------------------------------------

def _classify_from_probe(probe, expected_start, tolerance_days=CLASSIFY_TOLERANCE_DAYS):
    """Pure classification logic, given an already fetched probe frame.

    Split out from `classify_ticker` so this decision, three ways to read a
    vendor response, is testable without a network call:

    - empty: genuinely retired, no successor (yet).
    - reaches back to at or before `expected_start` (within `tolerance_days`):
      still current, safe to treat as one continuous series.
    - starts well after `expected_start`: the ticker has been recycled by an
      unrelated, currently trading company.
    """
    if probe.empty:
        return "retired"
    actual_start = probe.index.min().tz_localize(None).normalize()
    if actual_start <= pd.Timestamp(expected_start) + pd.Timedelta(days=tolerance_days):
        return "current"
    return "recycled"


def classify_ticker(ticker, expected_start, tolerance_days=CLASSIFY_TOLERANCE_DAYS):
    """Classify a ticker against what the vendor actually serves for it now.

    `ticker_history`'s own shape cannot reliably say whether a ticker is
    genuinely retired or just administratively relabeled: `GOOGL` (still
    trading; Wikipedia simply stopped recording its alternation with `GOOG`)
    and `CMCSK` (genuinely eliminated in a 2015 share class conversion)
    produce the identical "stopped reappearing" shape. Only the vendor's
    current answer distinguishes them, so this always makes a live call
    rather than inferring from local data.
    """
    yf_ticker = to_yfinance_ticker(ticker)
    probe = yf.Ticker(yf_ticker).history(period="max")
    return _classify_from_probe(probe, expected_start, tolerance_days)


# ---------------------------------------------------------------------------
# Per CIK ticker spans and fetching
# ---------------------------------------------------------------------------

def ticker_spans_for_cik(cik, ticker_history):
    """Compute each distinct ticker a CIK used, with its own safe fetch span.

    Groups `ticker_history`'s rows by ticker string, not by row order, so a
    ticker's fragmented occurrences (a dual class share alternating with its
    sibling in the source's own monthly snapshots, e.g. `NWSA`/`NWS`,
    `GOOG`/`GOOGL`) collapse into one span rather than looking like repeated
    retirements.

    Each distinct ticker is then classified (`classify_ticker`) rather than
    trusted from its own `end_date` alone. A "current" ticker gets its start
    pulled back to the CIK's earliest known date rather than its own,
    narrower start, since the vendor's own data already reaches back
    further (confirmed for `BKNG`, `GOOGL`, `NWSA`, `FISV`); anything else
    keeps its own observed start and end, the honest span to fetch.
    """
    rows = ticker_history[ticker_history["cik"] == cik]
    cik_start = rows["start_date"].min()

    spans = []
    for ticker, group in rows.groupby("ticker"):
        own_start = group["start_date"].min()
        own_end = None if group["end_date"].isna().any() else group["end_date"].max()
        status = classify_ticker(ticker, own_start)
        start, end = (cik_start, None) if status == "current" else (own_start, own_end)
        spans.append({"ticker": ticker, "start_date": start, "end_date": end, "status": status})
    return pd.DataFrame(spans)


def fetch_cik_prices(cik, ticker_history):
    """Fetch daily OHLCV for every distinct ticker a CIK used.

    Returns a dict keyed by ticker, not one combined frame: a dual class CIK
    has two genuinely separate, independently priced securities that must
    never be merged. Picking the correct one for a given date is
    `ticker_on`'s job (`src/universe/point_in_time.py`), not this
    function's.
    """
    spans = ticker_spans_for_cik(cik, ticker_history)
    results = {}
    for _, row in spans.iterrows():
        yf_ticker = to_yfinance_ticker(row["ticker"])
        end = None if pd.isna(row["end_date"]) else row["end_date"]
        results[row["ticker"]] = yf.Ticker(yf_ticker).history(start=row["start_date"], end=end)
    return results


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def save_cik_prices(cik, prices_by_ticker):
    """Cache one CIK's fetched prices as a single parquet file, long format.

    Empty ticker frames are dropped before writing: they carry no data, and
    their fallback column schema differs from a successful fetch's (an
    extra `Adj Close`, missing `Dividends`/`Stock Splits`), which would
    otherwise corrupt the combined frame's dtypes for no benefit. Coverage
    (which tickers were attempted and failed) is tracked separately, by
    `build_prices`, not reconstructed from this file: once a failure is
    dropped here, there is nothing left in this file to reconstruct it
    from.
    """
    PRICES_RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = [df.assign(ticker=ticker) for ticker, df in prices_by_ticker.items() if not df.empty]
    combined = pd.concat(frames) if frames else pd.DataFrame(columns=["ticker"])
    combined.to_parquet(PRICES_RAW_DIR / f"{cik}.parquet")
    return combined


def load_cik_prices(cik):
    """Load a CIK's cached prices, or None if not yet fetched."""
    path = PRICES_RAW_DIR / f"{cik}.parquet"
    return pd.read_parquet(path) if path.exists() else None


# ---------------------------------------------------------------------------
# Point in time price lookup
# ---------------------------------------------------------------------------

def close_on_or_before(prices, ticker, as_of):
    """Point in time close: the most recent trading day at or before as_of.

    Never a later date, per the README's no-look-ahead rule. Returns None if
    the ticker has no data at all, or as_of predates its earliest session.
    Validated against a toy weekend-gap case and real usage across hundreds
    of companies in notebooks/exploring_factors.ipynb, Parts 1 and 5.
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    close = ticker_prices.asof(as_of_ts)["Close"]
    return None if pd.isna(close) else close


def next_open_after(prices, ticker, as_of):
    """Point in time open: the next trading session's open strictly after as_of.

    The execution-timing counterpart to close_on_or_before. A signal is
    computed from the close on or before the rebalance date, but per the
    README's no-lookahead rule, an order can't execute at that same
    session's close, since the close isn't known until the session ends;
    it executes at the following session's open instead. Returns None if
    the ticker has no data at all, or as_of is at or after its last session.
    Validated against a toy weekend-gap case and real usage in
    notebooks/exploring_backtest.ipynb, Part 8.
    """
    ticker_prices = prices[prices["ticker"] == ticker].sort_index()
    if ticker_prices.empty:
        return None
    as_of_ts = pd.Timestamp(as_of).tz_localize(ticker_prices.index.tz)
    window = ticker_prices.loc[ticker_prices.index > as_of_ts]
    if window.empty:
        return None
    open_price = window.iloc[0]["Open"]
    return None if pd.isna(open_price) else open_price


# ---------------------------------------------------------------------------
# The build: expensive, network-bound, meant to be run occasionally
# ---------------------------------------------------------------------------

def build_prices(force_refresh=False):
    """Fetch (or load) prices for every CIK that ever appears in `ticker_history`.

    Loads `data/processed/prices_coverage.parquet` directly if present and
    `force_refresh` is False, the common case, mirroring `build_universe`'s
    own two branch contract. Otherwise fetches every CIK from scratch and
    writes a fresh coverage report; there is no partial cache shortcut
    inside that rebuild branch, deliberately.

    `save_cik_prices` drops empty ticker frames before writing, so a
    coverage report reconstructed from an existing per CIK cache can never
    see a past failure. That was the actual bug found while building this:
    an apparently perfect "0 empty" result that was really evidence the
    information needed to see failures had already been discarded before it
    reached the cache. Coverage is therefore always computed fresh, from
    the live fetch results, in the same pass that writes the cache, and
    persisted immediately rather than derived from disk after the fact.

    Returns the coverage DataFrame (`cik`, `ticker`, `rows`), one row per
    distinct ticker ever attempted for that CIK.
    """
    _, ticker_history = build_universe()

    if not force_refresh and PRICES_COVERAGE_PATH.exists():
        return pd.read_parquet(PRICES_COVERAGE_PATH)

    all_ciks = ticker_history["cik"].dropna().unique()
    coverage = []
    for i, cik in enumerate(all_ciks):
        prices = fetch_cik_prices(cik, ticker_history)
        save_cik_prices(cik, prices)
        for ticker, df in prices.items():
            coverage.append({"cik": cik, "ticker": ticker, "rows": len(df)})

        if (i + 1) % 50 == 0:
            logger.info("%d/%d CIKs done", i + 1, len(all_ciks))

    coverage_df = pd.DataFrame(coverage)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    coverage_df.to_parquet(PRICES_COVERAGE_PATH, index=False)
    return coverage_df
