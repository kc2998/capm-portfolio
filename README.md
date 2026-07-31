# Quant Portfolio

A multi factor, cross sectional portfolio management system, built as a personal, fully open source project. This README exists to give full context on what's been decided so far, including for anyone (or any tool) picking up the project mid build.

## Project intent

This is a research and paper trading system, not a live trading system. The goal is to build something that works end to end and is honest about its own assumptions, not to publish novel research or manage real capital, though a path to live paper trading is part of the plan. If it ever generates real returns worth trading on, that's a bonus, not the design goal.

The architecture is directly based on the standard multi factor system used at large quant firms, as described in a reference video transcript kept locally at `resources/What-Nobody-Tells-You-About-Being-a-Quant.md`. That directory is not committed, since it holds third party material that cannot be redistributed. That transcript should be treated as the primary context document for the overall shape of this system, the block by block breakdown (data and signals, alpha model, risk model, portfolio construction, execution, performance analysis) comes directly from it, and a lot of terminology used throughout this repo (point in time data, security matching, information ratio, the fundamental law of active management) is explained there in detail.

## Core architecture

The system is a pipeline, not a single model:

```
Data sources
  -> Signal engineering (raw factors)
  -> Alpha model (combined, neutralized score)
  -> Risk model (runs in parallel)
  -> Portfolio optimizer (balances alpha vs risk)
  -> Execution (paper trading simulation)
  -> Performance analysis (feeds back into signal engineering)
```

Two theoretical foundations underpin this, both worth understanding before touching the code:

- **CAPM** gives the language, alpha and beta, and the claim that a stock's fair expected return depends only on its beta (its sensitivity to the market). The formula: `E(r_i) = r_f + beta_i * (E(r_m) - r_f)`.
- **Arbitrage Pricing Theory**, the direct justification for going multi factor at all, generalizes CAPM's single beta into several independent systematic factors. This project is built on APT's worldview, not CAPM's, since the whole premise is that there are multiple independent sources of return worth isolating.

A critical distinction to preserve in code and naming: **CAPM alpha** (a regression intercept, measured in percent, a statement about return) is not the same thing as a **combined factor score** (a relative ranking number with no return units, built from z scored signals). The project should keep these named differently in code, something like `factor_score` for the ranking number, reserving `alpha` for anything expressed in actual return units.

## Scope decisions already made

- **Paper trading, not live execution.** Real broker integration, tax handling, and live capital are explicitly out of scope for now.
- **Cross sectional, not single asset technical.** Every signal is scored relative to the rest of the universe on the same date, not judged against its own price history in isolation. This is the fundamental difference from a single ticker technical strategy (e.g. a Pinescript momentum or mean reversion script).
- **Universe: S&P 500, point in time.** Point in time index membership matters a lot here, backtesting a past date using today's constituent list introduces survivorship bias (e.g. Tesla wasn't added until 2020, so it shouldn't appear in a 2015 backtest). Membership is read from Wikipedia's article as it existed on each target date, retrieved through the MediaWiki revision API, rather than reconstructed by reverse applying the page's changes log. The evidence behind that choice, along with the coverage limits it carries, is recorded in `notebooks/logs/universe_construction.md`.
- **Everything built by hand, step by step**, for learning purposes, not generated wholesale. Code is introduced incrementally, with explanations, rather than dropped in as finished modules. The working agreement this implies, along with the documentation style used throughout the repo, is written out in `CLAUDE.md`.

## Rebalance frequency

Rebalance frequency is a configuration parameter (`rebalance_freq` in `configs/factors.yaml`,
consumed by `backtest/engine.py` as a pandas frequency string such as `W-FRI`, `SM`, or `ME`)
rather than a fixed design decision. Monthly, semi monthly, and weekly are to be compared
empirically once the pipeline runs end to end.

