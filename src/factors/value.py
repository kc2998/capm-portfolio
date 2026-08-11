"""Value factor: earnings yield.

Built and validated in notebooks/exploring_factors.ipynb, Part 7.
"""

from src.factors.size import market_cap_as_of
from src.loaders.fundamentals import latest_value_as_of


def earnings_yield_factor(facts, prices, ticker, as_of):
    """Raw value factor: trailing annual earnings yield, net income over
    split-adjusted market capitalization.

    Earnings, not revenue or gross profit, is the numerator: net_income is
    tagged consistently across nearly every filer (a single tag,
    NetIncomeLoss, per fundamentals.py's TAG_ALIASES), where revenue and
    gross profit both have documented sector gaps (banks report interest
    income instead of revenue, per loaders/README.md).

    Returns None if net income or market cap cannot be resolved, or if
    market cap is non-positive. Validated against a toy case and a real
    51-company sample (Part 7): mean 0.046, range -0.040 to 0.200, matching
    the same shape already established for this ratio in Part 1.
    """
    ni = latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")
    if ni is None:
        return None
    market_cap = market_cap_as_of(facts, prices, ticker, as_of)
    if market_cap is None or market_cap <= 0:
        return None
    return ni[0] / market_cap
