"""Quality factor: return on equity.

Built and validated in notebooks/exploring_factors.ipynb, Part 8.
"""

from src.loaders.fundamentals import latest_value_as_of


def roe_factor(facts, as_of):
    """Raw quality factor: return on equity, trailing annual net income over
    stockholders' equity.

    Unlike market cap, a non-positive equity value is not filtered out here:
    negative book equity is a real, common state (leveraged share buybacks),
    not an error, though it does make ROE's sign hard to read the normal
    way. Confirmed against a real 58-company sample (Part 8): std 0.477
    versus earnings yield's 0.038-0.048 from the same sample, and the
    extreme tail (MSCI -1.77, ORLY -1.69, PM -0.76, CLX 1.64) are all real,
    well known low or negative book equity companies, not a defect the way
    the split-adjustment bug was. Left as raw data for scoring/zscore.py's
    winsorization and later IC measurement to handle, per the README's
    factor-zoo discipline, rather than guessed at here.

    stockholders_equity resolves via the StockholdersEquityIncludingPortion-
    AttributableToNoncontrollingInterest fallback for filers that stopped
    tagging the narrower StockholdersEquity after ASU 2009-17, which
    overstates equity by the minority interest (median gap 3.9% across
    fundamentals_construction.md's validation panel).

    Returns None if net income or equity cannot be resolved.
    """
    ni = latest_value_as_of(facts, "net_income", "USD", as_of, period="annual")
    if ni is None:
        return None
    equity = latest_value_as_of(facts, "stockholders_equity", "USD", as_of)
    if equity is None:
        return None
    return ni[0] / equity[0]