The reasoning matters, because the obvious intuition is misleading. Sampling more often
looks like it should provide more observations for fitting and evaluation, but observations
drawn from an overlapping window are not independent of one another. Momentum measured over
252 trading days and sampled one week apart shares 247 of those days with the preceding
observation, so the two values are nearly identical. Using the standard approximation for
overlapping samples, where the effective sample size is `N * (1 - rho) / (1 + rho)` and `rho`
is the correlation between consecutive observations, sixteen years of momentum yields an
effective sample size of roughly eight whether sampled weekly (832 nominal observations) or
monthly (190 nominal observations). Effective sample size is governed by the horizon of the
signal, not by how often it is recorded.

The same calculation applied to a one week reversal signal sampled weekly gives
non overlapping windows, a correlation near zero, and an effective sample size close to the
full 832. Increasing sampling frequency is therefore a substantial gain in statistical power,
but only for signals whose own horizon is comparably short. Moving to a weekly cadence
requires changing the set of factors, not only the calendar.

Note that this constraint applies to the time dimension alone. Each rebalance date already
supplies roughly 500 cross sectional observations, so the information coefficient on any
single date is estimated reasonably precisely. The scarce quantity is independent time
points, which is what determines whether a positive average information coefficient reflects
skill or chance.

Once a portfolio optimizer with an explicit transaction cost term exists, rebalance frequency
largely resolves itself. The construction problem takes the form
`maximize alpha(w) - lambda * risk(w) - cost(|w - w_current|)`, which compares the expected
gain from trading against the cost of trading. When signals have barely moved, the gain is
small, the cost term dominates, and the optimizer declines to trade. When many signals shift
at once, the gain exceeds the cost and it trades in proportion to how much the view changed.
Trading frequency then follows from the economics rather than from an imposed calendar. This
property depends entirely on the cost model being present, which is why the cost model has
been moved earlier in the build order.

Rules that follow from this:

- Compare frequencies **net of transaction costs**. Gross returns will always favor faster
  rebalancing, and the difference between gross and net is where the answer lies.
- Treat frequency as a **tuned hyperparameter inside purged cross validation**, never selected
  by inspecting full sample results. Otherwise the conclusion that a given frequency won
  records nothing more than which frequency overfitted best.
- Every adjustment rule must be expressible as code. Discretionary intervention reintroduces
  the behavioral biases a systematic process exists to remove, and makes a backtest
  unreplayable because judgement cannot be replayed.
- **Universe resolution need not match rebalance frequency.** Index membership changes roughly
  25 times per year, about twice a month, and Wikipedia's own revision lag was 53 days in
  2010, so weekly snapshots would assert a precision the source does not possess. Snapshots
  are taken monthly and the most recent snapshot is used for each rebalance.
- Plan for turnover control from the first backtest: no trade bands (only trade a name once
  its rank moves outside a buffer), partial rebalancing toward the target, and explicit
  turnover constraints in the `cvxpy` optimizer.

## Factor selection

Factors are grouped by the frequency at which their underlying information genuinely
refreshes. A factor contributes new information only when its inputs change, so this grouping
determines which cadences are meaningful and which merely generate turnover.

**Weekly horizon: price and volume only.** These require no fundamentals, carry no filing
lag, and are not subject to restatement, which makes them both the cheapest factors to build
and the only ones that justify a weekly cadence.

| Factor | Computation | Data needed |
|---|---|---|
| Short term reversal | Negative of trailing one week (or one month) return | Daily prices |
| 52 week high proximity | Price divided by trailing 252 day maximum | Daily prices |
| Illiquidity (Amihud) | Mean of absolute return divided by dollar volume | Daily prices and volume |
| Volume shock | Recent volume divided by trailing average volume | Daily volume |
| Residual momentum | Momentum after removing market and sector beta | Daily prices |

Short term reversal is well documented (Jegadeesh 1990, Lehmann 1990) but is strongest among
small and illiquid securities and is substantially eroded by transaction costs. Its
usefulness within a large capitalization universe should be screened by information
coefficient before it is built into the pipeline.

**Semi monthly horizon.**

| Factor | Computation | Data needed |
|---|---|---|
| Short interest change | Rate of change in short interest as percent of float | FINRA short interest, published about twice monthly |
| Insider buying, short window | Net insider buying over trailing 30 days, divided by market cap | SEC EDGAR Form 4 filings |

