"""Model 1 and 2: where do incidents start climbing, and how long after the strain?

Poisson regression of weekly outage episodes on a ramp of the lagged capacity index:
rate = exposure * exp(a + b * ramp + g * wear), ramp = clip((knot - index[t - lag]) / width, 0, 1).
The knot is the tipping point, the width is how fast the ramp saturates, and the
lag is the lead time. All three are found by grid search on the likelihood.
Intervals use the profile likelihood, widened by the overdispersion. Pure numpy.
"""

import numpy as np

from horizon.models.features import capacity_index, lag, wear_proxy

KNOTS = np.round(np.arange(0.40, 1.001, 0.01), 2)
WIDTHS = [0.05, 0.10, 0.15, 0.20, 0.30]
LAGS = list(range(0, 13))
CI_DROP = 1.92  # 95 percent interval from the profile likelihood (chi-square, 1 df)


def poisson_fit(X, y, offset, iters=60):
    beta = np.zeros(X.shape[1])
    beta[0] = np.log(max(y.sum(), 0.5) / np.exp(offset).sum())

    def loglik(b):
        eta = np.clip(X @ b + offset, -30, 30)
        return float(np.sum(y * eta - np.exp(eta)))

    cur = loglik(beta)
    for _ in range(iters):
        mu = np.exp(np.clip(X @ beta + offset, -30, 30))
        grad = X.T @ (y - mu)
        hess = (X * mu[:, None]).T @ X + 1e-8 * np.eye(len(beta))
        step = np.linalg.solve(hess, grad)
        t = 1.0
        while t > 1e-4 and loglik(beta + t * step) < cur:
            t /= 2
        beta = beta + t * step
        new = loglik(beta)
        if abs(new - cur) < 1e-10:
            cur = new
            break
        cur = new
    return beta, cur


def _lagged_by_team(tw, idx, weeks):
    out = np.empty(len(idx))
    for t in np.unique(tw["team_id"]):
        m = tw["team_id"] == t
        out[m] = lag(idx[m], weeks)
    return out


def fit_tipping_point(tw, exposure, outcome="detected_outage_episodes"):
    idx, wear, y = capacity_index(tw), wear_proxy(tw), tw[outcome].astype(float)
    off = np.log(exposure)
    null_ll = poisson_fit(np.column_stack([np.ones(len(y)), wear]), y, off)[1]
    ll = np.full((len(KNOTS), len(WIDTHS), len(LAGS)), -np.inf)
    best = (-np.inf, None, None)
    for c, w in enumerate(LAGS):
        li = _lagged_by_team(tw, idx, w)
        for b_, wd in enumerate(WIDTHS):
            for a_, k in enumerate(KNOTS):
                X = np.column_stack([np.ones(len(y)), np.clip((k - li) / wd, 0, 1), wear])
                beta, val = poisson_fit(X, y, off)
                if beta[1] > 0:
                    ll[a_, b_, c] = val
                    if val > best[0]:
                        best = (val, (a_, b_, c), beta)
    val, (a_, b_, c), beta = best
    li = _lagged_by_team(tw, idx, LAGS[c])
    X = np.column_stack([np.ones(len(y)), np.clip((KNOTS[a_] - li) / WIDTHS[b_], 0, 1), wear])
    mu = np.exp(X @ beta + off)
    phi = max(1.0, float(np.sum((y - mu) ** 2 / np.maximum(mu, 1e-9)) / (len(y) - 3)))
    drop = CI_DROP * phi
    knot_prof = ll.max(axis=(1, 2)) - val
    lag_prof = ll.max(axis=(0, 1)) - val
    return {
        "knot": float(KNOTS[a_]), "knot_ci": (float(KNOTS[knot_prof >= -drop].min()), float(KNOTS[knot_prof >= -drop].max())),
        "width": float(WIDTHS[b_]), "lag_weeks": int(LAGS[c]),
        "lag_ci": (int(np.array(LAGS)[lag_prof >= -drop].min()), int(np.array(LAGS)[lag_prof >= -drop].max())),
        "rate_multiplier_at_full_strain": float(np.exp(beta[1])), "wear_coef": float(beta[2]),
        "overdispersion": phi, "lr_vs_no_tipping_point": float(2 * (val - null_ll)),
        "profile_knots": KNOTS, "profile_ll": knot_prof,
        "profile_lags": np.array(LAGS), "profile_lag_ll": lag_prof,
    }
