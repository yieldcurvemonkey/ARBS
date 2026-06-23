"""Cross-sectional fitted-curve rich/cheap module for a rates RV toolkit.

Closure-factory pattern mirroring ``make_pca_rv_builder`` in ``pca_rv.py``.
Pure pandas / numpy / scipy — no pricing, no IO.

Usage (snapshot)::

    fit, residual, rank, rmse, otr_spread, get_data = make_curve_fit_builder(
        df, id_col="cusip", form="nss"
    )
    fit()
    res = residual()           # Series indexed by id; >0 => cheap
    z   = res.zscore(60)       # not applicable for snapshots; panel: per-bond rolling z
    r   = rank()               # most-cheap first
    m   = rmse()               # float (snapshot) or Series (panel)

Usage (panel)::

    fit, residual, rank, rmse, otr_spread, get_data = make_curve_fit_builder(
        df, id_col="cusip", date_col="date", form="nss"
    )
    fit()
    resid_ns = residual()
    z = resid_ns.zscore(window=60)   # DataFrame bonds×dates rolling z

Curve forms
-----------
"ns"     Nelson-Siegel (4 params)
"nss"    Nelson-Siegel-Svensson (6 params)
"spline" Smoothing cubic spline
"linear" OLS line  y ~ a + b*maturity
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import numpy as np
import pandas as pd
from scipy.interpolate import UnivariateSpline
from scipy.optimize import least_squares


# ---------------------------------------------------------------------------
# Curve-form implementations (pure functions)
# ---------------------------------------------------------------------------

def _ns_yield(tau: np.ndarray, b0: float, b1: float, b2: float, lam: float) -> np.ndarray:
    tau = np.asarray(tau, dtype=float)
    x = tau / lam
    f1 = (1.0 - np.exp(-x)) / x
    f2 = f1 - np.exp(-x)
    return b0 + b1 * f1 + b2 * f2


def _nss_yield(tau: np.ndarray, b0: float, b1: float, b2: float, b3: float,
               lam: float, lam2: float) -> np.ndarray:
    tau = np.asarray(tau, dtype=float)
    x1 = tau / lam
    x2 = tau / lam2
    f1 = (1.0 - np.exp(-x1)) / x1
    f2 = f1 - np.exp(-x1)
    f3 = (1.0 - np.exp(-x2)) / x2 - np.exp(-x2)
    return b0 + b1 * f1 + b2 * f2 + b3 * f3


def _fit_ns(maturities: np.ndarray, yields: np.ndarray, weights: Optional[np.ndarray],
            loss: str) -> np.ndarray:
    """Fit Nelson-Siegel; return fitted yields."""
    m_mean = float(np.mean(yields))
    m_short = float(yields[maturities == maturities.min()].mean()) if maturities.size > 0 else m_mean
    p0 = [m_mean, m_short - m_mean, 0.0, 2.0]
    bounds_lo = [-np.inf, -np.inf, -np.inf, 0.05]
    bounds_hi = [np.inf,  np.inf,  np.inf, 30.0]

    def residuals(p):
        b0, b1, b2, lam = p
        r = _ns_yield(maturities, b0, b1, b2, lam) - yields
        if weights is not None:
            r = r * weights
        return r

    ls_loss = "soft_l1" if loss == "lad" else "linear"
    res = least_squares(residuals, p0, bounds=(bounds_lo, bounds_hi), loss=ls_loss, max_nfev=10000)
    b0, b1, b2, lam = res.x
    return _ns_yield(maturities, b0, b1, b2, lam)


def _fit_nss(maturities: np.ndarray, yields: np.ndarray, weights: Optional[np.ndarray],
             loss: str) -> np.ndarray:
    """Fit Nelson-Siegel-Svensson; return fitted yields.

    Tries multiple random initialisations to reduce local-minima sensitivity.
    """
    m_mean = float(np.mean(yields))
    m_short = float(yields[maturities == maturities.min()].mean()) if maturities.size > 0 else m_mean

    ls_loss = "soft_l1" if loss == "lad" else "linear"

    def residuals(p):
        b0, b1, b2, b3, lam, lam2 = p
        r = _nss_yield(maturities, b0, b1, b2, b3, lam, lam2) - yields
        if weights is not None:
            r = r * weights
        return r

    bounds_lo = [-np.inf, -np.inf, -np.inf, -np.inf, 0.05, 0.05]
    bounds_hi = [np.inf,  np.inf,  np.inf,  np.inf, 30.0, 30.0]

    # Multiple starts to improve convergence
    starts = [
        [m_mean, m_short - m_mean, 0.0, 0.0, 2.0, 5.0],
        [m_mean, m_short - m_mean, 1.0, 0.5, 1.5, 4.0],
        [m_mean, m_short - m_mean, -1.0, 1.0, 3.0, 8.0],
        [m_mean, 0.0, 0.5, 0.5, 2.0, 5.0],
    ]

    best_cost = np.inf
    best_fitted = None
    for p0 in starts:
        try:
            res = least_squares(residuals, p0, bounds=(bounds_lo, bounds_hi),
                                loss=ls_loss, max_nfev=20000, ftol=1e-12, xtol=1e-12)
            if res.cost < best_cost:
                best_cost = res.cost
                best_fitted = _nss_yield(maturities, *res.x)
        except Exception:
            continue

    if best_fitted is None:
        raise RuntimeError("NSS optimisation failed for all starting points.")
    return best_fitted


def _fit_spline(maturities: np.ndarray, yields: np.ndarray,
                weights: Optional[np.ndarray]) -> np.ndarray:
    """Smoothing cubic spline; return fitted yields."""
    order = np.argsort(maturities)
    m_s = maturities[order]
    y_s = yields[order]
    w_s = weights[order] if weights is not None else None

    n = len(m_s)
    # smoothing factor: if n >= 4 use variance-based, else s=0 (interpolating)
    var = float(np.var(y_s)) if n >= 4 else 0.0
    s = n * var * 0.1 if var > 0 else None

    spl = UnivariateSpline(m_s, y_s, w=w_s, k=3, s=s)
    fitted_sorted = spl(m_s)

    # Put back in original order
    fitted = np.empty(n)
    fitted[order] = fitted_sorted
    return fitted


def _fit_linear(maturities: np.ndarray, yields: np.ndarray,
                weights: Optional[np.ndarray]) -> np.ndarray:
    """OLS line y ~ a + b*maturity; return fitted yields."""
    if weights is not None:
        coeffs = np.polyfit(maturities, yields, 1, w=weights)
    else:
        coeffs = np.polyfit(maturities, yields, 1)
    return np.polyval(coeffs, maturities)


def _fit_one(form: str, maturities: np.ndarray, yields: np.ndarray,
             weights: Optional[np.ndarray], loss: str) -> np.ndarray:
    if form == "ns":
        return _fit_ns(maturities, yields, weights, loss)
    elif form == "nss":
        return _fit_nss(maturities, yields, weights, loss)
    elif form == "spline":
        return _fit_spline(maturities, yields, weights)
    elif form == "linear":
        return _fit_linear(maturities, yields, weights)
    else:
        raise ValueError(f"Unknown curve form: {form!r}. Choose from 'ns', 'nss', 'spline', 'linear'.")


# ---------------------------------------------------------------------------
# Panel residual wrapper (SimpleNamespace with .zscore for cross-time z-scores)
# ---------------------------------------------------------------------------

def _panel_rv_result(residual_df: pd.DataFrame) -> SimpleNamespace:
    """Wrap a panel residual DataFrame (rows=dates, cols=bond ids) with .zscore."""

    def zscore(window: int = 60) -> pd.DataFrame:
        r = residual_df.rolling(int(window))
        out = (residual_df - r.mean()) / r.std(ddof=1)
        return out

    return SimpleNamespace(frame=residual_df, zscore=zscore)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def make_curve_fit_builder(
    data: pd.DataFrame,
    *,
    maturity_col: str = "maturity",
    yield_col: str = "yield",
    id_col: Optional[str] = None,
    date_col: Optional[str] = None,
    form: str = "nss",
    loss: str = "ols",
    weight_col: Optional[str] = None,
):
    """Cross-sectional fitted-curve rich/cheap builder.

    Parameters
    ----------
    data : pd.DataFrame
        Long-format bond data.  If ``date_col`` is None → single snapshot.
    maturity_col, yield_col, id_col, date_col : str
        Column names.
    form : {'ns', 'nss', 'spline', 'linear'}
        Yield curve form to fit.
    loss : {'ols', 'lad'}
        Loss function for NS/NSS (lad → soft_l1 robust).
    weight_col : str, optional
        Per-bond weight column (e.g. 1/(DV01*price)).

    Returns
    -------
    (fit, residual, rank, rmse, otr_spread, get_data)
    """
    if form not in ("ns", "nss", "spline", "linear"):
        raise ValueError(f"form must be 'ns', 'nss', 'spline', or 'linear'; got {form!r}")
    if loss not in ("ols", "lad"):
        raise ValueError(f"loss must be 'ols' or 'lad'; got {loss!r}")

    state = {
        "data": data.copy(),
        "maturity_col": maturity_col,
        "yield_col": yield_col,
        "id_col": id_col,
        "date_col": date_col,
        "form": form,
        "loss": loss,
        "weight_col": weight_col,
        "result_df": None,       # full result frame after fit()
        "is_panel": date_col is not None,
    }

    # ------------------------------------------------------------------
    # fit()
    # ------------------------------------------------------------------
    def fit() -> pd.DataFrame:
        df = state["data"]
        m_col = state["maturity_col"]
        y_col = state["yield_col"]
        id_c = state["id_col"]
        d_col = state["date_col"]
        w_col = state["weight_col"]
        f = state["form"]
        l = state["loss"]

        rows = []

        if not state["is_panel"]:
            # single snapshot
            mats = df[m_col].to_numpy(dtype=float)
            ylds = df[y_col].to_numpy(dtype=float)
            wts = df[w_col].to_numpy(dtype=float) if w_col and w_col in df.columns else None
            fitted = _fit_one(f, mats, ylds, wts, l)
            resid = ylds - fitted
            for pos_i, (i, row) in enumerate(df.iterrows()):
                rec = {
                    m_col: row[m_col],
                    y_col: row[y_col],
                    "fitted": fitted[pos_i],
                    "residual": resid[pos_i],
                }
                if id_c and id_c in df.columns:
                    rec["id"] = row[id_c]
                rows.append(rec)
            result = pd.DataFrame(rows)
        else:
            # panel: fit per date
            dates = sorted(df[d_col].unique())
            for dt in dates:
                mask = df[d_col] == dt
                sub = df[mask].copy()
                mats = sub[m_col].to_numpy(dtype=float)
                ylds = sub[y_col].to_numpy(dtype=float)
                wts = sub[w_col].to_numpy(dtype=float) if w_col and w_col in sub.columns else None
                fitted = _fit_one(f, mats, ylds, wts, l)
                resid = ylds - fitted
                for j, (idx, row) in enumerate(sub.iterrows()):
                    rec = {
                        "date": dt,
                        m_col: row[m_col],
                        y_col: row[y_col],
                        "fitted": fitted[j],
                        "residual": resid[j],
                    }
                    if id_c and id_c in sub.columns:
                        rec["id"] = row[id_c]
                    rows.append(rec)
            result = pd.DataFrame(rows)

        state["result_df"] = result
        return result

    def _require():
        if state["result_df"] is None:
            raise RuntimeError("Call fit() before using the curve_fit_rv builder.")
        return state["result_df"]

    # ------------------------------------------------------------------
    # residual()
    # ------------------------------------------------------------------
    def residual():
        """Return residuals.

        Snapshot → pd.Series indexed by bond id (or integer).
        Panel    → SimpleNamespace with .frame (wide: index=date, cols=bond_id)
                   and .zscore(window) method.
        """
        result = _require()
        id_c = state["id_col"]

        if not state["is_panel"]:
            if id_c and "id" in result.columns:
                s = result.set_index("id")["residual"]
            else:
                s = result["residual"].reset_index(drop=True)
            s.name = "residual"
            return s
        else:
            # Pivot to wide: rows=date, cols=bond_id
            if id_c and "id" in result.columns:
                wide = result.pivot(index="date", columns="id", values="residual")
            else:
                wide = result.pivot(index="date", columns=state["maturity_col"], values="residual")
            return _panel_rv_result(wide)

    # ------------------------------------------------------------------
    # rank(date=None)
    # ------------------------------------------------------------------
    def rank(date=None) -> pd.DataFrame:
        """Cross-sectional ranking by residual for one date (most cheap first)."""
        result = _require()
        id_c = state["id_col"]

        if state["is_panel"]:
            dates = sorted(result["date"].unique())
            dt = date if date is not None else dates[-1]
            sub = result[result["date"] == dt].copy()
        else:
            sub = result.copy()

        if id_c and "id" in sub.columns:
            rank_df = (
                sub[["id", "residual"]]
                .sort_values("residual", ascending=False)
                .reset_index(drop=True)
            )
        else:
            rank_df = (
                sub[[state["maturity_col"], "residual"]]
                .sort_values("residual", ascending=False)
                .reset_index(drop=True)
            )
            rank_df.rename(columns={state["maturity_col"]: "maturity"}, inplace=True)

        rank_df.index = range(1, len(rank_df) + 1)
        rank_df.index.name = "rank"
        return rank_df

    # ------------------------------------------------------------------
    # rmse()
    # ------------------------------------------------------------------
    def rmse():
        """Per-date RMSE (dispersion/liquidity proxy).

        Snapshot → float.
        Panel    → pd.Series indexed by date.
        """
        result = _require()

        if not state["is_panel"]:
            r = result["residual"].to_numpy(dtype=float)
            return float(np.sqrt(np.mean(r ** 2)))
        else:
            def _rmse_group(g):
                r = g["residual"].to_numpy(dtype=float)
                return float(np.sqrt(np.mean(r ** 2)))
            return result.groupby("date").apply(_rmse_group, include_groups=False).rename("rmse")

    # ------------------------------------------------------------------
    # otr_spread(new_id, old_id)
    # ------------------------------------------------------------------
    def otr_spread(new_id, old_id) -> float:
        """yield(new_id) - yield(old_id) on the latest available date."""
        result = _require()
        y_col = state["yield_col"]
        id_c = state["id_col"]

        if not id_c or "id" not in result.columns:
            raise ValueError("otr_spread requires id_col to be specified.")

        if state["is_panel"]:
            latest_date = result["date"].max()
            sub = result[result["date"] == latest_date]
        else:
            sub = result

        def _get_yield(bond_id):
            rows = sub[sub["id"] == bond_id]
            if rows.empty:
                raise KeyError(f"Bond id {bond_id!r} not found in fitted results.")
            return float(rows[y_col].iloc[0])

        return _get_yield(new_id) - _get_yield(old_id)

    # ------------------------------------------------------------------
    # get_data()
    # ------------------------------------------------------------------
    def get_data() -> pd.DataFrame:
        return state["data"].copy()

    return (fit, residual, rank, rmse, otr_spread, get_data)
