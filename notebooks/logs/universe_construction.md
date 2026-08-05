# Universe construction: findings log

Record of what was learned while building the point in time S&P 500 universe in
`notebooks/exploring_universe.ipynb`. Started 2026-07-21, last updated 2026-08-05.

This file exists so the reasoning behind the universe builder survives outside the
notebook. The README states the decisions; this file states the evidence, organized to
follow the notebook's own order: 2008 to present first, then 1996 to 2008, then how the two
eras connect. Abandoned approaches and validation exercises live here in prose rather than
as dead code left in the notebook for someone to puzzle over later.

## The task

Build a table of S&P 500 membership, 1996 to today, that can answer "who was a member on
date D" without look ahead, i.e. without accidentally using information not yet known as of
D. No single free source covers the whole span, so two are combined:

| Era | Source | Why this era, this source |
|---|---|---|
| 2008 to present | Wikipedia's own revision history | re-derivable from the primary source at any time |
| 1996 to 2008 | A book-derived CSV (Clenow/Norgate) | the only free source reaching this far back |

Both eras end up in the same shape, one row per membership interval:

| ticker | cik | start_date | end_date | source |
|---|---|---|---|---|
| AAPL | 320193 | 1996-01-02 | (null, still a member) | clenow_norgate+wikipedia_revision |
| BCO | (none) | 1996-01-02 | 1996-01-12 | clenow_norgate |
| PCLN | 1075531 | 2009-11-06 | 2018-03-31 | wikipedia_revision |
| BKNG | 1075531 | 2018-03-31 | (null, still a member) | wikipedia_revision |

Everything below is the reasoning behind that shape, the bugs found while actually running
it, and the complications that came up building each piece.

## Part 1: 2008 to present, reading Wikipedia's own history

### The problem

There is no free, authoritative record of past S&P 500 membership. The index is a
commercial product of S&P Dow Jones Indices, not a regulatory filing, so SEC EDGAR has
nothing on membership itself. CRSP, the standard academic source, is subscription only and
cannot be redistributed, incompatible with releasing this project as open source.

### First attempt, and why it was abandoned

Wikipedia's "List of S&P 500 companies" page carries a table titled "Selected changes to
the list of S&P 500 components." The first plan was to walk backward from today's
constituent list through this log, undoing each recorded change to reconstruct any past
date. Counting recorded changes per year showed why that doesn't work:

| Period | Recorded changes per year |
|---|---|
| 2015 to 2025 | 20 to 30 |
| 2011 to 2014 | 16 to 19 |
| 2007 to 2010 | 8 to 13 |
| Before 2007 | 0 to 7, with entire years missing |

2001, 2002, and 2004 show zero recorded changes, implausible for a period covering the
dot-com collapse, one of the highest turnover episodes in the index's history. The log is
incomplete, not merely sparse, and the damage compounds: membership on date D is derived by
applying every change between D and today, so one missing entry corrupts every earlier date
too, not just its own year. The oldest, most interesting dates would be the least
trustworthy.

### The fix: read the page as it actually looked, not derive it

The MediaWiki API returns the article as it existed at any past moment, two requests per
snapshot:

1. `action=query&prop=revisions`, `rvdir=older`, `rvstart=<timestamp>`, returns the last
   revision at or before the requested date.
2. `action=parse&oldid=<revid>&prop=text` returns that revision's rendered HTML, parsed
   directly for the constituent table.

Membership is read, not derived, so the changes log's incompleteness stops mattering and
errors no longer accumulate, each snapshot is independent of every other. Probing revisions
at two year intervals confirmed the method works and found its boundary:

| Requested date | Revision returned | Rows | Result |
|---|---|---|---|
| 2006-06-30 | n/a | n/a | No constituent table present yet |
| 2008-06-30 | 2008-06-20 | 500 | Table found |
| 2010-06-30 | 2010-05-08 | 500 | Table found |
| 2012-06-30 | 2012-06-18 | 500 | Table found |
| 2014-06-30 | 2014-06-27 | 501 | Table found |
| 2018-06-30 | 2018-06-29 | 505 | Table found |
| 2022-06-30 | 2022-06-29 | 503 | Table found |

Usable history extends back to at least 2008, an improvement of roughly three years over
the changes log approach. The exact 2006-2008 boundary was not pinned down further, since
2008 already exceeds the project's original 2010 target.

### Complications found building on top of this

**Revision lag varies by era.** A snapshot is only as fresh as the page's last edit before
the requested date:

| Requested | Revision | Lag |
|---|---|---|
| 2008-06-30 | 2008-06-20 | 10 days |
| 2010-06-30 | 2010-05-08 | 53 days |
| 2012-06-30 | 2012-06-18 | 12 days |
| 2014-06-30 | 2014-06-27 | 3 days |
| 2018-06-30 | 2018-06-29 | 1 day |
| 2022-06-30 | 2022-06-29 | 1 day |

Not look ahead (a snapshot only ever contains information public as of its date), but real
inaccuracy: a 2010 snapshot reflects early May, not late June. Data quality improves
monotonically over time; early years deserve more skepticism than recent ones.

**Column names drift across revisions.** A parser matching exact names or table position
will fail silently somewhere in this range:

| 2008 to 2012 | 2014 to 2018 | 2022 to present |
|---|---|---|
| `Ticker symbol` | `Ticker symbol` | `Symbol` |
| `Company` | `Security` | `Security` |
| `GICS Sector` | `GICS Sub Industry` | `GICS Sub-Industry` |
| `Address of Headquarters` | `Location` | `Headquarters Location` |
| absent | `Date first added` | `Date first added` |
| absent | `CIK` | `CIK` |