**Monthly horizon.** These are the foundational price based factors.

| Factor | Computation | Data needed |
|---|---|---|
| Momentum | Trailing 12 month return, excluding the most recent month | Daily prices |
| Low volatility | Trailing standard deviation of returns | Daily prices |
| Size | Log of market cap | Market cap |
| Insider buying, standard window | Net insider buying over trailing 90 days, divided by market cap | SEC EDGAR Form 4 filings |

**Quarterly horizon: filing driven.** These are anchored to reporting periods and cannot
refresh faster than companies file.

| Factor | Computation | Data needed |
|---|---|---|
| Value | Earnings to price or book to price ratio | Fundamentals |
| Quality | Return on equity or debt to equity | Fundamentals |
| Earnings call evasiveness | Hedging language detection or response length vs question length in the Q&A section | Scraped earnings call transcripts |

Value is only partly static between filings. The earnings term is fixed until the next
report, but the price term moves continuously, so relative rankings still shift as prices
diverge.

**Daily horizon: deferred.**

| Factor | Computation | Data needed |
|---|---|---|
| Reddit/social sentiment | Daily sentiment score per ticker via a pretrained classifier (e.g. FinBERT), aggregated and z scored | Reddit API scrape |

Sentiment decays over days and will retain little value in a weekly or slower system. This is
a genuine tension rather than an oversight. It can be resolved either by accepting the
degradation or by running a faster sleeve alongside the slower one, and the decision is
deferred until the core pipeline is proven.

**Build order within factors.** The five foundational factors (momentum, value, size,
quality, low volatility) are built first regardless of horizon, since they establish the
scoring pipeline. The weekly horizon price and volume factors follow, since they reuse the
same price data already loaded. Insider and short interest come next, and sentiment and
earnings call analysis last.

Other ideas considered and intentionally deprioritized for now: options skew (rough free data
access), supply chain lead lag (bigger build, needs entity extraction from 10-Ks first),
Twitter sentiment (API access got too expensive for a free tier).

## Data sources

| Data | Source | Cost | Notes |
|---|---|---|---|
| Daily prices | `yfinance` | Free | Built and validated as one parquet file per CIK under `data/raw/prices/`, plus a coverage report at `data/processed/prices_coverage.parquet`; full methodology in `notebooks/logs/loaders_construction.md` |
| Fundamentals, market cap | SEC EDGAR XBRL API | Free | Point in time caveat below |
| Universe membership | Wikipedia S&P 500 page, retrieved per date through the MediaWiki revision API (2008 onward), plus a book-derived CSV (Clenow/Norgate) for 1996 to 2008 | Free | Wikipedia requires a real `User-Agent` header or requests are blocked with a 403. Built and validated as `data/processed/universe_spans.parquet` and `data/processed/ticker_history.parquet`; full methodology in `notebooks/logs/universe_construction.md` |
| Insider trading | SEC EDGAR full text search (Form 4) | Free | |
| Short interest | FINRA | Free | |
| Risk free rate | 3 month T-bill yield, FRED API | Free | |
| Reddit sentiment (later) | Reddit API (PRAW) | Free tier | |
| Earnings transcripts (later) | Scraped or a cheap transcript API | Mostly free, some paid | Coverage gaps for smaller companies |

**Known limitation to document honestly in the repo, not hide**: free fundamentals sources generally show current, restated financials, not the originally filed numbers as they stood on the filing date. This is a real point in time gap. Price only signals (momentum, low volatility) don't have this problem since price history isn't restated. Treat backtest results involving fundamentals with more skepticism than price only results, and note this limitation wherever fundamentals data is used.

**Prices are cached locally rather than fetched live.** Vendor prices are pulled once and
written to `data/raw`, then processed into `data/processed`, and all downstream code reads
from disk. Two reasons. A backtest reads the same price history repeatedly, once per
rebalance and once per parameter setting, so repeated network calls are slow and hit rate
limits. More importantly, `yfinance` serves prices adjusted for splits and dividends, and
those adjustments change as new corporate actions occur, so the same historical date can
return a different value months later. A backtest whose inputs shift underneath it cannot be
reproduced.

