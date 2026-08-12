"""
R0 — lead-lag regression of signed futures aggressor volume on signed customer swap DV01.

ONE specification, run ONCE, exactly as pre-registered in r0_prereg.md. Runner choices
that the prereg left open were frozen in r0_deviations.md (section "R0 — runner choices,
FROZEN BEFORE ESTIMATION") before this file was written.

    Y_{b,t} = alpha_b + sum_{k=-30}^{+30} beta_k * X_{b,t-k}
              + bin-of-day FE + 5 lags of Y + eps

k > 0  <=>  X precedes Y  (post-print futures flow; the hedge channel).
Pre-registered sign: positive X predicts NEGATIVE Y, so the hedge channel is beta_k < 0.

Inference: standard errors clustered by CME session date (governs), plus Newey-West
with a 60-bin Bartlett bandwidth (reported alongside).

Usage:  python run_r0.py            # selftest, then the single real run
        python run_r0.py --selftest # selftest only

No import of SDRUtils.dealer_direction or SDRUtils.stir_flow. Matplotlib only.
"""

from __future__ import annotations

import os
import sys
import time
import textwrap

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import scipy.sparse as sp
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")

# ---------------------------------------------------------------------------
# Frozen constants (r0_prereg.md + r0_deviations.md section R*)
# ---------------------------------------------------------------------------
KMIN, KMAX = -30, 30          # prereg
N_YLAGS = 5                   # prereg
NW_BANDWIDTH = 60             # prereg
TSTAT_CRIT = 1.96             # prereg
DECISION_BUCKETS = ["SFR_FF", "TU", "FV", "TY_UXY", "US"]   # prereg bucket map; WN excluded
ROLL_WIN = 1440               # R4
ROLL_MINP = 240               # R4
EDGE = max(abs(KMIN), abs(KMAX))   # R7: drop first/last 30 bins of each session

LAGS = list(range(KMIN, KMAX + 1))
XCOLS = [f"x{k:+d}" for k in LAGS]
YCOLS = [f"ylag{j}" for j in range(1, N_YLAGS + 1)]
REGCOLS = XCOLS + YCOLS
IPOS = [REGCOLS.index(f"x{k:+d}") for k in LAGS if k >= 1]
INEG = [REGCOLS.index(f"x{k:+d}") for k in LAGS if k <= -1]

_LOG_LINES: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _LOG_LINES.append(msg)


# ---------------------------------------------------------------------------
# Fixed-effect absorption (R6)
# ---------------------------------------------------------------------------
class FEAbsorber:
    """Exact within-transformation for one or two additive factors."""

    def __init__(self, codes_list: list[np.ndarray]):
        self.codes = codes_list
        self.n = len(codes_list[0])
        if len(codes_list) == 1:
            g = codes_list[0]
            self.counts = np.bincount(g).astype(float)
            self.k_fe = int(self.counts.size)
            self.mode = "oneway"
        else:
            blocks, off = [], 0
            for g in codes_list:
                ng = int(g.max()) + 1
                blocks.append(sp.csr_matrix(
                    (np.ones(self.n), (np.arange(self.n), g)), shape=(self.n, ng)))
                off += ng
            self.D = sp.hstack(blocks).tocsr()
            DtD = (self.D.T @ self.D).toarray()
            self.P = np.linalg.pinv(DtD, rcond=1e-10)
            self.k_fe = off - (len(codes_list) - 1)   # one collinearity per extra factor
            self.mode = "twoway"

    def absorb(self, M: np.ndarray) -> np.ndarray:
        M = np.asarray(M, dtype=float)
        one_d = M.ndim == 1
        if one_d:
            M = M[:, None]
        if self.mode == "oneway":
            g = self.codes[0]
            sums = np.zeros((self.counts.size, M.shape[1]))
            for j in range(M.shape[1]):
                sums[:, j] = np.bincount(g, weights=M[:, j], minlength=self.counts.size)
            R = M - (sums / self.counts[:, None])[g]
        else:
            alpha = self.P @ (self.D.T @ M)
            R = M - self.D @ alpha
        return R[:, 0] if one_d else R


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------
def ols_with_ses(Zy: np.ndarray, ZX: np.ndarray, cluster: np.ndarray,
                 block: np.ndarray, k_fe: int, nw_bw: int = NW_BANDWIDTH,
                 do_nw: bool = True) -> dict:
    """OLS on FE-absorbed data; cluster-robust and Newey-West (Bartlett) covariances.

    cluster : cluster id per row (CME session date code)
    block   : block id per row for the NW kernel (bucket code); rows must be
              contiguous per block and time-ordered inside it.
    """
    n, k = ZX.shape
    XtX = ZX.T @ ZX
    bread = np.linalg.pinv(XtX, rcond=1e-12)
    beta = bread @ (ZX.T @ Zy)
    e = Zy - ZX @ beta
    kk = k + k_fe

    # --- cluster-robust by day -------------------------------------------------
    U = ZX * e[:, None]
    order = np.argsort(cluster, kind="stable")
    cs = cluster[order]
    bounds = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1], True])
    Us = U[order]
    G = len(bounds) - 1
    agg = np.add.reduceat(Us, bounds[:-1], axis=0)          # G x k
    meat_cl = agg.T @ agg
    c_cl = (G / max(G - 1, 1)) * ((n - 1) / max(n - kk, 1))
    V_cl = bread @ meat_cl @ bread * c_cl

    # --- Newey-West, Bartlett, bandwidth nw_bw, within block -------------------
    if do_nw:
        S = U.T @ U
        b_bounds = np.flatnonzero(np.r_[True, block[1:] != block[:-1], True])
        for l in range(1, nw_bw + 1):
            w = 1.0 - l / (nw_bw + 1.0)
            Gl = np.zeros((k, k))
            for bi in range(len(b_bounds) - 1):
                s, t = b_bounds[bi], b_bounds[bi + 1]
                if t - s <= l:
                    continue
                Ub = U[s:t]
                Gl += Ub[l:].T @ Ub[:-l]
            S += w * (Gl + Gl.T)
        V_nw = bread @ S @ bread * (n / max(n - kk, 1))
    else:
        V_nw = np.full((k, k), np.nan)

    return dict(beta=beta, V_cl=V_cl, V_nw=V_nw, n=n, k=k, k_fe=k_fe, G=G,
                resid_var=float(e @ e / max(n - kk, 1)))


