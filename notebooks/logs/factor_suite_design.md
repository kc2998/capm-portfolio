# Factor suite design: risk model, alpha model, and the factor universe

A design brief, written to align on the shape of the factor suite before the loaders are
rebuilt to support it. This file records the reasoning; concrete factor definitions and the
loader specifications follow once we agree on the structure here.

Dated 2026-07-31. Audience: both maintainers.

## Purpose

We are about to move from the universe and price loaders into factor computation. Before
building factors piecemeal, this note settles three questions that determine how `scoring/`
and `risk_model/` should be structured:

1. What is the difference between a risk factor and an alpha factor in this system, and why
   does it matter for the code.
2. How the 13 factor themes from Jensen, Kelly, and Pedersen (2023) fit in.
3. Which novel signals are worth curating as proprietary alpha, and what data each requires.

The conclusion is a target architecture and a data-dependency map that motivates the next
round of loader work.

## The central distinction: risk model versus alpha model

A quant equity system maintains two factor sets that serve opposite purposes. Conflating them
is the most common structural error, so this section is deliberate.

**Risk factors** describe common covariance. Their job is to let us measure a portfolio's
exposure to a shared source of return variation, and to forecast portfolio risk. Standard
risk factors are market, size, value, momentum, volatility, liquidity, plus industry and a
specific (idiosyncratic) risk term per stock.

**Alpha factors** are the return predictors we bet on: the signals we believe forecast
future return and that are not already captured elsewhere.

### Inclusion in the risk model is not neutralization

The key realization is that putting a factor in the risk model and hedging that factor to
zero are two separate decisions.

Including a factor in the risk model means "I want to know my exposure to this." It says
nothing about what that exposure should be. Whether we drive the exposure to zero
(neutralize) or hold it deliberately (bet) is decided in the optimizer, using the alpha
model, not in the risk model.

The same characteristic can therefore appear in both roles. A risk model includes a value
factor because value explains common return covariation; a value investor still holds
positive value exposure on purpose. The risk model measures it, the alpha model wants it, the
optimizer takes it knowingly rather than by accident.

### Exposure is the lever, and it runs both directions

For any factor, the target exposure can be:

- **Positive**, when we have a view that it still pays. We are betting on it. It functions as
  alpha.
- **Zero**, when we have no view. We neutralize it so it neither helps nor hurts, and return
  comes from elsewhere. It functions purely as risk control.
- **Negative**, occasionally, when we believe it is currently a headwind.

The risk model is what lets us set that number precisely rather than discover the exposure
after the fact. Without it, we might believe we are betting on a novel insider signal while a
third of our return variance quietly comes from an unintended small-cap, high-volatility tilt.
Stated compactly: the risk model does not tell us what to bet on; it ensures the only bets we
carry are the ones we chose.

### Why thoroughly studied factors remain useful

"Well studied" and "useful" answer different questions.

Whether a factor's *premium still pays* is the alpha question. For the classic themes the
honest answer is "less than it once did," because publication and crowding erode premia.

Whether a factor is useful *as a risk control* depends only on whether it still explains
common covariance, meaning whether stocks that load on it still move together. That is far
more durable, because the co-movement comes from shared economic exposure rather than from a
mispricing that arbitrage competes away. Value stocks still rise and fall together as a group
whether or not value earns a premium. A factor can be dead as alpha and indispensable as a
risk axis. This is precisely why the well-studied themes remain worth modeling.

## The JKP 13 themes as the risk-model taxonomy

Jensen, Kelly, and Pedersen, "Is There a Replication Crisis in Finance?", Journal of Finance
2023, study 153 factors across 93 countries and reach two conclusions relevant to us. The
majority of factors replicate and work out of sample, and, more useful for design, they
cluster into 13 themes. The clustering is derived from factors that covary, which is exactly
the property a risk model needs, so the themes are natural risk-model axes.

The 13 themes, with a representative characteristic and the data each primarily requires:

| Theme | Example characteristic | Primary data | Buildable with current loaders |
|---|---|---|---|
| Momentum | 12 month return, skipping the last month | Daily prices | Yes |
| Short-term reversal | Negative of last month return | Daily prices | Yes |
| Low risk | Volatility, beta, idiosyncratic volatility | Daily prices | Yes |
| Seasonality | Same-calendar-month historical return | Daily prices | Yes |
| Size | Log market capitalization | Price and shares outstanding | Partial: needs shares outstanding |
| Value | Book, earnings, cash flow, or sales to price | Fundamentals | No: needs fundamentals loader |
| Profitability | Gross profits to assets, return on equity | Fundamentals | No |
| Quality | Composite of profitability, stability, safety | Fundamentals | No |
| Profit growth | Change in earnings or profitability | Fundamentals | No |
| Investment | Asset growth | Fundamentals | No |
| Accruals | Non-cash component of earnings | Fundamentals | No |
| Debt issuance | Net debt issuance | Fundamentals | No |
| Low leverage | Debt to equity, book leverage | Fundamentals | No |

