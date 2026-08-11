"""Debt issuance factor (proxy): percent change in total debt, year over year.

Built and validated in notebooks/exploring_factors.ipynb, Part 3p.
"""

from src.loaders.fundamentals import latest_value_as_of


def debt_issuance_factor(facts, as_of, periods_back=4):
    """Raw debt issuance factor (proxy): percent change in total debt
    (long term, current plus noncurrent) between the most recent balance
    sheet and the one roughly a year earlier.

    A proxy, not the literature's precise definition (Bradshaw, Richardson,
    Sloan 2006): the precise version nets cash-flow-statement proceeds
    from debt issuance against repayments during the period, capturing
    actual financing activity. This measures the balance outstanding
    instead, which can move for reasons unrelated to issuance (FX
    translation on foreign debt, fair value remeasurement, a noncurrent
    tranche reclassified to current, or a lease accounting standard
    change folding new leases into the long term debt tags) and misses
    a same-period issuance-and-repayment refinancing entirely, since
    that leaves the balance unchanged. Built as a proxy deliberately: per
    the README's build order reasoning, whether the imprecision here
    matters enough to justify the loader work a precise version needs is
    a question for the step 6 IC pass, not something to guess at before
    any measurement exists.

    Same offset=4 mechanism as investment_factor, for the same reason:
    long_term_debt_noncurrent and long_term_debt_current are both instant
    concepts reported every quarter, so offset=4 is what reaches roughly
    a year back for a filer reporting all four quarters separately.
    Missing long_term_debt_current specifically (in either period) is
    treated as zero, not as missing data, same reasoning as
    leverage_factor.

    Confirmed against a real 60-company sample (Part 3p): ORCL at the top
    of the observed range matches its well documented 2024 bond issuance
    funding OCI data center buildout for AI workloads; FFIV at exactly
    -1.0 is a clean full debt payoff. The spread here (std 0.83) is much
    wider than investment_factor's (std 0.29) on the same sample, a real
    property of a balance based proxy rather than noise to explain away:
    a company paying off all its debt is a clean -100%, while a small
    existing balance plus a large new raise can swing well past +300%.

    Returns None if total debt is unresolvable (both debt concepts
    missing) for either period, or if the prior period's total debt is
    exactly zero.
    """
    def _total_debt(offset):
        noncurrent = latest_value_as_of(facts, "long_term_debt_noncurrent", "USD", as_of, offset=offset)
        current = latest_value_as_of(facts, "long_term_debt_current", "USD", as_of, offset=offset)
        if noncurrent is None and current is None:
            return None
        return (noncurrent[0] if noncurrent else 0) + (current[0] if current else 0)

    current_debt = _total_debt(0)
    prior_debt = _total_debt(periods_back)
    if current_debt is None or prior_debt is None or prior_debt == 0:
        return None
    return (current_debt - prior_debt) / prior_debt