The 2018 revision even carries a Wikipedia footnote marker inside a column name,
`Date first added[3][4]`. Table position isn't safe either: today's page has three tables
(the third a navigation box), the 2015 revision has two. The fix in both cases is matching
by signature, for example the first column whose lowercased name contains `symbol` or
`ticker`, which matches every revision tested.

**Ticker punctuation drifts within the wiki era itself.** Three CIKs show a security split
purely by spelling, found once `ticker_history` (Part 3) exposed it:

| CIK | Tickers observed | What's actually going on |
|---|---|---|
| 14693 (Brown-Forman) | `BF.B`, `BF-B` | Same security; Wikipedia alternates the separator across revisions |
| 1067983 (Berkshire Hathaway) | `BRK.B`, `BRK-B` | Same security, same issue |
| 1336917 (Under Armour) | `UA`, `UA-C`, `UA.C`, `UAA` | A mix: `UA-C`/`UA.C` is the same spelling issue, `UA` vs `UAA` is a genuine dual class distinction |

Left unfixed, `build_spans` reads a punctuation change as an exit and a fresh entry for the
same, unchanged security, fragmenting one continuous membership into several. Fixed by
collapsing the hyphen form to the period form before anything downstream touches the ticker
column. This also resolved the dual class open question in passing: once spelling noise is
removed, Under Armour's `UA`/`UAA` split is the only genuine case left (see Open items).

**CIK is absent before roughly 2014.** The Central Index Key, SEC's identifier for a filing
entity, is the join key to EDGAR for fundamentals and insider filings, and unlike a ticker
it is stable across a rename. It simply isn't in the table before 2014 (see the column table
above), which constrains anything joining to EDGAR further back, not the universe itself.

**The constituent count is never exactly 500.** The index tracks 500 companies but a
slightly larger number of share classes (Alphabet's GOOGL/GOOG, Fox's FOXA/FOX, News Corp's
NWSA/NWS), plus timing noise around any single addition or deletion. The accepted band is
495 to 517, not exactly 500, and every snapshot is checked against it, since Wikipedia is
editable by anyone and a vandalized revision would otherwise pass through as corrupted
membership.

### Turning snapshots into a membership table

Two representations were considered:

| Representation | Shape | Verdict |
|---|---|---|
| Membership matrix: one row per date, one column per ticker, boolean cells | wide, and mostly repeats the same value since membership changes on ~25 days a year | Rejected, wide and sparse |
| Spans table: one row per membership interval (`ticker, start_date, end_date`) | compact, exact | Adopted |

A membership matrix for 2020 alone would look like:

| date | AAPL | MSFT | XYZ |
|---|---|---|---|
| 2020-01-31 | 1 | 1 | 1 |
| 2020-02-29 | 1 | 1 | 1 |
| 2020-03-31 | 1 | 1 | 0 |

against the equivalent spans table:

| ticker | start_date | end_date |
|---|---|---|
| AAPL | 1996-01-02 | (still a member) |
| MSFT | 1994-06-01 | (still a member) |
| XYZ | 2015-01-01 | 2020-02-29 |

Built by diffing consecutive monthly snapshots (the cadence already decided in the README,
since index membership changes roughly twice a month, and a finer cadence would assert more
precision than the source has): a ticker appearing in month N but not N-1 opens a span; one
disappearing closes it at N-1. Boundary precision is therefore exact to the snapshot
interval, one month for this era. Verified directly, reconstructing membership from the
resulting spans table for `2022-06-30` against the original snapshot for that date, an exact
match, `0` tickers in either set not in the other.

### Attaching CIK

CIK is absent before ~2014 (above), so an entity's CIK is taken as the latest non-null value
observed anywhere across its snapshots, not whatever was present when its span opened,
otherwise a span opened in 2009 would lose CIK it plainly acquires later:

| Outcome | Count | Explanation |
|---|---|---|
| Spans with a CIK | 836 of 995 | direct |
| Spans missing CIK | 159, fully explained | every one closes by 2014-04-30, none still open, exactly the pre-2014 gap above, not a defect |

### A discovery: left censoring

Inspecting the earliest spans turned up `BCO`, a span running only `1996-01-02` to
`1996-01-12`, ten days, implausible for real index turnover. Checking the actual event
clarified it:

| Field | Naive reading | What it actually means |
|---|---|---|
| `start_date` = 1996-01-02 | "joined the index this day" | already a member when the book file's coverage begins; true join date predates the data entirely |
| `end_date` = 1996-01-12 | "left ten days later" | genuine, correct, confirmed removal |

This generalizes to every span opening exactly on its source's first observed date
(`1996-01-02` for the book era, `2008-01-31` for the Wikipedia era, see Part 2 and 3): a
structural property of any bounded observation window, not a defect in either source.
Decision: these spans are kept, not deleted or corrected, and marked with a boolean
`left_censored` column so the limitation is queryable. Membership correctness is unaffected;
only tenure length is unknown for these specific spans, which nothing in the current factor
list (momentum, value, size, quality, low volatility, per the README) depends on.

## Part 2: 1996 to 2008, the book file

### The problem

Wikipedia's constituent table doesn't exist before 2008 (Part 1). Something else is needed
for 1996 to 2008.

### The candidate source

`S&P 500 Historical Components & Changes.csv`, distributed through the `fja05680/sp500`
repository (MIT licensed), originally bundled with Andreas Clenow's book *Trading Evolved*
and built on Norgate Data, a commercial vendor of survivorship bias free historical index
constituents. Covers `1996-01-02` through `2019-01-11`, effectively daily rows (not every
calendar date has one; a new row appears when something changes). Kept in this repository
at `data/raw/S&P 500 Historical Components & Changes.csv`, the raw file, not the
repository's own cleaned "Updated" version, for the reason below.

### Complications found in this source

**Currently active companies are relabeled with their present day ticker, retroactively.**

