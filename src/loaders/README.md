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
| `usable` | bool | whether the response carries any `us-gaap` facts; `fetched: True, usable: False` means the request succeeded but the filer reports under a taxonomy this module does not parse (see the `ifrs-full` caveat below) |

### How to use it

```python
from src.loaders.fundamentals import (
    build_fundamentals, load_company_facts, concept_value_as_of, latest_value_as_of,
)

# Loads the existing coverage report and cached files if present; only
# fetches from EDGAR if the coverage report is missing or force_refresh=True.
coverage = build_fundamentals()

facts = load_company_facts(320193)  # Apple

# Net income Apple had actually reported, as of a specific date, for the
# fiscal year it later restated by 27 percent: the value known before the
# restatement, and the value known after.
concept_value_as_of(facts, "net_income", "USD", "2008-09-27", "2009-12-01", "annual")
concept_value_as_of(facts, "net_income", "USD", "2008-09-27", "2010-06-01", "annual")

# A balance sheet concept takes no period, since it describes an instant.
concept_value_as_of(facts, "total_assets", "USD", "2020-09-26", "2020-12-01")

# Shares outstanding has its own function and takes no period end at all.
shares_outstanding_as_of(facts, "2020-12-01")

# A factor never knows a filer's fiscal period end; latest_value_as_of derives it.
# Returns (val, filed, form, tag, period_end).
latest_value_as_of(facts, "net_income", "USD", "2022-01-01", "annual")
```

**Always resolve a concept through `concept_value_as_of` (if the period end is already known),
`latest_value_as_of` (if it is not), or a derived helper (`total_liabilities_as_of`,
`gross_profit_as_of`), never by reading a specific tag name directly.** Which tag a filer uses
for a concept varies across filers, and can even change across one filer's own history (see the
Alphabet and CSX examples below); reading one hardcoded tag name will silently return nothing
for a filer, or a period, that happens to use a different one.

### The `period` argument

An end date does not identify an income statement or cash flow fact. Alphabet's 2021-06-30
carries both a 90 day figure of $18,525,000,000 and a 180 day year to date figure of
$36,455,000,000, filed on the same day, and both are correct. `period` says which is wanted:
`"quarterly"`, `"half_year"`, `"nine_month"`, or `"annual"`.

It is **required** for a concept whose facts describe a span of time and **rejected** for one
describing a balance at an instant. `CONCEPT_KIND` records which is which:

| Kind | Concepts | `period` |
|---|---|---|
| duration | `revenue`, `cost_of_revenue`, `net_income`, `operating_cash_flow`, `gross_profit` | required |
| instant | `total_assets`, `total_liabilities`, `stockholders_equity`, `long_term_debt_noncurrent`, `long_term_debt_current`, `shares_outstanding` | must be omitted |

Omitting it on a duration concept raises `ValueError` rather than defaulting to annual, because
silently choosing a period is the defect the argument exists to prevent.

Period type is decided by the duration of a fact as a fraction of that filer's own fiscal year,
not by an absolute day count. A quarter runs 83 days at Costco, which divides its year into 12,
12, 12, and 16 weeks, 89 to 91 at a calendar year filer, 97 at Apple in a 53 week year, and 111
or 118 at Costco's fourth quarter. EDGAR's own `fp` and `form` fields cannot be used for this:
both label the filing a fact appeared in rather than the fact, and one Costco fact appears under
`fp` values of Q3, Q4, and FY. Full derivation and evidence in
`notebooks/logs/fundamentals_construction.md`, Parts 14 and 15.

### Period discovery: querying without a period end

`concept_value_as_of` requires a `period_end`, but a factor at a rebalance date holds 500
companies and none of their fiscal calendars: Apple's year ends in late September, Costco's in
late August, McKesson's in March, and each shifts by a few days a year. `available_periods`
returns every period end a concept resolves for, as of a given date, sorted oldest first;
`latest_value_as_of` wraps it to return the most recent value directly, as `(val, filed, form,
tag, period_end)`.

