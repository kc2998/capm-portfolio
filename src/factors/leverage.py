"""Low leverage factor: total debt over stockholders' equity.

Built and validated in notebooks/exploring_factors.ipynb, Part 3o.
"""

from src.loaders.fundamentals import latest_value_as_of


def leverage_factor(facts, as_of):
    """Raw low leverage factor: total debt (long term, current plus
    noncurrent) over stockholders' equity.

    Named "low leverage" in the README and the JKP taxonomy because low
    values of this ratio are the ones associated with the premium, the
    same convention as low_vol_factor: this function returns the plain
    debt-to-equity ratio itself, not its negative, since which direction
    to bet is a decision for the alpha model later, not baked into a raw
    factor's sign here.

    Missing long_term_debt_current specifically is treated as zero, not
    as missing data: fundamentals.py's own documentation established this
    concept is frequently and legitimately zero and often left untagged
    once it is, not evidence of unresolvable data. Missing
    long_term_debt_noncurrent is treated the same way for symmetry,
    though it's a much rarer case in practice. Only a company with no
    resolvable debt tag at all makes this factor unresolvable.

    Like quality.py's stockholders_equity, a non-positive value there is
    not filtered out: negative book equity is real, common data
    (leveraged buybacks), not an error, left for scoring/zscore.py and
    later IC measurement to handle. Equity of exactly zero is the one
    case still guarded against, since dividing by it would raise rather
    than produce a meaningful ratio.

    Confirmed against a real 60-company sample (Part 3o): MO and DPZ
    showing negative leverage matches their well documented negative
    book equity from years of buybacks. IRM at the extreme (685.6) is
    real too: only $18.5M in stockholders' equity against $12.7B in
    total debt, a genuine, thin-equity characteristic of REIT accounting
    (REITs distribute most taxable income as dividends, depleting
    retained earnings toward zero even for healthy companies), exactly
    the kind of case winsorization exists to handle downstream.

    Returns None if stockholders' equity cannot be resolved or is
    exactly zero, or if both debt concepts are unresolvable.
    """
    noncurrent = latest_value_as_of(facts, "long_term_debt_noncurrent", "USD", as_of)
    current = latest_value_as_of(facts, "long_term_debt_current", "USD", as_of)
    if noncurrent is None and current is None:
        return None
    total_debt = (noncurrent[0] if noncurrent else 0) + (current[0] if current else 0)

    equity = latest_value_as_of(facts, "stockholders_equity", "USD", as_of)
    if equity is None or equity[0] == 0:
        return None
    return total_debt / equity[0]