**Delisted securities are the weak point of free price data.** A point in time universe
necessarily includes companies that have since been acquired or have failed, which is the
entire purpose of avoiding survivorship bias. Free sources have their poorest coverage for
exactly those names. The price loader must measure and report the fraction of historical
members for which prices cannot be retrieved, rather than dropping them quietly, because
quiet dropping would reintroduce survivorship bias at the data layer after it had been
removed at the universe layer. Measured directly, not assumed: roughly 91% coverage for
still-active names versus 49% for delisted ones, a real gap, see
`notebooks/logs/loaders_construction.md`.

**Ticker format differs between sources.** Wikipedia writes multi class tickers with a period
(`BRK.B`, `BF.B`) where `yfinance` expects a hyphen (`BRK-B`). Translation belongs in the
price loader, at the boundary where the vendor is called. The universe parser reports what
the source said and does not adapt it to any particular consumer.

## Key concepts the implementation must respect

These came up repeatedly during planning and are easy to accidentally violate while coding fast, so they're listed explicitly here.

- **Point in time discipline.** Universe membership, fundamentals, and any restated data must reflect only what was actually known as of the backtest date. No look ahead. In practice this means using the date on which information became publicly available, not the date the information describes. A quarterly report covers a period ending in March but does not reach EDGAR until May, so the filing date governs, with a conservative lag of 45 to 90 days after period end where filing dates are unavailable. FINRA short interest carries a settlement date and a later publication date, and the publication date governs. Prices are used as of the rebalance date's close and orders execute at the following session's open, since computing a signal from a closing price and trading at that same close is a subtle form of look ahead.
- **Survivorship bias.** Don't backtest against today's constituent list for past dates.
- **Cross sectional z scoring.** Every raw factor gets standardized relative to the rest of the universe on that same date, not against its own historical distribution.
- **Missing data handling.** When a stock lacks a given factor on a given date, drop that term from the weighted average and renormalize the remaining weights, rather than substituting zero (zero implies "average," not "unknown"). Document whichever missing data rule is used.
- **Beta neutralization.** Before ranking, regress the combined factor score against beta across the universe on that date, and rank on the residual, not the raw score. This prevents the model from accidentally rewarding high beta names and calling it skill. This regression is refit at every rebalance date, never fit once and reused.
- **Walk forward backtesting.** Fit and test on non overlapping time windows, rolling forward, rather than fitting once on the full history and grading against the same data.
- **Purged cross validation when tuning parameters.** When testing different factor weights, lookback windows, or rebalance frequencies, tune on some folds and test only on a held out fold, with a gap around the boundary to avoid leakage. Expect real forward performance to be somewhat worse than the best backtest seen during tuning.
- **Information coefficient as the fast screening tool.** Before building a full pipeline around any new signal idea, check its IC (the correlation between the signal's value and the stock's forward return, across stocks and time) to see if it's worth pursuing at all. Values around 0.02 to 0.05 are considered decent in equities.
- **Multiple testing awareness.** If many novel signal ideas get tried, some will look good purely by chance. Be honest about how many ideas were tested before finding one that worked, and hold out data that's never touched during signal design.

## Repo structure