Only periods already filed by the query date count as available. Apple's fiscal 2021 ended
2021-09-25 but was not filed until 2021-10-29, so a query on 2021-10-01 sees fiscal 2020 as the
most recent annual period, not fiscal 2021; querying on the end date instead would price a
rebalance using a figure published four weeks later, look ahead that is invisible in the result
because the number returned looks entirely reasonable.

`offset` steps back through the periods that are actually available for that filer, not through
calendar periods: `offset=1` is what a growth factor comparing this year against last needs, but
a filer that does not tag its fourth quarter separately has only three quarterly periods a year,
so `offset=4` is not reliably "the same quarter a year ago." A seasonal comparison should match
on the period end's month instead.

`total_liabilities` and `gross_profit` are resolvable through their derived route as well as
their direct tag; a period counts as available if either reaches it. Dover Corp has tagged no
direct `Liabilities` fact since 2009, but `Assets` and `StockholdersEquity` are both current, so
`latest_value_as_of` still returns a current figure, tagged `"derived: total_assets -
stockholders_equity"` rather than a single EDGAR tag name, since the value comes from two facts
rather than one. Full derivation and evidence in `notebooks/logs/fundamentals_construction.md`,
Parts 18 and 19.

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

**An accounting standard change moving most filers at once, not one filer's idiosyncratic
choice.** ASU 2009-17, effective fiscal 2009, required noncontrolling interest to be reported as
part of total equity; most filers responded by switching tags and never returned to the shorter
name. CSX's `StockholdersEquity` tag carries 4 points, all from 2008 to mid-2009;
`StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` carries 267 points
through 2026. ASC 842, effective 2019, did the same to long term debt: Home Depot's plain
`LongTermDebtCurrent`/`LongTermDebtNoncurrent` tags stop in 2017, replaced by
`LongTermDebtAndCapitalLeaseObligations(Current)`, which folds in finance lease obligations.
Both are in `TAG_ALIASES` alongside the older names, so `concept_value_as_of` reaches whichever
one a filer actually used for the period queried.

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
- **Shares outstanding is queried differently from everything else, and is missing entirely for
  some multi-class filers.** `shares_outstanding_as_of(facts, as_of_date)` takes no period end,
  because neither source tag is dated to one a caller would hold:
  `dei:EntityCommonStockSharesOutstanding` carries the cover page date, measured at 20 to 54 days
  after the period end across the validation panel, and `us-gaap:CommonStockSharesOutstanding` is
  dated to the period end but optional. `concept_value_as_of` raises if asked for this concept.
  Separately, roughly 9 percent of filers have no undimensioned share count under either tag:
  they report the figure only per share class, and the bulk `companyfacts` endpoint serves only
  undimensioned facts. Measured across the full usable cache (853 companies), 66 have no genuine
  point in time count, all with multiple share classes or a partnership unit structure. For
  those, the function falls back to the period average share count
  (`WeightedAverageNumberOfSharesOutstandingBasic`, quarterly in preference to annual, and
  `WeightedAverageNumberOfDilutedSharesOutstanding` if a filer, such as Tyson Foods, tags only
  the diluted figure), which carries a median absolute error of 0.43 percent against a true
  count. The fallback is a last resort, never pooled with genuine counts, and the returned tag
  names it, so callers can identify the affected companies; `allow_weighted_average=False`
  excludes them outright. 10 remain unresolved even with the fallback: Sunoco (a limited
  partnership; units, not shares, are not a well defined quantity to fall back to), a First Trust
  fund, and 8 multi-class or post-acquisition-subsidiary filers (Berkshire Hathaway, Ares
  Management, Visa, Constellation Brands, Ryan Specialty, Dell International, Level 3 Parent,
  Erie Indemnity) with no weighted-average tag at any age. Full reasoning, including why the
  SEC's Financial Statement Data Sets were investigated and rejected as covering fewer filers at
  greater cost, is in Part 17 of the log; the wider-scale count is in Part 18.
