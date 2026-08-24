r"""GV block — the sizing rules, and the mark-noise model that motivates them.

The brief for this block is one objection: *the previous backtest results look
bad because of sizing.*  Scaling a whole book cannot change its Sharpe, so the
objection can only be about the **relative** size of the two legs.  Three
mechanisms were measured before the pre-registration was frozen and each one is
implemented here as a named, comparable rule rather than argued about:

``beta_chg``
    Rolling OLS of ``dCA`` on ``dleg``.  Unbiased (the mark noise is in the
    dependent variable) but its residual variance carries ``2*nu`` of noise
    regardless of window length, so ``SE(beta_hat)`` is large and a 252-day
    rolling estimate is close to random.  Block 3's family A.

``beta_lvl``
    Rolling OLS of ``CA`` on ``leg`` in LEVELS.  Block 3's family B, and the
    brief's own printed regression.  Measured on 2026: ``beta_lvl = +0.1461``
    while the daily co-movement is ``-0.0970`` -- **opposite signs**.  Because
    ``var(dCA - b*dleg) = var(dCA) - 2b*cov + b^2*var(dleg)`` and ``cov < 0``,
    a positive ``b`` ADDS variance.  A "hedge" with the wrong sign is a sizing
    defect that no amount of scaling repairs.

``vega_match``
    The brief's own framing -- the CA is a price of variance, a butterfly is a
    linear-space vol proxy, so match their **vol sensitivities**.  Under Citi's
    convention ``CA_bp = sigma_bp^2 * w / 2e4`` with ``w = mean_i(T1_i^2)``,
    so ``dCA_bp/dsigma_bp = sigma_bp * w / 1e4``.  The leg's own
    ``dleg_bp/dsigma_bp`` is fitted against the matched ATMF normal vol.  Both
    derivatives are evaluated at the SAME linearisation point -- the market's
    benchmark vol -- so the rule is defined on every date including the ZIRP
    days where the CA is negative and has no real implied vol at all.

``vol_ratio``
    Risk parity: ``sign(rho) * sd(dCA_denoised) / sd(dleg)``.  Needs no vol
    regression, so it is the rule that survives when ``vega_match``'s gate binds.

Units, stated once:  CA and legs in **bp**; normal vol in **bp/yr**; ``w`` in
**years^2**; a beta is **bp of CA per bp of leg**; a leg's size is
``leg_dv01`` = USD per bp of the QUOTED combination (see ``gv_universe``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "NoiseFit",
    "noise_fit",
    "kalman_ewma_alpha",
    "denoise",
    "BURN_IN_BD",
    "fit_denoise_halflives",
    "ca_implied_variance_bp2",
    "ca_implied_vol_bp",
    "ca_vega_bp_per_bp",
    "rolling_beta_changes",
    "rolling_beta_levels",
    "rolling_vol_beta",
    "rolling_vol_ratio",
    "VOL_BETA_T_MIN",
    "VOL_BETA_R2_MIN",
    "SIZING_RULES",
    "sizing_beta",
]

#: The window used to estimate each structure's mark-noise ratio, and hence its
#: denoising half-life.  Estimated ONCE on the first ``BURN_IN_BD`` panel dates
#: and frozen for the whole backtest -- a trailing estimate would make the
#: filter time-varying and a full-sample estimate would be look-ahead.
BURN_IN_BD = 252

#: Gates on the leg-vs-vol regression that ``vega_match`` divides by.  A
#: noise-sized slope in a denominator produces an unbounded hedge, so a day that
#: fails either gate cannot open a position and the refusal is counted.
VOL_BETA_T_MIN = 2.0
VOL_BETA_R2_MIN = 0.20


# ---------------------------------------------------------------------------
# 1. The mark-noise model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NoiseFit:
    """Moment inversion of ``observed = true(random walk) + iid noise``.

    ``var(d) = tau + 2*nu`` and ``cov(d_t, d_{t-1}) = -nu``, so
    ``ac1 = -nu / (tau + 2*nu)``.  That is bounded below by ``-0.5``, attained
    only when ``tau = 0``: a series whose daily change autocorrelates at -0.5 is
    pure measurement noise.  Inverting,

        ``nu  = -ac1 * var(d)``
        ``tau = var(d) * (1 + 2*ac1)``

    and ``tau <= 0`` is reported as ``pure_noise`` rather than clipped silently.
    """

    n: int
    ac1: float
    var_d: float
    sigma_true: float
    sigma_noise: float
    pure_noise: bool

    @property
    def noise_ratio(self) -> float:
        """``sigma_noise / sigma_true``; ``inf`` for a pure-noise series."""
        if self.sigma_true <= 0:
            return float("inf")
        return self.sigma_noise / self.sigma_true

    @property
    def snr(self) -> float:
        """``q = tau / nu`` -- the local-level model's signal-to-noise ratio."""
        if self.sigma_noise <= 0:
            return float("inf")
        return (self.sigma_true ** 2) / (self.sigma_noise ** 2)


