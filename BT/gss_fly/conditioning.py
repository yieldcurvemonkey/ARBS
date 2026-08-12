"""Metrics that answer "how ill-conditioned is the GSS fly book to its parameters".

DESIGN NOTE — the estimability triage this module encodes.

    Tier 0  exact, ZERO extra backtests.  The entry gate (`zsig_bp > entry_zsig_bp`, the
            turning-point test, the cooldown, the leg-overlap veto) and the exit gate
            (`zsig <= repo_penalty_bp`, the z-rollover) never read `half_spread_bp` or
            `cost_legs` — see BT/gss_fly/strategy.py:130-201, where the only use of the cost
            config is `rt = 2.0 * fly_tcost_bp(...)` AFTER the entry decision is made. So a
            multiplicative rescale of the half-spread table leaves the trade set IDENTICAL and
            the equity curve is recoverable in closed form.  This does NOT extend to
            `repo_penalty_bp` (it IS the exit gate) or `fallback_repo_pct` (it enters QDB
            financing).
    Tier 1  exact in DECISION space, cheap.  `GSSSignalEngine.__call__` is a pure function of
            (panel.s2c, panel.ytm, cfg) — no pricing.  Trade-set conditioning is therefore
            exactly computable without QueryDrivenBacktest.
    Tier 2  noisy in PERFORMANCE space.  Anything Sharpe-valued.  With 332 days the annualised
            Sharpe SE is ~0.87 at SR=0, so cross-config Sharpe dispersion below ~1.7 is
            indistinguishable from estimation noise.  Every Tier-2 metric here is therefore
            paired with a null and is reported RELATIVE to it, never on its own scale.

Nothing here re-runs a backtest.  Everything consumes a table of
(parameter vector -> equity curve / trade log / summary).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "equity_at_cost_multiplier",
    "breakeven_cost_multiplier",
    "cost_rank_instability",
    "trade_key_set",
    "trade_set_jaccard",
    "knob_jaccard_profile",
    "rademacher_neff",
    "participation_ratio",
    "paired_neighbour_test",
    "top_set_clustering_ratio",
    "split_rank_stability",
    "rho_noise_ceiling",
    "deflated_sharpe",
    "lo_effective_T",
    "response_surface_tolerance",
]

_EULER = 0.5772156649015329


# ---------------------------------------------------------------- Tier 0: the cost axis
def equity_at_cost_multiplier(
    equity: pd.Series,
    closed: pd.DataFrame,
    m: float,
    *,
    date_col: str = "closed_at",
    fee_col: str = "fee_allocated",
    open_fee_usd: float = 0.0,
) -> pd.Series:
    """Exact equity curve if every half-spread were scaled by ``m``.

    Valid ONLY because the fee never feeds back into the trade decision (see module docstring).
    Fees are booked at the unwind date and are linear in the half-spread table, so

        equity_m(t) = equity_1(t) + (1 - m) * cumulative_fee(t)

    ``open_fee_usd`` charges a synthetic exit cost on the book still open at the last date.
    Without it every break-even number is biased UP, because `GSSExitAction` is the engine's
    only fee hook and a position that never unwound never paid.
    """
    eq = equity.dropna().sort_index()
    if closed.empty or fee_col not in closed.columns:
        cum = pd.Series(0.0, index=eq.index)
    else:
        fees = closed[[date_col, fee_col]].copy()
        fees[date_col] = pd.to_datetime(fees[date_col])
        by_day = fees.groupby(date_col)[fee_col].sum().astype(float)
        cum = by_day.reindex(eq.index, fill_value=0.0).cumsum()
    out = eq + (1.0 - float(m)) * cum
    if open_fee_usd:
        out.iloc[-1] = out.iloc[-1] - float(m) * float(open_fee_usd)
    return out


def breakeven_cost_multiplier(
    equity: pd.Series,
    closed: pd.DataFrame,
    *,
    open_fee_usd: float = 0.0,
    **kw,
) -> float:
    """``m*`` such that terminal equity is zero.  m* = gross / fees.

    READ IT AS: the fraction of the CHARGED bid/offer the book can actually pay.  m* >= 1 means
    the config survives at the costs it was charged; m* = 0.45 means it needs the market to be
    2.2x tighter than assumed.  Report max(m*) over the WHOLE sampled space: if that maximum is
    below 1, no configuration in the space is viable and the conditioning question is moot.
    """
    eq0 = equity_at_cost_multiplier(equity, closed, 0.0, open_fee_usd=0.0, **kw)
    gross = float(eq0.iloc[-1])
    fees = float(closed["fee_allocated"].astype(float).sum()) if not closed.empty else 0.0
    fees += float(open_fee_usd)
    if fees <= 0:
        return float("inf") if gross > 0 else float("nan")
    return gross / fees


def cost_rank_instability(
    per_config: Dict[str, Tuple[pd.Series, pd.DataFrame]],
    multipliers: Sequence[float] = (0.0, 0.25, 0.5, 0.75, 1.0),
    *,
    open_fee_usd: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Does "the best config" survive a change in the cost assumption?

    Returns a (multiplier x multiplier) Spearman matrix of terminal-P&L rankings, plus the
    identity of the argmax at each multiplier.  If the argmax moves as m goes 0 -> 1, then
    "the optimal parameters" is not even a well-defined object without first fixing the cost
    table — which is a conditioning statement about a knob nobody counts as a knob.
    """
    ofs = open_fee_usd or {}
    rows = {}
    for m in multipliers:
        rows[m] = {
            k: float(equity_at_cost_multiplier(eq, cl, m, open_fee_usd=ofs.get(k, 0.0)).iloc[-1])
            for k, (eq, cl) in per_config.items()
        }
    tbl = pd.DataFrame(rows)
    rho = tbl.corr(method="spearman")
    rho.attrs["argmax"] = {m: tbl[m].idxmax() for m in multipliers}
    return rho