def lincomb(res: dict, idx: list[int]) -> dict:
    c = np.zeros(res["beta"].size)
    c[idx] = 1.0
    v = float(c @ res["beta"])
    se_cl = float(np.sqrt(max(c @ res["V_cl"] @ c, 0.0)))
    se_nw = float(np.sqrt(max(c @ res["V_nw"] @ c, 0.0)))
    return dict(val=v, se_cl=se_cl, t_cl=v / se_cl if se_cl > 0 else np.nan,
                se_nw=se_nw, t_nw=v / se_nw if se_nw > 0 else np.nan)


def diffcomb(res: dict) -> dict:
    """(sum k>=1) - (sum k<=-1)."""
    c = np.zeros(res["beta"].size)
    c[IPOS] = 1.0
    c[INEG] = -1.0
    v = float(c @ res["beta"])
    se_cl = float(np.sqrt(max(c @ res["V_cl"] @ c, 0.0)))
    se_nw = float(np.sqrt(max(c @ res["V_nw"] @ c, 0.0)))
    return dict(val=v, se_cl=se_cl, t_cl=v / se_cl if se_cl > 0 else np.nan,
                se_nw=se_nw, t_nw=v / se_nw if se_nw > 0 else np.nan)


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------
def rolling_scale(v: np.ndarray, bucket_code: np.ndarray) -> np.ndarray:
    """R4: strictly-trailing rolling std, window ROLL_WIN, min_periods ROLL_MINP,
    per bucket; fallback to that bucket's full-sample std."""
    s = pd.Series(v)
    out = np.empty_like(v, dtype=float)
    for b in np.unique(bucket_code):
        m = bucket_code == b
        sb = s[m]
        r = sb.rolling(ROLL_WIN, min_periods=ROLL_MINP).std().shift(1)
        full = float(sb.std(ddof=1))
        if not np.isfinite(full) or full == 0:
            full = 1.0
        r = r.fillna(full)
        r = r.where(np.isfinite(r) & (r > 0), full)
        out[m] = r.to_numpy()
    return out


def shift_global(a: np.ndarray, k: int) -> np.ndarray:
    """column for lag k: out[i] = a[i-k]  (R1)."""
    out = np.full(a.shape, np.nan)
    if k > 0:
        out[k:] = a[:-k]
    elif k < 0:
        out[:k] = a[-k:]
    else:
        out[:] = a
    return out


