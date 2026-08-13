"""S1 -- does signed swap-spread flow predict the swap spread?

``docs/dealer_direction/signals/S_PREREG.md`` S1, run on the design sample only.
The specification below was frozen, and the SPEC section of ``S1_RESULT.md``
written, **before the regression executed**. Nothing here is parameterised by a
CLI switch that could reach the hold-out.

Stages::

    python BT/dd_signals/s1_spread_flow.py mi01      # -> D:/.../s1_mi01_min.parquet
    python BT/dd_signals/s1_spread_flow.py validate  # machinery vs known answers
    python BT/dd_signals/s1_spread_flow.py run       # -> out/s1_results.csv

Reads ``D:/dd_signals_cache/s1_dev.parquet`` (built by ``measure_costs.py s1``:
one row per spread package, the printed ``package_transaction_spread`` in bp,
the MI01 mid at the production T-1min instant, and their difference) and
``out/costs.csv`` (the per-bucket ``b0`` and the cost hurdles, both measured
before any signal was estimated). No tape read happens here at all, so the
hold-out cannot be touched by this module even by accident.
"""

from __future__ import annotations

import datetime
import math
import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")

import numpy as np
import pandas as pd

REPO = "C:/Users/chris/clee/ARBS-dd"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

CACHE = pathlib.Path("D:/dd_signals_cache")
OUT = pathlib.Path(REPO) / "BT" / "dd_signals" / "out"

# =========================================================================
# THE FROZEN SPECIFICATION.  One specification, run once (S_PREREG §5).
# =========================================================================

#: S_PREREG §2. The hold-out (2025-09-01 .. 2026-08-07) is not opened. Module
#: constants with no CLI override, exactly as in ``measure_costs.py``. MI01 is
#: read only inside this window, so a forward change that would need a
#: September close simply has no target and drops -- the truncation is
#: structural rather than a filter that could be relaxed.
DESIGN_START = "2024-03-01"
DESIGN_END = "2025-08-31"

#: The population. S_PREREG §4 makes "the S1 units failing to reconcile against
#: MI01" a reason to call a test uninformative, and ``COSTS.md`` §3.6 records
#: that clause FIRING for ``MATCHED_MATURITY`` and ``INVOICE``: they carry a PTS
#: on 6.5%/8.2% of legs and on that subset ``b0`` reaches +16.7 bp and ``s``
#: 17.9 bp against MI01, because an invoice spread is quoted to a futures CTD
#: forward and not to MI01's spot axis. Those rows carry
#: ``reconciles_to_mid = False`` in ``costs.csv``. Signing them off an MI01
#: deviation would be signing off a 17 bp measurement error, so the tested
#: family is SPREADOVER, which reconciles to +-0.05 bp at every tenor.
FAMILY = "SPREADOVER"

#: S_PREREG S1 is about *customer* flow, so the primary venue is D2C. D2D is
#: interdealer -- the dealer laying risk off, not a customer decision -- and is
#: carried as one labelled diagnostic, never pooled with D2C.
PRIMARY_VENUE = "D2C"
DIAGNOSTIC_VENUE = "D2D"

#: MI01's axis intersected with the tenors spreadovers actually print at.
TENORS = ("2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")

#: The daily mark. 15:00 New York is the Treasury cash close, which is the
#: instant a swap spread is marked at. MI01's session is 01:00-22:59 ET on a New
#: York clock, so this is inside it on every day.
CLOSE_ET = datetime.time(15, 0)

#: A close is the last MI01 print at or before 15:00 ET and must be no more than
#: this stale. MI01 prints ~1,300 of its 1,320 session minutes, so this only
#: rejects a genuinely broken day rather than trimming the sample.
CLOSE_MAX_STALE = pd.Timedelta("30min")

#: Flow window for close-day D: ``[cutoff(D-1), cutoff(D))`` where
#: ``cutoff(D) = D 15:00 ET``. Half-open and ending AT the target's own base
#: instant, so no print in the flow can post-date the start of the forward
#: change being predicted. 82.1% of prints are before 15:00 ET on their own
#: calendar day; the rest are the London and the 19:00-22:59 ET sessions, which
#: this window assigns to the next close rather than dropping. ``as_of_date`` on
#: the tape is a UTC date and could not be used for this: 4.4% of prints fall on
#: a different New York date than their ``as_of_date``.
#:
#: Days are indexed by MI01's own observed close calendar, not by pandas'
#: business-day rule, so holidays cannot shift a horizon.

#: S_PREREG S1: "the following 1-5 business days".
HORIZONS = (1, 2, 3, 4, 5)

#: The regressor: notional-weighted net signed fraction,
#: ``F = sum(n_i * d_i) / sum(n_i)`` over the window, with
#: ``d_i = sign(deviation_i - b0_bucket)`` in ``{-1, +1}``.
#:
#: The sign, not a calibrated probability, because ``tau = s^2/(2h)`` needs
#: ``h``, and ``COSTS.md`` §3.2 records that the mixture fit could not resolve
#: ``h`` on this population (all 14 buckets at separation 0.025-0.050 against a
#: gate of 1.0). ``sign(x - b0)`` is invariant to ``tau``; a probability
#: weighting is not. ``F`` in ``[-1, +1]`` is bounded and scale-free across
#: buckets, and the kill-rule quantity -- edge per trade -- depends only on
#: ``sign(F)``, so it is invariant to this normalisation entirely.
#:
#: ``b0`` per bucket comes from ``costs.csv``, fitted before any signal was
#: estimated. |b0| <= 0.028 bp everywhere, so it is a small correction, but
#: taking it from the pre-measured file rather than re-estimating it here keeps
#: the de-biasing out of the signal's own hands.
#: ``d_i = 0`` (deviation exactly on ``b0``) is dropped and counted.