```
quant-portfolio/
├── README.md
├── requirements.txt
├── .gitignore
├── configs/
│   ├── universe.yaml
│   └── factors.yaml
├── data/
│   ├── raw/                    # gitignored, untouched vendor pulls
│   └── processed/               # gitignored, parquet partitioned by date
├── resources/                    # gitignored, third party reference material held locally
│   ├── What-Nobody-Tells-You-About-Being-a-Quant.md   # primary context document (video transcript)
│   └── Active_Portfolio_Management_A_Quantitati.pdf   # Grinold & Kahn reference text
├── src/
│   ├── universe/
│   │   ├── point_in_time.py    # reconstructs S&P 500 membership by date, done
│   │   └── README.md           # what it produces, schema, toy examples
│   ├── loaders/
│   │   ├── prices.py            # point in time OHLCV per CIK, done
│   │   ├── README.md            # what it produces, schema, toy examples
│   │   ├── fundamentals.py
│   │   ├── insider.py
│   │   └── short_interest.py
│   ├── factors/
│   │   ├── momentum.py
│   │   ├── value.py
│   │   ├── size.py
│   │   ├── quality.py
│   │   ├── low_vol.py
│   │   └── insider_signal.py
│   ├── scoring/
│   │   ├── zscore.py            # cross sectional z scoring
│   │   ├── combine.py           # weighted combination, missing data handling
│   │   └── neutralize.py        # beta regression and residual
│   ├── risk_model/
│   │   └── factor_covariance.py
│   ├── optimizer/
│   │   └── construct_portfolio.py   # cvxpy based
│   ├── backtest/
│   │   ├── engine.py             # walk forward loop
│   │   └── metrics.py            # IC, information ratio, drawdown, turnover
│   └── execution/
│       └── paper_broker.py       # simulated fills and transaction costs
├── notebooks/                    # exploratory work happens here first
│   └── logs/                     # findings from exploratory work, kept after the notebook moves on
├── tests/
│   ├── test_point_in_time.py     # pure logic only; no network calls mocked or hit
│   └── test_prices.py            # pure logic only; no network calls mocked or hit
└── scripts/                       # thin entry points that call into src
    ├── build_universe.py         # python -m scripts.build_universe [--refresh] [--verbose]
    └── build_prices.py           # python -m scripts.build_prices [--refresh] [--verbose]
```

