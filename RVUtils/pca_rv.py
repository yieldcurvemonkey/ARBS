"""PCA relative-value builder (data-agnostic).

Closure-factory mirroring `make_secondary_axis_plot` / `make_linear_regression_builder`.
Given a wide DataFrame of rates/structures (DatetimeIndex, columns = tenors or
structures), fits a PCA on levels or changes and exposes RV utilities:

    fit, fair_value, residual, fly_weights, curve_weights, \
        directionality, risk_buckets, factor_corr_check, get_model = \
        make_pca_rv_builder(df, on="levels", n_factors=3)
    fit()
    w = fly_weights("2y", "5y", "10y")          # PC1/PC2-neutral fly weights
    res = residual(("2y","5y","10y"), weights=w)  # rich/cheap; res>0 => belly cheap
    z = res.zscore(60)

Math sources: SSB *Principles of PCA*, CS *PCA Unleashed*, Huggins-Schaller Ch.3,
BofA 2s4s7s, ING/JPM cross-market notes (see spec appendix).
"""
from __future__ import annotations

import warnings
from types import SimpleNamespace
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries


def _rv_result(series: pd.Series) -> SimpleNamespace:
    """Wrap a residual/structure series with chainable z-score / percentile helpers."""
    series = series.dropna()

    def zscore(window: int = 60) -> pd.Series:
        r = series.rolling(int(window))
        out = (series - r.mean()) / r.std(ddof=1)
        out.name = (series.name or "residual") + f"_z{window}"
        return out

    def percentile(window: int = 252) -> pd.Series:
        out = series.rolling(int(window)).rank(pct=True)
        out.name = (series.name or "residual") + f"_pctl{window}"
        return out

    def last() -> float:
        return float(series.iloc[-1]) if len(series) else np.nan

    return SimpleNamespace(series=series, zscore=zscore, percentile=percentile, last=last)


