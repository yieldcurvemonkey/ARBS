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
from itertools import combinations
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
        if method == "pca":
            D = state["scores"][list(drivers)]
        elif method == "regression":
            D = state["df"][list(drivers)]
        else:
            raise ValueError(
                "method must be 'pca' or 'regression'. For minimum-variance / "
                "PC-neutral construction weights use fly_weights()/curve_weights()."
            )
        common = s.index.intersection(D.dropna().index)
        s2 = s.loc[common]
        D2 = D.loc[common]
        X = np.column_stack([np.ones(len(D2)), D2.values])
        beta = np.linalg.lstsq(X, s2.values, rcond=None)[0]
        resid = pd.Series(s2.values - X @ beta, index=common, name="dir_neutral_residual")
        return {"betas": pd.Series(beta[1:], index=list(drivers)), "intercept": float(beta[0]), "residual": resid}

    # ---------- risk buckets ----------
    def risk_buckets(dv01_ladder) -> pd.Series:
        """PC exposures f = V^T r of a DV01 ladder. Assumes the default cov-PCA
        (matrix='cov'); for a corr-PCA model the loadings are in standardized
        space and exposures would need rescaling by the per-column scales."""
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


# ============================================================================
# Rolling PCA residual + eigenvector continuity (v2, spec A)
# ============================================================================

