"""Profit growth factor: change in net income over total assets.

Built and validated in notebooks/exploring_factors.ipynb, Part 3l.
"""

from src.loaders.fundamentals import latest_value_as_of


def profit_growth_factor(facts, as_of):
    """Raw profit growth factor: change in net income between the two most
    recently available annual periods, scaled by total assets.

    Scaled by total assets rather than expressed as a percent change of
    the prior period's own net income, deliberately: net income can be
    zero, negative, or small enough that a percent-change denominator
    blows up or flips sign in a way that says nothing about genuine
    growth, the same near-zero-denominator concern that shaped
    market_cap_as_of and quality.py's design. Total assets is virtually
    always positive and comparatively stable, a well behaved denominator.

    Uses latest_value_as_of's offset argument (offset=0 for the most
    recent annual period, offset=1 for the one before it), the exact
    mechanism the fundamentals loader already built and tested for this
    purpose.

    Confirmed against a real 60-company sample (Part 3l): mean 0.020,
    median 0.003, most companies in a tight single-digit-percent-of-assets
    band. FIS at the top (0.281) is real, not a defect: its FY2022 net
    income was an even larger loss (-$16.72B) than FY2023's (-$6.654B,
    already confirmed in universe_construction.md's ticker_on finding),
    so the loss narrowing year over year is a genuine positive change.

    Returns None if either net income figure or total assets cannot be
    resolved, or if total assets is non-positive.
    """
    current = latest_value_as_of(facts, "net_income", "USD", as_of, period="annual", offset=0)
    prior = latest_value_as_of(facts, "net_income", "USD", as_of, period="annual", offset=1)
    if current is None or prior is None:
        return None
    assets = latest_value_as_of(facts, "total_assets", "USD", as_of)
    if assets is None or assets[0] <= 0:
        return None
    return (current[0] - prior[0]) / assets[0]
