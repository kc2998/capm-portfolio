# Backtest construction: findings log

Record of what was learned while building the walk forward loop, portfolio construction, and
evaluation metrics in `notebooks/exploring_backtest.ipynb`. Started 2026-08-13, last updated
2026-08-19.

This file exists so the reasoning behind the backtest loop survives outside the notebook. The
README states the decisions; this file states the evidence, organized to follow the notebook's
own part numbering. Real bugs found while building this, and one mistaken claim made and later
corrected in this very log, are recorded here rather than left as dead reasoning in the
notebook for someone to puzzle over later.

## The task

Per the top level `README.md`'s build order, step 6 is the point where information coefficient
first gets measured across the complete 13-theme factor suite, one comprehensive pass rather
than a piecemeal screen. That requires four things that didn't exist yet: an estimate of each
stock's market beta (needed by `scoring/neutralize.py`, which took betas as a given argument
rather than computing them), a walk forward loop that re-resolves the point in time universe
and recomputes every factor at each rebalance date, a portfolio construction rule to turn a
ranking into actual weights, and a way to measure whether any of it predicts anything.

## Part 1 and 2: setup and beta

`src/loaders/market.py` fetches and caches a market proxy (SPY) in the same cached shape as a
CIK price file, so `close_on_or_before` and later `next_open_after` work on it unmodified. Two
real bugs found immediately:

- `fetch_market_prices(ticker, start=None, end=None)` called `yf.Ticker(ticker).history(start=None, end=None)`, which is not the same as asking for full history: with both arguments `None`, `yfinance` silently falls back to its own default `period="1mo"`. The cached file held only the most recent month of data until this was found. Fixed by explicitly requesting `period="max"` when no start or end is given, the same convention `exploring_loaders.ipynb`'s own first cell used to originally probe `yfinance`'s raw shape.
- `save_market_prices` tagged the fetched frame with a `ticker` column via `prices.assign(ticker=ticker)` before writing to parquet, correctly. But `assign()` returns a copy rather than mutating in place, and `build_market` returned the caller's original, untagged `prices` variable on a fresh fetch, not what was actually written to disk. On a cache hit this was invisible, since the file on disk was always correctly tagged; it only surfaced on a cache miss, once the stale 1-month cache was deleted to test the first fix. Fixed by having `save_market_prices` return the tagged frame it wrote, the same convention `loaders/prices.py`'s own `save_cik_prices` already follows.

`src/risk_model/beta.py`'s `beta_as_of` (weekly returns, 104 week trailing window, refit fresh
at every `as_of`) was validated against a toy case (a market and stock series engineered so the
true beta is exactly 2.0, `market_returns` varied week to week deliberately since a constant
market return makes `var(market)` zero and the slope undefined) and real data: SPY regressed
against itself returns exactly 1.0, NVDA (volatile, cyclical) comes back at 1.94, PG and KO
(defensive staples) at 0.46 and 0.42. Across the full 60 company sample used throughout this
notebook, mean beta 0.99, std 0.38, 2 of 60 (`BX`, `LULU`) unresolved; see Open items.

## Part 3: wiring one date's full pipeline, and a 1000x share count