def noise_fit(level: pd.Series) -> NoiseFit:
    d = pd.Series(level).astype(float).dropna().diff().dropna()
    n = int(len(d))
    if n < 30:
        return NoiseFit(n, float("nan"), float("nan"), float("nan"),
                        float("nan"), False)
    ac1 = float(d.autocorr(1))
    var_d = float(d.var(ddof=1))
    nu = max(0.0, -ac1 * var_d)
    tau = var_d * (1.0 + 2.0 * ac1)
    pure = tau <= 0.0
    return NoiseFit(n, ac1, var_d,
                    float(math.sqrt(max(tau, 0.0))),
                    float(math.sqrt(nu)), bool(pure))


def kalman_ewma_alpha(snr: float) -> float:
    """Steady-state Kalman gain of the local-level model, ``q = tau/nu``.

    ``K = (-q + sqrt(q^2 + 4q)) / 2``.  The steady-state filter of a random walk
    observed with iid noise IS an EWMA with weight ``K`` on the new observation,
    so this is not an approximation to the optimal filter -- it is the optimal
    filter, written as the one-parameter form the pandas API already has.

    ``q -> inf`` (no noise) gives ``K -> 1`` (no smoothing); ``q -> 0`` gives
    ``K -> 0``.
    """
    q = float(snr)
    if not np.isfinite(q):
        return 1.0
    if q <= 0:
        return 1e-6
    return float((-q + math.sqrt(q * q + 4.0 * q)) / 2.0)


def _alpha_to_halflife(alpha: float) -> float:
    a = min(max(float(alpha), 1e-9), 1 - 1e-9)
    return float(math.log(0.5) / math.log(1.0 - a))


def denoise(level: pd.Series, halflife: float) -> pd.Series:
    """Causal EWMA of a level series.

    Used for **signals only**.  P&L is always marked on the raw panel: smoothing
    a signal is legitimate, smoothing an execution price is not, and this
    module never returns a smoothed series into a P&L path.
    """
    hl = float(halflife)
    if hl <= 0:
        return pd.Series(level).astype(float)
    return pd.Series(level).astype(float).ewm(halflife=hl, adjust=False).mean()


def fit_denoise_halflives(panel: pd.DataFrame, cols: Sequence[str], *,
                          burn_in: int = BURN_IN_BD) -> pd.DataFrame:
    """Per-column noise fit and Kalman-optimal EWMA half-life, on the burn-in.

    Returns the fit on the burn-in (what the backtest uses) alongside the
    full-sample fit (reported, never used), so the gap between them is visible
    rather than assumed away.
    """
    rows = []
    for c in cols:
        s = panel[c].dropna()
        fb = noise_fit(s.iloc[:burn_in])
        ff = noise_fit(s)
        a = kalman_ewma_alpha(fb.snr)
        rows.append({
            "column": c, "n_burn": fb.n,
            "ac1_burn": fb.ac1, "ac1_full": ff.ac1,
            "sigma_true_burn": fb.sigma_true, "sigma_noise_burn": fb.sigma_noise,
            "noise_ratio_burn": fb.noise_ratio, "noise_ratio_full": ff.noise_ratio,
            "pure_noise_burn": fb.pure_noise, "pure_noise_full": ff.pure_noise,
            "snr_burn": fb.snr, "alpha": a, "halflife_bd": _alpha_to_halflife(a),
        })
    return pd.DataFrame(rows).set_index("column")


