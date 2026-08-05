"""The factor model: what moves the ultra-long forward slope.

Inference runs on CHANGES with HAC (Newey-West) standard errors. Levels
regressions are computed too, because they are the RV anchor the residual
z-score is built on, but they are returned with ``anchor_only=True``: in the
2026 sample the levels Durbin-Watson is ~0.2, so their t-statistics are not
evidence of anything and no consumer may treat them as such.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

__all__ = [
    "RegressionResult",
    "changes_regression",
    "levels_regression",
    "frequency_ladder",
    "durbin_watson",
    "ar1_phi",
    "ar1_half_life_days",
    "residual_z",
    "drift",
    "positive_residual_clustering",
]


@dataclass(frozen=True)
class RegressionResult:
    betas: Dict[str, float]
    tstats: Dict[str, float]
    r_squared: float
    durbin_watson: float
    n: int
    kind: str
    anchor_only: bool
    residuals: pd.Series = field(repr=False)


def durbin_watson(resid) -> float:
    e = pd.Series(resid).astype(float).dropna().to_numpy()
    if e.size < 3:
        return float("nan")
    de = np.diff(e)
    return float((de @ de) / (e @ e))


def _fit(y: pd.Series, X: pd.DataFrame, *, kind: str, anchor_only: bool,
         hac_lags: Optional[int]) -> RegressionResult:
    data = pd.concat([y.rename("_y_"), X], axis=1).dropna()
    if len(data) < 10:
        raise ValueError(f"only {len(data)} aligned observations")
    cols = [c for c in data.columns if c != "_y_"]
    Xm = sm.add_constant(data[cols])
    model = sm.OLS(data["_y_"], Xm).fit()
    lags = hac_lags if hac_lags is not None else max(1, int(round(len(data) ** 0.25)))
    robust = model.get_robustcov_results(cov_type="HAC", maxlags=lags)
    return RegressionResult(
        betas={c: float(model.params[c]) for c in cols},
        tstats={c: float(robust.tvalues[list(Xm.columns).index(c)]) for c in cols},
        r_squared=float(model.rsquared),
        durbin_watson=durbin_watson(model.resid),
        n=int(len(data)),
        kind=kind,
        anchor_only=anchor_only,
        residuals=model.resid,
    )


def changes_regression(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    *,
    horizon_days: int = 1,
    hac_lags: Optional[int] = None,
) -> RegressionResult:
    """d(spread) on d(drivers) at ``horizon_days``. This is where inference lives."""
    y = pd.Series(spread_bp).astype(float).diff(horizon_days)
    X = pd.DataFrame(
        {k: pd.Series(v).astype(float).diff(horizon_days) for k, v in drivers.items()}
    )
    return _fit(y, X, kind="changes", anchor_only=False, hac_lags=hac_lags)


def levels_regression(
    spread_bp: pd.Series, drivers: Dict[str, pd.Series],
    *, hac_lags: Optional[int] = None,
) -> RegressionResult:
    """Levels fit. RV anchor only -- never inference. See the module docstring."""
    y = pd.Series(spread_bp).astype(float)
    X = pd.DataFrame({k: pd.Series(v).astype(float) for k, v in drivers.items()})
    return _fit(y, X, kind="levels", anchor_only=True, hac_lags=hac_lags)


def frequency_ladder(
    spread_bp: pd.Series,
    drivers: Dict[str, pd.Series],
    horizons: Sequence[int] = (1, 5, 21),
) -> pd.DataFrame:
    """H1: is the funding factor a weekly/monthly effect invisible daily?"""
    rows = []
    for h in horizons:
        res = changes_regression(spread_bp, drivers, horizon_days=int(h))
        rec = {"horizon_days": int(h), "r_squared": res.r_squared, "n": res.n,
               "durbin_watson": res.durbin_watson}
        for k in drivers:
            rec[f"beta_{k}"] = res.betas[k]
            rec[f"t_{k}"] = res.tstats[k]
        rows.append(rec)
    return pd.DataFrame(rows)


def ar1_phi(resid) -> float:
    """OLS AR(1) coefficient of a residual series."""
    e = pd.Series(resid).astype(float).dropna()
    if len(e) < 20:
        return float("nan")
    x, y = e.shift(1).dropna(), e.iloc[1:]
    return float(np.polyfit(x.to_numpy(), y.to_numpy(), 1)[0])


def ar1_half_life_days(resid) -> float:
    """Business days to halve. Infinite for a unit root."""
    phi = ar1_phi(resid)
    if not np.isfinite(phi) or phi <= 0.0 or phi >= 1.0:
        return float("inf")
    return float(np.log(0.5) / np.log(phi))


def residual_z(resid, *, window: int = 252, min_periods: int = 126) -> pd.Series:
    """Rolling z on the residual's OWN dispersion.

    Not the OLS standard error: that is sigma/sqrt(n), it shrinks with sample
    size, and bands built on it tighten as history accumulates until the rule
    fires constantly.
    """
    e = pd.Series(resid).astype(float)
    roll = e.rolling(int(window), min_periods=int(min_periods))
    return (e - roll.mean()) / roll.std(ddof=1)


def drift(changes_resid, *, window: int = 63) -> pd.DataFrame:
    """Signal 2: the vol-orthogonal structural drift, and its significance."""
    from RVUtils.SFRRVLab.stats import nw_tstat

    e = pd.Series(changes_resid).astype(float)
    mean = e.rolling(int(window), min_periods=int(window)).mean()
    t = e.rolling(int(window), min_periods=int(window)).apply(
        lambda w: nw_tstat(w, lags=5), raw=False
    )
    return pd.DataFrame({"mean_bp_per_day": mean, "t_stat": t})


def positive_residual_clustering(resid, *, window: int = 21) -> pd.Series:
    """Share of positive residuals in the window -- the regime tell (H4)."""
    e = pd.Series(resid).astype(float)
    return (e > 0).rolling(int(window), min_periods=int(window)).mean()
