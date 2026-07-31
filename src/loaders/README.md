# Prices: point in time daily OHLCV for the S&P 500 universe

Answers "what did this security actually trade at on date D," for every entity that has ever
been a member of the S&P 500, using the historically correct ticker for each date range
(`src/universe/point_in_time.py`), cached locally rather than fetched live.

This file explains what the module produces and how to call it. The full methodology, every
`yfinance` behavior found while building it, and the evidence behind every non-obvious
decision, is in `notebooks/logs/loaders_construction.md`. That file records why; this one
records how to use the result.

## What it produces

**One parquet file per CIK** under `data/raw/prices/{cik}.parquet` (gitignored, fetched by
`build_prices()` when missing), long format, one row per trading day per ticker:

| column | type | meaning |
|---|---|---|
| (index) | tz-aware `DatetimeIndex` | the trading date, as `yfinance` reports it (US Eastern) |
| `Open`, `High`, `Low`, `Close` | float | split and dividend adjusted, per `yfinance`'s default |
| `Volume` | int | shares traded |
| `Dividends`, `Stock Splits` | float | per-day corporate action amount, `0.0` on an ordinary day |
| `ticker` | string | which of the CIK's tickers this row belongs to |

A CIK contributes more than one distinct `ticker` value when it held more than one
concurrently priced security (a dual class share, e.g. News Corp's `NWSA`/`NWS`) or renamed
over time (e.g. Priceline to Booking Holdings); see the toy examples below for both shapes.

**One coverage report** at `data/processed/prices_coverage.parquet`:

| column | type | meaning |
|---|---|---|
| `cik` | Int64 | the entity |
| `ticker` | string | the distinct ticker attempted |
| `rows` | int | how many trading days came back; `0` means the fetch was attempted and failed |

## How to use it

```python
from src.loaders.prices import build_prices, load_cik_prices
from src.universe.point_in_time import build_universe, ticker_on

# Loads the existing coverage report and cached files if present (the
# common case); only fetches from yfinance if the coverage report is
# missing or force_refresh=True.
coverage = build_prices()

universe_spans, ticker_history = build_universe()

# What did CIK 1075531 (Priceline / Booking Holdings) close at on this date?
ticker = ticker_on(ticker_history, 1075531, "2015-06-30")   # "PCLN"
prices = load_cik_prices(1075531)
prices[prices["ticker"] == ticker].loc["2015-06-30":"2015-06-30", "Close"]
```

**Always resolve the ticker via `ticker_on`, not by assuming which one is "the" series for a
CIK.** A cached file can hold more than one ticker, and which one is period-correct for a
given date is exactly what `ticker_on` answers.

## Toy examples, from the real data

**A rename, folded into one continuous series.** Priceline renamed to Booking Holdings in
2018; `ticker_history` records two ticker intervals for CIK 1075531, but `yfinance` already
serves the pre-rename years under the current ticker, so this CIK's cached file holds one
continuous series under `BKNG`, not two:

| ticker | rows | date range |
|---|---|---|
| `BKNG` | 3,059 | 2014-06-02 to present |
| `PCLN` | 0 | attempted, empty: the old ticker has since been reused by an unrelated company (see the log) |

**A dual class share, genuinely two series.** News Corp's CIK (1564708) holds two
concurrently traded, independently priced securities, both present in the cached file, neither
one dropped in favor of the other:

| ticker | rows | date range |
|---|---|---|
| `NWSA` | 3,059 | 2014-06-02 to present |
| `NWS` | 3,059 | 2014-06-02 to present |

**A genuine gap, honestly reported, not silently dropped.** Comcast eliminated its `CMCSK`
special share class in a 2015 conversion; that ticker's fetch is attempted (per
`ticker_history`) and comes back empty, recorded as `rows = 0` in the coverage report rather
than omitted:

| cik | ticker | rows |
|---|---|---|
| 1166691 | `CMCSA` | 3,059+ |
| 1166691 | `CMCSK` | 0 |

## Caveats worth knowing before relying on this

- **Delisted coverage is a real, quantified gap, not just a documented risk.** Measured
  against the full universe: roughly 91% of still-active tickers return real data, versus
  roughly 49% of delisted ones. Free vendor coverage genuinely thins out for names that have
  left the index, exactly the reason a point in time universe needs to measure this rather
  than assume it.
- **The index is tz-aware, not a plain ISO date string.** `universe_spans` and
  `ticker_history` use plain date strings; this module's cached prices keep `yfinance`'s own
  tz-aware `DatetimeIndex` (US Eastern) as returned. Normalizing the two to compare directly is
  not yet built; see the log's open items.
- **Ticker recycling is checked, not eliminated.** `classify_ticker` distinguishes a
  genuinely current ticker from one that has been reused by an unrelated, live company by
  comparing the vendor's actual earliest date against what's expected, with a 45 day
  tolerance for ordinary weekend and holiday slack. This was verified against every real case
  found while building it (renames, dual class shares, retirements, recycling), not proven
  exhaustively; a case shaped differently from all of these could in principle still slip
  through.
- **A CIK can legitimately fetch prices twice for the same real security.** `GOOGL`, `GOOG`,
  `FOXA`, `FOX`, and a handful of others are attributed to two different CIKs in
  `ticker_history` (a known, documented gap in the universe module, see
  `notebooks/logs/universe_construction.md`'s Open items). Both CIKs will be fetched and
  cached independently; the price returned for any given date is the same real market price
  regardless of which CIK's file it comes from, so correctness holds as long as a lookup
  always goes through `ticker_on` for a specific `(cik, date)`, never by concatenating two
  CIKs' files into one assumed-continuous series.
- **The coverage report is a snapshot, not incrementally maintained.** `build_prices()`
  either loads the existing report or rebuilds everything from scratch; there is no
  "fetch only the CIKs added since last time" path. Simple by design, revisit if the universe
  is refreshed often enough for this to become a real cost.

## Rebuilding

```bash
python -m scripts.build_prices            # load if present, else build
python -m scripts.build_prices --refresh --verbose   # force a full rebuild, with progress
```

A full rebuild makes one or more requests per distinct ticker (a live probe via
`classify_ticker`, plus the actual price fetch), roughly 900 to 1,000 requests across the
full universe, and takes fifteen to twenty minutes; there is no cheaper intermediate cache to
fall back on the way the universe module's Wikipedia snapshots are, since asking the vendor
directly is the entire point of this module. See `notebooks/logs/loaders_construction.md` for
what each design decision cost to get right.