| Ticker | First appears in the raw file | Real world event |
|---|---|---|
| `BKNG` | 2009-11-06 | Priceline.com actually renamed to Booking Holdings in 2018 |
| `PCLN` | never appears | the ticker the company traded under for that entire period |

Confirmed in both the raw file and the repository's own cleaned version, so it's in the
underlying data, not that repository's processing.

**Delisted or ticker-recycled companies carry a `BASE-YYYYMM` suffix.**

| Ticker as recorded | Date range | Meaning |
|---|---|---|
| `H-200107` | 1996-01-02 to 2006-08-01 | one company's tenure holding the ticker `H` |
| `H-200704` | 2006-08-01 onward | a different company later reusing the same letters |

The suffix is constant within a tenure and changes only when the ticker is reused,
confirmed by tracing `COV`, `H`, and `GRA` across every row. It never appears on a currently
active company's ticker (the file's last row, `2019-01-11`, has zero suffixed tickers), so
it is exactly how this source disambiguates a defunct ticker from a later reuse of the same
letters.

Consequence: the `fja05680/sp500` repository's own cleaning notebook
(`sp500_historical.ipynb`) strips this suffix and drops duplicate rows, merging distinct
company tenures under one bare ticker. The raw file, keeping the suffix as part of the
identity, is the correct starting point here.

### Decision

Use this file only for 1996 through 2008, not for the overlapping 2008 to 2019 window where
Wikipedia already has coverage: the revision API is independently re-verifiable from the
primary source at any time, while the book file is a frozen third party artifact of
uncertain redistribution rights, the same concern that already excluded CRSP.

### Evidence behind excluding the overlap

A systematic quarterly sweep, 44 dates from `2008-03-31` to `2018-12-31`, compared each
Wikipedia snapshot against the book file's nearest row.

| Date | Wiki n | Book n | raw_diff | base_diff | base_diff as % of roster |
|---|---|---|---|---|---|
| 2008-03-31 | 500 | 502 | 306 | 97 | 19% |
| 2011-06-30 | 500 | 501 | 219 | 77 | 15% |
| 2013-06-30 | 500 | 501 | 171 | 57 | 11% |
| 2015-06-30 | 502 | 503 | 123 | 37 | 7% |
| 2016-06-30 | 504 | 515 | 85 | 31 | 6% |
| 2018-06-30 | 505 | 514 | 15 | 3 | 0.6% |
| 2018-12-31 | 505 | 504 | 5 | 3 | 0.6% |

(`raw_diff`: tickers differing exactly as written. `base_diff`: the same, after stripping
the `BASE-YYYYMM` suffix, isolating the recycling artifact from a genuine disagreement.)

`base_diff` shrinks steadily toward 2019, the book file's own generation date, not because
the source becomes more accurate, but because the retroactive relabeling problem above
surfaces a mismatch for every company that renamed between the check date and 2019, and
there's less time for that to have happened the closer the check date sits to 2019.

