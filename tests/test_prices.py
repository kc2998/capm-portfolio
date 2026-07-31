"""Tests for the pure, no-I/O logic in src/loaders/prices.py.

Deliberately excludes anything that hits the network: classify_ticker,
ticker_spans_for_cik, fetch_cik_prices, and build_prices exist specifically
to ask a vendor a question, so they are validated empirically against real
tickers in notebooks/exploring_loaders.ipynb and documented in
notebooks/logs/loaders_construction.md, not mocked here. What's covered
below is the decision logic those functions wrap around: ticker
translation, and the three way classification given an already fetched
response, the same principle tests/test_point_in_time.py already applies.
"""

import pandas as pd
import pytest

from src.loaders.prices import (
    _classify_from_probe,
    load_cik_prices,
    save_cik_prices,
    to_yfinance_ticker,
)


# ---------------------------------------------------------------------------
# to_yfinance_ticker
# ---------------------------------------------------------------------------

def test_to_yfinance_ticker_leaves_a_plain_ticker_alone():
    assert to_yfinance_ticker("AAPL") == "AAPL"


def test_to_yfinance_ticker_translates_multi_class_period_to_hyphen():
    assert to_yfinance_ticker("BF.B") == "BF-B"
    assert to_yfinance_ticker("BRK.B") == "BRK-B"


def test_to_yfinance_ticker_strips_base_yyyymm_suffix_before_translating():
    # AFS.A-200011: a book-era recycling disambiguator on a multi class
    # ticker, both need handling, and in the right order (strip, then
    # translate), or the suffix's hyphen gets mistaken for the class
    # separator.
    assert to_yfinance_ticker("AFS.A-200011") == "AFS-A"


def test_to_yfinance_ticker_strips_a_bare_suffixed_ticker():
    assert to_yfinance_ticker("RYAN-200610") == "RYAN"


# ---------------------------------------------------------------------------
# _classify_from_probe
# ---------------------------------------------------------------------------

def _probe(dates):
    index = pd.DatetimeIndex(dates, tz="America/New_York")
    return pd.DataFrame({"Close": range(len(dates))}, index=index)


def test_classify_from_probe_empty_is_retired():
    # CMCSK's real case: Comcast genuinely eliminated this share class in
    # 2015, no successor exists.
    assert _classify_from_probe(pd.DataFrame(), "2015-09-30") == "retired"


def test_classify_from_probe_reaching_expected_start_is_current():
    probe = _probe(["2014-05-31", "2014-06-01"])
    assert _classify_from_probe(probe, "2014-05-31") == "current"


def test_classify_from_probe_within_tolerance_is_current():
    # BKNG's real case: requested 2018-03-31, the vendor's actual first
    # trading day was 2018-04-02 (a weekend in between), ordinary slack,
    # not genuine ambiguity.
    probe = _probe(["2018-04-02"])
    assert _classify_from_probe(probe, "2018-03-31") == "current"


def test_classify_from_probe_starting_much_later_is_recycled():
    # PCLN's real case: ticker_history expects 2014-05-31, but the symbol
    # was recycled and the vendor's actual data only reaches back to 2025,
    # a different, unrelated company.
    probe = _probe(["2025-10-16"])
    assert _classify_from_probe(probe, "2014-05-31") == "recycled"


def test_classify_from_probe_respects_the_tolerance_boundary():
    probe = _probe(["2015-01-01"])
    assert _classify_from_probe(probe, "2014-11-01", tolerance_days=45) == "recycled"
    assert _classify_from_probe(probe, "2014-11-01", tolerance_days=90) == "current"


# ---------------------------------------------------------------------------
# save_cik_prices / load_cik_prices
# ---------------------------------------------------------------------------

def test_save_and_load_cik_prices_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("src.loaders.prices.PRICES_RAW_DIR", tmp_path)

    df = pd.DataFrame(
        {"Open": [1.0, 2.0], "Close": [1.1, 2.1]},
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02"], tz="America/New_York"),
    )
    saved = save_cik_prices(999999, {"XYZ": df})
    loaded = load_cik_prices(999999)

    assert loaded.equals(saved)
    assert list(loaded["ticker"].unique()) == ["XYZ"]


def test_save_cik_prices_drops_empty_ticker_frames(tmp_path, monkeypatch):
    monkeypatch.setattr("src.loaders.prices.PRICES_RAW_DIR", tmp_path)

    saved = save_cik_prices(999998, {"EMPTY": pd.DataFrame()})
    assert saved.empty


def test_load_cik_prices_returns_none_when_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("src.loaders.prices.PRICES_RAW_DIR", tmp_path)

    assert load_cik_prices(123456789) is None
