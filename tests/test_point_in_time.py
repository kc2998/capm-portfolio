"""Tests for the pure, no-I/O logic in src/universe/point_in_time.py.

Deliberately excludes anything that hits the network (Wikipedia, SEC): those
are exercised by actually running the pipeline, not by mocking here. What's
covered below is the logic that turned out, while building this, to be worth
double checking: several of these tests exist specifically because the bug
they guard against was found once by hand (see notebooks/logs/universe_construction.md).
"""

import pandas as pd
import pytest

from src.universe.point_in_time import (
    apply_filing_verification,
    attach_cik,
    base_ticker,
    build_spans,
    combine_universe_spans,
    extract_ticker_mentions,
    flag_book_ticker_verification,
    flag_left_censored,
    membership_on,
    ciks_on,
    nearest_10k,
    normalize_ticker_punctuation,
    ticker_on,
)


# ---------------------------------------------------------------------------
# normalize_ticker_punctuation / base_ticker
# ---------------------------------------------------------------------------

def test_normalize_ticker_punctuation_collapses_hyphen_to_period():
    assert normalize_ticker_punctuation("BRK-B") == "BRK.B"
    assert normalize_ticker_punctuation("BF-B") == "BF.B"


def test_normalize_ticker_punctuation_leaves_period_form_and_plain_tickers_alone():
    assert normalize_ticker_punctuation("BRK.B") == "BRK.B"
    assert normalize_ticker_punctuation("AAPL") == "AAPL"


def test_base_ticker_strips_the_book_csvs_recycling_suffix():
    assert base_ticker("H-200107") == "H"
    assert base_ticker("CCB-199602") == "CCB"


def test_base_ticker_leaves_bare_tickers_and_lookalikes_alone():
    assert base_ticker("AAPL") == "AAPL"
    # not a BASE-YYYYMM suffix: too many hyphens, or the suffix isn't 6 digits
    assert base_ticker("BRK-B") == "BRK-B"
    assert base_ticker("FOO-12") == "FOO-12"


# ---------------------------------------------------------------------------
# build_spans
# ---------------------------------------------------------------------------

def _snap(tickers):
    return pd.DataFrame({"ticker": tickers, "cik": pd.NA})


def test_build_spans_opens_a_span_on_first_appearance_and_closes_on_disappearance():
    snapshots = {
        "2020-01-31": _snap(["AAPL", "MSFT"]),
        "2020-02-29": _snap(["AAPL", "MSFT"]),
        "2020-03-31": _snap(["AAPL"]),  # MSFT exits
    }
    spans = build_spans(snapshots)

    aapl = spans[spans["ticker"] == "AAPL"].iloc[0]
    assert aapl["start_date"] == "2020-01-31"
    assert pd.isna(aapl["end_date"])  # still open, never observed to exit

    msft = spans[spans["ticker"] == "MSFT"].iloc[0]
    assert msft["start_date"] == "2020-01-31"
    assert msft["end_date"] == "2020-02-29"  # last date confirmed present


def test_build_spans_every_ticker_in_the_first_snapshot_opens_there():
    # There is no "before" to compare against, so everything present on the
    # first date opens a span there rather than being treated as unknown.
    snapshots = {"2020-01-31": _snap(["AAPL"])}
    spans = build_spans(snapshots)
    assert spans.iloc[0]["start_date"] == "2020-01-31"


# ---------------------------------------------------------------------------
# attach_cik / flag_left_censored
# ---------------------------------------------------------------------------

def test_attach_cik_uses_the_latest_non_null_cik_not_the_value_at_span_start():
    snapshots = {
        "2009-01-31": pd.DataFrame({"ticker": ["XYZ"], "cik": [pd.NA]}),
        "2015-01-31": pd.DataFrame({"ticker": ["XYZ"], "cik": [42]}),
    }
    spans = pd.DataFrame([{"ticker": "XYZ", "start_date": "2009-01-31", "end_date": None}])
    result = attach_cik(spans, snapshots)
    assert result.iloc[0]["cik"] == 42


def test_flag_left_censored_marks_only_spans_starting_on_the_first_observed_date():
    spans = pd.DataFrame([
        {"ticker": "BCO", "start_date": "1996-01-02", "end_date": "1996-01-12"},
        {"ticker": "AAPL", "start_date": "2001-05-01", "end_date": None},
    ])
    result = flag_left_censored(spans, "1996-01-02")
    assert result.iloc[0]["left_censored"] == True
    assert result.iloc[1]["left_censored"] == False


# ---------------------------------------------------------------------------
# flag_book_ticker_verification
# ---------------------------------------------------------------------------

def test_flag_book_ticker_verification_suffixed_tickers_verified_by_default():
    spans = pd.DataFrame([{"ticker": "H-200107", "cik": pd.NA}])
    former_names = pd.DataFrame(columns=["cik", "former_name", "from_date", "to_date"])
    result = flag_book_ticker_verification(spans, former_names)
    assert result.iloc[0]["verified"]