CIK based matching (a wiki-only ticker and a book-only ticker resolving to the same CIK are
almost certainly the same company renamed, using SEC's bulk registry for the book side and
Wikipedia's own CIK column, available from ~2014, for the wiki side) confirms most of what
remains where it has data to check:

| Period | base_diff | confirmed via CIK | unexplained |
|---|---|---|---|
| 2008-03 to 2014-03 (25 quarters, no wiki CIK yet) | 1,859 | 0 | 1,859 (100%) |
| 2014-06 to 2018-12 (19 quarters, wiki CIK available) | 490 | 266 | 224 (46%) |
| **Total** | **2,349** | **266 (11%)** | **2,083 (89%)** |

The 11% headline is misleading alone: dominated by 25 quarters where confirmation was
structurally impossible (no wiki CIK yet), not by unexplainable mismatches. The unexplained
share, where the method has data, falls from 49% right after 2014 to 0% by late 2018.

The tickers recurring most often in what's left pair up almost one to one, every pair a
real, identifiable event:

| Wiki (quarters) | Book (quarters) | Event |
|---|---|---|
| WYN (41) | WYND (41) | Wyndham Worldwide to Wyndham Destinations |
| BHI (38) | BHGE (38) | Baker Hughes to Baker Hughes GE (renamed again since, to BKR) |
| TSO (38) | ANDV (38) | Tesoro to Andeavor |
| YHOO (37) | AABA (37) | Yahoo to Altaba (fully dissolved in 2020) |
| AA (35) | ARNC (35) | Alcoa's 2016 split into Alcoa Corp and Arconic |
| CSC (31) | DXC (31) | Computer Sciences Corp to DXC Technology, a merger |
| GCI (29) | TGNA (29) | Gannett to TEGNA |
| WAG (28) | WBA (28) | Walgreens to Walgreens Boots Alliance |
| WLP (27) | ANTM (27) | WellPoint to Anthem |

Each breaks a one-hop CIK lookup against *today's* registry in a different way: a second
rename since (`BHI`/`BHGE`), full dissolution (`YHOO`/`AABA`), or a merger that plausibly
assigned a new CIK (`CSC`/`DXC`). A separate, unrelated category, `BRK-B`/`BRK.B` and
`BF-B`/`BF.B`, is pure punctuation (see Part 1), no CIK needed to explain it.

**Conclusion.** The 2008-2019 disagreement is real, systematic, and traceable by name to the
book file's design, not to genuine uncertainty about membership. Closing the remaining gap
would need a general historical ticker resolver, which SEC doesn't support for free, and the
book data isn't used in this window regardless of how well it can be reconciled, so further
work here would improve a validation exercise, not the pipeline. The exclusion stands.

### CIK backfill for this era

SEC's bulk registry (`company_tickers.json`, 10,432 entries, free, no auth) resolves CIK for
any bare ticker still in use by an active filer today, which is most of them, since this
source's labeling already substitutes today's ticker for any still-active company. It
cannot resolve a suffixed ticker, since that company is by definition no longer an active
filer, an expected, explainable non-match.

**Result:** 432 of 854 book-era spans matched a CIK (51%). The other 49% splits into two
very different buckets, addressed in Part 3: suffixed tickers (no CIK possible, by design)
and bare tickers whose company simply isn't findable this way (worth a closer look).

## Part 3: connecting the two eras, ticker identity

### Two problems this surfaces

| Problem | Cause |
|---|---|
| Boundary artifact | A company continuously in the index across `2008-01-31` produces two disconnected spans: a book-era one left open only because the book data was deliberately cut off there, and a wiki-era one starting fresh and left-censored, reading as a phantom exit and re-entry |
| Unresolved pre-2008 risk | Every confirmed relabeling example (Part 2) happens to be a rename that occurred *after* 2008. Nothing rules out a company renaming *before* 2008 while remaining continuously active, which the book file would relabel the same way, and which cannot be checked against Wikipedia, since Wikipedia doesn't reach back that far |

### The fix: a second table, `ticker_history`, keyed by CIK

`universe_spans` and `ticker_history` answer different questions:

| Question | Table | Example |
|---|---|---|
| Was this entity a member on date D? | `universe_spans` | CIK 1075531 a member from 2009-11-06 to present |
| What symbol did this entity trade under on date D? | `ticker_history` | CIK 1075531 traded as PCLN until 2018-03-31, BKNG after |

Keying by CIK rather than ticker is what makes both problems solvable at once: a rename
doesn't look like two companies, and a continuous membership can be recognized as one
entity across the source boundary regardless of what string each source used.

### Building it for 2008 onward: verified

Wikipedia's ticker for a date is already period-correct (confirmed via `PCLN`/`BKNG`).
`build_ticker_history_wiki` walks the monthly snapshots grouped by CIK and records a new
entry whenever the ticker tied to a CIK changes between snapshots. Every entry here is
`verified = True`. 59 CIKs show more than one ticker across the wiki era, real renames once
the punctuation artifacts from Part 1 are excluded.

### Building it before 2008: verified where possible, flagged where not

Nothing as reliable as Wikipedia exists to check pre-2008 rename timing directly. SEC's
`submissions` API (`data.sec.gov/submissions/CIK##########.json`) does provide a free,
structured, dated *legal name* history per company (`formerNames`), confirmed live:

```
Booking Holdings Inc. (CIK 1075531)
  Priceline Group Inc.   2014-04-01 to 2018-02-16
  PRICELINE COM INC      1998-12-23 to 2014-03-19
```

That's name history, not ticker history, but the two are almost always paired, a rebrand
and a symbol change typically happen together, so it works as a proxy:

| Ticker type | Rule applied | Reasoning |
|---|---|---|
| Suffixed (`BASE-YYYYMM`) | `verified = True` by default | belongs to a company no longer active by 2019; retroactive relabeling can only affect a company still active enough to have a "current" name to apply |
| Bare, no CIK match at all | `verified = False`, flagged | SEC's current registry not recognizing this exact symbol is itself evidence of a later rename or acquisition (the `BHI`/`BHGE` pattern), not proof the label was safe |
| Bare, has CIK, no former name on record | `verified = True` | no evidence of a rename; a company with no legal name change is unlikely to have changed ticker either |
| Bare, has CIK, a former name on record | `verified = False`, flagged | deliberately over-inclusive (any former name at all, not a tight date-overlap check), since a flagged entry costs a cheap manual look and a missed one would not |

The second row above was a real gap caught only by inspecting actual output: the first
version of this rule treated "no CIK to check" as equivalent to "checked and found nothing,"
defaulting to `verified = True`. That silently passed `BHGE` itself, the confirmed example
motivating this entire design, since SEC's current registry no longer recognizes `BHGE` (it
renamed again since, to `BKR`). Corrected once found.

**What this does and doesn't close.** Turns an unbounded, unverifiable risk into a short,
named list. Does not supply the correct historical ticker for a flagged entry, only that one
is worth checking; recovering the actual pre-2008 symbol still needs a manual look. Also not
a perfect detector: a ticker can change without a legal renaming (a symbol conflict, an
exchange switch), which this method would miss entirely.

**Example of what the manual check looks like:** ticker `CAL`, flagged, spanning
`1996-01-02` to `1996-07-19`, CIK `14707`. Its real SEC record:

```
CIK 14707, current ticker CAL (Caleres Inc.)
formerNames:
  BROWN SHOE CO INC     2003-06-25 to 2015-05-27
  BROWN SHOE CO INC/    1999-12-10 to 2003-06-13
  BROWN GROUP INC       1994-09-01 to 1999-04-26
```

In 1996 this company was legally Brown Group Inc., not Caleres, so `CAL` is very likely
another instance of the retroactive relabeling problem, reaching further back than any
confirmed 2008-2019 case. Not yet confirmed what the real 1996 ticker was, that confirmation
is precisely what `verified = False` is asking for.

### A bug found only by running it: unstitched book-era spans counted as active forever

The first working version of the combine step produced implausible results:
`membership_on()` returned 639 to 703 members for dates after 2008, far outside the 495 to
517 band established in Part 1. Tracing a concrete case, `BHGE` showed
`start_date = 1996-01-02, end_date = NaN`, and was being counted as an active member on
`2015-06-30`, eight years before Baker Hughes GE existed as a name.

**Root cause.** Any book-era span left open (no exit observed) that wasn't matched to a
continuing wiki-era entry kept a null `end_date`. The query logic reads a null `end_date` as
"still active today," which is only true for the wiki era, where the most recent snapshot
really is close to today. For the book era, null meant "we stopped looking on 2008-01-30,"
and treating that as "still active in 2026" claims eighteen years of certainty the data does
not support.

