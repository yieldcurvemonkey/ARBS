import datetime
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Sequence, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.odr import ODR, Model, RealData

from RVUtils.mean_reversion import simulate_mean_reversion_ou


def make_linear_regression_builder(
    *,
    df: Optional[pd.DataFrame] = None,
    y: Optional[pd.Series] = None,
    y_col: Optional[str] = None,
    on_diff: bool = False,
    on_returns: bool = False,
    add_constant: bool = True,
    date_color_bar: bool = False,
    preprocess: Optional[Dict[str, Any]] = None,
    window: Optional[int] = None,
):
    """
    Multi-linear regression builder with TLS/OLS/WLS/GLS, rich preprocessing, and rolling regression utilities.
    Dates are taken from the index; index MUST be datetime/date-like.

    Returns:
      add_indep_var(obj, *, name=None, transform=None)
      fit(*, model="OLS"|"WLS"|"GLS"|"TLS", weights=None, tls_x_errs=None, tls_y_errs=None, verbose=False)
      plot_actual_vs_predicted(title=None, date_color_bar=None, cmap="viridis", diff_verb=None)
      plot_residuals_vs_predicted(title=None, date_color_bar=None, cmap="viridis", diff_verb=None)
      get_data() -> (X_design_df, y_series, results)

      if window is not None,
      rolling_beta(*, window=None, model=None, name=None, step=1, min_obs=None, ...)
      rolling_r2(*, window=None, model=None, step=1, min_obs=None, ...)
    """

    # --------------------- helpers: index coercion ---------------------
    def _to_dt_index(idx, who: str) -> pd.DatetimeIndex:
        if isinstance(idx, pd.PeriodIndex):
            return idx.to_timestamp()
        if isinstance(idx, pd.DatetimeIndex):
            return idx.tz_convert(None) if idx.tz is not None else idx
        try:
            di = pd.DatetimeIndex(pd.to_datetime(idx))
            return di.tz_convert(None) if di.tz is not None else di
        except Exception as e:
            raise ValueError(f"{who} must be datetime/date-like; " f"try `df = df.set_index('Date')` then `df.index = pd.to_datetime(df.index)`.") from e

    def _ensure_dt_index_on(obj, who: str):
        out = obj.copy()
        out.index = _to_dt_index(out.index, who)
        return out

    # --------------------- resolve y / df ---------------------
    if on_diff and on_returns:
        raise ValueError("on_diff and on_returns are mutually exclusive.")

    if y is None:
        if df is None or y_col is None:
            raise ValueError("Provide either y (Series) OR df + y_col.")
        if y_col not in df.columns:
            raise ValueError(f"'{y_col}' not in df.")
        df = _ensure_dt_index_on(df, "df.index")
        y = df[y_col]
    else:
        y = _ensure_dt_index_on(y, "y.index")
        if df is not None:
            df = _ensure_dt_index_on(df, "df.index")

    y = y.copy()
    y.name = y.name or (y_col or "y")

    # --------------------- preprocessing config (defaults) ---------------------
    pp = {
        "join_how": "inner",  # inner | outer
        "sort_index": True,
        "drop_duplicate_index": "keep-last",  # keep-last | keep-first | error | none
        "date_start": None,  # "YYYY-MM-DD" or pd.Timestamp
        "date_end": None,
        "resample_rule": None,  # e.g., "B", "D", "W", "M"
        "resample_agg": "last",  # "last" | "mean" | "sum" | callable
        "coerce_numeric": True,  # to_numeric(errors="coerce")
        "max_missing_frac": None,  # drop columns with > this fraction NaN
        "fill_method": None,  # None | "ffill" | "bfill"
        "fill_limit": None,  # max consecutive fills
        "interpolate": False,  # True/False
        "interpolate_method": "time",  # "time" | "linear" | etc.
        "interpolate_kwargs": {},  # extra kwargs to .interpolate
        "dropna_how": "any",  # "any" | "all" | None (None -> drop at the end anyway)
        "demean": False,
        "zscore": False,  # standardize each series (after diff/returns if used)
        "log": False,  # log-transform positive series (after resample/fill, before diff/returns)
        "diff_periods": 1,  # used when on_diff=True
        "return_periods": 1,  # used when on_returns=True
        "outliers": {  # outlier handling per column
            "strategy": None,  # None | "winsor" | "zclip" | "madclip" | "trim_z" | "trim_mad"
            "winsor_limits": (0.01, 0.99),
            "z_thresh": 4.0,
            "mad_thresh": 5.0,
            "clip_bounds": None,  # (lo, hi)
        },
        "scale": {  # feature scaling for X; y left unscaled by default
            "type": None,  # None | "standard" | "minmax" | "robust"
            "range": (0.0, 1.0),  # for minmax
            "with_centering": True,
            "scale_y": False,  # set True to also scale y
        },
        "collinearity": {
            "drop_zero_variance": True,
            "corr_threshold": None,  # e.g., 0.98 to greedily drop highly-correlated features
            "vif_threshold": None,  # e.g., 10.0 to iteratively drop high-VIF features
            "max_iter": 5,
        },
    }
    if preprocess:
        # shallow+deep update
        for k, v in preprocess.items():
            if isinstance(v, dict) and isinstance(pp.get(k, None), dict):
                pp[k].update(v)
            else:
                pp[k] = v

    state = {
        "xs": [],  # list[(name, Series)]
        "model": None,  # "OLS" | "WLS" | "GLS" | "TLS"
        "results": None,
        "X_used": None,
        "y_used": None,
        "date_used": None,  # DatetimeIndex aligned to fitted sample
        "date_color_bar_default": bool(date_color_bar),
        "scalers": {"X": {}, "y": None},  # scaling params if used
        "dropped_columns": {"missing": [], "zero_var": [], "high_corr": [], "high_vif": []},
        "preprocess": pp,
        "window_default": (int(window) if window is not None else None),
    }

    # --------------------- add_indep_var ---------------------
    def _coerce_series(obj, name=None):
        if isinstance(obj, str):
            if df is None:
                raise ValueError("Column name provided but no df was given to the builder.")
            if obj not in df.columns:
                raise ValueError(f"'{obj}' not in df.")
            s = df[obj]
            s = _ensure_dt_index_on(s, f"Series('{obj}').index")
            s.name = obj
            return s
        elif isinstance(obj, pd.Series):
            s = _ensure_dt_index_on(obj, "independent Series.index")
            if name is not None:
                s = s.copy()
                s.name = name
            s.name = s.name or "x"
            return s
        else:
            raise TypeError("add_indep_var expects a column name (str) or a pandas Series.")

    def add_indep_var(obj: Union[str, pd.Series], *, name: Optional[str] = None, transform: Optional[Callable[[pd.Series], pd.Series]] = None):
        s = _coerce_series(obj, name=name)
        if pp["sort_index"]:
            s = s.sort_index()
        if transform is not None:
            s = transform(s)
            if name is not None:
                s.name = name
        state["xs"].append((s.name, s))
        return s.name

    # --------------------- TLS fit (stable pattern) ---------------------
    def _tls_fit(
        X: pd.DataFrame,
        y_vec: pd.Series,
        x_errs=None,
        y_errs=None,
        verbose: bool = False,
    ):
        X_in = X.copy()
        y_in = y_vec.copy()

        X_np = np.ascontiguousarray(X_in.to_numpy(dtype=np.float64))
        y_np = np.ascontiguousarray(y_in.to_numpy(dtype=np.float64))

        n, k = X_np.shape
        if n <= k:
            raise ValueError(f"TLS: need more observations than regressors (n={n}, k={k}).")

        def _linear_f_no_constant(beta: np.ndarray, x_variable: np.ndarray) -> np.ndarray:
            _, b = beta[0], beta[1:]
            b.shape = (b.shape[0], 1)
            return (x_variable * b).sum(axis=0)

        def _linear_f_constant(beta: np.ndarray, x_variable: np.ndarray) -> np.ndarray:
            a, b = beta[0], beta[1:]
            b.shape = (b.shape[0], 1)
            return a + (x_variable * b).sum(axis=0)

        linear = Model(_linear_f_constant) if add_constant else Model(_linear_f_no_constant)

        real_kwargs = {}
        if x_errs is not None:
            sx = np.ascontiguousarray(np.asarray(x_errs, dtype=np.float64))
            if sx.shape == (n, k):
                real_kwargs["sx"] = sx.T
            else:
                raise ValueError("TLS: x_errs must have shape (n_obs, n_features).")
        if y_errs is not None:
            sy = np.ascontiguousarray(np.asarray(y_errs, dtype=np.float64))
            if sy.shape == (n,):
                real_kwargs["sy"] = sy
            else:
                raise ValueError("TLS: y_errs must have length n_obs.")

        mydata = RealData(X_np.T, y_np, **real_kwargs)
        p_len = k + (1 if add_constant else 0)
        myodr = ODR(mydata, linear, beta0=np.ones(p_len, dtype=np.float64))
        out = myodr.run()

        if verbose:
            try:
                out.pprint()
            except Exception:
                print("ODR summary:")
                print(f"  iter: {getattr(out, 'iter', 'NA')}")
                print(f"  stopreason: {getattr(out, 'stopreason', 'NA')}")
                print(f"  sum_square: {getattr(out, 'sum_square', 'NA')}")

        if add_constant:
            intercept = float(out.beta[0])
            betas = np.asarray(out.beta[1:], dtype=np.float64)
            sd_beta = np.asarray(out.sd_beta, dtype=np.float64)
            se_intercept = float(sd_beta[0])
            se_betas = sd_beta[1:]
        else:
            intercept = 0.0
            betas = np.asarray(out.beta, dtype=np.float64)
            se_intercept = np.nan
            se_betas = np.asarray(out.sd_beta, dtype=np.float64)

        y_hat = intercept + (X_in.to_numpy() @ betas)
        resid = y_in.to_numpy() - y_hat

        ss_res = float(np.sum(resid**2))
        y_mean = float(np.mean(y_in.to_numpy()))
        ss_tot = float(np.sum((y_in.to_numpy() - y_mean) ** 2))
        rsq = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

        names = list(X_in.columns)
        if add_constant:
            params = pd.Series([intercept, *betas], index=["const", *names])
            bse = pd.Series([se_intercept, *se_betas], index=["const", *names])
        else:
            params = pd.Series(betas, index=names)
            bse = pd.Series(se_betas, index=names)

        df_resid = max(n - (k + (1 if add_constant else 0)), 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            tvals = params / bse
        pvals = pd.Series(2 * (1 - stats.t.cdf(np.abs(tvals), df=df_resid)), index=params.index)

        return SimpleNamespace(
            params=params,
            bse=bse,
            pvalues=pvals,
            rsquared=rsq,
            resid=pd.Series(resid, index=y_in.index),
            fittedvalues=pd.Series(y_hat, index=y_in.index),
            model=SimpleNamespace(
                endog_names=y_in.name,
                exog_names=(["const"] + names) if add_constant else names,
            ),
            nobs=n,
            df_resid=df_resid,
            odr_output=out,
        )

    def _pcr_fit(
        X: pd.DataFrame,
        y_vec: pd.Series,
        n_components: Optional[Union[int, float]] = None,  # int k or float variance threshold (0,1]
        scale: bool = True,
        verbose: bool = False,
    ):
        """
        Principal Components Regression (PCR).
        - PCA on (centered & optionally standardized) X (no constant in X here).
        - OLS of y on leading principal component scores.
        - Coefficients are mapped back to original feature space so results look
        like a standard regression: params['const'] and params[<original X cols>].

        Returns a SimpleNamespace consistent with the builder's result contract.
        Adds .pcr_info with PCA bits (components, explained_variance_ratio, etc).
        """
        X_in = X.copy()
        y_in = y_vec.copy()
        names = list(X_in.columns)

        # --- center & optionally standardize ---
        X_mat = X_in.to_numpy(dtype=np.float64, copy=True)
        mu = X_mat.mean(axis=0)

        Xc = X_mat - mu
        sd = Xc.std(axis=0, ddof=1)
        if scale:
            sd_safe = np.where((sd == 0) | ~np.isfinite(sd), 1.0, sd)
            Xcs = Xc / sd_safe
        else:
            sd_safe = np.ones_like(sd)
            Xcs = Xc

        # --- PCA via SVD of the (centered/standardized) design ---
        # Xcs = U S Vt   (n x p) = (n x p) (p) (p x p)
        U, S, Vt = np.linalg.svd(Xcs, full_matrices=False)
        var_all = S**2
        exp_ratio = var_all / var_all.sum()

        # choose k (components)
        if n_components is None:
            # default: 95% variance
            k = int(np.searchsorted(np.cumsum(exp_ratio), 0.95) + 1)
        elif isinstance(n_components, float) and 0.0 < n_components <= 1.0:
            k = int(np.searchsorted(np.cumsum(exp_ratio), n_components) + 1)
        else:
            k = int(n_components)

        k = max(1, min(k, Xcs.shape[1], Xcs.shape[0] - 1))

        # PC scores: Z = U * S  (== Xcs @ Vt.T)
        Z = U[:, :k] * S[:k]  # (n x k)
        Z_design = sm.add_constant(Z)

        # OLS of y on PC scores
        ols_pc = sm.OLS(y_in.to_numpy(dtype=np.float64), Z_design).fit()

        # map back to original space
        a = float(ols_pc.params[0])  # intercept in PC space
        gamma = ols_pc.params[1:].copy()  # loadings on Z (k,)

        # J maps PC gammas to original-space betas: b = J @ gamma
        #   with J = V_k / sd (if scaled), where V_k = Vt[:k,:].T  (p x k)
        J = (Vt[:k, :].T) / sd_safe[:, None]  # (p x k)
        b = J @ gamma  # original feature betas (p,)

        # intercept in original space: c = a - mu · b
        c = a - float(mu @ b)

        # ---- standard errors via delta method ----
        cov_theta = ols_pc.cov_params().to_numpy()  # (k+1, k+1)
        cov_gamma = cov_theta[1:, 1:]  # (k, k)
        cov_b = J @ cov_gamma @ J.T  # (p, p)
        se_b = np.sqrt(np.clip(np.diag(cov_b), 0.0, np.inf))

        # var(c) for c = a - mu^T b, with theta = [a; gamma]
        # c = [1, -(J^T mu)] · theta
        g = np.concatenate(([1.0], -(J.T @ mu)))  # (k+1,)
        var_c = float(g @ cov_theta @ g.T)
        se_c = np.sqrt(max(var_c, 0.0))

        params = pd.Series([c, *b], index=["const", *names])
        bse = pd.Series([se_c, *se_b], index=["const", *names])

        df_resid = int(ols_pc.df_resid)
        with np.errstate(divide="ignore", invalid="ignore"):
            tvals = params / bse
        pvals = pd.Series(2 * (1 - stats.t.cdf(np.abs(tvals), df=df_resid)), index=params.index)

        # fitted/residuals computed in original space (sanity: identical to ols_pc.fitted)
        y_hat = c + X_mat @ b
        resid = y_in.to_numpy(dtype=np.float64) - y_hat
        ss_res = float((resid**2).sum())
        ss_tot = float(((y_in - y_in.mean()) ** 2).sum())
        rsq = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

        # optional verbosity
        if verbose:
            ev_cum = np.cumsum(exp_ratio)
            print(f"PCR: selected k={k} PCs; variance explained={ev_cum[k-1]:.3%}")

        return SimpleNamespace(
            params=params,
            bse=bse,
            pvalues=pvals,
            rsquared=rsq,
            resid=pd.Series(resid, index=y_in.index),
            fittedvalues=pd.Series(y_hat, index=y_in.index),
            model=SimpleNamespace(endog_names=y_in.name, exog_names=["const", *names]),
            nobs=len(y_in),
            df_resid=df_resid,
            pcr_info=SimpleNamespace(
                n_components=k,
                components_=Vt[:k, :],  # (k x p) PC loadings (feature space)
                scores_=Z,  # (n x k) scores
                explained_variance_ratio_=exp_ratio[:k],
                means_=mu,
                scales_=sd_safe,
                scaled=scale,
            ),
        )

    # --------------------- preprocessing helpers ---------------------
    def _winsorize(s: pd.Series, lo=0.01, hi=0.99):
        ql, qh = s.quantile(lo), s.quantile(hi)
        return s.clip(lower=ql, upper=qh)

    def _zclip(s: pd.Series, z=4.0):
        m, sd = s.mean(), s.std(ddof=1)
        if sd == 0 or not np.isfinite(sd):
            return s
        lo, hi = m - z * sd, m + z * sd
        return s.clip(lower=lo, upper=hi)

    def _madclip(s: pd.Series, k=5.0):
        med = s.median()
        mad = (s - med).abs().median()
        if mad == 0 or not np.isfinite(mad):
            return s
        sigma = 1.4826 * mad
        lo, hi = med - k * sigma, med + k * sigma
        return s.clip(lower=lo, upper=hi)

    def _apply_outliers(dfX: pd.DataFrame):
        strat = pp["outliers"]["strategy"]
        if strat is None:
            return dfX
        if strat == "winsor":
            lo, hi = pp["outliers"]["winsor_limits"]
            return dfX.apply(lambda s: _winsorize(s, lo, hi))
        if strat == "zclip":
            return dfX.apply(lambda s: _zclip(s, pp["outliers"]["z_thresh"]))
        if strat == "madclip":
            return dfX.apply(lambda s: _madclip(s, pp["outliers"]["mad_thresh"]))
        if strat == "trim_z":
            z = pp["outliers"]["z_thresh"]
            m = dfX.mean()
            sd = dfX.std(ddof=1).replace(0, np.nan)
            zed = (dfX - m) / sd
            return dfX.mask(zed.abs() > z)  # mark as NaN; will be dropped later
        if strat == "trim_mad":
            med = dfX.median()
            mad = (dfX - med).abs().median().replace(0, np.nan)
            sigma = 1.4826 * mad
            zed = (dfX - med) / sigma
            return dfX.mask(zed.abs() > pp["outliers"]["mad_thresh"])
        if strat == "clip_bounds" and pp["outliers"]["clip_bounds"] is not None:
            lo, hi = pp["outliers"]["clip_bounds"]
            return dfX.clip(lower=lo, upper=hi)
        return dfX

    def _scale_X(dfX: pd.DataFrame):
        typ = pp["scale"]["type"]
        if typ is None:
            return dfX
        Xs = dfX.copy()
        state["scalers"]["X"] = {}
        if typ == "standard":
            for c in Xs.columns:
                mu, sd = Xs[c].mean(), Xs[c].std(ddof=1)
                if sd == 0 or not np.isfinite(sd):
                    continue
                Xs[c] = (Xs[c] - mu) / sd if pp["scale"]["with_centering"] else Xs[c] / sd
                state["scalers"]["X"][c] = ("standard", mu, sd)
        elif typ == "minmax":
            lo, hi = pp["scale"]["range"]
            for c in Xs.columns:
                mn, mx = Xs[c].min(), Xs[c].max()
                rng = mx - mn
                if rng == 0 or not np.isfinite(rng):
                    continue
                Xs[c] = lo + (Xs[c] - mn) * (hi - lo) / rng
                state["scalers"]["X"][c] = ("minmax", mn, mx, lo, hi)
        elif typ == "robust":
            for c in Xs.columns:
                med = Xs[c].median()
                iqr = Xs[c].quantile(0.75) - Xs[c].quantile(0.25)
                if iqr == 0 or not np.isfinite(iqr):
                    continue
                Xs[c] = (Xs[c] - med) / iqr if pp["scale"]["with_centering"] else Xs[c] / iqr
                state["scalers"]["X"][c] = ("robust", med, iqr)
        return Xs

    def _collinearity_prune(dfX: pd.DataFrame):
        drops = state["dropped_columns"]
        X = dfX.copy()

        # zero variance
        if pp["collinearity"]["drop_zero_variance"]:
            stds = X.std(ddof=1)
            zero_cols = stds.index[~np.isfinite(stds) | (stds == 0.0)].tolist()
            if zero_cols:
                drops["zero_var"].extend(zero_cols)
                X = X.drop(columns=zero_cols, errors="ignore")

        # high correlation greedy prune
        ct = pp["collinearity"]["corr_threshold"]
        if ct is not None and len(X.columns) > 1:
            corr = X.corr().abs()
            upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
            to_drop = set()
            while True:
                max_corr = upper.max().max()
                if not np.isfinite(max_corr) or max_corr < ct:
                    break
                pair = np.where(upper.values == max_corr)
                i, j = int(pair[0][0]), int(pair[1][0])
                col_i, col_j = upper.index[i], upper.columns[j]
                # drop the one with larger mean absolute correlation
                mean_i = corr[col_i].mean()
                mean_j = corr[col_j].mean()
                victim = col_i if mean_i >= mean_j else col_j
                to_drop.add(victim)
                X = X.drop(columns=[victim])
                corr = X.corr().abs()
                upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
            if to_drop:
                drops["high_corr"].extend(sorted(to_drop))

        # VIF prune (iterative)
        vt = pp["collinearity"]["vif_threshold"]
        if vt is not None and len(X.columns) > 1:
            try:
                from statsmodels.stats.outliers_influence import variance_inflation_factor as VIF

                it = 0
                while it < pp["collinearity"]["max_iter"] and len(X.columns) > 1:
                    it += 1
                    # add const for VIF computation
                    Xv = sm.add_constant(X, has_constant="add")
                    vifs = pd.Series(
                        [VIF(Xv.values, i) for i in range(1, Xv.shape[1])],  # skip const
                        index=X.columns,
                        dtype=float,
                    )
                    vmax = vifs.max()
                    if np.isnan(vmax) or vmax <= vt:
                        break
                    victim = vifs.idxmax()
                    drops["high_vif"].append(victim)
                    X = X.drop(columns=[victim])
            except Exception:
                # fail-open: if VIF not available for any reason, keep X as-is
                pass

        return X

    # --------------------- assemble & preprocess ---------------------
    def _assemble_clean_data(weights=None):
        # collect columns
        cols = {y.name: y}
        for nm, s in state["xs"]:
            cols[nm] = s

        # concat with join policy
        data = pd.concat(cols.values(), axis=1, join=pp["join_how"])
        data.columns = list(cols.keys())

        if pp["sort_index"]:
            data = data.sort_index()

        # de-duplicate index
        ddi = pp["drop_duplicate_index"]
        if ddi and ddi != "none":
            if not data.index.is_unique:
                if ddi == "keep-last":
                    data = data[~data.index.duplicated(keep="last")]
                elif ddi == "keep-first":
                    data = data[~data.index.duplicated(keep="first")]
                else:
                    raise ValueError("Duplicate index detected and 'drop_duplicate_index' set to 'error'.")

        # trim date range
        if pp["date_start"] is not None:
            data = data.loc[pd.to_datetime(pp["date_start"]) :]
        if pp["date_end"] is not None:
            data = data.loc[: pd.to_datetime(pp["date_end"])]

        # resample (after union)
        if pp["resample_rule"]:
            agg = pp["resample_agg"]
            if isinstance(agg, str):
                data = getattr(data.resample(pp["resample_rule"]), agg)()
            else:
                data = data.resample(pp["resample_rule"]).apply(agg)

        # coerce numeric
        if pp["coerce_numeric"]:
            data = data.apply(pd.to_numeric, errors="coerce")

        # per-column missing threshold
        if isinstance(pp["max_missing_frac"], (float, int)):
            miss = data.isna().mean()
            to_drop = miss.index[miss > float(pp["max_missing_frac"])].tolist()
            if to_drop:
                state["dropped_columns"]["missing"].extend(to_drop)
                data = data.drop(columns=to_drop)

        # fill and/or interpolate
        if pp["fill_method"] in ("ffill", "bfill"):
            data = data.fillna(method=pp["fill_method"], limit=pp["fill_limit"])
        if pp["interpolate"]:
            try:
                data = data.interpolate(method=pp["interpolate_method"], limit_direction="both", **pp["interpolate_kwargs"])
            except Exception:
                data = data.interpolate(limit_direction="both")

        # optional log (positive only)
        if pp["log"]:
            pos = (data > 0).all()
            data.loc[:, pos] = np.log(data.loc[:, pos])

        # diff/returns (yours) or per-config periods
        if on_diff:
            p = int(pp["diff_periods"] or 1)
            data = data.diff(p)
        elif on_returns:
            p = int(pp["return_periods"] or 1)
            data = data.pct_change(p)

        # demean / zscore (after diff/returns)
        if pp["demean"]:
            data = data - data.mean()
        if pp["zscore"]:
            sd = data.std(ddof=1).replace(0, np.nan)
            data = (data - data.mean()) / sd

        # outliers
        data = _apply_outliers(data)

        # final NA drop
        if pp["dropna_how"] in ("any", "all"):
            data = data.dropna(how=pp["dropna_how"])
        data = data.dropna()

        # split y/X
        y_used = data[y.name]
        X_used = data.drop(columns=[y.name])

        # scale (X and optionally y)
        if pp["scale"]["type"] is not None and len(X_used.columns) > 0:
            X_used = _scale_X(X_used)
        if pp["scale"]["scale_y"]:
            typ = pp["scale"]["type"]
            if typ == "standard":
                mu, sd = y_used.mean(), y_used.std(ddof=1)
                if sd and np.isfinite(sd):
                    y_used = (y_used - mu) / sd if pp["scale"]["with_centering"] else y_used / sd
                    state["scalers"]["y"] = ("standard", mu, sd)
            elif typ == "minmax":
                lo, hi = pp["scale"]["range"]
                mn, mx = y_used.min(), y_used.max()
                rng = mx - mn
                if rng and np.isfinite(rng):
                    y_used = lo + (y_used - mn) * (hi - lo) / rng
                    state["scalers"]["y"] = ("minmax", mn, mx, lo, hi)
            elif typ == "robust":
                med = y_used.median()
                iqr = y_used.quantile(0.75) - y_used.quantile(0.25)
                if iqr and np.isfinite(iqr):
                    y_used = (y_used - med) / iqr if pp["scale"]["with_centering"] else y_used / iqr
                    state["scalers"]["y"] = ("robust", med, iqr)

        # collinearity pruning on X
        if len(X_used.columns) > 1:
            X_used = _collinearity_prune(X_used)

        # attach weights if any
        w_used = None
        if weights is not None:
            w_used = weights if isinstance(weights, pd.Series) else pd.Series(weights, index=data.index).reindex(y_used.index)
        if w_used is None and "_w_" in X_used.columns:
            w_used = X_used["_w_"]
            X_used = X_used.drop(columns=["_w_"], errors="ignore")

        # const
        if add_constant and len(X_used.columns) > 0:
            X_used = sm.add_constant(X_used)

        # aligned DatetimeIndex
        date_used = pd.DatetimeIndex(y_used.index)
        return X_used, y_used, date_used, w_used

    # --------------------- fit ---------------------
    def fit(
        *,
        model: str = "OLS",
        weights: Optional[Union[pd.Series, np.ndarray, list]] = None,
        tls_x_errs: Optional[np.ndarray] = None,
        tls_y_errs: Optional[np.ndarray] = None,
        tls_lambda: Optional[Union[float, Sequence[float]]] = None,
        verbose: bool = False,
        pcr_n_components: Optional[Union[int, float]] = None,  # int k or float variance threshold
        pcr_scale: bool = True,
    ):
        if len(state["xs"]) == 0:
            raise ValueError("No independent variables added. Call add_indep_var(...) first.")

        model = model.upper()
        if model not in {"OLS", "WLS", "GLS", "TLS", "PCR"}:
            raise ValueError("model must be one of {'OLS','WLS','GLS','TLS', 'PCR'}")

        X_used, y_used, date_used, w_used = _assemble_clean_data(weights=weights)

        if X_used.shape[0] <= (X_used.shape[1]):
            raise ValueError(f"Not enough observations after preprocessing: n={X_used.shape[0]}, p={X_used.shape[1]}.")

        if model == "TLS":
            X_tls = X_used.drop(columns=["const"]) if "const" in X_used.columns else X_used.copy()

            # If the user passed a lambda but not explicit sx/sy, build them.
            if tls_x_errs is None and tls_y_errs is None and tls_lambda is not None:
                lam = np.asarray(tls_lambda, dtype=float)
                n, k = X_tls.shape
                if lam.ndim == 0:
                    sx = np.full((n, k), np.sqrt(float(lam)))
                elif lam.shape == (k,):
                    sx = np.sqrt(lam)[None, :].repeat(n, axis=0)
                else:
                    raise ValueError("tls_lambda must be a scalar or length-k array.")
                sy = np.ones(n, dtype=float)
                res = _tls_fit(X_tls, y_used, x_errs=sx, y_errs=sy, verbose=verbose)
            else:
                res = _tls_fit(X_tls, y_used, x_errs=tls_x_errs, y_errs=tls_y_errs, verbose=verbose)

        else:
            if model == "OLS":
                sm_model = sm.OLS(y_used, X_used)
            elif model == "WLS":
                if w_used is None and weights is None:
                    raise ValueError("WLS requires 'weights'. Provide weights aligned to data.")
                sm_model = sm.WLS(y_used, X_used, weights=(w_used if w_used is not None else weights))

            elif model == "PCR":
                X_pcr = X_used.drop(columns=["const"], errors="ignore")
                if X_pcr.shape[1] == 0:
                    raise ValueError("PCR requires at least one non-constant regressor.")
                res = _pcr_fit(
                    X_pcr,
                    y_used,
                    n_components=pcr_n_components,  # None->95% variance; float->threshold; int->k comps
                    scale=pcr_scale,
                    verbose=verbose,
                )

            else:
                sm_model = sm.GLS(y_used, X_used)
            res = sm_model.fit()
            if verbose:
                print(res.summary())

        state["model"] = model
        state["results"] = res
        state["X_used"] = X_used
        state["y_used"] = y_used
        state["date_used"] = date_used

        if model == "PCR":
            state["pcr_info"] = res.pcr_info
        else:
            state["pcr_info"] = None

        return res

    def _eqn_text(res):
        params = res.params
        rsq = res.rsquared
        parts = []
        for k, v in params.items():
            if k == "const":
                parts.append(f"{v:.3f}")
            else:
                parts.append(f"{v:+.3f}*{k}")
        return f"y = {' '.join(parts)}\nR² = {rsq:.3f}"

    def _scatter_with_optional_date(ax, x_vals, y_vals, *, use_date_color_bar: bool, cmap: str):
        if use_date_color_bar and state["date_used"] is not None:
            d = state["date_used"]
            d0 = d.min()
            date_num = ((d - d0).asi8 / 1e9).astype(float)
            sc = ax.scatter(np.asarray(x_vals), np.asarray(y_vals), c=date_num, cmap=cmap, alpha=0.85)
            cbar = plt.colorbar(sc, ax=ax)
            cbar.set_label("Date")
            ticks = np.linspace(date_num.min(), date_num.max(), num=8)
            cbar.set_ticks(ticks)
            cbar.set_ticklabels(pd.to_datetime(ticks, unit="s", origin=d0).strftime("%Y-%m-%d"))
        else:
            ax.scatter(np.asarray(x_vals), np.asarray(y_vals), alpha=0.85)

    def _format_last_date(ts):
        ts = pd.Timestamp(ts)
        return ts.strftime("%Y-%m-%d") if ts.time() == datetime.time(0, 0, 0) else ts.isoformat(sep=" ")

    def plot_actual_vs_predicted(
        title: Optional[str] = None,
        date_color_bar: Optional[bool] = None,
        cmap: str = "viridis",
        diff_verb: Optional[str] = None,  # e.g. "changes" or "returns"
    ):
        if state["results"] is None:
            raise RuntimeError("Call fit(...) before plotting.")

        res = state["results"]
        y_used = state["y_used"]
        y_hat = res.fittedvalues
        use_bar = state["date_color_bar_default"] if date_color_bar is None else bool(date_color_bar)

        xcols = [c for c in state["X_used"].columns if c != "const"]
        x_name = ", ".join(xcols) if xcols else "x"
        if on_returns:
            suffix = f" ({diff_verb or 'returns'})"
        elif on_diff:
            suffix = f" ({diff_verb or 'changes'})"
        else:
            suffix = ""

        fig, ax = plt.subplots()
        _scatter_with_optional_date(ax, y_hat, y_used, use_date_color_bar=use_bar, cmap=cmap)

        last_idx = y_used.index[-1]
        last_date = state["date_used"][-1]
        ax.scatter(
            [y_hat.loc[last_idx]],
            [y_used.loc[last_idx]],
            s=75,
            color="red",
            edgecolor="black",
            linewidth=1,
            zorder=5,
            label=f"Most Recent: {_format_last_date(last_date)}",
        )

        low = np.nanmin([y_hat.min(), y_used.min()])
        high = np.nanmax([y_hat.max(), y_used.max()])
        pad = 0.02 * (high - low) if np.isfinite(high - low) else 0.0
        x0, x1 = low - pad, high + pad
        ax.set_xlim(x0, x1)
        ax.set_ylim(x0, x1)
        # ax.plot([x0, x1], [x0, x1], "k--", linewidth=1)

        show_calibration = True
        if show_calibration:
            xs = np.array([x0, x1])

            if state["model"] == "TLS":

                def _f(p, x):
                    return p[0] * x + p[1]

                cal_out = ODR(RealData(y_hat.values, y_used.values), Model(_f), beta0=[1.0, 0.0]).run()
                m, b = cal_out.beta
                ax.plot(xs, m * xs + b, "k--", linewidth=1.2, color="gray")
            else:
                cal = sm.OLS(y_used, sm.add_constant(y_hat)).fit()
                b = float(cal.params["const"])
                m = float(cal.params[cal.params.index.difference(["const"])[0]])
                ax.plot(xs, m * xs + b, "k--", linewidth=1.2, color="gray")

        ax.set_xlabel(f"{x_name}{suffix}")
        ax.set_ylabel(f"{y_used.name}{suffix}")
        ax.set_title(title or f"{state['model']}{suffix}: {y_used.name} vs {x_name}")

        ax.plot([], [], " ", label=_eqn_text(res))
        ax.legend(fontsize="large")
        ax.grid(True)
        plt.show()

    def plot_residuals_vs_predicted(
        title: Optional[str] = None,
        date_color_bar: Optional[bool] = None,
        cmap: str = "viridis",
        diff_verb: Optional[str] = None,  # e.g. "changes" or "returns"
    ):
        if state["results"] is None:
            raise RuntimeError("Call fit(...) before plotting.")

        res = state["results"]
        y_hat = res.fittedvalues
        resid = res.resid
        use_bar = state["date_color_bar_default"] if date_color_bar is None else bool(date_color_bar)

        xcols = [c for c in state["X_used"].columns if c != "const"]
        x_name = ", ".join(xcols) if xcols else "x"
        if on_returns:
            suffix = f" ({diff_verb or 'returns'})"
        elif on_diff:
            suffix = f" ({diff_verb or 'changes'})"
        else:
            suffix = ""

        fig, ax = plt.subplots()
        _scatter_with_optional_date(ax, y_hat, resid, use_date_color_bar=use_bar, cmap=cmap)

        last_idx = resid.index[-1]
        last_date = state["date_used"][-1]
        ax.scatter(
            [y_hat.loc[last_idx]],
            [resid.loc[last_idx]],
            s=75,
            color="red",
            edgecolor="black",
            linewidth=1,
            zorder=5,
            label=f"Most Recent: {_format_last_date(last_date)}",
        )

        ax.axhline(0.0, color="red", linestyle="--", linewidth=1)

        ax.set_xlabel(f"{x_name}{suffix}")
        ax.set_ylabel(f"Residuals of {state['y_used'].name}{suffix}")
        ax.set_title(title or f"Residuals: {state['y_used'].name}{suffix} vs {x_name}{suffix}")

        ax.plot([], [], " ", label=_eqn_text(res))
        ax.legend(fontsize="large")
        ax.grid(True)
        plt.show()

    def plot_residuals_timeseries(
        title: Optional[str] = None,
        plot_zscores: bool = False,
        plot_zero: bool = False,
        stds: Optional[Union[int, float, list, tuple]] = (),
        diff_verb: Optional[str] = None,  # e.g. "changes" or "returns"
        ou_bands: bool = False,
        ou_steps: int = 126,
        ou_bandalpha: float = 0.15,
    ):
        if state["results"] is None:
            raise RuntimeError("Call fit(...) before plotting.")

        res = state["results"]
        # Align residuals to the fitted sample index just in case
        resid = pd.Series(res.resid, index=state["y_used"].index).dropna()

        # Suffix for labels/titles
        if on_returns:
            suffix = f" ({diff_verb or 'returns'})"
        elif on_diff:
            suffix = f" ({diff_verb or 'changes'})"
        else:
            suffix = ""

        # Choose series to plot (this is also what we calibrate OU on if requested)
        if plot_zscores:
            mu = float(resid.mean())
            sd = float(resid.std(ddof=1))
            z = (resid - mu) / sd if np.isfinite(sd) and sd > 0 else resid * 0.0
            series = z
            y_label = "Z-Scores"
            center = 0.0
        else:
            series = resid
            y_label = f"Residuals of {state['y_used'].name}{suffix}"
            center = float(series.mean())

        # Build title
        xcols = [c for c in state["X_used"].columns if c != "const"]
        x_name = ", ".join(xcols) if xcols else "x"
        ttl = title or f"Residuals: {state['y_used'].name}{suffix} regressed on {x_name}{suffix}"

        # Plot historical residuals
        fig, ax = plt.subplots()
        ax.plot(series.index, series.values, linestyle="-", linewidth=1.2, label="Residuals")

        # Mean/zero line
        if plot_zero:
            ax.axhline(center, color="red", linestyle="--", linewidth=1, label=("Mean" if not plot_zscores else "Zero"))

        # Static σ-bands on the historical sample (optional)
        if stds is not None:
            if not isinstance(stds, (list, tuple, np.ndarray)):
                stds = [stds]
            sd_hist = float(series.std(ddof=1))
            if np.isfinite(sd_hist) and sd_hist > 0:
                for k in stds:
                    k = float(k)
                    upper = center + k * sd_hist
                    lower = center - k * sd_hist
                    h = ax.axhline(upper, linestyle="--", linewidth=1, label=(f"+{k}σ (hist)" if not plot_zscores else f"+{k} (hist)"))
                    ax.axhline(lower, linestyle="--", linewidth=1, color=h.get_color(), label=(f"-{k}σ (hist)" if not plot_zscores else f"-{k} (hist)"))

        # OU mean-reversion forecast bands (forward-looking)
        if ou_bands:
            try:
                # Calibrate on the plotted series (residuals or z-scores)
                df_calib = series.to_frame(name="resid")
                if df_calib.shape[0] < 3:
                    raise ValueError("OU calibration requires at least 3 observations.")

                ou_df, fpt = simulate_mean_reversion_ou(df_calib, steps=ou_steps)

                # Plot mean path
                (ou_mean_line,) = ax.plot(ou_df.index, ou_df["mean_reversion"].values, linestyle="-", linewidth=1.45, label="OU mean path", color="skyblue")

                if "+1_sigma" in ou_df.columns and "-1_sigma" in ou_df.columns:
                    (up1,) = ax.plot(ou_df.index, ou_df["+1_sigma"].values, linestyle="--", linewidth=1.2, color="lightcoral", alpha=0.90)
                    ax.plot(ou_df.index, ou_df["-1_sigma"].values, linestyle="--", linewidth=1.2, color=up1.get_color())

                if "+2_sigma" in ou_df.columns and "-2_sigma" in ou_df.columns:
                    (up2,) = ax.plot(ou_df.index, ou_df["+2_sigma"].values, linestyle="-.", linewidth=1.2, color="lightcoral", alpha=0.90)
                    ax.plot(ou_df.index, ou_df["-2_sigma"].values, linestyle="-.", linewidth=1.2, color=up2.get_color())

                mu_inf = float(ou_df["mean_reversion"].iloc[-1]) if "mean_reversion" in ou_df.columns else np.nan
                if "+1_sigma" in ou_df.columns and "mean_reversion" in ou_df.columns:
                    sigma_inf = float(ou_df["+1_sigma"].iloc[-1] - ou_df["mean_reversion"].iloc[-1])
                else:
                    sigma_inf = np.nan

                label_bits = []
                if fpt is not None and np.isfinite(fpt):
                    label_bits.append(f"OU FPT≈{fpt:.0f} steps")
                if np.isfinite(mu_inf):
                    label_bits.append(f"μ∞≈{mu_inf:.3f}")
                if np.isfinite(sigma_inf):
                    label_bits.append(f"σ∞≈{sigma_inf:.3f}")
                    label_bits.append(f"μ∞±1σ≈[{mu_inf - sigma_inf:.3f}, {mu_inf + sigma_inf:.3f}]")
                    label_bits.append(f"μ∞±2σ≈[{mu_inf - 2*sigma_inf:.3f}, {mu_inf + 2*sigma_inf:.3f}]")

                ax.plot([], [], " ", label="; ".join(label_bits))

            except NameError:
                raise RuntimeError("simulate_mean_reversion_ou is not defined. Please import/define it, " "or set ou_bands=False.")

        # “Most Recent” level as a horizontal line with legend entry
        last_dt = series.index[-1]
        last_val = float(series.iloc[-1])
        ax.axhline(
            y=last_val,
            color="red",
            linestyle="-",
            alpha=0.75,
            zorder=6,
            label=f"Most Recent: {_format_last_date(last_dt)} (value={last_val:.2f})",
        )

        # Cosmetics
        ax.set_xlabel("Date")
        ax.set_ylabel(y_label)
        ax.set_title(ttl)
        # Include model stats snippet in the legend (same style as your other plots)
        ax.plot([], [], " ", label=_eqn_text(res))
        ax.legend(loc=(0, 0), fontsize="large")
        ax.grid(True)
        plt.show()

    def _rolling_core(
        *,
        model: Optional[str] = None,
        window: Optional[int] = None,
        weights: Optional[Union[pd.Series, np.ndarray, list]] = None,
        tls_x_errs: Optional[np.ndarray] = None,
        tls_y_errs: Optional[np.ndarray] = None,
        tls_lambda: Optional[Union[float, Sequence[float]]] = None,
        pcr_n_components: Optional[Union[int, float]] = None,
        pcr_scale: bool = True,
        step: int = 1,
        min_obs: Optional[int] = None,
        verbose: bool = False,
    ):
        """
        Run rolling regressions using the current preprocessing settings and design.
        Returns (beta_df, r2_series).
        """
        # Build full-sample design first (uses your preprocessing config)
        X_used, y_used, date_used, w_used = _assemble_clean_data(weights=weights)

        # Resolve model and window
        mdl = (model.upper() if isinstance(model, str) else (state["model"] or "OLS")).upper()
        if mdl not in {"OLS", "WLS", "GLS", "TLS", "PCR"}:
            raise ValueError("model must be one of {'OLS','WLS','GLS','TLS','PCR'}")

        W = int(window or state["window_default"] or 60)  # sane default = 60
        if W < 3:
            raise ValueError("window must be >= 3.")

        # Columns for parameter matrix (respect constant the same way as fit())
        beta_cols = list(X_used.columns) if len(X_used.columns) else (["const"] if add_constant else [])
        beta_df = pd.DataFrame(index=y_used.index[max(W - 1, 0) :], columns=beta_cols, dtype=float)
        r2 = pd.Series(index=beta_df.index, dtype=float, name="R2")

        # Minimum observations (by default: a bit over-identified)
        if min_obs is None:
            p = max(len(beta_cols), 1)
            min_obs = max(p + 1, 3)
        step = int(step) if step and step > 0 else 1

        # Rolling loop
        n = len(y_used)
        for end in range(W - 1, n, step):
            start = end - W + 1
            yw = y_used.iloc[start : end + 1]
            Xw = X_used.iloc[start : end + 1]

            if len(yw) < min_obs or Xw.shape[0] <= Xw.shape[1]:
                # under-identified window; leave NaNs
                continue

            try:
                if mdl == "PCR":
                    Xp = Xw.drop(columns=["const"], errors="ignore")
                    if Xp.shape[1] == 0:
                        # no regressors; skip
                        continue
                    res_w = _pcr_fit(
                        Xp,
                        yw,
                        n_components=pcr_n_components,
                        scale=pcr_scale,
                        verbose=False,
                    )

                elif mdl == "TLS":
                    X_tls = Xw.drop(columns=["const"], errors="ignore")
                    if tls_x_errs is None and tls_y_errs is None and tls_lambda is not None:
                        lam = np.asarray(tls_lambda, dtype=float)
                        nn, kk = X_tls.shape
                        if lam.ndim == 0:
                            sx = np.full((nn, kk), np.sqrt(float(lam)))
                        elif lam.shape == (kk,):
                            sx = np.sqrt(lam)[None, :].repeat(nn, axis=0)
                        else:
                            raise ValueError("tls_lambda must be a scalar or length-k array.")
                        sy = np.ones(nn, dtype=float)
                        res_w = _tls_fit(X_tls, yw, x_errs=sx, y_errs=sy, verbose=False)
                    else:
                        res_w = _tls_fit(X_tls, yw, x_errs=tls_x_errs, y_errs=tls_y_errs, verbose=False)

                else:
                    if mdl == "WLS":
                        ww = w_used.iloc[start : end + 1] if w_used is not None else None
                        if ww is None:
                            raise ValueError("WLS rolling requires 'weights' provided to the builder or to rolling call.")
                        sm_model = sm.WLS(yw, Xw, weights=ww)
                    elif mdl == "GLS":
                        sm_model = sm.GLS(yw, Xw)
                    else:  # OLS
                        sm_model = sm.OLS(yw, Xw)
                    res_w = sm_model.fit()

                # Store params aligned to full beta_cols (const + original features)
                params_w = res_w.params.reindex(beta_cols)
                beta_df.iloc[beta_df.index.get_loc(yw.index[-1])] = params_w.values
                r2.iloc[r2.index.get_loc(yw.index[-1])] = getattr(res_w, "rsquared", np.nan)

            except Exception as e:
                if verbose:
                    print(f"Rolling fit failed on window ending {yw.index[-1]}: {e}")
                # keep NaNs and continue
                continue

        return beta_df, r2

        # --------------------- public rolling APIs ---------------------

    def rolling_beta(
        *,
        window: Optional[int] = None,
        model: Optional[str] = None,
        name: Optional[str] = None,
        step: int = 1,
        min_obs: Optional[int] = None,
        weights: Optional[Union[pd.Series, np.ndarray, list]] = None,
        tls_x_errs: Optional[np.ndarray] = None,
        tls_y_errs: Optional[np.ndarray] = None,
        tls_lambda: Optional[Union[float, Sequence[float]]] = None,
        pcr_n_components: Optional[Union[int, float]] = None,
        pcr_scale: bool = True,
        verbose: bool = False,
    ) -> Union[pd.DataFrame, pd.Series]:
        """
        Rolling betas over time (index = window end date).
        - If `name` is None: returns a DataFrame of all parameters (including 'const' if present).
        - If `name` provided: returns a Series for that coefficient.
        """
        beta_df, _ = _rolling_core(
            model=model,
            window=window,
            weights=weights,
            tls_x_errs=tls_x_errs,
            tls_y_errs=tls_y_errs,
            tls_lambda=tls_lambda,
            pcr_n_components=pcr_n_components,
            pcr_scale=pcr_scale,
            step=step,
            min_obs=min_obs,
            verbose=verbose,
        )
        if name is None:
            return beta_df
        if name not in beta_df.columns:
            raise KeyError(f"Coefficient '{name}' not found. Available: {list(beta_df.columns)}")
        out = beta_df[name].copy()
        out.name = f"beta[{name}]"
        return out

    def rolling_r2(
        *,
        window: Optional[int] = None,
        model: Optional[str] = None,
        step: int = 1,
        min_obs: Optional[int] = None,
        weights: Optional[Union[pd.Series, np.ndarray, list]] = None,
        tls_x_errs: Optional[np.ndarray] = None,
        tls_y_errs: Optional[np.ndarray] = None,
        tls_lambda: Optional[Union[float, Sequence[float]]] = None,
        pcr_n_components: Optional[Union[int, float]] = None,
        pcr_scale: bool = True,
        verbose: bool = False,
    ) -> pd.Series:
        """Rolling R² over time (index = window end date)."""
        _, r2 = _rolling_core(
            model=model,
            window=window,
            weights=weights,
            tls_x_errs=tls_x_errs,
            tls_y_errs=tls_y_errs,
            tls_lambda=tls_lambda,
            pcr_n_components=pcr_n_components,
            pcr_scale=pcr_scale,
            step=step,
            min_obs=min_obs,
            verbose=verbose,
        )
        return r2
    
    def rolling_correlation(
        *,
        window: Optional[int] = None,
        step: int = 1,
        min_obs: Optional[int] = None,
        name: Optional[str] = None,
        drop_const: bool = True,
        method: str = "pearson",
    ) -> Union[pd.DataFrame, pd.Series]:
        if method.lower() != "pearson":
            raise ValueError("rolling_correlation currently supports method='pearson' only.")

        # Build full-sample design using your preprocessing pipeline
        X_used, y_used, _date_used, _ = _assemble_clean_data()

        # Choose window / min obs
        W = int(window or state.get("window_default") or 60)
        if W < 3:
            raise ValueError("window must be >= 3.")
        mp = int(min_obs) if min_obs is not None else W

        # Select columns to correlate with y
        Xc = X_used.drop(columns=["const"], errors="ignore") if drop_const else X_used.copy()
        if Xc.shape[1] == 0:
            raise ValueError("No regressors available for correlation (after dropping 'const').")

        # Compute rolling Pearson correlations
        corr_df = pd.DataFrame(index=y_used.index, columns=Xc.columns, dtype=float)
        for col in Xc.columns:
            corr_df[col] = y_used.rolling(window=W, min_periods=mp).corr(Xc[col])

        # Keep indices that correspond to fully-formed windows; apply step
        corr_df = corr_df.iloc[W-1::max(int(step), 1)]

        if name is None:
            return corr_df
        if name not in corr_df.columns:
            raise KeyError(f"'{name}' not found. Available: {list(corr_df.columns)}")
        out = corr_df[name].copy()
        out.name = f"corr(y,{name})"
        return out

    def get_data():
        return state["X_used"], state["y_used"], state["results"]

    if window is not None:
        return (
            add_indep_var,
            fit,
            plot_actual_vs_predicted,
            plot_residuals_vs_predicted,
            plot_residuals_timeseries,
            get_data,
            rolling_beta,
            rolling_r2,
            rolling_correlation
        )

    return add_indep_var, fit, plot_actual_vs_predicted, plot_residuals_vs_predicted, plot_residuals_timeseries, get_data