#: Same 6-MAD trim as the cost fit, per bucket, applied BEFORE signing:
#: ``costs.csv``'s ``b0`` was fitted on the trimmed population, and the sign of
#: a wrong-bond print or a misprint (the p99 tail of 1-22 bp in ``COSTS.md``
#: §3.3) is noise about direction, not information.
TRIM_K = 6.0

#: MI01's own staleness tolerance when re-signing for the placebo, matching
#: ``measure_costs.MI01_TOLERANCE``.
MI01_TOLERANCE = pd.Timedelta("2min")

#: S_PREREG §4: "fewer than ~200 usable bucket-days" makes a cell uninformative.
#: A usable bucket-day is a close-day that has a valid k-step-forward close and
#: at least one signable print in its window.
MIN_BUCKET_DAYS = 200

#: S_PREREG §3: p < 0.025, Bonferroni over the two hypotheses. Two-sided,
#: because a wrong-sign result has to be reportable as such.
ALPHA = 0.025
Z_ALPHA = 1.959963984540054            # not used for the test; kept for reference
Z_ALPHA_2SIDED = 2.2414027276049526    # Phi^-1(1 - 0.025/2)
Z_POWER = 0.8416212335729143           # Phi^-1(0.80)

#: MDE at 80% power for a two-sided test at ALPHA.
MDE_MULT = Z_ALPHA_2SIDED + Z_POWER    # 3.0830

#: Overlapping k-day forward changes on a daily index are MA(k-1), which
#: day-clustering inside a single bucket's time series cannot see -- within a
#: bucket there is one observation per day, so a day cluster has one member.
#: Aggregating prints to bucket-days is what satisfies S_PREREG §4's "N_eff is
#: trading days"; Newey-West with a Bartlett kernel at lag = k is what handles
#: the overlap. Declared here before the run, and validated in ``validate``
#: against planted MA(k-1) errors.
def nw_lag(k: int) -> int:
    return int(k)


#: **Size correction, forced by the validation stage and applied before the real
#: run.** The SPEC declared Newey-West at lag = k judged against a normal
#: critical value. ``validate`` test (4) -- which is exactly what the SPEC put
#: the validation there for -- measured that combination REJECTING A TRUE NULL
#: AT 5-7% instead of 2.5% once the regressor is persistent and the horizon
#: overlaps (plain OLS reaches 29%). Widening the Bartlett bandwidth does not
#: fix it: k=5 stays at 5.4-7.4% for every lag from k to 4k, and a circular
#: block bootstrap at L = 10/20/30 lands in the same place. This is the known
#: finite-sample over-rejection of overlapping long-horizon tests, not a
#: bandwidth choice.
#:
#: So the critical value is calibrated by simulation instead of assumed: for a
#: cell's own ``(n, k, rho)`` the null distribution of ``|t|`` is simulated
#: under an AR(1) regressor and MA(k-1) errors, and its 98.75th percentile is
#: the critical value. ``rho`` is the lag-1 autocorrelation of ``F`` itself --
#: a property of the regressor, observable without the target, so calibrating
#: on it looks at nothing the hypothesis is about.
#:
#: The correction moves every number the same way: a larger critical value
#: makes PASS harder, DEAD harder, and UNINFORMATIVE easier. That is the
#: direction a kill rule may not be wrong in -- an under-sized SE would have
#: manufactured DEAD verdicts out of noise, which is precisely R0's downgrade
#: run backwards. At k=5, rho=0.6, n=370 the multiplier is 2.918 for beta and
#: 2.646 for the edge against the normal's 2.241.
CRIT_REPS = 20000
CRIT_SEED = 20260812
_CRIT_CACHE: dict = {}


def null_crits(n: int, k: int, rho: float) -> tuple[float, float]:
    """Size-corrected two-sided critical ``|t|`` at ALPHA for (beta, edge)."""
    from scipy.signal import lfilter

    rho = float(min(max(rho, 0.0), 0.9))
    key = (int(n), int(k), round(rho, 1))
    if key in _CRIT_CACHE:
        return _CRIT_CACHE[key]
    n_, k_, rho_ = key[0], key[1], key[2]
    rng = np.random.default_rng((CRIT_SEED, n_, k_, int(rho_ * 10)))
    z = rng.normal(size=(CRIT_REPS, n_))
    F = lfilter([math.sqrt(1.0 - rho_ * rho_)], [1.0, -rho_], z, axis=1)
    inno = rng.normal(size=(CRIT_REPS, n_ + k_))
    cs = np.cumsum(inno, axis=1)
    y = cs[:, k_:] - cs[:, :-k_]              # exactly the MA(k-1) the overlap makes
    lag = nw_lag(k_)
    ones = np.ones(n_)
    tb = np.empty(CRIT_REPS)
    te = np.empty(CRIT_REPS)
    for i in range(CRIT_REPS):
        b, se = nw_ols(y[i], np.column_stack([ones, F[i]]), lag)
        tb[i] = b[1] / se[1] if se[1] > 0 else np.nan
        s = np.sign(F[i])
        m, sm = nw_mean(-s * y[i], lag)
        te[i] = m / sm if sm > 0 else np.nan
    q = 1.0 - ALPHA / 2.0
    out = (float(np.nanquantile(np.abs(tb), q)),
           float(np.nanquantile(np.abs(te), q)))
    _CRIT_CACHE[key] = out
    return out

