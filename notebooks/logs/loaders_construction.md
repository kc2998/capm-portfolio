# Price loader construction: findings log

Record of what was learned while building the point in time price loader in
`notebooks/exploring_loaders.ipynb`. Started 2026-07-30.

This file exists so the reasoning behind the price loader survives outside the notebook. The
README states the decisions; this file states the evidence, organized to follow the notebook's
own order: the vendor's raw shape first, then renames and recycling, then dual class shares,
then the deeper CIK problem that search surfaced, then caching and scale, then coverage.
Abandoned approaches and validation exercises live here in prose rather than as dead code left
in the notebook for someone to puzzle over later.

## The task

Answer, without look ahead: "what did this security's price actually do on date D," for every
entity that was ever a member of the S&P 500, per `universe_spans` (`src/universe/README.md`),
using the historically correct ticker for each date range, per `ticker_history`, not whatever
string a source happens to report today.

| Requirement | Source | Why it matters |
|---|---|---|
| Cache locally, never fetch live | README, "Prices are cached locally rather than fetched live" | `yfinance` serves split/dividend adjusted prices that change retroactively as new corporate actions occur; a backtest whose inputs shift underneath it cannot be reproduced |
| Measure and report missing coverage, never drop silently | README, "Delisted securities are the weak point of free price data" | delisted names are the entire point of a point in time universe; free sources have their weakest coverage exactly there, and silent dropping would reintroduce survivorship bias at the data layer after it was removed at the universe layer |
| Translate ticker format at the vendor boundary | README, "Ticker format differs between sources" | tickers are stored internally with a period (`BRK.B`), a convention already settled for the universe; `yfinance` expects a hyphen (`BRK-B`) |
| Point in time discipline in how prices get used | README, "Key concepts the implementation must respect" | a rebalance uses the close as of the rebalance date; any resulting order executes at the next session's open. The loader's job is to have both values available; enforcing which one is used where is the backtest engine's job downstream |

`membership_on(universe_spans, date)` (`src/universe/point_in_time.py`) defines the scope,
which CIKs need prices at all, and for what date ranges. `ticker_on(ticker_history, cik, date)`
defines the symbol, the historically correct ticker for a CIK on a given date. Reading
`universe_spans["ticker"]` directly for a price call would be wrong for the book era in exactly
the cases documented in `universe_construction.md` (the retroactive relabeling problem).

## Part 1: the vendor's actual shape, not assumed

Before designing anything, one familiar, currently listed ticker (`AAPL`), full history, no
date restriction, to see what `yfinance` actually returns rather than guessing:

```
shape: (11499, 7)
index: 1980-12-12 to 2026-07-30 (tz-aware, US/Eastern, offset shifts with DST)
columns: Open, High, Low, Close, Volume, Dividends, Stock Splits
```

Two findings that shaped everything after:

- **No `Adj Close` column.** 1980 prices are fractional (around $0.10), only sensible as
  split-adjusted given AAPL's four splits since IPO. `history()` returns adjusted OHLC
  directly by default, with `Dividends` and `Stock Splits` as separate per-day event columns.
  This confirms, rather than merely predicts, the README's caching rationale: these adjusted
  values are exactly the ones that move retroactively as new corporate actions occur, so a raw
  pull must be cached the moment it is made.
- **The index is tz-aware**, `America/New_York` wall clock time with the DST offset baked in,
  not UTC and not a naive date. `universe_spans` and `ticker_history` carry no timezone, a
  mismatch not yet resolved (see Open items).

## Part 2: renames and ticker recycling

### The core danger: a retired ticker can be silently reissued