The style themes above are the style block of the risk model. A complete risk model also
needs a market factor, industry factors (GICS), and a per-stock specific-risk term. Note that
GICS sector was dropped when the universe was promoted into `src/`; it exists in the cached
snapshots but not in `universe_spans` or `ticker_history`, and it will need to be re-attached
to support industry factors and sector-neutral scoring. See the universe log's open items.

Eight of the 13 themes are fundamentals-based. A full 13-theme risk model is therefore gated
on the EDGAR fundamentals loader and on shares outstanding. Only five themes are buildable
from the price and volume data available today.

## Chen and Zimmermann as the definitional reference

The Open Source Asset Pricing project (Chen and Zimmermann, Critical Finance Review 2022)
publishes open Python code that constructs roughly 300 published signals, and documents their
replication: for the 161 characteristics clearly significant in the original papers, 98
percent reproduce with t-stats above 1.96. The underlying stock data is CRSP and Compustat,
which is licensed and cannot be redistributed, so the value to us is as a recipe book. We can
read the exact definition of any classic factor, formula and edge cases included, and
reimplement it on our own free data, then check our result against their documented t-stats.
We cannot ship their computed values.

## The factor-zoo discipline

The replication literature carries a warning to build in from the start. After correcting for
multiple testing at a t-stat hurdle near 2.78 (Harvey, Liu, and Zhu), roughly 80 percent of
published anomalies become insignificant. Machine-learning factor-zoo work reaches the same
place: strip redundancy and only a handful of independent dimensions remain, essentially
market, value, momentum, reversal, and a risk or quality axis. The lesson is not that most
factors are fake, but that the honest prior is skepticism and the survivors cluster. Every
candidate is judged on marginal information coefficient after orthogonalizing against the
existing suite and the risk factors, and on an honest count of how many ideas were tried. Most
candidates should die at the screen.

## Novel alpha candidates

These are the proprietary signals worth curating, chosen because they are buildable from free,
scrapeable data and are documented to have low correlation with the standard themes. Reported
magnitudes come from the original samples, mostly predate 2020, and several show documented
decay. Treat them as reasons to test, not as expected returns; the information coefficient on
our own universe is the arbiter.

| Signal | Idea | Reported effect | Data source | Horizon | Loader status |
|---|---|---|---|---|---|
| Lazy Prices | Year-over-year textual similarity of a firm's 10-K / 10-Q; firms that materially change disclosure language underperform | Up to 188 bps per month, low correlation to market, value, size, momentum, investment, profitability | EDGAR filing text | Months (slow) | Reuses existing filing-fetch machinery |
| Opportunistic insiders | Net insider buying restricted to insiders whose trades are irregular (information-driven), not calendar-routine | ~82 bps per month for opportunistic; ~0 for routine | EDGAR Form 4 | Weeks to months | Needs Form 4 loader |
| PEAD / SUE | Standardized unexpected earnings drives continued drift; expected earnings from a seasonal random walk, no analyst estimates needed | Robust historically, decayed in large caps | EDGAR fundamentals plus earnings dates | ~60 to 90 days | Needs fundamentals loader |
| Wikipedia attention | Retail attention (page-view spikes) predicts returns, contrarian: heavily attended names underperform | Modest, orthogonal to price and accounting factors | Wikimedia page-view REST API (free, clean) | Days (fast) | Needs a small new loader |

Three of the four are filing- or event-driven and play out over months, so they sit in the
same slow sleeve as the fundamental factors and align with a monthly rebalance. Wikipedia
attention is the exception, a fast contrarian signal belonging in the price and volume sleeve.

Two of these refine, rather than add to, plans already in the README. The insider factor
should be the opportunistic-only version from the start, not the naive sum of net buying,
since the routine trades carry essentially no alpha and only add noise. Lazy Prices is
reachable soonest because `src/universe/point_in_time.py` already fetches EDGAR filing text
(`fetch_filing_text`, `get_filing_history`) for ticker verification.

## Horizon and sleeves