#: The verdict ladder, fixed before the run so no band can be chosen after
#: seeing a number. ``kill_ceiling`` is ``kill_threshold_used_bps`` from
#: ``costs.csv`` (2x the measured round-trip ceiling, S_PREREG §1).
#: ``kill_floor`` is 2x the lattice floor -- ``COSTS.md`` §5.2's explicit
#: instruction that an edge between the floor and ceiling hurdles is genuinely
#: ambiguous rather than dead. D2C has no detectable lattice of its own, so it
#: inherits the same-tenor D2D increment as its floor, which is what §5.2 says
#: to do.
#:
#:   1. usable bucket-days < 200                      -> UNINFORMATIVE_COVERAGE
#:   2. sign wrong AND p < ALPHA                      -> WRONG_SIGN
#:   3. edge >= kill_ceiling AND p < ALPHA AND sign ok -> PASS (hold-out may open)
#:   4. edge + z*SE < kill_floor                      -> DEAD
#:   5. MDE > kill_ceiling                            -> UNINFORMATIVE_POWER
#:   6. otherwise                                     -> AMBIGUOUS (hold-out shut)
#:
#: Band 4 before band 5 deliberately: DEAD is only claimed when the whole
#: one-sided 98.75% range of the edge sits below even the cheapest reading of
#: the cost, which is a statement that does not need the test to have had power
#: against the ceiling. Anything that fails band 4 and has MDE above the
#: ceiling is UNINFORMATIVE, exactly as R0's downgrade worked.
VERDICT_LADDER = ("UNINFORMATIVE_COVERAGE", "WRONG_SIGN", "PASS", "DEAD",
                  "UNINFORMATIVE_POWER", "AMBIGUOUS")

#: Direction, fixed in advance by S_PREREG S1: customer PAYS the spread ->
#: prints ABOVE the mid -> deviation > 0 -> F > 0; the dealer is left receiving
#: and long the spread, its pending trade is SELLING, so the spread FALLS. MI01
#: publishes the spread as swap minus Treasury (-46 bp at 10Y), and the tape's
#: printed spread reconciles to it in level and sign, so "falls" is
#: unambiguously "becomes more negative".
#:
#:      EXPECTED_BETA_SIGN = -1
EXPECTED_BETA_SIGN = -1

#: One placebo, declared before the run (this repo's memory records that
#: post-hoc checks multiply until one flatters): re-sign every print against
#: the MI01 value at the SAME CLOCK MINUTE one close-day earlier. That destroys
#: both the half-spread information and any same-day mid-error link while
#: leaving the trade structure, the notionals and the window untouched. Its
#: edge must be ~0. If it is not, the pipeline leaks and the run is reported as
#: broken rather than as a result.
PLACEBO_NAME = "prev_session_same_minute_mid"

#: Simulation sizes for ``validate``. Seeded; the seed is consumed by a
#: generator, not positionally across a reordered frame.
VAL_REPS = 2000
VAL_SEED = 20260811


def _log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


# =========================================================================
# the estimator: OLS with a Newey-West (Bartlett) covariance
# =========================================================================

