# Factors: from a raw company number to a ranking score

This file explains every factor now built in `src/factors/`: sixteen modules covering all 13
JKP risk-model themes plus three additional weekly-horizon alpha candidates. It covers what
each one measures, the exact formula used, where every input in that formula comes from, and
how the resulting numbers are combined and neutralized into the single score the rest of the
pipeline treats as "alpha." It assumes no finance background; terms specific to accounting or
investing are defined on first use.

The first five, size, value, quality, momentum, and low volatility, were built first and are
called the **foundational factors** throughout this file, a label kept for continuity with
earlier notebooks and logs rather than any difference in how they are treated today; all
sixteen factors go through the same standardization, combination, and neutralization pipeline
described below. The remaining eleven, covered in their own section afterward, complete the
JKP taxonomy: short term reversal, seasonality, 52 week high proximity, volume shock, and
illiquidity from cached price and volume data, plus profitability, profit growth, investment,
accruals, low leverage, and debt issuance from cached fundamentals.

This file also places those sixteen factors against the two other categories the top level
`README.md` distinguishes: **risk factors**, which describe shared covariance rather than
predict return, and **novel alpha candidates**, proprietary signals held to a different
evidentiary bar than the well documented JKP themes. Both are covered near the end.

Full derivation and every validated edge case are in `notebooks/exploring_factors.ipynb`, cited
by part number below. This file records what each factor is and how to read it; the notebook
records how each one was built and checked.

## Why a raw number is not enough on its own

