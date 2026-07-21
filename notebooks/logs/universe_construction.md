# Universe construction: findings log

Record of what was learned while building the point in time S&P 500 universe in
`notebooks/exploring_universe.ipynb`. Dated 2026-07-21.

This file exists so the reasoning behind the universe builder survives outside the
notebook. The README states the decisions; this file states the evidence.

## Approach change: revision history replaces changes log reconstruction

### The original plan

Wikipedia's "List of S&P 500 companies" page carries two tables of interest: the current
constituent list, and a log of historical additions and removals. The initial plan was to
reconstruct membership on any past date by starting from today's list and walking backward
through the changes log, undoing each change that occurred after the target date. A stock
added after the target date gets removed; a stock removed after the target date gets
restored.

### Why it was abandoned

The changes log is titled "Selected changes to the list of S&P 500 components." The word
"selected" turned out to be accurate. Counting recorded changes per year gives:

| Period | Recorded changes per year |
|---|---|
| 2015 to 2025 | 20 to 30 |
| 2011 to 2014 | 16 to 19 |
| 2007 to 2010 | 8 to 13 |
| Before 2007 | 0 to 7, with entire years missing |

The years 2001, 2002, and 2004 contain no entries at all. This is not plausible as a record
of low turnover: the 2001 to 2002 period covered the dot-com collapse, one of the highest
turnover episodes in the index's history, when many constituents were deleted after their
market capitalizations fell. Their absence establishes that the log is incomplete rather
than merely sparse.

Incompleteness is more damaging here than it first appears, because reconstruction errors
accumulate. Membership on date D is derived by applying every recorded change between D and
the present. A single missing deletion from 2009 therefore corrupts the reconstructed
universe for 2009 and for every earlier date, not for 2009 alone. The deepest and most
interesting part of a backtest would be the least trustworthy part.

### The replacement

The MediaWiki API can return the article as it existed at any past moment. Two requests are
required per snapshot:

1. `action=query&prop=revisions` with `rvdir=older` and `rvstart=<timestamp>` returns the
   identifier of the last revision made at or before the requested date. This is the version
   a reader would have seen on that day.
2. `action=parse&oldid=<revid>&prop=text` returns that revision's rendered HTML, from which
   the constituent table is parsed directly.

Membership is therefore read rather than derived. The incomplete changes log becomes
irrelevant, and the error accumulation problem disappears because each snapshot is
independent of every other.

Requests should carry a descriptive `User-Agent` including contact information, which is
what the Wikimedia API documentation asks of automated clients. A browser user agent string
is acceptable for ordinary page retrieval but is discouraged for API access.

## Coverage of the revision history approach

Probing revisions at two year intervals gave the following:

| Requested date | Revision returned | Rows | Result |
|---|---|---|---|
| 2006-06-30 | n/a | n/a | No tables present |
| 2008-06-30 | 2008-06-20 | 500 | Table found |
| 2010-06-30 | 2010-05-08 | 500 | Table found |
| 2012-06-30 | 2012-06-18 | 500 | Table found |
| 2014-06-30 | 2014-06-27 | 501 | Table found |
| 2018-06-30 | 2018-06-29 | 505 | Table found |
| 2022-06-30 | 2022-06-29 | 503 | Table found |

Usable history extends back to at least 2008, with 2006 predating the introduction of a
constituent table on the page. The exact boundary between 2006 and 2008 has not been
located and is not currently worth locating, since 2008 already exceeds the project's 2010
target. This is an improvement of roughly three years over the changes log approach.

## Limitations to carry forward

### Revision lag varies systematically with era

Each snapshot returns the last edit at or before the requested date, so a snapshot is stale
by however long the page went unedited. The lag is not constant:

| Requested | Revision | Lag |
|---|---|---|
| 2008-06-30 | 2008-06-20 | 10 days |
| 2010-06-30 | 2010-05-08 | 53 days |
| 2012-06-30 | 2012-06-18 | 12 days |
| 2014-06-30 | 2014-06-27 | 3 days |
| 2018-06-30 | 2018-06-29 | 1 day |
| 2022-06-30 | 2022-06-29 | 1 day |

The page was edited infrequently in its early years and is now edited within a day of any
index change. A 2010 snapshot therefore reflects the index as of early May rather than late
June, and any membership change during the intervening seven weeks is invisible.

This does not introduce look ahead, since the snapshot contains only information that was
publicly available on the requested date. It does introduce inaccuracy, because the snapshot
may disagree with the index's actual composition. The practical consequence is that data
quality improves monotonically over time, and results from early years deserve more
skepticism than results from recent years.

### CIK is absent before approximately 2014

The Central Index Key is the SEC's unique identifier for a filing entity. It is the join key
to EDGAR for both fundamentals and Form 4 insider filings, and unlike a ticker symbol it is
stable when a company renames or relists.

Snapshots from 2008 to 2012 carry only ticker, company name, SEC filings link, and GICS
sector. The CIK column appears from around 2014. Early snapshots therefore cannot supply the
EDGAR join key directly, and a separate ticker to CIK mapping will be required if
fundamentals are extended back that far. The universe itself needs only tickers, so this
constrains the fundamentals loader rather than the universe builder.

### Column names drift substantially across revisions

Observed across the probed revisions:

