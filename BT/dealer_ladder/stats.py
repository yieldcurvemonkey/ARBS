"""Statistics for the dealer-ladder study: day-blocked inference and Romano-Wolf.

Deliberately narrow. What the repo already has is reused, not reimplemented:

- ``BT/signals/deflated_sharpe.py``  — deflated Sharpe / expected max Sharpe under
  the null / DSR gating.
- ``RVUtils/SFRRVLab/stats.py``      — ``nw_tstat`` (Newey-West), ``cost_curve``,
  ``nonoverlapping_sharpe``, ``grid_distribution``, ``deflated_for_grid``,
  ``neighbourhood_stability``, ``verdict``.

What did not exist anywhere and is written here:

- **day-blocked (cluster-by-date) inference.** Intraday observations inside one
  session are not independent: they share the same flow, the same curve vintage
  and the same regime. Clustering by ET calendar date is the coarsest honest unit.
  The only block bootstrap in the repo was eleven hard-coded lines inside
  ``BT/serff/backtest.py``'s summariser; mlfinlab's bootstrap functions are
  ``pass`` stubs that return ``None``.
- **Romano-Wolf stepdown** over a family of variants, resampling whole days so
  cross-contract, cross-horizon and cross-variant correlation is preserved. A
  Bonferroni correction over a heavily correlated grid is badly conservative and
  a per-variant p-value is badly anti-conservative; the stepdown is the honest
  middle and is what the feasibility audit asks for by name.
- **rank information coefficient**, per block and pooled. Grep for
  ``spearman``/``rank_ic`` across BT, RVUtils and SDRUtils returns nothing.

Sign convention throughout: a POSITIVE statistic means the signal predicted the
target in the hypothesised direction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------
def day_codes(when) -> np.ndarray:
    """Integer block id per observation, one block per ET calendar date."""
    ts = pd.to_datetime(pd.Series(list(when)))
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("America/New_York")
    return pd.factorize(ts.dt.date, sort=True)[0]


def _as_blocks(values, blocks):
    v = np.asarray(values, dtype=float)
    b = np.asarray(blocks)
    if v.shape[0] != b.shape[0]:
        raise ValueError(f"values ({v.shape[0]}) and blocks ({b.shape[0]}) differ in length")
    ok = np.isfinite(v)
    return v[ok], b[ok]


def cluster_mean_t(values, blocks) -> dict:
    """Mean with a cluster-robust (by block) standard error and t.

    The cluster estimator is the standard one-way form: with block sums
    ``S_g = sum_{i in g} (x_i - xbar)``, ``Var(xbar) = sum_g S_g^2 / n^2``. It makes
    no assumption of equal block sizes, which matters because sessions differ a
    lot in print count.

    Returns ``{"mean", "se", "t", "n", "n_blocks"}``. ``se``/``t`` are NaN when
    fewer than two blocks survive — one day can never support inference.
    """
    v, b = _as_blocks(values, blocks)
    n = v.size
    if n == 0:
        return {"mean": np.nan, "se": np.nan, "t": np.nan, "n": 0, "n_blocks": 0}
    mean = float(v.mean())
    uniq = np.unique(b)
    if uniq.size < 2:
        return {"mean": mean, "se": np.nan, "t": np.nan, "n": n, "n_blocks": int(uniq.size)}
    dev = v - mean
    sums = np.array([dev[b == g].sum() for g in uniq], dtype=float)
    # small-sample correction, as in one-way clustered OLS
    g = uniq.size
    scale = g / (g - 1.0)
    var = scale * float((sums ** 2).sum()) / (n ** 2)
    se = float(np.sqrt(var)) if var > 0 else np.nan
    t = mean / se if se and np.isfinite(se) and se > 0 else np.nan
    return {"mean": mean, "se": se, "t": float(t) if t == t else np.nan,
            "n": int(n), "n_blocks": int(g)}


def resample_blocks(blocks, rng) -> np.ndarray:
    """Row indices for one day-blocked bootstrap draw (whole days, with replacement)."""
    b = np.asarray(blocks)
    uniq = np.unique(b)
    where = {g: np.flatnonzero(b == g) for g in uniq}
    picked = rng.choice(uniq, size=uniq.size, replace=True)
    return np.concatenate([where[g] for g in picked]) if uniq.size else np.array([], dtype=int)


def day_blocked_ci(values, blocks, *, n_boot=2000, alpha=0.05, seed=0) -> dict:
    """Percentile bootstrap CI for the mean, resampling whole days."""
    v, b = _as_blocks(values, blocks)
    base = cluster_mean_t(v, b)
    if v.size == 0 or np.unique(b).size < 2:
        return {**base, "lo": np.nan, "hi": np.nan, "n_boot": 0}
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = resample_blocks(b, rng)
        draws[i] = v[idx].mean()
    lo, hi = np.quantile(draws, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {**base, "lo": float(lo), "hi": float(hi), "n_boot": int(n_boot)}


# --------------------------------------------------------------------------
# Romano-Wolf stepdown
# --------------------------------------------------------------------------
def romano_wolf(panel: pd.DataFrame, blocks, *, n_boot=2000, seed=0,
                two_sided=True) -> pd.DataFrame:
    """Family-wise adjusted p-values over the columns of ``panel``.

    ``panel`` holds one column per hypothesis (a variant) and one row per
    observation, aligned to ``blocks``. Whole days are resampled jointly across
    ALL columns, so the bootstrap null preserves the correlation between variants
    — which is the entire reason a grid of 200 nearly-identical configurations
    does not get 200 independent shots at significance.

    Method (Romano & Wolf 2005 stepdown):
      1. observed studentised statistic per column, day-clustered;
      2. B day-blocked resamples, each recentred on the observed mean so the
         bootstrap distribution is a null;
      3. order columns by |t| descending; for the leading column the adjusted p is
         the share of resamples whose MAXIMUM |t*| over the still-active set
         reaches the observed |t|; enforce monotonicity down the order.

    Returns a frame indexed by column with ``mean, se, t, n, n_blocks, p_raw,
    p_fwer``, sorted by descending |t|.
    """
    if panel.empty or panel.shape[1] == 0:
        return pd.DataFrame(columns=["mean", "se", "t", "n", "n_blocks",
                                     "p_raw", "p_fwer"])
    b = np.asarray(blocks)
    if b.shape[0] != panel.shape[0]:
        raise ValueError("blocks length must match panel rows")

    cols = list(panel.columns)
    obs = {c: cluster_mean_t(panel[c].to_numpy(dtype=float), b) for c in cols}
    t_obs = np.array([obs[c]["t"] for c in cols], dtype=float)
    means = np.array([obs[c]["mean"] for c in cols], dtype=float)

    rng = np.random.default_rng(seed)
    vals = panel.to_numpy(dtype=float)
    t_star = np.full((n_boot, len(cols)), np.nan, dtype=float)
    for i in range(n_boot):
        idx = resample_blocks(b, rng)
        sub, subb = vals[idx], b[idx]
        for j in range(len(cols)):
            # recentre on the observed mean -> a null distribution
            r = cluster_mean_t(sub[:, j] - means[j], subb)
            t_star[i, j] = r["t"]

    absobs = np.abs(t_obs) if two_sided else t_obs
    absstar = np.abs(t_star) if two_sided else t_star

    p_raw = np.array([
        np.nanmean(absstar[:, j] >= absobs[j]) if np.isfinite(absobs[j]) else np.nan
        for j in range(len(cols))
    ])

    order = np.argsort(-np.nan_to_num(absobs, nan=-np.inf))
    p_fwer = np.full(len(cols), np.nan, dtype=float)
    active = list(order)
    running = 0.0
    for pos, j in enumerate(order):
        if not np.isfinite(absobs[j]):
            continue
        block = absstar[:, active]
        # An all-NaN bootstrap row means every active hypothesis was unidentified in
        # that resample (e.g. a draw with a single block). Treat it as "no evidence"
        # instead of letting nanmax warn and return NaN.
        if block.size:
            usable = np.isfinite(block).any(axis=1)
            maxes = np.full(block.shape[0], np.nan)
            if usable.any():
                maxes[usable] = np.nanmax(block[usable], axis=1)
        else:
            maxes = np.array([np.nan])
        p = float(np.nanmean(maxes >= absobs[j])) if np.isfinite(maxes).any() else np.nan
        running = max(running, p)          # monotone non-decreasing down the order
        p_fwer[j] = running
        active = active[1:]                 # drop the leading hypothesis

    out = pd.DataFrame({
        "mean": means,
        "se": [obs[c]["se"] for c in cols],
        "t": t_obs,
        "n": [obs[c]["n"] for c in cols],
        "n_blocks": [obs[c]["n_blocks"] for c in cols],
        "p_raw": p_raw,
        "p_fwer": p_fwer,
    }, index=cols)
    return out.reindex(out["t"].abs().sort_values(ascending=False).index)


# --------------------------------------------------------------------------
# information coefficient
# --------------------------------------------------------------------------
def rank_ic(signal, target) -> float:
    """Spearman rank correlation, NaN-safe. Returns NaN below 3 usable pairs."""
    s = pd.Series(np.asarray(signal, dtype=float))
    y = pd.Series(np.asarray(target, dtype=float))
    ok = s.notna() & y.notna()
    if ok.sum() < 3:
        return np.nan
    s, y = s[ok], y[ok]
    if s.nunique() < 2 or y.nunique() < 2:
        return np.nan
    return float(s.rank().corr(y.rank()))


def ic_by_block(signal, target, blocks) -> pd.Series:
    """Rank IC computed WITHIN each block, indexed by block id.

    Per-block ICs are the natural unit for day-blocked inference on an IC: pooling
    across days would let a cross-sectional level difference between days
    masquerade as predictive power.
    """
    df = pd.DataFrame({"s": np.asarray(signal, dtype=float),
                       "y": np.asarray(target, dtype=float),
                       "b": np.asarray(blocks)})
    return df.groupby("b").apply(
        lambda g: rank_ic(g["s"], g["y"]), include_groups=False)


# --------------------------------------------------------------------------
# reporting helpers
# --------------------------------------------------------------------------
def stars(t) -> str:
    """|t| stars: *** >= 3, ** >= 2.58, * >= 1.96, . >= 1.64, else blank.

    3 sigma leads because the pre-registered primary gate is raw t >= 3.
    """
    if t is None or not np.isfinite(t):
        return ""
    a = abs(float(t))
    if a >= 3.0:
        return "***"
    if a >= 2.58:
        return "**"
    if a >= 1.96:
        return "*"
    if a >= 1.64:
        return "."
    return ""


def sign_consistency(values, blocks) -> dict:
    """Share of blocks whose mean carries the pooled sign, plus a sign test.

    A pooled mean driven by one enormous session is not an effect. The binomial
    sign test over blocks is deliberately crude and hard to fake.
    """
    v, b = _as_blocks(values, blocks)
    if v.size == 0:
        return {"pooled_mean": np.nan, "share_agreeing": np.nan, "n_blocks": 0,
                "p_sign": np.nan}
    pooled = float(v.mean())
    uniq = np.unique(b)
    if pooled == 0.0:
        # no pooled sign to agree WITH: agreement is undefined, not zero
        return {"pooled_mean": 0.0, "share_agreeing": np.nan,
                "n_blocks": int(uniq.size), "p_sign": np.nan}
    block_means = np.array([v[b == g].mean() for g in uniq], dtype=float)
    nz = block_means[block_means != 0.0]
    agree = int((np.sign(nz) == np.sign(pooled)).sum())
    n = nz.size
    p = np.nan
    if n:
        from math import comb
        # two-sided exact binomial at p=0.5
        tail = sum(comb(n, k) for k in range(agree, n + 1)) / (2.0 ** n)
        p = float(min(1.0, 2.0 * tail))
    return {"pooled_mean": pooled, "share_agreeing": (agree / n) if n else np.nan,
            "n_blocks": int(uniq.size), "p_sign": p}


def attenuate(net_bp, accuracy) -> float:
    """Scale a signed result by the classification-attenuation factor ``2a - 1``.

    With independent sign accuracy ``a`` the signed exposure retains ``2a-1``:
    0.6 -> 20%, 0.7 -> 40%, 0.8 -> 60%. Direction here is UNCERTIFIED against
    truth labels, so every headline number is reported across a grid of ``a``.
    """
    return float(net_bp) * (2.0 * float(accuracy) - 1.0)