def make_pca_rv_builder(
    df: pd.DataFrame,
    *,
    tenors: Optional[Sequence] = None,
    on: str = "levels",
    matrix: str = "cov",
    n_factors: int = 3,
    window: Optional[int] = None,
    sort_by_tenor: bool = False,
    fixed_loadings_date=None,
):
    if on not in ("levels", "changes"):
        raise ValueError("on must be 'levels' or 'changes'")

    data = df.copy()
    if tenors is not None:
        data = data[list(tenors)]
    data = data.sort_index()

    state = {
        "df": data,
        "on": on,
        "matrix": matrix,
        "n_factors": int(n_factors),
        "sort_by_tenor": bool(sort_by_tenor),
        "window": window,
        "fixed_loadings_date": fixed_loadings_date,
        "model": None,
        "scores": None,
        "cols": None,
    }

    # ---------- fit ----------
    def fit():
        src = state["df"]
        if state["fixed_loadings_date"] is not None:
            src = src.loc[: state["fixed_loadings_date"]]
        model, scores = fit_curve_pca_from_timeseries(
            src,
            use_changes=(on == "changes"),
            sort_by_tenor=state["sort_by_tenor"],
            matrix=state["matrix"],
            pin_signs=True,
        )
        state["model"] = model
        state["scores"] = scores
        state["cols"] = list(model.columns)
        return model

    def _require():
        if state["model"] is None:
            raise RuntimeError("Call fit() before using the pca_rv builder.")
        return state["model"]

    def get_model():
        return state["model"], state["scores"]

    # ---------- fair value ----------
    def fair_value(cols: Optional[Sequence] = None, k: Optional[int] = None) -> pd.DataFrame:
        model = _require()
        k = state["n_factors"] if k is None else int(k)
        out_cols = state["cols"] if cols is None else list(cols)
        lvl = state["df"][state["cols"]].dropna(how="any")
        if on == "levels":
            recs = {idx: model.reconstruct(row, k=k) for idx, row in lvl.iterrows()}
            fv = pd.DataFrame(recs).T
        else:
            chg = lvl.diff().dropna(how="any")
            fitted = {idx: model.reconstruct(row, k=k) for idx, row in chg.iterrows()}
            fchg = pd.DataFrame(fitted).T[state["cols"]]
            fv = lvl.iloc[0] + fchg.cumsum()  # cumulative reconstruction -> levels
        fv.index.name = lvl.index.name
        return fv[out_cols]

    # ---------- residual / rich-cheap ----------
    def residual(structure, weights: Optional[dict] = None, k: Optional[int] = None) -> SimpleNamespace:
        model = _require()
        k = state["n_factors"] if k is None else int(k)
        fv = fair_value(k=k)
        actual = state["df"][state["cols"]]
        if isinstance(structure, str):
            legs, wmap = [structure], {structure: 1.0}
        else:
            legs = list(structure)
            if weights is None:
                raise ValueError("Provide weights for a multi-leg structure.")
            wmap = dict(weights)
        act = sum(wmap[c] * actual[c] for c in legs)
        fit_s = sum(wmap[c] * fv[c] for c in legs)
        resid = (act - fit_s).reindex(fv.index).dropna()
        resid.name = "residual"
        return _rv_result(resid)

    # ---------- weights ----------
    def fly_weights(short, body, long, neutralize=("PC1", "PC2")) -> dict:
        model = _require()
        L = model.loadings
        if len(neutralize) != 2:
            raise ValueError("fly_weights neutralizes exactly two factors (e.g. ('PC1','PC2')).")
        p1, p2 = neutralize
        e_s = np.array([L.loc[short, p1], L.loc[short, p2]])
        e_b = np.array([L.loc[body, p1], L.loc[body, p2]])
        e_l = np.array([L.loc[long, p1], L.loc[long, p2]])
        M = np.column_stack([e_s, e_l])  # 2x2
        cond = np.linalg.cond(M)
        if cond > 1e8:
            warnings.warn(f"fly_weights: ill-conditioned system (cond={cond:.1e}); weights unstable.")
        w_s, w_l = np.linalg.solve(M, -e_b)
        return {short: float(w_s), body: 1.0, long: float(w_l)}

    def curve_weights(short, long, neutralize=("PC1",)) -> dict:
        model = _require()
        L = model.loadings
        p1 = neutralize[0]
        e1_s = float(L.loc[short, p1])
        e1_l = float(L.loc[long, p1])
        if e1_s == 0:
            raise ValueError("Short-leg PC loading is zero; cannot neutralize.")
        return {short: float(-e1_l / e1_s), long: 1.0}

    # ---------- directionality ----------
    def directionality(structure, weights: Optional[dict] = None, drivers=("PC1", "PC2"), method="pca") -> dict:
        model = _require()
        if isinstance(structure, str):
            s = state["df"][structure]
        else:
            if weights is None:
                raise ValueError("Provide weights for a multi-leg structure.")
            wmap = dict(weights)
            s = sum(wmap[c] * state["df"][c] for c in structure)
        s = s.dropna()
        if method in ("pca", "minvar"):
            D = state["scores"][list(drivers)]
        else:  # "regression" on explicit driver columns
            D = state["df"][list(drivers)]
        common = s.index.intersection(D.dropna().index)
        s2 = s.loc[common]
        D2 = D.loc[common]
        X = np.column_stack([np.ones(len(D2)), D2.values])
        beta = np.linalg.lstsq(X, s2.values, rcond=None)[0]
        resid = pd.Series(s2.values - X @ beta, index=common, name="dir_neutral_residual")
        return {"betas": pd.Series(beta[1:], index=list(drivers)), "intercept": float(beta[0]), "residual": resid}

    # ---------- risk buckets ----------
    def risk_buckets(dv01_ladder) -> pd.Series:
        model = _require()
        r = pd.Series(dv01_ladder).reindex(model.columns).fillna(0.0)
        f = model.loadings.T.values @ r.values  # (K_pc,)
        return pd.Series(f, index=model.loadings.columns, name="pc_exposure")

    # ---------- pre-trade factor-correlation check ----------
    def factor_corr_check(weights: dict, window: int = 126, driver="PC1", tol: float = 0.2) -> pd.DataFrame:
        _require()
        s = sum(weights[c] * state["df"][c] for c in weights)
        dpnl = s.diff()
        fchg = state["scores"][driver].diff()
        common = dpnl.dropna().index.intersection(fchg.dropna().index)
        dpnl, fchg = dpnl.loc[common], fchg.loc[common]
        beta = dpnl.rolling(int(window)).cov(fchg) / fchg.rolling(int(window)).var()
        return pd.DataFrame({f"beta_to_{driver}": beta, "flagged": beta.abs() > tol})

    fit.state = state
    return (fit, fair_value, residual, fly_weights, curve_weights,
            directionality, risk_buckets, factor_corr_check, get_model)