def nw_ols(y: np.ndarray, X: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and Newey-West standard errors at Bartlett ``lag``.

    ``X`` must already contain its own constant column. ``y`` and ``X`` must be
    on a CONTIGUOUS daily index -- the lag structure is positional, so a gap in
    the row index silently reinterprets the kernel. Callers build a gapless
    panel and put ``F = 0`` on a no-print day rather than dropping the row.

    A ``n/(n-k)`` degrees-of-freedom correction is applied to the meat, which is
    the conservative direction. Calibration is checked in :func:`stage_validate`.
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    b = xtx_inv @ (X.T @ y)
    e = y - X @ b
    u = X * e[:, None]
    S = u.T @ u
    for L in range(1, int(lag) + 1):
        if L >= n:
            break
        w = 1.0 - L / (lag + 1.0)
        G = u[L:].T @ u[:-L]
        S = S + w * (G + G.T)
    S = S * (n / max(n - k, 1))
    V = xtx_inv @ S @ xtx_inv
    return b, np.sqrt(np.maximum(np.diag(V), 0.0))


def nw_mean(x: np.ndarray, lag: int) -> tuple[float, float]:
    """Mean of ``x`` and its Newey-West standard error. ``x`` must be gapless."""
    x = np.asarray(x, dtype=float)
    b, se = nw_ols(x, np.ones((len(x), 1)), lag)
    return float(b[0]), float(se[0])


def two_sided_p(t: float) -> float:
    if not np.isfinite(t):
        return float("nan")
    return float(math.erfc(abs(t) / math.sqrt(2.0)))


# =========================================================================
# stage: mi01 -- the target series, read offline, bounded by DESIGN_END
# =========================================================================

MI01_CACHE = CACHE / "s1_mi01_min.parquet"


def stage_mi01() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as ss

    ss.set_force_offline(True)
    CACHE.mkdir(parents=True, exist_ok=True)

    _log("MI01: reading the design window offline, month by month")
    parts = []
    m0 = pd.Timestamp(DESIGN_START).to_period("M")
    m1 = pd.Timestamp(DESIGN_END).to_period("M")
    for per in pd.period_range(m0, m1, freq="M"):
        a = max(per.start_time, pd.Timestamp(DESIGN_START))
        b = min(per.end_time.normalize() + pd.Timedelta("23:59:00"),
                pd.Timestamp(DESIGN_END) + pd.Timedelta("23:59:00"))
        try:
            f = ss.swap_spread_history("USD_SOFR", TENORS, start=a, end=b, freq="MI01")
        except Exception as exc:  # noqa: BLE001
            _log(f"  {per}: FAILED {type(exc).__name__}: {exc}")
            continue
        if f is not None and not f.empty:
            parts.append(f.astype("float32"))
        _log(f"  {per}: {0 if f is None else len(f)} minutes")
    mi = pd.concat(parts).sort_index()
    mi = mi[~mi.index.duplicated(keep="first")]
    mi.index.name = "ts_et"
    # Structural hold-out guard: nothing outside the design window may be here.
    assert mi.index.max() <= pd.Timestamp(DESIGN_END) + pd.Timedelta("23:59:59"), \
        f"MI01 frame reaches {mi.index.max()} -- past DESIGN_END"
    mi.reset_index().to_parquet(MI01_CACHE, index=False)
    _log(f"MI01: wrote {MI01_CACHE} {mi.shape}, {mi.index.min()} .. {mi.index.max()}")


def load_mi01() -> pd.DataFrame:
    mi = pd.read_parquet(MI01_CACHE).set_index("ts_et").sort_index()
    mi = mi.astype(float)
    assert mi.index.max() <= pd.Timestamp(DESIGN_END) + pd.Timedelta("23:59:59")
    return mi


def daily_closes(mi: pd.DataFrame) -> pd.DataFrame:
    """Per-tenor 15:00 ET close: the last MI01 print in ``(14:30, 15:00]``.

    Returned indexed by New York calendar date, one column per tenor, NaN where
    no print inside the staleness window exists.
    """
    lo = (datetime.datetime.combine(datetime.date(2000, 1, 1), CLOSE_ET)
          - CLOSE_MAX_STALE).time()
    win = mi[(mi.index.time > lo) & (mi.index.time <= CLOSE_ET)]
    d = win.groupby(win.index.normalize()).last()
    d.index.name = "close_day"
    return d


# =========================================================================
# the print population
# =========================================================================

def load_prints() -> pd.DataFrame:
    d = pd.read_parquet(CACHE / "s1_dev.parquet",
                        columns=["package_id", "venue", "trade_type", "tenor_label",
                                 "notional", "is_block", "is_capped", "snap_et",
                                 "mi01_bp", "pts_bp", "deviation_bps"])
    d = d[d["trade_type"].eq(FAMILY)]
    d = d.dropna(subset=["deviation_bps", "snap_et", "notional"])
    d = d[d["notional"] > 0]
    return d.reset_index(drop=True)


def load_b0_and_hurdles() -> pd.DataFrame:
    c = pd.read_csv(OUT / "costs.csv", comment="#")
    c = c[c["family"].eq(FAMILY)].copy()
    c["tenor"] = c["tenor_bucket"]
    return c.set_index(["tenor", "venue"])


def sign_prints(prints: pd.DataFrame, cost: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """6-MAD trim per bucket, then ``d = sign(deviation - b0)``. Returns audit."""
    from SDRUtils.dealer_direction.probability import trim_mask

    out, audit = [], []
    for (t, v), g in prints.groupby(["tenor_label", "venue"], sort=True):
        if (t, v) not in cost.index:
            audit.append(dict(tenor=t, venue=v, n_raw=len(g), status="NO_COST_ROW"))
            continue
        row = cost.loc[(t, v)]
        b0 = float(row["b0_bps"])
        keep = trim_mask(g["deviation_bps"].to_numpy(float), TRIM_K)
        g = g[keep].copy()
        g["d"] = np.sign(g["deviation_bps"].to_numpy(float) - b0)
        n_zero = int((g["d"] == 0).sum())
        g = g[g["d"] != 0]
        out.append(g)
        audit.append(dict(tenor=t, venue=v, n_raw=int(keep.size),
                          n_trimmed_out=int((~keep).sum()), n_zero_sign=n_zero,
                          n_signed=len(g), b0_bps=b0,
                          frac_pay=float((g["d"] > 0).mean()),
                          frac_capped=float(g["is_capped"].mean()),
                          frac_block=float(g["is_block"].mean())))
    return pd.concat(out, ignore_index=True), audit


def assign_close_day(snap: pd.Series, close_days: pd.DatetimeIndex) -> np.ndarray:
    """Index into ``close_days`` of the close whose window contains each print.

    Window for close-day ``j`` is ``[cutoff_{j-1}, cutoff_j)``. ``side='right'``
    so a print exactly at 15:00:00 belongs to the NEXT close, keeping the
    interval half-open and the target strictly forward-looking. Prints before
    the first cutoff (no complete window) or after the last get ``-1``.
    """
    cut = (close_days + pd.Timedelta(hours=CLOSE_ET.hour,
                                     minutes=CLOSE_ET.minute)).to_numpy()
    idx = np.searchsorted(cut, snap.to_numpy(), side="right")
    idx = np.where(idx >= len(cut), -1, idx)
    idx = np.where(idx == 0, -1, idx)          # first day's window is incomplete
    return idx


# =========================================================================
# stage: validate -- the machinery against known answers, before the real run
# =========================================================================

def _ma_errors(rng, n: int, k: int, sd: float) -> np.ndarray:
    """Overlapping k-day sums of iid innovations: exactly the MA(k-1) the
    forward-change construction induces."""
    inno = rng.normal(0.0, sd, size=n + k)
    return np.array([inno[i:i + k].sum() for i in range(n)])


def stage_validate() -> None:
    _log("=" * 72)
    _log("VALIDATE -- the regression/NW/edge/MDE machinery vs known answers")
    _log("=" * 72)
    rng = np.random.default_rng(VAL_SEED)
    n = 350

    _log("")
    _log("(1) NULL: beta = 0 under MA(k-1) errors. t should be ~N(0,1) and the")
    _log("    rejection rate at ALPHA=0.025 two-sided should be ~2.5%.")
    rows = []
    for k in HORIZONS:
        tn, tw, rej_nw, rej_ols = [], [], 0, 0
        for _ in range(VAL_REPS):
            F = rng.uniform(-1, 1, size=n)
            y = _ma_errors(rng, n, k, 1.0)
            X = np.column_stack([np.ones(n), F])
            b, se = nw_ols(y, X, nw_lag(k))
            t = b[1] / se[1]
            tn.append(t)
            rej_nw += abs(t) > Z_ALPHA_2SIDED
            b2, se2 = nw_ols(y, X, 0)          # naive OLS, for contrast
            t2 = b2[1] / se2[1]
            tw.append(t2)
            rej_ols += abs(t2) > Z_ALPHA_2SIDED
        rows.append(dict(k=k, sd_t_nw=round(float(np.std(tn)), 3),
                         rej_nw=round(rej_nw / VAL_REPS, 4),
                         sd_t_ols=round(float(np.std(tw)), 3),
                         rej_ols_no_hac=round(rej_ols / VAL_REPS, 4)))
    null = pd.DataFrame(rows)
    print(null.to_string(index=False), flush=True)

    _log("")
    _log("(2) PLANTED beta: recovery and coverage of the NW interval.")
    rows = []
    for k in HORIZONS:
        for beta in (-1.0, -0.25):
            bs, cov = [], 0
            for _ in range(400):
                F = rng.uniform(-1, 1, size=n)
                y = beta * F + _ma_errors(rng, n, k, 1.0)
                X = np.column_stack([np.ones(n), F])
                b, se = nw_ols(y, X, nw_lag(k))
                bs.append(b[1])
                cov += abs(b[1] - beta) <= Z_ALPHA_2SIDED * se[1]
            rows.append(dict(k=k, beta_true=beta, beta_mean=round(float(np.mean(bs)), 4),
                             bias=round(float(np.mean(bs)) - beta, 4),
                             coverage_97_5=round(cov / 400, 3)))
    plant = pd.DataFrame(rows)
    print(plant.to_string(index=False), flush=True)

    _log("")
    _log("(3) EDGE machinery: a planted directional edge of known size in bp,")
    _log("    recovered per trade, with no-position days carried as zeros.")
    rows = []
    for k in HORIZONS:
        for edge in (0.0, 0.5):
            es, ses, cov = [], [], 0
            for _ in range(400):
                F = rng.choice([-1.0, 0.0, 1.0], size=n, p=[0.45, 0.10, 0.45])
                y = -np.sign(F) * edge + _ma_errors(rng, n, k, 1.0)
                pnl = -np.sign(F) * y                      # 0 where F == 0
                m_all, se_all = nw_mean(pnl, nw_lag(k))
                ntr = int((F != 0).sum())
                scale = n / max(ntr, 1)
                es.append(m_all * scale)
                ses.append(se_all * scale)
                cov += abs(m_all * scale - edge) <= Z_ALPHA_2SIDED * se_all * scale
            rows.append(dict(k=k, edge_true=edge,
                             edge_mean=round(float(np.mean(es)), 4),
                             bias=round(float(np.mean(es)) - edge, 4),
                             se_mean=round(float(np.mean(ses)), 4),
                             se_realised=round(float(np.std(es)), 4),
                             coverage_97_5=round(cov / 400, 3)))
    edge = pd.DataFrame(rows)
    print(edge.to_string(index=False), flush=True)

    _log("")
    _log("(4) NULL with a PERSISTENT regressor -- the case that actually needs")
    _log("    the HAC. With F iid, F_t*e_t is serially uncorrelated however")
    _log("    autocorrelated e is, so test (1) cannot tell NW from plain OLS.")
    _log("    An AR(1) F against MA(k-1) errors can, and an under-sized SE here")
    _log("    is exactly how a false positive would enter.")
    rows = []
    for k in (1, 3, 5):
        for rho in (0.0, 0.3, 0.6, 0.9):
            rej_nw = rej_ols = 0
            for _ in range(800):
                z = rng.normal(size=n)
                F = np.empty(n)
                F[0] = z[0]
                for i in range(1, n):
                    F[i] = rho * F[i - 1] + math.sqrt(1 - rho * rho) * z[i]
                y = _ma_errors(rng, n, k, 1.0)
                X = np.column_stack([np.ones(n), F])
                b, se = nw_ols(y, X, nw_lag(k))
                rej_nw += abs(b[1] / se[1]) > Z_ALPHA_2SIDED
                b2, se2 = nw_ols(y, X, 0)
                rej_ols += abs(b2[1] / se2[1]) > Z_ALPHA_2SIDED
            rows.append(dict(k=k, rho_F=rho, rej_nw=round(rej_nw / 800, 4),
                             rej_ols_no_hac=round(rej_ols / 800, 4)))
    persist = pd.DataFrame(rows)
    print(persist.to_string(index=False), flush=True)

    _log("")
    _log("(4b) THE FIX: the same null, judged against the SIZE-CORRECTED")
    _log("     critical value from null_crits(). Should land on 2.5%.")
    rows = []
    for k in (1, 3, 5):
        for rho in (0.0, 0.6, 0.9):
            cb, ce = null_crits(n, k, rho)
            rej_b = rej_e = 0
            for _ in range(800):
                z = rng.normal(size=n)
                F = np.empty(n)
                F[0] = z[0]
                for i in range(1, n):
                    F[i] = rho * F[i - 1] + math.sqrt(1 - rho * rho) * z[i]
                y = _ma_errors(rng, n, k, 1.0)
                b, se = nw_ols(y, np.column_stack([np.ones(n), F]), nw_lag(k))
                rej_b += abs(b[1] / se[1]) > cb
                m, sm = nw_mean(-np.sign(F) * y, nw_lag(k))
                rej_e += abs(m / sm) > ce
            rows.append(dict(k=k, rho_F=rho, crit_beta=round(cb, 3),
                             crit_edge=round(ce, 3),
                             rej_beta_corrected=round(rej_b / 800, 4),
                             rej_edge_corrected=round(rej_e / 800, 4)))
    corrected = pd.DataFrame(rows)
    print(corrected.to_string(index=False), flush=True)

    _log("")
    _log("(5) MDE: an effect exactly at the reported MDE should be detected")
    _log("    ~80% of the time. The reference SE is taken from the SAME P&L")
    _log("    construction the real run reports it from -- -sign(F)*y, not the")
    _log("    raw forward change. Those differ by a factor of ~sqrt(k): an iid")
    _log("    position sign scrambles the overlap, a persistent one does not,")
    _log("    so the MDE is checked at both rho = 0 and rho = 0.6.")
    rows = []
    for k in (1, 3, 5):
        for rho in (0.0, 0.6):
            def draw_F():
                z = rng.normal(size=n)
                F = np.empty(n)
                F[0] = z[0]
                for i in range(1, n):
                    F[i] = rho * F[i - 1] + math.sqrt(1 - rho * rho) * z[i]
                return np.sign(F)
            _cb, ce = null_crits(n, k, rho)
            ses = []
            for _ in range(200):
                F = draw_F()
                ses.append(nw_mean(-F * _ma_errors(rng, n, k, 1.0), nw_lag(k))[1])
            mde_v = (ce + Z_POWER) * float(np.mean(ses))
            hits = 0
            for _ in range(600):
                F = draw_F()
                y = -F * mde_v + _ma_errors(rng, n, k, 1.0)
                m, se = nw_mean(-F * y, nw_lag(k))
                hits += abs(m / se) > ce
            rows.append(dict(k=k, rho_F=rho, se_pnl=round(float(np.mean(ses)), 4),
                             crit_edge=round(ce, 3), mde_bps=round(mde_v, 4),
                             power=round(hits / 600, 3)))
    mde = pd.DataFrame(rows)
    print(mde.to_string(index=False), flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "s1_validate.txt", "w") as fh:
        fh.write("S1 machinery validation -- planted answers, before the real run\n\n")
        fh.write("(1) null, beta=0 under MA(k-1); rejection at 2.5% expected\n")
        fh.write(null.to_string(index=False) + "\n\n")
        fh.write("(2) planted beta recovery / NW coverage (97.5% nominal)\n")
        fh.write(plant.to_string(index=False) + "\n\n")
        fh.write("(3) planted edge per trade, zeros on no-position days\n")
        fh.write(edge.to_string(index=False) + "\n\n")
        fh.write("(4) null with an AR(1) regressor -- NW vs no-HAC, 2.5% expected.\n")
        fh.write("    THE FAILURE THIS STAGE EXISTS TO CATCH: both are liberal.\n")
        fh.write(persist.to_string(index=False) + "\n\n")
        fh.write("(4b) the same null against the size-corrected critical value\n")
        fh.write(corrected.to_string(index=False) + "\n\n")
        fh.write("(5) power at the size-corrected MDE (0.80 expected)\n")
        fh.write(mde.to_string(index=False) + "\n")
    _log(f"wrote {OUT / 's1_validate.txt'}")


# =========================================================================
# stage: run -- the one real pass
# =========================================================================

def build_panel(signed: pd.DataFrame, closes: pd.DataFrame,
                *, flow_col: str = "d") -> pd.DataFrame:
    """One row per (tenor, venue, close-day): F, the closes, and the forwards.

    Gapless in close-day within a bucket -- every close-day the bucket's tenor
    has a valid close is present, with ``F = 0`` and ``n_prints = 0`` where the
    window held nothing. The NW kernel is positional, so the gapless index is
    load-bearing rather than cosmetic.
    """
    frames = []
    for tenor in sorted(signed["tenor_label"].unique()):
        s = closes[tenor].dropna()
        if s.empty:
            continue
        days = pd.DatetimeIndex(s.index)
        g_t = signed[signed["tenor_label"].eq(tenor)].copy()
        g_t["j"] = assign_close_day(g_t["snap_et"], days)
        g_t = g_t[g_t["j"] >= 0]
        for venue in sorted(g_t["venue"].unique()):
            g = g_t[g_t["venue"].eq(venue)]
            w = g["notional"].to_numpy(float)
            num = pd.Series(w * g[flow_col].to_numpy(float)).groupby(g["j"].values).sum()
            den = pd.Series(w).groupby(g["j"].values).sum()
            cnt = g.groupby("j").size()
            panel = pd.DataFrame({"close_day": days, "close_bps": s.to_numpy(float)})
            panel["tenor"] = tenor
            panel["venue"] = venue
            panel["F"] = 0.0
            panel["n_prints"] = 0
            panel.loc[num.index, "F"] = (num / den).to_numpy(float)
            panel.loc[cnt.index, "n_prints"] = cnt.to_numpy(int)
            panel["net_notional"] = 0.0
            panel.loc[num.index, "net_notional"] = num.to_numpy(float)
            for k in HORIZONS:
                panel[f"fwd{k}"] = panel["close_bps"].shift(-k) - panel["close_bps"]
            frames.append(panel)
    return pd.concat(frames, ignore_index=True)


def estimate(panel: pd.DataFrame, cost: pd.DataFrame, *, label: str) -> pd.DataFrame:
    rows = []
    for (tenor, venue), g in panel.groupby(["tenor", "venue"], sort=True):
        g = g.sort_values("close_day").reset_index(drop=True)
        cr = cost.loc[(tenor, venue)] if (tenor, venue) in cost.index else None
        kill_ceiling = float(cr["kill_threshold_used_bps"]) if cr is not None else np.nan
        # COSTS.md §5.2: D2C has no lattice of its own; it inherits the
        # same-tenor D2D increment as the floor of its bracket.
        floor_src = (tenor, DIAGNOSTIC_VENUE)
        tick = (float(cost.loc[floor_src, "tick_bps"])
                if floor_src in cost.index else np.nan)
        kill_floor = 2.0 * tick if np.isfinite(tick) else np.nan
        for k in HORIZONS:
            sub = g[g[f"fwd{k}"].notna()].copy()
            if len(sub) < 20:
                continue
            # gapless within the surviving contiguous block
            y = sub[f"fwd{k}"].to_numpy(float)
            F = sub["F"].to_numpy(float)
            lag = nw_lag(k)
            b, se = nw_ols(y, np.column_stack([np.ones(len(y)), F]), lag)
            beta, beta_se = float(b[1]), float(se[1])
            t = beta / beta_se if beta_se > 0 else np.nan
            p = two_sided_p(t)

            pos = np.sign(F)
            pnl = -pos * y                     # long the fall when F > 0
            n_all = len(pnl)
            n_tr = int((pos != 0).sum())
            m_all, se_all = nw_mean(pnl, lag)
            scale = n_all / max(n_tr, 1)
            edge, edge_se = m_all * scale, se_all * scale
            t_e = edge / edge_se if edge_se > 0 else np.nan
            p_e = two_sided_p(t_e)
            hit = float((pnl[pos != 0] > 0).mean()) if n_tr else np.nan

            # Size correction. rho is the regressor's own lag-1
            # autocorrelation: observable without the target, so calibrating
            # on it looks at nothing the hypothesis is about.
            rho = float(pd.Series(F).autocorr(1)) if np.std(F) > 0 else 0.0
            if not np.isfinite(rho):
                rho = 0.0
            crit_b, crit_e = null_crits(n_all, k, rho)
            sig_beta = abs(t) > crit_b
            sig_edge = abs(t_e) > crit_e
            mde = (crit_e + Z_POWER) * edge_se

            usable = int((sub["n_prints"] > 0).sum())
            sign_ok = (np.sign(beta) == EXPECTED_BETA_SIGN)
            upper = edge + crit_e * edge_se

            if usable < MIN_BUCKET_DAYS:
                verdict = "UNINFORMATIVE_COVERAGE"
            elif (not sign_ok) and sig_beta:
                verdict = "WRONG_SIGN"
            elif np.isfinite(kill_ceiling) and edge >= kill_ceiling and sig_edge and edge > 0:
                verdict = "PASS"
            elif np.isfinite(kill_floor) and upper < kill_floor:
                verdict = "DEAD"
            elif np.isfinite(kill_ceiling) and mde > kill_ceiling:
                verdict = "UNINFORMATIVE_POWER"
            else:
                verdict = "AMBIGUOUS"

            rows.append(dict(
                spec=label, tenor=tenor, venue=venue, k=k,
                n_days=n_all, usable_bucket_days=usable, n_trades=n_tr,
                nw_lag=lag, rho_F=rho, crit_beta=crit_b, crit_edge=crit_e,
                beta_bps_per_unit_F=beta, beta_se=beta_se, beta_t=t,
                beta_p_normal=p, beta_significant=bool(sig_beta),
                beta_sign_expected=EXPECTED_BETA_SIGN, sign_ok=bool(sign_ok),
                edge_bps_per_trade=edge, edge_se=edge_se, edge_t=t_e,
                edge_p_normal=p_e, edge_significant=bool(sig_edge),
                edge_upper_sizecorr=upper, mde_bps=mde, hit_rate=hit,
                mean_abs_F=float(np.abs(F[pos != 0]).mean()) if n_tr else np.nan,
                sd_fwd_bps=float(np.std(y, ddof=1)),
                kill_floor_bps=kill_floor, kill_ceiling_bps=kill_ceiling,
                mde_over_ceiling=mde / kill_ceiling if np.isfinite(kill_ceiling) else np.nan,
                verdict=verdict))
    return pd.DataFrame(rows)


def placebo_signs(signed: pd.DataFrame, mi: pd.DataFrame,
                  closes: pd.DataFrame) -> pd.DataFrame:
    """``d_placebo`` from the SAME clock minute one close-day earlier.

    The trade, its notional, its window and its tenor are untouched; only the
    mid it is signed against moves back one session. That removes the
    half-spread information and any same-day mid-error link at once.
    """
    out = []
    for tenor in sorted(signed["tenor_label"].unique()):
        s = closes[tenor].dropna()
        days = pd.DatetimeIndex(s.index)
        g = signed[signed["tenor_label"].eq(tenor)].copy()
        g["j"] = assign_close_day(g["snap_et"], days)
        g = g[g["j"] >= 1]
        gap = (days.to_numpy()[g["j"].to_numpy()]
               - days.to_numpy()[g["j"].to_numpy() - 1])
        g["snap_prev"] = g["snap_et"].to_numpy() - gap
        ser = mi[tenor].dropna().sort_index().rename("mi01_prev").reset_index()
        ser.columns = ["snap_prev", "mi01_prev"]
        g = g.sort_values("snap_prev")
        g = pd.merge_asof(g, ser, on="snap_prev", direction="backward",
                          tolerance=MI01_TOLERANCE)
        out.append(g)
    g = pd.concat(out, ignore_index=True)
    g = g.dropna(subset=["mi01_prev"])
    g["d"] = np.sign(g["pts_bp"].to_numpy(float) - g["mi01_prev"].to_numpy(float))
    return g[g["d"] != 0]


def stage_run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _log("S1: loading the print cache and the pre-measured b0 / hurdles")
    prints = load_prints()
    cost = load_b0_and_hurdles()
    _log(f"S1: {len(prints)} {FAMILY} packages with a usable deviation")

    signed, audit = sign_prints(prints, cost)
    ad = pd.DataFrame(audit)
    print(ad.to_string(index=False), flush=True)
    ad.to_csv(OUT / "s1_population.csv", index=False)

    mi = load_mi01()
    closes = daily_closes(mi)
    _log(f"S1: MI01 closes {closes.shape}, {closes.index.min().date()} .. "
         f"{closes.index.max().date()}; per-tenor valid closes "
         f"{closes.notna().sum().to_dict()}")

    panel = build_panel(signed, closes)
    panel.to_parquet(CACHE / "s1_panel.parquet", index=False)
    _log(f"S1: panel {panel.shape} -> {CACHE / 's1_panel.parquet'}")

    res = estimate(panel, cost, label="primary")

    _log("")
    _log(f"PLACEBO: {PLACEBO_NAME}")
    pl = placebo_signs(signed, mi, closes)
    _log(f"S1 placebo: {len(pl)} of {len(signed)} prints re-signed")
    ppanel = build_panel(pl, closes)
    pres = estimate(ppanel, cost, label="placebo")

    allres = pd.concat([res, pres], ignore_index=True)
    allres.to_csv(OUT / "s1_results.csv", index=False)
    _log(f"wrote {OUT / 's1_results.csv'} ({len(allres)} rows)")

    show = ["tenor", "venue", "k", "usable_bucket_days", "n_trades", "rho_F",
            "beta_bps_per_unit_F", "beta_t", "beta_p_normal", "crit_beta",
            "edge_bps_per_trade", "edge_se", "edge_t", "mde_bps",
            "kill_floor_bps", "kill_ceiling_bps", "hit_rate", "verdict"]
    for lab in ("primary", "placebo"):
        for venue in (PRIMARY_VENUE, DIAGNOSTIC_VENUE):
            sub = allres[allres.spec.eq(lab) & allres.venue.eq(venue)]
            if sub.empty:
                continue
            _log("")
            _log(f"--- {lab.upper()} / {venue} ---")
            print(sub[show].round(4).to_string(index=False), flush=True)


def stage_plumbing() -> None:
    """End-to-end known-answer test of the alignment, and the oracle ceiling.

    The contemporaneous correlation between ``F`` and the same-day close-to-close
    move is ~0.05 here, which cannot distinguish "the day index is off" from "the
    flow is noise" -- so it is not used as the alignment check. This is: replace
    each print's direction with ``-sign(close(t+1) - close(t))`` for its OWN
    close-day. Under the hypothesis's own convention (``F > 0`` predicts a fall)
    a perfect oracle must return a large NEGATIVE beta, hit rate 1.0, and an edge
    equal to the mean absolute daily move. Repeating it one day stale must
    collapse to ~0. Together those pin the day index, the window, the sign
    convention and the edge arithmetic at once.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    prints = load_prints()
    cost = load_b0_and_hurdles()
    signed, _ = sign_prints(prints, cost)
    mi = load_mi01()
    closes = daily_closes(mi)
    lines = []

    for tag, stale in (("oracle_same_day", 0), ("oracle_one_day_stale", 1)):
        out = []
        for tenor in TENORS:
            s = closes[tenor].dropna()
            days = pd.DatetimeIndex(s.index)
            v = pd.Series(s.to_numpy(float))
            fwd1 = v.shift(-1) - v
            g = signed[signed["tenor_label"].eq(tenor)].copy()
            g["j"] = assign_close_day(g["snap_et"], days)
            g = g[g["j"] >= 0]
            src = (g["j"] - stale).clip(lower=0)
            g["d"] = -np.sign(fwd1.reindex(src).to_numpy())
            out.append(g.dropna(subset=["d"]))
        o = pd.concat(out, ignore_index=True)
        o = o[o["d"] != 0]
        res = estimate(build_panel(o, closes), cost, label=tag)
        sub = res[res["venue"].eq(PRIMARY_VENUE) & res["k"].eq(1)][
            ["tenor", "beta_bps_per_unit_F", "beta_t", "edge_bps_per_trade",
             "hit_rate"]]
        lines += [f"--- {tag} (k=1, {PRIMARY_VENUE}) ---",
                  sub.round(4).to_string(index=False), ""]
        _log(f"{tag}: done")

    ref = {t: float(np.abs(np.diff(closes[t].dropna().to_numpy(float))).mean())
           for t in TENORS}
    lines += ["reference: mean |close-to-close move| per tenor, bp",
              "  " + "  ".join(f"{t}={v:.3f}" for t, v in ref.items()), ""]

    rows = []
    for tenor in TENORS:
        s = closes[tenor].dropna().to_numpy(float)
        for k in HORIZONS:
            d = s[k:] - s[:-k]
            orc = float(np.abs(d).mean())
            for venue in (PRIMARY_VENUE, DIAGNOSTIC_VENUE):
                if (tenor, venue) not in cost.index:
                    continue
                kt = float(cost.loc[(tenor, venue), "kill_threshold_used_bps"])
                rows.append(dict(tenor=tenor, venue=venue, k=k,
                                 sd_fwd_bps=d.std(ddof=1), oracle_edge_bps=orc,
                                 kill_ceiling_bps=kt, oracle_over_hurdle=orc / kt,
                                 min_hit_rate_to_clear=0.5 * (1 + kt / orc)))
    oc = pd.DataFrame(rows)
    oc.to_csv(OUT / "s1_oracle_ceiling.csv", index=False)
    lines += ["MAXIMUM ATTAINABLE EDGE -- a perfect k-day oracle vs the hurdle.",
              "oracle_over_hurdle < 1 means NO signal of any strength can clear.",
              oc[oc["tenor"].isin(["5Y", "10Y", "30Y"])].round(3).to_string(index=False)]
    txt = "\n".join(lines)
    print(txt, flush=True)
    with open(OUT / "s1_plumbing.txt", "w") as fh:
        fh.write("S1 end-to-end plumbing, known answers\n\n" + txt + "\n")
    _log(f"wrote {OUT / 's1_plumbing.txt'} and {OUT / 's1_oracle_ceiling.csv'}")


def main() -> None:
    stages = {"mi01": stage_mi01, "validate": stage_validate,
              "plumbing": stage_plumbing, "run": stage_run}
    if len(sys.argv) < 2 or sys.argv[1] not in stages:
        print(f"usage: {sys.argv[0]} {{{'|'.join(stages)}}}")
        raise SystemExit(2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        stages[sys.argv[1]]()


if __name__ == "__main__":
    main()