Wiring all sixteen factors, `scoring/zscore.py`, `scoring/combine.py`, and `scoring/neutralize.py`
together for one date surfaced `size_factor`'s log market cap ranging up to 30.4 for one company
in the sample, `e^30.4 ≈ $15.6 trillion`, larger than any real company has ever been worth.
Traced directly against the cached data (`src/loaders/fundamentals.py`'s `shares_outstanding_as_of`):
Packaging Corporation of America's 2024-05-08 10-Q reports `dei:EntityCommonStockSharesOutstanding`
as 89,797,979,000, while the same filing's own `us-gaap:CommonStockSharesIssued` reports
89,800,000 for the prior quarter, a factor of exactly 1000. This is a genuine filer error in the
raw SEC XBRL data, confirmed by reading the cached `companyfacts` JSON directly, not a parsing
bug: `dei:EntityCommonStockSharesOutstanding`'s own value really is what's in the source.

`SHARES_OUTSTANDING_TAGS` previously pooled only two tags (`dei:EntityCommonStockSharesOutstanding`,
`us-gaap:CommonStockSharesOutstanding`) and picked whichever had the latest `end` date, with no
cross-check, because normally the two tags agree to within 0.01 percent. PKG doesn't tag
`CommonStockSharesOutstanding` at all, only `CommonStockSharesIssued`, which wasn't pooled, so
there was nothing to catch the error against. Fixed two ways: `CommonStockSharesIssued` added
as a third pooled tag, and a new `_drop_uncorroborated_within_filing` helper that discards a
candidate if no other tag from the *same accession* agrees within a 5x ratio. Same-accession
only, deliberately: a plain cross-time ratio check would also flag a genuine stock split (a
real, legitimate jump in the raw filed share count between one filing and the next, the entire
reason `split_adjustment_ratio` exists) as an error. A single filing can never straddle a split,
so disagreement within one filing is unambiguous, while disagreement across filings is exactly
where a real split shows up and must be left alone. Verified after the fix: PKG's shares resolve
to 89,800,000 via `CommonStockSharesIssued`, market cap to $15.6 billion, `size_factor` to 23.47,
in line with the rest of the sample.

## Part 4: configs/factors.yaml

Rebalance cadence and factor weights moved into a single YAML file, matching the top level
`README.md`'s point that rebalance frequency is a configuration parameter, not a fixed decision.
`rebalance_freq: "ME"` (month end) is a representative starting point, most of the suite is
monthly or quarterly horizon; weekly and semi-monthly are to be compared empirically once a real
run exists. All sixteen weights are equal (1.0), deliberately not fit: weighting a factor by its
own measured performance before that performance has ever been measured would be circular, and
doing so from the same pass meant to measure IC would be the data snooping the factor-zoo
discipline section already warns against.

## Part 5: the walk forward loop, and a survivorship trap in the sample itself

The first version of the loop reused `sample_ciks`, the 60 company sample fixed once in Part 1
against `AS_OF`, across all seventeen test dates. This is exactly the survivorship bias the top
level `README.md` opens with, testing January 2023 with June 2024's constituent list, caught
before it was trusted by naming it explicitly rather than by a symptom. Fixed with `ciks_on`
(added to `src/universe/point_in_time.py`, the CIK-keyed sibling of the existing `membership_on`,
which returns tickers), resolving the actual point in time universe fresh at every date.

A second version drew a random 60 company subsample from each date's correct universe, for
speed, using one `random.seed(0)` call before the loop rather than reseeding at each date. This
produced turnover values of 3.6 to 4.0 between consecutive months, which was flagged as
impossible on the reasoning that total long and short weight are each capped at 1.0, so a
complete inversion of the book should cap turnover at 2.0. The real cause: two independent
random 60-company draws from a roughly 500-company universe overlap by only about 7 names on
average, so most of what looked like turnover was the sampling procedure swapping out unrelated
companies, not the strategy trading. Fixed by dropping the subsample and scoring the full point
in time universe (roughly 500 names) at every date instead, since the real S&P 500 only turns
over about 25 names a year and continuity should be the norm.

The "turnover cannot exceed 2.0" reasoning used to justify that diagnosis was itself checked
directly against the post-fix data and found to be wrong, worth recording since it was stated
confidently before being checked. Deriving turnover in terms of retention (`x` = count staying
long, `y` = count staying short, bucket size `n`, weight `w = 1/n`) gives
`turnover = 4 - 2(x + y) / n`, not a 2.0 ceiling: the true worst case is 4.0, when every position
exits and gets replaced by an entirely fresh name on both sides. A real post-fix date
(2024-02-29) landed on exactly 2.0 turnover, which was re-checked directly rather than assumed
alarming, and turned out to reflect ordinary reranking (49 of 92 longs stayed long, 43 of 92
shorts stayed short, only 10 and 7 flipped sides) where `x + y` happened to equal `n` exactly, a
numerical coincidence, not a flipped book. The original resampling diagnosis was still correct
independently of the wrong bound used to justify it: arbitrary resampling genuinely does inject
churn unrelated to the strategy.

## Part 6 and 7: quantile buckets and a basic transaction cost model

`quantile_weights` longs the top fifth of `factor_score`, shorts the bottom fifth, equal
weighted within each side; dollar neutral by construction since long and short weights each sum
to 1.0 in magnitude. `turnover` sums absolute weight change across the union of tickers in
either date (missing treated as 0, not netted to a one-way figure, since overstating cost is the
safer direction for a first pass), translated into cost via a flat `COST_BPS = 10` basis point
placeholder, per the top level `README.md`'s own framing that a crude estimate is sufficient at
this step.

## Part 8: forward returns and information coefficient, and a lookahead the execution price was hiding

`forward_return` originally used `close_on_or_before` for both the entry and exit price, the
same close `compute_row` had just used to compute the signal itself. This is precisely what the
top level `README.md`'s point in time discipline section already warns against: "computing a
signal from a closing price and trading at that same close is a subtle form of look ahead."
Caught during a deliberate pre-promotion review, not by a symptom in the numbers, since a close
to close return isn't obviously wrong to look at.

Fixed with a new point in time lookup, `next_open_after` (added to `src/loaders/prices.py`,
next to `close_on_or_before`): the next trading session's open strictly after a given date,
validated against a toy weekend-gap case (a Friday and the following Monday, confirming the
function returns Monday's open for a Friday query and correctly returns `None` when queried on
or after the series' own last date). `forward_return` now uses the open following the rebalance
date as entry and the open following the next rebalance date as exit. Re-running the full
sixteen-date IC series after the fix gave 0.0236 mean, 0.0778 std, close to the original close
to close numbers (0.0244, 0.0728) rather than wildly different, evidence the fix corrected a
subtle timing convention rather than exposing a larger bug.

A second concern, checked at the same time rather than assumed away: `portfolio_return`'s
`dropna()` silently drops any held position with no measurable forward return, which could
reintroduce survivorship bias at the return layer the same way the price loader's own coverage
report exists to prevent at the data layer (roughly 91 percent coverage for still active names
versus 49 percent for delisted ones, per `loaders_construction.md`). `missing_forward_return_positions`
measures rather than silently absorbs this: across all seventeen dates and roughly 92 held
positions per side, zero held positions lacked a forward return in this test window. Clean for
now, not a guarantee it stays clean across full history, more delistings are likely across 15
years than across 16 months; see Open items.

## Promotion

Everything above was promoted once validated, following the same notebook-first-then-`src/`
pattern as every other module in this project:

| Piece | Destination |
|---|---|
| `next_open_after` | `src/loaders/prices.py`, next to `close_on_or_before` |
| `ciks_on` | `src/universe/point_in_time.py`, next to `membership_on` |
| `compute_row`, `FACTOR_REGISTRY`, `run_rebalance`, `quantile_weights`, `forward_return`, `add_forward_returns`, `run_backtest` | `src/backtest/engine.py` |
| `turnover`, `missing_forward_return_positions`, `information_coefficient`, `portfolio_return`, `backtest_returns`, `max_drawdown` | `src/backtest/metrics.py` |

`compute_row` was rebuilt around a registry rather than promoted as the original sixteen
hardcoded dictionary keys, a deliberate design choice made during promotion, not forced by a
bug: three small adapters (`_facts_only`, `_prices_only`, `_facts_and_prices`) capture the three
argument shapes the sixteen factor functions actually use, so `FACTOR_REGISTRY` becomes a flat,
one-line-per-factor table and a future seventeenth factor needs one new registry line, not an
edit to `compute_row` itself. `beta` stays outside the registry deliberately: it needs
`market_prices`, an external series none of the other factors touch, so forcing it into the
same four-argument shape would fit it to a mold it doesn't belong in.

Verified, not assumed, that reorganizing the code didn't change what it computes: `compute_row`
promoted first and checked alone against the exact same 60 company sample, every value in
`raw.describe()` matched the notebook's original output exactly (size mean 24.426017, quality
mean -0.007914, leverage mean 12.275442, beta mean 0.990973, and every other column). After the
rest of the promotion, the full stack was re-run across the same seventeen test dates and
compared against the notebook's own recorded output: the complete sixteen-value IC series, mean
IC 0.0236, std IC 0.0778, the full gross/cost/net return table, and max drawdown -0.034 all
matched exactly.

## Results, read carefully

Mean IC of 0.0236 sits at the low end of the "0.02 to 0.05 considered decent" range the top
level `README.md` cites for equity factors, and does not blow up or flip sign under the
execution-timing fix, both mild positive signs about the computation. It is not evidence the
factor suite works. With std IC 0.0778 and only 16 observations, the standard error on the mean
is `0.0778 / sqrt(16) ≈ 0.0195`, putting the mean about 1.2 standard errors from zero, short of
ordinary significance and far short of the roughly 2.78 t-stat hurdle the factor-zoo discipline
section already commits this project to before trusting any candidate. Several of the sixteen
factors barely move month to month, so the true number of independent observations behind this
estimate is smaller than sixteen, not larger. This window validates that the computation
behaves sensibly; it does not yet answer whether the factor suite has real predictive power,
that requires the full history run.

## Part 9: full history results

`scripts/build_backtest.py` (new) and three additions to `src/backtest/engine.py`
(`save_backtest_results`, `load_backtest_results`, `build_backtest`) give the walk forward loop
the same load-if-cached-else-compute-and-cache contract as the other loaders, persisting to
`data/processed/backtest_panel.parquet` and `backtest_weights.parquet` as two long format
tables (`date` and `cik` columns) rather than the dict-of-frames shape convenient for
computation.

A real round trip bug was caught before trusting the cache: `pd.concat` across every date's
frame aligns to the union of columns, so the most recent date, which genuinely has no
`forward_return` column (nothing to compare it against yet, per `run_backtest`'s own contract),
came back from parquet with the column anyway, filled entirely with `NaN`. `load_backtest_results`
now drops it back out for that date specifically, so a cached and a freshly computed result are
indistinguishable. Left unfixed, this would have silently inflated the observed sample size by
one wherever `information_coefficient`'s own `"forward_return" not in df.columns` check was
relied on downstream. `run_backtest` also gained per-month progress logging
(`logger.info("month %d/%d (%s)", ...)`, under `--verbose`), needed once a run stretches to
nearly 200 dates rather than the seventeen-date mechanism check.

The real measurement: 199 monthly dates, 2010-01-31 to 2026-07-31, bounded by the fundamentals
2009 XBRL mandate and the cached price data's own upper bound respectively. One date,
`2026-06-30`, produced no measurable IC at all: `factor_score` resolves normally (476 of 498),
but `forward_return` is entirely `NaN`, traced to the price cache's own ceiling rather than a
bug. `forward_return` for this date needs a session strictly after `2026-07-31` (the next
rebalance date) as its exit price, and `2026-07-31` is the last date `data/raw/prices` reaches;
`next_open_after` correctly returns `None` rather than guessing. This means the two most recent
rebalance dates, not only the final one `run_backtest` already excludes by design, contribute no
IC observation. Effective sample after dropping it: 197, not 198.

IC: mean 0.0146, std 0.1022, naive SE `0.1022 / sqrt(197) ≈ 0.0073`, naive t ≈ 2.00, already
short of the roughly 2.78 hurdle. Lag-1 autocorrelation (computed on the raw 198-length series
with the `NaN` still in place, not on the dropna'd version, since a `NaN` sitting in the middle
of a series would otherwise let a positional shift silently pair two months that are really two
apart as if they were one apart; in this run the `NaN` happens to sit at the tail so it makes no
difference, but the raw-series approach is the one that stays correct in general) is 0.0561,
mild persistence rather than none. Effective sample size
`197 * (1 - 0.0561) / (1 + 0.0561) ≈ 176.1`, corrected SE ≈ 0.0077, corrected t ≈ 1.89. The
combined, equal-weighted sixteen-factor suite does not clear the significance bar on this
measurement.

Cumulative net return over the full window: 22.1 percent (roughly 1.2 percent annualized), max
drawdown -19.1 percent. A buy-and-hold SPY benchmark computed the same way (the same
`forward_return` mechanism, same dates, same treatment of the one unmeasurable month) returned
828.5 percent cumulatively over the same window. The two are not a fair risk-adjusted
comparison: the quantile bucket portfolio is dollar-neutral by construction (long and short
weights each sum to 1.0 in magnitude), carrying close to zero net market beta, while SPY carries
full market exposure. The comparison is still informative in absolute terms, and consistent
with, not contradictory to, the IC result above.

`missing_forward_return_positions`, flagged in Part 8's Open items as clean only across a
sixteen-month window and needing a full history recheck: not clean at full scale. 5 dates show a
held position with no measurable forward return, 195 total missing observations, but 190 of
those are the single `2026-06-30` price-ceiling date above, already explained. The other 5,
spread across four separate 2018 dates (`CSRA`, `ANDV`, `EVHC`, `ESRX`, `SCG`, one or two per
date), are real delistings: all five were acquired in 2018 mergers (CSRA by General Dynamics,
Andeavor by Marathon Petroleum, Envision Healthcare by KKR, Express Scripts by Cigna, SCANA by
Dominion Energy), consistent with the price loader's own documented, much poorer coverage for
delisted names. A small, bounded, explained residual, not a systemic gap.

## Part 10: per-factor information coefficient

Answers the gap Part 9 left open: whether the combined score's weak result hides an
individually stronger factor underneath it. `run_rebalance` (`src/backtest/engine.py`) was
widened to return each factor's own z-scored value as a `z_<factor>` column, alongside the
existing `combined_score`/`factor_score`, computed once inside the function rather than
discarded after `combine()` uses it. `save_backtest_results`/`load_backtest_results` needed no
changes, since both are schema-agnostic (`pd.concat`/`groupby` on however many columns exist).
This required a full rerun (`python -m scripts.build_backtest --refresh`), since the existing
cache reflected the old, narrower schema.

No individual factor clears the roughly 2.78 hurdle, naive or autocorrelation-corrected (same
method as Part 9: lag-1 autocorrelation on the raw per-date IC series, effective sample size
`n * (1 - rho) / (1 + rho)`). The correction moves every factor's t-stat by less than 0.15 in
magnitude and never flips a conclusion, since the gap to significance is too large for it to
matter here:

| Factor | mean IC | naive t | rho | effective n | corrected t |
|---|---|---|---|---|---|
| debt_issuance | 0.0079 | 1.73 | 0.090 | 164.4 | 1.58 |
| leverage | 0.0054 | 1.28 | 0.051 | 178.1 | 1.22 |
| low_vol | 0.0193 | 0.99 | -0.016 | 203.4 | 1.00 |
| momentum | 0.0119 | 0.82 | -0.050 | 217.8 | 0.87 |
| seasonality | 0.0060 | 0.85 | -0.002 | 197.8 | 0.85 |
| volume_shock | 0.0032 | 0.56 | -0.105 | 243.3 | 0.63 |
| short_term_reversal | 0.0059 | 0.54 | -0.086 | 234.0 | 0.59 |
| investment | 0.0027 | 0.42 | 0.119 | 155.0 | 0.37 |
| quality | 0.0016 | 0.30 | -0.025 | 207.0 | 0.31 |
| profitability | 0.0031 | 0.37 | 0.190 | 134.2 | 0.30 |
| high_proximity | 0.0002 | 0.01 | -0.107 | 244.2 | 0.01 |
| size | 0.0001 | 0.01 | 0.027 | 186.7 | 0.01 |
| profit_growth | -0.0008 | -0.10 | 0.125 | 153.4 | -0.09 |
| illiquidity | -0.0040 | -0.43 | -0.105 | 243.1 | -0.48 |
| value | -0.0050 | -0.54 | 0.016 | 190.6 | -0.54 |
| accruals | -0.0069 | -0.96 | 0.052 | 177.6 | -0.91 |

Worth noting rather than treating as a contradiction: the combined score's own naive t (2.00,
Part 9) exceeds every individual factor's naive t (max 1.73). Averaging several weak, partially
independent, consistently-signed signals raising the apparent significance above any single
ingredient is the expected behavior of combination, not evidence a strong factor is hiding in
the mix. The four negative-IC factors below show the combined result is not secretly one
dominant signal being diluted by noise; it is a genuine diversification effect across many
individually weak pieces.

`value` and `accruals` reading negative over this window is not read as a defect. Both are
long-studied, historically robust factors in the literature this project's own risk-model
taxonomy is built on, and value's underperformance through most of the 2010s (with a partial
reversal beginning 2022) is well documented independently of this project's own measurement,
consistent with rather than contradicted by what shows up here. One 16.5-year window is not
evidence either factor is permanently broken.

This result reinforces, more strongly than the combined-only measurement did, that weight
optimization (Build order step 7's optimizer, and purged cross validation over
`configs/factors.yaml`) is premature: there is no standout factor to overweight even if the
intent were to, and searching for a subset that looks good in this specific sample would be
exactly the data snooping the factor-zoo discipline section warns against.

## Open items

- `BX` and `LULU`'s persistent missing beta was flagged twice during validation and never
  root-caused. Not blocking, but still genuinely unresolved, not merely accepted.
- `COST_BPS = 10` and equal factor weights in `configs/factors.yaml` are both deliberate
  placeholders, not tuned results. Per Part 10's results, tuning either remains premature: no
  individual factor stands out to justify overweighting it, so there is nothing principled to
  tune toward yet.
- What comes after this measurement is an open question, not yet decided: continuing to the risk
  model and optimizer (Build order step 7) regardless, revisiting the alpha model's construction
  itself, or something else. See the top level `README.md`'s Current status.