Testing `PCLN` (Priceline's old ticker before its 2018 rename to Booking Holdings) and `FRC`
(First Republic Bank, seized and delisted May 2023) side by side:

```
PCLN  (196, 7)   2025-10-16 to 2026-07-29
FRC   (0, 6)     $FRC: possibly delisted; no price data found
```

`FRC` behaved as expected, a genuine delisting returns nothing. `PCLN` did not: 196 rows ending
today is not Priceline/Booking Holdings history, the ticker has been recycled, some unrelated,
currently listed company holds that symbol now, and `yfinance` resolves it with no concept of
the entity that used to trade under it, and no warning that anything is wrong. This is the same
ticker-recycling phenomenon already found in the book CSV's `BASE-YYYYMM` suffix during the
universe build, surfacing in a second data source, more dangerous here because nothing signals
the mismatch.

### The vendor folds a rename into the current ticker

`BKNG`'s own full history reaches back to 1999-03-31, Priceline's actual IPO date. The
pre-rename years were not lost, they live under the current ticker. Tested again for a genuine
bankruptcy discontinuity, not just a rename: `GM` (General Motors) has traded as `GM` both
before its 2009 bankruptcy and after its November 2010 relisting as a legally distinct entity.
`yfinance`'s `GM` data starts exactly 2010-11-18, correctly bounded to the new entity, no
contamination from the defunct predecessor. Four real cases now agreed on one pattern:

| Ticker | What happened | Result |
|---|---|---|
| `BKNG` | renamed, same entity | full history since 1999, correctly stitched |
| `GM` | entity dissolved (bankruptcy), ticker reissued to a new entity | bounded correctly to the new entity's own window |
| `FRC` | entity dissolved, ticker not reissued | empty, explicit warning |
| `PCLN` | retired ticker reissued to an unrelated, live company | that company's data, silently |

**Fetching by an entity's current ticker is reliable in every case tested; fetching by any of
its retired tickers is not, and there is no way to tell the difference from the response
alone.**

### Does an explicit date range make the recycling risk safe?

Requesting `PCLN`'s own historical window, `2014-05-31` to `2018-03-31` (rather than
`period="max"`), returned nothing, `possibly delisted`, the same failure as `FRC`, not the
wrong company's recent data. Whatever entity holds `PCLN` today has no data reaching that far
back, so asking for the historically correct window converts a recycled-ticker mismatch into
the already-handled empty-frame failure mode. **Design conclusion: the fetch step must always
pass the segment's own `start_date`/`end_date`, never `period="max"`.** This does not eliminate
the risk entirely (two still-live companies with overlapping history could in principle still
collide), but removes it as the primary concern.

### A bug found only by building the fetch-and-stitch loop

A first, naive version looped over every `ticker_history` segment and fetched each under its
own historical ticker:

```python
def fetch_cik_history(cik):
    segments = ticker_history[ticker_history["cik"] == cik].sort_values("start_date")
    frames = [yf.Ticker(to_yfinance_ticker(s["ticker"])).history(start=s["start_date"], end=s["end_date"])
              for _, s in segments.iterrows()]
    return pd.concat(frames)
```

Run on Priceline/Booking (CIK 1075531): `(2094, 8)`, starting **2018-04-02**, not 2014. The
`PCLN` segment returned empty, exactly as predicted above, and `pd.concat` silently absorbed
it. Four real years of Priceline's own trading history were missing with nothing in the shape
or the date range signaling a failure, the "check the seam" step this cell was meant to run
instead found that one whole side of the seam never existed. The fix: if a CIK's most recent
segment has no `end_date` (still active), fetch once, using the current ticker, across the
full combined range from the earliest segment's own start, rather than one call per historical
segment. Confirmed on the same CIK: `(3059, 7)`, `2014-06-02` to present, the full history
recovered in a single call.

### Ticker format translation