# ---------------------------------------------------------------------------
# 2. The CA as a price of variance
# ---------------------------------------------------------------------------
def ca_implied_variance_bp2(ca_bp, w) -> pd.Series:
    """``v = 2e4 * CA_bp / w`` in ``(bp/yr)^2`` -- a SIGNED variance price.

    Kept in variance rather than vol because ``CA_bp`` is exactly linear in
    variance and goes negative on ZIRP days, where ``sqrt`` has nothing to
    return.  The variance basis signal is built on this; the vol inversion below
    is a display quantity.
    """
    return 2e4 * pd.Series(ca_bp).astype(float) / pd.Series(w).astype(float)


def ca_implied_vol_bp(ca_bp, w) -> pd.Series:
    """``sigma = sqrt(v)`` in bp/yr, NaN where the adjustment is non-positive."""
    v = ca_implied_variance_bp2(ca_bp, w)
    return np.sqrt(v.where(v > 0))


def ca_vega_bp_per_bp(sigma_bench_bp, w) -> pd.Series:
    """``dCA_bp / dsigma_bp = sigma * w / 1e4``, evaluated at the BENCHMARK vol.

    Evaluating the model's derivative at the market's own vol rather than at the
    CA's implied vol is what makes this defined on every date -- including the
    ~ZIRP days where the observed CA is negative.  It also removes a feedback
    loop: a hedge ratio built from the CA's own level would move with the very
    signal it is sizing.
    """
    return (pd.Series(sigma_bench_bp).astype(float)
            * pd.Series(w).astype(float) / 1e4)