Consistent with the rebalance-frequency decision in the README, factors are grouped by the
frequency at which their information genuinely refreshes, and combined by a single optimizer.

- **Fast sleeve** (price and volume, weekly horizon): short-term reversal, 52-week high, MAX,
  illiquidity, volume shock, Wikipedia attention.
- **Slow sleeve** (fundamentals and filings, monthly to quarterly horizon): the fundamental
  themes, Lazy Prices, opportunistic insiders, PEAD.

The risk model's covariance is estimated over a window matched to the holding period, and the
neutralization regression is refit at every rebalance, never fit once and reused.

## Target architecture, in one picture

- **Risk model**: the 13 JKP themes as the style block, plus market, industry (GICS), and
  specific risk. Purpose is exposure measurement and risk forecasting, not a set of bets.
- **Alpha model**: a deliberate subset of the themes we have conviction on, plus the curated
  novel signals. Each factor carries an explicit risk-versus-alpha role in config; new factors
  default to alpha, and a factor is moved to risk-only when we conclude we have no edge on it.
- **Optimizer**: takes exposure where the alpha model justifies it, neutralizes the themes we
  have no view on, and reconciles the fast and slow sleeves through a transaction cost term so
  that trading frequency follows from the economics.

Neutralization is a decision to forgo a premium, made deliberately per factor, not a blanket
default applied to all 13 themes.

## Data-dependency map and loader implications

This is the section that motivates the next round of loader work. Grouped by what each
capability requires.

**Available now** (universe plus price loaders): the five price-based themes (momentum,
short-term reversal, low risk, seasonality, partial size), the fast-sleeve price and volume
factors, and Lazy Prices via the existing filing-text fetch.

**Requires the EDGAR fundamentals loader** (XBRL, point-in-time on filing date): eight of the
13 themes (value, profitability, quality, profit growth, investment, accruals, debt issuance,
low leverage), plus PEAD / SUE, plus shares outstanding, which also completes the size factor
and enables market capitalization for weighting.

**Requires the Form 4 loader**: the opportunistic-insider factor, including the routine-versus-
opportunistic classification, which needs a per-insider trading-history window.

**Requires a small new loader**: Wikipedia page views for the attention factor.

**Requires re-attaching GICS sector** to the universe tables (present in cached snapshots,
dropped from the promoted tables): industry risk factors and sector-neutral scoring.

**Deferred**: FINRA short interest, FRED risk-free rate, and the wave-two text sources
(earnings-call transcripts, social sentiment).

## What we need to agree on before building

1. That the 13 themes are adopted as the target risk-model taxonomy, understanding the risk
   model itself is a later build-order step once fundamentals exist.
2. That risk-versus-alpha is an explicit per-factor role in config, not a blanket assignment.
3. That the EDGAR fundamentals loader is the pivotal next data-engineering task, because it
   unlocks eight themes, PEAD, and market capitalization at once.
4. That the insider factor is built in its opportunistic-only form from the start.
5. That the factor-computation interface is fixed before the first factor: a factor is a
   function returning one raw value per universe member on a date, indexed by the stable
   entity (CIK), with z-scoring, missing-data handling, and neutralization living in
   `scoring/`, never inside a factor.

## References

- Jensen, Kelly, Pedersen (2023), "Is There a Replication Crisis in Finance?", Journal of
  Finance. https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249 and the Global Factor
  Data portal https://jkpfactors.com/ (cluster diagram at https://jkpfactors.com/graph)
- Chen, Zimmermann (2022), "Open Source Cross-Sectional Asset Pricing", Critical Finance
  Review. https://github.com/OpenSourceAP/CrossSection and https://www.openassetpricing.com/
- Cohen, Malloy, Nguyen (2020), "Lazy Prices", NBER w25084.
  https://www.nber.org/system/files/working_papers/w25084/w25084.pdf
- Cohen, Malloy, Pomorski (2012), "Decoding Inside Information", NBER w16454.
  https://www.nber.org/system/files/working_papers/w16454/w16454.pdf
- "PEAD.txt: Post-Earnings-Announcement Drift Using Text", San Francisco Fed 2024.
  https://www.frbsf.org/research-and-insights/publications/system-research-philadelphia-fed/2024/05/pead-txt-post-earnings-announcement-drift-using-text/
- Harvey, Liu, Zhu (2016), "... and the Cross-Section of Expected Returns", on multiple-testing
  hurdles. Context in "Exploring the factor zoo with a machine-learning portfolio",
  https://www.sciencedirect.com/science/article/abs/pii/S1057521924005313
