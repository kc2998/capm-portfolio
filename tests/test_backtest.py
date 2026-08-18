"""Tests for the pure, no-I/O logic in src/backtest/engine.py and
src/backtest/metrics.py.

Deliberately excludes compute_row, run_rebalance, and run_backtest, which
orchestrate the network- and disk-bound loaders and are validated
empirically against real data in notebooks/exploring_backtest.ipynb and
documented in notebooks/logs/backtest_construction.md, not mocked here.
"""

import pandas as pd
import pytest

from src.backtest.engine import quantile_weights
from src.backtest.metrics import turnover


# ---------------------------------------------------------------------------
# quantile_weights
# ---------------------------------------------------------------------------

def _scores(values):
    return pd.DataFrame({"factor_score": values}, index=range(len(values)))


def test_quantile_weights_longs_the_top_fifth_and_shorts_the_bottom_fifth():
    df = _scores([5.0, 4.0, 3.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0, -4.0])
    w = quantile_weights(df, quantile=0.2)
    assert w[0] == 0.5 and w[1] == 0.5
    assert w[8] == -0.5 and w[9] == -0.5
    assert (w[2:8] == 0.0).all()


def test_quantile_weights_is_dollar_neutral():
    df = _scores([5.0, 4.0, 3.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0, -4.0])
    w = quantile_weights(df, quantile=0.2)
    assert w.sum() == 0.0


def test_quantile_weights_excludes_missing_scores_from_bucket_sizing():
    df = _scores([5.0, 4.0, None, 2.0, 1.0])
    w = quantile_weights(df, quantile=0.2)
    # 4 valid scores; 20% of 4 rounds down to 0, floored back up to 1 by
    # max(1, ...), so exactly one long and one short come out of this.
    assert w[0] == 1.0
    assert w[4] == -1.0
    assert w[2] == 0.0   # the missing score itself gets no weight either


def test_quantile_weights_with_one_valid_score_gives_it_to_the_short_side():
    # A known, currently unfixed quirk, worth documenting rather than
    # hiding: with only one valid score, longs and shorts both resolve to
    # that same single stock, and since shorts is assigned second in the
    # function body, it wins. Not a realistic case at this project's scale
    # (the real universe is roughly 500 names), but real behavior, not
    # assumed.
    df = _scores([5.0])
    w = quantile_weights(df, quantile=0.2)
    assert w[0] == -1.0


# ---------------------------------------------------------------------------
# turnover
# ---------------------------------------------------------------------------

def test_turnover_is_zero_when_nothing_changed():
    w = pd.Series({1: 0.5, 2: -0.5})
    assert turnover(w, w) == 0.0


def test_turnover_counts_an_exit_to_zero():
    w_prev = pd.Series({1: 0.5, 2: -0.5})
    w_curr = pd.Series({2: -0.5})
    assert turnover(w_prev, w_curr) == 0.5


def test_turnover_counts_a_new_entrant_from_zero():
    w_prev = pd.Series({2: -0.5})
    w_curr = pd.Series({1: 0.5, 2: -0.5})
    assert turnover(w_prev, w_curr) == 0.5


def test_turnover_counts_a_full_flip_as_twice_the_position_size():
    # Long becomes short: |-0.5 - 0.5| = 1.0, not 0.5, since the position
    # crossed all the way through zero rather than just entering or exiting.
    w_prev = pd.Series({1: 0.5})
    w_curr = pd.Series({1: -0.5})
    assert turnover(w_prev, w_curr) == 1.0
