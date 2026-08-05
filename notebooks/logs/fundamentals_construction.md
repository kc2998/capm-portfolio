# Fundamentals loader construction: findings log

Record of what was learned while building and validating the EDGAR fundamentals loader.
Started 2026-07-31. Parts 1 through 12 were produced in `notebooks/exploring_fundamentals.ipynb`,
which built the loader and is kept as the historical record of that work. Part 13 onward were
produced in `notebooks/validating_fundamentals.ipynb`, which compares candidate implementations
against a fixed panel of companies and does not define its own copies of the loader's functions.

This file exists so the reasoning behind the fundamentals loader survives outside the notebook.
`notebooks/logs/factor_suite_design.md` states which themes and signals the loader needs to
support; this file states the evidence encountered while establishing whether and how EDGAR's
data can support them, organized to follow the notebook's own order: the vendor's raw shape and
target tag list first, then tag standardization across filers, then point in time
reconstruction from filed dates, then shares outstanding.

## The task

For each of the eight fundamentals-based JKP themes plus shares outstanding (value,
profitability, quality, profit growth, investment, accruals, debt issuance, low leverage,
size), determine what raw EDGAR XBRL data each one needs, and answer, without look ahead, what
value was actually known as of a given date, not the current, possibly restated figure.

| Requirement | Source | Why it matters |
|---|---|---|
| Use the filing date, not the period end date | README, "Point in time discipline" | a quarterly report covers a period that ended earlier than the date the figure became public; the filing date governs |
| Do not assume free fundamentals sources are restated only | README, "Known limitation to document honestly", flagged for revision here (see Part 3 and Open items) | if EDGAR's own filed history can be queried directly, the existing limitation may overstate the problem |
| One factor-computation interface, independent of any one filer's tag choices | `factor_suite_design.md`, "What we need to agree on before building" | a factor is a function over one value per universe member per date; the loader's job is to resolve whichever tag a given filer actually used to that one value, not to expose tag-name variation to the factor layer |

Union of raw concepts needed across the eight themes, distilled from
`factor_suite_design.md`'s data-dependency map:

| Concept | Feeds | Assumed primary tag |
|---|---|---|
| Total assets | Investment; low leverage; profitability denominator | `us-gaap:Assets` |
| Total liabilities | Low leverage | `us-gaap:Liabilities` |
| Stockholders' equity | Value (book/price); profitability (ROE); low leverage | `us-gaap:StockholdersEquity` |
| Net income | Value (E/P); profitability; quality; profit growth | `us-gaap:NetIncomeLoss` |
| Revenue | Value (S/P); profitability (gross margin) | `us-gaap:Revenues` |
| Gross profit | Profitability | `us-gaap:GrossProfit` |
| Operating cash flow | Value (CF/P); accruals | `us-gaap:NetCashProvidedByUsedInOperatingActivities` |
| Long term debt | Debt issuance; low leverage | `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebtCurrent` |
| Shares outstanding | Size; denominator for every "/price" ratio above | `dei:EntityCommonStockSharesOutstanding` |

## Background: filings, XBRL, and why a concept has no single tag

Recorded here because most of the difficulty in this loader comes from properties of the source
rather than from anything the code does, and a reader arriving at the alias machinery without
this context will read it as needless complication.

A price is a single observed number with one authoritative record that never changes. An
accounting figure is neither. It is produced by a company about itself, drawn from one of three
statements, and it can be revised after publication.

- The **balance sheet** is a snapshot at one instant, governed by the identity
  `Assets = Liabilities + Stockholders' equity`. Stockholders' equity, also called book value,
  is the residual claim: what would remain for shareholders if every asset were realized at its
  recorded value and every liability settled.
- The **income statement** covers a span of time, running from revenue down to net income.
  Gross profit is an intermediate subtotal, revenue minus the cost of revenue, meaning the
  direct cost of producing what was sold, before overhead, research, and tax.
- The **cash flow statement** also covers a span, and reports cash movement rather than
  accounting recognition. Net income and operating cash flow diverge because revenue is
  recognized when earned rather than when collected, and that divergence is exactly what the
  accruals theme measures.

The distinction between a quantity measured at an instant and a quantity measured over a span
(a stock and a flow) is the most consequential structural fact in this source. It reappears
directly in the data format, and Part 13 records a defect that follows from ignoring it.

Two further terms recur. A **fiscal year** need not be the calendar year: Apple's fiscal 2021
ran 2020-09-27 to 2021-09-25, and many retailers use a 52 or 53 week calendar ending on a fixed
weekday, so period lengths vary by several days year to year. A **restatement** is a revision to
an already published figure, sometimes an error correction and sometimes an accounting method
change applied retrospectively.

Public companies file annual reports (form 10-K), quarterly reports (form 10-Q), and amendments
to either (10-K/A, 10-Q/A) with the SEC, archived publicly in EDGAR. Each filer carries a
**CIK**, a permanent numeric identifier that survives renames and ticker changes, which is why
this project keys on CIK throughout; each individual submission carries an accession number.

Since 2009, filers have also attached a machine readable version of each filing in **XBRL**
(eXtensible Business Reporting Language). XBRL does not restructure the filing, it annotates it:
each presented number is wrapped in a label naming the concept it represents, the period it
covers, and its units. Those labels are drawn from a published **taxonomy**, a dictionary of
defined concepts. Two are relevant: `us-gaap`, holding on the order of fifteen thousand
financial statement elements, and `dei` (Document and Entity Information), a small set of cover
page facts about the filer itself. An individual element is what this log calls a **tag**.

The critical property is that the SEC issues a dictionary, not a form. Filers describe their own
statements using it, and four distinct consequences follow.

1. **The dictionary offers several elements for what looks like one concept.** Revenue alone has
   been reported under `Revenues`, `SalesRevenueNet`, and
   `RevenueFromContractWithCustomerExcludingAssessedTax`, among others. None is incorrect.
2. **The dictionary changes as accounting standards change.** The 2018 revenue recognition
   standard (ASC 606) introduced the third tag above and deprecated the second, so a filer's tag
   choice partly encodes when it filed. A sample drawn from a single recent date cannot observe
   any era but the current one, which is what motivated Part 12.
3. **Filers tag only what they present.** XBRL annotates the statement rather than generating
   one, so a company whose income statement shows no gross profit subtotal has no `GrossProfit`
   fact under any name. This is a presentation choice, not absent data.
4. **Some concepts do not apply to some business models.** Banks report interest income,
   interest expense, and non-interest income rather than a generic revenue line, because the
   economics do not map onto one. No quantity of aliases resolves this.

A fifth complication is unrelated to vocabulary. XBRL supports **dimensions**, a mechanism for
breaking a fact down by category (revenue by geography, shares outstanding by share class). The
`companyfacts` endpoint serves only the undimensioned version of each fact, so a filer that
reports a quantity solely per class has no value for that quantity in this source at all.

Finally, each fact carries three dates, and conflating them is the point in time failure this
project exists to avoid. `start` and `end` describe the period the number covers, with balance
sheet facts carrying `end` alone since they describe an instant. `filed` is the date the number
became public. A backtest may condition only on `filed`.

This tag standardization work is the principal reason commercial fundamentals vendors exist:
Compustat and its competitors employ analysts to map heterogeneous filings onto a fixed schema.
`TAG_ALIASES` is a small and transparent version of the same task, and is therefore a maintained
list rather than a problem that gets finished.

## Part 1: the vendor's raw shape and the target tag list

EDGAR's `companyfacts` API (`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`,
the same `SEC_HEADERS` User-Agent already established in `src/universe/point_in_time.py`)
returns one JSON document per company: an `entityName`, and a `facts` object split into two
taxonomies, `dei` (entity-level cover page facts) and `us-gaap` (financial statement facts).
Each tag under either taxonomy holds a list of individual data points, one per reporting period
and filing.

Apple (CIK 320193), a large and long-tenured filer, exposes 503 `us-gaap` tags and 2 `dei`
tags, far more than the nine concepts assumed above. The target list was checked against
Apple's tags directly rather than assumed: all nine `us-gaap` tags and the one `dei` tag were
present under the exact names assumed.

## Part 2: tag standardization across filers

