"""Point in time S&P 500 universe builder.

Produces two artifacts: `universe_spans` (membership, one row per interval) and
`ticker_history` (which symbol an entity traded under, and when), built from two
sources, Wikipedia's revision history (2008 onward, re-derivable from the primary
source at any time) and a book derived CSV (1996 to 2008, Clenow/Norgate),
reconciled against each other, cross checked, and verified where possible against
primary source SEC filings.

Full methodology, every source considered and rejected, every bug found while
building this, and the evidence behind every non-obvious decision are recorded in
`notebooks/logs/universe_construction.md`. This module is the promoted, clean
implementation; that file is the reasoning behind it. `notebooks/exploring_universe.ipynb`
is where this was originally built and validated, kept as the historical record.
"""

import logging
import re
import ssl
import time
from io import StringIO
from pathlib import Path

import certifi
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths, resolved relative to the project root rather than hardcoded, since
# this module may be imported from anywhere (scripts/, tests/, eventually the
# backtest engine), not just run from a fixed working directory.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

BOOK_CSV_PATH = DATA_RAW / "S&P 500 Historical Components & Changes.csv"
WIKI_SNAPSHOTS_CACHE = DATA_RAW / "wiki_snapshots.parquet"
SEC_TICKER_CIK_CACHE = DATA_RAW / "sec_ticker_cik.parquet"
FORMER_NAMES_CACHE = DATA_RAW / "former_names.parquet"
FILING_VERIFICATION_CACHE = DATA_RAW / "filing_verification.parquet"
UNIVERSE_SPANS_PATH = DATA_PROCESSED / "universe_spans.parquet"
TICKER_HISTORY_PATH = DATA_PROCESSED / "ticker_history.parquet"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKI_API_URL = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE_TITLE = "List of S&P 500 companies"
# Wikimedia asks API clients to identify themselves with a descriptive User-Agent
# including contact info, discouraged from using a plain browser UA for API access.
WIKI_HEADERS = {
    "User-Agent": "capm-portfolio/0.1 (research project; https://github.com/kc2998/capm-portfolio)"
}

# SEC's fair access policy asks for a real, identifying contact, not a generic string.
SEC_HEADERS = {"User-Agent": "capm-portfolio-research kevin (contact: hongxianl957@gmail.com)"}

WIKI_ERA_START = "2008-01-31"          # first monthly snapshot date; also the era boundary
BOOK_ERA_END = "2008-01-30"            # last book-era date before the boundary
BOOK_ERA_FIRST_DATE = "1996-01-02"     # book file's first observed date

ROW_COUNT_BAND = (495, 517)            # plausible S&P 500 constituent count, per the log
MAX_FILING_GAP_DAYS = 548              # ~18 months; beyond this a "nearest" filing isn't evidence


def _ensure_ssl_context():
    """Point Python's default HTTPS context at certifi's CA bundle.

    Called lazily by build_universe(), not at import time, so importing this
    module has no side effects. Needed on macOS python.org installs, which
    don't hook into the system keychain; without it, HTTPS requests can fail
    with SSL: CERTIFICATE_VERIFY_FAILED.
    """
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())


# ---------------------------------------------------------------------------
# Wikipedia revision fetching (2008 onward)
# ---------------------------------------------------------------------------

def revision_at(date_iso):
    """Return (revid, timestamp) of the last Wikipedia revision at or before date_iso."""
    params = {
        "action": "query", "prop": "revisions", "titles": WIKI_PAGE_TITLE,
        "rvlimit": 1,
        "rvdir": "older",
        "rvstart": date_iso,
        "rvprop": "ids|timestamp",
        "format": "json", "formatversion": 2,
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=10)
    r.raise_for_status()
    revs = r.json()["query"]["pages"][0].get("revisions", [])
    return (revs[0]["revid"], revs[0]["timestamp"]) if revs else (None, None)


def revision_html(revid):
    """Fetch the rendered HTML of a specific Wikipedia revision."""
    params = {"action": "parse", "oldid": revid, "prop": "text",
              "format": "json", "formatversion": 2}
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["parse"]["text"]