Scanning every ticker in `universe_spans` for punctuation found 14 of 1,407 carrying a period,
in two groups: 6 clean multi-class tickers (`BF.B`, `BRK.B`, `NWS.A`, `RDS.A`, `UA.C`,
`VIA.B`), and 8 also carrying the book CSV's `BASE-YYYYMM` recycling suffix (e.g.
`AFS.A-200011`). The suffix is bookkeeping this project invented to disambiguate two companies
that reused the same ticker at different times, never a string that existed on any exchange;
translating it naively (`.replace(".", "-")` alone) gives `AFS-A-200011`, meaningless to any
vendor. The correct transform, `base_ticker(ticker).replace(".", "-")`, reusing the universe
module's own `base_ticker` helper, checked by hand against all 14 real cases and confirmed
correct. Separately confirmed directly at scale: `BF.B` failed inside a 50-ticker batch
download with the same `possibly delisted` message a genuinely dead ticker gets, `BF-B`
succeeded, `(22, 7)`. That overlapping error message is itself worth remembering, it covers
both "no longer trades" and "not a symbol in the form given," with no way to tell which from
the message alone.

## Part 3: dual class shares

### A search for a genuine multi-rename CIK instead found something bigger

Looking for a CIK with more than one real rename (rather than the single-hop `PCLN`/`BKNG`
case already confirmed), the natural search, CIKs with 3 or more `ticker_history` segments,
surfaced 35 candidates, the largest count 260 segments for one CIK. That is far too many for
a real rename history. Inspecting it directly: CIK 1564708 is News Corp, and `NWSA`/`NWS` are
its two simultaneously traded share classes, both active every day, not a ticker that keeps
changing. `ticker_history`'s schema (one row per interval, implying a single identity handed
off sequentially) has no way to express two tickers being concurrently current for one CIK, so
the monthly snapshot recorded it as if the official ticker kept flipping.

The consequence for a price loader is sharper than for membership counting: the current-ticker
fetch rule from Part 2 would pick whichever ticker the CIK's last segment happens to name,
fetch only that one, and silently never touch the other, a real, separately traded security
dropped entirely with no empty frame, no warning, nothing to suggest anything is missing.
Quieter and worse than every failure mode found so far.

### Verifying against the vendor, not the shape of the data

Confirmed directly (`yf.Ticker("NWSA").history(start="2014-05-31")` returned real data through
today) that `NWSA` never stopped trading, its apparent cutoff was an artifact of which ticker
the snapshot happened to record as official that month. The distinguishing signal between this
and a genuine retirement: `NWSA` appears in many separate occurrences while its CIK remains
active; a genuine retirement (like `PCLN`) appears in exactly one. But this signal alone is not
enough, found by checking two more cases before trusting it:

- **`GOOG`/`GOOGL` (Alphabet, CIK 1288776):** the same alternating pattern, but it stops in the
  data at 2016-05-31, only `GOOG` continues after. `GOOGL` is obviously still real and actively
  traded today; Wikipedia's own table simply stopped recording the alternation, a gap in the
  source's tracking, not evidence of retirement.
- **`CMCSA`/`CMCSK` (Comcast, CIK 1166691):** the identical shape, alternates for three months
  in 2015, then only `CMCSA` continues. But `CMCSK` is genuinely gone (Comcast eliminated that
  share class in a real 2015 conversion), confirmed directly, `yf.Ticker("CMCSK").history(period="max")` returns nothing.

`GOOGL` and `CMCSK` produce the identical "stopped reappearing" shape in the data, one is real
and current, the other is genuinely retired. No refinement of date logic on `ticker_history`'s
own rows distinguishes them; only the vendor's current answer does.

### `classify_ticker`: one mechanism instead of per-case logic

```python
def classify_ticker(ticker, expected_start, tolerance_days=45):
    probe = yf.Ticker(to_yfinance_ticker(ticker)).history(period="max")
    if probe.empty:
        return "retired"
    actual_start = probe.index.min().tz_localize(None).normalize()
    if actual_start <= pd.Timestamp(expected_start) + pd.Timedelta(days=tolerance_days):
        return "current"
    return "recycled"
```