**Fix.** Any book-era span left open with no continuing wiki-era match has its `end_date`
capped at the book era's own last observed date (`2008-01-30`) rather than left null. 224 of
854 book-era spans needed this correction on the run that found the bug.

### Boundary stitching

With CIK as the shared key, `combine_universe_spans` recognizes a book-era span left open at
`2008-01-31` and a wiki-era span opening the same date, same CIK, as one continuous
membership, merging them: the book span's start date, the wiki span's (verified) ticker
going forward, and its real end date if it has one. Left as two adjacent rows when no
shared CIK confirms it, typically because the book-era company was delisted before 2008 and
never reached Wikipedia's coverage at all. 276 memberships were stitched this way.

### Final reconciled numbers

| Table | Rows | Breakdown |
|---|---|---|
| `universe_spans` | 1,569 | 717 wiki-only, 576 book-only, 276 stitched across the boundary |
| `ticker_history` | 2,809 | 2,523 verified, 286 flagged (93 no CIK match at all, 193 has a CIK with a former name on record) |

`membership_on()` now returns 499, 498, 500, and 501 members for `2000-01-03`, `2008-01-31`,
`2015-06-30`, and `2022-06-30` respectively, all inside the plausible band.

## Automated verification via SEC filings

193 of `ticker_history`'s book-era spans are flagged (`verified = False`). One alternative
was considered and rejected before building anything: asking an agent to search the web and
assert an answer. That fails the same test this project has already applied to other
sources, a scraped, non-reproducible judgment call is a weaker source than the "curated
repositories" already dismissed for undocumented methodology, since a repeat query to the
same agent isn't even guaranteed to reproduce the same answer, and a wrong answer carries no
way to audit itself.

### The method: read the company's own filings

For any flagged span with a CIK, SEC's `submissions` API exposes the entity's *complete*
filing history, not just the last ~1000 filings surfaced by the default endpoint, confirmed
live: `CAL`/Caleres's 1996 10-K405 only appears in a separate paginated file
(`filings.files`), going back to 1994. The pipeline:

1. Pull the complete filing history for the CIK.
2. Pick the 10-K or 10-K405 closest to the flagged span's start date, discarding anything
   more than 18 months away as uninformative rather than reporting a misleading match.
3. Fetch that filing's full submission text.
4. Search for a literal ticker disclosure and return it with the exact filing citation
   (accession number) and quoted sentence, or an honest `None` if nothing was found.

Every result is either a citable quote from a primary source or an explicit, reported gap,
never a bare assertion.

### Regex bugs found by checking real output, not assumed

Three bugs surfaced from hand-checking a handful of results against the actual filing text,
each caught before it could distort the full 193-row run:

| Bug | Example | Fix |
|---|---|---|
| Case-insensitivity applied to the whole pattern, not just the word "symbol" | matched `SHALL` from "the trademark symbol shall be expressed", and `FOR` from "...ticker symbol for the common stock..." | scope case-insensitivity to `(?i:symbols?)` only; the captured ticker must be genuinely all-caps in the source text |
| No sanity check on how far the nearest filing actually is from the span | `CCK` matched a filing from 2003 against a 1996-2000 span, three years past the span's own end | reject any nearest filing more than ~18 months away, report "no filing found" instead |
| Quoted, colon-listed, and dual-ticker phrasings not recognized | `HP`'s real 1995 filing states `...with the ticker symbol "HP."`, a genuine confirmation the first version of the pattern missed entirely because of the quotes | tolerate optional quotes, an optional colon, and an optional second ticker joined by "and" (for dual class or tracking stock disclosures) |