def find_constituents(tabs):
    """Pick the table that looks like a constituents list: has a ticker-ish column.

    Matching on a column signature rather than a fixed index is what lets one
    parser work across a decade of Wikipedia reformatting.
    """
    for i, t in enumerate(tabs):
        cols = [str(c).lower() for c in t.columns]
        if any("symbol" in c or "ticker" in c for c in cols):
            return i, t
    return None, None


def normalize_ticker_punctuation(ticker):
    """Collapse the hyphen/period share-class notation to one form.

    Wikipedia itself is inconsistent across revisions about whether a multi
    class ticker uses a period or a hyphen (BRK.B vs BRK-B), which otherwise
    makes build_spans see a punctuation change as an exit and a fresh entry
    for the same, unchanged security.
    """
    return re.sub(r"-([A-Za-z])$", r".\1", ticker)


def normalize_constituents(table):
    """Extract a clean (ticker, cik) frame from a raw constituents table.

    Column names drift across eras ('Ticker symbol' -> 'Symbol'; CIK absent
    before ~2014), so columns are matched by signature, the same principle
    find_constituents already uses to pick the table itself.
    """
    cols = {str(c).lower().strip(): c for c in table.columns}

    ticker_col = next((orig for lower, orig in cols.items()
                        if "symbol" in lower or "ticker" in lower), None)
    if ticker_col is None:
        raise ValueError("no ticker-like column found")

    cik_col = cols.get("cik")  # exact match, this column's name hasn't drifted

    return pd.DataFrame({
        "ticker": table[ticker_col].astype(str).str.strip().apply(normalize_ticker_punctuation),
        "cik": table[cik_col] if cik_col is not None else pd.NA,
    })


def snapshot_at(date_iso):
    """Fetch and normalize the S&P 500 constituents table as of date_iso.

    Returns None rather than raising when no usable table exists, either
    because the date predates the table's introduction on the page, or
    because the row count falls outside the plausible band, so a bad or
    vandalized revision gets skipped and counted, not silently trusted.
    """
    revid, ts = revision_at(f"{date_iso}T00:00:00Z")
    if revid is None:
        return None

    try:
        tabs = pd.read_html(StringIO(revision_html(revid)))
    except ValueError:
        return None  # page fetched fine, but no tables on it yet, pre-2008 era

    _, table = find_constituents(tabs)
    if table is None:
        return None

    norm = normalize_constituents(table)
    if not (ROW_COUNT_BAND[0] <= len(norm) <= ROW_COUNT_BAND[1]):
        return None

    return norm, ts


def fetch_wiki_snapshots(cache_path=WIKI_SNAPSHOTS_CACHE, start_date=WIKI_ERA_START):
    """Fetch (or load cached) monthly Wikipedia snapshots from start_date to today.

    One snapshot per month end, the cadence decided in the README: index
    membership changes roughly twice a month, so a finer cadence would assert
    more precision than the source has. Several minutes and ~440 requests the
    first time; every call after that loads from disk in under a second.
    """
    if cache_path.exists():
        cached = pd.read_parquet(cache_path)
        return {
            date: group.drop(columns="snapshot_date").reset_index(drop=True)
            for date, group in cached.groupby("snapshot_date")
        }

    month_ends = pd.date_range(start_date, pd.Timestamp.today().normalize(), freq="ME")
    logger.info("fetching %d monthly Wikipedia snapshots", len(month_ends))

    snapshots = {}
    skipped, errors = [], []
    for i, d in enumerate(month_ends):
        date_iso = d.strftime("%Y-%m-%d")
        try:
            result = snapshot_at(date_iso)
        except Exception as e:
            errors.append((date_iso, type(e).__name__, str(e)))
            continue

        if result is None:
            skipped.append(date_iso)
        else:
            norm, ts = result
            snapshots[date_iso] = norm

        if (i + 1) % 24 == 0:
            logger.info("%d/%d months done, %d skipped, %d errors",
                        i + 1, len(month_ends), len(skipped), len(errors))
        time.sleep(0.5)

    logger.info("%d snapshots retrieved, %d skipped, %d errors",
                len(snapshots), len(skipped), len(errors))
    if errors:
        logger.warning("fetch errors: %s", errors)

    all_snaps = pd.concat(
        [df.assign(snapshot_date=date) for date, df in snapshots.items()],
        ignore_index=True,
    )
    all_snaps["cik"] = all_snaps["cik"].astype("Int64")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    all_snaps.to_parquet(cache_path, index=False)

    return snapshots