# ---------------------------------------------------------------------------
# 3. Rolling estimators
# ---------------------------------------------------------------------------
def _roll_ols(y: pd.Series, x: pd.Series, window: int, min_periods: int
              ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Rolling univariate OLS with intercept -> (beta, t_stat, r2)."""
    y = pd.Series(y).astype(float)
    x = pd.Series(x).astype(float)
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1)
    n = j["x"].rolling(window, min_periods=min_periods).count()
    mx = j["x"].rolling(window, min_periods=min_periods).mean()
    my = j["y"].rolling(window, min_periods=min_periods).mean()
    vx = j["x"].rolling(window, min_periods=min_periods).var(ddof=1)
    vy = j["y"].rolling(window, min_periods=min_periods).var(ddof=1)
    cxy = j["x"].rolling(window, min_periods=min_periods).cov(j["y"], ddof=1)
    beta = cxy / vx.replace(0.0, np.nan)
    r = cxy / np.sqrt(vx.replace(0.0, np.nan) * vy.replace(0.0, np.nan))
    r2 = r * r
    # t on beta:  r * sqrt((n-2)/(1-r^2))
    t = r * np.sqrt((n - 2).clip(lower=0) / (1.0 - r2).clip(lower=1e-12))
    _ = (mx, my)                                 # kept for readability of intent
    return beta, t, r2


def rolling_beta_changes(ca: pd.Series, leg: pd.Series, *, window: int = 252,
                         min_periods: Optional[int] = None
                         ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Hedge-ratio beta from DAILY CHANGES (block 3 family A)."""
    mp = min_periods or max(60, window // 2)
    return _roll_ols(pd.Series(ca).diff(), pd.Series(leg).diff(), window, mp)


def rolling_beta_levels(ca: pd.Series, leg: pd.Series, *, window: int = 252,
                        min_periods: Optional[int] = None
                        ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Fair-value beta from LEVELS (block 3 family B; the brief's regression)."""
    mp = min_periods or max(60, window // 2)
    return _roll_ols(pd.Series(ca), pd.Series(leg), window, mp)


def rolling_vol_beta(leg: pd.Series, nvol: pd.Series, *, window: int = 252,
                     min_periods: Optional[int] = None
                     ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """``dleg_bp / dsigma_bp`` -- is the butterfly a volatility proxy at all?

    The premise of the whole block ("swap butterflies are vol proxies in linear
    space") lives or dies on this regression, so its R2 and t are first-class
    outputs, not diagnostics.
    """
    mp = min_periods or max(60, window // 2)
    return _roll_ols(pd.Series(leg), pd.Series(nvol), window, mp)


def rolling_vol_ratio(ca_denoised: pd.Series, leg: pd.Series, *,
                      window: int = 252, min_periods: Optional[int] = None
                      ) -> pd.Series:
    """Risk-parity beta: ``sign(rho) * sd(dCA_denoised) / sd(dleg)``.

    The sign comes from the DAILY-CHANGE correlation, which is the one that says
    which way the legs actually move together; the magnitude comes from the
    denoised CA, so the hedge is not scaled by measurement noise.
    """
    mp = min_periods or max(60, window // 2)
    dc = pd.Series(ca_denoised).diff()
    dl = pd.Series(leg).diff()
    sd_c = dc.rolling(window, min_periods=mp).std(ddof=1)
    sd_l = dl.rolling(window, min_periods=mp).std(ddof=1)
    rho = dc.rolling(window, min_periods=mp).corr(dl)
    sign = np.sign(rho).replace(0.0, np.nan)
    return (sign * sd_c / sd_l.replace(0.0, np.nan)).rename("beta_vol_ratio")


# ---------------------------------------------------------------------------
# 4. The rule registry
# ---------------------------------------------------------------------------
#: Every declared sizing rule, by id.  ``none`` and ``unit`` are the two ends of
#: the plausible range and exist so the sweep is bracketed rather than centred
#: on whichever rule happened to be tried first.
SIZING_RULES: Tuple[str, ...] = (
    "beta_chg", "beta_lvl", "vega_match", "vol_ratio", "none", "unit",
)


@dataclass
class SizingInputs:
    ca: pd.Series                 # raw CA, bp
    ca_denoised: pd.Series        # EWMA CA, bp -- signals only
    leg: pd.Series                # quoted combination, bp
    nvol: pd.Series               # matched ATMF normal vol, bp/yr
    w: pd.Series                  # mean_i(T1_i^2), years^2
    window: int = 252


def sizing_beta(rule: str, inp: SizingInputs
                ) -> Tuple[pd.Series, pd.Series]:
    """``(beta, gate_ok)`` for one rule, in bp of CA per bp of leg.

    ``gate_ok`` is False on days a position may not be opened under that rule.
    Only ``vega_match`` gates; the others return an all-True mask where beta is
    finite, so the caller has one uniform contract.
    """
    r = str(rule)
    if r == "none":
        b = pd.Series(0.0, index=inp.ca.index)
        return b, pd.Series(True, index=inp.ca.index)
    if r == "unit":
        b = pd.Series(1.0, index=inp.ca.index)
        return b, pd.Series(True, index=inp.ca.index)
    if r == "beta_chg":
        b, _, _ = rolling_beta_changes(inp.ca, inp.leg, window=inp.window)
    elif r == "beta_lvl":
        b, _, _ = rolling_beta_levels(inp.ca, inp.leg, window=inp.window)
    elif r == "vol_ratio":
        b = rolling_vol_ratio(inp.ca_denoised, inp.leg, window=inp.window)
    elif r == "vega_match":
        vb, t, r2 = rolling_vol_beta(inp.leg, inp.nvol, window=inp.window)
        ok = (t.abs() >= VOL_BETA_T_MIN) & (r2 >= VOL_BETA_R2_MIN)
        ca_vega = ca_vega_bp_per_bp(inp.nvol, inp.w)
        b = (ca_vega / vb.where(ok)).rename("beta_vega_match")
        return b, ok.fillna(False) & np.isfinite(b)
    else:                                                       # pragma: no cover
        raise ValueError(f"unknown sizing rule {rule!r}; declared {SIZING_RULES}")
    b = b.rename(f"beta_{r}")
    return b, pd.Series(np.isfinite(b), index=b.index)
