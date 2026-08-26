"""OLS helpers for chart 3, with cluster-robust SEs. Self-tested in c3_selftest.py."""
import numpy as np
from scipy import stats as sps


def ols(X, y):
    """Plain OLS. X includes its own intercept column. Returns dict."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    dof = n - k
    sigma2 = (resid @ resid) / dof
    cov = sigma2 * XtX_inv
    se = np.sqrt(np.diag(cov))
    t = beta / se
    p = 2 * sps.t.sf(np.abs(t), dof)
    ybar = y.mean()
    ss_tot = ((y - ybar) ** 2).sum()
    ss_res = resid @ resid
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return dict(beta=beta, se=se, t=t, p=p, resid=resid, dof=dof, r2=r2,
                XtX_inv=XtX_inv, n=n, k=k, sigma2=sigma2)


def ols_cluster(X, y, groups):
    """OLS with cluster-robust (CR1) sandwich SEs."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    groups = np.asarray(groups)
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    uniq = np.unique(groups)
    G = len(uniq)
    meat = np.zeros((k, k))
    for g in uniq:
        m = groups == g
        Xg = X[m]
        ug = resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    c = (G / (G - 1.0)) * ((n - 1.0) / (n - k))
    cov = c * (XtX_inv @ meat @ XtX_inv)
    se = np.sqrt(np.diag(cov))
    t = beta / se
    dof = G - 1
    p = 2 * sps.t.sf(np.abs(t), dof)
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1.0 - (resid @ resid) / ss_tot if ss_tot > 0 else np.nan
    return dict(beta=beta, se=se, t=t, p=p, r2=r2, n=n, k=k, n_clusters=G, dof=dof)


def wls(X, y, w):
    """Weighted least squares, weights w (e.g. 1/SE^2)."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    w = np.asarray(w, float)
    sw = np.sqrt(w)
    Xw = X * sw[:, None]
    yw = y * sw
    return ols(Xw, yw)


def simple_fit(x, y):
    """Bivariate OLS with intercept -> slope, t, r2, p, plus leverage & Cook's D."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    X = np.column_stack([np.ones_like(x), x])
    r = ols(X, y)
    H_diag = np.einsum("ij,jk,ik->i", X, r["XtX_inv"], X)
    e = r["resid"]
    mse = r["sigma2"]
    cook = (e ** 2 / (r["k"] * mse)) * (H_diag / (1.0 - H_diag) ** 2)
    return dict(intercept=r["beta"][0], slope=r["beta"][1],
                se_slope=r["se"][1], t_slope=r["t"][1], p_slope=r["p"][1],
                r2=r["r2"], n=r["n"], dof=r["dof"],
                leverage=H_diag, cook=cook, resid=e)
