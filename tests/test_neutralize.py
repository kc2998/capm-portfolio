"""Tests for src/scoring/neutralize.py."""

import pandas as pd
import pytest

from src.scoring.neutralize import neutralize


def test_neutralize_returns_the_ols_residual_against_beta():
    betas = pd.Series([1.0, 2.0, 3.0], index=["A", "B", "C"])
    scores = pd.Series([1.0, 2.0, 6.0], index=["A", "B", "C"])

    result = neutralize(scores, betas)

    assert result["A"] == pytest.approx(0.5)
    assert result["B"] == pytest.approx(-1.0)
    assert result["C"] == pytest.approx(0.5)


def test_neutralize_excludes_a_missing_score_from_the_fit_and_returns_nan():
    betas = pd.Series([1.0, 2.0, 3.0, 4.0], index=["A", "B", "C", "D"])
    scores = pd.Series([1.0, 2.0, 6.0, None], index=["A", "B", "C", "D"])

    result = neutralize(scores, betas)

    assert result["A"] == pytest.approx(0.5)
    assert result["B"] == pytest.approx(-1.0)
    assert result["C"] == pytest.approx(0.5)
    assert pd.isna(result["D"])


def test_neutralize_excludes_a_missing_beta_from_the_fit_and_returns_nan():
    betas = pd.Series([1.0, 2.0, 3.0, None], index=["A", "B", "C", "D"])
    scores = pd.Series([1.0, 2.0, 6.0, 10.0], index=["A", "B", "C", "D"])

    result = neutralize(scores, betas)

    assert result["A"] == pytest.approx(0.5)
    assert result["B"] == pytest.approx(-1.0)
    assert result["C"] == pytest.approx(0.5)
    assert pd.isna(result["D"])