def test_flag_book_ticker_verification_bare_ticker_with_no_cik_is_flagged():
    # This is the BHGE gap: a bare ticker with no CIK match at all used to
    # default to verified=True, silently passing the confirmed example that
    # motivated this whole check.
    spans = pd.DataFrame([{"ticker": "BHGE", "cik": pd.NA}])
    former_names = pd.DataFrame(columns=["cik", "former_name", "from_date", "to_date"])
    result = flag_book_ticker_verification(spans, former_names)
    assert not result.iloc[0]["verified"]


def test_flag_book_ticker_verification_bare_ticker_with_cik_and_no_former_name_is_verified():
    spans = pd.DataFrame([{"ticker": "AAPL", "cik": 320193}])
    former_names = pd.DataFrame(columns=["cik", "former_name", "from_date", "to_date"])
    result = flag_book_ticker_verification(spans, former_names)
    assert result.iloc[0]["verified"]


def test_flag_book_ticker_verification_bare_ticker_with_a_former_name_is_flagged():
    spans = pd.DataFrame([{"ticker": "CAL", "cik": 14707}])
    former_names = pd.DataFrame([
        {"cik": 14707, "former_name": "BROWN GROUP INC", "from_date": "1994-09-01", "to_date": "1999-04-26"},
    ])
    result = flag_book_ticker_verification(spans, former_names)
    assert not result.iloc[0]["verified"]


# ---------------------------------------------------------------------------
# extract_ticker_mentions
# ---------------------------------------------------------------------------

def test_extract_ticker_mentions_finds_a_plain_mention():
    text = "the common stock trades on the Philadelphia Stock Exchange under the symbol SRV."
    matches = extract_ticker_mentions(text)
    assert ("SRV", matches[0][1]) in [(t, c) for t, c in matches]


def test_extract_ticker_mentions_handles_quotes_and_a_trailing_period():
    text = 'traded on the New York Stock Exchange with the ticker symbol "HP."'
    tickers = [t for t, _ in extract_ticker_mentions(text)]
    assert "HP" in tickers


def test_extract_ticker_mentions_handles_a_colon_and_dual_tickers():
    text = "Nasdaq National Market Symbol: PMTC"
    tickers = [t for t, _ in extract_ticker_mentions(text)]
    assert "PMTC" in tickers

    text2 = 'trade on the New York Stock Exchange under the ticker symbols "PZB" and "PZX", respectively.'
    tickers2 = {t for t, _ in extract_ticker_mentions(text2)}
    assert tickers2 == {"PZB", "PZX"}


def test_extract_ticker_mentions_does_not_match_lowercase_words_after_symbol():
    # The bug this guards against: case-insensitivity applied to the whole
    # pattern instead of just the word "symbol" matched ordinary lowercase
    # words (SHALL, for) as if they were tickers.
    text = "the trademark symbol shall be expressed as 'tm'."
    assert extract_ticker_mentions(text) == []

    text2 = "SRV is the New York Stock Exchange ticker symbol for the common stock of Example Inc."
    tickers = [t for t, _ in extract_ticker_mentions(text2)]
    assert "FOR" not in tickers


# ---------------------------------------------------------------------------
# nearest_10k
# ---------------------------------------------------------------------------

def test_nearest_10k_picks_the_closest_filing():
    history = [
        ("10-K", "1996-04-19", "aaa"),
        ("10-K", "2003-03-31", "bbb"),
        ("8-K", "1996-04-20", "ccc"),  # not a 10-K, ignored
    ]
    form, date, accession = nearest_10k(history, "1996-01-02")
    assert accession == "aaa"


def test_nearest_10k_rejects_a_filing_too_far_from_the_target_date():
    # The CCK case: a 2003 filing is not evidence about a 1996-2000 span.
    history = [("10-K", "2003-03-31", "bbb")]
    assert nearest_10k(history, "1996-01-02", max_gap_days=548) is None


# ---------------------------------------------------------------------------
# combine_universe_spans
# ---------------------------------------------------------------------------

def test_combine_universe_spans_stitches_a_continuous_membership_across_the_boundary():
    book_spans = pd.DataFrame([
        {"ticker": "AAPL", "cik": 320193, "start_date": "1996-01-02",
         "end_date": None, "left_censored": True},
    ])
    wiki_spans = pd.DataFrame([
        {"ticker": "AAPL", "cik": 320193, "start_date": "2008-01-31",
         "end_date": None, "left_censored": True},
    ])
    result = combine_universe_spans(book_spans, wiki_spans)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["source"] == "clenow_norgate+wikipedia_revision"
    assert row["start_date"] == "1996-01-02"
    assert pd.isna(row["end_date"])


def test_combine_universe_spans_caps_an_unstitched_open_book_span_instead_of_leaving_it_null():
    # The core bug found by running this: an open book-era span with no
    # continuing wiki entry was being read as "still active today."
    book_spans = pd.DataFrame([
        {"ticker": "BHGE", "cik": pd.NA, "start_date": "1996-01-02",
         "end_date": None, "left_censored": True},
    ])
    wiki_spans = pd.DataFrame([], columns=["ticker", "cik", "start_date", "end_date", "left_censored"])
    result = combine_universe_spans(book_spans, wiki_spans, book_era_end="2008-01-30")

    assert result.iloc[0]["end_date"] == "2008-01-30"


