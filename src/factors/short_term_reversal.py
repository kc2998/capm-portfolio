"""Short term reversal factor: negative of the trailing one week return.

Built and validated in notebooks/exploring_factors.ipynb, Part 3f.
"""

import pandas as pd

from src.loaders.prices import close_on_or_before


def short_term_reversal_factor(prices, ticker, as_of, lookback=pd.DateOffset(weeks=1)):
    """Raw short term reversal factor: negative of the trailing return over
    lookback (one week by default; pass pd.DateOffset(months=1) for the
    monthly variant Jegadeesh 1990 also documents).

    The negation is part of the factor's own definition, not a later
    alpha-direction choice the way size_factor/low_vol_factor's raw sign
    is: short term reversal bets that a stock's most recent return
    predicts the opposite next, so a name that just fell gets a high score
    here, not a low one, by construction.

    No month skipped, unlike momentum: this factor is the near-term effect
    momentum deliberately excludes, not a longer-horizon signal that needs
    protecting from it.

    Well documented (Jegadeesh 1990, Lehmann 1990) but strongest among
    small, illiquid securities and substantially eroded by transaction
    costs; screen by information coefficient within a large-cap universe
    before trusting it here, per the README, rather than assuming it
    carries over. Checked against a real 60-company sample (Part 3f): the
    most extreme case, FDX at -0.189, is a confirmed real event (a ~15%
    single-day rally after its June 2024 earnings beat), not a data defect.

    Returns None if either endpoint's close price cannot be resolved.
    """
    end = close_on_or_before(prices, ticker, as_of)
    start = close_on_or_before(prices, ticker, pd.Timestamp(as_of) - lookback)
    if end is None or start is None:
        return None
    return -(end / start - 1)
