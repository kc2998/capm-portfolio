# Loaders: point in time data fetched from external vendors

Each module here answers one factual question about a security as of a specific date, fetched
once from an external vendor or source and cached locally rather than fetched live. This file
explains what each module produces and how to call it. The full methodology behind each one,
every vendor behavior found while building it, and the evidence behind every non-obvious
decision, is in that module's own file under `notebooks/logs/`. Those files record why; this
one records how to use the result.

## Prices

Answers "what did this security actually trade at on date D," for every entity that has ever
been a member of the S&P 500, using the historically correct ticker for each date range
(`src/universe/point_in_time.py`), cached locally rather than fetched live.

Full methodology in `notebooks/logs/loaders_construction.md`.

### What it produces

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

### How to use it

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

### Toy examples, from the real data

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

### Caveats worth knowing before relying on this

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

### Rebuilding

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

## Fundamentals

Answers "what financial statement figures were actually known about this company as of date
D," for every entity that has ever been a member of the S&P 500, using EDGAR's own XBRL
`companyfacts` API. Point in time resolution happens against a company's raw, cached filing
history: which tag a filer uses for a concept, and which value had actually been filed as of a
given date, not merely which period it describes.

Full methodology in `notebooks/logs/fundamentals_construction.md`.

### What it produces

**One JSON file per CIK** under `data/raw/fundamentals/{cik}.json` (gitignored, fetched by
`build_fundamentals()` when missing), exactly as EDGAR's `companyfacts` API returns it: an
`entityName`, and a `facts` object split into two taxonomies (`dei`, entity level cover page
facts, and `us-gaap`, financial statement facts), each tag holding a list of individual data
points, one per reporting period and filing.

**One coverage report** at `data/processed/fundamentals_coverage.parquet`:

| column | type | meaning |
|---|---|---|
| `cik` | Int64 | the entity |
| `fetched` | bool | whether `companyfacts` returned data at all; `False` means no XBRL history exists for this CIK, expected for filers that delisted before EDGAR's 2009 XBRL mandate |

### How to use it

```python
from src.loaders.fundamentals import build_fundamentals, load_company_facts, concept_value_as_of

# Loads the existing coverage report and cached files if present; only
# fetches from EDGAR if the coverage report is missing or force_refresh=True.
coverage = build_fundamentals()

facts = load_company_facts(320193)  # Apple

# Net income Apple had actually reported, as of a specific date, for the
# fiscal year it later restated by 27 percent: the value known before the
# restatement, and the value known after.
concept_value_as_of(facts, "net_income", "USD", "2008-09-27", "2009-12-01")
concept_value_as_of(facts, "net_income", "USD", "2008-09-27", "2010-06-01")
```

**Always resolve a concept through `concept_value_as_of`, or a derived helper
(`total_liabilities_as_of`, `gross_profit_as_of`), never by reading a specific tag name
directly.** Which tag a filer uses for a concept varies across filers, and can even change
across one filer's own history (see the Alphabet example below); reading one hardcoded tag
name will silently return nothing for a filer, or a period, that happens to use a different
one.

### Toy examples, from the real data

**Tag standardization, not assumed, checked.** DoorDash (CIK 1792789), which began filing
after the 2018 revenue recognition standard (ASC 606) took effect, never used the older
`Revenues` tag that Apple and Costco still report:

| concept | Apple / Costco's tag | DoorDash's tag |
|---|---|---|
| revenue | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` |

**A filer's own tag choice changing over time, not only across filers.** Alphabet (CIK
1652044) reported `LongTermDebtNoncurrent` from 2014 through mid-2020, an undifferentiated
`LongTermDebt` figure instead for 2021 and 2022 (no noncurrent/current split that year), then
reverted to `LongTermDebtNoncurrent` from 2023 onward. `concept_value_as_of` resolves aliases
per period queried, not once per company, specifically because of this case.

**A genuine point in time restatement, not merely a data quirk.** Apple's fiscal year 2008 net
income was reported as $4,834,000,000 in its original 10-K (filed 2009-10-27), then restated to
$6,119,000,000 in a 10-K/A (filed 2010-01-25), a 27 percent change from Apple's early adoption
of ASU 2009-13/14 (a change in revenue recognition method for iPhone and Apple TV sales,
applied retrospectively, not an error correction). Querying `concept_value_as_of` as of a date
before versus after the 10-K/A returns the two different, both genuinely correct for their
time, figures.

### Caveats worth knowing before relying on this

- **A missing value is never inferred as zero.** If no alias has a value for a queried period,
  `concept_value_as_of` returns `None`. A missing tag might mean the underlying balance is
  genuinely zero (some filers omit a zero rather than tag it explicitly), or might mean the
  breakdown simply had not been filed yet as of the queried date (confirmed directly: Alphabet's
  2019 current debt figure of $0 was not filed until ten months after its original 10-K).
  Conflating the two would misrepresent what was actually known on a given date.
- **Two concepts are derived, not read from a single tag, when a filer doesn't tag them
  directly.** `total_liabilities_as_of` falls back to `Assets - StockholdersEquity` (the
  balance sheet identity) when a filer has no explicit `Liabilities` tag, true for roughly a
  quarter of a random sample of S&P 500 filers checked. `gross_profit_as_of` falls back to
  revenue minus cost of revenue when a filer has no explicit `GrossProfit` tag.
- **Some concepts are structurally unavailable for some filers, not merely unaliased.**
  DoorDash's shares outstanding could not be resolved under any known alias, in either the
  `dei` or `us-gaap` taxonomy; its own facts contain only a preferred share count of zero, a
  mezzanine equity classification, and period average share counts, none of which answer the
  question. A known, bounded gap, not yet resolved.
- **Revenue does not exist as a concept for every sector.** Banks (Truist and Fifth Third
  Bancorp both came back missing revenue in a random sample) report interest and non-interest
  income instead of a generic revenue line, since the business model does not map onto one. A
  value factor built directly on `revenue` does not apply cleanly to financial sector filers.
- **Market capitalization and any price scaled ratio require a correction this module does not
  make.** Cached prices (`src/loaders/prices.py`, above) are always split adjusted; a
  historical shares outstanding figure from a filing is not. Combining them directly silently
  understates market cap by the cumulative split ratio for any company that has split its stock
  since the filing date. This module resolves fundamentals data only; the price join and its
  split adjustment correction belong in `src/factors/value.py`.
- **Coverage has not been measured at full scale.** The alias mechanism has been checked
  against a 30 company random sample of the 2020 S&P 500 (see
  `notebooks/logs/fundamentals_construction.md`), not the full historical universe of roughly
  500 to 1,000 members.

### Rebuilding

```bash
python -m scripts.build_fundamentals            # load if present, else build
python -m scripts.build_fundamentals --refresh --verbose   # force a full rebuild, with progress
```