# ---------------------------------------------------------------------------
# Snapshots to spans (shared by both eras: build_spans is source agnostic)
# ---------------------------------------------------------------------------

def build_spans(snapshots):
    """Diff consecutive snapshots into (ticker, start_date, end_date) spans.

    A ticker appearing in snapshot N but not N-1 opens a span at N; one
    disappearing closes the span at N-1, the last date it was confirmed
    present. Boundary precision is therefore limited to the snapshot
    interval, monthly for the wiki era, daily for the book era. Used
    unmodified for both sources; it only needs a {date: DataFrame} mapping
    with a "ticker" column.
    """
    dates = sorted(snapshots)
    open_spans = {}
    closed = []

    prev_date = None
    prev_tickers = set()

    for date in dates:
        curr_tickers = set(snapshots[date]["ticker"])

        entered = curr_tickers - prev_tickers
        exited = prev_tickers - curr_tickers

        for ticker in entered:
            open_spans[ticker] = date

        for ticker in exited:
            start = open_spans.pop(ticker)
            closed.append((ticker, start, prev_date))

        prev_tickers = curr_tickers
        prev_date = date

    for ticker, start in open_spans.items():
        closed.append((ticker, start, None))

    return pd.DataFrame(closed, columns=["ticker", "start_date", "end_date"])


def attach_cik(spans, snapshots):
    """Attach the latest known CIK for each ticker to its span(s).

    CIK is absent from Wikipedia's table before ~2014, so a span opened in,
    say, 2009 has no CIK at its start date even if the same company is still
    a member after 2014, once the column exists. Taking the latest non-null
    CIK observed anywhere in the ticker's history, rather than the value at
    span start, avoids losing that information.
    """
    all_rows = pd.concat(snapshots.values(), ignore_index=True)
    latest_cik = (
        all_rows.dropna(subset=["cik"])
        .groupby("ticker")["cik"]
        .last()
    )
    spans = spans.copy()
    spans["cik"] = spans["ticker"].map(latest_cik)
    return spans


def flag_left_censored(spans, first_observed_date):
    """Mark spans whose start_date is the first date this source can see.

    A span opening on the very first observed snapshot doesn't mean the
    company joined the index that day, only that it was already a member
    when observation began. The true join date predates the data and is
    unrecoverable from this source. Membership correctness is unaffected;
    only tenure length is unknown for these spans.
    """
    spans = spans.copy()
    spans["left_censored"] = spans["start_date"] == first_observed_date
    return spans


# ---------------------------------------------------------------------------
# The book era, 1996 to 2008
# ---------------------------------------------------------------------------

def load_book_snapshots(path=BOOK_CSV_PATH):
    """Load the book CSV's daily rows into the same {date: DataFrame} shape
    used for the Wikipedia snapshots, so build_spans works on either source
    unmodified.

    Tickers are kept exactly as the file reports them, including the
    BASE-YYYYMM suffix used when a ticker has since been recycled by a
    different company. Stripping it, the way the source repository's own
    cleaning script does, would merge two distinct companies' history under
    one symbol.
    """
    df = pd.read_csv(path)
    book_snapshots = {}
    for row in df.itertuples(index=False):
        tickers = row.tickers.split(",")
        book_snapshots[row.date] = pd.DataFrame({
            "ticker": tickers,
            "cik": pd.NA,
        })
    return book_snapshots


def base_ticker(ticker):
    """Strip the book CSV's BASE-YYYYMM disambiguation suffix, if present."""
    parts = ticker.split("-")
    return parts[0] if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 6 else ticker