The `HP` case is worth naming specifically: it wasn't a false positive, it was a true,
citable confirmation the regex simply couldn't see at first, `Helmerich & Payne, Inc. Common
Stock is traded on the New York Stock Exchange with the ticker symbol "HP."` The book's
original `HP` ticker for that span was correct all along.

### What a genuinely ambiguous case looks like

`BCO`, flagged, `1996-01-02` to `1996-01-12`, CIK `78890` (Pittston Company, later The
Brink's Company). Its 1996 10-K405 never mentions `BCO` at all; instead it discloses two
pairs of tracking stock tickers, `PZS`/`PZM` and `PZB`/`PZX`, for a corporate restructuring
that took effect in the exact same ten day window as the flagged span. There isn't one clean
replacement ticker here, there are four, for what were at the time two separate securities.
Classified `confirmed_mismatch_ambiguous` rather than auto-corrected to any one of them,
since picking one would be a guess dressed up as a finding.

### Results across all 193

| Status | Count | Meaning |
|---|---|---|
| `confirmed_match` | 61 | Book's original ticker verified correct against a real filing |
| `confirmed_mismatch` | 18 | Book's ticker was wrong; one clear replacement found and applied |
| `confirmed_mismatch_ambiguous` | 3 | Wrong, but multiple candidates found (dual class or tracking stock); left for a person to resolve |
| `no_pattern_match` | 82 | A filing was found, but it doesn't state the ticker in any recognized form |
| `no_filing_found` | 29 | No 10-K exists within 18 months of the span (may itself indicate a reorganized CIK, as with `CCK`/Crown Holdings) |

82 of 193 (42%) are now resolved with a citable primary source. The other 111 (58%) remain
an honest, explained residual, not a failure of the method: mostly filings that simply don't
restate their own ticker (`no_pattern_match`), or CIKs whose filing history doesn't reach
back far enough (`no_filing_found`). Confirmed results were applied back into
`ticker_history`: `confirmed_match` rows get `verified = True` with a citation;
`confirmed_mismatch` rows get their `ticker` corrected, with the original book value kept in
a new `original_ticker` column and the citation in a new `evidence` column, so every
correction stays auditable rather than silently overwritten; `confirmed_mismatch_ambiguous`
rows are left exactly as they were, still flagged, still needing a person.

## Data model, final

Two parquet files under `data/processed/`, neither partitioned by date: each holds one row
per interval, a few thousand rows for the full history, so partitioning would add
complexity for files that already fit comfortably in memory.

**`universe_spans.parquet`**, membership:

| column | type | meaning |
|---|---|---|
| `ticker` | string | the symbol as its source reported it |
| `cik` | nullable Int64 | SEC's filer identifier, where derivable |
| `start_date` | string, ISO date | first date observed as a member |
| `end_date` | string, ISO date, or null | last date observed as a member; null means still active |
| `source` | string | `wikipedia_revision`, `clenow_norgate`, or `clenow_norgate+wikipedia_revision` for a stitched membership |
| `left_censored` | bool | `True` if `start_date` is the first date its era can observe |

**`ticker_history.parquet`**, symbol identity:

| column | type | meaning |
|---|---|---|
| `cik` | nullable Int64 | the entity, stable across renames |
| `ticker` | string | the symbol in use during this interval, corrected where the SEC filing check found a mismatch |
| `start_date`, `end_date` | string, ISO date, or null | the interval this ticker was in use; null end means still current |
| `source` | string | which era this entry came from |
| `verified` | bool | `True` if confirmed period-correct or evidence-backed; `False` if still flagged for manual review |
| `original_ticker` | nullable string | the book file's original value, populated only where the filing check corrected it, so a correction is never a silent overwrite |
| `evidence` | nullable string | the citing SEC accession number and quoted sentence, populated only where the filing check found a match or mismatch |

## Toy example: raw sources to processed tables

Following one real company, Apple, end to end, from what each raw source actually looks
like to the final combined row.

**Raw wiki source**, one row of the constituents table parsed from a monthly revision
(`2015-06-30`, columns trimmed to what matters here):

| Ticker symbol | ... | CIK |
|---|---|---|
| AAPL | ... | 320193 |

**Raw book source**, one row of the CSV, the whole day's membership as a single comma
joined string (only the relevant fragment shown):

```
1996-01-02,"...,AAPL,ABT,...,XOM,..."
```

Both get reduced by their respective loaders to the same shape, `(ticker, cik)` per
observed date, before anything else touches them:

| date | ticker | cik |
|---|---|---|
| 1996-01-02 (book) | AAPL | (none, book file has no CIK column) |
| 2015-06-30 (wiki) | AAPL | 320193 |

`build_spans` compresses many dates of presence into one interval per source, `attach_cik`
and the book-era CIK backfill fill in the identifier, `flag_left_censored` marks the
earliest date as uncertain, and `combine_universe_spans` stitches the book-era and wiki-era
pieces together via the shared CIK, since Apple was continuously a member across the 2008
boundary:

| ticker | cik | start_date | end_date | source | left_censored |
|---|---|---|---|---|---|
| AAPL | 320193 | 1996-01-02 | (null, still a member) | clenow_norgate+wikipedia_revision | True |

`left_censored = True` here means exactly what Part 1 established for `BCO`: Apple was
already a member when the book file's tracking begins in 1996, not that it joined that
specific day.

The same walk-through for a company that renamed, Priceline to Booking Holdings, produces
two rows in `ticker_history` instead of one continuous row in `universe_spans`, because
membership never stopped, only the label changed:

| cik | ticker | start_date | end_date | verified | source |
|---|---|---|---|---|---|
| 1075531 | PCLN | 2009-11-06 | 2018-03-31 | True | wikipedia_revision |
| 1075531 | BKNG | 2018-03-31 | (null, current) | True | wikipedia_revision |

## How to use the universe

**Where it lives.** `data/processed/universe_spans.parquet` and
`data/processed/ticker_history.parquet`, gitignored per the README's convention for
processed data, built by running `notebooks/exploring_universe.ipynb` top to bottom. Four
upstream caches make repeat runs fast:

| Cache | Contents | Cost, first run |
|---|---|---|
| `data/raw/wiki_snapshots.parquet` | 222 monthly Wikipedia snapshots | several minutes, ~440 requests |
| `data/raw/sec_ticker_cik.parquet` | SEC's bulk ticker-CIK registry | one request |
| `data/raw/former_names.parquet` | SEC legal name history per book-era CIK | one request per distinct CIK, throttled |
| `data/raw/filing_verification.parquet` | the SEC filing check's result for each of the 193 flagged spans | 2 to 3 requests per span, a few minutes |

To force a refresh, delete the file and rerun; there is no automatic expiry, an explicit
delete is simpler and more honest than a staleness check for data that only needs to be
current as of whenever the universe is next rebuilt.

**Querying membership on a date.** A ticker was a member on date `D` if
`start_date <= D <= end_date`, treating a null `end_date` as still active:

```python
def membership_on(universe_spans, date_iso):
    active = universe_spans[
        (universe_spans["start_date"] <= date_iso)
        & (universe_spans["end_date"].isna() | (universe_spans["end_date"] >= date_iso))
    ]
    return set(active["ticker"])
