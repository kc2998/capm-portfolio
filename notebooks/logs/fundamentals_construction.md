# Fundamentals loader construction: findings log

Record of what was learned while exploring the EDGAR fundamentals loader in
`notebooks/exploring_fundamentals.ipynb`. Started 2026-07-31.

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

## Open items

- DoorDash's shares outstanding gap remains unresolved. Whether it can be recovered at all from
  this filer's per-class dimensional facts (would require a different API, such as a
  per-concept endpoint that preserves dimensions, or parsing the filing's own financial
  statement exhibit, rather than the bulk `companyfacts` endpoint), or should instead be
  documented as a bounded, known gap, is not yet decided.
- The dual/multi-class market cap approximation from Part 8 (one class's price times the
  combined share count across all classes) has not been checked against how large an error it
  introduces when share classes trade at meaningfully different prices. Alphabet's GOOG and
  GOOGL are close enough historically that this likely does not matter much for Alphabet
  specifically, but this has not been verified, and no other multi-class filer has been checked.
- `price_as_of` and `split_adjustment_factor` exist only in this notebook, not in any promoted
  module. They belong in `src/factors/value.py` once that build-order step is reached, per Part
  11; until then, no `src/` code can compute market capitalization or a price scaled ratio.
- DoorDash's cached price coverage being scoped to its actual S&P 500 membership span, not its
  full trading history, is correct, existing price-loader behavior, not a fundamentals-loader
  problem, but it means any fundamentals-to-price join for a given CIK is implicitly bounded to
  that CIK's membership window. Stated explicitly in `src/loaders/README.md` now.
- The alias mechanism has now been checked against four hand-picked companies plus a 30
  company random sample of the 2020 S&P 500, not the full historical universe of roughly 500 to
  1,000 members across its full 1996-to-present span. `build_fundamentals()` running against
  the whole universe, once actually run, is the next real test of scale.