The separation between `src` and `scripts` is deliberate: `src` holds reusable, testable logic with no side effects on import, `scripts` holds short, direct entry points that call into `src` and decide what to actually run and where to save output. Exploratory or messy data investigation (inspecting a new source's structure, debugging a scrape) happens in `notebooks/` first, and only gets promoted into `src` once it's a clean, working function.

`notebooks/logs/` holds the findings from that exploratory work in prose. A notebook records
what was run; the log records what was learned and why a decision was made, which is the part
that stays relevant after the notebook itself is superseded. The README states decisions, the
logs state the evidence behind them.

## Build order

1. Point in time universe builder (`src/universe/point_in_time.py`, done, see its own `README.md`) plus a price loader (`src/loaders/prices.py`, done, see its own `README.md`). Validate with a trivial backtest of the S&P 500 itself, no factors yet, just to confirm the universe and price pipeline are correct.
2. Fundamentals loader plus the five foundational factors. Build `scoring/zscore.py` and `scoring/combine.py` with missing data handling from day one.
3. `scoring/neutralize.py`, tested against toy examples before trusting it on real data.
4. Quantile bucket portfolio construction (simple long top fifth, short bottom fifth), plus `backtest/engine.py` and `backtest/metrics.py`, with `rebalance_freq` read from config, and a basic transaction cost model. This gives a full working loop end to end on foundational factors alone.
5. Weekly horizon price and volume factors (short term reversal, 52 week high proximity, illiquidity, volume shock). These reuse price data already loaded in step 1, and make a weekly cadence meaningful enough to compare against monthly.
6. Insider trading and short interest loaders, added as new factors into the existing scoring pipeline. No architecture changes needed if step 2 was built generically.
7. `risk_model` and `optimizer` (replacing quantile bucketing with a real `cvxpy` optimization once the ranking itself is trusted). Turnover constraints and no trade bands belong here.
8. `execution/paper_broker.py` for an ongoing paper trading loop, refining the step 4 cost model into realistic fill simulation.
9. Reddit sentiment and earnings call evasiveness factors, once the core pipeline is proven and trusted.

The transaction cost model appears at step 4 rather than alongside execution, which is where
it would naturally sit. The reason is that cost determines whether a faster rebalance cadence
is worth anything. At monthly frequency costs are a refinement; at weekly frequency the
difference between gross and net return is the entire result, and the optimizer property
described above, whereby trading frequency follows from the economics, does not hold without
a cost term. A crude estimate in basis points per unit of turnover is sufficient at step 4.
It only needs to exist before any faster cadence result is believed.

## Environment setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

macOS note: if HTTPS requests fail with an SSL certificate error, it's usually because the python.org installer doesn't hook into the system certificate store. Fix with `pip install --upgrade certifi` inside the venv, and set `ssl._create_default_https_context` to use `certifi.where()` at the top of any module making HTTPS requests.

Wikipedia and some other scraped sources return `403 Forbidden` without a real `User-Agent` header on the request. Use `requests.get(url, headers={"User-Agent": "..."})` and pass the resulting text into `pandas.read_html`, rather than letting `read_html` hit the URL directly.

## Current status

- Repo scaffolding complete (folder structure, virtual environment, `.gitignore`, `requirements.txt`).
- **Point in time universe built and validated, 1996 to present.** Two artifacts:
  `data/processed/universe_spans.parquet` (membership, one row per interval) and
  `data/processed/ticker_history.parquet` (which symbol an entity traded under, and when).
  Built from Wikipedia's revision history (2008 onward, re-derivable at any time) and a
  book-derived CSV (1996 to 2008, Clenow/Norgate), reconciled against each other and
  cross-checked. Full methodology, every source considered and rejected, and every bug
  found while building it are recorded in `notebooks/logs/universe_construction.md`.
- Of the pre-2008 tickers flagged for manual review, 82 of 193 have been automatically
  confirmed or corrected against primary source SEC filings (a citable filing and quoted
  disclosure for each, not an assumption). A known, bounded residual remains: 3 corporate
  action cases genuinely need a person to resolve (a tracking stock or dual class split),
  and 204 are checked but inconclusive or unmatched, explained rather than silently dropped.
  None of this blocks using the universe; it only affects how far the pre-2008 ticker
  strings themselves can be trusted without a closer look.
- One decision still open: whether dual class share listings (e.g. `GOOG`/`GOOGL`) should be
  treated as one company or two; see the log's Open items.
- **Promoted to `src/universe/point_in_time.py`.** Side effect free on import, project root
  relative paths, a small public API (`build_universe()`, `membership_on()`, `ticker_on()`)
  instead of a linear script. Verified against the notebook's own output: identical row
  counts and membership on every test date. `notebooks/exploring_universe.ipynb` stays as
  the historical record of how this was built; `src/universe/README.md` is the usage
  reference for the promoted version. 24 tests in `tests/test_point_in_time.py` cover the
  pure logic, several written directly against bugs found while building this.
- A known, documented gap in `ticker_history`: a handful of tickers (`GOOGL`/`GOOG`,
  `FOXA`/`FOX`, `XOM`, and others) are attributed to two different CIKs where an
  administrative reorganization changed the reporting entity with no real trading
  discontinuity. A fix was attempted and reverted after it turned out to also merge two
  genuinely different companies handed the same ticker via a real merger; see the log's Open
  items for the distinguishing signal still needed before this can be fixed safely.
- **Point in time price loader built and validated**, `src/loaders/prices.py`. Produces one
  parquet file per CIK (`data/raw/prices/{cik}.parquet`, gitignored) and a coverage report
  (`data/processed/prices_coverage.parquet`), fetched via `yfinance`, keyed by (CIK, ticker)
  rather than CIK alone since a single CIK can hold more than one concurrently priced
  security (a dual class share) as well as more than one ticker over time (a rename).
  Verified against every real edge case found: ticker recycling (a retired symbol silently
  reused by an unrelated company), dual and triple class shares, genuine retirements, and a
  round trip rename. Measured, not assumed: roughly 91% coverage for still-active names
  versus 49% for delisted ones. Side effect free on import, a small public API
  (`build_prices()`, `fetch_cik_prices()`, `load_cik_prices()`), 12 tests in
  `tests/test_prices.py` covering the pure decision logic (the network-bound classification
  itself is validated empirically, not mocked). `notebooks/exploring_loaders.ipynb` stays as
  the historical record; `src/loaders/README.md` is the usage reference; full methodology in
  `notebooks/logs/loaders_construction.md`.
- Next concrete step: the fundamentals loader and the five foundational factors, per the
  build order below.
