"""Tests for src/scoring/zscore.py."""

import pandas as pd

from src.scoring.zscore import winsorize, zscore


def test_winsorize_pulls_an_extreme_value_down_to_the_percentile_cutoff():
    toy = pd.Series(range(1, 101), dtype=float)
    toy_with_outlier = pd.concat([toy, pd.Series([10_000.0])], ignore_index=True)
    clipped = winsorize(toy_with_outlier, 0.01, 0.99)
    assert clipped.max() == 100.0


def test_zscore_leaves_a_missing_value_as_nan_not_zero():
    toy_with_gap = pd.Series([1.0, 2.0, 3.0, None, 5.0])
    z = zscore(toy_with_gap, winsorize_pct=0)
    assert z.isna().sum() == 1
    assert pd.isna(z.iloc[3])
    assert z.dropna().index.tolist() == [0, 1, 2, 4]