A single well tagged filer does not establish that tag names are standardized. Costco (CIK
909832, a second large, older filer) and DoorDash (CIK 1792789, already present in
`data/raw/prices/`, IPO'd December 2020) were checked against the same nine `us-gaap` tags and
one `dei` tag. Costco matched cleanly, identical to Apple. DoorDash did not: four `us-gaap`
tags and the `dei` tag were absent.

That one list of absences conflated three distinct causes, worth separating:

- **Revenue is a genuine tag-name synonym.** DoorDash reports
  `RevenueFromContractWithCustomerExcludingAssessedTax` instead of `Revenues`, the tag
  introduced by the 2018 revenue recognition standard (ASC 606). Older filers such as Apple and
  Costco continue to report `Revenues`; DoorDash, which began filing after the standard took
  effect, never used the older tag.
- **Gross profit is not always tagged at all.** DoorDash has no `GrossProfit` tag under any
  name. It reports `RevenueFromContractWithCustomerExcludingAssessedTax` and, on the cost side,
  `CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization`, so gross profit must be
  derived as revenue minus cost of revenue for this filer rather than read from one tag, and the
  cost tag's name is no more standardized than revenue's.
- **Long term debt tags are absent, cause unconfirmed.** DoorDash has neither
  `LongTermDebtNoncurrent` nor `LongTermDebtCurrent`. Not yet established whether this reflects
  a genuinely zero debt balance or a further, unidentified tag name; see Open items.

A tag alias mechanism was built to resolve the first two cases: `TAG_ALIASES` maps a concept
name to an ordered list of `(taxonomy, tag)` pairs, checked in order, first match wins.
`resolve_tag(facts, concept)` returns the first pair actually present. Verified directly:
revenue resolves to `("us-gaap", "Revenues")` for Apple and Costco and to `("us-gaap",
"RevenueFromContractWithCustomerExcludingAssessedTax")` for DoorDash. Gross profit resolves
`("direct", "GrossProfit")` for Apple and Costco and `("derived", revenue_tag, cost_tag)` for
DoorDash.

## Part 3: point in time reconstruction from filed dates

The README currently states that free fundamentals sources "generally show current, restated
financials, not the originally filed numbers as they stood on the filing date." Whether this
applies to EDGAR's own `companyfacts` API specifically, as opposed to a downstream vendor that
only ever surfaces the latest figure, had not been checked directly, so it was tested against
Apple's `NetIncomeLoss` history.

Apple's `NetIncomeLoss` carries 338 total data points. Grouped by the reporting period each
point describes (`start`, `end`), 112 periods have more than one recorded value. Most of these
are not restatements: a company re-reports the same historical figure as a prior year
comparative in every later filing covering that period, identical value, only the filing date
and accession number differ. Filtering to periods where the value itself changed leaves 5
genuine restatements.

One is trivial: fiscal year 2007 net income moved from $3,496,000,000 to $3,495,000,000, a
$1,000,000 correction, filed 2010-01-25. The other four are not: fiscal year 2008 net income
moved from $4,834,000,000 (original 10-K, filed 2009-10-27) to $6,119,000,000 (10-K/A, filed
2010-01-25), a 27 percent change, and fiscal year 2009 net income similarly moved by
approximately 44 percent, both traced to the same 2010-01-25 10-K/A. This is Apple's early
adoption of ASU 2009-13/14, which eliminated subscription method revenue recognition for
iPhone and Apple TV sales (previously deferred over the device's estimated life) in favor of
recognizing it upfront, applied retrospectively to prior periods. It is a genuine accounting
policy change, not an error correction, and it is exactly the shape of look ahead the README's
point in time discipline exists to prevent: an investor in late 2009 could only have seen the
smaller, pre-restatement figure.

`fact_as_of(facts, taxonomy, tag, unit, period_end, as_of_date)` returns the data point for a
given period with the latest `filed` date that is still on or before `as_of_date`, or `None` if
nothing had been filed yet. Verified directly against the fiscal year 2008 case: queried as of
2009-12-01 (before the 10-K/A), it returns the pre-restatement $4,834,000,000 from the original
10-K; queried as of 2010-06-01 (after), it returns the post-restatement $6,119,000,000 from the
10-K/A. The mechanism was confirmed to prevent the look ahead, not merely describe it.

This is evidence that the README's current fundamentals limitation is broader than warranted,
at least for EDGAR's own `companyfacts` API: filed history is retained as distinct historical
entries, each with its own filing date and accession number, and is directly queryable for a
point in time value. The restated-only problem may be specific to derived or vendor sources
that expose only the latest figure, rather than to the primary source itself. Flagged as a
candidate revision to the README's stated limitation rather than changed here; see Open items.

## Part 4: shares outstanding, a cross taxonomy problem, not a dimensional one

DoorDash's missing `dei:EntityCommonStockSharesOutstanding` was initially suspected to reflect
per-class dimensional data (DoorDash has multiple stock classes) dropped by the bulk
`companyfacts` endpoint, which is documented elsewhere to expose only non-dimensional, default
context facts. Tested against Alphabet (CIK 1652044), a second multi-class filer already
relevant to an open question in `universe_construction.md`, whether `GOOG`/`GOOGL` should be
treated as one company or two.

The hypothesis did not hold as stated. Alphabet reports a single, non-dimensional
`us-gaap:CommonStockSharesOutstanding` figure (approximately 12.1 billion shares in its most
recent filings, consistent with its actual combined share count across classes), not a
class-level breakdown. The absence is not dimensional dropping in general; it is the same
taxonomy and tag-choice inconsistency already seen with revenue, now spanning two taxonomies
(`dei` and `us-gaap`) rather than tag names within one.

`TAG_ALIASES` and `resolve_tag` were generalized accordingly: every alias list is now a list of
`(taxonomy, tag)` pairs uniformly, rather than a fixed taxonomy per concept with tag-name-only
aliases, since shares outstanding could not be expressed in the earlier, narrower shape.
Verified across four companies: Apple and Costco resolve via `dei:EntityCommonStockSharesOutstanding`;
Alphabet resolves via the `us-gaap:CommonStockSharesOutstanding` fallback; DoorDash resolves to
`None` under either name. DoorDash's `us-gaap` facts were checked directly and contain only
`PreferredStockSharesOutstanding` (0), `TemporaryEquitySharesOutstanding` (a mezzanine equity
classification, not the common float), and the weighted average variants (a period average,
not a point in time balance), confirming this as a genuine, bounded residual rather than an
artifact of insufficient alias coverage.

Superseded in part by Part 12, including this section's heading. The dimensional hypothesis was
rejected here on Alphabet's evidence alone, and that rejection was too broad. Meta reproduces
DoorDash's shape exactly, and Alphabet is the exception rather than the rule: it escapes
dimensional dropping only because it additionally tags a combined, undimensioned figure. Read
this section as establishing that a `us-gaap` fallback recovers some filers, not that dimensional
dropping is absent.

## Part 5: accruals, and a single function for tag resolution plus point in time lookup

Accruals, profitability's cash-flow method: `(net income - operating cash flow) / assets`. All
three concepts (`NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, `Assets`) had
already been confirmed present under standard names for every company tested in Part 2's
missing-tag check, so no new alias work was needed here. This was instead the natural point to
stop testing tag resolution (`resolve_tag`) and point in time lookup (`fact_as_of`) separately:
`concept_value_as_of(facts, concept, unit, period_end, as_of_date)` chains the two, resolving
which tag a filer uses for a concept and returning the value known as of a date in one call.

Verified across all four companies with one real annual period each: Apple -0.072, Costco
-0.087, DoorDash -0.170, Alphabet -0.078. DoorDash's case is a useful sanity check on its own:
a net loss (-$468,000,000) alongside positive operating cash flow ($692,000,000, typical of a
growth-stage company with large non-cash stock-compensation add-backs) still produces a
sensible accruals figure rather than a nonsensical one.

## Part 6: debt issuance, and a fix to how aliases get resolved

Debt issuance: year over year change in total long term debt (`long_term_debt_noncurrent` plus
`long_term_debt_current`), scaled by prior period assets. Using the aliases and mechanism as
they stood after Part 2 produced two failures worth separating.

DoorDash's total debt came back entirely unresolved. Checked directly: DoorDash's actual long
term debt is tagged `ConvertibleLongTermNotesPayable` and `ConvertibleNotesPayableCurrent`
(convertible notes, not traditional term debt), confirmed against a real total liabilities
balance of $9,501,000,000 that this was a genuine tag-name gap, not a zero balance. Added as a
fourth and fifth alias.

Alphabet's total debt also came back unresolved for 2021 and 2022, for a more serious reason.
`LongTermDebtNoncurrent` has data for Alphabet from 2014 through 2020-06-30, nothing at all for
2021 or 2022, then resumes from 2023 onward. For 2021 and 2022, Alphabet reported one
undifferentiated `LongTermDebt` figure instead of splitting noncurrent and current. This broke
an assumption built into `resolve_tag`: that a company uses one canonical tag for a concept
across its entire history, resolved once and reused for every period. Alphabet shows this is
false; which tag a company uses can change across its own filing history, not only vary company
to company.

Fixed by folding `resolve_tag` and `concept_value_as_of` into a single function that tries every
alias for the specific period being queried, rather than committing to one tag per company up
front. Verified this closes the gap: Alphabet's 2021 noncurrent debt now resolves via the
`LongTermDebt` fallback ($15,440,000,000 as of 2022-02-02).

A second, smaller finding surfaced in the same debugging, left as a design position rather than
a bug to fix: Alphabet's 2019 current-debt figure ($0) was not filed until 2020-10-30 and
2021-02-03, well after the original FY2019 10-K (filed 2020-02-04). Querying as of shortly
after that original 10-K correctly returns "not yet disclosed." Decided explicitly rather than
left implicit: a period with no data under any known alias is always returned as `None`, never
inferred as zero, consistent with the README's existing missing-data rule for `scoring/combine.py`
(drop the term, do not substitute zero, since zero implies "average" not "unknown"). A missing
debt tag might mean zero debt, or might mean the breakdown simply was not filed yet; conflating
the two would misrepresent what was actually known on a given date. This means finer breakdowns
(a noncurrent/current split) will show more missing coverage in early periods than a coarser
combined figure would, a real, accepted cost of the policy rather than a defect.

Debt issuance verified across the test set: Apple 0.0159, DoorDash and Alphabet both correctly
`None` for their respective prior periods (DoorDash's prior period predates any of its debt
tags; Alphabet's prior period predates its current-debt disclosure), which is the missing-data
policy working as intended, not a failure of the mechanism.

## Part 7: investment, profit growth, and low leverage

Three more themes, each a direct reapplication of `concept_value_as_of` with no new resolution
logic: investment (asset growth, `Assets` at two dates), profit growth (change in net income,
scaled by prior assets for the same reason as accruals and debt issuance: comparable magnitude
across companies of very different sizes, and no sign flip when prior net income is itself
negative), and low leverage (book leverage, `Liabilities / Assets`, a single-date ratio needing
no year over year comparison). `total_liabilities` and `stockholders_equity` added to
`TAG_ALIASES`, both resolving cleanly under their standard names for all four companies.

One test-date artifact, not a mechanism problem: DoorDash's FY2020 10-K was filed 2021-03-05,
four days after an initially chosen `as_of_date` of 2021-03-01, which correctly produced
`None` rather than skip-ahead data. Corrected by moving the test date later, not by changing
the mechanism.

Verified across all four companies: Apple (-4.3% asset growth, +0.6% profit growth, 79.8% book
leverage), Costco (+22.4% asset growth, reflecting 2020 demand growth, 66.3% leverage), DoorDash
(+7.2% asset growth, roughly flat profit growth), Alphabet (+15.8% asset growth, +2.1% profit
growth, 30.4% leverage).

## Part 8: value, a join with the price loader, and a split-adjustment bug

Value is the one theme not answerable from fundamentals data alone: it needs market
capitalization (shares outstanding times price) to form book-to-price and earnings-to-price
ratios, the first point this notebook joined fundamentals data to the existing price loader
(`src/loaders/prices.py`).

DoorDash was excluded from this pass for two compounding, unrelated reasons, not a value-theme
bug: its shares outstanding is the already-documented Part 4 gap, and its cached price file
(`data/raw/prices/1792789.parquet`) only covers 2025-03-31 onward, because the price loader
caches a CIK's actual S&P 500 membership span rather than its full trading history, and
DoorDash only joined the index in March 2025.

For Apple and Costco, market cap came out correct on the first attempt (Apple approximately
$2.02 trillion as of 2020-12-01, matching its well known crossing of $2 trillion in August
2020; Costco approximately $144.9 billion). Alphabet did not: computed market cap of $69.3
billion, obviously wrong for a company worth over a trillion dollars in early 2021.

Root cause, confirmed directly: cached prices are always split adjusted (Part 1 of
`loaders_construction.md`, no `Adj Close` column exists because adjustment is baked into
`Close` directly, deliberately, for correct total-return backtesting), but a shares-outstanding
figure from a historical SEC filing is as-filed, never retroactively adjusted for a split that
had not yet happened. Alphabet split 20 for 1 on 2022-07-18 (confirmed in the cached price
file's `Stock Splits` column). Multiplying an as-filed, pre-split share count by an already
split-adjusted price silently understates market cap by the split ratio: $69.3 billion times 20
is approximately $1.385 trillion, matching Alphabet's real market cap on 2021-03-01 almost
exactly (it closed around $2,061 per share pre-split that day; $102.57 times 20 is
approximately $2,051, the same number). This is structural, not a bug specific to one alias: it
will silently affect every value-theme computation for a historical date, for any company that
has ever split its stock.

A second, compounding bug was found while building the fix. Alphabet is a dual class filer
(`GOOG` and `GOOGL` both trade concurrently), and its cached price file contains both tickers'
rows together. Reading that file directly and taking whichever row sorts last for a date mixes
the two tickers, which independently produced two consequences: it picks between two genuinely
different real prices somewhat arbitrarily, and it double counts the same real-world split
event once per ticker (confirmed directly: the raw `Stock Splits` column showed two rows dated
2022-07-18, both value 20.0, one per ticker, which without correction inflated the computed
adjustment factor to 400 instead of 20). Fixed by using `ticker_on(ticker_history, cik, date)`,
the loader's own established convention for picking one consistent ticker for a CIK on a given
date (already used throughout `src/loaders/prices.py`), rather than reading `load_cik_prices`'
output unfiltered.

`split_adjustment_factor(one_ticker_prices, since_date)` computes the cumulative product of
every split recorded after `since_date` within one ticker's own series, reproducing the factor
already baked into the cached price, then applied to the as-filed share count before computing
market cap. Verified: Apple and Costco both correctly show a factor of 1.0 (no qualifying
split after their respective periods), leaving their already-correct numbers unchanged.
Alphabet's factor comes out to exactly 20.0, and its corrected market cap of approximately
$1.385 trillion, book-to-price of 16.1 percent, and earnings-to-price of 2.9 percent are all now
in line with its real 2021 valuation.

Not resolved, and not attempted here: for a dual class company, this approach uses one class's
price (whichever `ticker_on` returns) multiplied by the combined share count across all
classes, rather than summing each class's own shares times its own price. A common simplifying
approximation in practice, but not exactly correct if share classes trade at meaningfully
different prices (a control premium or liquidity difference between voting and non-voting
shares). See Open items.

## Part 9: broader sample testing, and two findings that are not mechanism failures

Everything to this point had been tested against four hand-picked companies chosen to surface
known-hard cases, which says nothing about the general failure rate. Checked against 30
companies drawn from the actual S&P 500 membership on 2020-01-01, not hand-picked: all 30
fetched successfully from `companyfacts` (S&P 500 members are large, established filers,
unsurprising that none are absent from EDGAR entirely). Coverage per concept, checking only
whether any alias resolves anywhere in a filer's history, not a specific dated value:

| concept | coverage |
|---|---|
| total assets | 30/30 (100%) |
| shares outstanding | 30/30 (100%) |
| net income | 29/30 (97%) |
| stockholders equity | 29/30 (97%) |
| operating cash flow | 29/30 (97%) |
| revenue | 27/30 (90%) |
| long term debt, noncurrent | 27/30 (90%) |
| total liabilities | 22/30 (73%) |
| cost of revenue | 20/30 (67%) |
| long term debt, current | 18/30 (60%) |

The two weakest numbers both resolve into an explanation, not a coverage problem to keep
chasing with more aliases.

**Total liabilities' gap is a derivation gap, not a coverage gap.** The 8 failing companies
(McKesson, FMC, Whirlpool, Lumen, Fastenal, Gap, AutoZone, Corpay) all report `Assets` and
`StockholdersEquity` directly but never tag an explicit `Liabilities` total, since it is
implied by the balance sheet identity `Liabilities = Assets - StockholdersEquity`. Confirmed
directly for two of them (McKesson, Fastenal): both have `Assets`, `StockholdersEquity`, and
`LiabilitiesAndStockholdersEquity` tags, none of them an explicit `Liabilities` figure. Fixed by
adding a `total_liabilities_as_of` helper with the same direct-tag-then-derive shape already
used for gross profit, rather than searching for a nonexistent fourth alias.

**Revenue's gap is a genuine sector difference, not a naming variant.** The 2 failing companies
in this sample, Truist Financial and Fifth Third Bancorp, are both banks. Banks do not have
"revenue" in the conventional sense; they report interest and non-interest income under
entirely different concepts, because the business model itself does not map onto a generic
revenue line. Documented as an accepted, sector-specific limitation of the value theme as
built, not something more aliases can fix.

## Part 10: sanity check fixtures

Before promoting anything, quick assertions against synthetic fixtures rather than live data,
targeting specifically the two mechanisms that had already hidden real bugs behind "looks right
for every company tried so far": `concept_value_as_of`'s per-period alias resolution (fixture
mirrors Alphabet's real `LongTermDebtNoncurrent`-to-`LongTermDebt` switch), its point in time
selection (fixture mirrors Apple's real restatement, a later `filed` date must never be
returned for an earlier `as_of_date`), `total_liabilities_as_of`'s direct-then-derive fallback,
and `split_adjustment_factor`'s cumulative product and its date boundary (a split landing after
`since_date` must count, one on or before it must not). All passed. One boundary deliberately
left unverified against real data: whether a split landing exactly on a fundamentals period end
should count is an assumption the fixture asserts, not a confirmed fact about how EDGAR period
ends and a split's effective date actually relate.

## Part 11: promotion into `src/loaders/fundamentals.py`

Two decisions made before writing any promoted code, since both shape the module's entire
structure.

**Cache raw `companyfacts` JSON per CIK, resolve at query time**, rather than precompute and
cache resolved values. Mirrors `prices.py` exactly: `load_cik_prices()` returns raw OHLCV, and
anything downstream is computed from that raw cache at use time. The alternative (precompute
every concept for every period into a flattened table) would bake in today's alias list and
derivation rules; fixing an alias or adding a derivation, both of which happened multiple times
while building this, would then require a full rebuild to take effect rather than an immediate
fix.

**`src/loaders/README.md` restructured to cover both loaders as sections** (`## Prices`, `##
Fundamentals`), rather than a second, separate README file, since the original file was titled
specifically for prices despite living in a directory meant to hold multiple loaders
(`fundamentals.py`, `insider.py`, `short_interest.py` per the main README's own repo-structure
sketch).

**`price_as_of` and `split_adjustment_factor` are deliberately not promoted into
`fundamentals.py`.** Both join fundamentals data to price data to compute an actual factor
value (market capitalization, book to price, earnings to price), which is what
`src/factors/value.py` is for, a later build-order step. `fundamentals.py` stays a pure loader:
fetch, cache, and resolve raw concept values point in time, nothing that reads from
`src/loaders/prices.py`. Both functions remain in this notebook only, until `src/factors/value.py`
is actually built.

What was promoted: `fetch_company_facts`, `save_company_facts`, `load_company_facts`,
`TAG_ALIASES`, `concept_value_as_of`, `total_liabilities_as_of`, `gross_profit_as_of`, and
`build_fundamentals` (mirroring `build_prices`'s own two-branch contract: load the existing
coverage report if present, otherwise fetch and cache every CIK in `ticker_history`, recording
`fetched: False` rather than silently skipping a CIK with no XBRL history, the same discipline
the price loader applies to delisted tickers). `scripts/build_fundamentals.py` added as the
thin entry point. `tests/test_fundamentals.py` adapts the Part 10 fixtures directly, 12 tests,
all passing; the full suite (48 tests across all three modules) stays green. Verified against
real data after promotion, not only the synthetic fixtures: Apple's net income, total
liabilities, and gross profit, and DoorDash's derived gross profit, all reproduce the values
already established earlier in this notebook.

`build_fundamentals()` has not been run against the full universe. `data/raw/fundamentals/` is
empty until that is actually run, a genuine network operation against roughly 500 to 1,000
CIKs.

## Part 12: a broader, multi era sample, and the separation of four distinct failures

Dated 2026-08-01. Every sample to this point shared a defect that only becomes visible once
stated: the four hand-picked companies were chosen to surface known-hard cases, and the 30
company sample in Part 9 was drawn from S&P 500 membership on a single date, 2020-01-01. A
single-date sample can contain only companies that were in the index on that date, which is to
say survivors of everything that happened before it, and it can observe only whichever
accounting standard era was current, since tag choice partly encodes filing era (see Background,
consequence 2). Both restrictions matter for a point in time backtest, whose whole purpose is to
include the companies that later left.

The replacement sample draws 30 CIKs from `universe_spans` rows carrying a non-null `end_date`
(entities that have since left the index, whether acquired, delisted, or failed) and 30 from
membership active on 2025-01-01, deduplicated by CIK, for 60 distinct companies spanning
membership dates from the 1990s to the present. All 60 returned `companyfacts` data
successfully.

The Part 9 coverage table also conflated questions that have different answers and different
remedies, so this pass asks four separately:

| Question | Count | Companies |
|---|---|---|
| No revenue under any alias | 6 of 60 | `PLL`, `CCU-200807`, `CCE`, `BCR`, `LLTC`, `ACT` |
| Revenue present, but neither `GrossProfit` nor any cost of revenue alias | 15 of 60 | `EHC`, `H-200107`, `CEG`, `KSU`, `TE`, `GGP`, `BHF`, `SEG-200011`, `INVH`, `CMG`, `UDR`, `TPL`, `BEN`, `KKR`, `ACGL` |
| No liabilities path, direct or derived | 1 of 60 | `CCU-200807` |
| No shares outstanding tag in either taxonomy | 2 of 60 | `H-200107`, `META` |

Four findings, of which only the first is an alias gap.

**A `SalesRevenueNet` alias is needed, and only a multi era sample could have shown it.** The
tag was the common pre-2018 choice, deprecated when ASC 606 introduced
`RevenueFromContractWithCustomerExcludingAssessedTax`. Found by drilling into a pre-2018 filer
in this sample. Not yet added to `TAG_ALIASES`. Goldman's
`RevenuesNetOfInterestExpense` surfaced by the same route and is a bank-specific concept rather
than a general synonym, discussed below.

**The gross profit gap is a presentation and sector reality, not an alias gap, and it is
large.** Fifteen of 60, a quarter of the sample, report revenue but offer no path to gross
profit under either the direct tag or the revenue-minus-cost derivation from Part 2. The names
are concentrated in businesses whose income statements have no cost-of-goods line to subtract:
REITs (`INVH`, `UDR`, `GGP`), asset managers and alternative managers (`BEN`, `KKR`), insurers
(`ACGL`, `BHF`), utilities and railroads (`CEG`, `TE`, `KSU`), and restaurant operators that
present operating costs in several lines without subtotaling (`CMG`). Gross profits to assets is
the headline characteristic for the JKP profitability theme, so a theme-level fallback
characteristic is required rather than further alias search. This is a design decision, recorded
under Considerations below, not something more work on the loader resolves.

**Meta reproduces the DoorDash shares outstanding gap, which establishes it as structural rather
than an artifact of one young filer.** Checked directly against EDGAR: Meta's `dei` block
contains only `EntityPublicFloat`, and its `us-gaap` block contains no
`CommonStockSharesOutstanding`, only `PreferredStockSharesOutstanding` (zero) and the weighted
average variants. This is dimensional dropping (Background, fifth complication) applied to a
multi-class filer that reports its share count solely per class. Part 4 tested this hypothesis
against Alphabet and reported that it did not hold; the correct reading is narrower than Part 4
concluded. Dimensional dropping is real, and Alphabet escapes it only because it additionally
tags a combined, undimensioned `us-gaap:CommonStockSharesOutstanding` figure. Filers that do not
are simply absent from this endpoint. Meta is the largest company in the sample, so this is not
a marginal gap.

**Tickers carrying a date suffix trace to the universe module, not to this loader.** `CCU-200807`,
`H-200107`, and `SEG-200011` are disambiguated symbols produced by
`src/universe/point_in_time.py` where one ticker string was held by more than one entity over
time. Their empty fundamentals results were established during the notebook run to follow from
the already-documented CIK misattribution issue in that module (see
`universe_construction.md`'s Open items) rather than from any tag resolution failure here. Noted
so that a later reader does not re-investigate them as a fundamentals defect.

## Part 13: three defects in how a fact's dates are interpreted

Dated 2026-08-02. Found by inspecting EDGAR's returned facts directly, not by running the
loader, and therefore not visible to any of the coverage passes above. All three concern the
meaning of a fact's dates rather than the resolution of its tag, which is a layer the notebook
had treated as settled since Part 3.

**A flow concept is identified by `start` and `end` together, but `concept_value_as_of` filters
on `end` alone.** At a fiscal year end this happens to be harmless, since only the annual figure
carries that end date. At a quarter end it is not, because the same end date carries both the
three month figure and the year to date figure. Alphabet's `NetIncomeLoss` at `end = 2021-06-30`:

| start | duration | value | filed |
|---|---|---|---|
| 2021-04-01 | 90 days | $18,525,000,000 | 2021-07-28 |
| 2021-01-01 | 180 days | $36,455,000,000 | 2021-07-28 |

Both were filed on the same date, so selecting the latest `filed` breaks the tie by list order
and returns the year to date figure, roughly double the quarterly one, with no error raised. The
same shape holds at `end = 2021-09-30` ($18,936,000,000 for the quarter against $55,391,000,000
for the nine months). Fiscal year ends were checked separately and are currently safe: Apple's
fiscal 2021, and Alphabet's, Costco's, JPMorgan's, and Coca-Cola's 2021 year ends each carry
exactly one duration. The consequence is confined to quarterly queries, which is precisely the
PEAD/SUE signal the loader was built to unlock, and any quarter-over-quarter profit growth
computation. This is the stock and flow distinction from the Background section reappearing as a
defect.

Incidentally confirming that the point in time layer itself works: JPMorgan's fiscal 2021 net
income appears at the same duration under two values, $48,334,000,000 and $48,300,000,000, a
genuine later revision, correctly separated by the `filed` rule.

**`end` does not mean the same thing on a `dei` fact as on a `us-gaap` fact, so a period-matched
query for shares outstanding can essentially never succeed on the primary alias.**
`dei:EntityCommonStockSharesOutstanding` answers "how many shares existed when this document was
prepared", so its `end` is a cover page date falling weeks after the fiscal period closed.
Apple's first quarter fiscal 2026 entry carries `end = 2026-01-16` for a quarter that ended
2025-12-27. Measured across Apple's full history, the dei end dates and the
`us-gaap:CommonStockSharesOutstanding` end dates coincide once in roughly 70 entries. Apple's
fiscal 2020 share count, used for the market capitalization check in Part 8, therefore resolved
only through the second alias, and the first alias contributed nothing. Any filer tagging only
the mandatory `dei` cover page disclosure and not the optional `us-gaap` element returns `None`
for every period-matched query, silently. Shares outstanding is not a period-scoped quantity in
the way a balance sheet item is, and forcing it through the same interface is the error.

**The coverage figures throughout this log measure tag existence, not dated resolution.**
`resolve_anywhere` asks only whether a tag name appears anywhere in a filer's history. That is a
legitimate screen for alias adequacy, and it is what Parts 9 and 12 report, but it is a
different and easier question than whether a dated query returns a value. Given the finding
above, the reported 100 percent coverage for shares outstanding in Part 9 measures the easier
question. The dated resolution rate has not been measured for any concept.

## Part 14: the standing test panel, and Decision A on how a period type is identified

Dated 2026-08-04. This part settles the first of the four decisions listed under Considerations
below, and establishes the sample that the remaining three will reuse.

### The panel

Prior testing used four hand-picked companies and a 30 company sample drawn from S&P 500
membership on a single date, 2020-01-01. A single-date sample necessarily contains only
companies that were members on that date, and can observe only whichever accounting standard era
was current, so neither departed companies nor earlier tag vocabularies are represented. Rather
than draw a fresh random sample for each decision, which makes results incomparable across
decisions and invites stopping when a number looks favorable, a fixed panel of 18 companies was
constructed and cached once to `data/raw/fundamentals/`. Every member is present for a recorded
reason, along the axes that had already produced failures: filing era, fiscal calendar shape,
business model, share class structure, index status, and specific known pathologies.

The panel is deliberately selected to be difficult, so its pass rates measure whether an
implementation handles the shapes known to exist. They are not an estimate of how often each
shape occurs, which is what a full-scale run against the real universe measures. The two are
kept as separate measurements.

Ticker to CIK resolution goes through `ticker_history` rather than hardcoded values, since the
universe module is the project's source of truth for that mapping. The lookup returns every
matching CIK rather than one, so that ambiguity is visible. One panel member required an
explicit override: `GOOGL` resolves to both 1288776 (Google Inc) and 1652044 (Alphabet Inc),
the administrative reorganization already documented under `universe_construction.md`'s open
items, and 1652044 is the entity every earlier finding in this log was established against.

Constructing the panel surfaced a failure mode not previously considered. `CCU-200807` resolves
to CIK 888746, whose `companyfacts` filing history begins 2018-04-27, a decade after the
membership span the universe assigns it (1997-09-02 to 2008-01-30). The entity is United
Breweries Co Inc, a Chilean brewer trading under the `CCU` symbol on the NYSE today, so the
universe has matched a 1997 ticker string to its present holder. What matters for this loader is
what that entity's facts contain: it files form 20-F as a foreign private issuer, under the
`ifrs-full` taxonomy rather than `us-gaap`, in Chilean pesos and inflation-indexed units rather
than USD. It has 0 `us-gaap` tags. Every entry in `TAG_ALIASES` names `us-gaap` or `dei`, and
`concept_value_as_of` is only ever called with `unit="USD"` or `unit="shares"`, so such a filer
returns `None` for every concept while `build_fundamentals` records `fetched: True` because the
request succeeded. Index membership is restricted to US companies, so IFRS filers arrive only
through ticker misattribution, which makes the frequency of this a function of the universe
module's open items rather than of anything here. Recorded as a new open item.

### The question

`concept_value_as_of` selects candidate facts on `p["end"] == period_end` alone. An end date
identifies a balance sheet fact completely, since such a fact describes an instant, but an
income statement or cash flow fact describes a span and several spans share an end date.
Alphabet's `NetIncomeLoss` at `end = 2021-06-30` carries a 90 day figure of $18,525,000,000 and
a 180 day figure of $36,455,000,000, both filed 2021-07-28. Decision A is which property of a
fact identifies its period type.

### Elimination of `fp` and `form`

Both fields describe the filing a fact appeared in rather than the fact itself. Costco's fact
for the period 2019-02-18 to 2019-05-12, one start, one end, one value, appears with `fp` values
of Q3, Q4, and FY, because it was re-reported as a prior period comparative in later filings.
Invitation Homes' 30 day January 2017 period appears with `fp` values of Q1, Q2, and Q3. `form`
fails for the same reason and carries an additional problem: a 10-Q contains quarterly, year to
date, and prior year annual facts together, and a restated figure sometimes appears only as a
comparative inside a later 10-Q, so filtering on form would discard legitimate facts.

That leaves duration, computed as `end - start`, and the remainder of this part concerns how to
use it.

### The empirical duration distribution

Across four concepts and the panel, 10,216 facts distribute into five groups separated by gaps:

| Group | Durations observed | Facts |
|---|---|---|
| Instant, no `start` key | not applicable | 2,064 |
| Quarterly | 83 to 97 | 3,804 |
| Half year | 167 to 188 | 1,190 |
| Nine month | 241 to 279 | 1,168 |
| Annual | 363 to 370 | 1,937 |
| Unclustered | 30, 58, 111, 118, 149, 333 | 53 |

Two structural notes. Instant facts require no tolerance at all: the absence of a `start` key is
an exact signal, and every balance sheet fact fell into that bucket and nothing else did.
Separately, `end - start` yields one less than the inclusive day count, so a 52 week year appears
as 363, a calendar year as 364, a leap calendar year as 365, and a 53 week year as 370. A band
drawn from an assumption of "365 give or take a few" would sit wrong against all four.

### What the unclustered durations are

Nearly all of them come from three panel members, and each has a specific explanation that
generalizes beyond the individual company.

**Costco divides its fiscal year into 12, 12, 12, and 16 weeks rather than four equal quarters.**
Fiscal 2021 ran Q1 from 2020-08-31 to 2020-11-22 (83 days), Q2 and Q3 likewise at 83 days, and
Q4 from 2021-05-10 to 2021-08-29 (111 days). Its year to date figures fall at 167, 251, and 363
days. The 118 day facts are the same fourth quarter at 17 weeks in a 53 week year.

**Apple's 53 week fiscal years open with a 14 week quarter.** Fiscal 2012, 2017, and 2023 each
begin with a 97 day first quarter, giving year to date figures of 188 and 279 days instead of the
usual 180 and 272. Apple's annual durations are only ever 363 and 370.

**Invitation Homes reports a predecessor and a successor entity either side of a 2017
reorganization.** It publishes January 2017 alone (30 days), a successor series beginning
2017-02-01 (58, 149, 241, and 333 days), and a combined calendar year 2017 (364 days). Two
reporting bases, both legitimate, overlapping in time.

Taken together these establish that a quarter is 83 days at Costco, 89 to 91 at a calendar year
filer, 97 at Apple in a 53 week year, and 111 or 118 at Costco's fourth quarter, a spread of 35
days for one period type across two companies.

### Three candidate rules and the arbiter

Three implementations were written and compared rather than one being chosen by argument.

1. **Absolute duration bands.** Boundaries placed in the empty space between the observed
   clusters.
2. **Fiscal anchor.** Derive each filer's fiscal year start dates from its annual facts, then
   classify a fact as year to date if it begins on one of those dates, on the reasoning that a
   year to date figure always begins at the fiscal year boundary and a quarterly figure does not.
3. **Ratio to the filer's own annual duration.** Classify by the fraction of that filer's own
   year that a period covers, on the reasoning that what varies between filers is the length of
   the year rather than the proportions within it.

The arbiter was fixed before any of them was run, and is not the number of facts each labels. An
implementation can always label more facts by labeling them wrongly, and the defect being fixed
is one where a wrong number is returned confidently. The arbiter is instead whether a company,
end date, and period type together identify exactly one fact. If two facts answer the same
question, the caller has gained nothing.

| Candidate | Colliding groups | Of which the values differ |
|---|---|---|
| Absolute duration bands | 14 | 2 |
| Fiscal anchor | 25 | 20 |
| Ratio to own annual duration | 16 | 4 |

The distinction in the second column emerged from inspecting the collisions and is essential.
Most collisions consist of two facts carrying identical values under start dates a few days
apart, which is one fact recorded twice rather than a question the caller must answer.

The fiscal anchor is rejected. Twenty of its twenty-five collisions are genuine disagreements,
because it treats `start` as an identity key and filers do not tag start dates consistently:
Fifth Third records its fiscal year start as 2008-12-31 in one filing and 2009-01-01 in another
for the same year. That inconsistency also explains why it collided at Apple, Alphabet, Chipotle,
and Fastenal, where the other two candidates saw nothing.

Absolute bands appearing better than ratios at 2 against 4 is an artifact of boundary placement
rather than a property of the approach. Both additional collisions are Invitation Homes periods
that the band rule leaves unlabeled only because its 149 day figure falls one day below a
`half_year` floor of 150 and its 333 day figure falls seven days below an `annual` floor of 340.
Boundaries of 145 and 330 would have produced 4 as well. Ratios were adopted because they
recognize the same period type across a 35 day absolute spread, which is the property the
Costco and Apple calendars demonstrate is needed.

### Two causes of collision, requiring two separate mechanisms

Inspecting the colliding facts showed two distinct situations that cannot be handled by one rule.

The first is one reporting period whose start date was tagged inconsistently between filings.
Costco's third quarter of fiscal 2009 appears with starts of 2009-02-08 and 2009-02-16, both
valued at $210,000,000. Fifth Third, Coca-Cola, and MeadWestvaco all do the same at smaller
offsets.

The second is two genuinely different periods sharing an end date, which in this panel means
Invitation Homes' predecessor and successor bases, where the values differ substantially.

Coca-Cola supplies the case that shows the two must be separated rather than merged. All four of
its `NetIncomeLoss` facts ending 2011-07-01:

| start | days | value | filed |
|---|---|---|---|
| 2011-01-01 | 181 | 4,697,000,000 | 2011-08-01 |
| 2011-01-01 | 181 | 4,703,000,000 | 2012-07-26 |
| 2011-04-02 | 90 | 2,797,000,000 | 2011-08-01 |
| 2011-04-03 | 89 | 2,800,000,000 | 2012-07-26 |

Both figures were revised in the 2012 filing. The half year figure kept its start date, so the
existing point in time rule resolves it correctly as a restatement. The quarterly figure had its
start shifted by one day in the same filing, so the two vintages appear to be different periods,
the filing dates are never compared, and the loader returns the superseded $2,797,000,000
indefinitely. That pair must be merged and settled by filing date. Invitation Homes' pairs must
not be merged. The only property separating them is the distance between their start dates.

### Measuring the tolerance rather than choosing it

The distance between competing start dates was measured across three flow concepts and the whole
panel, grouped by company, concept, end date, and period label:

| Gap between consecutive starts | Pairs | Values identical | Values differ |
|---|---|---|---|
| 1 to 8 days | 19 | 18 | 1 |
| 31 days | 3 | 0 | 3 |

Nothing occurs between 9 and 30 days. The single small-gap pair with differing values is the
Coca-Cola restatement above, which is the case the mechanism exists to rescue rather than a
counterexample. Because the empty range spans 22 days, any tolerance within it produces identical
behavior, so the parameter does not require tuning. 15 days was adopted as a value near the
middle of that range.

### The rule adopted

1. Determine the filer's annual duration as the most common duration among its facts lasting 340
   to 380 days. This is the only absolute band in the rule, and it is the boundary with the widest
   clear space on either side.
2. Classify each fact. A fact with no `start` key is an instant, identified structurally. A fact
   with a `start` is classified by the ratio of its duration to the filer's annual duration, using
   0.18 to 0.35 for quarterly, 0.40 to 0.55 for half year, 0.60 to 0.80 for nine month, and 0.90
   to 1.05 for annual.
3. When more than one fact matches an end date and period type, group them by start date,
   treating starts within 15 days of each other as the same period. If more than one group
   remains, keep the group whose ratio is closest to the canonical value for its label (0.25, 0.5,
   0.75, 1.0).
4. Within the surviving group, apply the existing point in time rule unchanged: discard anything
   filed after the query date, then take the latest filed.

The ordering of steps 3 and 4 is load bearing. Reversed, Coca-Cola's superseded $2,797,000,000
would be selected, because the older vintage has the ratio closer to 0.25.

### Verification

Coca-Cola's second quarter of 2011, queried as of 2013-01-01, returns $2,800,000,000, the revised
figure. Invitation Homes' fiscal 2017, queried as of 2019-01-01, returns -$105,337,000, the
combined calendar year rather than the successor's -$88,458,000. Both answers are unchanged at
tolerances of 9, 15, 22, and 30 days, confirming the parameter is not tuned.

Swept across the panel, three concepts, and every end date, with the query date set to 2026-01-01
so that every filed vintage is simultaneously visible, which maximizes the number of competing
facts, the ratio tie-break in step 3 fires exactly three times. All three are Invitation Homes
net income at the 2017 half year, nine month, and annual ends, and all three select the
2017-01-01 basis. No other company in the panel requires the tie-break under any concept.

## Part 15: validating Decision A at wider scale, and writing it into `src`

Dated 2026-08-04. Part 14 settled the rule against 18 deliberately difficult companies. This
part tests whether it survives companies chosen at random, and records the implementation.

### A 100 company random sample

100 CIKs were drawn from `universe_spans`, 50 that have left the index and 50 current, excluding
panel members. 99 returned `companyfacts`; the one 404 is a company that delisted before the 2009
XBRL mandate, which is the expected result rather than a failure. Every duration concept in
`TAG_ALIASES` was classified, including `cost_of_revenue` and `gross_profit`, which the panel work
had not covered.

| Outcome | Count |
|---|---|
| Distinct periods classified | 30,886 across 98 companies |
| Labeled quarterly | 14,633 |
| Labeled annual | 5,598 |
| Labeled half year | 5,305 |
| Labeled nine month | 5,104 |
| Measured against a year length and fitting no band | 29 (0.09%) |
| No annual figure available for the concept, so unmeasurable | 217 |

The 29 unbanded facts matter more than their count. Every one has a ratio between 0.00 and 0.16,
meaning periods of a few days to about two months. Nothing sits at 0.37, at 0.58, or at 0.85. The
empty space between the four bands, which in Part 14 could have been an accident of an 18 company
sample, remains empty across 100 randomly drawn companies and five concepts. The residue is a
single recognizable category of short stub periods around corporate events, for which returning
`None` is correct: a three week period is not a quarterly figure and should not be offered as one.

### The fiscal year length is measured across concepts, not within one

The 217 unmeasurable periods fall in 9 company and concept pairs, and expose a defect in the
per-concept measurement Part 14 used. Boston Scientific tags net income only for 90, 91, 180, and
272 day periods and never for a full year, reporting the fourth quarter and leaving the annual
figure to be summed. Measuring the fiscal year from net income alone therefore finds no seed, and
every net income fact for that company becomes unclassifiable, which would silently remove it from
the value, profitability, profit growth, and PEAD signals at once.

Three scopes were compared for all 9 failing pairs:

| Scope | Result | Cost on the largest cached file (JPMorgan, 8.6 MB) |
|---|---|---|
| The queried concept alone | `None` for all 9 | negligible |
| The five duration concepts in `TAG_ALIASES` | resolves all 9, agreeing with the exhaustive scan in every case | 0.2 ms |
| Every tag in the document | resolves all 9 | 12 ms |

For reference, parsing the JSON that all three then read costs 45 ms. The bounded scan is
therefore about half a percent of work already being done, which removes both the argument for
restricting it to one concept and the argument for caching the result. `annual_duration` was
changed to take the whole facts document and measure across the duration concepts.

### Making the measurement deterministic

`ETS-200603` resolves to Elite Express Holding Inc., which has exactly two annual periods,
2023-12-01 to 2024-10-25 at 329 days and 2024-12-01 to 2025-11-30 at 364 days, a company that
moved its fiscal year end. With one instance of each length the mode is tied, and
`Counter.most_common` breaks the tie by insertion order, which follows the order facts appear in
the vendor's response. With 364 chosen, the 329 day period has a ratio of 0.904 and classifies as
annual; with 329 chosen, the 364 day period has a ratio of 1.107 and classifies as `None`. A
result that depends on document ordering is not replayable in the sense the README requires, so
ties are now broken toward the longer duration, which treats the settled year rather than the
transition year as the filer's norm.

This was the only fiscal year change found in 100 companies, and the company is itself a universe
misattribution rather than a genuine index member, so the category remains thinly tested.

### A second filer under a non-`us-gaap` taxonomy

`GRN-199812` resolves to Barclays Bank PLC, which reports 370 tags under `ifrs-full` and none
under `us-gaap`. This is the same situation as CIK 888746 in Part 14, reached the same way through
a ticker misattribution, and confirms it as a category rather than a single case. Two instances in
roughly 117 companies examined. Both are recorded under Open items.

### Implementation

`concept_value_as_of` and `gross_profit_as_of` now take a `period` argument naming which kind of
period is wanted. It is required for a concept whose facts describe a span and rejected for one
describing an instant, which `CONCEPT_KIND` records. Making it required rather than defaulting to
`"annual"` is deliberate: silently choosing a period is the defect being fixed, so a caller who
does not say what they want receives a `ValueError` listing the options rather than a plausible
looking number. `total_liabilities_as_of` is unchanged, since all three of its concepts are
instants.

Verified against real cached data rather than fixtures alone. Alphabet's second quarter of 2021
now returns $18,525,000,000 where it previously returned the half year figure of $36,455,000,000;
Costco's 83 day second quarter of fiscal 2020 returns $931,000,000 where it previously returned
the 167 day figure of $1,775,000,000. The point in time behavior was checked separately and is
intact: Apple's fiscal 2008 net income still returns $4,834,000,000 as of December 2009 and
$6,119,000,000 as of June 2010, and Coca-Cola's second quarter of 2011 returns the pre-revision
$2,797,000,000 when queried as of September 2011 and the revised $2,800,000,000 when queried as of
2013. `tests/test_fundamentals.py` grew from 12 to 28 tests, each fixture mirroring a named real
filer's shape rather than an invented one.

### Verification by accounting identity

The strongest available check does not depend on how the classifier works: within a fiscal year,
consecutive year to date figures must differ by exactly the reported quarterly figure. Applied
across the panel, 523 of 547 checks balance exactly, or 95.6 percent. The 24 exceptions were
examined individually and none is a classification error, which would be wrong by a whole quarter.
Two causes account for all of them.

**Presentation rounding.** All 96 of Meta's net income values are exact multiples of one million,
because it presents its statements in millions. Its first quarter of 2017 was 3,064 million and
its half year 6,959 million, implying a second quarter of 3,895 million against a reported 3,894
million. Three independently rounded figures need not satisfy an exact identity. All the facts
involved carry the same accession numbers, so no revision is implicated. This is a property of the
source that no loader can remove.

**Vintages that were not revised together.** Fastenal's fiscal 2015 annual net income was
516,361,000 in the filings of February 2016 and February 2017 and 516,400,000 in February 2018,
while its nine month figure was never revised after October 2016. Resolving each figure to its own
latest vintage therefore combines a revised annual with an unrevised nine month, and the two are
not internally consistent. The loader is behaving correctly; the filer simply did not revise them
together.

Both causes are sub-percent in magnitude and are worth knowing about before any factor computes a
quarter over quarter change, since such a factor inherits them. Neither is actionable in the
loader.

## Part 16: Decision C, how shares outstanding is queried

Dated 2026-08-04.

### The question

Every other instant concept is queried by naming a period end, which works because a balance
sheet fact's `end` is the fiscal period end, the date a caller already holds. Part 13 found that
`dei:EntityCommonStockSharesOutstanding` does not behave that way: it records how many shares
existed when the filing was prepared, so its `end` is a cover page date some weeks later. The
question was therefore not which tag to prefer but whether a period end belongs in the query at
all.

### Measurement

For each panel member, its most recent fiscal year end was taken from its own annual facts and a
share count requested at that date, as of one year later so that the annual report had certainly
been filed. An earlier version of this measurement queried as of a fixed date one day after the
year end, which for the twelve calendar year filers measured filing lag rather than the
interface; the corrected figures are below. The lesson generalizes: any measurement of a point in
time interface has to choose a query date relative to each filer's own calendar, not a fixed one.

| Outcome | Count | Companies |
|---|---|---|
| Resolves | 12 | AAPL, COST, GOOGL, MWV, JPM, FITB, ACGL, INVH, KKR, CEG, KSU, FAST |
| Cover page tag only, unreachable by period matching | 3 | KO, CMG, MCK |
| No undimensioned share count in either tag | 2 | META, DASH |
| Not a `us-gaap` filer, so no fiscal year could be derived | 1 | CCU-200807 |

All twelve resolutions came through `us-gaap:CommonStockSharesOutstanding`. None came through the
cover page tag, despite fifteen companies carrying it, several with seventy or more facts.

The offsets explain why, and rule out the obvious alternative fix. `gaap_offset`, the distance
from the fiscal year end to the nearest fact under that tag, is 0 in every one of the twelve
cases. `dei_offset` is never 0: it runs from 20 days (Apple) through 30 (Costco), 49
(Coca-Cola), to 54 (Arch Capital). The cover page date is not an imprecise version of the period
end but a systematically later date meaning something else, so no tolerance recovers it. A
tolerance wide enough for 54 days is most of a quarter and would begin matching adjacent periods.

Coca-Cola, Chipotle, and McKesson carry 71, 65, and 68 share count facts respectively, and the
loader could return none of them.

### Whether the two tags can be pooled

Pooling and taking the freshest is only safe if both tags count the same thing. A filer whose
cover page reported one share class while its balance sheet reported the combined total would be
silently mixed, and market capitalization would jump between rebalance dates according to which
tag happened to be fresher. Checked on the 11 panel members carrying both, comparing the closest
dated pair from each:

| Days between the two dates | Ratio range |
|---|---|
| 0 (AAPL, FITB, CEG) | 0.9991 to 1.0001 |
| 8 to 19 (FAST, KSU, INVH, COST, MWV) | 0.9993 to 1.0003 |
| 31 to 47 (JPM, ACGL, KKR) | 1.0000 to 1.0079 |

Nothing approaches 0.5 or 2. The deviations scale with the gap between the dates, which is what
ordinary issuance and buyback activity produces, and the largest, JPMorgan at 0.79 percent over
31 days, is drift rather than a difference in scope. Costco's and Constellation's slight
shortfalls come from the `us-gaap` figure being rounded to the nearest thousand.

### The rule adopted

`shares_outstanding_as_of(facts, as_of_date)` takes no period end. It discards facts filed after
the query date, pools both tags, takes the fact with the latest `end`, and breaks ties on `end`
by the latest `filed` so that an amendment supersedes what it amends. `shares_outstanding` was
removed from `TAG_ALIASES` and `CONCEPT_KIND`, and `concept_value_as_of` now raises a directive
`ValueError` if asked for it, so that the silent failure this part measured cannot recur.

### Verification

Against the real cached files as of 2026-08-01, the three previously unreachable filers now
resolve: Coca-Cola at 4,302,482,418, Chipotle at 1,265,418,000, and McKesson at 120,204,051.
Apple, Costco, JPMorgan, and Fastenal resolve through the cover page tag, which is fresher than
their balance sheet figure; Alphabet resolves through `CommonStockSharesOutstanding`, being the
only panel member without a cover page tag. Meta and DoorDash remain `None`, which no interface
change can alter since neither tag exists for them.

One unplanned finding: `CCU-200807` resolves, at 369,502,872 from a form 20-F. The `dei`
taxonomy is form-agnostic, so cover page facts exist even for filers whose financial statements
are entirely outside `us-gaap`. The taxonomy gap recorded in Part 14 therefore affects the
financial concepts but not the share count.

Six tests added, taking `tests/test_fundamentals.py` to 34.

## Part 17: Decision D, the share count for multi-class filers

Dated 2026-08-04.

### The scope of the gap, and a defect found while measuring it

Part 16 left Meta and DoorDash without a share count. Measured across all 117 cached companies,
querying each at its own last filing date so that departed names are not counted as failures for
having left the index, 11 have no usable count. Every one has either multiple share classes or a
partnership unit structure, which is the population whose facts carry a `ClassOfStock` dimension
and are therefore dropped by the bulk `companyfacts` endpoint. That is 9.4 percent, concentrated
in dual class governance rather than scattered at random.

Four of the 11 were worse than missing. Mastercard, A. O. Smith, Datadog, and Robinhood reported
an undimensioned count for part of their history and then switched to per-class tagging, so
`companyfacts` retains the older facts and nothing after. `shares_outstanding_as_of` faithfully
returned the freshest fact available, which for Mastercard meant 122,530,193 from 2010 against an
actual count near 905,000,000, an understatement of market capitalization by roughly sevenfold,
silently. Datadog and Robinhood returned zero.

Fixed by bounding staleness: a count dated more than `MAX_SHARE_COUNT_AGE_DAYS` (400) before the
query date is treated as unavailable rather than returned, since a filer that stopped tagging is
indistinguishable from the value alone from one whose latest figure is merely old. Non-positive
counts are discarded for the same reason. The function now also returns the fact's `end`, so a
caller can see how current the figure is; the earlier signature omitted it, which was the reason
this went unnoticed.

### The exact route was investigated and covers less

The SEC's Financial Statement Data Sets publish quarterly archives of the same filing data as
flat files, and unlike the API they retain dimensions. Meta's fiscal 2025 rows confirm the
mechanism: `ClassOfStock=CommonClassA` at 2,187,000,000, `ClassOfStock=CommonClassB` at
343,000,000, and `EquityComponents=CommonStock` at 2,530,000,000, the last being exactly the sum
of the first two. The archives run from 2009q1 and are immutable once published, so a build would
be genuinely incremental: 68 archives once, then one per quarter.

Three findings against it, all from inspecting the 2026q1 archive directly.

**It does not carry the cover page tag.** `dei:EntityCommonStockSharesOutstanding` appears 12
times in a file of several hundred thousand rows. The data sets hold financial statement facts,
not cover page facts, so only `us-gaap:CommonStockSharesOutstanding` is reachable.

**Three of the 11 have no such tag at all.** The New York Times reports `CommonStockSharesIssued`
per class (178,951,695 Class A and 780,724 Class B) and never the outstanding figure; issued is
not outstanding, and the Times holds enough treasury stock that the gap is about 10 percent. A. O.
Smith is the same shape with a 35 percent gap. Sunoco is a limited partnership reporting
`LimitedPartnersCapitalAccountUnitsOutstanding` across three unit classes in an entirely separate
vocabulary. Recovering these would require subtracting treasury shares and handling partnership
units, both further normalization layers.

**Combining the class rows is not a lookup.** Meta, DoorDash, Datadog, and Robinhood carry an
`EquityComponents=CommonStock` row equal to the sum of their classes. Ralph Lauren carries one at
135,400,000 while its classes sum to 60,600,000, because for that filer the row is issued shares
appearing in the equity rollforward under the same element name. A rule trusting the total row
would have been 123 percent too high for the first filer checked closely. Doing it correctly
means summing class members while excluding non-common ones such as American Homes 4 Rent's
`ClassACommonUnits`, which is a maintained list rather than a fact.

Net: the exact route recovers 8 of 11 at perhaps fifty times the cost of the approximation, which
recovers 10.

### The approximation, and why the quarterly figure matters

`us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` is undimensioned for almost every filer,
because earnings per share requires it. It answers a different question: the count averaged across
a reporting period weighted by how long each share was outstanding, which is the correct
denominator for earnings per share and the wrong one for market capitalization.

The objection to using it was that its error should correlate with share repurchase, since an
average over a period exceeds the current count precisely when the count has been falling, and
repurchase intensity correlates with the profitability and value characteristics these factors
measure. A lagged share count would therefore penalize exactly the companies those factors favor.

Measured against a true point in time count on 5,271 observations where both were available:

| Source | Median error | Median absolute | 5th to 95th | Within 5% |
|---|---|---|---|---|
| Annual weighted average | +0.37% | 1.74% | -9.88% to +8.09% | 78% |
| Quarterly weighted average | +0.00% | 0.43% | -2.71% to +3.10% | 95% |

The quarterly figure is closer in 83 percent of cases. The annual figure's positive median is the
predicted skew; the quarterly figure's median of zero is it disappearing. The lag falls from
roughly ten months to roughly three, which removes the systematic component rather than merely
shrinking it. The objection was therefore an artifact of choosing the wrong period rather than a
property of the weighted average.

### The rule adopted

`shares_outstanding_as_of` falls back to the weighted average only when no genuine count resolves,
never pooling the two, preferring the quarterly figure over the annual one, and subject to the
same staleness bound. The returned tag names the source, so a caller and the coverage report can
both see which companies rely on it, and `allow_weighted_average=False` excludes them outright,
which is what a sensitivity check on the approximation needs.

### Cross-validation between two independent sources

The fallback's output was checked against the per-class sums pulled from the Financial Statement
Data Sets, which share no code path and no endpoint with it:

| Company | Weighted average fallback | Per-class sum from the archives |
|---|---|---|
| Meta | 2,534,000,000 | 2,530,000,000 |
| Ralph Lauren | 61,100,000 | 60,600,000 |
| Universal Health Services | 61,071,000 | 61,063,000 |
| DoorDash | 435,429,000 | 434,247,000 |
| Datadog | 353,272,000 | 352,526,000 |
| Robinhood | 899,000,000 | 901,328,000 |

Agreement within one to two percent throughout, with the residual explained by the two figures
being dated up to six months apart. The fallback also avoids the Ralph Lauren trap by
construction, since it never reads the equity rollforward row.

Ten of the 11 filers are recovered. Sunoco remains `None`, which is correct rather than a gap: a
limited partnership has units rather than shares, and a common share count is not a well defined
quantity for it. Five tests added, taking `tests/test_fundamentals.py` to 39.

## Considerations to settle before the fixes

Each of these is a decision rather than a defect, and each changes the loader's interface, so
they are recorded before implementation rather than discovered during it.

**How a period type is identified. Settled, see Part 14.** `fp` and `form` were eliminated on
evidence: both label the filing a fact appeared in rather than the fact, and the same Costco fact
appears under three different `fp` values. Absolute duration bands were rejected in favor of the
ratio of a period's duration to the filer's own annual duration, since a quarter runs from 83 to
118 days across the panel. Two further mechanisms handle competing facts: start dates within 15
days are treated as one period tagged inconsistently, and genuinely distinct periods sharing an
end date are settled by proximity to the canonical ratio before the filing date rule applies.

**Where fiscal calendar knowledge lives.** A factor asks "the most recent known annual net
income for these 500 CIKs on this rebalance date". Nothing currently enumerates a filer's
periods, so the caller must already know each fiscal period end, which no factor code can
supply. Either the loader gains a period discovery function or every factor reimplements one.
The loader is the correct home, since this is a question about filings rather than about
factors.

**Whether shares outstanding leaves the period-matched interface. Settled, see Part 16.** It
does. `shares_outstanding_as_of(facts, as_of_date)` takes no period end, pools both tags, and
takes the freshest count filed by the query date. The cover page tag is dated 20 to 54 days
after the period end and never coincides with it, so period matching reached only the optional
`us-gaap` tag and returned nothing for the filers that omit it.

**Whether a period average share count is an acceptable fallback. Settled, see Part 17.** It is,
provided the quarterly figure is used rather than the annual one, which reduces the median
absolute error from 1.74 to 0.43 percent and removes the repurchase-related skew entirely. The
exact alternative, the SEC's Financial Statement Data Sets, was investigated and covers 8 of the
11 affected filers against the approximation's 10, at far greater cost. The fallback is a last
resort, never pooled with genuine counts, and is identifiable by its returned tag.

The two considerations below were subsequently reclassified as factor definition questions rather
than loader questions, and are deferred to the `src/factors/` build step. Both concern how a
theme is defined when a concept does not apply to a filer, not how a filing is read.

**What the profitability theme falls back to when no gross profit path exists.** Return on
equity, computed from net income and stockholders' equity, requires no new data and resolves for
essentially all of the 15 affected companies. Whether the theme should use a single
characteristic with a fallback, or should be defined as a composite that drops unavailable terms
and renormalizes (the missing data rule the README already states for `scoring/combine.py`), is
the more consequential form of the question.

**Whether bank and insurer revenue is worth aliasing at all.** `RevenuesNetOfInterestExpense`
and the interest income concepts would recover a revenue figure for financial sector filers, but
that figure is not economically comparable to an industrial company's revenue, so a
cross sectional sales-to-price ranking mixing the two would be measuring sector membership as
much as valuation. Sector-neutral scoring, which is gated on re-attaching GICS to the universe
tables, is arguably the real answer.

## Open items

- The three defects in Part 13 are unfixed in `src/`. The rule that corrects the first of them
  is settled and verified in `notebooks/validating_fundamentals.ipynb` (Part 14), but
  `concept_value_as_of` has not yet been changed, so it still returns a year to date figure in
  place of a quarterly one at any non-year-end period.
- A filer using a taxonomy other than `us-gaap` returns `None` for every concept while
  `build_fundamentals` records `fetched: True`, since the request itself succeeded. Found via
  CIK 888746, a 20-F filer reporting under `ifrs-full` in Chilean pesos, reached through a
  universe ticker misattribution (Part 14). Such filers should not appear in a correct S&P 500
  universe, so the frequency depends on the universe module's open items, but the coverage
  report currently cannot distinguish "fetched and usable" from "fetched and empty".
- `SalesRevenueNet` is not yet in `TAG_ALIASES`, so pre-2018 revenue is unresolvable for filers
  that used it.
- The shares outstanding gap has widened rather than closed. DoorDash was the original case;
  Meta reproduces it, and Part 12 establishes it as dimensional dropping affecting multi-class
  filers generally rather than a one-filer anomaly. Recovering it requires either a source that
  preserves dimensions (a per-concept endpoint, or the filing's own XBRL instance rather than
  the bulk `companyfacts` aggregation), or the weighted average approximation discussed under
  Considerations, or documenting the affected companies as a bounded gap.
- The dual and multi-class market cap approximation from Part 8 (one class's price times the
  combined share count across all classes) has not been checked for how large an error it
  introduces when classes trade at meaningfully different prices. Alphabet's `GOOG` and `GOOGL`
  are close enough historically that this likely does not matter for Alphabet specifically, but
  this has not been verified and no other multi-class filer has been checked.
- `price_as_of` and `split_adjustment_factor` exist only in this notebook, not in any promoted
  module. They belong in `src/factors/value.py` once that build-order step is reached, per Part
  11; until then, no `src/` code can compute market capitalization or a price scaled ratio.
- DoorDash's cached price coverage being scoped to its actual S&P 500 membership span, not its
  full trading history, is correct, existing price-loader behavior, not a fundamentals-loader
  problem, but it means any fundamentals-to-price join for a given CIK is implicitly bounded to
  that CIK's membership window. Stated explicitly in `src/loaders/README.md` now.
- `build_fundamentals()` has still never been run. `data/raw/fundamentals/` is empty, and
  `data/processed/fundamentals_coverage.parquet` does not exist. Separately, and relevant to
  verifying any price join, `build_prices()` has not completed either: `data/raw/prices/` holds
  33 CIK files and `data/processed/prices_coverage.parquet` does not exist, though both this
  file and `src/loaders/README.md` describe the coverage report as an existing artifact.
- Coverage at scale remains unmeasured, and when it is measured it should be measured by dated
  resolution rather than by tag existence, per Part 13. The alias mechanism has now been checked
  against four hand-picked companies, a 30 company single-date sample, and a 60 company multi
  era sample, against a full historical universe of roughly 500 to 1,000 members.
- `src/loaders/README.md` and the project `README.md` both report the Part 9 coverage figures
  without the existence-versus-resolution qualifier, and both describe the loader in terms that
  Part 13 narrows. Neither has been corrected.