def load_sec_ticker_cik(cache_path=SEC_TICKER_CIK_CACHE):
    """Fetch (or load cached) SEC's bulk ticker-to-CIK mapping.

    Free, no auth, roughly 10,000 entries. Only covers today's active
    registrants under today's current ticker, so it resolves a still-active
    company's present-day symbol (the book CSV's own convention for such
    companies) but can never resolve a ticker a company no longer trades
    under.
    """
    if cache_path.exists():
        sec_df = pd.read_parquet(cache_path)
        return dict(zip(sec_df["ticker"], sec_df["cik"]))

    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    sec_ticker_to_cik = {v["ticker"]: v["cik_str"] for v in data.values()}

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "ticker": list(sec_ticker_to_cik.keys()),
        "cik": list(sec_ticker_to_cik.values()),
    }).to_parquet(cache_path, index=False)

    return sec_ticker_to_cik


def backfill_book_cik(book_spans, sec_ticker_to_cik):
    """Attach CIK to book-era spans via SEC's current registry, where possible.

    Resolves any bare ticker still in use by an active filer today, which is
    most bare tickers here, since the source already labels active companies
    with their present day ticker. Cannot resolve a suffixed ticker, since
    that company is by definition no longer an active filer, an expected,
    explainable non-match.
    """
    book_spans = book_spans.copy()
    book_spans["cik"] = book_spans["ticker"].map(
        lambda t: sec_ticker_to_cik.get(base_ticker(t))
    )
    return book_spans


# ---------------------------------------------------------------------------
# ticker_history: symbol identity, separate from membership
# ---------------------------------------------------------------------------

def build_ticker_history_wiki(snapshots):
    """Build a (cik, ticker, start_date, end_date) history from the wiki snapshots.

    Unlike build_spans, which tracks membership, this tracks which ticker
    string a given CIK used over time. A CIK changing its associated ticker
    between two snapshots is a real, dated rename, verifiable because
    Wikipedia's ticker for each date is the one actually in use then. Rows
    with no CIK (pre-2014) can't be tracked this way; their tickers are
    still correct for membership purposes, just not linkable across a
    rename.

    Known limitation: Wikipedia's own reported CIK for a ticker occasionally
    changes across its edit history with no real trading discontinuity
    (Google/Alphabet's CIK moved from 1288776 to 1652044 around mid-2016;
    21st Century Fox/Fox Corp's similarly, 1754301/1308161), which this
    function does not detect, so such a company's rename history appears
    split across two CIKs rather than one. Resolving this by trusting each
    ticker string's latest reported CIK unconditionally was tried and
    reverted: it also merges tickers that were handed off between two
    genuinely different companies via a real merger (ACE Limited's CIK
    inheriting Chubb Corporation's old "CB" ticker in 2016; Johnson Controls
    and Tyco International's 2016 merger), fabricating an alternation
    pattern between two companies that were never concurrent. The signal
    that distinguishes the two cases, whether merging creates a new
    alternation pattern versus resolves one that already existed, is not
    yet implemented; see notebooks/logs/universe_construction.md.
    """
    all_rows = pd.concat(
        [df.assign(snapshot_date=date) for date, df in snapshots.items()],
        ignore_index=True,
    )
    tracked = all_rows.dropna(subset=["cik"]).sort_values("snapshot_date")

    history = []
    for cik, group in tracked.groupby("cik"):
        current_ticker = None
        start = None
        for _, row in group.iterrows():
            if row["ticker"] != current_ticker:
                if current_ticker is not None:
                    history.append((cik, current_ticker, start, row["snapshot_date"]))
                current_ticker = row["ticker"]
                start = row["snapshot_date"]
        history.append((cik, current_ticker, start, None))

    result = pd.DataFrame(history, columns=["cik", "ticker", "start_date", "end_date"])
    result["source"] = "wikipedia_revision"
    result["verified"] = True  # period-correct by construction
    return result


def fetch_former_names(cik):
    """Fetch a company's legal name history from SEC's submissions API.

    Returns a list of (name, from_date, to_date) tuples, empty if the
    company has never changed its legal name on record. Proxy signal only,
    not proof: a ticker can change without a legal renaming, which this
    would miss.
    """
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    return [(fn["name"], fn["from"][:10], fn["to"][:10]) for fn in data.get("formerNames", [])]


