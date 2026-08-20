r"""Matrices, flies, signals and the selection rule the timestamp grid runs on.

Everything downstream is (date x bond) numpy, because the grid asks the same question
19,200 times and a pandas groupby per cell would make the search the bottleneck rather
than the thinking.

Four decisions worth stating, because each one is a place a grid flatters itself.

**The P&L is a fly of YIELDS, not a fly of residuals.** The engine's object is
``R = y_belly - a*y_front - (1-a)*y_back`` with ``a = (t_back - t_belly)/(t_back -
t_front)``, and a long fly earns ``-(R - R0)`` per unit of belly DV01. Residuals are for
*ranking* only. A fly of residuals differs from a fly of yields by the fly of the fitted
curve, which is not a traded object, and mixing the two makes the numbers incomparable to
both the daily study and the perfect-foresight ceiling.

**Selection uses only what is knowable at entry.** Eligibility is: the signal is finite at
``mark_hour``, and all three legs are priced at ``mark_hour`` *and* at ``entry_hour``.
Whether the exit print exists is NOT part of eligibility -- filtering on it would let the
grid quietly select the bonds that happened to trade.

**Ties are broken by a fixed random permutation, not by array position.** ``deletion`` and
``not_held`` are exactly zero for most of a 97-bond cross-section. ``argsort`` on a tied
vector returns index order, which here is maturity order, so a "signal" with no
cross-sectional variation would systematically buy one end of the curve and sell the
other -- a curve tilt wearing the signal's name. Dates with fewer than
``MIN_DISTINCT_SCORES`` distinct finite scores are refused outright.

**The cost is charged once per completed round trip, at the full package weight.** The
three legs carry ``|1| + |a| + |1-a| = 2`` times the average leg spread, and an intraday
hold pays exactly the same as a one-month hold -- the spread does not know how long you
held.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "notebooks" / "backtests" / "etf_rebalance" / "_data"

CLOCK_HOURS = list(range(9, 18))
WING_GAP_MIN_Y = 0.10
WING_GAP_MAX_Y = 0.80
MIN_DISTINCT_SCORES = 12
TIE_SEED = 20260820


# ----------------------------------------------------------------------------- matrices

@dataclass
class Matrices:
    dates: pd.DatetimeIndex
    cusips: np.ndarray
    Y: Dict[int, np.ndarray]          # clock hour -> (D, N) yield in percent
    RESZ: Dict[int, np.ndarray]       # clock hour -> (D, N) cross-sectional z of resid_bp
    RES: Dict[int, np.ndarray]        # clock hour -> (D, N) resid_bp
    STALE: Dict[int, np.ndarray]      # clock hour -> (D, N) bool, yield == prior hour
    T: np.ndarray                     # (D, N) ttm
    MODDUR: np.ndarray                # (D, N)
    SPREAD_PX: np.ndarray             # (D, N) FedInvest full spread in PRICE bp
    RANK: np.ndarray                  # (D, N) off-the-run rank
    early_close: np.ndarray           # (D,) bool
    is_last_bd: np.ndarray            # (D,) bool


def _pivot(df: pd.DataFrame, value: str, dates, cusips) -> np.ndarray:
    p = df.pivot_table(index="date", columns="cusip", values=value, aggfunc="last")
    return p.reindex(index=dates, columns=cusips).to_numpy(float)


def load_matrices(panel_path: Optional[pathlib.Path] = None) -> Matrices:
    p = pd.read_parquet(panel_path or (DATA / "tsgrid_intraday_panel.parquet"))
    dates = pd.DatetimeIndex(np.sort(p["date"].unique()))
    cusips = np.sort(p["cusip"].unique())

    Y, RESZ, RES, STALE = {}, {}, {}, {}
    for h in CLOCK_HOURS:
        g = p[p["hour"] == h]
        Y[h] = _pivot(g, "ytm_h", dates, cusips)
        RES[h] = _pivot(g, "resid_bp", dates, cusips)
        r = RES[h]
        med = np.nanmedian(r, axis=1, keepdims=True)
        mad = np.nanmedian(np.abs(r - med), axis=1, keepdims=True) * 1.4826
        sd = np.nanstd(r, axis=1, keepdims=True)
        scale = np.where(mad > 0, mad, sd)
        with np.errstate(invalid="ignore", divide="ignore"):
            RESZ[h] = np.clip((r - med) / np.where(scale > 0, scale, np.nan), -5.0, 5.0)
        st = g.pivot_table(index="date", columns="cusip", values="stale", aggfunc="last")
        STALE[h] = st.reindex(index=dates, columns=cusips).fillna(False).to_numpy(bool)

    base = p[p["hour"] == 16]
    T = _pivot(base, "ttm", dates, cusips)
    MODDUR = _pivot(base, "mod_dur", dates, cusips)
    SPREAD_PX = _pivot(base, "spread_price_bp", dates, cusips)
    RANK = _pivot(base, "rank", dates, cusips)

    day = p.groupby("date")[["early_close", "is_last_bd"]].first().reindex(dates)
    return Matrices(dates=dates, cusips=cusips, Y=Y, RESZ=RESZ, RES=RES, STALE=STALE,
                    T=T, MODDUR=MODDUR, SPREAD_PX=SPREAD_PX, RANK=RANK,
                    early_close=day["early_close"].fillna(False).to_numpy(bool),
                    is_last_bd=day["is_last_bd"].fillna(False).to_numpy(bool))


# --------------------------------------------------------------------------------- legs

@dataclass
class Legs:
    front: np.ndarray   # (D, N) int, -1 where no wing
    back: np.ndarray
    a: np.ndarray       # (D, N) float
    valid: np.ndarray   # (D, N) bool


def build_legs(m: Matrices, *, step: int = 1) -> Legs:
    """Nearest eligible wing on each side, ``step`` maturity places away.

    ``step`` is the fly WIDTH knob: 1 is the nearest neighbour on each side (a ~3-month
    fly, the ladder's own width), 2 skips one bond, and so on.
    """
    D, N = m.T.shape
    front = np.full((D, N), -1, dtype=int)
    back = np.full((D, N), -1, dtype=int)
    a = np.full((D, N), np.nan)
    for d in range(D):
        t = m.T[d]
        ok = np.where(np.isfinite(t))[0]
        if ok.size < 2 * step + 1:
            continue
        order = ok[np.argsort(t[ok], kind="stable")]
        tt = t[order]
        for k in range(step, order.size - step):
            j, jf, jb = order[k], order[k - step], order[k + step]
            gf, gb = tt[k] - tt[k - step], tt[k + step] - tt[k]
            if not (WING_GAP_MIN_Y <= gf <= WING_GAP_MAX_Y):
                continue
            if not (WING_GAP_MIN_Y <= gb <= WING_GAP_MAX_Y):
                continue
            front[d, j], back[d, j] = jf, jb
            a[d, j] = (tt[k + step] - tt[k]) / (tt[k + step] - tt[k - step])
    return Legs(front=front, back=back, a=a, valid=front >= 0)


def fly_level(m: Matrices, legs: Legs, hour: int) -> np.ndarray:
    """``R = y_belly - a*y_front - (1-a)*y_back`` in PERCENT, NaN where unbuildable."""
    y = m.Y[hour]
    D, N = y.shape
    rows = np.arange(D)[:, None]
    f = np.where(legs.valid, legs.front, 0)
    b = np.where(legs.valid, legs.back, 0)
    yf = y[rows, f]
    yb = y[rows, b]
    R = y - legs.a * yf - (1.0 - legs.a) * yb
    return np.where(legs.valid, R, np.nan)


def package_cost_bp(m: Matrices, legs: Legs, *, anchor: str) -> np.ndarray:
    """Round-trip cost of the package in YIELD bp per unit of BELLY DV01."""
    if anchor == "measured":
        px = np.where(m.SPREAD_PX >= 0.5, m.SPREAD_PX, np.nan)
        med = np.nanmedian(px, axis=1, keepdims=True)
        px = np.where(np.isfinite(px), px, med)
        leg = px / m.MODDUR
    elif anchor == "flat":
        leg = np.full_like(m.MODDUR, 0.30)
        leg[~np.isfinite(m.MODDUR)] = np.nan
    elif anchor == "sr1170":
        # 30y sector, keyed on off-the-run rank, the paper's own table
        tbl = np.array([4.96, 5.18, 12.35, 16.21, 18.34, 18.69, 166.98])
        r = np.where(np.isfinite(m.RANK), np.clip(m.RANK, 0, 6), 6).astype(int)
        leg = tbl[r] / m.MODDUR
    else:
        raise ValueError(anchor)
    D, N = leg.shape
    rows = np.arange(D)[:, None]
    f = np.where(legs.valid, legs.front, 0)
    b = np.where(legs.valid, legs.back, 0)
    C = leg + np.abs(legs.a) * leg[rows, f] + np.abs(1.0 - legs.a) * leg[rows, b]
    return np.where(legs.valid, C, np.nan)


# ------------------------------------------------------------------------------ signals

HOLDINGS_SIGNALS = ["active_w", "active_rel", "bucket_active", "bucket_hist_z",
                    "flow", "ownership", "not_held"]
CALENDAR_SIGNALS = ["deletion", "addition"]
CONTROL_SIGNALS = ["resid"]
ALL_SIGNALS = HOLDINGS_SIGNALS + CALENDAR_SIGNALS + CONTROL_SIGNALS


def _xsec_z(raw: np.ndarray) -> np.ndarray:
    med = np.nanmedian(raw, axis=1, keepdims=True)
    mad = np.nanmedian(np.abs(raw - med), axis=1, keepdims=True) * 1.4826
    sd = np.nanstd(raw, axis=1, keepdims=True)
    scale = np.where(mad > 0, mad, sd)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (raw - med) / np.where(scale > 0, scale, np.nan)
    return np.clip(z, -5.0, 5.0)


def build_signal_matrices(m: Matrices, *, fund: str = "TLT") -> Dict[str, np.ndarray]:
    """Raw (unlagged, un-z'd) signal matrices on the panel's own (date, cusip) grid."""
    act = pd.read_parquet(DATA / f"fundfig_active_{fund}.parquet")
    act = act[act["cusip"].isin(set(m.cusips))]
    act = act[act["date"] >= m.dates.min() - pd.Timedelta(days=400)]
    act = act.sort_values(["date", "cusip"]).copy()
    act["par_per_share"] = act["par"] / act["shares_out"].replace(0, np.nan)

    hd = pd.DatetimeIndex(np.sort(act["date"].unique()))

    def piv(col, frame=None):
        f = act if frame is None else frame
        return f.pivot_table(index="date", columns="cusip", values=col,
                             aggfunc="last").reindex(index=hd, columns=m.cusips
                                                     ).to_numpy(float)

    W_F, W_I, ACT = piv("w_f"), piv("w_i"), piv("active_w")
    OWN, PPS, FF = piv("ownership"), piv("par_per_share"), piv("free_float")
    TTM_H = piv("ttm")
    HELD = act.pivot_table(index="date", columns="cusip", values="held",
                           aggfunc="last").reindex(index=hd, columns=m.cusips
                                                   ).fillna(False).to_numpy(bool)

    out: Dict[str, np.ndarray] = {}
    out["active_w"] = -ACT
    with np.errstate(invalid="ignore", divide="ignore"):
        out["active_rel"] = -(ACT / np.where(W_I != 0, W_I, np.nan))
    out["ownership"] = OWN
    out["not_held"] = (~HELD).astype(float) * np.nan_to_num(W_I)

    # flow: 5-holdings-day change in par per share, scaled by float
    d5 = PPS - np.roll(PPS, 5, axis=0)
    d5[:5] = np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        out["flow"] = d5 / np.where(FF > 0, FF, np.nan) * 1e6

    # bucket signals: 0.25y constant-maturity buckets
    bidx = np.floor(TTM_H / 0.25)
    ba = np.full_like(ACT, np.nan)
    bh = np.full_like(ACT, np.nan)
    for i in range(bidx.shape[0]):
        b = bidx[i]
        fin = np.isfinite(b)
        if not fin.any():
            continue
        keys, inv = np.unique(b[fin], return_inverse=True)
        sf = np.zeros(keys.size)
        si = np.zeros(keys.size)
        np.add.at(sf, inv, np.nan_to_num(W_F[i][fin]))
        np.add.at(si, inv, np.nan_to_num(W_I[i][fin]))
        v = np.full(b.size, np.nan)
        v[fin] = -(sf - si)[inv]
        ba[i] = v
        w = np.full(b.size, np.nan)
        w[fin] = sf[inv]
        bh[i] = w
    out["bucket_active"] = ba
    # bucket_hist_z: bucket weight against its own trailing 250-day history (shifted)
    bw = pd.DataFrame(bh)
    prior = bw.shift(1)
    mu = prior.rolling(250, min_periods=62).mean()
    sd = prior.rolling(250, min_periods=62).std()
    out["bucket_hist_z"] = -((bw - mu) / sd.replace(0.0, np.nan)).to_numpy()

    # calendar-only, computed from maturity alone -- no holdings file is read
    D = hd.size
    me = (hd + pd.offsets.MonthEnd(0))
    hit = np.full((D, m.cusips.size), np.nan)
    for mth in range(3, -1, -1):
        rebal = me + pd.offsets.MonthEnd(mth)
        dd = ((rebal - hd).days.to_numpy(float) / 365.25)[:, None]
        drops = (TTM_H - dd) < 20.0
        hit = np.where(drops, float(mth), hit)
    out["deletion"] = -np.where(np.isfinite(hit), 4.0 - hit, 0.0) / 4.0

    iss = act.groupby("cusip")["maturity_date"].first()
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    issd = pd.to_datetime(uni.set_index("cusip")["issue_date"]).reindex(m.cusips)
    age_m = ((hd.to_numpy()[:, None] - issd.to_numpy()[None, :])
             / np.timedelta64(1, "D")) / 30.44
    out["addition"] = np.where(age_m >= 0, np.exp(-age_m / 3.0), 0.0)

    # reindex every matrix from holdings dates onto panel dates, forward filled
    res = {}
    for k, v in out.items():
        df = pd.DataFrame(v, index=hd, columns=m.cusips)
        res[k] = df.reindex(m.dates, method="ffill", limit=5).to_numpy(float)
    return res


def orthogonalize(Z: np.ndarray, CTRL: np.ndarray) -> np.ndarray:
    """Cross-sectional residual of ``Z`` on ``CTRL``, date by date.

    The daily study's central finding is that the holdings signals are the bond's own
    richness in disguise; every sign flipped once this was applied. It is a grid axis
    here for the same reason, and it is the only way ``mark_hour`` can bind on a signal
    read from a once-a-day holdings file.
    """
    D, N = Z.shape
    out = np.full((D, N), np.nan)
    for d in range(D):
        z, c = Z[d], CTRL[d]
        ok = np.isfinite(z) & np.isfinite(c)
        if ok.sum() < MIN_DISTINCT_SCORES:
            continue
        x = c[ok] - c[ok].mean()
        den = float(x @ x)
        if den <= 0:
            continue
        b = float(x @ (z[ok] - z[ok].mean())) / den
        out[d, ok] = z[ok] - z[ok].mean() - b * x
    return out


def lag_matrix(M: np.ndarray, lag: int) -> np.ndarray:
    """Shift a signal ``lag`` panel rows forward. Row t then holds date t-lag's book."""
    if lag <= 0:
        return M
    out = np.full_like(M, np.nan)
    out[lag:] = M[:-lag]
    return out


# ----------------------------------------------------------------------------- selection

@dataclass
class Selection:
    top: np.ndarray      # (D, n) int, -1 where unusable
    bot: np.ndarray
    usable: np.ndarray   # (D,) bool


def select(Z: np.ndarray, eligible: np.ndarray, *, n: int = 3,
           rng_perm: Optional[np.ndarray] = None) -> Selection:
    D, N = Z.shape
    if rng_perm is None:
        rng_perm = np.random.default_rng(TIE_SEED).permutation(N).astype(float)
    score = np.where(eligible & np.isfinite(Z), Z, np.nan)
    cnt = np.isfinite(score).sum(axis=1)

    filled = np.where(np.isfinite(score), score, np.inf)
    order = np.lexsort((np.broadcast_to(rng_perm, (D, N)), filled), axis=-1)
    srt = np.take_along_axis(filled, order, axis=-1)

    # distinct finite scores per date, without a python loop: count the steps in the
    # sorted finite prefix. A cross-section with too few distinct values cannot be
    # ranked, and ranking it anyway selects by tie-break rather than by signal.
    col = np.arange(N)[None, :]
    finite_pos = col < cnt[:, None]
    step = np.ones((D, N), bool)
    step[:, 1:] = srt[:, 1:] != srt[:, :-1]
    ndist = (step & finite_pos).sum(axis=1)
    usable = (cnt >= 2 * n) & (ndist >= MIN_DISTINCT_SCORES)

    bot = order[:, :n].copy()
    take = np.clip(cnt[:, None] - n + np.arange(n)[None, :], 0, N - 1)
    top = np.take_along_axis(order, take, axis=-1).copy()
    bot[~usable] = -1
    top[~usable] = -1
    return Selection(top=top, bot=bot, usable=usable)


def perfect_foresight_per_date(ret: np.ndarray, eligible: np.ndarray, *, n: int = 3
                               ) -> np.ndarray:
    """Per date, the mean |return| of the ``2n`` largest movers -- the book's own ceiling.

    A six-package book that knew the sign of every fly would earn exactly this. It is a
    hard upper bound on any cell built from the same return matrix and the same
    eligibility, so every grid cell is asserted against it.
    """
    a = np.where(eligible & np.isfinite(ret), np.abs(ret), np.nan)
    D, N = a.shape
    k = 2 * n
    filled = np.where(np.isfinite(a), a, -np.inf)
    part = -np.sort(-filled, axis=1)[:, :k]
    part = np.where(np.isfinite(part), part, np.nan)
    with np.errstate(invalid="ignore"):
        out = np.nanmean(part, axis=1)
    cnt = np.isfinite(a).sum(axis=1)
    return np.where(cnt >= k, out, np.nan)


def cell_pnl(ret: np.ndarray, cost: np.ndarray, sel: Selection
             ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-date mean gross bp, mean cost bp and trade count for one selection."""
    D = ret.shape[0]
    gross = np.full(D, np.nan)
    cst = np.full(D, np.nan)
    ntr = np.zeros(D, dtype=int)
    rows = np.where(sel.usable)[0]
    if rows.size == 0:
        return gross, cst, ntr
    t, b = sel.top[rows], sel.bot[rows]
    rr = np.concatenate([ret[rows[:, None], t], -ret[rows[:, None], b]], axis=1)
    cc = np.concatenate([cost[rows[:, None], t], cost[rows[:, None], b]], axis=1)
    ok = np.isfinite(rr) & np.isfinite(cc)
    n = ok.sum(axis=1)
    with np.errstate(invalid="ignore"):
        g = np.where(n > 0, np.nansum(np.where(ok, rr, 0.0), axis=1) / np.maximum(n, 1), np.nan)
        c = np.where(n > 0, np.nansum(np.where(ok, cc, 0.0), axis=1) / np.maximum(n, 1), np.nan)
    gross[rows], cst[rows], ntr[rows] = g, c, n
    return gross, cst, ntr


# ------------------------------------------------------------------------------- stats

def newey_west_t(x: np.ndarray, lags: int) -> float:
    """t of the mean of ``x`` with a Bartlett HAC correction at ``lags``."""
    v = x[np.isfinite(x)]
    n = v.size
    if n < 20:
        return np.nan
    e = v - v.mean()
    s = float(e @ e) / n
    for L in range(1, min(lags, n - 1) + 1):
        w = 1.0 - L / (lags + 1.0)
        s += 2.0 * w * float(e[L:] @ e[:-L]) / n
    if s <= 0:
        return np.nan
    return float(v.mean() / np.sqrt(s / n))