| 2008 to 2012 | 2014 to 2018 | 2022 to present |
|---|---|---|
| `Ticker symbol` | `Ticker symbol` | `Symbol` |
| `Company` | `Security` | `Security` |
| `GICS Sector` | `GICS Sub Industry` | `GICS Sub-Industry` |
| `Address of Headquarters` | `Location` | `Headquarters Location` |
| absent | `Date first added` | `Date first added` |
| absent | `CIK` | `CIK` |

The 2018 revision additionally carries Wikipedia footnote markers inside the column name
itself, as `Date first added[3][4]`. Any parser matching column names exactly, or selecting
tables by position, will fail silently somewhere across this range. Selection must be made
on a fuzzy signature, for example the first column whose lowercased name contains `symbol`
or `ticker`, which matches every revision tested.

The same argument applies to table position. The present page returns three tables, the
third being a navigation box (identifiable by the `vte` prefix, Wikipedia's view/talk/edit
template) rather than data. The 2015 revision returns two. Positional indexing happens to
work today and is not safe across revisions.

### Snapshots require validation

Wikipedia is editable by anyone and is periodically vandalized. A snapshot landing on a
vandalized revision would return corrupted membership. Every snapshot should be checked for
a plausible row count and should raise rather than proceed when the check fails.

The appropriate range is 495 to 510 rather than exactly 500, for reasons given below.

### Constituent count is not exactly 500

The index tracks 500 companies but holds a slightly larger number of share classes. Alphabet
(GOOGL and GOOG), Fox Corporation (FOXA and FOX), and News Corp (NWSA and NWS) each
contribute two rows, giving 503 rows at present. The set of dual class members has changed
over time, which is why the 2015 snapshot returned 502 and the 2018 snapshot 505.

Duplicate CIK values identify these cases directly, since the CIK is assigned per company
rather than per share class:

```python
current.groupby("CIK").size().sort_values(ascending=False).head()
```

Two smaller sources of variation: a deletion sometimes takes effect a day or two before the
corresponding addition, so the index genuinely runs at 499 or 501 briefly; and the Wikipedia
page is not updated at the instant a change takes effect, so a snapshot can capture a
partial update.

## Data model: spans table

Two representations were considered.

A **membership matrix** indexes dates against tickers with boolean cells. It is simple to
query but stores the same value repeatedly, since membership changes on roughly 25 days per
year while the matrix has a row for every date. It is also wide and sparse, as several
hundred tickers have passed through the index since 2010.

A **spans table** stores one row per membership interval, as `ticker, start_date, end_date`.
Membership on date D is the set of rows satisfying `start_date <= D <= end_date`. A stock
that leaves and later rejoins occupies two rows. This is compact, exact, and is the
conventional point in time representation.

The spans table is the source of truth. Snapshots for individual dates are materialized from
it on demand and are not committed to the repository.

The spans table is built by taking periodic snapshots and comparing consecutive pairs. A
ticker appearing in snapshot N but not N-1 begins a span; one disappearing ends a span.
Boundary precision is therefore limited to the snapshot interval, which is acceptable when
the interval matches or exceeds the rebalance frequency, since membership cannot be acted on
between rebalances in any case.

The wider benefit is that the spans table defines an interface. Everything downstream reads
the spans table and is indifferent to how it was produced, so the Wikipedia source can be
replaced without altering any other component. When a data source is uncertain, the
interface rather than the source is the thing worth fixing in place.

## Sources considered and rejected

**SEC EDGAR.** EDGAR is a repository of regulatory filings and has no representation of
index membership. Membership in the S&P 500 is not a regulatory fact and generates no
filing. The index is a commercial product of S&P Dow Jones Indices, and its constituent
history is licensed rather than public. EDGAR remains essential for fundamentals and insider
data, which is what the CIK column supports.

**CRSP via WRDS.** CRSP maintains authoritative point in time membership with exact entry
and exit dates, and additionally supplies delisting returns for companies that ceased
trading, which would address a known weakness in free price data. It is the standard
academic source for this problem and may be available through a university subscription.
It was rejected here on licensing grounds: the data cannot be redistributed, which is
incompatible with releasing this project as an open source tool. It remains useful as a
private cross check for anyone with access.

**Curated repositories.** Several public datasets of historical constituents exist, most
derived from the same Wikipedia revision history. They are reasonable as an independent
cross check but carry undocumented methodology, which makes them unsuitable as a primary
source.

## Downstream consequences for the price loader

Two items surfaced here that belong to the price loader rather than the universe builder,
recorded so they are not lost.

**Ticker format.** Wikipedia writes multi class tickers with a period, as `BRK.B` and
`BF.B`. The `yfinance` API expects a hyphen, as `BRK-B`. Translation belongs at the boundary
where the vendor is called, not in the universe parser, whose responsibility is to report
faithfully what the source said.

**Delisted coverage.** A point in time universe necessarily contains companies that have
since ceased trading, which is the entire purpose of avoiding survivorship bias. Free price
sources have their weakest coverage for exactly those names. The price loader should measure
and report the fraction of historical members for which prices are unavailable, rather than
dropping them silently, since silent dropping would reintroduce survivorship bias through
the data layer after it had been removed from the universe layer.

## Open items

- Locate the precise earliest usable revision between 2006 and 2008, if history before 2008
  is ever wanted.
- Decide whether dual class listings should be treated as one company or two when
  constructing the universe, and apply the decision consistently in factor computation.
- Cross check a sample of reconstructed snapshots against an independent source to quantify
  the error introduced by revision lag.