def load_former_names(ciks, cache_path=FORMER_NAMES_CACHE):
    """Fetch (or load cached) legal name history for a list of CIKs.

    Throttled to stay comfortably under SEC's fair-access limit
    (~10 requests/second).
    """
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    rows = []
    for i, cik in enumerate(ciks):
        try:
            for name, frm, to in fetch_former_names(cik):
                rows.append({"cik": cik, "former_name": name, "from_date": frm, "to_date": to})
        except Exception as e:
            logger.warning("former names fetch failed for CIK %s: %s", cik, e)
        if (i + 1) % 50 == 0:
            logger.info("%d/%d CIKs checked", i + 1, len(ciks))
        time.sleep(0.15)

    former_names = pd.DataFrame(rows, columns=["cik", "former_name", "from_date", "to_date"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    former_names.to_parquet(cache_path, index=False)
    return former_names


def flag_book_ticker_verification(book_spans, former_names):
    """Mark each book-era span as verified or flagged for manual review.

    Suffixed tickers are verified by default; the retroactive relabeling
    problem (a still-active company's present day ticker bleeding backward
    into its own earlier history) cannot apply to a company no longer
    active. A bare ticker is flagged if SEC records any former legal name
    for its CIK, deliberately over-inclusive rather than a tight date-range
    check, since a flagged entry costs a cheap manual look and a missed one
    would not. A bare ticker with no CIK match at all is flagged too: SEC's
    current registry not recognizing this exact symbol is itself evidence
    of a later rename or acquisition, not proof the label was safe.
    """
    book_spans = book_spans.copy()
    is_bare = book_spans["ticker"] == book_spans["ticker"].map(base_ticker)
    at_risk_ciks = set(former_names["cik"])
    no_cik_match = book_spans["cik"].isna()
    book_spans["verified"] = ~(is_bare & (book_spans["cik"].isin(at_risk_ciks) | no_cik_match))
    return book_spans


# ---------------------------------------------------------------------------
# Automated verification against SEC filings
# ---------------------------------------------------------------------------

def get_filing_history(cik):
    """Fetch a CIK's complete filing history, not just the recent ~1000 filings.

    The submissions endpoint's top-level filings.recent only covers a
    company's most recent filings; anything older is referenced under
    filings.files as separate paginated JSON files, which is where a
    company's 1990s-era 10-Ks actually live.
    """
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()

    recent = data["filings"]["recent"]
    rows = list(zip(recent["form"], recent["filingDate"], recent["accessionNumber"]))

    for f in data["filings"].get("files", []):
        page_url = f"https://data.sec.gov/submissions/{f['name']}"
        pr = requests.get(page_url, headers=SEC_HEADERS, timeout=10)
        pr.raise_for_status()
        page = pr.json()
        rows.extend(zip(page["form"], page["filingDate"], page["accessionNumber"]))

    return rows


def nearest_10k(history, target_date, max_gap_days=MAX_FILING_GAP_DAYS):
    """Pick the 10-K-type filing closest to target_date.

    Returns None if the closest available filing is still more than
    max_gap_days away, since a distant filing isn't evidence about the span
    at all, and reporting it as a "found filing" would be misleading.
    """
    candidates = [(f, d, a) for f, d, a in history if f.startswith("10-K")]
    if not candidates:
        return None
    target = pd.Timestamp(target_date)
    candidates.sort(key=lambda row: abs(pd.Timestamp(row[1]) - target))
    nearest = candidates[0]
    gap = abs(pd.Timestamp(nearest[1]) - target)
    if gap > pd.Timedelta(days=max_gap_days):
        return None
    return nearest


def fetch_filing_text(cik, accession):
    """Fetch a filing's complete submission text file.

    Old EDGAR filings aren't valid UTF-8; decoding as latin-1, which never
    raises on arbitrary bytes, avoids encoding errors on this older data.
    """
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}.txt"
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    return r.content.decode("latin-1")


def extract_ticker_mentions(text):
    """Find candidate ticker mentions, tolerating quotes, colons, and paired tickers.

    Tickers are frequently quoted in older filings ('symbol "HP."') or
    listed factsheet-style ('Symbol: PMTC'), and a single sentence sometimes
    discloses two at once for a dual class or tracking stock structure
    ('ticker symbols "PZB" and "PZX"'). Only "symbol(s)" itself is matched
    case-insensitively; each captured ticker must still be genuinely
    all-caps in the source text, or ordinary lowercase words right after
    "symbol" get mistaken for tickers.
    """
    pattern = re.compile(
        r'.{0,60}(?i:symbols?)\s*:?\s*'
        r'["\']?([A-Z]{1,5})[.,]?["\']?'
        r'(?:\s*(?:and|,)\s*["\']?([A-Z]{1,5})[.,]?["\']?)?'
        r'.{0,40}'
    )
    matches = []
    for m in pattern.finditer(text):
        for ticker in m.groups():
            if ticker:
                matches.append((ticker, m.group(0).strip()))
    return matches


def find_ticker_in_filing(cik, target_date):
    """Find the ticker actually disclosed in a filing near target_date.

    Returns None if no 10-K exists near this date, a dict with an "error"
    key if a fetch failed, or a dict carrying the filing's identity and
    matched evidence, so a failure is a reported gap rather than a guess.
    """
    try:
        history = get_filing_history(cik)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    filing = nearest_10k(history, target_date)
    if filing is None:
        return None

    form, filing_date, accession = filing
    try:
        text = fetch_filing_text(cik, accession)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    return {
        "form": form,
        "filing_date": filing_date,
        "accession": accession,
        "mentions": extract_ticker_mentions(text),
    }


def run_filing_verification(book_spans, cache_path=FILING_VERIFICATION_CACHE):
    """Check every flagged, CIK-matched book-era span against its own SEC filings.

    Classifies each into confirmed_match, confirmed_mismatch,
    confirmed_mismatch_ambiguous (multiple candidate tickers, e.g. a
    tracking stock or dual class split, left for a person to resolve),
    no_pattern_match, or no_filing_found. Roughly 2 to 3 requests per span;
    throttled and cached.
    """
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    to_check = book_spans[(~book_spans["verified"]) & book_spans["cik"].notna()]
    logger.info("%d flagged, CIK-matched spans to check against SEC filings", len(to_check))

    rows = []
    for i, (_, row) in enumerate(to_check.iterrows()):
        result = find_ticker_in_filing(row["cik"], row["start_date"])
        base = {"ticker": row["ticker"], "cik": row["cik"],
                "start_date": row["start_date"], "end_date": row["end_date"]}

        if result is None:
            rows.append({**base, "status": "no_filing_found", "candidate": None,
                         "evidence": None, "accession": None})
        elif "error" in result:
            rows.append({**base, "status": "fetch_error", "candidate": None,
                         "evidence": result["error"], "accession": None})
        elif not result["mentions"]:
            rows.append({**base, "status": "no_pattern_match", "candidate": None,
                         "evidence": None, "accession": result["accession"]})
        else:
            candidates = {t for t, _ in result["mentions"]}
            if row["ticker"] in candidates:
                status = "confirmed_match"
            elif len(candidates) == 1:
                status = "confirmed_mismatch"
            else:
                status = "confirmed_mismatch_ambiguous"
            rows.append({**base, "status": status, "candidate": ", ".join(sorted(candidates)),
                         "evidence": result["mentions"][0][1], "accession": result["accession"]})

        if (i + 1) % 25 == 0:
            logger.info("%d/%d checked", i + 1, len(to_check))
        time.sleep(0.3)

    filing_verification = pd.DataFrame(rows)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    filing_verification.to_parquet(cache_path, index=False)
    return filing_verification


def apply_filing_verification(ticker_history, filing_verification):
    """Apply the SEC filing verification results back into ticker_history.

    confirmed_match spans get a stronger verified status backed by an
    actual citation, not just the absence of a red flag. confirmed_mismatch
    spans get their ticker corrected, with the original book label and the
    filing citation kept alongside rather than silently overwritten, so the
    correction stays auditable. confirmed_mismatch_ambiguous spans are left
    untouched: multiple candidate tickers (a dual class or tracking stock
    split) need a person to pick the right one, not an automatic choice.
    Everything else is left exactly as it was, an honestly unresolved gap.
    """
    ticker_history = ticker_history.copy()
    ticker_history["original_ticker"] = pd.NA
    ticker_history["evidence"] = pd.NA

    for _, row in filing_verification.iterrows():
        mask = (
            (ticker_history["source"] == "clenow_norgate")
            & (ticker_history["cik"] == row["cik"])
            & (ticker_history["start_date"] == row["start_date"])
        )
        if row["status"] == "confirmed_match":
            ticker_history.loc[mask, "verified"] = True
            ticker_history.loc[mask, "evidence"] = f"{row['accession']}: {row['evidence']}"
        elif row["status"] == "confirmed_mismatch":
            ticker_history.loc[mask, "original_ticker"] = ticker_history.loc[mask, "ticker"]
            ticker_history.loc[mask, "ticker"] = row["candidate"]
            ticker_history.loc[mask, "verified"] = True
            ticker_history.loc[mask, "evidence"] = f"{row['accession']}: {row['evidence']}"

    return ticker_history


# ---------------------------------------------------------------------------
# Combining both eras
# ---------------------------------------------------------------------------

def combine_universe_spans(book_spans, spans_with_cik,
                            boundary_date=WIKI_ERA_START, book_era_end=BOOK_ERA_END):
    """Concatenate both eras' spans, stitching any membership that straddles
    the boundary where the two sources meet into a single row.

    A book-era span left open at the boundary (no exit observed, only
    because the book data stops there) and a wiki-era span opening exactly
    at the boundary, sharing a CIK, are one continuous membership recorded
    by two different sources, not two real events. Left as two adjacent
    rows when no shared CIK confirms it, most often because the book-era
    company has no CIK match at all (typically delisted before 2008, never
    reaching Wikipedia's coverage). A book-era span left open with no
    continuing wiki-era entry has its end_date capped at book_era_end,
    the last date the book source was actually observed: leaving it null
    would claim the company is still active today, which only holds for
    the wiki era, where the most recent snapshot is close to today.
    """
    book_open = book_spans[book_spans["end_date"].isna() & book_spans["cik"].notna()]
    wiki_at_boundary = spans_with_cik[
        (spans_with_cik["start_date"] == boundary_date) & spans_with_cik["cik"].notna()
    ]
    stitch_ciks = set(book_open["cik"]) & set(wiki_at_boundary["cik"])
    logger.info("%d memberships stitched across the 2008 boundary", len(stitch_ciks))

    stitched = []
    for cik in stitch_ciks:
        book_row = book_open[book_open["cik"] == cik].iloc[0]
        wiki_row = wiki_at_boundary[wiki_at_boundary["cik"] == cik].iloc[0]
        stitched.append({
            "ticker": wiki_row["ticker"],
            "cik": cik,
            "start_date": book_row["start_date"],
            "end_date": wiki_row["end_date"],
            "source": "clenow_norgate+wikipedia_revision",
            "left_censored": book_row["left_censored"],
        })
    stitched_df = pd.DataFrame(stitched)

    book_remaining = book_spans[~(
        book_spans["end_date"].isna() & book_spans["cik"].isin(stitch_ciks)
    )].copy()
    still_open = book_remaining["end_date"].isna()
    logger.info("%d book-era spans left open with no continuing wiki entry, capped at %s",
                still_open.sum(), book_era_end)
    book_remaining.loc[still_open, "end_date"] = book_era_end
    book_remaining = book_remaining.assign(source="clenow_norgate")

    wiki_remaining = spans_with_cik[~(
        (spans_with_cik["start_date"] == boundary_date) & spans_with_cik["cik"].isin(stitch_ciks)
    )].assign(source="wikipedia_revision")

    universe_spans = pd.concat([book_remaining, wiki_remaining, stitched_df], ignore_index=True)
    universe_spans["cik"] = universe_spans["cik"].astype("Int64")
    return universe_spans[["ticker", "cik", "start_date", "end_date", "source", "left_censored"]]


# ---------------------------------------------------------------------------
# Public read helpers: cheap, local, meant to be called often
# ---------------------------------------------------------------------------

def membership_on(universe_spans, date_iso):
    """Return the set of tickers that were S&P 500 members on date_iso."""
    active = universe_spans[
        (universe_spans["start_date"] <= date_iso)
        & (universe_spans["end_date"].isna() | (universe_spans["end_date"] >= date_iso))
    ]
    return set(active["ticker"])


def ticker_on(ticker_history, cik, date_iso):
    """Return the vendor-facing ticker a CIK traded under on date_iso, or None.

    Use this, not universe_spans["ticker"] directly, when a real symbol is
    needed for a price vendor call: universe_spans reports whatever string
    its source used, which for the book era may be a retroactively applied
    later ticker (see universe_construction.md); ticker_history is what
    tracks the actual symbol in force on a given date.
    """
    match = ticker_history[
        (ticker_history["cik"] == cik)
        & (ticker_history["start_date"] <= date_iso)
        & (ticker_history["end_date"].isna() | (ticker_history["end_date"] >= date_iso))
    ]
    if match.empty:
        return None
    return match.iloc[0]["ticker"]


# ---------------------------------------------------------------------------
# The build: expensive, network-bound, meant to be run occasionally
# ---------------------------------------------------------------------------

def build_universe(force_refresh=False):
    """Build (or load) universe_spans and ticker_history.

    Loads data/processed/universe_spans.parquet and ticker_history.parquet
    directly if both already exist and force_refresh is False, the common
    case, since index membership changes slowly and rebuilding is only
    needed when deliberately refreshing the data. Otherwise runs the full
    pipeline: Wikipedia snapshots (2008 on) and the book CSV (1996 to 2008),
    each turned into spans, CIK attached, the book era checked against SEC's
    legal name history and, where possible, its own historical filings, then
    both eras combined with boundary stitching.

    Returns (universe_spans, ticker_history).
    """
    if not force_refresh and UNIVERSE_SPANS_PATH.exists() and TICKER_HISTORY_PATH.exists():
        return pd.read_parquet(UNIVERSE_SPANS_PATH), pd.read_parquet(TICKER_HISTORY_PATH)

    _ensure_ssl_context()

    # --- 2008 to present: Wikipedia ---
    snapshots = fetch_wiki_snapshots()
    spans = build_spans(snapshots)
    spans_with_cik = attach_cik(spans, snapshots)
    spans_with_cik = flag_left_censored(spans_with_cik, WIKI_ERA_START)

    wiki_ticker_history = build_ticker_history_wiki(snapshots)

    # --- 1996 to 2008: the book file ---
    book_snapshots = load_book_snapshots()
    book_snapshots_pre2008 = {
        date: df for date, df in book_snapshots.items() if date < WIKI_ERA_START
    }
    book_spans = build_spans(book_snapshots_pre2008)
    book_spans = flag_left_censored(book_spans, BOOK_ERA_FIRST_DATE)

    sec_ticker_to_cik = load_sec_ticker_cik()
    book_spans = backfill_book_cik(book_spans, sec_ticker_to_cik)

    bare_ciks = book_spans.loc[
        book_spans["ticker"] == book_spans["ticker"].map(base_ticker), "cik"
    ].dropna().unique()
    former_names = load_former_names(bare_ciks)
    book_spans = flag_book_ticker_verification(book_spans, former_names)

    # --- Automated verification against SEC filings ---
    filing_verification = run_filing_verification(book_spans)

    book_ticker_history = book_spans[
        ["cik", "ticker", "start_date", "end_date", "verified"]
    ].copy()
    book_ticker_history["source"] = "clenow_norgate"

    ticker_history = pd.concat([book_ticker_history, wiki_ticker_history], ignore_index=True)
    ticker_history["cik"] = ticker_history["cik"].astype("Int64")
    ticker_history = apply_filing_verification(ticker_history, filing_verification)

    # --- Combine ---
    universe_spans = combine_universe_spans(book_spans, spans_with_cik)

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    universe_spans.to_parquet(UNIVERSE_SPANS_PATH, index=False)
    ticker_history.to_parquet(TICKER_HISTORY_PATH, index=False)

    return universe_spans, ticker_history