- **A share count more than 400 days old is treated as unavailable.** Four cached filers report an
  undimensioned count for part of their history and then switch to per-class tagging, so the
  endpoint retains an old figure and nothing after it. Without the bound, Mastercard returned a
  2010 count of 122,530,193 against an actual figure near 905,000,000. Tune with `max_age_days`
  if a longer horizon is genuinely wanted.
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
- **`build_fundamentals()` has now been run at essentially full scale** (875 cached CIKs, 867
  fetched, 853 usable), but what has been measured is still mostly tag existence rather than
  dated resolution. The published per-concept figures (100% for total assets and shares
  outstanding, down to 60% for near-term debt maturities) record whether a tag appears anywhere
  in a filer's history, which is a weaker question than whether a dated query returns a value.
  Current portion of long term debt is a further, distinct case: it is frequently and
  legitimately zero, and many filers tag it once and stop re-confirming the zero every quarter,
  so a stale or absent value there should be read as "probably near zero," not "still broken";
  see Part 18 of the log.
- **A filer reporting under a taxonomy other than `us-gaap` returns `None` for every concept.**
  Foreign private issuers file form 20-F under `ifrs-full`, often in a currency other than USD,
  and every entry in `TAG_ALIASES` names `us-gaap` or `dei`. The coverage report's `usable`
  column now distinguishes this from a genuine fetch failure, rather than recording only
  `fetched: True`. Four such filers are known (CIK 888746, a Chilean brewer reporting in
  `CLP`/`CLF`; Barclays Bank PLC; Pacific Airport Group; Lufax Holding), all reached through the
  universe module's known CIK misattribution rather than through genuine index membership. A
  fifth `fetched: True, usable: False` case, CIK 2115436, is not `ifrs-full` at all: it carries
  only a `ffd` fee-disclosure taxonomy, an unrelated entity reached through the same
  misattribution mechanism for ticker `XOM`. No `ifrs-full` alias table exists or is planned;
  none of the five represent genuine S&P 500 membership.
- **Year to date and quarterly figures need not reconcile to the last dollar.** Checked across
  the validation panel, 95.6 percent of year to date ladders balance exactly against the reported
  quarterly figures. The remainder differ by well under one percent, from two causes: a filer
  presenting statements in millions rounds each figure independently, so three rounded numbers
  need not satisfy an exact identity (Meta); and a filer that revises one figure without revising
  the others leaves the latest vintage of each mutually inconsistent (Fastenal). Any factor
  computing a quarter over quarter change inherits this.
- **Two aliases stand in for a broader quantity than the tag they replace.** Where a filer stopped
  tagging `StockholdersEquity` after ASU 2009-17, the fallback
  `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` is total equity rather
  than equity attributable to shareholders, so book value is overstated by the minority interest.
  Measured on the 78 companies reporting both at a shared period end, the median worst-case gap is
  3.9 percent and 35 exceed 5 percent; Marsh and McLennan reported -$3,923,000,000 under the
  narrow tag and +$6,872,000,000 under the inclusive one on the same date. Similarly `DebtCurrent`,
  the fallback for `long_term_debt_current`, is total current debt including commercial paper and
  short-term borrowings: Ecolab reported $6,200,000 against $1,445,300,000 on the same date. In
  both cases alias order means the narrower tag wins whenever a filer reports it, so the broader
  figure is reached only where nothing else exists. The lease-inclusive debt alias is not affected,
  agreeing to a median of 0.05 percent. Evidence in Part 21 of the log.
- **A filer can restate its own history in different units, and nothing in the data says so.**
  Harley-Davidson re-reported its 2011 and 2012 quarters in 2013 stated in thousands rather than
  dollars, at period ends a few days from the originals. Both vintages carry the unit `USD`, and
  because the end dates differ the loader treats them as separate periods rather than as vintages
  of one, so `latest_value_as_of` prefers the later, thousand-fold smaller figure. McDonald's tags
  its weighted average share count in millions while its share count is in units, the same
  problem in a different concept. Not detectable from the unit label and not corrected here, since
  judging a value implausible is a data quality decision rather than a resolution rule. A factor
  computing growth rates should expect it.

### Rebuilding

```bash
python -m scripts.build_fundamentals            # load if present, else build
python -m scripts.build_fundamentals --refresh --verbose   # force a full rebuild, with progress
```
