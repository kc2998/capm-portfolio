# Backtest: walk forward loop, portfolio construction, and evaluation metrics

Answers the question the rest of this project has been building toward: given the combined
factor suite, does it predict which stocks outperform, and what would a portfolio that traded
on it have actually earned, net of turnover cost. This is Build order step 6, the point where
information coefficient first gets measured across the complete 13-theme factor set, one
comprehensive pass rather than a piecemeal screen.

This file explains what each module produces and how to call it. The full methodology, every
bug found while building it (a filer's 1000x share count error, a survivorship trap in an
early version of the loop itself, an execution-timing lookahead the numbers alone didn't
reveal), and the evidence behind every non-obvious decision, is in
`notebooks/logs/backtest_construction.md`. That file records why; this one records how to use
the result.

## engine.py: the walk forward loop

Answers "what did the combined factor suite say about every stock in the universe, on every
rebalance date." Re-resolves point in time universe membership fresh at each date (`ciks_on`,
`src/universe/point_in_time.py`) rather than reusing one fixed sample across time, which would
reintroduce the survivorship bias the top level `README.md` opens with.

### What it produces

**`FACTOR_REGISTRY`**, a dict mapping each of the sixteen factor names to a small adapter
function, all sharing the same `(facts, prices, ticker, as_of)` call shape even though the
underlying factor functions don't. Three adapters (`_facts_only`, `_prices_only`,
`_facts_and_prices`) capture the three argument shapes actually in use. Adding a seventeenth
factor means one new line in this dict, not an edit to `compute_row`.

**`_load_universe_data(ciks)`**: loads each CIK's company facts and price history once and
returns a `{cik: (facts, prices)}` dict. A CIK's cached data does not change within a single
run, only `as_of` changes what the factor functions do with it, so `run_backtest` builds this
once up front rather than letting every date reread the same files from disk.

**`compute_row(cik, as_of, facts, prices, ticker_history, market_prices)`**: every raw factor
plus beta for one CIK on one date, a dict with `cik`, `ticker`, the sixteen factor names, and
`beta`. `facts` and `prices` are supplied already loaded, from `_load_universe_data`. `beta` is
computed outside the registry deliberately, it needs `market_prices`, an external series none
of the other factors touch.

**`run_rebalance(as_of, ciks, weights, cik_data, ticker_history, market_prices)`**: one date's
full scoring pipeline for a list of CIKs, raw factors z-scored (`scoring/zscore.py`), combined
(`scoring/combine.py`), neutralized against beta (`scoring/neutralize.py`). `cik_data` is the
dict from `_load_universe_data`. Returns a DataFrame indexed by `cik` with `ticker`,
`combined_score`, `beta`, `factor_score`.

**`quantile_weights(df, score_col="factor_score", quantile=0.2)`**: long the top fifth of
`factor_score`, short the bottom fifth, equal weighted within each side. Dollar neutral by
construction, long and short weights each sum to 1.0 in magnitude.

**`forward_return(prices, ticker, start, end)`** and
**`add_forward_returns(result, as_of, next_date, cik_data)`**: a stock's return from the
trading session after `start` to the session after `end`, using `next_open_after`
(`src/loaders/prices.py`), not either date's own close, per the top level `README.md`'s
execution timing rule: "orders execute at the following session's open." `add_forward_returns`
reads prices from `cik_data` rather than the disk.

**`run_backtest(dates, universe_spans, ticker_history, market_prices, weights)`**: the loop
itself. Resolves every CIK that appears in the universe on any date in `dates` and loads its
data once via `_load_universe_data`, then runs `run_rebalance` and `quantile_weights` at every
date, attaching `forward_return` to every date but the last. Returns
`(panel_results, portfolio_weights)`, both dicts keyed by `"YYYY-MM-DD"` date strings.

### How to use it

```python
import pandas as pd
import yaml

from src.universe.point_in_time import build_universe
from src.loaders.fundamentals import build_fundamentals
from src.loaders.prices import build_prices
from src.loaders.market import build_market
from src.backtest.engine import run_backtest

universe_spans, ticker_history = build_universe()
build_fundamentals()
build_prices()
market_prices = build_market()

with open("configs/factors.yaml") as f:
    config = yaml.safe_load(f)

dates = pd.date_range("2023-01-01", "2024-06-28", freq=config["rebalance_freq"])
panel_results, portfolio_weights = run_backtest(
    dates, universe_spans, ticker_history, market_prices, config["weights"]
)
```

## metrics.py: evaluation

Answers "given the loop's output, does the signal predict anything, and what would trading on
it have earned."

### What it produces

**`turnover(w_prev, w_curr)`**: sum of absolute weight change across the union of tickers in
either date, missing treated as 0.

**`missing_forward_return_positions(weights, forward_returns)`**: held positions (nonzero
weight) with no measurable forward return. Surfaces rather than silently absorbs the same
failure mode the price loader's own coverage report already measures for delisted names,
dropping these silently would reintroduce survivorship bias at the return layer.

**`information_coefficient(panel_results)`**: the cross sectional correlation between
`factor_score` and `forward_return`, one value per date, as a `pd.Series` indexed by date.

