"""Investment factor: percent change in total assets, year over year.

Built and validated in notebooks/exploring_factors.ipynb, Part 3m.
"""

from src.loaders.fundamentals import latest_value_as_of


def investment_factor(facts, as_of, periods_back=4):
    """Raw investment factor: percent change in total assets between the
    most recent balance sheet and the one roughly a year earlier.

    total_assets is an instant concept reported every quarter, so
    consecutive offsets (offset=0, offset=1, ...) step through
    consecutive quarters, not years; offset=4 is what reaches roughly one
    year back for a filer that reports all four quarters separately, the
    same reasoning latest_value_as_of's own docstring gives for its
    offset argument. periods_back is exposed rather than hardcoded since
    a filer that doesn't tag its fourth quarter separately has only three
    periods a year, and offset=4 would then reach back roughly 16 months
    instead of 12.

    Expressed as a plain percent change of the prior period's own value,
    unlike profit_growth_factor: total_assets is virtually always
    positive, so it doesn't have the near-zero-denominator problem
    net_income does.

    Confirmed against a real 60-company sample (Part 3m): AVGO at the top
    (1.445) matches its completed ~$69B VMware acquisition (Nov 2023);
    EXR (1.265) likely reflects its 2023 Life Storage merger. FIS at the
    bottom (-0.413) is a third independent confirmation of the same
    Worldpay divestiture already found via ticker_on and profit_growth.

    Returns None if either total assets figure cannot be resolved, or if
    the prior period's total assets is non-positive.
    """
    current = latest_value_as_of(facts, "total_assets", "USD", as_of, offset=0)
    prior = latest_value_as_of(facts, "total_assets", "USD", as_of, offset=periods_back)
    if current is None or prior is None or prior[0] <= 0:
        return None
    return (current[0] - prior[0]) / prior[0]
