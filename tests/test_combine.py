"""Tests for src/scoring/combine.py."""

import pandas as pd

from src.scoring.combine import combine


def test_combine_drops_a_missing_factor_and_renormalizes_rather_than_zeroing_it():
    factors = pd.DataFrame({
        "momentum": [1.0, 1.0],
        "value": [-1.0, None],
    }, index=["A", "B"])
    weights = {"momentum": 0.5, "value": 0.5}

    result = combine(factors, weights)
    assert result["A"] == 0.0
    assert result["B"] == 1.0


def test_combine_returns_nan_for_a_stock_missing_every_factor():
    factors = pd.DataFrame({
        "momentum": [1.0, None],
        "value": [-1.0, None],
    }, index=["A", "B"])
    weights = {"momentum": 0.5, "value": 0.5}

    result = combine(factors, weights)
    assert result["A"] == 0.0
    assert pd.isna(result["B"])
