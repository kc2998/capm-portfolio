"""Walk forward backtest loop: per-date factor computation and portfolio construction.

Built and validated in notebooks/exploring_backtest.ipynb.
"""

import pandas as pd

from src.universe.point_in_time import ticker_on, ciks_on
from src.loaders.fundamentals import load_company_facts
from src.loaders.prices import load_cik_prices, next_open_after
from src.risk_model.beta import beta_as_of
from src.scoring.zscore import zscore
from src.scoring.combine import combine
from src.scoring.neutralize import neutralize
from src.factors.size import market_cap_as_of, size_factor
from src.factors.value import earnings_yield_factor
from src.factors.quality import roe_factor
from src.factors.momentum import momentum_factor
from src.factors.low_vol import low_vol_factor
from src.factors.short_term_reversal import short_term_reversal_factor
from src.factors.seasonality import seasonality_factor
from src.factors.high_proximity import high_proximity_factor
from src.factors.volume_shock import volume_shock_factor
from src.factors.illiquidity import illiquidity_factor
from src.factors.profitability import gross_profitability_factor
from src.factors.profit_growth import profit_growth_factor
from src.factors.investment import investment_factor
from src.factors.accruals import accruals_factor
from src.factors.leverage import leverage_factor
from src.factors.debt_issuance import debt_issuance_factor


# ---------------------------------------------------------------------------
# Factor registry: every factor takes the same (facts, prices, ticker, as_of)
# shape here, even though the underlying factor functions don't, so that
# compute_row can loop over this dict instead of hardcoding one line per
# factor. Adding a new factor means adding one line below, not editing
# compute_row.
# ---------------------------------------------------------------------------

def _facts_only(fn):
    """Adapt a factor that only needs facts (e.g. roe_factor, accruals_factor)."""
    def wrapped(facts, prices, ticker, as_of):
        return fn(facts, as_of) if facts is not None else None
    return wrapped


def _prices_only(fn):
    """Adapt a factor that only needs prices and a resolved ticker."""
    def wrapped(facts, prices, ticker, as_of):
        return fn(prices, ticker, as_of) if prices is not None and ticker is not None else None
    return wrapped


def _facts_and_prices(fn):
    """Adapt a factor that needs both facts and prices (e.g. earnings_yield_factor)."""
    def wrapped(facts, prices, ticker, as_of):
        return fn(facts, prices, ticker, as_of) if facts is not None and prices is not None and ticker is not None else None
    return wrapped


def _size(facts, prices, ticker, as_of):
    if facts is None or prices is None or ticker is None:
        return None
    return size_factor(market_cap_as_of(facts, prices, ticker, as_of))


FACTOR_REGISTRY = {
    "size": _size,
    "value": _facts_and_prices(earnings_yield_factor),
    "quality": _facts_only(roe_factor),
    "momentum": _prices_only(momentum_factor),
    "low_vol": _prices_only(low_vol_factor),
    "short_term_reversal": _prices_only(short_term_reversal_factor),
    "seasonality": _prices_only(seasonality_factor),
    "high_proximity": _prices_only(high_proximity_factor),
    "volume_shock": _prices_only(volume_shock_factor),
    "illiquidity": _prices_only(illiquidity_factor),
    "profitability": _facts_only(gross_profitability_factor),
    "profit_growth": _facts_only(profit_growth_factor),
    "investment": _facts_only(investment_factor),
    "accruals": _facts_only(accruals_factor),
    "leverage": _facts_only(leverage_factor),
    "debt_issuance": _facts_only(debt_issuance_factor),
}


def compute_row(cik, as_of, ticker_history, market_prices):
    """Every raw factor plus beta for one CIK on one date.

    beta is computed separately from FACTOR_REGISTRY rather than folded into
    it: it needs market_prices, an external series none of the other
    factors touch, so it doesn't fit the registry's (facts, prices, ticker,
    as_of) shape without forcing it.
    """
    facts = load_company_facts(cik)
    ticker = ticker_on(ticker_history, cik, as_of)
    prices = load_cik_prices(cik)

    row = {"cik": cik, "ticker": ticker}
    for name, factor_fn in FACTOR_REGISTRY.items():
        row[name] = factor_fn(facts, prices, ticker, as_of)
    row["beta"] = beta_as_of(prices, ticker, market_prices, as_of) if prices is not None and ticker is not None else None
    return row


def run_rebalance(as_of, ciks, weights, ticker_history, market_prices):
    """One date's full scoring pipeline: raw factors, z-scored, combined,
    neutralized against beta, for every cik in ciks.
    """
    raw = pd.DataFrame(
        [compute_row(cik, as_of, ticker_history, market_prices) for cik in ciks]
    ).set_index("cik")
    factor_cols = [c for c in raw.columns if c not in ("ticker", "beta")]
    zscored = raw[factor_cols].apply(zscore)
    combined_score = combine(zscored, weights)
    factor_score = neutralize(combined_score, raw["beta"])
    return pd.DataFrame({
        "ticker": raw["ticker"], "combined_score": combined_score,
        "beta": raw["beta"], "factor_score": factor_score,
    })


def quantile_weights(df, score_col="factor_score", quantile=0.2):
    """Long the top quantile of score_col, short the bottom quantile, equal
    weighted within each side. Dollar neutral by construction: long weights
    sum to 1.0, short weights sum to -1.0.
    """
    scores = df[score_col].dropna()
    n_bucket = max(1, int(len(scores) * quantile))
    ranked = scores.sort_values(ascending=False)
    longs = ranked.index[:n_bucket]
    shorts = ranked.index[-n_bucket:]

    weights = pd.Series(0.0, index=df.index)
    weights[longs] = 1.0 / n_bucket
    weights[shorts] = -1.0 / n_bucket
    return weights


def forward_return(prices, ticker, start, end):
    """A stock's return from the session after start to the session after
    end, per the README's no-lookahead execution timing rule.
    """
    entry = next_open_after(prices, ticker, start)
    exit = next_open_after(prices, ticker, end)
    if entry is None or exit is None:
        return None
    return exit / entry - 1


def add_forward_returns(result, as_of, next_date):
    """Attach each held stock's forward_return from as_of to next_date."""
    rets = {}
    for cik, row in result.iterrows():
        prices = load_cik_prices(cik)
        if prices is None or row["ticker"] is None:
            continue
        rets[cik] = forward_return(prices, row["ticker"], as_of, next_date)
    result = result.copy()
    result["forward_return"] = pd.Series(rets)
    return result


def run_backtest(dates, universe_spans, ticker_history, market_prices, weights):
    """The walk forward loop: run_rebalance and quantile_weights at every
    date, with forward_return attached to every date but the last (nothing
    to compare it against yet).

    dates: a DatetimeIndex, e.g. pd.date_range(start, end, freq=rebalance_freq).
    Returns (panel_results, portfolio_weights), both dicts keyed by the same
    "YYYY-MM-DD" date strings used throughout this pipeline.
    """
    dates_str = [d.strftime("%Y-%m-%d") for d in dates]

    panel_results = {}
    for d in dates_str:
        ciks = ciks_on(universe_spans, d)
        panel_results[d] = run_rebalance(d, ciks, weights, ticker_history, market_prices)

    for prev_d, curr_d in zip(dates_str, dates_str[1:]):
        panel_results[prev_d] = add_forward_returns(panel_results[prev_d], prev_d, curr_d)

    portfolio_weights = {d: quantile_weights(df) for d, df in panel_results.items()}

    return panel_results, portfolio_weights
