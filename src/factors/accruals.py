"""Accruals factor (Sloan 1996): net income minus operating cash flow, over total assets.

Built and validated in notebooks/exploring_factors.ipynb, Part 3n.
"""

from src.loaders.fundamentals import latest_value_as_of


def accruals_factor(facts, as_of):
    """Raw accruals factor (Sloan 1996): net income minus operating cash
    flow, scaled by total assets.

    Measures the non-cash component of reported earnings: a high value
    means net income is running well ahead of the cash a company actually
    generated, the classic red flag this factor exists to capture (high
    accruals firms have been shown to subsequently underperform, on
    average, since the non-cash portion of earnings tends not to persist).

    Scaled by total assets, the same convention as profit_growth_factor
    and gross_profitability_factor, for the same reason: a well behaved,
    virtually always positive denominator.

    Confirmed against a real 60-company sample (Part 3n): mostly negative
    (median -0.031), as expected, since operating cash flow typically
    exceeds net income for healthy companies. FIS at the extreme (-0.306)
    is a fourth independent factor touching its FY2023 situation: a huge
    net loss driven largely by a non-cash goodwill impairment, so
    operating cash flow barely moved by comparison. EMR at the opposite
    extreme (0.271) reflects a real, one-time gain on the 2023 sale of
    its Climate Technologies business, which inflated net income without
    a matching operating cash inflow.

    Returns None if net income, operating cash flow, or total assets
    cannot be resolved, or if total assets is non-positive.
    """
    ni = latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")
    ocf = latest_value_as_of(facts, "operating_cash_flow", "USD", as_of, period="annual")
    if ni is None or ocf is None:
        return None
    assets = latest_value_as_of(facts, "total_assets", "USD", as_of)
    if assets is None or assets[0] <= 0:
        return None
    return (ni[0] - ocf[0]) / assets[0]