def test_membership_on_treats_null_end_date_as_still_active():
    spans = pd.DataFrame([
        {"ticker": "AAPL", "start_date": "1996-01-02", "end_date": None},
        {"ticker": "XYZ", "start_date": "1996-01-02", "end_date": "2000-01-01"},
    ])
    assert membership_on(spans, "2020-01-01") == {"AAPL"}
    assert membership_on(spans, "1998-01-01") == {"AAPL", "XYZ"}

def test_ciks_on_treats_null_end_date_as_still_active():
    spans = pd.DataFrame([
        {"cik": 320193, "start_date": "1996-01-02", "end_date": None},
        {"cik": 999999, "start_date": "1996-01-02", "end_date": "2000-01-01"},
    ])
    assert ciks_on(spans, "2020-01-01") == [320193]
    assert set(ciks_on(spans, "1998-01-01")) == {320193, 999999}


def test_ciks_on_drops_missing_ciks_and_deduplicates():
    spans = pd.DataFrame([
        {"cik": pd.NA, "start_date": "1996-01-02", "end_date": None},
        {"cik": 320193, "start_date": "1996-01-02", "end_date": None},
        {"cik": 320193, "start_date": "2005-01-01", "end_date": None},
    ])
    assert ciks_on(spans, "2010-01-01") == [320193]


# ---------------------------------------------------------------------------
# ticker_on / apply_filing_verification
# ---------------------------------------------------------------------------

def test_ticker_on_returns_the_ticker_in_force_on_a_date_not_the_current_one():
    history = pd.DataFrame([
        {"cik": 1075531, "ticker": "PCLN", "start_date": "2009-11-06", "end_date": "2018-03-31"},
        {"cik": 1075531, "ticker": "BKNG", "start_date": "2018-03-31", "end_date": None},
    ])
    assert ticker_on(history, 1075531, "2015-06-30") == "PCLN"
    assert ticker_on(history, 1075531, "2022-01-01") == "BKNG"
    assert ticker_on(history, 1075531, "2000-01-01") is None

def test_ticker_on_prefers_the_most_recently_started_row_when_two_open_rows_exist():
    # The FNF/FIS case (CIK 1136893): a book-era row for FNF, open since
    # 2006, and a wikipedia-era row for FIS, open since 2014, both match
    # any date from 2014 onward. Array order used to pick FNF regardless
    # of query date; the most recent start date should win instead.
    history = pd.DataFrame([
        {"cik": 1136893, "ticker": "FNF", "start_date": "2006-11-10", "end_date": None},
        {"cik": 1136893, "ticker": "FIS", "start_date": "2014-05-31", "end_date": None},
    ])
    assert ticker_on(history, 1136893, "2024-06-28") == "FIS"


def test_ticker_on_still_returns_the_only_match_before_the_second_rows_start():
    history = pd.DataFrame([
        {"cik": 1136893, "ticker": "FNF", "start_date": "2006-11-10", "end_date": None},
        {"cik": 1136893, "ticker": "FIS", "start_date": "2014-05-31", "end_date": None},
    ])
    assert ticker_on(history, 1136893, "2010-01-01") == "FNF"


def test_apply_filing_verification_corrects_a_mismatch_and_keeps_the_original():
    ticker_history = pd.DataFrame([
        {"cik": 14707, "ticker": "CAL", "start_date": "1996-01-02",
         "end_date": "1996-07-19", "verified": False, "source": "clenow_norgate"},
    ])
    filing_verification = pd.DataFrame([
        {"cik": 14707, "start_date": "1996-01-02", "status": "confirmed_mismatch",
         "candidate": "BG", "evidence": "(symbol BG)", "accession": "0000014707-96-000004"},
    ])
    result = apply_filing_verification(ticker_history, filing_verification)

    row = result.iloc[0]
    assert row["ticker"] == "BG"
    assert row["original_ticker"] == "CAL"
    assert row["verified"]
    assert "BG" in row["evidence"]


def test_apply_filing_verification_leaves_ambiguous_results_untouched():
    ticker_history = pd.DataFrame([
        {"cik": 78890, "ticker": "BCO", "start_date": "1996-01-02",
         "end_date": "1996-01-12", "verified": False, "source": "clenow_norgate"},
    ])
    filing_verification = pd.DataFrame([
        {"cik": 78890, "start_date": "1996-01-02", "status": "confirmed_mismatch_ambiguous",
         "candidate": "PZB, PZM, PZS, PZX", "evidence": "...", "accession": "0000950117-96-000277"},
    ])
    result = apply_filing_verification(ticker_history, filing_verification)

    row = result.iloc[0]
    assert row["ticker"] == "BCO"  # unchanged
    assert not row["verified"]     # still flagged
    assert pd.isna(row["original_ticker"])
