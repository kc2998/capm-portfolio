"""Backtest metrics: information coefficient, turnover, portfolio return, drawdown.

Built and validated in notebooks/exploring_backtest.ipynb, Part 7 and Part 8.
"""

import pandas as pd

COST_BPS = 10  # basis points per unit of turnover, a crude placeholder per the README


def turnover(w_prev, w_curr):
    """Sum of absolute weight change across the union of tickers in either
    date, missing treated as 0. Not netted down to a one-way figure, since
    being conservative about cost is the safer direction for a first pass.
    """
    aligned = pd.concat([w_prev, w_curr], axis=1, keys=["prev", "curr"]).fillna(0.0)
    return (aligned["curr"] - aligned["prev"]).abs().sum()


def missing_forward_return_positions(weights, forward_returns):
    """Held positions (nonzero weight) with no measurable forward_return.

    Surfaces rather than silently absorbs the same failure mode the price
    loader's own coverage report already measures for delisted names:
    dropping these silently would reintroduce survivorship bias at the
    return layer after it was already removed at the universe layer.
    """
    held = weights[weights != 0].index
    return [cik for cik in held if pd.isna(forward_returns.get(cik))]


def information_coefficient(panel_results):
    """Cross sectional correlation between factor_score and forward_return,
    one value per date that has a forward_return column (every date but the
    last one run_backtest produced).
    """
    ic_by_date = {}
    for d, df in panel_results.items():
        if "forward_return" not in df.columns:
            continue
        valid = df[["factor_score", "forward_return"]].dropna()
        ic_by_date[d] = valid["factor_score"].corr(valid["forward_return"])
    return pd.Series(ic_by_date)


def portfolio_return(weights, forward_returns, prior_weights=None, cost_bps=COST_BPS):
    """One date's (net, gross, cost) return for a quantile bucket portfolio.

    cost is 0.0 when prior_weights is None: the first date in a backtest has
    no prior rebalance to measure turnover against.
    """
    aligned = pd.concat([weights, forward_returns], axis=1, keys=["weight", "return"]).dropna()
    gross = (aligned["weight"] * aligned["return"]).sum()
    cost = turnover(prior_weights, weights) * cost_bps / 10000 if prior_weights is not None else 0.0
    return gross - cost, gross, cost


def backtest_returns(panel_results, portfolio_weights, cost_bps=COST_BPS):
    """Gross, cost, and net return per date across a full run_backtest result."""
    dates_sorted = sorted(panel_results)
    prior_w = None
    returns = {}
    for d in dates_sorted:
        df = panel_results[d]
        if "forward_return" not in df.columns:
            continue
        net, gross, cost = portfolio_return(
            portfolio_weights[d], df["forward_return"], prior_weights=prior_w, cost_bps=cost_bps
        )
        returns[d] = {"gross": gross, "cost": cost, "net": net}
        prior_w = portfolio_weights[d]
    return pd.DataFrame(returns).T


def max_drawdown(net_returns):
    """Largest peak to trough decline in cumulative (1 + net_returns).cumprod()."""
    cumulative = (1 + net_returns).cumprod()
    drawdown = cumulative / cumulative.cummax() - 1
    return drawdown.min()