def build_grid(y: pd.DataFrame, authoritative_sessions: bool = True) -> pd.DataFrame:
    """Y's dense grid, sorted (bucket, minute), with session id and within-session pos."""
    g = y[y["bucket"].isin(DECISION_BUCKETS)].copy()
    g = g.sort_values(["bucket", "minute_utc"], kind="stable").reset_index(drop=True)
    step = g.groupby("bucket")["minute_utc"].diff().dt.total_seconds()
    new_sess = (step != 60) | step.isna()
    g["sess_idx"] = new_sess.groupby(g["bucket"]).cumsum().astype(int)
    g["sess_key"] = g["bucket"] + "|" + g["sess_idx"].astype(str)
    g["pos"] = g.groupby("sess_key").cumcount()
    g["slen"] = g.groupby("sess_key")["pos"].transform("size")
    # CME session (trade) date: taken from data/y_sessions.csv, which is authoritative.
    # A derived "date of the session's last minute" rule is WRONG for the evening-only
    # 2026-08-07 sessions, whose last minute falls on 2026-08-06 — it merges them into
    # the previous day's cluster. Joined on (bucket, first minute of session).
    if authoritative_sessions:
        ys = pd.read_csv(os.path.join(DATA, "y_sessions.csv"))
        ys["first_minute"] = pd.to_datetime(ys["first_minute"], utc=True)
        first_min = g.groupby("sess_key")["minute_utc"].transform("min")
        key = pd.DataFrame({"bucket": g["bucket"].to_numpy(), "first_minute": first_min.to_numpy()})
        g["session_date"] = key.merge(
            ys[["bucket", "first_minute", "session_date"]],
            on=["bucket", "first_minute"], how="left")["session_date"].to_numpy()
        if g["session_date"].isna().any():
            raise RuntimeError(
                f"{int(g['session_date'].isna().sum())} grid rows could not be matched to a "
                "session in data/y_sessions.csv")
    else:   # synthetic panels only: sessions are full by construction
        last_min = g.groupby("sess_key")["minute_utc"].transform("max")
        g["session_date"] = last_min.dt.tz_convert("America/Chicago").dt.date.astype(str)
    g["bin_of_day"] = g["minute_utc"].dt.hour * 60 + g["minute_utc"].dt.minute
    g["keep"] = (g["pos"] >= EDGE) & (g["pos"] <= g["slen"] - 1 - EDGE)
    return g


def make_design(grid: pd.DataFrame, xser: np.ndarray) -> tuple:
    """Standardise, build the 61 X lags + 5 Y lags, apply the keep mask."""
    bcode = pd.factorize(grid["bucket"])[0]
    ystd = grid["signed_volume"].to_numpy(float) / rolling_scale(
        grid["signed_volume"].to_numpy(float), bcode)
    xstd = xser / rolling_scale(xser, bcode)

    cols = [shift_global(xstd, k) for k in LAGS]
    cols += [shift_global(ystd, j) for j in range(1, N_YLAGS + 1)]
    M = np.column_stack(cols)
    keep = grid["keep"].to_numpy()
    keep = keep & np.isfinite(M).all(axis=1) & np.isfinite(ystd)
    return ystd[keep], M[keep], keep


def run_one(grid: pd.DataFrame, xser: np.ndarray, scope: str, do_nw: bool = True) -> dict:
    yv, M, keep = make_design(grid, xser)
    sub = grid.loc[keep]
    cl = pd.factorize(sub["session_date"])[0]
    bcode = pd.factorize(sub["bucket"])[0]
    bod = pd.factorize(sub["bin_of_day"])[0]
    if scope == "pooled":
        fe = FEAbsorber([bcode, bod])
    else:
        fe = FEAbsorber([bod])
    Zy = fe.absorb(yv)
    ZX = fe.absorb(M)
    res = ols_with_ses(Zy, ZX, cl, bcode, fe.k_fe, do_nw=do_nw)
    res["n_days"] = int(pd.Series(sub["session_date"]).nunique())
    res["n_bins"] = int(len(sub))
    return res


# ---------------------------------------------------------------------------
# SELFTEST — known beta profile, known sign, known lag (run BEFORE the real data)
# ---------------------------------------------------------------------------
def _synth_fit(true_k, true_b, seed, n_sess=40, n_bins=700):
    """Synthetic panel with the SAME shape as the real one, and a KNOWN beta profile."""
    rng = np.random.default_rng(seed)
    rows = []
    t0 = pd.Timestamp("2026-01-05 00:00", tz="UTC")
    for b in DECISION_BUCKETS[:3]:                       # real bucket labels, 3 of them
        for s in range(n_sess):
            start = t0 + pd.Timedelta(days=s)
            mins = start + pd.to_timedelta(np.arange(n_bins), unit="m")
            rows.append(pd.DataFrame({"bucket": b, "minute_utc": mins}))
    g = pd.concat(rows, ignore_index=True)
    g["signed_volume"] = 0.0
    g["gross_volume"] = 0
    g["n_trades"] = 0
    grid = build_grid(g, authoritative_sessions=False)   # sorts + sessionises
    n = len(grid)
    # X is generated ON the grid's own row order, so no realignment is possible
    x = rng.standard_normal(n) * rng.choice([0.0, 1.0], size=n, p=[0.4, 0.6])
    bod_eff = np.sin(2 * np.pi * grid["bin_of_day"].to_numpy() / 1440.0) * 0.8
    b_eff = pd.factorize(grid["bucket"])[0] * 0.5
    y = np.zeros(n)
    e = rng.standard_normal(n)
    sess = grid["sess_key"].to_numpy()
    for i in range(n):
        ar = 0.30 * y[i - 1] if i > 0 and sess[i - 1] == sess[i] else 0.0
        j = i - true_k
        xk = x[j] if (0 <= j < n and sess[j] == sess[i] and true_b != 0.0) else 0.0
        y[i] = bod_eff[i] + b_eff[i] + ar + true_b * xk + e[i]
    grid = grid.copy()
    grid["signed_volume"] = y
    # The prereg standardises BOTH series, so the estimand is not `true_b` but
    # `true_b * scale_X / scale_Y`. Predicted here, a priori, from the scales the
    # estimator will itself use — the estimate is then checked against that prediction.
    bcode = pd.factorize(grid["bucket"])[0]
    expected = true_b * float(np.mean(rolling_scale(x, bcode))) / \
        float(np.mean(rolling_scale(y, bcode)))
    return run_one(grid, x, "pooled", do_nw=True), expected, x