def align_eigenvectors(V_new: np.ndarray, V_prev: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """Flip sign of each column of V_new where cos(v_new, v_prev) < threshold.

    Ensures eigenvector continuity across rolling windows where the sign is
    arbitrary from the eigen-decomposition.
    """
    V = V_new.copy()
    for j in range(V.shape[1]):
        dot = float(V[:, j] @ V_prev[:, j])
        norm_new = float(np.linalg.norm(V[:, j]))
        norm_prev = float(np.linalg.norm(V_prev[:, j]))
        denom = norm_new * norm_prev
        cos_sim = dot / denom if denom > 0 else 0.0
        if cos_sim < threshold:
            V[:, j] = -V[:, j]
    return V


def rolling_residual(
    df: pd.DataFrame,
    structure,
    weights=None,
    window: int = 261,
    k: int = 3,
    sign_align: bool = True,
    on: str = "levels",
    matrix: str = "cov",
) -> pd.Series:
    """Rolling PCA residual: D_t = S_t - Ŝ_t using trailing-window PCA.

    Re-fits PCA every step on df.iloc[t-window:t], reconstructs the structure
    with k factors, and takes the difference. Eigenvectors are sign-aligned
    across windows when sign_align=True.

    Returns a Series in input units (same as df columns).
    """
    from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries, CurvePCAModel

    data = df.sort_index().dropna(how="any")
    cols = list(data.columns)
    n = len(data)
    window = int(window)
    k = int(min(k, len(cols)))

    if isinstance(structure, str):
        legs, wmap = [structure], {structure: 1.0}
    else:
        legs = list(structure)
        if weights is None:
            raise ValueError("Provide weights for a multi-leg structure.")
        wmap = dict(weights)

    residuals = pd.Series(index=data.index, dtype=float, name="rolling_residual")
    prev_loadings = None

    for t in range(window, n + 1):
        window_df = data.iloc[t - window : t]

        model, _ = fit_curve_pca_from_timeseries(
            window_df,
            use_changes=(on == "changes"),
            sort_by_tenor=False,
            matrix=matrix,
            pin_signs=True,
        )

        if sign_align and prev_loadings is not None:
            V_new = model.loadings.values
            V_aligned = align_eigenvectors(V_new, prev_loadings, threshold=0.0)
            model = CurvePCAModel(
                columns=model.columns,
                mean=model.mean,
                loadings=pd.DataFrame(V_aligned, index=model.loadings.index, columns=model.loadings.columns),
                eigenvalues=model.eigenvalues,
                scales=model.scales,
            )
        prev_loadings = model.loadings.values.copy()

        row = data.iloc[t - 1]
        rec = model.reconstruct(row, k=k)
        actual_s = sum(wmap[c] * row[c] for c in legs)
        fitted_s = sum(wmap[c] * rec[c] for c in legs)
        residuals.iloc[t - 1] = actual_s - fitted_s

    return residuals.dropna()


# ============================================================================
# Eigenportfolio returns (spec F)
# ============================================================================

def eigenportfolio_returns(
    loadings: pd.DataFrame,
    asset_returns: pd.DataFrame,
    asset_vols: pd.Series,
) -> pd.DataFrame:
    """Eigenportfolio (factor-mimicking portfolio) return series.

    F_j(t) = sum_i (v_{ji} / sigma_i) * R_i(t)
    where v_{ji} is the loading of asset i on PC j, sigma_i is asset i's vol.
    """
    assets = loadings.index
    pcs = loadings.columns
    R = asset_returns[assets].values
    V = asset_vols.reindex(assets).values
    W = loadings.values / V[:, None]
    F = R @ W
    return pd.DataFrame(F, index=asset_returns.index, columns=pcs)


# ============================================================================
# PCA Screener (CS "PCA Unleashed", JPM "RV on EUR swap yield curve",
# ING "Deconstructing the EUR yield curve", SSB "Principles of PCA")
# ============================================================================


def _build_and_fit(df, *, on, matrix, n_factors):
    """Shared helper: build + fit a PCA builder, return the unpacked tuple."""
    (fit, fair_value, residual, fly_weights_fn, curve_weights_fn,
     directionality, risk_buckets, factor_corr_check, get_model) = \
        make_pca_rv_builder(df, on=on, matrix=matrix, n_factors=n_factors)
    fit()
    return SimpleNamespace(
        fit=fit, fair_value=fair_value, residual=residual,
        fly_weights=fly_weights_fn, curve_weights=curve_weights_fn,
        directionality=directionality, risk_buckets=risk_buckets,
        factor_corr_check=factor_corr_check, get_model=get_model,
        state=fit.state,
    )


def screen_residuals(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    matrix: str = "cov",
    n_factors: int = 3,
    zscore_window: int = 60,
    pctl_window: int = 252,
) -> pd.DataFrame:
    """Per-tenor PCA residual snapshot with z-scores and historical markers.

    Returns DataFrame indexed by column name with: actual, fitted, residual,
    zscore, percentile, residual_1d, residual_1w, residual_1m.
    Positive residual => actual above PCA fair value (cheap for yields).
    """
    b = _build_and_fit(df, on=on, matrix=matrix, n_factors=n_factors)
    fv = b.fair_value()
    actual = b.state["df"][b.state["cols"]].reindex(fv.index)
    resid_df = (actual - fv).dropna(how="all")

    n = len(resid_df)
    rows = []
    for col in resid_df.columns:
        s = resid_df[col].dropna()
        if len(s) < 2:
            continue
        z_series = s.rolling(zscore_window).apply(
            lambda x: (x.iloc[-1] - x.mean()) / x.std(ddof=1) if x.std(ddof=1) > 0 else 0.0,
            raw=False,
        )
        p_series = s.rolling(pctl_window).rank(pct=True)

        last_idx = s.index[-1]
        row = {
            "tenor": col,
            "actual": float(actual[col].loc[last_idx]) if last_idx in actual.index else np.nan,
            "fitted": float(fv[col].loc[last_idx]) if last_idx in fv.index else np.nan,
            "residual": float(s.iloc[-1]),
            "zscore": float(z_series.iloc[-1]) if len(z_series) >= zscore_window else np.nan,
            "percentile": float(p_series.iloc[-1]) if len(p_series) >= pctl_window else np.nan,
        }
        for label, offset in [("residual_1d", 1), ("residual_1w", 5), ("residual_1m", 21)]:
            row[label] = float(s.iloc[-(offset + 1)]) if len(s) > offset else np.nan
        rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.set_index("tenor")
    return out


def screen_flies(
    df: pd.DataFrame,
    *,
    combos: Optional[Sequence] = None,
    on: str = "levels",
    matrix: str = "cov",
    n_factors: int = 3,
    zscore_window: int = 60,
    pctl_window: int = 252,
    min_zscore: float = 0.0,
    top_n: int = 20,
) -> pd.DataFrame:
    """Scan 3-leg fly combinations for PC1/PC2-neutral dislocation.

    Returns DataFrame ranked by |zscore| with: short, body, long,
    w_short, w_long, spread, residual, zscore, percentile, mean, std.
    """
    b = _build_and_fit(df, on=on, matrix=matrix, n_factors=n_factors)
    cols = b.state["cols"]
    actual = b.state["df"][cols]

    if combos is None:
        combos = list(combinations(cols, 3))

    rows = []
    for combo in combos:
        short, body, long = combo[0], combo[1], combo[2]
        if not all(c in cols for c in (short, body, long)):
            continue
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                w = b.fly_weights(short, body, long)
                if any("ill-conditioned" in str(cw.message) for cw in caught):
                    continue
        except Exception:
            continue

        w_s, w_l = w[short], w[long]
        if abs(w_s) > 20 or abs(w_l) > 20:
            continue

        spread = w_s * actual[short] + 1.0 * actual[body] + w_l * actual[long]
        spread = spread.dropna()
        if len(spread) < zscore_window:
            continue

        roll = spread.rolling(zscore_window)
        z_series = (spread - roll.mean()) / roll.std(ddof=1)
        p_series = spread.rolling(pctl_window).rank(pct=True)

        cur_z = float(z_series.iloc[-1])
        if abs(cur_z) < min_zscore:
            continue

        rows.append({
            "short": short, "body": body, "long": long,
            "w_short": w_s, "w_long": w_l,
            "spread": float(spread.iloc[-1]),
            "residual": float(spread.iloc[-1] - roll.mean().iloc[-1]),
            "zscore": cur_z,
            "percentile": float(p_series.iloc[-1]) if len(p_series) >= pctl_window else np.nan,
            "mean": float(roll.mean().iloc[-1]),
            "std": float(roll.std(ddof=1).iloc[-1]),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["abs_zscore"] = out["zscore"].abs()
    out = out.sort_values("abs_zscore", ascending=False).drop(columns="abs_zscore").head(top_n)
    return out.reset_index(drop=True)


def screen_curves(
    df: pd.DataFrame,
    *,
    combos: Optional[Sequence] = None,
    on: str = "levels",
    matrix: str = "cov",
    n_factors: int = 3,
    zscore_window: int = 60,
    pctl_window: int = 252,
    min_zscore: float = 0.0,
    top_n: int = 20,
) -> pd.DataFrame:
    """Scan 2-leg curve trades for PC1-neutral dislocation.

    Returns DataFrame ranked by |zscore| with: short, long, w_short,
    spread, residual, zscore, percentile, mean, std.
    """
    b = _build_and_fit(df, on=on, matrix=matrix, n_factors=n_factors)
    cols = b.state["cols"]
    actual = b.state["df"][cols]

    if combos is None:
        combos = list(combinations(cols, 2))

    rows = []
    for short, long in combos:
        if short not in cols or long not in cols:
            continue
        try:
            w = b.curve_weights(short, long)
        except (ValueError, np.linalg.LinAlgError):
            continue

        w_s = w[short]
        if abs(w_s) > 20:
            continue

        spread = w_s * actual[short] + 1.0 * actual[long]
        spread = spread.dropna()
        if len(spread) < zscore_window:
            continue

        roll = spread.rolling(zscore_window)
        z_series = (spread - roll.mean()) / roll.std(ddof=1)
        p_series = spread.rolling(pctl_window).rank(pct=True)

        cur_z = float(z_series.iloc[-1])
        if abs(cur_z) < min_zscore:
            continue

        rows.append({
            "short": short, "long": long,
            "w_short": w_s,
            "spread": float(spread.iloc[-1]),
            "residual": float(spread.iloc[-1] - roll.mean().iloc[-1]),
            "zscore": cur_z,
            "percentile": float(p_series.iloc[-1]) if len(p_series) >= pctl_window else np.nan,
            "mean": float(roll.mean().iloc[-1]),
            "std": float(roll.std(ddof=1).iloc[-1]),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["abs_zscore"] = out["zscore"].abs()
    out = out.sort_values("abs_zscore", ascending=False).drop(columns="abs_zscore").head(top_n)
    return out.reset_index(drop=True)


def _default_fly_combos(cols):
    """Standard flies: body strictly between short and long, all at least 1 apart."""
    n = len(cols)
    out = []
    for i in range(n):
        for j in range(i + 2, n):
            for k in range(j + 2, n):
                out.append((cols[i], cols[j], cols[k]))
    return out


def rv_opportunity_index(
    df: pd.DataFrame,
    *,
    fly_combos: Optional[Sequence] = None,
    on: str = "levels",
    matrix: str = "cov",
    n_factors: int = 3,
    zscore_window: int = 126,
    smoothing: int = 10,
) -> pd.Series:
    """JPM-style RV opportunity index: smoothed sum of squared z-scores
    across PCA-neutral flies. Higher values => more dislocation on the curve.
    """
    b = _build_and_fit(df, on=on, matrix=matrix, n_factors=n_factors)
    cols = b.state["cols"]
    actual = b.state["df"][cols]

    if fly_combos is None:
        fly_combos = _default_fly_combos(cols)

    spread_list = []
    for combo in fly_combos:
        short, body, long = combo
        if not all(c in cols for c in (short, body, long)):
            continue
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                w = b.fly_weights(short, body, long)
                if any("ill-conditioned" in str(cw.message) for cw in caught):
                    continue
        except Exception:
            continue
        w_s, w_l = w[short], w[long]
        if abs(w_s) > 20 or abs(w_l) > 20:
            continue
        spread = w_s * actual[short] + 1.0 * actual[body] + w_l * actual[long]
        spread_list.append(spread)

    if not spread_list:
        return pd.Series(dtype=float, name="rv_opportunity_index")

    z_sq_sum = None
    for s in spread_list:
        s = s.dropna()
        roll = s.rolling(zscore_window)
        z = (s - roll.mean()) / roll.std(ddof=1)
        z_sq = z ** 2
        if z_sq_sum is None:
            z_sq_sum = z_sq
        else:
            z_sq_sum = z_sq_sum.add(z_sq, fill_value=0.0)

    idx = z_sq_sum.dropna().rolling(smoothing).mean()
    idx.name = "rv_opportunity_index"
    return idx.dropna()


def beta_stability(
    df: pd.DataFrame,
    body: str,
    short_wing: str,
    long_wing: str,
    *,
    regression_window: int = 126,
    vol_window: int = 63,
    zscore_window: int = 126,
) -> pd.DataFrame:
    """JPM-style traffic light indicator for a specific fly.

    Tracks rolling regression beta stability of the 50:50 fly vs body yield
    and wing curve. Returns DataFrame with: fly, beta_body, beta_wing,
    beta_body_vol, beta_wing_vol, traffic_light.

    traffic_light > 3 => "red" (regime instability, avoid systematic RV)
    traffic_light < 2 => "green" (stable betas, RV trading attractive)
    """
    data = df[[short_wing, body, long_wing]].dropna()
    fly = 2 * data[body] - data[short_wing] - data[long_wing]
    body_yield = data[body]
    wing_curve = data[long_wing] - data[short_wing]

    n = len(data)
    rw = int(regression_window)
    beta_b = pd.Series(index=data.index, dtype=float)
    beta_w = pd.Series(index=data.index, dtype=float)

    for t in range(rw, n):
        window_slice = slice(t - rw, t)
        y = fly.iloc[window_slice].values
        X = np.column_stack([
            np.ones(rw),
            body_yield.iloc[window_slice].values,
            wing_curve.iloc[window_slice].values,
        ])
        try:
            coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        beta_b.iloc[t] = coeffs[1]
        beta_w.iloc[t] = coeffs[2]

    beta_b_vol = beta_b.rolling(vol_window).std(ddof=1)
    beta_w_vol = beta_w.rolling(vol_window).std(ddof=1)

    zw = int(zscore_window)
    z_b = (beta_b_vol - beta_b_vol.rolling(zw).mean()) / beta_b_vol.rolling(zw).std(ddof=1)
    z_w = (beta_w_vol - beta_w_vol.rolling(zw).mean()) / beta_w_vol.rolling(zw).std(ddof=1)

    traffic = np.sqrt(z_b.fillna(0.0) ** 2 + z_w.fillna(0.0) ** 2)

    return pd.DataFrame({
        "fly": fly,
        "beta_body": beta_b,
        "beta_wing": beta_w,
        "beta_body_vol": beta_b_vol,
        "beta_wing_vol": beta_w_vol,
        "traffic_light": traffic,
    })
