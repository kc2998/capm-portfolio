"""Curated real-company panel for validating fundamentals-dependent code against known hard
cases, not just a random sample.

Each entry was chosen because it exercises a specific, documented failure mode in the
fundamentals loader (see notebooks/logs/fundamentals_construction.md): a fiscal calendar
shape, a share structure ambiguity, a tag-naming era transition, a business model with no
gross profit line, or (CCU-200807) a foreign filer that returns None for every us-gaap
concept. Originally built in notebooks/validating_fundamentals.ipynb; factored out here so
notebooks/exploring_factors.ipynb can check factor code against the same known-hard cases
too, rather than relying only on a random sample, which could go a long time without ever
hitting one of these by chance.
"""

PANEL = [
    ("AAPL", "fiscal calendar", "52/53 week year ending late September; also the real 27% FY2008 restatement"),
    ("COST", "fiscal calendar", "a 12-12-12-16 week retail year, so quarters run 83 days and the fourth 111"),
    ("KO",   "fiscal calendar", "conventional calendar year consumer goods filer, the control case"),
    ("GOOGL", "share structure", "dual class that does tag a combined undimensioned count; also the mid-history LongTermDebt switch and a 20:1 split"),
    ("META", "share structure", "dual class with no undimensioned share count in either taxonomy"),
    ("DASH", "filing era",      "first filed after ASC 606: no Revenues, no GrossProfit, convertible debt tags, no share count"),
    ("MWV",  "filing era",      "pre-2018 filer using the deprecated SalesRevenueNet tag; since departed"),
    ("CCU-200807", "taxonomy and currency", "universe misattribution to a foreign private issuer: files 20-F under ifrs-full in CLP, so every us-gaap alias returns None while coverage still records fetched: True"),
    ("JPM",  "business model",  "bank, calendar year end; FY2021 net income revised at the same duration"),
    ("FITB", "business model",  "bank with no revenue tag under any alias"),
    ("ACGL", "business model",  "insurer: revenue present, no gross profit path"),
    ("INVH", "business model",  "REIT reporting a predecessor and a successor entity either side of a 2017 reorganisation"),
    ("KKR",  "business model",  "alternative asset manager, no gross profit path"),
    ("CMG",  "business model",  "restaurant: operating costs presented without a gross profit subtotal"),
    ("CEG",  "business model",  "utility, no gross profit path"),
    ("KSU",  "index status",    "railroad, acquired and departed; no gross profit path"),
    ("MCK",  "known pathology", "reports Assets and StockholdersEquity but never an explicit Liabilities tag"),
    ("FAST", "known pathology", "the same balance sheet identity case, confirmed directly in Part 9"),
    # Added by the tag alias work in Decision B. Each of these froze at an old period
    # under the tag TAG_ALIASES knew about, because an accounting standard moved most
    # filers to a different tag name at once, and each is the company its fix is
    # verified against in section 5.3.
    ("CSX",  "tag era",         "ASU 2009-17 moved equity to the noncontrolling interest inclusive tag; 4 points under the old name, 267 under the new"),
    ("ITW",  "tag era",         "the same equity tag switch, verified independently of CSX"),
    ("HD",   "tag era",         "ASC 842 folded finance leases into the long term debt tags; both plain tags stop in 2017"),
    ("LOW",  "tag era",         "the same lease inclusive debt switch"),
    ("DTE",  "tag era",         "the same lease inclusive debt switch, in a utility"),
    ("TSN",  "tag era",         "moved current debt to the shorter DebtCurrent instead, and tags only the diluted weighted average share count"),
    ("DHR",  "tag era",         "both the equity switch and the DebtCurrent route"),
    ("HOG",  "tag era",         "tagged revenue as SalesRevenueNet before 2013, unresolvable until that alias was added"),
    ("WAT",  "known pathology", "last tagged current debt at exactly 0 and stopped re-confirming it: a genuine zero, not a missing alias"),
    ("DOV",  "known pathology", "no direct Liabilities tag since 2009, so total liabilities resolves only through the balance sheet identity"),
]

# Where ticker_history maps a panel ticker to more than one CIK, the ambiguity is resolved here
# explicitly rather than inside the lookup, so the reason sits next to the choice. GOOGL is the
# case the universe log documents: an administrative reorganisation moved the reporting entity
# from Google Inc (1288776) to Alphabet Inc (1652044) in 2015 with no trading discontinuity, and
# 1652044 is the entity every finding in the fundamentals log was established against.
CIK_OVERRIDES = {"GOOGL": 1652044}


def ciks_for_ticker(ticker, ticker_history):
    """Reverse of ticker_on: which entities ever used a symbol.

    Returns every match on purpose. More than one means either the documented universe-module
    CIK misattribution or a genuinely recycled symbol, and silently taking the first would hide
    both.
    """
    matches = ticker_history.loc[ticker_history["ticker"] == ticker, "cik"].dropna().unique()
    return sorted(int(c) for c in matches)


def resolve_panel_ciks(ticker_history):
    """Resolve every PANEL ticker to exactly one CIK, using CIK_OVERRIDES to break a genuine
    ambiguity in ticker_history rather than picking one silently.

    Returns a list of (ticker, cik, axis, why) tuples, one per panel member. Raises if a
    ticker resolves to more than one CIK with no override, since that is exactly the kind of
    silent ambiguity this panel exists to surface, not paper over.
    """
    resolved = []
    for ticker, axis, why in PANEL:
        ciks = ciks_for_ticker(ticker, ticker_history)
        if ticker in CIK_OVERRIDES:
            cik = CIK_OVERRIDES[ticker]
        elif len(ciks) == 1:
            cik = ciks[0]
        else:
            raise ValueError(f"{ticker}: {len(ciks)} CIKs, needs a CIK_OVERRIDES entry")
        resolved.append((ticker, cik, axis, why))
    return resolved