```

**Getting the actual symbol to hand a price vendor for a date.** Look it up in
`ticker_history` by CIK and date, do not read `ticker` directly off `universe_spans` for
this purpose, and check `verified` before trusting it without a second look.

**Caveats to carry into any consumer of these tables.**

| Caveat | What it means in practice |
|---|---|
| Precision differs by era | `wikipedia_revision` spans are accurate to the month; `clenow_norgate` spans to the day the book file recorded a change |
| Ticker strings are not vendor-ready symbols | Pre-2008 tickers may carry a `BASE-YYYYMM` suffix; multi class tickers are normalized to a period (`BRK.B`) where `yfinance` expects a hyphen (`BRK-B`); that translation belongs at the price loader boundary |
| CIK coverage has known gaps | absent before ~2014 for the wiki era; for the book era, resolved for 51% of spans (432 of 854), the rest split between suffixed tickers (no CIK possible by design) and unmatched bare tickers (worth investigating) |
| `left_censored` spans have no true join date | treat `start_date` as "at least since," not "exactly since"; irrelevant to any signal that doesn't use tenure length |
| `verified = False` is a to-do list, not a correction | 207 entries remain after the SEC filing check (down from 286): 93 with no CIK at all, 111 checked but inconclusive (no matching filing or no matching pattern), 3 genuinely ambiguous (multiple candidate tickers). None of these are confirmed wrong, just unconfirmed either way |
| `original_ticker` and `evidence` in `ticker_history` are populated only for corrected or confirmed rows | a null `original_ticker` means the ticker was never changed by this process, not that it was never checked; check `verified` and `evidence` together to tell the difference |
| The 2008 to 2019 window is Wikipedia only | except where a membership was stitched across the boundary |
| Dual class shares are kept as separate rows | resolved as a byproduct of the punctuation fix (Part 1): `UA`/`UAA` is the one remaining genuine case |

## Sources considered and rejected

| Source | Free | Redistributable | Point-in-time coverage | Verdict |
|---|---|---|---|---|
| SEC EDGAR | Yes | Yes | None: index membership isn't a regulatory fact, no filing records it | Rejected for membership; still essential for CIK, fundamentals, insider data |
| CRSP via WRDS | No | No | Excellent, the academic standard, includes delisting returns | Rejected on licensing grounds; useful as a private cross check for anyone with access |
| Curated repositories (e.g. other GitHub S&P 500 lists) | Yes | Varies | Usually derived from the same Wikipedia history | Reasonable as an independent cross check, unsuitable as a primary source, undocumented methodology |
| Wikipedia revision API | Yes | Yes | 2008 to present | Adopted as primary source, 2008 onward |
| Clenow/Norgate book file | Yes (MIT repo) | Rights unconfirmed | 1996 to 2019, but retroactively relabeled from 2008 onward | Adopted for 1996 to 2008 only |

## A gap found after promotion: two open ticker_history rows per CIK

Found 2026-08-05, not during the original build, while validating a downstream factor
computation (`notebooks/exploring_factors.ipynb`) against real earnings data. A random
sample of 60 companies included one whose ticker resolved to `FNF`, but whose fundamentals
showed a net loss of $6.654 billion for fiscal year 2023, an implausible figure for Fidelity
National Financial, a title insurer with a market capitalization near $15 billion that year.

### The cause

CIK 1136893's `entityName` in EDGAR's own `companyfacts` response is "Fidelity National
Information Services, Inc.", not Fidelity National Financial. The real event: in 2006, the
original Fidelity National Financial, Inc. (this CIK) spun off its title insurance business
into a new, separately incorporated company that kept the name and the ticker `FNF`, while
the original entity renamed itself Fidelity National Information Services and adopted the
ticker `FIS`, keeping CIK 1136893. SEC's current bulk registry confirms the split: `FNF` now
resolves to CIK 1331875, `FIS` to CIK 1136893.

`ticker_history` correctly holds evidence of both identities, but as two independent,
unreconciled rows:

| cik | ticker | start_date | end_date | source |
|---|---|---|---|---|
| 1136893 | FNF | 2006-11-10 | null | clenow_norgate |
| 1136893 | FIS | 2014-05-31 | null | wikipedia_revision |

The book-era row is itself a clean example of the retroactive relabeling problem from Part
2: the raw book CSV originally carried `FIS` (today's ticker) for this 2006-era span, and
the automated SEC filing check (accession `0000892569-07-000185`) found a 2007 filing that
states the ticker as "FNF", correctly overriding it. Both rows are independently accurate
for their own era. The defect is that neither the book/wiki concatenation step nor
`ticker_on` ever compares two rows for the same CIK against each other, so both stayed open
indefinitely, and `ticker_on` fell back to whichever row happened to sort first.

### Scope, measured across the full cache

Every CIK carrying more than one open ended (`end_date` null) `ticker_history` row: 286. Of
those, 273 have both rows agreeing on the ticker once the `BASE-YYYYMM` suffix is stripped
(for example `NKE`, `AAPL` era spans opening once in each source), harmless in practice
regardless of which row `ticker_on` picked. The remaining 13 disagree:

| CIK | Tickers | Likely event |
|---|---|---|
| 1136893 | FNF, FIS | 2006 spinoff, this case, confirmed above |
| 794367 | FD, M | Federated Department Stores to Macy's, 2007, not independently confirmed |
| 1018963 | ALT, ATI | Allegheny Technologies, exact mechanism not independently confirmed |
| 24545 | ACCOB, TAP | Adolph Coors to Molson Coors, 2005 merger, not independently confirmed |
| 93410 | CHV, CVX | Chevron, ticker changed around the 2001 Texaco merger, not independently confirmed |
| 26172 | CUM, CMI | Cummins, ticker symbol change, not independently confirmed |
| 895421 | DWD, MS | Dean Witter Discover to Morgan Stanley, 1997 merger, not independently confirmed |
| 823768 | UW, WM | USA Waste Services acquired Waste Management Inc. and took its name, 1998, not independently confirmed |
| 712515 | ERTS, EA | Electronic Arts, ticker symbol change, not independently confirmed |
| 1021860 | NOI, NOV | National Oilwell to National Oilwell Varco, 2005 merger, not independently confirmed |
| 833444 | P, TYC, JCI | Already named below: Johnson Controls / Tyco, 2016 merger, confirmed |
| 896159 | CB, ACE, CB | Already named below: ACE Limited / Chubb, 2016 merger, confirmed |
| 1652044, 1754301 | GOOGL/GOOG, FOXA/FOX | Already named below: monthly alternation, a different shape from this defect |

Two of these, 833444 and 896159, are the same cases already on record below as casualties of
a reverted fix attempt: the book-era row's CIK attribution is itself wrong, an unrelated,
no longer separately tracked company's history misattributed onto the surviving entity's CIK
by `backfill_book_cik`'s current-registry lookup. That is a different, harder defect than
this one: FNF and FIS share one genuinely continuous CIK; old Chubb Corporation and ACE
Limited do not.

### The fix and its limit

`ticker_on` now prefers the row with the latest `start_date` when more than one matches,
rather than array order. Checked against all 13 disagreeing CIKs for a present-day query
date, this returns the currently correct ticker in every case, including 833444 and 896159,
since a present-day query only ever needed the most recent row regardless of whether an
older row's CIK is itself correct.

What this does not fix: a historical query date that falls inside a wrongly attributed
book-era span (833444 or 896159, before 2014) still returns data for the wrong CIK. Nine of
the thirteen ticker pairs above are cited from a plausible real-world event, not
independently confirmed the way 1136893, 833444, and 896159 were. Resolving the underlying
CIK attribution remains open, tracked below. Covered by two new tests in
`tests/test_point_in_time.py`: one confirming the tie break picks the later row once both
match, one confirming a query date before the second row's start still returns the single
match unchanged.

## Open items

- Resolve the 3 `confirmed_mismatch_ambiguous` entries by hand (`BCO`/Pittston is one, a
  tracking stock restructuring with four candidate tickers, not one), since these are
  specifically the cases the automated pass identified as needing a person, not more
  automation.
- Decide what to do with the 111 `no_pattern_match` / `no_filing_found` entries and the 93
  with no CIK at all: resolve further by hand, broaden the filing-text search (a different
  keyword than "symbol," or fall back to an earlier or later filing when the nearest one
  doesn't state it), or defer until a specific flagged ticker is actually needed by a real
  backtest. The last option is proportionate given how much of the original 286 is already
  resolved; the remainder is a known, bounded, and now well-characterized residual rather
  than an open-ended one.
- Locate the precise earliest usable revision between 2006 and 2008, if history before 1996
  is ever wanted. Low priority: the book file's own reliability before 2001 is itself in
  question, per its source's README, so this would need a third source regardless.
- Promote the working notebook logic into `src/universe/point_in_time.py`, replacing the
  current `fetch_sp500_tables()` stub, per the build order in the README. The pipeline is
  now producing sane, cross-checked output end to end; this is the next real step.
- `build_ticker_history_wiki` groups snapshot rows by each row's own raw, per-snapshot CIK,
  found (while building the price loader, `notebooks/logs/loaders_construction.md`) to
  misattribute a company's rename history when Wikipedia's own reported CIK for a ticker
  changed across its edit history with no real trading discontinuity: Google/Alphabet
  (1288776 to 1652044, mid-2016) and 21st Century Fox/Fox Corp (1754301/1308161) each show up
  as two artificially separate CIKs instead of one continuous rename. A fix (resolve each
  ticker string to its latest reported CIK before grouping, mirroring `attach_cik`'s own rule
  for membership spans) was implemented and reverted after rebuilding revealed it also merges
  tickers handed off between two genuinely *different* companies via a real merger: ACE
  Limited's CIK inheriting Chubb Corporation's old `CB` ticker in 2016, and Johnson Controls
  merging with Tyco International, also in 2016, both fabricated an alternation pattern
  between two companies that were never concurrent, a worse problem than the one being fixed.
  The distinguishing signal, whether merging two CIK buckets for the same ticker creates a new
  alternation pattern versus resolves one that already existed continuously, is not yet
  implemented. Left as a known, documented gap rather than force a fix under time pressure;
  the price loader's own investigation is bounded by it (see that log for the practical
  consequence). Independently reconfirmed 2026-08-05 while investigating a downstream factor
  bug: see "A gap found after promotion" above, which found both Chubb/ACE (CIK 896159) and
  Tyco/Johnson Controls (CIK 833444) again via `ticker_history`'s ticker column, fixed
  `ticker_on`'s read-time resolution, and left this underlying CIK attribution exactly as
  open as it was here.
- The same underlying phenomenon (an administrative CIK change with no real trading
  discontinuity) also surfaces through a second, distinct mechanism: `backfill_book_cik`
  resolves a book-era ticker's CIK from SEC's bulk registry as of whenever it was fetched,
  not as of the historical period the span covers. Checked systematically (every ticker
  appearing under more than one CIK anywhere in `ticker_history`, 39 found; of those, 7 also
  show two different CIKs in `universe_spans` itself, `APC`, `BBBY`, `BBT`, `LB`, `NE`, `STI`,
  `XOM`, every one split exactly at the book/wiki era boundary, 2008-01-30 to 2008-01-31,
  too precise to be 7 coincidental real corporate events landing on the same date).
  Confirmed for `XOM` directly against SEC's live registry: it currently maps to CIK 2115436,
  "ExxonMobil Holdings Corp," not the long-standing "Exxon Mobil Corporation" CIK (34088) that
  Wikipedia's own table has stably reported, evidence of a recent holding-company
  reorganization with no real trading interruption, the same shape as Google/Alphabet's 2015
  reorganization, just caught by the book-era backfill instead of the wiki-era attach step.
  The remaining 32 of the 39 ambiguous tickers resolve to a single CIK in `universe_spans`
  (the `attach_cik` "latest wins" rule already absorbs the inconsistency there), so only these
  7 carry the sharper consequence of two CIKs both being genuine, recognized members at
  different times. Not fixed for the same reason as the point above; see
  `notebooks/logs/loaders_construction.md` for the practical consequence and the query
  discipline this requires from downstream code in the meantime.
