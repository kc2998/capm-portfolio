"""Momentum factor: trailing 12 month return, excluding the most recent month.

Built and validated in notebooks/exploring_factors.ipynb, Part 9.
"""

import pandas as pd

from src.loaders.prices import close_on_or_before


def momentum_factor(prices, ticker, as_of):
    """Raw momentum factor: trailing 12 month return, excluding the most
    recent month.

    The most recent month is skipped deliberately: short term reversal
    works in the opposite direction to momentum over roughly a one month
    horizon, so including it would blend two factors with opposite signs
    into one noisy signal (see the README's short term reversal factor).

    No split-adjustment correction is needed here, unlike market_cap_as_of:
    both prices come from the same ticker's cached series, already adjusted
    to the same basis, so their ratio is already split-and-dividend
    consistent on its own.

    Known limitation, shared with every other point in time price lookup in
    this codebase: if the CIK renamed its ticker within the trailing 12
    month window and as_of predates that rename, the resolved ticker won't
    match how a "current" ticker's full history is actually cached (see
    src/loaders/README.md's PCLN/BKNG example). Not fixed here.

    Confirmed against a real 57-company sample (Part 9): mean 0.201, range
    -0.375 to 1.368, matching real 2023-2024 market history (NRG, ANET, and
    KLAC's semiconductor-led run in the winning tail; FMC, BMY, and ENPH's
    real underperformance in the losing tail).

    Returns None if either endpoint's close price cannot be resolved.
    """
    end = close_on_or_before(prices, ticker, pd.Timestamp(as_of) - pd.DateOffset(months=1))
    start = close_on_or_before(prices, ticker, pd.Timestamp(as_of) - pd.DateOffset(months=12))
    if end is None or start is None:
        return None
    return end / start - 1