# ---------------------------------------------------------------- Tier 1: decision space
def trade_key_set(trade_log: pd.DataFrame, *, tolerance_days: int = 0) -> set:
    """The set of decisions a config made: ``(fly_id, entry_date)`` for every ENTER.

    ``tolerance_days`` buckets the entry date so that "the same trade two days later" is not
    scored as a completely different decision.  Report BOTH the exact and the tolerant Jaccard:
    the gap between them is itself informative — a large gap means the parameters move the
    TIMING of a stable trade set, a small gap means they move the SET.
    """
    if trade_log.empty:
        return set()
    ent = trade_log[trade_log["event"] == "ENTER"]
    d = pd.to_datetime(ent["date"])
    if tolerance_days > 0:
        key = (d.astype("int64") // (86_400_000_000_000 * int(tolerance_days)))
    else:
        key = d.dt.strftime("%Y-%m-%d")
    return set(zip(ent["fly_id"].astype(str), key.astype(str)))


def trade_set_jaccard(a: pd.DataFrame, b: pd.DataFrame, *, tolerance_days: int = 0) -> float:
    """|A n B| / |A u B| over ENTER decisions.  1.0 = identical book, 0.0 = disjoint.

    This is the ONE conditioning metric that is exact at this sample size, because it measures
    the conditioning of the DECISION FUNCTION, not of a P&L estimate.  No amount of extra data
    would change it, and no null is required.
    """
    sa, sb = trade_key_set(a, tolerance_days=tolerance_days), trade_key_set(b, tolerance_days=tolerance_days)
    if not sa and not sb:
        return float("nan")
    return len(sa & sb) / max(1, len(sa | sb))


def knob_jaccard_profile(
    baseline_log: pd.DataFrame,
    perturbed: Dict[Tuple[str, float], pd.DataFrame],
    *,
    tolerance_days: int = 0,
) -> pd.DataFrame:
    """Jaccard vs relative knob perturbation, one row per (knob, step).

    ``perturbed`` maps ``(knob_name, relative_step)`` -> that config's trade log.  Add the
    finite-difference slope ``dJ/d(log knob)`` per knob: a knob whose 5% perturbation already
    costs 0.4 of the trade set is a knob the strategy cannot be specified without.
    """
    rows = []
    for (knob, step), log in perturbed.items():
        j = trade_set_jaccard(baseline_log, log, tolerance_days=tolerance_days)
        rows.append({
            "knob": knob,
            "rel_step": float(step),
            "jaccard": j,
            "n_trades": int((log["event"] == "ENTER").sum()) if not log.empty else 0,
            "decision_elasticity": (1.0 - j) / abs(float(step)) if step else np.nan,
        })
    out = pd.DataFrame(rows).sort_values(["knob", "rel_step"])
    return out


def participation_ratio(pnl: pd.DataFrame) -> float:
    """(sum lambda)^2 / sum(lambda^2) of the config-PnL covariance — cheap effective rank.

    A family of N configs that is really ONE strategy scores ~1; a family of N genuinely
    different strategies scores ~N.  Use as a cross-check on the Rademacher calibration, not as
    a substitute: it is a second-moment statistic and says nothing about the MAXIMUM, which is
    what a grid search actually reports.
    """
    x = pnl.to_numpy(dtype=float)
    x = np.nan_to_num(x - np.nanmean(x, axis=0, keepdims=True), nan=0.0)
    lam = np.linalg.eigvalsh(np.cov(x, rowvar=False))
    lam = lam[lam > 0]
    if lam.size == 0:
        return float("nan")
    return float(lam.sum() ** 2 / (lam ** 2).sum())


def rademacher_neff(
    pnl: pd.DataFrame,
    *,
    draws: int = 2000,
    ks: Sequence[int] = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
    seed: int = 0,
) -> Dict[str, float]:
    """Effective number of INDEPENDENT strategies the parameter sweep actually searched.

    Uses ``RVUtils.StatisticalFinance.ras.empirical_rademacher_complexity`` — R-hat measures how
    well the BEST member of the family fits a random sign pattern, so a grid of near-identical
    configs is charged almost nothing and a grid of genuinely different ones is charged a lot.

    Calibrated EMPIRICALLY, not by inverting the Massart bound: R-hat is computed for synthetic
    families of k i.i.d. columns with the same T and the same per-column non-trading sparsity,
    and N_eff is the k whose R-hat matches the observed one (log-linear interpolation).  The
    closed-form inversion exp(T*R^2/2) is wrong at small k (it returns ~1.4 for a single
    strategy) and must not be used.

    READ IT AS: N_eff / N near 0 -> the parameters do not define distinct strategies; the sweep
    is one bet wearing many hats, so the search is well-conditioned but also pointless.
    N_eff / N near 1 -> every config is a separate bet, the reported maximum is the max of N_eff
    independent draws, and the winner must clear a correspondingly higher bar.
    """
    from RVUtils.StatisticalFinance.ras import empirical_rademacher_complexity, standardize_returns

    rng = np.random.default_rng(seed)
    x = standardize_returns(pnl)
    T, N = x.shape
    r_obs = empirical_rademacher_complexity(x, draws=draws, rng=rng)

    # match the sparsity: a config that trades 8% of days has most of its mass at zero, and a
    # dense synthetic family would not be comparable.
    density = float(np.mean(np.abs(x) > 0))
    curve = {}
    for k in ks:
        if k > 4 * N:
            break
        z = rng.standard_normal((T, k))
        z *= (rng.random((T, k)) < max(density, 1e-3))
        z = standardize_returns(z)
        curve[k] = empirical_rademacher_complexity(z, draws=max(200, draws // 4), rng=rng)

    kk = np.array(sorted(curve), dtype=float)
    rr = np.array([curve[int(k)] for k in kk], dtype=float)
    order = np.argsort(rr)
    n_eff = float(np.exp(np.interp(r_obs, rr[order], np.log(kk[order]))))
    return {
        "r_hat": float(r_obs),
        "n_configs": int(N),
        "n_eff": n_eff,
        "n_eff_frac": n_eff / max(1, N),
        "participation_ratio": participation_ratio(pnl),
        "calibration": curve,
    }


# ---------------------------------------------------------------- Tier 2: performance space
def lo_effective_T(x: np.ndarray, max_lag: int = 10) -> float:
    """Autocorrelation-adjusted sample size, T / (1 + 2*sum (1-k/(L+1)) rho_k).

    A GSS fly is held for days, so daily P&L is serially correlated and the naive T over-counts
    independent observations.  Every Sharpe standard error and the DSR below use T_eff, not T.
    Bartlett-weighted so the correction stays positive.
    """
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    T = v.size
    if T < 3:
        return float(T)
    v = v - v.mean()
    denom = float(v @ v)
    if denom <= 0:
        return float(T)
    L = int(min(max_lag, T // 4))
    s = 0.0
    for k in range(1, L + 1):
        rho = float(v[k:] @ v[:-k]) / denom
        s += (1.0 - k / (L + 1.0)) * rho
    factor = max(1e-6, 1.0 + 2.0 * s)
    return float(T / factor)


def deflated_sharpe(
    pnl: np.ndarray,
    *,
    sr_variance_across_trials: float,
    n_trials: float,
    periods_per_year: float = 252.0,
) -> Dict[str, float]:
    """Bailey & Lopez de Prado (2014) DSR, with T replaced by the Lo-adjusted effective T.

    ``n_trials`` must be N_eff from :func:`rademacher_neff`, NOT the raw config count: the raw
    count over-deflates a correlated grid, which is the exact criticism ras.py's docstring makes.
    ``sr_variance_across_trials`` is the variance of the PER-OBSERVATION Sharpe across the
    sampled configs.

    Returns the per-observation and annualised Sharpe, the expected maximum under the null
    (``sr0``), and the DSR probability.  DSR > 0.95 is the conventional survival bar.
    """
    v = np.asarray(pnl, dtype=float)
    v = v[np.isfinite(v)]
    T = v.size
    sd = v.std(ddof=1)
    if T < 5 or sd <= 0:
        return {"sharpe_obs": np.nan, "sharpe_ann": np.nan, "sr0": np.nan, "dsr": np.nan, "T_eff": np.nan}
    sr = float(v.mean() / sd)
    t_eff = lo_effective_T(v)
    n = max(2.0, float(n_trials))
    sr0 = math.sqrt(max(sr_variance_across_trials, 0.0)) * (
        (1.0 - _EULER) * stats.norm.ppf(1.0 - 1.0 / n)
        + _EULER * stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    )
    g3 = float(stats.skew(v))
    g4 = float(stats.kurtosis(v, fisher=False))
    denom = math.sqrt(max(1e-12, 1.0 - g3 * sr + 0.25 * (g4 - 1.0) * sr * sr))
    z = (sr - sr0) * math.sqrt(max(1.0, t_eff - 1.0)) / denom
    return {
        "sharpe_obs": sr,
        "sharpe_ann": sr * math.sqrt(periods_per_year),
        "sr0": float(sr0),
        "dsr": float(stats.norm.cdf(z)),
        "T_eff": float(t_eff),
        "skew": g3,
        "kurtosis": g4,
    }


def paired_neighbour_test(pnl_a: pd.Series, pnl_b: pd.Series, *, max_lag: int = 10) -> Dict[str, float]:
    """Do two NEIGHBOURING configs differ, testing the paired difference not the two Sharpes?

    Two configs sharing 80% of their trades also share 80% of their estimation error.  Comparing
    SR(A) against SR(B) throws that away and has almost no power at T=332; testing the daily
    DIFFERENCE d_t = pnl_A(t) - pnl_B(t) keeps it and is the only version of "does this knob
    matter" that has any power at this sample size.  Newey-West because d_t inherits the
    multi-day holding autocorrelation.

    READ IT AS: across all one-step neighbour pairs, the FRACTION with |t| > 2.  Compare that
    fraction against the fraction produced by ``mcpt.shared_sign_flip_null`` on the same family,
    NOT against a nominal 5% — the nominal rate is wrong under serial correlation.
    """
    d = (pnl_a.reindex(pnl_a.index.union(pnl_b.index)).fillna(0.0)
         - pnl_b.reindex(pnl_a.index.union(pnl_b.index)).fillna(0.0)).to_numpy(dtype=float)
    d = d[np.isfinite(d)]
    T = d.size
    if T < 10 or d.std(ddof=1) == 0:
        return {"mean_diff": float(np.nansum(d)), "t_nw": np.nan, "T_eff": np.nan}
    t_eff = lo_effective_T(d, max_lag=max_lag)
    se = d.std(ddof=1) / math.sqrt(max(2.0, t_eff))
    return {
        "mean_diff": float(d.mean()),
        "total_diff": float(d.sum()),
        "t_nw": float(d.mean() / se),
        "T_eff": float(t_eff),
    }


def top_set_clustering_ratio(
    params: pd.DataFrame,
    score: pd.Series,
    *,
    q: float = 0.10,
    draws: int = 2000,
    seed: int = 0,
) -> Dict[str, float]:
    """Is the optimum a PLACE or an ACCIDENT?

    Standardise the parameter columns, take the top ``q`` fraction by ``score``, and compare the
    mean pairwise distance inside that set against the mean pairwise distance of RANDOM subsets
    of the same size.

    READ IT AS: ratio << 1 with a small permutation p -> the good configs sit together, there is
    a genuine basin, and the optimum is a plateau.  Ratio ~ 1 -> the top decile is spatially
    indistinguishable from a random decile, the ranking carries no geometry, and the "best
    config" is a draw from the noise.  This is a far better plateau test than neighbourhood
    degradation at a sparse sample, because it needs no dense grid and no local quadratic.

    FAILURE MODE: inert knobs dilute the distance metric.  Run it a second time restricted to the
    knobs with non-negligible surrogate importance, and report both.  Categorical knobs need a
    declared distance (0/1) and should be reported separately, since one boolean can dominate.
    """
    rng = np.random.default_rng(seed)
    x = params.to_numpy(dtype=float)
    x = (x - x.mean(0)) / np.where(x.std(0) > 0, x.std(0), 1.0)
    n = x.shape[0]
    k = max(3, int(round(q * n)))
    top = np.argsort(-score.to_numpy(dtype=float))[:k]

    def _mpd(idx):
        d = np.linalg.norm(x[idx][:, None, :] - x[idx][None, :, :], axis=-1)
        iu = np.triu_indices(len(idx), 1)
        return float(d[iu].mean())

    obs = _mpd(top)
    null = np.array([_mpd(rng.choice(n, size=k, replace=False)) for _ in range(draws)])
    return {
        "mean_pairwise_dist_top": obs,
        "null_median": float(np.median(null)),
        "clustering_ratio": obs / float(np.median(null)),
        "p_clustered": float((1 + int((null <= obs).sum())) / (draws + 1)),
        "k": k,
    }


def split_rank_stability(
    pnl: pd.DataFrame,
    *,
    n_splits: int = 20,
    block_days: int = 21,
    min_active_days: int = 10,
    seed: int = 0,
) -> pd.DataFrame:
    """Spearman rho between config rankings on two halves of the sample.

    Randomised BLOCK splits, not one contiguous half: a single 2024H2 / 2025 cut confounds
    parameter stability with a regime change, and there is no way to tell the two apart from one
    number.  Blocks of ``block_days`` preserve the holding-period autocorrelation.

    On the sample-size question the user raised: the PRECISION of rho is governed by the number
    of CONFIGS (SE ~ 1/sqrt(M-1), so 200 configs give SE ~ 0.07), while the ATTENUATION of rho is
    governed by the number of TRADES.  With ~17 trades per half the per-config Sharpe SE is ~1.2
    annualised, so rho is attenuated towards zero by the reliability ratio
    var_signal / (var_signal + var_noise) whatever the truth is.  A precisely-measured
    rho = 0.05 therefore proves that any parameter effect is SMALL RELATIVE TO HALF-SAMPLE NOISE
    — it does not prove the effect is zero.  Always report it against
    :func:`rho_noise_ceiling`.

    Configs with fewer than ``min_active_days`` active days in either half are dropped and
    counted, because an undefined Sharpe silently becomes a tie and biases rho.
    """
    rng = np.random.default_rng(seed)
    idx = pnl.index
    n_blocks = max(2, len(idx) // block_days)
    blocks = np.array_split(np.arange(len(idx)), n_blocks)
    rows = []
    for s in range(n_splits):
        perm = rng.permutation(n_blocks)
        a = np.concatenate([blocks[i] for i in perm[: n_blocks // 2]])
        b = np.concatenate([blocks[i] for i in perm[n_blocks // 2:]])
        sa, sb, kept = [], [], []
        for c in pnl.columns:
            va, vb = pnl[c].to_numpy()[a], pnl[c].to_numpy()[b]
            if (np.abs(va) > 0).sum() < min_active_days or (np.abs(vb) > 0).sum() < min_active_days:
                continue
            if va.std(ddof=1) == 0 or vb.std(ddof=1) == 0:
                continue
            sa.append(va.mean() / va.std(ddof=1))
            sb.append(vb.mean() / vb.std(ddof=1))
            kept.append(c)
        if len(kept) < 5:
            rows.append({"split": s, "rho": np.nan, "n_kept": len(kept), "n_dropped": pnl.shape[1] - len(kept)})
            continue
        rho = float(stats.spearmanr(sa, sb).statistic)
        rows.append({"split": s, "rho": rho, "n_kept": len(kept), "n_dropped": pnl.shape[1] - len(kept)})
    return pd.DataFrame(rows)


def rho_noise_ceiling(
    pnl: pd.DataFrame,
    *,
    n_splits: int = 20,
    block_days: int = 21,
    draws: int = 200,
    seed: int = 0,
) -> Dict[str, float]:
    """The rho you would see IF the measured cross-config Sharpe differences were all real.

    Simulates each config as i.i.d. draws with the mean and sd it actually showed in the full
    sample, then runs the identical split machinery.  The resulting distribution is the CEILING:
    no estimator can beat it at this T.  Report rho_observed against rho_ceiling.

    If rho_ceiling is itself near zero — which is the likely outcome at 34 trades — then the
    split-half test cannot distinguish a perfectly stable parameter surface from a random one,
    and the honest conclusion is that the experiment has no power, NOT that the strategy is
    unstable.  That verdict is the point of computing this.
    """
    rng = np.random.default_rng(seed)
    mu = pnl.mean(axis=0).to_numpy(dtype=float)
    sd = pnl.std(axis=0, ddof=1).to_numpy(dtype=float)
    T = pnl.shape[0]
    out = []
    for _ in range(draws):
        sim = pd.DataFrame(rng.standard_normal((T, len(mu))) * sd + mu, index=pnl.index, columns=pnl.columns)
        r = split_rank_stability(sim, n_splits=max(2, n_splits // 4), block_days=block_days,
                                 seed=int(rng.integers(1 << 31)))["rho"]
        out.append(float(np.nanmean(r)))
    a = np.array(out, dtype=float)
    return {"rho_ceiling_mean": float(np.nanmean(a)),
            "rho_ceiling_p05": float(np.nanpercentile(a, 5)),
            "rho_ceiling_p95": float(np.nanpercentile(a, 95))}


def response_surface_tolerance(
    params: pd.DataFrame,
    score: pd.Series,
    *,
    sigma_score: float,
    ridge: float = 1e-6,
    permutation_draws: int = 500,
    seed: int = 0,
) -> Dict[str, object]:
    """Quadratic response surface -> Hessian eigenvalues -> TOLERANCE RADII, and only then kappa.

    Fits ``score ~ b0 + g'x + 0.5 x'Hx`` on range-standardised continuous knobs (declare the
    standardisation: columns are mapped to their sampled range, so a "unit" is the full sweep
    width of that knob and the eigenvalues are comparable).

    The headline output is NOT the condition number.  It is, per eigen-direction,

        r_i = sqrt(2 * sigma_score / |lambda_i|)

    the distance you must travel along that direction before the score moves by one NOISE standard
    deviation.  r_i >= 1 means the whole sampled range of that direction is inside the noise —
    the strategy is INSENSITIVE along it.  r_i << 1 means a small fraction of the sweep width
    already matters — that is a genuine tolerance, and the smallest r_i is the tightest tolerance
    in the parameter space.  This is what "ill-conditioned" should mean operationally, and unlike
    kappa it is dimensioned in something a trader can act on.

    kappa = |lambda_max| / |lambda_min| is reported, with its permutation null, because it was
    asked for.  It is MEANINGFUL only when: (a) the fit sits near an interior optimum (check
    ||g|| small at the centre); (b) the surface is locally smooth; (c) the fit has real
    explanatory power.  It is VOID here for at least three reasons that must be stated whenever
    it is quoted: categorical knobs (wing_objective, cost_legs, require_turning_point) have no
    Hessian and are excluded; the response in entry_zsig_bp is a STEP function because the trade
    count jumps by integers, so its second derivative is a sum of deltas, not a number; and when
    noise dominates, H is effectively a random symmetric matrix whose smallest eigenvalue is near
    zero BY CONSTRUCTION, so kappa is large whatever the truth.  Hence the permutation null:
    quote kappa_observed / kappa_null_median, never kappa against 1.
    """
    rng = np.random.default_rng(seed)
    X = params.to_numpy(dtype=float)
    rngs = X.max(0) - X.min(0)
    rngs = np.where(rngs > 0, rngs, 1.0)
    Z = (X - X.mean(0)) / rngs
    y = score.to_numpy(dtype=float)
    k = Z.shape[1]
    pairs = [(i, j) for i in range(k) for j in range(i, k)]

    def _design(z):
        return np.column_stack([np.ones(len(z)), z] + [z[:, i] * z[:, j] for i, j in pairs])

    A = _design(Z)
    n_coef = A.shape[1]
    if len(y) < n_coef + 5:
        return {"error": f"need > {n_coef + 5} configs to fit a quadratic in {k} knobs; have {len(y)}",
                "n_coef": n_coef}

    def _fit(yy):
        G = A.T @ A + ridge * np.eye(n_coef)
        return np.linalg.solve(G, A.T @ yy)

    def _hessian(beta):
        H = np.zeros((k, k))
        for c, (i, j) in enumerate(pairs):
            b = beta[1 + k + c]
            if i == j:
                H[i, i] = 2.0 * b
            else:
                H[i, j] = H[j, i] = b
        return H

    beta = _fit(y)
    H = _hessian(beta)
    lam = np.linalg.eigvalsh(H)
    absl = np.abs(lam)
    kappa = float(absl.max() / max(absl.min(), 1e-12))

    yhat = A @ beta
    ss = 1.0 - float(((y - yhat) ** 2).sum() / max(1e-12, ((y - y.mean()) ** 2).sum()))

    null = []
    for _ in range(permutation_draws):
        lp = np.abs(np.linalg.eigvalsh(_hessian(_fit(rng.permutation(y)))))
        null.append(lp.max() / max(lp.min(), 1e-12))
    null = np.array(null, dtype=float)

    radii = np.sqrt(2.0 * float(sigma_score) / np.maximum(absl, 1e-12))
    vecs = np.linalg.eigh(H)[1]
    return {
        "r_squared_in_sample": ss,
        "gradient_norm": float(np.linalg.norm(beta[1:1 + k])),
        "eigenvalues": lam,
        "tolerance_radii_in_sweep_widths": radii,
        "tightest_direction": {params.columns[i]: float(v)
                               for i, v in enumerate(vecs[:, int(np.argmax(absl))])},
        "kappa": kappa,
        "kappa_null_median": float(np.median(null)),
        "kappa_vs_null": kappa / float(np.median(null)),
        "p_kappa": float((1 + int((null >= kappa).sum())) / (permutation_draws + 1)),
    }