Verified against every case found in the notebook at once: `PCLN` -> `recycled`, `CMCSK` ->
`retired`, `GOOGL`, `NWSA`, `BKNG` -> `current`, all five correct. `tolerance_days=45` absorbs
ordinary weekend/holiday slack (`BKNG` landing on 2018-04-02 for a requested 2018-03-31)
without blurring `PCLN`'s real gap of over a decade.

Rebuilt `ticker_spans_for_cik` on top of this, grouping `ticker_history` by ticker string (so
fragmented occurrences collapse into one span regardless of what alternates between them), and
classifying each distinct ticker rather than trusting its own `end_date`:

```python
def ticker_spans_for_cik(cik):
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
```

Tested against every case found so far at once: Priceline (`PCLN` recycled, `BKNG` current),
News Corp (both current), Alphabet (both current), Comcast (`CMCSA` current, `CMCSK` retired).
`fetch_cik_prices`, which loops these spans and returns a dict keyed by ticker rather than one
combined frame (dual class securities must never be merged), confirmed both `NWSA` and `NWS`
come back as full, independent, identically shaped series, `(3059, 7)` each, neither silently
dropped, the original failure mode this design exists to fix.

One real bug found while wiring this together: building the spans as a `DataFrame` and reading
`row["end_date"]` compared to `None` directly works only when a CIK's column has a mix of real
values and `None` (keeping pandas' dtype as `object`). For News Corp, both rows have
`end=None` and nothing else, so the whole column becomes `float64` and `None` becomes `NaN`, a
type `yf.Ticker().history()` cannot parse as an `end` argument. Fixed by checking
`pd.isna(row["end_date"])`, which catches both uniformly, rather than trusting `None` survives
a `DataFrame` round trip unchanged.

### Confirming this generalizes: three way splits and a genuine round trip rename

Under Armour (CIK 1336917) confirmed a genuine three-way split, `UA` (70 segments), `UAA`
(65), `UA.C` (4), handled correctly with no changes to the function. Fiserv (CIK 798354)
confirmed a genuine round trip rename, `FISV` to `FI` in 2023 and back to `FISV` in 2025:
`classify_ticker` correctly returns `current` for `FISV` (threading straight through the `FI`
interlude) and `retired` for `FI` (no successor as of this writing). Checked whether `FI`'s
bounded fetch was filling a real gap or duplicating data `FISV` already has: `FISV`'s own
fetch already has real rows inside the `FI` window, the vendor folds the interlude in here too.
Keeping both as separate dict entries is harmless for correctness (any lookup resolves the
period-correct ticker via `ticker_on` regardless of storage shape), just mildly redundant, not
a bug worth engineering around.

## Part 4: a deeper CIK problem, found by checking whether 45 test cases were enough

Before trusting this design against the full universe, it was worth checking directly whether
every edge case had actually been found, rather than assuming a segment-count search had
caught everything. It structurally could not have: that search only surfaces a CIK whose
ticker *alternates*; a single-ticker company whose own CIK simply got corrected mid-history,
with no alternation at all, would show up as two CIKs, one row each, invisible to a "3 or more
segments" search.

```python
ticker_history.groupby("ticker")["cik"].nunique()
```

**39 tickers**, not 4, are attributed to more than one CIK somewhere in `ticker_history`.
Checked which are also ambiguous in `universe_spans` itself (since `attach_cik`'s "latest
observed wins" rule already resolved `GOOGL`/`FOXA` to one CIK there, even though
`ticker_history` had two, if that generalizes, most of the 39 carry no real consequence):

```
7 of 39 also ambiguous in universe_spans: APC, BBBY, BBT, LB, NE, STI, XOM
```

32 of the 39 do resolve to a single CIK in `universe_spans`, confirming the mitigation
generalizes for most of them. The remaining 7 are sharper: every one splits exactly at the
book/wiki era boundary (`end_date` 2008-01-30 on one side, `start_date` 2008-01-31 on the
other), too precise to be seven coincidental real corporate events landing on the same date.
Confirmed directly for `XOM` against SEC's live registry: it currently maps to CIK 2115436,
"ExxonMobil Holdings Corp," not the long-standing "Exxon Mobil Corporation" CIK (34088)
Wikipedia's table has stably reported, evidence of a recent holding-company reorganization
with no real trading interruption, the same shape as Alphabet's, just caught by the book-era
backfill (`backfill_book_cik`, which resolves a ticker's CIK from SEC's registry as of whenever
it was fetched, not as of the historical period) rather than the wiki-era `attach_cik` step.

### An attempted fix, and why it was reverted

Fixed `build_ticker_history_wiki` to resolve each ticker string to its latest reported CIK
before grouping, mirroring `attach_cik`'s own rule:

```python
tracked = tracked.assign(cik=tracked.groupby("ticker")["cik"].transform("last"))
```

Rebuilding confirmed this correctly merged `GOOG`/`GOOGL` (1288776 into 1652044) and
`FOX`/`FOXA` (1308161 into 1754301), each summing exactly to their prior totals, 292 = 49 +
243, 261 = 141 + 120, no discontinuity in either pair's actual price history at the merge
boundary (checked directly against `yfinance`). But the total `ticker_history` row count went
*up*, not down, 2,809 to 2,872, and inspection revealed why: `896159` (ACE Limited, which
acquired the original Chubb Corporation and renamed itself Chubb Limited in 2016, inheriting
the `CB` ticker) grew from 4 rows to 42, and a brand new CIK, `833444` (Johnson Controls and
Tyco International, merged in 2016), appeared with 59. Both are genuine mergers between two
*different* companies, not administrative CIK corrections for the same one; taking "the
ticker's latest reported CIK, unconditionally" merged old Chubb Corporation's entire
pre-merger history into ACE's CIK, and Johnson Controls' into Tyco's, fabricating an
alternation pattern between two entities that were never concurrent, a worse problem than the
one being fixed. Reverted; `ticker_history` and `universe_spans` are back to their original,
validated state.

**The distinguishing signal, whether merging two CIK buckets for the same ticker creates a new
alternation pattern versus resolves one that already existed continuously, is not yet
implemented.** Left as a known, documented gap (`universe_construction.md`'s Open items)
rather than force a fix under time pressure.

### Practical consequence for the price loader

For `GOOGL`/`FOXA`, one CIK is orphaned, `membership_on()` never resolves to it, so fetching
both wastes effort but never double counts. For `XOM` and the other 6, both CIKs are genuinely
recognized members at different times, book era under one, wiki era under the other. The price
returned for a given date is the same real market price regardless of which CIK's file it
comes from, so correctness holds as long as a lookup always goes through `membership_on()` +
`ticker_on()` for a specific `(cik, date)`, never by concatenating two CIKs' stored files into
one assumed non-overlapping series. Stated as an explicit constraint on downstream consumption,
not an implicit assumption; see `src/loaders/README.md`.

## Part 5: caching, storage shape, and batching at scale

### Storage shape

Three options considered: one long table for every security stacked together, a wide
ticker-per-column pivot, or one parquet file per CIK. Chosen: **one file per CIK**, long format
inside (`date, ticker, OHLCV`). A dual-class CIK genuinely needs two independent series (Part
3), and a renamed CIK's fetch already collapses to one continuous series on its own (Part 2),
neither shape change is something the storage layer itself needs to special case.

```python
def save_cik_prices(cik, prices_by_ticker):
    frames = [df.assign(ticker=ticker) for ticker, df in prices_by_ticker.items() if not df.empty]
    combined = pd.concat(frames) if frames else pd.DataFrame(columns=["ticker"])
    combined.to_parquet(PRICES_RAW_DIR / f"{cik}.parquet")
    return combined
```

Round trip verified exact (`loaded.equals(saved)` is `True`) on the Priceline/Booking case, no
silent corruption of the timezone aware index through a parquet write and read.

### Batching mechanics

`yf.download()` on a small mixed batch (`AAPL`, `MSFT`, `PCLN`, a deliberately invalid
ticker) confirmed one bad symbol does not fail the whole batch, but the columns are jagged,
not uniform: a failed ticker contributes an extra `Adj Close` field the successful ones do
not have (`yfinance` falls back to a different schema when a call finds no data), and
`download()` returns no `Dividends`/`Stock Splits` columns at all, unlike `Ticker().history()`.
The two calls are not equivalent.

### Rate limits and full-scale timing

50 real, currently active tickers via `yf.download()`: 1.4 seconds, a first real baseline.
Fetching (via the full `classify_ticker`-based pipeline) across the entire universe, 875
distinct CIKs, 985 CIK/ticker pairs, completed in roughly fifteen minutes, one recoverable
hiccup along the way (a `KeyboardInterrupt` raised inside a low level `curl`/`cffi` callback,
"exception ignored," meaning it could not propagate as a normal exception; the loop continued
past it). `classify_ticker` makes a live probe per distinct ticker in addition to the actual
price fetch, roughly doubling the request count against a design that trusted
`ticker_history`'s shape; accepted, since that trust is exactly what produced wrong answers for
`GOOGL` and `CMCSK` (Part 3).

## Part 6: coverage, measured properly

Getting an accurate, full-universe coverage number took two corrections, both real bugs, not
just imprecision.

**Bug one: a coverage report read from the cache can never see a failure.**
`save_cik_prices` deliberately drops empty ticker frames before writing (reasonable for the
cache file itself, no point storing an empty table), which means reading the cache back to
report coverage produced `0 empty` even though the full-universe run had visibly hit many
delisted names along the way. The information needed to see a failure was already discarded
before it reached the cache. Fixed by computing coverage from the live fetch results, in the
same pass that writes the cache, and persisting it as its own artifact
(`prices_coverage.parquet`) rather than reconstructing it from disk after the fact.

**Bug two: "still active" computed from the wrong table.** A first classification,
`ticker_history["end_date"].isna()`, undercounted delisted names: `ticker_history`'s book-era
rows are built before `combine_universe_spans` runs, so they never get the "cap an open
book-era span at the book era's own end date" treatment `universe_spans` applies. A company
delisted decades ago, book era coverage only, would still show a null `end_date` here, simply
because the book source's own tracking stopped without explicitly closing it. Reclassifying
against `universe_spans["end_date"].isna()`, the correctly capped, authoritative source,
moved the delisted bucket from 73 to 411 CIK/ticker pairs out of 985 total.

**The real, corrected numbers:**

```
                total  empty  coverage_pct
still_active
False (delisted)  411    210        48.9
True (active)     574     53        90.8
```

Roughly a 1.85x gap, real, but far short of the sevenfold gap two earlier, smaller samples had
suggested (a 15-and-15 random sample showed 87.5% vs. 13.3%; an accidentally book-era-biased
first-30 sample showed even worse). Both overstated the severity, most likely because a small
sample of delisted names skews toward the oldest, hardest 1990s book-era cases rather than the
full delisted population's actual age distribution. The general lesson: a coverage report is
only as good as its classification logic, not just its sample size.

## Data model, final

**One parquet file per CIK**, `data/raw/prices/{cik}.parquet`, long format:

| column | type | meaning |
|---|---|---|
| (index) | tz-aware `DatetimeIndex` | trading date, US/Eastern, as `yfinance` reports it |
| `Open`, `High`, `Low`, `Close` | float | split and dividend adjusted |
| `Volume` | int | shares traded |
| `Dividends`, `Stock Splits` | float | per-day corporate action amount |
| `ticker` | string | which of the CIK's tickers this row belongs to |

**`prices_coverage.parquet`**, one row per distinct ticker ever attempted for a CIK:

| column | type | meaning |
|---|---|---|
| `cik` | Int64 | the entity |
| `ticker` | string | the distinct ticker attempted |
| `rows` | int | trading days returned; `0` means attempted and failed, not omitted |

## Toy example: raw sources to processed tables

Following Priceline/Booking Holdings (CIK 1075531) end to end. `ticker_history` (already
built, `src/universe/point_in_time.py`) says this CIK used two tickers:

| cik | ticker | start_date | end_date | status |
|---|---|---|---|---|
| 1075531 | `PCLN` | 2014-05-31 | 2018-03-31 | recycled |
| 1075531 | `BKNG` | 2014-05-31 | (null, current) | current |

`ticker_spans_for_cik` produces this directly from `ticker_history` plus a live probe of each
ticker's actual vendor status; `fetch_cik_prices` then fetches each span, and `save_cik_prices`
writes the result:

| ticker | rows | date range |
|---|---|---|
| `BKNG` | 3,059 | 2014-06-02 to present |
| `PCLN` | 0 | attempted, empty (see Part 2) |

One row appears in the saved file (`save_cik_prices` drops the empty one), but the coverage
report keeps both, `rows = 0` for `PCLN` is a recorded, honest gap, not a silent omission.

## How to use the price loader

```python
from src.loaders.prices import build_prices, load_cik_prices
from src.universe.point_in_time import build_universe, ticker_on

coverage = build_prices()   # loads existing coverage report if present, else fetches everything
universe_spans, ticker_history = build_universe()

ticker = ticker_on(ticker_history, 1075531, "2015-06-30")   # "PCLN"
prices = load_cik_prices(1075531)
prices[prices["ticker"] == ticker].loc["2015-06-30":"2015-06-30", "Close"]
```

Always resolve the ticker via `ticker_on` before reading a cached file, never assume a CIK's
file holds only one ticker or that the first row is the right one, per Part 3 and Part 4.

## Design decisions considered and rejected

| Option | Verdict |
|---|---|
| One long table, all securities stacked | Rejected as the primary storage shape; does not naturally express a dual class CIK's two independent series any better than per-CIK files, and would be one very large file rather than many small ones |
| Wide, one column per ticker | Rejected; a rename means either duplicating data across two columns or arbitrarily picking one, and a dual class CIK has no single "current" column to place a rename's history under |
| Reconstruct coverage from the on-disk price cache | Rejected (Part 6); the cache deliberately drops empty results, so reconstructing coverage from it can never see a failure |
| Trust `ticker_history`'s shape to decide if a ticker is retired | Rejected (Part 3); `GOOGL` and `CMCSK` produce the identical shape despite one being live and the other genuinely gone |
| Resolve a ticker's CIK by "latest observed wins," same as `attach_cik` | Attempted and reverted (Part 4); correct for an administrative CIK correction, but merges two genuinely different companies handed the same ticker via a real merger |

## Open items

- The tz-aware `DatetimeIndex` `yfinance` returns is not yet reconciled with `universe_spans`
  and `ticker_history`'s plain ISO date strings. Needed before a backtest engine can look up
  "the price on rebalance date D" directly; not yet built or tested.
- The recycling check (`classify_ticker`) has been verified against every real case found in
  this notebook, not proven exhaustively. A ticker recycled to another still-live company with
  overlapping history, rather than one that started much later, could in principle still slip
  through; no such case has been found.
- The CIK-splitting problem found in Part 4 (`GOOGL`/`FOXA`/`XOM` and others) is a universe
  module gap, not something this module can fix on its own; see
  `universe_construction.md`'s Open items for the distinguishing signal that still needs
  building (merging creates a new alternation pattern versus resolves one that already
  existed).
- `build_prices()` has no incremental "fetch only what's new" path; a full rebuild always
  refetches everything. Simple by design; revisit if the universe is refreshed often enough
  for a full rebuild's fifteen to twenty minutes to become a real recurring cost.
- Promote the validated notebook logic into `src/loaders/prices.py`, per the build order in
  the README. Done: see its own `README.md`.
