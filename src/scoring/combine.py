"""Combining z-scored factors into one score per stock via a weighted average.

Built and validated in notebooks/exploring_factors.ipynb, Part 4.
"""

import pandas as pd


def combine(factors, weights):
    """Weighted average of already z-scored factors, per stock.

    `factors`: a DataFrame, one row per stock, one column per factor, already
    z-scored (see scoring/zscore.py). `weights`: a dict or Series mapping
    factor column name to its weight.

    A stock missing one or more factors has those terms dropped and the
    remaining weights renormalized, per the README's missing-data rule.
    NaN * weight is NaN, and `.sum(skipna=True)` (pandas' default) skips it,
    so a missing factor simply never enters the numerator; the denominator
    only counts weight from factors actually present (`aligned.notna()`), so
    it shrinks to match. Confirmed against a toy case (Part 4): two equally
    weighted factors, a stock missing one gets 1.0, the other factor's full
    z-score, not 0.5, what substituting zero for the missing term would give.
    A stock missing every factor gets weight_sum 0, explicitly mapped to NaN
    rather than a 0/0 division left to happen silently.
    """
    w = pd.Series(weights)
    aligned = factors[w.index]

    weighted_sum = aligned.mul(w, axis=1).sum(axis=1, skipna=True)
    weight_sum = aligned.notna().mul(w, axis=1).sum(axis=1)

    combined = weighted_sum / weight_sum
    combined[weight_sum == 0] = float("nan")
    return combined