def selftest() -> bool:
    log("=" * 96)
    log("SELFTEST — estimator validated on synthetic data with a KNOWN beta profile")
    log("=" * 96)
    ok = True

    RTOL = 0.05    # relative tolerance on the a-priori predicted standardised beta

    # (1) known effect at k = +3, pre-registered NEGATIVE sign
    r, exp1, _ = _synth_fit(true_k=+3, true_b=-0.30, seed=11)
    b = r["beta"]
    se = np.sqrt(np.diag(r["V_cl"]))
    i3, im3 = REGCOLS.index("x+3"), REGCOLS.index("x-3")
    log(f"  (1) DGP  Y_t = -0.30*X_(t-3) + 0.30*Y_(t-1) + bin-of-day + bucket + eps")
    log(f"      predicted standardised beta at k=+3 = {exp1:+.4f} "
        f"(= -0.30 * scale_X / scale_Y, computed a priori)")
    log(f"      beta(k=+3) = {b[i3]:+.4f}   t_cl = {b[i3]/se[i3]:+8.2f}    "
        f"rel err vs prediction = {b[i3]/exp1 - 1:+.3%}")
    log(f"      beta(k=-3) = {b[im3]:+.4f}  (true 0)  t_cl = {b[im3]/se[im3]:+8.2f}")
    log(f"      max |beta| over all k != +3 : {np.abs(np.delete(b[:61], i3)).max():.4f}")
    c1 = abs(b[i3] / exp1 - 1) < RTOL
    c2 = b[i3] / se[i3] < -5
    c3 = abs(np.delete(b[:61], i3)).max() < 0.05
    c4 = abs(b[im3]) < 0.02
    log(f"      magnitude recovered [{c1}], significant NEGATIVE [{c2}], "
        f"nothing elsewhere [{c3}], nothing at -3 [{c4}]")
    sp_ = lincomb(r, IPOS); sn_ = lincomb(r, INEG)
    log(f"      sum(k>=1) = {sp_['val']:+.4f} (t {sp_['t_cl']:+.2f}) | "
        f"sum(k<=-1) = {sn_['val']:+.4f} (t {sn_['t_cl']:+.2f})  -> "
        f"post-print mass, as injected")
    ok &= c1 and c2 and c3 and c4 and sp_["t_cl"] < -5

    # (2) mirror: known effect at k = -3 must NOT show up at +3
    r2, exp2, _ = _synth_fit(true_k=-3, true_b=-0.30, seed=12)
    b2 = r2["beta"]
    se2 = np.sqrt(np.diag(r2["V_cl"]))
    log(f"  (2) DGP  Y_t = -0.30*X_(t+3) ...   (mass deliberately PRE-print); "
        f"predicted {exp2:+.4f} at k=-3")
    log(f"      beta(k=-3) = {b2[im3]:+.4f}  t_cl = {b2[im3]/se2[im3]:+8.2f}   "
        f"beta(k=+3) = {b2[i3]:+.4f}  t_cl = {b2[i3]/se2[i3]:+8.2f}")
    c5 = abs(b2[im3] / exp2 - 1) < RTOL and abs(b2[i3]) < 0.02
    sp2 = lincomb(r2, IPOS); sn2 = lincomb(r2, INEG)
    log(f"      sum(k>=1) = {sp2['val']:+.4f} (t {sp2['t_cl']:+.2f}) | "
        f"sum(k<=-1) = {sn2['val']:+.4f} (t {sn2['t_cl']:+.2f})  -> "
        f"lag orientation is NOT transposed [{c5}]")
    ok &= c5 and sn2["t_cl"] < -5 and abs(sp2["t_cl"]) < 3

    # (3) null DGP must not manufacture significance
    r3, _, _ = _synth_fit(true_k=+3, true_b=0.0, seed=13)
    sp3 = lincomb(r3, IPOS); sn3 = lincomb(r3, INEG)
    log(f"  (3) NULL DGP: sum(k>=1) = {sp3['val']:+.4f} (t_cl {sp3['t_cl']:+.2f}, "
        f"t_nw {sp3['t_nw']:+.2f}) | sum(k<=-1) = {sn3['val']:+.4f} "
        f"(t_cl {sn3['t_cl']:+.2f})")
    c6 = abs(sp3["t_cl"]) < TSTAT_CRIT and abs(sn3["t_cl"]) < TSTAT_CRIT
    log(f"      no false significance [{c6}]")
    ok &= c6

    # (4) FE absorption vs explicit dummies, on a subsample
    rng = np.random.default_rng(7)
    n = 4000
    bc = rng.integers(0, 4, n); bd = rng.integers(0, 25, n)
    Xs = rng.standard_normal((n, 6))
    ys = Xs @ np.array([1, -2, 0.5, 0, 0.3, -0.7]) + bc * 0.9 + np.sin(bd) * 1.3 + rng.standard_normal(n)
    fe = FEAbsorber([bc, bd])
    bhat_fwl = np.linalg.lstsq(fe.absorb(Xs), fe.absorb(ys), rcond=None)[0]
    Dfull = np.column_stack([Xs,
                             np.eye(4)[bc][:, 1:], np.eye(25)[bd][:, 1:], np.ones(n)])
    bhat_full = np.linalg.lstsq(Dfull, ys, rcond=None)[0][:6]
    dmax = float(np.abs(bhat_fwl - bhat_full).max())
    c7 = dmax < 1e-9
    log(f"  (4) two-way FE absorption vs explicit dummies: max |diff| = {dmax:.2e} [{c7}]")
    ok &= c7

    # (5) cluster-robust SE vs statsmodels
    try:
        import statsmodels.api as sm
        cl = rng.integers(0, 30, n)
        Zx = fe.absorb(Xs); Zy = fe.absorb(ys)
        mine = ols_with_ses(Zy, Zx, cl, np.zeros(n, int), 0, nw_bw=3)
        sm_res = sm.OLS(Zy, Zx).fit(cov_type="cluster",
                                    cov_kwds={"groups": cl, "use_correction": True})
        rel = float(np.abs(np.sqrt(np.diag(mine["V_cl"])) / sm_res.bse - 1).max())
        c8 = rel < 1e-8
        log(f"  (5) day-clustered SE vs statsmodels cov_type='cluster': "
            f"max rel diff = {rel:.2e} [{c8}]")
        ok &= c8
        sm_nw = sm.OLS(Zy, Zx).fit(cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": False})
        mine_nw = np.sqrt(np.diag(mine["V_nw"]))
        rel2 = float(np.abs(mine_nw / sm_nw.bse - 1).max())
        log(f"      Newey-West(3) vs statsmodels HAC: max rel diff = {rel2:.2e} "
            f"[{rel2 < 1e-3}]  (small-sample factor differs by design)")
    except Exception as exc:                                    # pragma: no cover
        log(f"  (5) statsmodels cross-check unavailable: {exc}")

    log(f"  SELFTEST {'PASSED' if ok else 'FAILED'}")
    log("")
    return ok


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------
def x_series(xdf: pd.DataFrame, grid: pd.DataFrame, clock: str, split: str) -> np.ndarray:
    d = xdf[xdf["clock"] == clock]
    if split == "block":
        d = d[d["is_block"]]
    elif split == "nonblock":
        d = d[~d["is_block"]]
    elif split == "D2C":
        d = d[d["venue_class"] == "D2C"]
    elif split == "IDB":
        d = d[d["venue_class"] == "IDB"]
    agg = d.groupby(["bucket", "minute_utc"], as_index=False)["signed_dv01"].sum()
    key = pd.MultiIndex.from_frame(grid[["bucket", "minute_utc"]])
    s = agg.set_index(["bucket", "minute_utc"])["signed_dv01"].reindex(key).fillna(0.0)
    return s.to_numpy(float)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    t_start = time.time()

    if not selftest():
        log("SELFTEST FAILED — refusing to run on real data.")
        return 2
    if "--selftest" in sys.argv:
        return 0

    # ---- load & verify ----------------------------------------------------
    y = pd.read_parquet(os.path.join(DATA, "y_signed_volume.parquet"))
    x = pd.read_parquet(os.path.join(DATA, "x_signed_dv01.parquet"))
    grid = build_grid(y)

    # known-answer check on the session reconstruction
    ysess = pd.read_csv(os.path.join(DATA, "y_sessions.csv"))
    ysess = ysess[ysess["bucket"].isin(DECISION_BUCKETS)]
    mine = grid.groupby("bucket")["sess_key"].nunique()
    theirs = ysess.groupby("bucket").size()
    sess_ok = bool((mine.sort_index() == theirs.sort_index()).all())
    my_dates = set(zip(grid["bucket"], grid["session_date"]))
    their_dates = set(zip(ysess["bucket"], ysess["session_date"]))
    dates_ok = my_dates == their_dates

    log("=" * 96)
    log("R0 — lead-lag regression.  ONE specification, run ONCE.")
    log("=" * 96)
    log(f"session reconstruction vs data/y_sessions.csv: counts match [{sess_ok}], "
        f"session dates match [{dates_ok}]")
    if not (sess_ok and dates_ok):
        log(f"  mine:   {dict(mine)}")
        log(f"  theirs: {dict(theirs)}")
        log(f"  date-set symmetric difference: {len(my_dates ^ their_dates)}")
        log("  SESSION RECONSTRUCTION CHECK FAILED — refusing to run. The cluster unit is "
            "the CME session date; a wrong label silently merges clusters.")
        return 4

    n_days_tot = grid.loc[grid["keep"], "session_date"].nunique()
    n_bins_tot = int(grid["keep"].sum())
    log("")
    log(f"N_days = {n_days_tot}   (distinct CME session dates in the estimation sample)")
    log(f"N_bins = {n_bins_tot:,}  (bucket-minute observations entering the regression, "
        f"of {len(grid):,} on Y's grid; {len(grid) - n_bins_tot:,} dropped as session edges)")
    log("")
    log("per bucket:")
    ksub = grid[grid["keep"]]
    for b in DECISION_BUCKETS:
        gb = ksub[ksub["bucket"] == b]
        ab = grid[grid["bucket"] == b]
        log(f"  {b:8s} N_days = {gb['session_date'].nunique():3d}   N_bins = {len(gb):7,}"
            f"   (grid {len(ab):7,})   {ab['minute_utc'].min()} .. {ab['minute_utc'].max()}")
    log("")

    # X coverage on Y's grid, both clocks
    log("X mass landing on Y's grid (the rest is outside Y's sessions / outside Y's days):")
    for clock in ["exec", "diss"]:
        xc = x[x["clock"] == clock]
        tot = xc["gross_dv01"].sum()
        key = set(zip(grid["bucket"], grid["minute_utc"]))
        onk = xc[[(b, m) in key for b, m in zip(xc["bucket"], xc["minute_utc"])]]
        log(f"  {clock}: gross DV01 on grid {onk['gross_dv01'].sum()/1e6:10,.0f} / "
            f"{tot/1e6:10,.0f} $mm/bp = {onk['gross_dv01'].sum()/tot:6.1%}   "
            f"prints {onk['n_prints'].sum():,} / {xc['n_prints'].sum():,}")
        for b in DECISION_BUCKETS:
            t2 = xc[xc['bucket'] == b]['gross_dv01'].sum()
            o2 = onk[onk['bucket'] == b]['gross_dv01'].sum()
            log(f"      {b:8s} {o2/max(t2,1):6.1%}")
    log("")

    # ---- plumbing check on the REAL grid and the REAL X --------------------
    # Same code path as the run below, but Y is replaced by a synthetic series
    # carrying a known effect at k = +7. This tests the real sessions, the real
    # sparse-X reindex and the real keep mask, not just a synthetic panel.
    xs_diss = x_series(x, grid, "diss", "all")
    bcode_all = pd.factorize(grid["bucket"])[0]
    xstd_all = xs_diss / rolling_scale(xs_diss, bcode_all)
    rng = np.random.default_rng(2026)
    yfake = -0.25 * shift_global(xstd_all, 7) + rng.standard_normal(len(grid))
    yfake[~np.isfinite(yfake)] = 0.0
    gfake = grid.copy()
    gfake["signed_volume"] = yfake
    rp = run_one(gfake, xs_diss, "pooled", do_nw=False)
    i7 = REGCOLS.index("x+7")
    im7 = REGCOLS.index("x-7")
    sep = np.sqrt(np.diag(rp["V_cl"]))
    exp7 = -0.25 / float(np.mean(rolling_scale(yfake, bcode_all)))
    log("plumbing check on the REAL grid / REAL X (Y replaced by -0.25*Xstd_(t-7) + noise):")
    log(f"  beta(k=+7) = {rp['beta'][i7]:+.4f}  predicted {exp7:+.4f}  "
        f"t_cl = {rp['beta'][i7]/sep[i7]:+.2f}")
    log(f"  beta(k=-7) = {rp['beta'][im7]:+.4f}   max|beta| over k != +7 = "
        f"{np.abs(np.delete(rp['beta'][:61], i7)).max():.4f}")
    plumb_ok = (abs(rp["beta"][i7] / exp7 - 1) < 0.10
                and abs(rp["beta"][im7]) < 0.03
                and rp["beta"][i7] / sep[i7] < -5)
    log(f"  real-path lag orientation and sign verified [{plumb_ok}]")
    if not plumb_ok:
        log("  PLUMBING CHECK FAILED — refusing to report a verdict.")
        return 3
    log("")

    # ---- the run ----------------------------------------------------------
    scopes = [("pooled", None)] + [("bucket", b) for b in DECISION_BUCKETS]
    splits = ["all", "block", "nonblock", "D2C", "IDB"]
    rows, betas_rows = [], []
    store = {}

    for clock in ["exec", "diss"]:
        for split in splits:
            xs_full = x_series(x, grid, clock, split)
            for scope, b in scopes:
                if scope == "pooled":
                    g2, xs2 = grid, xs_full
                else:
                    m = (grid["bucket"] == b).to_numpy()
                    g2, xs2 = grid[m].reset_index(drop=True), xs_full[m]
                if np.all(xs2 == 0):
                    continue
                # R8/NW is a secondary report; computed for the headline all-flow runs
                r = run_one(g2, xs2, scope, do_nw=(split == "all"))
                sp_ = lincomb(r, IPOS)
                sn_ = lincomb(r, INEG)
                df_ = diffcomb(r)
                b0 = r["beta"][REGCOLS.index("x+0")]
                se0 = float(np.sqrt(r["V_cl"][REGCOLS.index("x+0"), REGCOLS.index("x+0")]))
                bb = r["beta"][:61]
                mass = np.abs(bb).sum()
                centroid = float((np.array(LAGS) * np.abs(bb)).sum() / mass) if mass > 0 else np.nan
                rows.append(dict(
                    clock=clock, split=split, scope=scope, bucket=(b or "POOLED"),
                    n_obs=r["n"], n_days=r["n_days"], n_clusters=r["G"],
                    sum_beta_kneg=sn_["val"], se_cluster_kneg=sn_["se_cl"], t_cluster_kneg=sn_["t_cl"],
                    se_nw_kneg=sn_["se_nw"], t_nw_kneg=sn_["t_nw"],
                    sum_beta_kpos=sp_["val"], se_cluster_kpos=sp_["se_cl"], t_cluster_kpos=sp_["t_cl"],
                    se_nw_kpos=sp_["se_nw"], t_nw_kpos=sp_["t_nw"],
                    diff_pos_minus_neg=df_["val"], se_cluster_diff=df_["se_cl"],
                    t_cluster_diff=df_["t_cl"], se_nw_diff=df_["se_nw"], t_nw_diff=df_["t_nw"],
                    beta_k0=float(b0), se_cluster_k0=se0,
                    t_cluster_k0=float(b0 / se0) if se0 > 0 else np.nan,
                    abs_ratio_pos_over_neg=(abs(sp_["val"]) / abs(sn_["val"])
                                            if sn_["val"] != 0 else np.nan),
                    post_print_share=(abs(sp_["val"]) / (abs(sp_["val"]) + abs(sn_["val"]))
                                      if (abs(sp_["val"]) + abs(sn_["val"])) > 0 else np.nan),
                    centroid_absbeta_D2=centroid,
                ))
                if split == "all":
                    store[(clock, b or "POOLED")] = r
                    secl = np.sqrt(np.diag(r["V_cl"]))
                    for i, kk in enumerate(LAGS):
                        betas_rows.append(dict(clock=clock, bucket=(b or "POOLED"), k=kk,
                                               beta=float(r["beta"][i]),
                                               se_cluster=float(secl[i]),
                                               se_nw=float(np.sqrt(r["V_nw"][i, i]))))
                log(f"  fitted {clock:4s} {split:8s} {(b or 'POOLED'):8s} "
                    f"n={r['n']:7,} G={r['G']:3d}  "
                    f"S_neg={sn_['val']:+7.4f} (t {sn_['t_cl']:+6.2f})  "
                    f"S_pos={sp_['val']:+7.4f} (t {sp_['t_cl']:+6.2f})")

    tab = pd.DataFrame(rows)
    tab.to_csv(os.path.join(OUT, "r0_table.csv"), index=False)
    bdf = pd.DataFrame(betas_rows)
    bdf.to_csv(os.path.join(OUT, "r0_betas.csv"), index=False)

    # ---- chart ------------------------------------------------------------
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.4), sharex=True)
    for ax, clock, ttl in zip(axes, ["exec", "diss"],
                              ["Execution clock (#96)", "Dissemination clock (D3) — the decision panel"]):
        d = bdf[(bdf["clock"] == clock) & (bdf["bucket"] == "POOLED")].sort_values("k")
        kk = d["k"].to_numpy(); bb = d["beta"].to_numpy(); ss = d["se_cluster"].to_numpy()
        ax.fill_between(kk, bb - 1.96 * ss, bb + 1.96 * ss, alpha=0.25, color="#3b6ea5",
                        label="95% CI, day-clustered")
        ax.plot(kk, bb, color="#14304f", lw=1.6, marker="o", ms=2.6, label=r"$\beta_k$")
        ax.axhline(0, color="#666", lw=0.8)
        ax.axvline(0, color="#c0392b", lw=1.4, ls="--", label="k = 0")
        ax.set_title(f"{ttl}   —   pooled, bucket FE", fontsize=10.5, loc="left")
        ax.set_ylabel(r"$\beta_k$  (std. Y per std. X)")
        ax.grid(alpha=0.25, lw=0.5)
        ax.legend(fontsize=8, loc="upper left", framealpha=0.9)
    axes[1].set_xlabel(r"$k$   (lag in minutes;  $k>0$: X precedes Y = post-print hedge window)")
    fig.suptitle("R0 — signed futures aggressor volume on signed customer swap DV01\n"
                 r"pre-registered hedge channel is $\beta_k<0$ at small $k>0$",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(os.path.join(OUT, "r0_betas.png"), dpi=160)
    plt.close(fig)

    # ---- verdict (R2/R3): pooled, dissemination clock, all flow ------------
    v = tab[(tab["clock"] == "diss") & (tab["scope"] == "pooled") & (tab["split"] == "all")].iloc[0]
    Sp, tp = v["sum_beta_kpos"], v["t_cluster_kpos"]
    Sn, tn = v["sum_beta_kneg"], v["t_cluster_kneg"]
    sig_pos = abs(tp) > TSTAT_CRIT
    sig_neg = abs(tn) > TSTAT_CRIT
    ratio_ok = abs(Sp) >= 2 * abs(Sn)
    right_sign = Sp < 0

    # Verdict ladder, exactly as frozen in r0_deviations.md R3 against r0_prereg.md.
    if not sig_pos:
        verdict, why = "FAIL", ("post-print mass is indistinguishable from zero under "
                                "day-clustered standard errors")
    elif not right_sign:
        verdict, why = "FAIL", ("post-print mass is significant but POSITIVE; the prereg "
                                "states a positive beta of the same magnitude is a "
                                "different phenomenon, not a pass")
    elif sig_neg:
        verdict, why = "AMBIGUOUS", "both the pre-print and the post-print sums are significant"
    elif ratio_ok:
        verdict, why = "PASS", ("post-print sum is significantly negative and at least 2x "
                                "the magnitude of the pre-print sum")
    else:
        verdict, why = "FAIL", ("post-print sum is significantly negative but is less than "
                                "2x the magnitude of the pre-print sum")

    log("")
    log("=" * 96)
    log("VERDICT — pooled, DISSEMINATION clock, all flow, day-clustered SEs (r0_prereg.md)")
    log("=" * 96)
    log(f"  sum(beta_k, k <= -1) = {Sn:+.5f}   SE {v['se_cluster_kneg']:.5f}   "
        f"t = {tn:+.2f}   (NW t = {v['t_nw_kneg']:+.2f})")
    log(f"  sum(beta_k, k >=  1) = {Sp:+.5f}   SE {v['se_cluster_kpos']:.5f}   "
        f"t = {tp:+.2f}   (NW t = {v['t_nw_kpos']:+.2f})")
    log(f"  difference (pos-neg) = {v['diff_pos_minus_neg']:+.5f}  "
        f"t = {v['t_cluster_diff']:+.2f}   (NW t = {v['t_nw_diff']:+.2f})")
    log(f"  beta_(k=0)           = {v['beta_k0']:+.5f}   t = {v['t_cluster_k0']:+.2f}")
    log(f"  |S_pos| / |S_neg|    = {v['abs_ratio_pos_over_neg']:.3f}   (PASS needs >= 2.0)")
    log(f"  post-print share     = {v['post_print_share']:.3f}")
    log(f"  post-print sum significant under day clustering : {sig_pos}")
    log(f"  post-print sum has the PRE-REGISTERED sign (<0)  : {right_sign}")
    log(f"  pre-print sum significant                        : {sig_neg}")
    log("")
    log(f"  VERDICT = {verdict}")
    log(f"  reason  : {why}")
    log("")
    log("D2 (addendum 1) — centroid of the |beta_k| mass, pooled all-flow:")
    for clock in ["exec", "diss"]:
        c = tab[(tab["clock"] == clock) & (tab["scope"] == "pooled") &
                (tab["split"] == "all")]["centroid_absbeta_D2"].iloc[0]
        log(f"    {clock}: {c:+.3f} bins")
    ce = tab[(tab.clock == "exec") & (tab.scope == "pooled") & (tab.split == "all")]["centroid_absbeta_D2"].iloc[0]
    cd = tab[(tab.clock == "diss") & (tab.scope == "pooled") & (tab.split == "all")]["centroid_absbeta_D2"].iloc[0]
    log(f"    diss - exec = {cd - ce:+.3f} bins  (attenuation-invariant)")
    log("")
    log(f"wrote {os.path.join(OUT, 'r0_betas.png')}")
    log(f"wrote {os.path.join(OUT, 'r0_table.csv')}   ({len(tab)} rows)")
    log(f"wrote {os.path.join(OUT, 'r0_betas.csv')}")
    log(f"elapsed {time.time() - t_start:.1f}s")

    with open(os.path.join(OUT, "r0_run.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_LOG_LINES) + "\n")
    with open(os.path.join(OUT, "r0_verdict.txt"), "w", encoding="utf-8") as f:
        f.write(verdict + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