**`portfolio_return(weights, forward_returns, prior_weights=None, cost_bps=COST_BPS)`** and
**`backtest_returns(panel_results, portfolio_weights, cost_bps=COST_BPS)`**: one date's, or the
whole run's, gross, cost, and net return for the quantile bucket portfolio. `COST_BPS = 10` is a
module constant, a crude basis-point-per-unit-of-turnover placeholder, per the top level
`README.md`'s own framing that a crude estimate is sufficient at this step.

**`max_drawdown(net_returns)`**: the largest peak to trough decline in cumulative
`(1 + net_returns).cumprod()`.

### How to use it

```python
from src.backtest.metrics import information_coefficient, backtest_returns, max_drawdown

ic_series = information_coefficient(panel_results)
returns_df = backtest_returns(panel_results, portfolio_weights)
print(max_drawdown(returns_df["net"]))
```

## Toy examples, from the real data

**A seventeen date, roughly 500 company mechanism check (2023-01-31 to 2024-06-28, monthly).**
Not a real measurement, see the caveat below, but confirms the loop behaves sensibly: mean
`factor_score` is 0.0 on every date (the neutralization residual's own construction), mean IC
0.0236, std IC 0.0778, turnover ranging 1.24 to 2.0, max drawdown -0.034.

**A real, filer-side bug the loop's own sanity checks caught, not assumed away.** Packaging
Corporation of America's 2024-05-08 10-Q reported its cover page share count as 89,797,979,000,
exactly 1000x its real value (89.8 million, confirmed against the same filing's own
`CommonStockSharesIssued` tag and every neighboring quarter). This showed up as `size_factor`
computing to 30.4, `e^30.4 ≈ $15.6 trillion`, larger than any real company has ever been worth.
Fixed in `src/loaders/fundamentals.py`'s `shares_outstanding_as_of`, full story in the log.

## Caveats worth knowing before relying on these results

- **The mechanism check above is not evidence the factor suite predicts returns.** Sixteen
  monthly IC observations gives a standard error of roughly 0.0195 on the mean, putting it
  about 1.2 standard errors from zero, short of ordinary significance and far short of the
  factor-zoo discipline section's roughly 2.78 t-stat hurdle. A real measurement needs the full
  history run.
- **Fundamentals data is only reliable from the 2009 XBRL mandate onward** (see
  `notebooks/logs/fundamentals_construction.md`), so a genuinely comprehensive run's usable
  window is roughly 2010 to present, not the full 1996 to present the universe and price data
  cover.
- **`COST_BPS` and the factor weights in `configs/factors.yaml` are both placeholders**, equal
  weighted and a flat cost rate, not tuned results. Tuning either from the same pass meant to
  measure IC would be the data snooping the factor-zoo discipline section warns against.
- **`missing_forward_return_positions` came back clean across sixteen months**, but this hasn't
  been checked across full history, where more delistings are likely.
- **Not yet wired into a script.** `run_backtest` currently only gets called from
  `notebooks/exploring_backtest.ipynb`; `scripts/build_backtest.py`, the entry point that would
  run it across full history and cache results to `data/processed/`, doesn't exist yet.

## Plan: built so far, and what remains

Built: the point in time universe and loaders (fundamentals, prices, market), sixteen JKP
taxonomy factors, the beta risk model, the scoring pipeline (z-score, combine, neutralize),
this module's walk forward loop and evaluation metrics, and a 169 test suite covering the
universe, loader, and pure backtest logic (`quantile_weights`, `turnover`) plus every factor
module. All of it was promoted from `notebooks/exploring_backtest.ipynb` into `src/` and
verified to reproduce the notebook's own numbers exactly. `_load_universe_data` was added to
cache each CIK's data once per run rather than once per rebalance date, needed before a full
history run is practical at all.

Remaining, in order, and why each step comes where it does:

1. **`scripts/build_backtest.py`.** Does not exist yet. The mechanism check above covers
   sixteen months, giving a standard error too large to conclude anything either way. A real
   measurement needs a run across the full usable history, roughly 2010 or 2011 onward given
   the fundamentals caveat above, persisted to `data/processed/` so later questions do not
   require recomputing it.
2. **Interpretation of that run.** The IC series needs to be read against the roughly 2.78
   t-stat hurdle from the factor-zoo discipline section, with a correction for effective sample
   size, since monthly rebalances one month apart are not fully independent observations the
   way the naive standard error assumes. A per-factor IC, not only the combined score, and a
   full history recheck of `missing_forward_return_positions`, belong at this stage too.
3. **Weight optimization**, conditional on step 2. Purged cross validation over the factor
   weights in `configs/factors.yaml`, currently equal weighted by construction, not tuned. This
   comes after the untuned measurement specifically so the measurement is not itself the
   product of search, the data snooping the factor-zoo discipline section warns against.
4. **A real risk model and optimizer** (Build order step 7), replacing the quantile bucket
   construction this module currently uses, gated on GICS sector data being reattached to the
   universe.
5. **`execution/paper_broker.py`**, and only after that, novel alpha candidates (Form 4 insider
   trading, Lazy Prices, Wikipedia attention, Reddit sentiment), which the top level `README.md`
   already pauses until this suite's own measurement is in hand.
