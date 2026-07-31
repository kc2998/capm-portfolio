# Universe: point in time S&P 500 membership

Answers two questions without look ahead: "who was a member of the S&P 500 on date D," and
"what ticker did a given company trade under on date D." Built from two sources, Wikipedia's
revision history (2008 to present) and a book derived CSV (1996 to 2008), reconciled against
each other and, where possible, verified against primary source SEC filings.

This file explains what the module produces and how to call it. The full methodology, every
source considered and rejected, every bug found while building it, and the evidence behind
every non-obvious decision, is in `notebooks/logs/universe_construction.md`. That file
records why; this one records how to use the result.

## What it produces

Two tables, saved as parquet under `data/processed/` (gitignored, rebuilt by
`build_universe()` when missing):

**`universe_spans`**, membership, one row per interval a ticker was continuously a member:

| column | type | meaning |
|---|---|---|
| `ticker` | string | the symbol as its source reported it |
| `cik` | nullable Int64 | SEC's filer identifier, where derivable |
| `start_date` | string, ISO date | first date observed as a member |
| `end_date` | string, ISO date, or null | last date observed as a member; null means still active |
| `source` | string | `wikipedia_revision`, `clenow_norgate`, or `clenow_norgate+wikipedia_revision` for a membership stitched across the 2008 boundary |
| `left_censored` | bool | `True` if `start_date` is the first date its era can observe; true join date is unknown, see the log |

**`ticker_history`**, symbol identity, separate from membership, one row per interval a CIK used a given ticker:

| column | type | meaning |
|---|---|---|
| `cik` | nullable Int64 | the entity, stable across renames |
| `ticker` | string | the symbol in use during this interval, corrected where an SEC filing check found a mismatch |
| `start_date`, `end_date` | string, ISO date, or null | the interval this ticker was in use; null end means still current |
| `source` | string | which era this entry came from |
| `verified` | bool | `True` if confirmed period-correct or evidence-backed; `False` if still flagged for manual review |
| `original_ticker` | nullable string | the book file's original value, populated only where a filing check corrected it |
| `evidence` | nullable string | the citing SEC accession number and quoted sentence, populated only where a filing check found a match or mismatch |

## How to use it

```python
from src.universe.point_in_time import build_universe, membership_on, ticker_on

# Loads the existing parquet files if present (the common case); only
# rebuilds from Wikipedia and SEC if they're missing or force_refresh=True.
universe_spans, ticker_history = build_universe()

# Was AAPL a member on this date?
"AAPL" in membership_on(universe_spans, "2015-06-30")   # True

# What did CIK 1075531 (Priceline / Booking Holdings) actually trade as?
ticker_on(ticker_history, 1075531, "2015-06-30")   # "PCLN"
ticker_on(ticker_history, 1075531, "2022-01-01")   # "BKNG"
```

**Use `ticker_on`, not `universe_spans["ticker"]`, when a real symbol is needed for a price
vendor call.** `universe_spans` reports whatever string its source used, which for the book
era may be a retroactively applied later ticker. `ticker_history` is what tracks the actual
symbol in force on a given date, and is the one built to answer that question.

## Toy examples, from the real data

**A continuous membership stitched across the two sources.** Apple was already a member
when the book file's tracking begins in 1996, stayed one straight through the 2008 boundary
where Wikipedia coverage picks up, and is still active:

| ticker | cik | start_date | end_date | source | left_censored |
|---|---|---|---|---|---|
| AAPL | 320193 | 1996-01-02 | (null, still active) | `clenow_norgate+wikipedia_revision` | `True` |

`left_censored = True` means "already a member when observation began," not "joined this
exact day," the true join date predates the data entirely and is unrecoverable from either
source.

**A rename, in `ticker_history`, not `universe_spans`.** Priceline never left the index when
it renamed to Booking Holdings, so membership is one continuous fact; the ticker changed,
which is exactly what a second table exists to track:

| cik | ticker | start_date | end_date | verified | source |
|---|---|---|---|---|---|
| 1075531 | PCLN | 2014-05-31 | 2018-03-31 | `True` | `wikipedia_revision` |
| 1075531 | BKNG | 2018-03-31 | (null, current) | `True` | `wikipedia_revision` |

**An entry still flagged for manual review.** Not every pre-2008 ticker has been confirmed
one way or the other yet:

| cik | ticker | start_date | end_date | verified |
|---|---|---|---|---|
| 78890 | BCO | 1996-01-02 | 1996-01-12 | `False` |

This one is a genuinely hard case, not a simple lookup miss: the company (Pittston, later
The Brink's Company) restructured into two tracking stock pairs in the exact same window,
so there are four plausible replacement tickers, not one. See the log for the full story.

## Caveats worth knowing before relying on these tables

- **Precision differs by era.** `wikipedia_revision` spans are accurate to the month
  (the monthly snapshot cadence); `clenow_norgate` spans to the day the book file recorded a
  change.
- **Pre-2008 tickers may carry a `BASE-YYYYMM` suffix** (a ticker recycling disambiguator,
  e.g. `H-200107`). Multi class tickers are normalized to a period (`BRK.B`); `yfinance`
  expects a hyphen (`BRK-B`), a translation that belongs at the price loader boundary, not
  here.
- **CIK coverage has known, explained gaps.** Absent before ~2014 for the wiki era; for the
  book era, resolved for about half of spans, the rest split between suffixed tickers (no
  CIK possible by design) and unmatched bare tickers.
- **`verified = False` is a to-do list, not a correction.** As of the last build, 207 of
  `ticker_history`'s 2,809 entries are still flagged: 93 with no CIK match at all, 111
  checked against SEC filings but inconclusive, 3 genuinely ambiguous corporate actions. None
  of this blocks using the universe; it only means the pre-2008 ticker string for those
  specific spans hasn't been independently confirmed.
- **The 2008 to 2019 window is Wikipedia only**, except where a membership was stitched
  across the boundary. The book file's own data for that overlapping period is deliberately
  not blended in; see the log for why.
- **Dual class share treatment is an open decision.** `GOOG`/`GOOGL`, `FOXA`/`FOX`,
  `NWSA`/`NWS` are currently kept as separate rows, not yet a settled call for factor
  computation.

## Rebuilding

```bash
python -m scripts.build_universe            # load if present, else build
python -m scripts.build_universe --refresh --verbose   # force a full rebuild, with progress
```

A full rebuild from nothing (all caches deleted) takes several minutes and makes several
hundred requests, to Wikipedia and SEC; with the intermediate caches under `data/raw/`
already present, `--refresh` re-derives both tables from them in a couple of seconds
without touching the network again. See `notebooks/logs/universe_construction.md` for what
each cache holds and why deleting one is an explicit, deliberate action rather than
something that expires automatically.
