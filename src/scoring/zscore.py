"""Cross sectional z-scoring: standardizing a raw factor against the rest of
the universe on one date, not against the factor's own history.

Built and validated in notebooks/exploring_factors.ipynb, Parts 1 through 3.
"""

import pandas as pd


def winsorize(values, lower=0.01, upper=0.99):
    """Clip a cross sectional series at its own [lower, upper] percentiles.

    Cheap insurance against a near-zero denominator in a factor or date not
    yet checked directly, not a correction the earnings-yield sample this was
    built against was shown to need: 278 real companies as of 2024-06-28
    ranged -0.197 to 0.217 with no outlier disconnected from its neighbors
    (Part 1). Confirmed against a toy series (1..100 plus one outlier of
    10,000, Part 3): the clipped max lands at 100.0, the base series' own
    99th percentile, not the raw outlier.
    """
    lo, hi = values.quantile([lower, upper])
    return values.clip(lo, hi)


def zscore(values, winsorize_pct=0.01):
    """Cross sectional z-score: standardize against the rest of the universe
    on this date, not against the factor's own history (the README's cross
    sectional rule).

    NaN passes through untouched at every step (quantile, clip, mean, and std
    all skip it by default), left for scoring/combine.py to drop and
    renormalize per the README's missing-data rule, rather than silently
    becoming a zero here. Confirmed against a toy series with one missing
    value (Part 3): the result carries exactly one NaN, in the same
    position, and the other four z-scores are computed from the four real
    values only.
    """
    clipped = winsorize(values, winsorize_pct, 1 - winsorize_pct) if winsorize_pct else values
    return (clipped - clipped.mean()) / clipped.std()