A **factor** is a rule that assigns every stock in the universe a single number on a given date,
meant to predict which stocks will outperform. The **universe** is the point in time set of
stocks under consideration (this project's S&P 500 membership, `src/universe/point_in_time.py`);
which stocks belong to it changes over time, and a factor is only ever compared across whichever
stocks belonged on that specific date.

The factors below live in different units: log dollars, a ratio near zero, a ratio that can swing
far larger, a percentage return, a standard deviation. None is used on its own. Before they can be
combined, or compared against each other, they go through steps defined precisely below:
standardization against the rest of the universe on that date (`src/scoring/zscore.py`), a
weighted average into one number per stock (`src/scoring/combine.py`), and a regression that
removes the part of that number explained by market beta (`src/scoring/neutralize.py`).

The final output is called `factor_score`, deliberately not `alpha`. In CAPM, alpha is a
regression intercept measured in units of return, a statement of the form "this stock earned 2
percent more than its risk justified." `factor_score` carries no such unit; it is a relative
ranking, and only says a stock looks stronger or weaker than its peers on this date, not by how
much return. The top level `README.md` treats this distinction as load bearing.

### Standardization: turning different scales into one

**Cross sectional** means "compared against the rest of the universe on the same date," as
opposed to compared against a stock's own history. Every step below is cross sectional: a stock's
z-score answers "how unusual is this value today, relative to its 500-ish peers today," never
"how does this compare to what this same stock looked like last year."

A **percentile** is the value below which a given fraction of a distribution falls; the 1st
percentile is the value only 1 percent of observations fall below. `winsorize` (in
`src/scoring/zscore.py`) clips a factor's values at its own 1st and 99th percentiles on that
date, so that one extreme company cannot dominate the mean and standard deviation computed next:

$$
\text{winsorize}(x_i) = \min\big(\max(x_i, \, p_{1}(x)), \, p_{99}(x)\big)
$$

where $x_i$ is one stock's raw factor value, and $p_1(x)$, $p_{99}(x)$ are the 1st and 99th
percentiles of that same factor computed across every stock in the universe on that date.

A **z-score** restates a value as "how many standard deviations above or below the average."
The **mean** is the simple average; the **standard deviation** measures how spread out the values
are around that average. After z-scoring, a factor's values across the universe have mean 0 and
standard deviation 1, on any date, regardless of the raw units it started in, which is what makes
log market cap and a percentage-point ratio comparable:

$$
z_i = \frac{\text{winsorize}(x_i) - \mu}{\sigma}, \qquad
\mu = \frac{1}{N}\sum_{i=1}^{N} \text{winsorize}(x_i), \qquad
\sigma = \sqrt{\frac{1}{N}\sum_{i=1}^{N} \big(\text{winsorize}(x_i) - \mu\big)^2}
$$

$N$ is the number of stocks in the universe on that date that have a value for this factor at
all; a stock with no value is carried through as missing rather than assigned any default,
confirmed in Part 3 of the notebook against a toy series with one missing entry.

### Combination: one score per stock

`combine` (`src/scoring/combine.py`) takes a weighted average of a stock's z-scores across every
factor:

$$
\text{combined\_score}_i = \frac{\sum_{k \in K_i} w_k \, z_{i,k}}{\sum_{k \in K_i} w_k}
$$

$w_k$ is the chosen weight for factor $k$ (for example, equal weight across all five), and $K_i$
is the subset of factors stock $i$ actually has a value for on that date, not every factor that
exists. A stock missing one factor has that term dropped from both the numerator and the
denominator and the remaining weights renormalized, rather than substituting zero, because zero
would assert "this stock is exactly average on the factor it's missing," a claim the data does
not support. Confirmed in Part 4: a stock missing one of two equally weighted factors receives the
other factor's full z-score, not half of it.

`combined_score` is not yet the final ranking; one more step, described next, is applied before
anything is ranked on it.

### Neutralization: removing the beta component

`src/scoring/neutralize.py` is built and tested, and it is worth being precise about what it does
and does not do, since the design involves two different regressions, both concerning "beta,"
that are easy to conflate.

**First: estimating each stock's own market beta, a regression across time, one stock at a
time.** This is the CAPM regression the top level `README.md` opens with. **Beta** measures how
sensitive a stock's return is to the market's return: a beta of 1.5 means the stock has
historically moved, on average, 1.5 percent for every 1 percent move in the market. It comes from
fitting this equation separately for each stock, using that one stock's own history of returns
against a market benchmark's history over the same dates:

$$
r_{i,t} - r_{f,t} = \alpha_i + \beta_i \,(r_{m,t} - r_{f,t}) + \epsilon_{i,t}
$$

| Symbol | Meaning |
|---|---|
| $r_{i,t}$ | Stock $i$'s return over period $t$, e.g. a day's or week's close to close price change |
| $r_{f,t}$ | The **risk-free rate** over the same period: the return on an investment with no default or market risk, standing in here for the 3 month T-bill yield the top level `README.md` lists as a planned data source |
| $r_{m,t}$ | The return of a **market proxy** over the same period: some benchmark meant to stand in for "the market as a whole" |
| $r_{i,t} - r_{f,t}$ | Stock $i$'s **excess return**: what it earned above the risk-free rate |
| $\alpha_i$ | The regression's intercept, in units of return; the literal "CAPM alpha" the top level `README.md` insists on keeping separate from `factor_score`, and not used anywhere downstream in this pipeline |
| $\beta_i$ | The regression's slope, and the number this step actually wants |
| $\epsilon_{i,t}$ | The residual for period $t$: whatever part of that period's return the market move does not explain |

This is a **time series regression**, one stock, many past dates, fit with ordinary least squares
over a trailing lookback window. **This half is not yet built.** `neutralize()` takes a `betas`
argument rather than computing it; per the Build order, beta estimation itself is grouped with
the backtest engine (step 8), after the full factor universe exists, not with `neutralize.py`
(step 3). Which market proxy stands in for $r_m$ and what lookback window to fit over are both
still open, and belong with that later step.

**Second: neutralizing the combined score against beta, a regression across stocks, one date at
a time.** This half is what `neutralize()` actually does. Given every stock's $\beta_i$ as of the
rebalance date, however it was produced, it fits a second, unrelated regression, this one
**cross sectional**, once per rebalance across every stock that day:

$$
\text{factor\_score}_i = a + b\,\beta_i + u_i
$$

$$
\hat b = \frac{\operatorname{Cov}(\beta,\, \text{combined\_score})}{\operatorname{Var}(\beta)}, \qquad
\hat a = \overline{\text{combined\_score}} - \hat b\,\bar\beta
$$

$a$ and $b$ are this regression's own intercept and slope, fit across the roughly 500 stocks in
the universe on that date, and $u_i$ is the residual: what remains of stock $i$'s combined score
once whatever part of it is linearly explained by beta alone has been removed. **$u_i$, not
$\text{combined\_score}_i$, is what a stock is finally ranked on**, and this is the value the
codebase calls `factor_score`. A stock missing either its score or its beta is excluded from the
fit entirely and its own residual returns as `NaN`, confirmed in Part 11 against a toy case: three
stocks fitting slope 2.5, intercept $-2$, giving residuals 0.5, $-1.0$, 0.5, and a fourth, missing
its score, correctly excluded and returned as `NaN`.

Per the top level `README.md`, this regression is refit at every rebalance date rather than fit
once and reused, the same reason the (not yet built) beta estimates feeding it are meant to come
from a rolling window rather than a single fixed fit: a relationship measured on old data is not
assumed to still hold today. The two regressions differ on every axis that matters, despite both
being described with the same two words: the first is fit once per stock, across time, to produce
one number, $\beta_i$; the second is fit once per date, across stocks, treating those $\beta_i$
values as a given input rather than something it estimates itself.

## The five foundational factors

### Size: log market capitalization

**Market capitalization** ("market cap") is the total market value of a company's outstanding
shares: current share price multiplied by the number of shares currently held by all
shareholders (**shares outstanding**). Size is one of the oldest documented cross sectional
patterns in equities (Banz, 1981): smaller companies have historically earned different average
returns than larger ones, plausibly because they are less liquid, less analyzed, and riskier in
ways a single beta does not fully capture.

$$
\text{market\_cap}(\text{as\_of}) = \text{shares}(t_{\text{shares}}) \times
\text{split\_ratio}(t_{\text{shares}} \rightarrow \text{today}) \times \text{price}(\text{as\_of})
$$

$$
\text{size\_factor} = \ln\big(\text{market\_cap}(\text{as\_of})\big)
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{shares}(t_{\text{shares}})$ | The most recent share count known as of the rebalance date | `shares_outstanding_as_of` in `src/loaders/fundamentals.py`, an EDGAR filing figure |
| $t_{\text{shares}}$ | The date that share count was reported as of, not the rebalance date itself | Returned alongside the count; can be well before `as_of` if that is the freshest filing available |
| $\text{price}(\text{as\_of})$ | The stock's closing price on or before the rebalance date | `close_on_or_before` in `src/loaders/prices.py` |
| $\text{split\_ratio}(t_{\text{shares}} \rightarrow \text{today})$ | A correction described below | `split_adjustment_ratio` in `src/factors/size.py` |

**Why the split correction is necessary.** A **stock split** is a corporate action where a
company divides each existing share into several new ones (a 4-for-1 split turns one share into
four), proportionally lowering the price per share without changing what the company as a whole
is worth. Cached prices (`src/loaders/prices.py`) are already split adjusted the way `yfinance`
serves them: the entire historical price series for a stock is restated onto the number of shares
that exist today, whatever date within that history is being read. A share count pulled from a
filing, in contrast, reflects only the number of shares that existed on that filing's own date,
with no adjustment for any split that happened afterward. Multiplying the two directly would
silently understate market cap for any company that has split its stock since the filing date, by
exactly the split factor.

$$
\text{split\_ratio}(t_0 \rightarrow t_1) = \prod_{t_0 < t \le t_1} r_t
$$

$r_t$ is the split ratio recorded on each split event's date (4.0 for a 4-for-1 split) occurring
strictly after $t_0$; a stock with no split in that window returns a ratio of 1.0, leaving the raw
share count unchanged. Confirmed against three real cases (Part 6): CMG, which split 50-for-1
before the query date, correctly returns a ratio of 50.0; ORLY, which split after the query date,
returns 15.0; AAPL, with no split in the window, returns 1.0.

**Why the logarithm.** Market caps span several orders of magnitude, from roughly a billion
dollars to well over a trillion within the same universe. Taking the natural log turns a
multiplicative relationship into an additive one: doubling in size is a constant step in log
space regardless of whether the starting point is small or large, which is the standard reason
size factors are built in log dollars rather than raw dollars in the academic literature this
project follows. Confirmed for correctness, not distributional shape, against exact cases in Part
6: $\ln(e) = 1.0$, $\ln(1.0) = 0.0$.

### Value: earnings yield

**Net income** is a company's accounting profit for a period: revenue minus every expense, tax,
and other charge on its income statement. Earnings yield restates it as a fraction of market cap,
the inverse of the more familiar price to earnings ("P/E") ratio:

$$
\text{value\_factor} = \frac{\text{net\_income}(\text{as\_of})}{\text{market\_cap}(\text{as\_of})}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{net\_income}(\text{as\_of})$ | The most recent annual net income figure known as of the rebalance date | `latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")` in `src/loaders/fundamentals.py` |
| $\text{market\_cap}(\text{as\_of})$ | As defined above, including the split correction | `market_cap_as_of` in `src/factors/size.py` |

**Why earnings, not revenue or gross profit.** `net_income` is tagged under a single, essentially
universal name (`NetIncomeLoss`) across the EDGAR filers this project has checked, where revenue
and gross profit both have documented sector gaps: banks report interest income rather than a
generic revenue line and are missing the tag entirely (`src/loaders/README.md`).

**Why earnings over price rather than price over earnings.** A P/E ratio behaves badly for a
company with negative earnings: a stock priced at \$100 losing \$1 per share has a P/E of $-100$,
a number that looks superficially similar to, and is not meaningfully orderable against, a wildly
overpriced but profitable stock. Earnings yield keeps the same case at $-0.01$, correctly reading
as strongly negative, and remains a continuous, sensibly ordered quantity across profitable and
unprofitable companies alike, which matters directly here since ranking depends on ordering the
whole universe consistently. Validated against a real 51-company sample as of 2024-06-28 (Part
7): mean 0.046, range $-0.040$ to $0.200$.

### Quality: return on equity

**Stockholders' equity**, also called book value, is the accounting value of what shareholders
would theoretically have left over if a company sold every asset and paid off every liability: on
the balance sheet, assets minus liabilities. **Return on equity** ("ROE") restates net income as a
fraction of that figure, a measure of how much accounting profit a company generates per dollar
of shareholder capital already invested in it:

$$
\text{quality\_factor} = \frac{\text{net\_income}(\text{as\_of})}{\text{stockholders\_equity}(\text{as\_of})}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{net\_income}(\text{as\_of})$ | Same annual figure used in the value factor | `latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")` |
| $\text{stockholders\_equity}(\text{as\_of})$ | The most recent equity figure known as of the rebalance date; equity describes a balance at an instant, so it takes no period argument | `latest_value_as_of(facts, "stockholders_equity", "USD", as_of)` |

Unlike the size and value factors, a non-positive result here is not filtered out. Negative book
equity is a real, fairly common state, most often produced by a company borrowing to buy back its
own shares faster than it retains earnings, not a data defect, though it does make ROE's sign
harder to read the usual way. Left as raw data for the z-score step's winsorization to handle
rather than guessed at inside the factor itself. Validated against a real 58-company sample (Part
8): standard deviation 0.477, against earnings yield's 0.038 to 0.048 in the same sample, and the
most extreme values (MSCI at $-1.77$, ORLY at $-1.69$, CLX at $1.64$) checked individually as
real, well known low or negative book equity companies rather than a computation error.

**Inherited from the fundamentals loader.** Where a filer stopped reporting the narrower
`StockholdersEquity` tag after a 2009 accounting standard change, `stockholders_equity` falls back
to a broader figure that includes minority interest, overstating equity by a median 3.9 percent
across the companies checked (`src/loaders/README.md`). This factor inherits that gap rather than
correcting it.

**A naming mismatch worth knowing before trusting the label.** In the JKP risk-model taxonomy
this project has adopted (see Risk factors below), ROE is one of two example characteristics
listed under **Profitability**, a distinct theme from **Quality**, which the taxonomy defines as
a composite of profitability, earnings stability, and balance sheet safety. `src/factors/quality.py`
computes ROE alone, and the top level `README.md` is explicit that this currently, more
precisely, matches Profitability's own definition rather than Quality's. The other Profitability
characteristic, gross profits to assets, is now separately built as `gross_profitability_factor`
in `src/factors/profitability.py` (see Fundamentals factors below), under a name that does match
the theme it targets. A genuine multi-component Quality composite is still future work; until it
exists, `quality_factor` remains Profitability wearing Quality's name in the code, now alongside
a second Profitability factor carrying the correct one.

### Momentum: trailing twelve month return, skipping the last month

A **return** is the percentage change in price over some period: buying at 100 and selling at 150
is a 50 percent return. Momentum is the observation, documented since Jegadeesh and Titman (1993),
that stocks which have recently risen tend to keep rising over the following months, and stocks
that have recently fallen tend to keep falling, a pattern that runs opposite to ordinary
mean-reversion intuition and is among the most robust anomalies in the literature.

$$
\text{momentum\_factor} = \frac{P(\text{as\_of} - 1\text{m})}{P(\text{as\_of} - 12\text{m})} - 1
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $P(\text{as\_of} - 1\text{m})$ | The stock's closing price one month before the rebalance date | `close_on_or_before` in `src/loaders/prices.py` |
| $P(\text{as\_of} - 12\text{m})$ | The stock's closing price twelve months before the rebalance date | `close_on_or_before`, same function, an earlier date |

**Why the most recent month is skipped, not an approximation.** Short term reversal, a separate,
still unbuilt factor in the Factor selection table, is the observation that a stock's return over
roughly the last month predicts the opposite direction over the next one, the reverse sign from
momentum's own twelve month pattern. Including the most recent month inside a "twelve month"
momentum window would blend two factors with opposing signs into one noisier number rather than
keeping them as two separate, individually interpretable signals.

**No split-adjustment correction needed, unlike size.** Both prices in the ratio come from the
same ticker's already cached series, adjusted onto the same split basis as each other by
construction, so their ratio is split-and-dividend consistent without any further correction, the
opposite situation from `market_cap_as_of`, which combines a price series with an entirely
separate, unadjusted share count. Validated against a real 57-company sample (Part 9): mean
0.201, range $-0.375$ to $1.368$, matching real 2023 to 2024 market history (NRG, ANET, and
KLAC's semiconductor-led run in the winning tail; FMC, BMY, and ENPH's real underperformance in
the losing tail).

### Low volatility: standard deviation of trailing daily returns

Low volatility is the observation, documented by Ang et al. (2006) and Frazzini and Pedersen
(2014) among others, that stocks whose prices move around less from day to day have historically
delivered better risk-adjusted, and in some samples even better raw, returns than a naive
higher-risk-higher-return intuition would predict:

$$
\text{low\_vol\_factor} = \sigma(r), \qquad
r_t = \frac{P_t}{P_{t-1}} - 1, \qquad t \in \{\text{as\_of} - 252\text{d}, \, \dots, \, \text{as\_of}\}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $r_t$ | The stock's daily return on trading day $t$: the percentage change in closing price from the previous trading day | Computed from the cached close price series in `src/loaders/prices.py` |
| $\sigma(r)$ | The standard deviation of those daily returns over the trailing window | As defined in the standardization section above, applied here to a time series rather than cross sectionally |
| 252 trading days | Roughly one calendar year of trading days, the lookback window used | `lookback_days` argument, default 252 |

252 trading days, not a shorter window, for the same reason as momentum's twelve month lookback:
more observations give a materially less noisy standard deviation estimate. The factor returns
the raw standard deviation, not its negative; which direction to bet, whether low volatility or
high volatility is the attractive end, is a decision left to the alpha model and optimizer, the
same convention `size_factor` follows by returning raw log market cap rather than its negative.
Requires at least half of the lookback window's trading days to actually be present, so a recent
IPO or a name near the start of its cached history does not produce a wildly noisy estimate from a
handful of days; returns `None` below that threshold. Validated against a real 58-company sample
(Part 10): mean 0.0166, range 0.0081 to 0.0388, matching real defensive-versus-growth sector
patterns (RSG, MCD, YUM in the low tail; ANET, AMD, ENPH in the high one).

## Price and volume factors: the remaining weekly horizon themes

Five more factors reuse only the price and volume data already cached by
`src/loaders/prices.py`, no new loader or architecture, per Build order step 4 in the top level
`README.md`. Four of the five, short term reversal, high proximity, volume shock, and
illiquidity, sit in that README's weekly horizon table, since price and volume data carries no
filing lag and can refresh as often as the cadence justifies. Seasonality is a calendar effect
rather than a fast one but is grouped here since it, too, needs nothing beyond cached prices.
Toy validation for all five is Part 3f through 3j of `notebooks/exploring_factors.ipynb`, each
also checked against the shared 60-company real-data panel factored out into
`notebooks/panel.py`.

### Short term reversal: negative of the trailing one week return

Short term reversal is the observation, documented by Jegadeesh (1990) and Lehmann (1990), that
a stock's return over roughly the last week to month predicts the opposite direction over the
following one, the reverse sign from momentum's own twelve month pattern and the reason
momentum's own window skips the most recent month rather than including it.

$$
\text{short\_term\_reversal\_factor} = -\left(\frac{P(\text{as\_of})}{P(\text{as\_of} - 1\text{w})} - 1\right)
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $P(\text{as\_of})$ | The stock's closing price on or before the rebalance date | `close_on_or_before` in `src/loaders/prices.py` |
| $P(\text{as\_of} - 1\text{w})$ | The stock's closing price one week before the rebalance date (one month, via `pd.DateOffset(months=1)`, is also supported, the other window Jegadeesh 1990 documents) | `close_on_or_before`, same function, an earlier date |

The negation is part of the factor's own definition, not a later alpha-direction choice the way
`size_factor` and `low_vol_factor`'s raw, unnegated sign is: a stock that just fell is meant to
score high here, since reversal bets that its next move runs the other way. Well documented in
the literature but strongest among small, illiquid securities and substantially eroded by
transaction costs, so its usefulness within this project's large capitalization universe is a
question for the information coefficient pass in Build order step 6, not assumed to carry over.
Checked against the real panel (Part 3f): the most extreme case, FedEx at $-0.189$, is a
confirmed real event, a roughly 15 percent single day rally after its June 2024 earnings beat,
not a data defect.

### Seasonality: average historical return in the same calendar month

Seasonality is the observation that a stock's return in a given calendar month tends to repeat
across years, plausibly reflecting recurring, calendar-linked flows such as tax loss selling or
sector-specific demand cycles.

$$
\text{seasonality\_factor} = \frac{1}{Y}\sum_{y=1}^{Y}
\left(\frac{P(m_y^{\text{end}})}{P(m_y^{\text{start}})} - 1\right)
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $m_y^{\text{end}}$, $m_y^{\text{start}}$ | The month-end and prior month-end closing prices, $y$ years before the rebalance date, for the same calendar month the rebalance date itself falls in | `close_on_or_before` in `src/loaders/prices.py`, evaluated at each prior year's month end |
| $Y$ | The count of complete prior occurrences of that month actually found, out of up to 40 years searched | Requires at least `min_years` (default 3) before returning a value |

The current, in-progress occurrence of the target month is deliberately excluded: only complete,
month-end-to-month-end returns from strictly earlier years count, since a partial return from the
month currently underway would look ahead into data not yet known as of the rebalance date. Fewer
than `min_years` complete occurrences returns `None` rather than an average of one or two data
points, since a genuinely repeating pattern needs more than that to distinguish it from a single
company-specific event. Checked against a real 56-company sample (Part 3g): mean 0.005, range
$-0.038$ to $0.113$, both tails tapering smoothly with no outlier disconnected from its
neighbors.

### 52 week high proximity: price over its own trailing 252 day maximum

52 week high proximity captures how close a stock's current price sits to its own recent peak,
a characteristic separately documented (alongside momentum itself) to carry predictive power for
future return.

$$
\text{high\_proximity\_factor} = \frac{P(\text{as\_of})}{\max_{t \,\in\, [\text{as\_of} - 252\text{d},\ \text{as\_of}]} P(t)}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $P(\text{as\_of})$ | The stock's closing price on the rebalance date | Cached close price series, `src/loaders/prices.py` |
| $\max_t P(t)$ | The maximum closing price over the trailing 252 trading days, inclusive of `as_of` itself | Same cached series |

A value of 1.0 means today's close is itself the trailing high; values below 1.0 measure how far
the current price sits below it, and a value can never exceed 1.0 by construction. Requires at
least half of the 252 day window's trading days actually present, the same threshold and
reasoning as `low_vol_factor`. Confirmed against the real panel (Part 3h): a minimum of 0.389
(PAYC, matching its real, documented 2023 to 2024 decline), and FedEx sitting exactly at 1.0,
independently confirming the same June 2024 earnings rally that made it the extreme case in the
short term reversal factor above.

### Volume shock: recent volume over trailing average volume

Volume shock measures whether a stock is trading unusually heavily right now relative to its own
recent pattern, a fast-changing signal distinct from the slower price-based factors elsewhere in
this file.

$$
\text{volume\_shock\_factor} = \frac{V(\text{as\_of})}{\overline{V}}, \qquad
\overline{V} = \frac{1}{20}\sum_{t=1}^{20} V(\text{as\_of} - t)
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $V(\text{as\_of})$ | The most recent trading day's volume | Cached volume series, `src/loaders/prices.py` |
| $\overline{V}$ | The average volume over the 20 trading days immediately before, excluding `as_of` itself | Same cached series |

Excluding the most recent day from its own baseline keeps the comparison genuine: today's volume
against a distinct trailing period, not partly compared against itself. Requires at least half of
the 20 day baseline window present, and returns `None` if the baseline average is exactly zero, a
genuinely halted or untraded name where the ratio is undefined rather than infinite. Checked
against the real panel (Part 3i): mean 1.84, systematically above 1.0 across nearly every name,
not a bug but a property of the sample date, 2024-06-28, the Russell US Indexes' annual
reconstitution date, a genuinely elevated-volume day market-wide; a check on an ordinary date
should center closer to 1.0.

### Illiquidity: mean absolute return over dollar volume

Illiquidity (Amihud, 2002) measures how much a given dollar of trading moves a stock's price:
higher values mean less liquid, since the same dollar volume produces a larger price impact.

$$
\text{illiquidity\_factor} = \frac{1}{T}\sum_{t=1}^{T} \frac{|r_t|}{P_t \, V_t}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $r_t$ | The stock's daily return on trading day $t$ | Computed from the cached close price series |
| $P_t V_t$ | Dollar volume on day $t$: closing price times shares traded | Cached close price and volume series |
| $T$ | The trailing window, 20 trading days by default, with any zero-dollar-volume day dropped rather than counted as an infinite ratio | `src/loaders/prices.py` |

Requires at least half of the 20 day window to remain after dropping zero-volume days. Confirmed
against the real panel (Part 3j): the most liquid names (Tesla, Broadcom, Eli Lilly, Costco,
Oracle) are genuine mega caps, and the least liquid (Jack Henry, Synchrony, Rollins, Tapestry,
MarketAxess) are comparatively smaller, matching the well documented inverse relationship between
size and Amihud illiquidity.

## Fundamentals factors: the remaining quarterly horizon themes

Six more factors reuse only the fundamentals data already cached by
`src/loaders/fundamentals.py`, five of them, profitability, profit growth, investment, accruals,
and low leverage, built on `latest_value_as_of`'s `offset` argument exactly as the top level
`README.md` anticipated when the loader was first promoted. Like value and quality above, these
are anchored to reporting periods and cannot refresh faster than companies file, which is why the
top level `README.md` groups them in its quarterly horizon table. Toy validation for all six is
Part 3k through 3p of `notebooks/exploring_factors.ipynb`, each also checked against the shared
60-company real-data panel in `notebooks/panel.py`.

### Profitability: gross profit over total assets

Gross profitability (Novy-Marx, 2013) restates gross profit, revenue minus the direct cost of
producing it, as a fraction of total assets, a distinct construct from `quality.py`'s return on
equity: profitability relative to the asset base a company deploys, rather than relative to its
book equity.

$$
\text{profitability\_factor} = \frac{\text{gross\_profit}(\text{as\_of})}{\text{total\_assets}(\text{as\_of})}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{gross\_profit}(\text{as\_of})$ | The most recent annual gross profit figure known as of the rebalance date, with an automatic revenue-minus-cost-of-revenue fallback for filers that never tag `GrossProfit` directly (e.g. DoorDash) | `latest_value_as_of(facts, "gross_profit", "USD", as_of, period="annual")` |
| $\text{total\_assets}(\text{as\_of})$ | The most recent total assets figure known as of the rebalance date | `latest_value_as_of(facts, "total_assets", "USD", as_of)` |

Unlike `quality.py`'s stockholders' equity, a non-positive total assets figure is filtered here
rather than preserved: a listed company reporting zero or negative total assets is not a real,
common state the way negative book equity is, so it is treated as unresolvable rather than left
for the z-score step to handle. Confirmed against a real 44-company sample (Part 3k): range 0.044
to 0.990. Domino's at the top matches its well known asset-light franchise model; the lower tail
(Globe Life, Nasdaq, Fidelity National Information Services) is dominated by financial services
names carrying large balance sheets relative to a crude gross-profit proxy, a real sector
characteristic rather than a defect.

### Profit growth: change in net income, scaled by total assets

Profit growth measures the year over year change in a company's accounting profit, one of the
JKP taxonomy's own example characteristics for this theme.

$$
\text{profit\_growth\_factor} = \frac{\text{net\_income}_{0} - \text{net\_income}_{-1}}{\text{total\_assets}(\text{as\_of})}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{net\_income}_{0}$ | Net income for the most recently available annual period | `latest_value_as_of(facts, "net_income", "USD", as_of, period="annual", offset=0)` |
| $\text{net\_income}_{-1}$ | Net income for the annual period before that | Same function, `offset=1` |
| $\text{total\_assets}(\text{as\_of})$ | The scaling denominator | `latest_value_as_of(facts, "total_assets", "USD", as_of)` |

Scaled by total assets rather than expressed as a percent change of the prior period's own net
income, deliberately: net income can be zero, negative, or small enough that a percent-change
denominator blows up or flips sign in a way that says nothing about genuine growth, the same
near-zero-denominator concern that shaped `market_cap_as_of` and `quality.py`'s own design. Total
assets is virtually always positive and comparatively stable, a well behaved denominator by
comparison. Confirmed against a real 60-company sample (Part 3l): mean 0.020, median 0.003, most
companies in a tight single-digit-percent-of-assets band. Fidelity National Information Services
sits at the top (0.281) for a genuine reason: its fiscal year 2022 net income was an even larger
loss than fiscal year 2023's, so the loss narrowing year over year is a real positive change, not
a defect.

### Investment: percent change in total assets, year over year

Investment (asset growth) is the observation that companies expanding their asset base quickly
have historically earned lower subsequent returns than companies growing more slowly, plausibly
reflecting overinvestment or overoptimism about growth prospects.

$$
\text{investment\_factor} = \frac{\text{total\_assets}_{0} - \text{total\_assets}_{-1\text{yr}}}{\text{total\_assets}_{-1\text{yr}}}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{total\_assets}_{0}$ | Total assets at the most recent balance sheet date known as of the rebalance date | `latest_value_as_of(facts, "total_assets", "USD", as_of, offset=0)` |
| $\text{total\_assets}_{-1\text{yr}}$ | Total assets roughly one year earlier | Same function, `offset=periods_back` (default 4) |

Total assets is an instant concept reported every quarter, so consecutive offsets step through
consecutive quarters, not years; `periods_back=4` is what reaches roughly a year back for a filer
that tags all four quarters separately, the same reasoning `latest_value_as_of`'s own docstring
gives for its `offset` argument. Expressed as a plain percent change, unlike profit growth above,
since total assets does not carry the near-zero-denominator problem net income does. Confirmed
against a real 60-company sample (Part 3m): Broadcom at the top (1.445) matches its completed
roughly $69 billion VMware acquisition in November 2023; Extra Space Storage (1.265) likely
reflects its 2023 Life Storage merger. Fidelity National Information Services at the bottom
($-0.413$) is a third independent confirmation of the same Worldpay divestiture already found via
`ticker_on` (`notebooks/logs/universe_construction.md`) and the profit growth factor above.

### Accruals: the non-cash component of earnings

Accruals (Sloan, 1996) measures how far reported earnings run ahead of the cash a company
actually generated. A high value is a classic red flag: high-accruals firms have been shown to
subsequently underperform, on average, since the non-cash portion of earnings tends not to
persist the way cash earnings do.

$$
\text{accruals\_factor} = \frac{\text{net\_income}(\text{as\_of}) - \text{operating\_cash\_flow}(\text{as\_of})}{\text{total\_assets}(\text{as\_of})}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{net\_income}(\text{as\_of})$ | Same annual figure used in the value and profit growth factors | `latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")` |
| $\text{operating\_cash\_flow}(\text{as\_of})$ | The most recent annual operating cash flow figure known as of the rebalance date | `latest_value_as_of(facts, "operating_cash_flow", "USD", as_of, period="annual")` |
| $\text{total\_assets}(\text{as\_of})$ | The scaling denominator, the same convention used throughout the fundamentals-based factors above | `latest_value_as_of(facts, "total_assets", "USD", as_of)` |

Confirmed against a real 60-company sample (Part 3n): mostly negative (median $-0.031$), as
expected, since operating cash flow typically exceeds net income for healthy companies. Fidelity
National Information Services sits at one extreme ($-0.306$) for a fourth independently confirmed
reason touching its fiscal year 2023 situation: a large net loss driven mostly by a non-cash
goodwill impairment, so operating cash flow barely moved by comparison. Emerson Electric sits at
the opposite extreme (0.271), reflecting a real, one-time gain on its 2023 sale of its Climate
Technologies business, which inflated net income without a matching operating cash inflow.

### Low leverage: total debt over stockholders' equity

Low leverage measures how much debt a company carries relative to its book equity. The theme is
named for the direction associated with the historical premium, lower leverage earning better
risk-adjusted returns, but the factor itself returns the plain, unnegated ratio, the same
convention `low_vol_factor` follows: which direction to bet is left to the alpha model and
optimizer.

$$
\text{leverage\_factor} = \frac{\text{total\_debt}(\text{as\_of})}{\text{stockholders\_equity}(\text{as\_of})}, \qquad
\text{total\_debt} = \text{debt}_{\text{noncurrent}} + \text{debt}_{\text{current}}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{debt}_{\text{noncurrent}}$ | Long term debt due beyond one year | `latest_value_as_of(facts, "long_term_debt_noncurrent", "USD", as_of)` |
| $\text{debt}_{\text{current}}$ | The portion of long term debt due within one year | `latest_value_as_of(facts, "long_term_debt_current", "USD", as_of)` |
| $\text{stockholders\_equity}(\text{as\_of})$ | Same figure used in the quality factor above | `latest_value_as_of(facts, "stockholders_equity", "USD", as_of)` |

Missing $\text{debt}_{\text{current}}$ specifically is treated as zero rather than as missing
data, since `src/loaders/README.md` already established this concept is frequently and
legitimately zero and often left untagged once it is; missing $\text{debt}_{\text{noncurrent}}$ is
treated the same way for symmetry, though it is a much rarer case in practice. A company is
unresolvable here only if neither debt concept exists at all. As with `quality.py`'s equity, a
non-positive value is not filtered out, since negative book equity from leveraged buybacks is
real, common data, not an error; equity of exactly zero is the one case still guarded against, to
avoid a division by zero rather than a meaningful ratio. Confirmed against a real 60-company
sample (Part 3o): Altria and Domino's showing negative leverage matches their well documented
negative book equity from years of buybacks. Iron Mountain sits at the extreme (685.6), a real
figure too, only 18.5 million dollars in stockholders' equity against 12.7 billion dollars in
total debt, a genuine, thin-equity characteristic of REIT accounting, since REITs distribute most
taxable income as dividends, depleting retained earnings toward zero even for healthy companies,
exactly the kind of case winsorization exists to handle downstream.

### Debt issuance (proxy): percent change in total debt, year over year

Debt issuance measures how much new debt financing a company has raised. The literature's precise
definition (Bradshaw, Richardson, and Sloan, 2006) nets cash-flow-statement proceeds from debt
issuance against repayments during the period, capturing actual financing activity directly. This
project builds a proxy instead: the year over year change in the debt balance outstanding, the
same total debt figure used in the low leverage factor above.

$$
\text{debt\_issuance\_factor} = \frac{\text{total\_debt}_{0} - \text{total\_debt}_{-1\text{yr}}}{\text{total\_debt}_{-1\text{yr}}}
$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| $\text{total\_debt}_{0}$ | Total debt (noncurrent plus current) at the most recent balance sheet date known as of the rebalance date | Same two `latest_value_as_of` calls as `leverage_factor`, `offset=0` |
| $\text{total\_debt}_{-1\text{yr}}$ | Total debt roughly one year earlier | Same calls, `offset=periods_back` (default 4), the same mechanism `investment_factor` uses |

A balance-based proxy differs from the precise definition in ways worth naming rather than
glossing over: the balance can move for reasons unrelated to issuance (foreign exchange
translation on debt held abroad, fair value remeasurement, a noncurrent tranche reclassified to
current, or a lease accounting standard change folding new leases into the long term debt tags),
and it entirely misses a same-period issuance-and-repayment refinancing, since that leaves the
balance unchanged. Built as a proxy deliberately: per the top level `README.md`'s build order
reasoning, whether this imprecision matters enough to justify the further loader work a precise
version needs is a question for the step 6 information coefficient pass, not something to guess
at before any measurement exists. Confirmed against a real 60-company sample (Part 3p): Oracle at
the top of the observed range matches its well documented 2024 bond issuance funding Oracle Cloud
Infrastructure data center buildout for AI workloads; F5 at exactly $-1.0$ is a clean full debt
payoff. The spread (standard deviation 0.83) is much wider than the investment factor's (0.29) on
the same sample, a real property of a balance-based proxy rather than noise to explain away: a
company paying off all its debt registers a clean $-100$ percent, while a small existing balance
plus a large new raise can swing well past $300$ percent.

## Risk factors: the same kind of computation, a different question

Every factor above was built to answer one question: does this characteristic predict which
stocks outperform. That is an **alpha factor** question. The top level `README.md`'s Risk model
versus alpha model section draws out a separate question a quant system also has to answer for
every characteristic it tracks: does this characteristic explain how stocks move together,
regardless of whether it predicts outperformance at all. That second question is what a **risk
factor** is for, and answering it is what a **factor covariance matrix** is built from
(`src/risk_model/factor_covariance.py`), a system not yet built in this project and out of scope
for this file; see the top level `README.md` for the full theory.

The two questions are independent. This project's adopted risk taxonomy is the 13 themes
identified by Jensen, Kelly, and Pedersen (2023, "Is There a Replication Crisis in Finance?",
Journal of Finance), who study 153 factors across 93 countries and find that they cluster into
these 13 by covariance, exactly the property a risk model needs. Reproduced here in full, since
it is the reference this project actually builds against, alongside which built factor, if any,
already matches a theme:

| JKP theme | Example characteristic | Primary data | Buildable with current loaders | Factor built in `src/factors/` |
|---|---|---|---|---|
| Momentum | 12 month return, skipping the last month | Daily prices | Yes | `momentum_factor` |
| Short term reversal | Negative of last month return | Daily prices | Yes | `short_term_reversal_factor` |
| Low risk | Volatility, beta, idiosyncratic volatility | Daily prices | Yes | `low_vol_factor`, the volatility piece only; beta and idiosyncratic volatility are not built |
| Seasonality | Same calendar month historical return | Daily prices | Yes | `seasonality_factor` |
| Size | Log market capitalization | Price and shares outstanding | Yes | `size_factor` |
| Value | Book, earnings, cash flow, or sales to price | Fundamentals | Yes | `value_factor`, the earnings-to-price version only; book, cash flow, and sales variants are not built |
| Profitability | Gross profits to assets, return on equity | Fundamentals | Yes | `gross_profitability_factor` (`profitability.py`), the gross-profits-to-assets version, plus `quality_factor` (`quality.py`), which computes the return-on-equity version under a name that, per the naming mismatch noted above, more precisely matches this theme than the one it carries |
| Quality | Composite of profitability, stability, safety | Fundamentals | Yes, every ingredient is cached; not yet assembled into one composite | Not yet |
| Profit growth | Change in earnings or profitability | Fundamentals | Yes, via `latest_value_as_of`'s `offset` argument | `profit_growth_factor` |
| Investment | Asset growth | Fundamentals | Yes, via `offset` on `total_assets`, the same mechanism as profit growth | `investment_factor` |
| Accruals | Non-cash component of earnings | Fundamentals | Yes, from `net_income`, `operating_cash_flow`, and `total_assets`, all cached | `accruals_factor` |
| Debt issuance | Net debt issuance | Fundamentals | Partial: a debt-level-change proxy is buildable from the cached debt tags; the literal financing-cash-flow figure needs a new tag alias | `debt_issuance_factor`, the balance-change proxy; the literal financing-cash-flow definition is not built |
| Low leverage | Debt to equity, book leverage | Fundamentals | Yes | `leverage_factor` |

12 of the 13 themes now have at least one dedicated factor; Quality remains the one unassembled
composite, and Debt issuance's dedicated factor is a proxy rather than the literature's precise
definition, both discussed in their own sections above.

A complete risk model also needs a market factor, industry factors (GICS, currently detached from
the universe tables, see `notebooks/logs/universe_construction.md`'s open items), and a per-stock
specific-risk term, none of which are themes in the table above and none of which are built.

Building a factor in `src/factors/` does not, by itself, add it to the risk model. Including a
theme in the risk model means only "we want to know our exposure to this"; whether that exposure
is then driven to zero (neutralized), held on purpose (bet on), or taken negative is decided later
in the optimizer using the alpha model, not automatically inherited from the factor existing. The
same characteristic can serve both roles at once, exactly as `value_factor` does here: value is
used as an alpha bet above, and the same computation is also a candidate risk-model input, because
value explains common return covariation independently of whether it currently pays a premium.

## Novel alpha candidates: a separate, unproven category

The top level `README.md`'s Novel alpha candidates section curates four proprietary signals, kept
deliberately apart from the five foundational factors above because they are held to a different
evidentiary bar. The foundational five are each backed by decades of published, widely replicated
research; the four candidates below come from a smaller number of individual papers, several with
documented decay since original publication, and are treated as reasons to test on this project's
own universe rather than as expected, ready-to-trust signals.

| Signal | Idea | Horizon |
|---|---|---|
| Lazy Prices | Year over year textual similarity of a firm's 10-K/10-Q; firms that materially change disclosure language underperform | Months |
| Opportunistic insiders | Net insider buying restricted to insiders whose trades are irregular, information driven, rather than calendar routine | Weeks to months |
| PEAD / SUE | Standardized unexpected earnings drives continued post-earnings drift, using a seasonal random walk for expected earnings rather than analyst estimates | 60 to 90 days |
| Wikipedia attention | Retail attention, measured by page view spikes, predicts returns in a contrarian direction: heavily attended names underperform | Days |

None of the four is built. Full detail, including each candidate's data source, loader status,
and reported original-sample magnitudes, is in the top level `README.md`. This project's factor
zoo discipline applies to these with extra weight precisely because they are novel: each is judged
on marginal information coefficient after orthogonalizing against the five factors above, not
taken on faith from the originating paper's own reported result.
