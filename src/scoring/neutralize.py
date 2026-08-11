"""Beta neutralization: residualizing a combined factor score against beta.

Built and validated in notebooks/exploring_factors.ipynb, Part 11.
"""

import pandas as pd


def neutralize(scores, betas):
    """Regress the combined factor score against beta, cross sectionally,
    and return the residual: what the score doesn't already explain via
    beta, which is what ranking should use per the README's beta
    neutralization rule.

    Refit fresh from whatever scores and betas are passed in, never reused
    across dates: the regression coefficients are allowed, and expected,
    to change from one rebalance date to the next.

    A stock missing either its score or its beta is excluded from fitting
    the regression (there's nothing to fit a relationship from), and its
    residual comes back as NaN automatically, since intercept + slope * NaN
    propagates to NaN through the final subtraction without needing an
    explicit check.

    Confirmed against a toy case (Part 11): three stocks fitting a line
    with slope 2.5, intercept -2, giving residuals 0.5, -1.0, 0.5, and a
    fourth missing its score entirely, correctly excluded from the fit and
    returned as NaN.
    """
    valid = scores.notna() & betas.notna()
    x = betas[valid]
    y = scores[valid]

    slope = x.cov(y) / x.var()
    intercept = y.mean() - slope * x.mean()

    return scores - (intercept + slope * betas)
