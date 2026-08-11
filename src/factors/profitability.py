"""Profitability factor: gross profit over total assets (Novy-Marx 2013).

Built and validated in notebooks/exploring_factors.ipynb, Part 3k.
"""

from src.loaders.fundamentals import latest_value_as_of


def gross_profitability_factor(facts, as_of):
    """Raw profitability factor: gross profit over total assets (Novy-Marx
    2013's gross profitability premium), distinct from quality.py's
    return on equity: a different construct, profitability relative to
    the asset base a company deploys, not relative to its book equity.

    gross_profit resolves via its own revenue-minus-cost-of-revenue
    fallback for filers that never tag GrossProfit directly (e.g.
    DoorDash), automatically, the same DERIVED_FALLBACK machinery
    latest_value_as_of already applies to total_liabilities.

    Unlike quality.py's stockholders_equity, a non-positive total_assets
    is filtered here rather than preserved: a listed company reporting
    zero or negative total assets isn't a real, common state the way
    negative book equity is, so it's treated as an error rather than
    left for scoring/zscore.py to handle.

    Confirmed against a real 44-company sample (Part 3k): range 0.044 to
    0.990. DPZ (Domino's) at the top matches its well known asset-light
    franchise model; the lower tail (GL, NDAQ, FIS) is dominated by
    financial-services names with large balance sheets relative to a
    crude gross-profit proxy, a real sector characteristic, not a defect.

    Returns None if gross profit or total assets cannot be resolved, or
    if total assets is non-positive.
    """
    gp = latest_value_as_of(facts, "gross_profit", "USD", as_of, period="annual")
    if gp is None:
        return None
    assets = latest_value_as_of(facts, "total_assets", "USD", as_of)
    if assets is None or assets[0] <= 0:
        return None
    return gp[0] / assets[0]
