"""Measure the round-trip transaction cost of the two instruments S1 and S2 trade.

The pre-registration (``docs/dealer_direction/signals/S_PREREG.md``, committed at
``5ec6a7dd``) states its kill rule against a *measured* cost, so this runs before
any signal is estimated. Nothing here reads the hold-out: every query and every
frame is bounded by :data:`DESIGN_START` .. :data:`DESIGN_END`.

WHAT IS BEING MEASURED
----------------------

For a print with observed deviation ``x = P_traded - P_mid``, the dealer-direction
design (``docs/dealer_direction/DESIGN.md`` §1.1) models

    x | customer paid      ~ N(b0 + h, s^2)
    x | customer received  ~ N(b0 - h, s^2)

so ``h`` **is** the dealer-to-client half-spread and ``s`` is our mid measurement
error. ``SDRUtils/dealer_direction/probability.fit_mixture`` fits ``(b0, h, s)``
by EM with the weight pinned at 0.5. That fit is the instrument; it is reused
unchanged rather than reimplemented, because reimplementing it would replace a
validated estimator with an unvalidated one.

    round trip = 2h            (cross the bid-offer once in, once out)
    kill threshold = 2 x round trip = 4h      (S_PREREG §1)

TWO INSTRUMENTS
---------------

* **S1, swap spread.** ``x = package_transaction_spread`` (converted to bp) minus
  the contemporaneous Citi MI01 swap spread for the same tenor. No curve is
  involved: both sides are already spreads in bp.
* **S2, outright SOFR swap.** ``x = printed fixed rate - repriced par mid``, in bp,
  through the production ``midprice.UnitRepricer`` on the Citi minute curve under
  the production T-1min snapshot rule.

WHY THE ANSWER IS A BRACKET AND NOT ``2h``
------------------------------------------

The fit is run first and reports, on every S1 bucket and with its own
diagnostics, that it cannot separate the two components: ``h/s`` of 0.03
against a floor of 0.05, ``LEPTOKURTIC_MOMENT_CHECK_FAILED``, and an ``h``
sitting exactly on ``MIN_SEPARATION * s``. :func:`stage_validate` measures why
and how badly: ``fit_mixture`` is unbiased to 2.4% when its reported separation
is at or above 1, and biased **down** by up to 80% below it. Down is the one
direction a kill-rule cost may not be wrong in, so a floored ``h`` is reported
as unresolved rather than used.

What replaces it is not another fit. It is two bounds that need no model:

* **floor -- the quote lattice.** ~100% of interdealer spreadover prints land
  exactly on a 0.125 bp grid, and the 90th percentile of consecutive-print
  changes is exactly one grid step. Bid and offer are at least one increment
  apart, so one increment is a floor on the round trip. This is the task's own
  cross-check clause -- "the observed bid-offer in the tape's own D2D prints" --
  made precise, promoted to load-bearing because the primary instrument
  declared itself unresolved.
* **ceiling -- the deviation dispersion.** The model's own second moment is
  ``m2 = h^2 + s^2`` with both terms non-negative, so ``2 sqrt(m2)`` bounds the
  round trip from above whatever the split. Trimmed at the 6 MAD the fit trims
  at.

Reported alongside, as **diagnostics only**: Roll (1984)
``sqrt(-Cov(dp_t, dp_t-1))``, ``mean|dp|`` over same-minute pairs, and the
repo's incumbent ``median|dp|/2``. All three assume the sides of consecutive
prints are independent draws, and on this population they are not -- a block
prints as several clips at one price, so 5-83% of consecutive differences are
exactly zero (``frac_dp_zero``). That biases Roll and ``mean|dp|`` DOWN, while
isolated misprints bias Roll UP, and ``median|dp|/2`` is outright degenerate
where the modal difference is zero. None of the three sets a cost.

``round_trip_used_bps`` is therefore the top of the bracket: the larger of the
two numbers that disagree, which is what the instruction asks for and the side
a kill rule has to be wrong on.

Stages, run in order::

    validate   estimators against known answers  (must pass before anything else)
    s1         build S1 deviations   -> CACHE/s1_dev.parquet
    s2         build S2 deviations   -> CACHE/s2/<date>.parquet  (resumable)
    fit        fit, bound, cross-check -> out/costs.csv
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"   # never open Excel

import argparse
import datetime
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd

REPO = "C:/Users/chris/clee/ARBS-dd"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

CACHE = pathlib.Path("D:/dd_signals_cache")
OUT = pathlib.Path(REPO) / "BT" / "dd_signals" / "out"

# --------------------------------------------------------------------------
# The pre-registered sample. NOT NEGOTIABLE AND NOT PARAMETERISED.
# --------------------------------------------------------------------------
#: S_PREREG §2. The hold-out (2025-09-01 .. 2026-08-07) is not opened in this
#: run -- not for a fit, not for a coverage count. Deliberately a module
#: constant with no CLI override, so a hold-out date cannot arrive by argument.
DESIGN_START = "2024-03-01"
DESIGN_END = "2025-08-31"

#: Every 3rd trading day of the design sample gets repriced for S2. Fixed
#: before any pricing ran (see the header of ``out/costs.csv``): the full
#: 376-day pass is 3.6 h at the measured 18.6 ms/leg and a third of it is
#: 1.2 h, while the thinnest D2C tenor band still lands ~5,700 prints against
#: the ``MIN_BUCKET_N = 800`` floor the fit needs.
S2_DAY_STRIDE = 3

#: MI01 carries these and only these. ``1M``/``3M``/``6M``/``1Y`` are on the
#: axis but no spreadover prints at them, so the intersection is the benchmark set.
S1_TENORS = ("2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")

#: Raw ``package_transaction_spread`` -> bp. The CFTC field carries no notation
#: flag and the tape passes it through unmodified, so three notations coexist
#: on this population; see :func:`pts_to_bp`.
PTS_MULTIPLIERS = {"DECIMAL": 1e4, "PERCENT": 1e2, "BP": 1.0}

#: A USD swap spread is somewhere between 2 and 200 bp in absolute value over
#: this window at these tenors. The three notations are 100x apart, so this
#: window selects exactly one of them for all but a measure-zero set of values
#: (two multipliers both land inside only for |raw| in {0.02, 2.0}), and it
#: cannot distort sub-bp structure: the classification is a decade, the
#: quantity being measured is a tenth of a bp.
PLAUSIBLE_SPREAD_BP = (2.0, 200.0)

#: How stale the MI01 mid may be. The production in-session snapshot rule is
#: 1 minute (``snapshot.IN_SESSION_MAX_LAG``); MI01 prints ~1,300 of the 1,320
#: minutes in its 01:00-22:59 ET session, so 2 minutes covers the tag's own
#: gaps without admitting a stale quote.
MI01_TOLERANCE = pd.Timedelta("2min")

#: Day-blocked bootstrap. Resampling DAYS, not prints: S_PREREG §4 says N_eff
#: is trading days, and a print-level bootstrap would report a standard error
#: 30x too small on a bucket with 30 prints a day.
BOOT_REPS = 400
BOOT_SEED = 20260811


def _log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------

def connect():
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    return psycopg2.connect(resolve_pg_url())


def rd(conn, sql, params=None) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")           # pandas' non-SQLAlchemy notice
        return pd.read_sql(sql, conn, params=params)


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------

def pts_to_bp(v) -> tuple[str, float]:
    """``(notation, bp)`` for one raw ``package_transaction_spread``.

    Returns ``("NONE", nan)`` when no multiplier lands in
    :data:`PLAUSIBLE_SPREAD_BP` and ``("AMBIGUOUS", nan)`` when two do. Both are
    refusals, counted and dropped -- guessing a notation is how a 100x error
    enters a cost number, and this repo has already paid for one factor of two.
    """
    if v is None or (isinstance(v, float) and v != v):
        return "NONE", float("nan")
    v = float(v)
    lo, hi = PLAUSIBLE_SPREAD_BP
    hits = [k for k, m in PTS_MULTIPLIERS.items() if lo <= abs(v) * m <= hi]
    if len(hits) == 1:
        return hits[0], v * PTS_MULTIPLIERS[hits[0]]
    return ("AMBIGUOUS" if hits else "NONE"), float("nan")


# --------------------------------------------------------------------------
# the independent estimator: consecutive-print tick, no mid involved
# --------------------------------------------------------------------------

def _pair_diffs(df: pd.DataFrame, *, price_col: str, time_col: str,
                pair_cols: list[str], max_gap_min: float | None = None):
    """Consecutive-print first differences within each ``pair_cols`` group.

    Pairing is within an EXACT instrument (tenor label), not a tenor band: two
    consecutive prints at 9Y and 12Y differ by the curve as well as by the
    spread, and that difference would be read as bid-offer.
    """
    from SDRUtils.stir_flow import config

    gap = float(config.TICK_PAIR_MAX_GAP_MIN if max_gap_min is None else max_gap_min)
    for key, g in df.groupby(pair_cols, dropna=False, sort=True):
        g = g.sort_values(time_col)
        dt_min = pd.to_datetime(g[time_col]).diff().dt.total_seconds() / 60.0
        d = g[price_col].diff()
        ok = (dt_min <= gap) & d.notna()
        if ok.sum() >= 2:
            yield key, d[ok].to_numpy(float), g.loc[ok, price_col].to_numpy(float)


def roll_half_spread(diffs: np.ndarray) -> float:
    """Roll (1984): ``h = sqrt(-Cov(Δp_t, Δp_{t-1}))``. No mid, no curve.

    Under the SAME model the mixture fit assumes -- an efficient price that is
    a random walk, and a side that is i.i.d. symmetric ±1 -- the first-order
    autocovariance of transaction-price changes is exactly ``-h^2``, because the
    bid-offer bounce is the only source of negative serial dependence. So this
    reads the half-spread off the print stream alone and cannot inherit an
    error from the Citi curve or from MI01, which is what makes it the right
    second opinion.

    Two known biases, both measured in :func:`stage_validate`:

    * **Up.** Any i.i.d. print-level noise that is not bid-offer -- an
      off-the-run bond behind a spreadover, a 9.75Y print pooled with a 10Y --
      contributes to ``-γ1`` identically to the spread. So this is an UPPER
      bound on ``h`` on a heterogeneous population, which is the safe direction
      for a cost.
    * **Undefined.** A trending mid or one-sided order flow makes ``γ1``
      positive and the square root imaginary; that returns NaN rather than a
      floor of zero, because zero would read as "measured, and free".
    """
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d)]
    if d.size < 30:
        return float("nan")
    g1 = float(np.cov(d[:-1], d[1:], ddof=1)[0, 1])
    return float(np.sqrt(-g1)) if g1 < 0 else float("nan")


#: The static-mid pairing window. ``mean |dp|`` equals ``h`` exactly when the
#: mid does not move between the two prints, and the production window of
#: ``TICK_PAIR_MAX_GAP_MIN = 60`` minutes is far from that for a swap RATE: a
#: 10y SOFR rate moves of order a basis point an hour, which is several times
#: the half-spread being measured, so the 60-minute reading is mostly drift.
#: One minute is the shortest window the tape's own timestamp resolution
#: supports and leaves a drift contribution an order of magnitude below ``h``.
#: Both windows are reported; neither is chosen after seeing the answer.
SAME_MINUTE_GAP_MIN = 1.0


def mean_abs_half_spread(diffs: np.ndarray) -> float:
    """``mean |Δp|`` -- equal to ``h`` exactly when the mid does not move.

    With a static mid and i.i.d. sides, ``|Δp|`` is ``0`` or ``2h`` with equal
    probability, so its MEAN is ``h``. (Its MEDIAN is a coin flip between ``0``
    and ``2h`` and is therefore degenerate -- which is what
    ``probability._independent_half_spread``'s ``median_tick / 2`` computes, and
    why it is not used here. :func:`stage_validate` shows the degeneracy.)
    Any mid movement adds to it, so this is a strict UPPER bound on ``h``.
    """
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d)]
    return float(np.mean(np.abs(d))) if d.size >= 30 else float("nan")


def median_tick_half_spread(diffs: np.ndarray) -> float:
    """``median |Δp| / 2`` -- the repo's incumbent rule, reported for comparison."""
    d = np.asarray(diffs, float)
    d = d[np.isfinite(d)]
    return float(np.median(np.abs(d)) / 2.0) if d.size >= 30 else float("nan")


#: Candidate quote increments, searched coarsest-first. Fractions of a bp that
#: a rates desk actually quotes; 1/16 bp is included only so that a finer grid
#: than 1/8 would be visible rather than silently rounded up to it.
TICK_CANDIDATES = (1.0, 0.5, 0.25, 0.125, 0.0625)

#: A grid is only claimed when this share of prints lands on it. High, because
#: the whole value of the lattice reading is that it is not a fit: a grid that
#: 80% of prints obey is a habit, not an increment.
LATTICE_HIT = 0.99


def detect_tick(prices, *, hit: float = LATTICE_HIT) -> tuple[float, float]:
    """``(tick, hit_rate)`` -- the COARSEST grid that ``hit`` of prints land on.

    Coarsest-first, because every price on a 0.125 grid is also on a 0.0625 one:
    searching fine-first would always return the finest candidate. The returned
    tick is the market's quote increment, read off the prints with no model and
    no mid.

    A round trip cannot cost less than one increment -- the bid and the offer
    are at least one apart -- so ``tick`` is a FLOOR on the round-trip cost, and
    ``tick / 2`` a floor on ``h``.
    """
    p = np.asarray(prices, float)
    p = p[np.isfinite(p)]
    if p.size < 100:
        return float("nan"), float("nan")
    for t in TICK_CANDIDATES:
        rate = float(np.mean(np.abs(np.round(p / t) * t - p) < 1e-6))
        if rate >= hit:
            return float(t), rate
    return float("nan"), float("nan")


def dispersion_ceiling(x, *, trim_k: float = 6.0) -> float:
    """``sqrt(m2)`` of the trimmed deviations -- a model-free CEILING on ``h``.

    The mixture model says the deviation's second central moment is exactly
    ``h^2 + s^2``. Both terms are non-negative, so ``h <= sqrt(m2)`` whatever
    the split, and ``2 sqrt(m2)`` bounds the round trip from above without
    identifying anything. Trimmed at the same 6 MAD the fit trims at, because
    untrimmed ``m2`` on this tape is set by a handful of 100 bp misprints and
    would bound nothing.

    This is the number that matters when the fit cannot separate: it says how
    large the cost could be, which is the side a kill rule must be wrong on.
    """
    v = np.asarray(x, float)
    v = v[np.isfinite(v)]
    if v.size < 30:
        return float("nan")
    med = np.median(v)
    mad = 1.4826 * np.median(np.abs(v - med))
    vt = v[np.abs(v - med) <= trim_k * mad] if mad > 0 else v
    return float(np.std(vt, ddof=1))


def print_stream_estimates(df: pd.DataFrame, *, price_col: str, time_col: str,
                           pair_cols: list[str], bucket_cols: list[str]) -> pd.DataFrame:
    """All three mid-free estimators per bucket, pairing inside ``pair_cols``.

    ``pair_cols`` must include the day and the exact instrument; ``bucket_cols``
    is the coarser reporting key the differences are pooled to.
    """
    idx = [pair_cols.index(c) for c in bucket_cols]

    def _pool(gap):
        out: dict[tuple, list[np.ndarray]] = {}
        for key, d, _px in _pair_diffs(df, price_col=price_col, time_col=time_col,
                                       pair_cols=pair_cols, max_gap_min=gap):
            out.setdefault(tuple(np.asarray(key, dtype=object)[idx]), []).append(d)
        return {k: np.concatenate(v) for k, v in out.items()}

    wide = _pool(None)                 # the production 60-minute pairing window
    tight = _pool(SAME_MINUTE_GAP_MIN)  # a static-mid window
    rows = []
    for k, d in wide.items():
        ad = np.abs(d)
        dt = tight.get(k, np.empty(0))
        rows.append(dict(zip(bucket_cols, k)) | {
            "tick_pairs": int(d.size),
            "h_roll_bps": roll_half_spread(d),
            "h_meanabs_bps": mean_abs_half_spread(d),
            "h_medtick_bps": median_tick_half_spread(d),
            "frac_dp_zero": float(np.mean(ad < 1e-9)),
            "p90_abs_dp_bps": float(np.percentile(ad, 90)),
            "p99_abs_dp_bps": float(np.percentile(ad, 99)),
            "pairs_1min": int(dt.size),
            "h_meanabs_1min_bps": mean_abs_half_spread(dt)})
    if not rows:
        return pd.DataFrame(columns=[*bucket_cols, *_EST_COLS])
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# stage: validate
# --------------------------------------------------------------------------

def stage_validate() -> None:
    """Both estimators against known answers, before either is believed.

    Three questions, each with an answer known in advance:

    1. Does ``fit_mixture`` recover an ``h`` that was put in? Run at the
       ``(h, s, n)`` combinations this data actually has.
    2. What does it return when there is NO spread (``h = 0``)? The answer must
       be recognisably a floor, not a small cost.
    3. How much does mid drift inflate the tick estimator? That number is the
       tolerance the cross-check gets read against.
    """
    from SDRUtils.dealer_direction import probability as P

    _log("VALIDATE 1/3 -- fit_mixture recovery of a known h")
    rng = np.random.default_rng(1234)
    rows = []
    for h in (0.05, 0.10, 0.25, 0.50):
        for s in (0.05, 0.10, 0.25):
            for n in (800, 3200, 12800):
                errs, seps = [], []
                for _ in range(40):
                    x, _paid = P.simulate(b0=0.02, h=h, s=s, n=n, rng=rng)
                    f = P.fit_mixture(x, bucket="SIM")
                    errs.append(f.h / h - 1.0)
                    seps.append(f.separation)
                e = np.asarray(errs)
                rows.append({"h_true": h, "s_true": s, "sep_true": h / s, "n": n,
                             "bias_pct": 100 * e.mean(),
                             "p90_abs_err_pct": 100 * np.percentile(np.abs(e), 90),
                             "sep_reported": float(np.median(seps))})
    rec = pd.DataFrame(rows)
    print(rec.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    good = rec.query("sep_reported >= 1.0")
    bad = rec.query("sep_reported < 1.0")
    print(f"  cells where the FIT ITSELF reports separation >= 1: {len(good)}/{len(rec)}; "
          f"worst p90 |error| there {good['p90_abs_err_pct'].max():.1f}%, "
          f"bias range [{good['bias_pct'].min():+.1f}%, {good['bias_pct'].max():+.1f}%]")
    print(f"  cells reporting separation < 1: bias range "
          f"[{bad['bias_pct'].min():+.1f}%, {bad['bias_pct'].max():+.1f}%] -- "
          "the failure is DOWNWARD, i.e. it argues the cost too low.")
    print("  => reported separation h/s >= 1 is the gate. Below it, h is a LOWER BOUND.")

    _log("VALIDATE 2/3 -- what the fit returns when there is NO spread (h=0)")
    rng = np.random.default_rng(99)
    z = []
    for _ in range(60):
        x = 0.02 + rng.normal(0.0, 0.10, 3200)
        f = P.fit_mixture(x, bucket="SIM_H0")
        z.append((f.h, f.s, tuple(f.flags)))
    hz = np.array([a for a, _b, _c in z])
    print(f"  h from a pure Gaussian (true h=0): median {np.median(hz):.4f} bp, "
          f"p90 {np.percentile(hz, 90):.4f} bp, max {hz.max():.4f} bp")
    print(f"  flags seen: {sorted({f for _a, _b, fl in z for f in fl})}")
    print("  => an h at or below this scale is NOISE, not a measured cost.")

    _log("VALIDATE 3/3 -- the three mid-free estimators against a known h, with drift")
    rng = np.random.default_rng(7)
    rows = []
    for h in (0.05, 0.10, 0.25):
        for mid_sd in (0.0, 0.01, 0.03, 0.10):     # bp per print interval
            for extra_noise in (0.0, 0.05):        # i.i.d. instrument heterogeneity
                n = 6000
                mid = np.cumsum(rng.normal(0.0, mid_sd, n))
                side = rng.choice([-1.0, 1.0], n)
                px = mid + side * h + rng.normal(0.0, extra_noise, n)
                d = np.diff(px)
                rows.append({"h_true": h, "mid_sd_per_print": mid_sd,
                             "iid_noise": extra_noise,
                             "roll": roll_half_spread(d),
                             "meanabs": mean_abs_half_spread(d),
                             "medtick": median_tick_half_spread(d),
                             "roll_ratio": roll_half_spread(d) / h})
    dr = pd.DataFrame(rows)
    print(dr.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    clean = dr.query("mid_sd_per_print > 0 and iid_noise == 0")
    print(f"  Roll ratio with a moving mid and no extra noise: "
          f"min {clean['roll_ratio'].min():.3f} max {clean['roll_ratio'].max():.3f}")
    print("  medtick is degenerate on a two-sided book (|dp| is 0 or 2h with p=1/2,")
    print("  so its median is a coin flip) -- which is what median_tick/2 computes.")

    _log("VALIDATE 4/5 -- the lattice detector against a known quote increment")
    rng = np.random.default_rng(31)
    rows = []
    for tick_true in (0.5, 0.25, 0.125, 0.0625):
        for off_grid in (0.0, 0.005, 0.02, 0.10):     # share of prints off the grid
            p = np.round(rng.normal(-40, 8, 8000) / tick_true) * tick_true
            k = rng.random(p.size) < off_grid
            p[k] += rng.normal(0, 0.3, int(k.sum()))
            det, hit = detect_tick(p)
            rows.append({"tick_true": tick_true, "off_grid_frac": off_grid,
                         "detected": det, "hit_rate": hit,
                         "ok": bool(det == tick_true) if off_grid <= 0.005
                         else bool(np.isnan(det) or det == tick_true)})
    lt = pd.DataFrame(rows)
    print(lt.to_string(index=False, float_format=lambda v: f"{v:8.4f}"))
    print(f"  detector correct or honestly-NaN in {lt['ok'].mean():.0%} of cells; "
          "it never returns a grid COARSER than the truth, which is what would "
          "overstate a floor.")

    _log("VALIDATE 5/5 -- the dispersion ceiling really is a ceiling on h")
    rng = np.random.default_rng(5)
    bad = 0
    for _ in range(200):
        h = float(rng.uniform(0.02, 0.6))
        s = float(rng.uniform(0.02, 0.6))
        x, _p = P.simulate(b0=float(rng.normal(0, 0.05)), h=h, s=s, n=5000, rng=rng)
        if dispersion_ceiling(x) < h:
            bad += 1
    print(f"  sqrt(m2_trimmed) < h_true in {bad}/200 draws "
          "(a 6-MAD trim removes a little of the mixture's own mass, so the "
          "bound is tight rather than loose when h >> s).")


# --------------------------------------------------------------------------
# stage: s1
# --------------------------------------------------------------------------

def _snap_et(row) -> pd.Timestamp:
    """The production T-1min instant, as a naive New York minute (MI01's clock)."""
    from SDRUtils.dealer_direction import snapshot

    try:
        ts, _field = snapshot.pricing_timestamp(row)
    except Exception:  # noqa: BLE001 - a row with no usable clock is dropped, counted
        return pd.NaT
    inst = snapshot.snap_instant(ts)
    if isinstance(inst, datetime.date) and not isinstance(inst, datetime.datetime):
        return pd.NaT                     # date-only #30; no intraday instant exists
    t = pd.Timestamp(inst)
    if t.tzinfo is None:
        return pd.NaT
    return t.tz_convert("America/New_York").tz_localize(None)


def stage_s1() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as ss
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    ss.set_force_offline(True)
    CACHE.mkdir(parents=True, exist_ok=True)

    _log("S1: pulling spread-package prints from the design window, month by month")
    # Chunked because a single 18-month read of this table returns "out of
    # memory for query result" through the pooler; see reference note on prod
    # reads. Each month is an independent bounded read, and every one of them
    # carries the design-window bound as well as its own.
    conn = connect()
    parts = []
    for per in pd.period_range(pd.Timestamp(DESIGN_START).to_period("M"),
                               pd.Timestamp(DESIGN_END).to_period("M"), freq="M"):
        a = max(per.start_time.date(), pd.Timestamp(DESIGN_START).date())
        b = min(per.end_time.date(), pd.Timestamp(DESIGN_END).date())
        p = rd(conn, f"""
            SELECT trade_id, package_id, as_of_date, venue, trade_type, tenor_label,
                   tenor_years, notional, is_block, is_capped,
                   package_transaction_spread AS pts,
                   execution_timestamp, original_execution_timestamp, event_timestamp,
                   event_timestamp_granularity, lifecycle_type
            FROM {LEGS_TABLE}
            WHERE as_of_date BETWEEN %(a)s AND %(b)s
              AND as_of_date BETWEEN %(d0)s AND %(d1)s
              AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow
              AND package_transaction_spread IS NOT NULL
              AND trade_type = ANY(%(tt)s)
              AND tenor_label = ANY(%(tl)s)""",
            {"a": str(a), "b": str(b), "d0": DESIGN_START, "d1": DESIGN_END,
             "tt": ["SPREADOVER", "MATCHED_MATURITY", "INVOICE"],
             "tl": list(S1_TENORS)})
        parts.append(p)
        _log(f"  {per}: {len(p)} legs")
    conn.close()
    legs = pd.concat(parts, ignore_index=True)
    _log(f"S1: {len(legs)} legs, {legs['package_id'].nunique()} packages")

    # One row per package. PTS is a package-level field replicated onto legs;
    # fitting on legs would pseudo-replicate a print and tighten h artificially.
    legs = legs.sort_values(["package_id", "trade_id"]).drop_duplicates("package_id")
    _log(f"S1: {len(legs)} after one-row-per-package")

    nk, bp = zip(*[pts_to_bp(v) for v in legs["pts"]])
    legs["notation"] = nk
    legs["pts_bp"] = bp
    _log(f"S1 notation: {legs['notation'].value_counts().to_dict()}")

    legs["snap_et"] = [_snap_et(r) for _, r in legs.iterrows()]
    _log(f"S1: snap resolved on {legs['snap_et'].notna().mean():.2%}")

    _log("S1: reading MI01 offline, month by month")
    mi_parts = []
    m0 = pd.Timestamp(DESIGN_START).to_period("M")
    m1 = pd.Timestamp(DESIGN_END).to_period("M")
    for per in pd.period_range(m0, m1, freq="M"):
        a = max(per.start_time, pd.Timestamp(DESIGN_START))
        b = min(per.end_time.normalize() + pd.Timedelta("23:59:00"),
                pd.Timestamp(DESIGN_END) + pd.Timedelta("23:59:00"))
        try:
            f = ss.swap_spread_history("USD_SOFR", S1_TENORS, start=a, end=b, freq="MI01")
        except Exception as exc:  # noqa: BLE001
            _log(f"  {per}: MI01 FAILED {type(exc).__name__}: {exc}")
            continue
        if f is not None and not f.empty:
            mi_parts.append(f)
        _log(f"  {per}: {0 if f is None else len(f)} minutes")
    mi = pd.concat(mi_parts).sort_index()
    mi = mi[~mi.index.duplicated(keep="first")]
    _log(f"S1: MI01 {mi.shape}, {mi.index.min()} .. {mi.index.max()}")

    d = legs.dropna(subset=["snap_et", "pts_bp"]).copy()
    parts = []
    for t, g in d.groupby("tenor_label"):
        if t not in mi.columns:
            continue
        s = mi[t].dropna().sort_index().rename("mi01_bp").reset_index()
        s.columns = ["snap_et", "mi01_bp"]
        g = g.sort_values("snap_et")
        m = pd.merge_asof(g, s, on="snap_et", direction="backward",
                          tolerance=MI01_TOLERANCE)
        parts.append(m)
    m = pd.concat(parts, ignore_index=True)
    _log(f"S1: MI01 matched on {m['mi01_bp'].notna().mean():.2%} of {len(m)}")
    m["deviation_bps"] = m["pts_bp"] - m["mi01_bp"]
    m["day"] = pd.to_datetime(m["as_of_date"])
    m.to_parquet(CACHE / "s1_dev.parquet", index=False)
    _log(f"S1: wrote {CACHE / 's1_dev.parquet'} ({len(m)} rows)")


# --------------------------------------------------------------------------
# stage: s2
# --------------------------------------------------------------------------

S2_SQL_FILTER = """
      AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow
      AND rate_index_clean='SOFR' AND trade_type='OUTRIGHT'
      AND coalesce(special_tenor_type,'STANDARD')='STANDARD'
      AND coalesce(abs(forward_start_years), 0) < 0.05
      AND coalesce(other_payment_ufro, 0) = 0
      AND fixed_rate IS NOT NULL AND effective_date IS NOT NULL
      AND expiration_date IS NOT NULL AND notional IS NOT NULL
"""
#: Spot-start, standard-tenor, on-market outright SOFR flow. That is the
#: instrument S2's signal would put on -- a par swap in a liquid tenor -- so it
#: is the population whose bid-offer is the relevant cost. An off-market swap
#: (one carrying an upfront) prints a rate that is not a quote, and a
#: forward-start or IMM-dated swap is a different instrument with its own
#: spread; including either would measure something S2 does not trade.


def s2_days() -> list[str]:
    conn = connect()
    days = rd(conn, f"""
        SELECT DISTINCT as_of_date FROM {_legs_table()}
        WHERE as_of_date BETWEEN %(d0)s AND %(d1)s {S2_SQL_FILTER}
        ORDER BY as_of_date""", {"d0": DESIGN_START, "d1": DESIGN_END})
    conn.close()
    all_days = [str(d) for d in days["as_of_date"]]
    return all_days[::S2_DAY_STRIDE]


def _legs_table() -> str:
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    return LEGS_TABLE


def stage_s2() -> None:
    from SDRUtils.dealer_direction import conventions, midprice, snapshot
    from SDRUtils.dealer_direction.types import Clocks, Unit

    outdir = CACHE / "s2"
    outdir.mkdir(parents=True, exist_ok=True)
    days = s2_days()
    todo = [d for d in days if not (outdir / f"{d}.parquet").exists()]
    _log(f"S2: {len(days)} sampled days (stride {S2_DAY_STRIDE}), {len(todo)} still to price")

    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    t_start = time.perf_counter()
    for k, day in enumerate(todo, 1):
        conn = connect()
        legs = rd(conn, f"""
            SELECT trade_id, package_id, as_of_date, rate_index_clean, venue,
                   execution_timestamp, original_execution_timestamp, event_timestamp,
                   event_timestamp_granularity, lifecycle_type,
                   effective_date, expiration_date, notional, fixed_rate,
                   tenor_years, tenor_label, is_capped, is_block
            FROM {_legs_table()}
            WHERE as_of_date = %(d)s {S2_SQL_FILTER}
            ORDER BY execution_timestamp, trade_id""", {"d": day})
        conn.close()

        recs = []
        with rep.day_scope():
            for _, r in legs.iterrows():
                try:
                    ts, field = snapshot.pricing_timestamp(r)
                except Exception:  # noqa: BLE001
                    recs.append({"trade_id": r["trade_id"], "failure": "NO_PRICING_CLOCK"})
                    continue
                unit = Unit(
                    unit_key=str(r["trade_id"]), kind="OUTRIGHT",
                    legs=pd.DataFrame([{
                        "trade_id": r["trade_id"],
                        "effective_date": r["effective_date"],
                        "expiration_date": r["expiration_date"],
                        "notional": r["notional"], "fixed_rate": r["fixed_rate"],
                        "is_capped": bool(r.get("is_capped") or False)}]),
                    package_id=r.get("package_id"), rate_index=r["rate_index_clean"],
                    as_of_date=pd.Timestamp(r["as_of_date"]).date(),
                    venue_class=r.get("venue") or "VENUE_UNKNOWN",
                    clocks=Clocks(pricing=ts, execution=r.get("execution_timestamp"),
                                  event=r.get("event_timestamp"),
                                  visibility=r.get("event_timestamp"),
                                  visibility_source="COST_MEASUREMENT"),
                    upfront=None)
                out = rep.price_unit(unit)
                base = {"trade_id": r["trade_id"], "as_of_date": day,
                        "venue": r["venue"], "tenor_years": r["tenor_years"],
                        "tenor_label": r["tenor_label"],
                        "is_block": bool(r.get("is_block") or False),
                        "notional": r["notional"], "clock_field": field,
                        "exec_ts": r["execution_timestamp"]}
                if out.failure is not None:
                    recs.append(base | {"failure": out.failure})
                    continue
                mid_pct = out.pricing.leg_mid_pct[0]
                traded_pct = float(r["fixed_rate"]) * 100.0
                dev = (conventions.structure_price([traded_pct], "OUTRIGHT", 1,
                                                   conventions.RULE_RATE)
                       - conventions.structure_price([mid_pct], "OUTRIGHT", 1,
                                                     conventions.RULE_RATE))
                recs.append(base | {"failure": None, "deviation_bps": dev,
                                    "traded_pct": traded_pct, "mid_pct": mid_pct,
                                    "snap_lag_s": out.pricing.snapshot_lag_seconds})
        df = pd.DataFrame(recs)
        df.to_parquet(outdir / f"{day}.parquet", index=False)
        el = time.perf_counter() - t_start
        _log(f"S2 [{k}/{len(todo)}] {day}: {len(df)} legs, "
             f"{int(df['failure'].isna().sum()) if 'failure' in df else 0} priced, "
             f"{el:.0f}s elapsed, eta {el / k * (len(todo) - k) / 60:.0f} min")


# --------------------------------------------------------------------------
# stage: fit
# --------------------------------------------------------------------------

def _boot_h(x: np.ndarray, days: np.ndarray, bucket: str) -> float:
    """Day-blocked bootstrap SE of ``h``. Resamples DAYS with replacement."""
    from SDRUtils.dealer_direction import probability as P

    rng = np.random.default_rng(BOOT_SEED)
    uniq = np.unique(days)
    by_day = {d: x[days == d] for d in uniq}
    hs = []
    for _ in range(BOOT_REPS):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        xb = np.concatenate([by_day[d] for d in pick])
        try:
            hs.append(P.fit_mixture(xb, bucket=bucket).h)
        except Exception:  # noqa: BLE001
            continue
    return float(np.std(hs, ddof=1)) if len(hs) > 20 else float("nan")


_EST_COLS = ("tick_pairs", "h_roll_bps", "h_meanabs_bps", "h_medtick_bps",
             "frac_dp_zero", "p90_abs_dp_bps", "p99_abs_dp_bps",
             "pairs_1min", "h_meanabs_1min_bps")
_EST_INT = {"tick_pairs", "pairs_1min"}


def _est_row(table: pd.DataFrame, key) -> dict:
    """The mid-free estimates for one bucket, or NaNs when it has no pairs."""
    if key in table.index:
        r = table.loc[key]
        return {c: (int(r[c]) if c in _EST_INT else float(r[c])) for c in _EST_COLS}
    return {c: (0 if c in _EST_INT else float("nan")) for c in _EST_COLS}


def _fit_bucket(x: np.ndarray, days: np.ndarray, bucket: str,
                prices: np.ndarray | None = None) -> dict:
    from SDRUtils.dealer_direction import probability as P

    f = P.fit_mixture(x, bucket=bucket)
    tick, hit = detect_tick(prices) if prices is not None else (float("nan"),
                                                                float("nan"))
    sd = dispersion_ceiling(x)
    return {
        "bucket": bucket, "n": int(f.n), "n_trimmed": int(f.n_trimmed),
        "n_days": int(len(np.unique(days))),
        "b0_bps": f.b0, "h_fit_bps": f.h, "s_fit_bps": f.s, "tau_bps": f.tau,
        "separation_h_over_s": f.separation,
        "mle_reliable": bool(f.mle_reliable),
        "flags": ";".join(f.flags),
        # Bootstrapped only where the fit resolved: 400 refits of a floor cost
        # minutes and produce the standard error of a floor.
        "h_fit_se_bps_day_block": (_boot_h(x, days, bucket)
                                   if f.separation >= 1.0 else float("nan")),
        "round_trip_fit_bps": 2.0 * f.h,
        # lattice: a floor. one quote increment is the narrowest a bid-offer can be.
        "tick_bps": tick, "tick_hit_rate": hit,
        "round_trip_lattice_bps": tick,
        # dispersion: a ceiling. m2 = h^2 + s^2 >= h^2.
        "sd_trimmed_bps": sd,
        "round_trip_ceiling_bps": 2.0 * sd,
    }


def stage_fit() -> None:
    from SDRUtils.dealer_direction import probability as P

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    # ---- S1 -------------------------------------------------------------
    s1 = pd.read_parquet(CACHE / "s1_dev.parquet")
    s1 = s1.dropna(subset=["deviation_bps"])
    s1["day"] = pd.to_datetime(s1["as_of_date"]).dt.date.astype(str)
    _log(f"S1: {len(s1)} usable deviations over {s1['day'].nunique()} days")

    prim = s1[s1["trade_type"] == "SPREADOVER"].copy()
    prim["t"] = pd.to_datetime(prim["snap_et"])
    # Pairing key includes the printed-spread population's own instrument (the
    # exact tenor label) and the day; pooled to (tenor, venue) for reporting.
    est_s1 = print_stream_estimates(
        prim, price_col="pts_bp", time_col="t",
        pair_cols=["tenor_label", "venue", "day"],
        bucket_cols=["tenor_label", "venue"]).set_index(["tenor_label", "venue"])

    for (t, v), g in prim.groupby(["tenor_label", "venue"]):
        if len(g) < 30:
            continue
        b = f"S1|SPREADOVER|{t}|{v}"
        r = _fit_bucket(g["deviation_bps"].to_numpy(float),
                        g["day"].to_numpy(), b, g["pts_bp"].to_numpy(float))
        rows.append(r | {"instrument": "S1_SWAP_SPREAD", "unit": "bp of spread",
                         "family": "SPREADOVER", "tenor_bucket": t, "venue": v}
                    | _est_row(est_s1, (t, v)))

    sec = s1[s1["trade_type"].isin(["MATCHED_MATURITY", "INVOICE"])].copy()
    sec["t"] = pd.to_datetime(sec["snap_et"])
    est_sec = print_stream_estimates(
        sec, price_col="pts_bp", time_col="t",
        pair_cols=["tenor_label", "day"],
        bucket_cols=["tenor_label"]).set_index(["tenor_label"])
    for t, g in sec.groupby("tenor_label"):
        if len(g) < 30:
            continue
        b = f"S1|MM_INVOICE|{t}|ALL"
        r = _fit_bucket(g["deviation_bps"].to_numpy(float), g["day"].to_numpy(), b,
                        g["pts_bp"].to_numpy(float))
        rows.append(r | {"instrument": "S1_SWAP_SPREAD", "unit": "bp of spread",
                         "family": "MATCHED_MATURITY+INVOICE", "tenor_bucket": t,
                         "venue": "ALL"} | _est_row(est_sec, t))

    # ---- S2 -------------------------------------------------------------
    # Integrity before use, and against the TARGET day set rather than against
    # whatever happens to be on disk: a per-day cache reports completion by the
    # files it wrote, which is not the same statement as "every sampled day is
    # present and readable". Two writers briefly raced this directory, so a
    # torn file is a live possibility and the survivor never revisits a day it
    # saw at startup.
    want = set(s2_days())
    files = sorted((CACHE / "s2").glob("*.parquet"))
    have, bad = {}, []
    for f in files:
        try:
            have[f.stem] = pd.read_parquet(f)
        except Exception as exc:  # noqa: BLE001
            bad.append((f.name, f"{type(exc).__name__}: {exc}"))
    missing = sorted(want - set(have))
    extra = sorted(set(have) - want)
    _log(f"S2 integrity: target {len(want)} days, readable {len(have)}, "
         f"unreadable {len(bad)}, missing {len(missing)}, not-in-target {len(extra)}")
    if bad or missing:
        for n, e in bad:
            _log(f"  UNREADABLE {n}: {e}")
        raise SystemExit(
            f"S2 cache incomplete: {len(missing)} missing, {len(bad)} unreadable. "
            "Delete the unreadable files and re-run `measure_costs.py s2`.")
    s2 = pd.concat([have[d] for d in sorted(want)], ignore_index=True)
    n_all = len(s2)
    s2 = s2[s2["failure"].isna()].dropna(subset=["deviation_bps"]).copy()
    s2["band"] = [P.tenor_band(y) for y in s2["tenor_years"]]
    s2["day"] = s2["as_of_date"].astype(str)
    _log(f"S2: {len(s2)}/{n_all} priced over {s2['day'].nunique()} days")

    s2["t"] = pd.to_datetime(s2["exec_ts"])
    s2["rate_bps"] = s2["traded_pct"] * 100.0
    est_s2 = print_stream_estimates(
        s2, price_col="rate_bps", time_col="t",
        pair_cols=["tenor_label", "venue", "day", "band"],
        bucket_cols=["band", "venue"]).set_index(["band", "venue"])

    for (bd, v), g in s2.groupby(["band", "venue"]):
        if len(g) < 30:
            continue
        b = f"S2|OUTRIGHT_SOFR|{bd}|{v}"
        r = _fit_bucket(g["deviation_bps"].to_numpy(float), g["day"].to_numpy(), b,
                        g["rate_bps"].to_numpy(float))
        rows.append(r | {"instrument": "S2_OUTRIGHT_SOFR", "unit": "bp of rate",
                         "family": "OUTRIGHT", "tenor_bucket": bd, "venue": v}
                    | _est_row(est_s2, (bd, v)))

    out = pd.DataFrame(rows)
    out["round_trip_roll_bps"] = 2.0 * out["h_roll_bps"]

    # THE FIT IS ONLY A MEASUREMENT WHERE IT SAYS IT IS.
    # stage_validate shows fit_mixture is unbiased (<=2.4%) when the fit's own
    # reported separation h/s is >= 1, and biased DOWN by up to 80% below that
    # -- always toward a smaller cost, which is the direction a kill rule must
    # not be wrong in. Below the gate the fitted h is a floor artefact and the
    # cost has to come from the mid-free readings instead.
    out["fit_status"] = np.where(out["separation_h_over_s"] >= 1.0,
                                 "MEASURED", "UNRESOLVED_FLOOR")
    rt_fit = np.where(out["fit_status"] == "MEASURED",
                      out["round_trip_fit_bps"], np.nan)
    # A bootstrap standard error on a floored h is the standard error OF THE
    # FLOOR -- it would read as a tight measurement of a number that is not a
    # measurement. Blanked wherever the fit did not resolve.
    out.loc[out["fit_status"] != "MEASURED", "h_fit_se_bps_day_block"] = np.nan

    # WHICH NUMBER IS USED, AND WHY IT IS THE LARGER ONE.
    #
    # Only estimators whose validated preconditions hold on this population may
    # set a cost. Measured in stage_validate and in the columns beside them:
    #
    #   fit           unbiased only where it reports separation >= 1; DOWN by up
    #                 to 80% below that, and it reports below that everywhere here
    #   Roll          UP with instrument heterogeneity, DOWN with repeat clips at
    #                 one price -- and `frac_dp_zero` runs 0.05-0.83, so both
    #                 contaminations are live. DIAGNOSTIC ONLY.
    #   mean|dp| 1min equals h only when the two sides are independent draws; the
    #                 same repeat clips make them dependent, biasing it DOWN.
    #                 DIAGNOSTIC ONLY.
    #   lattice       a hard FLOOR: bid and offer are >= one quote increment apart
    #   ceiling       a hard CEILING: m2 = h^2 + s^2 >= h^2
    #
    # That leaves the two bounds, so the reported cost is the top of the bracket
    # -- the larger, as instructed, and the side a kill rule must be wrong on.
    # `2 * h_fit` can never exceed the ceiling (the ceiling bounds h itself), so
    # including it changes nothing where the fit does resolve; it is in the max
    # so that the rule reads the same whether it resolves or not.
    out["round_trip_meanabs1m_bps"] = 2.0 * out["h_meanabs_1min_bps"]
    floor = out["round_trip_lattice_bps"].to_numpy(float)
    ceil = out["round_trip_ceiling_bps"].to_numpy(float)
    used = np.fmax(np.fmax(floor, ceil), rt_fit)
    out["round_trip_used_bps"] = used

    # A family whose printed price does not reconcile to its mid has no cost
    # here, and the csv must say so without help from the prose. MATCHED_MATURITY
    # and INVOICE carry a PTS on a selected 6-8% of legs and an invoice spread is
    # quoted against a futures CTD forward, not the spot swap-spread axis MI01
    # publishes: their b0 reaches +16.7 bp and their s reaches 17.9 bp. Leaving a
    # 71.7 bp "kill threshold" in a numeric column that a consumer will join on is
    # how a disavowed number gets used anyway.
    out["reconciles_to_mid"] = out["family"] != "MATCHED_MATURITY+INVOICE"
    out.loc[~out["reconciles_to_mid"],
            ["round_trip_used_bps", "kill_threshold_used_bps"]] = np.nan
    # A ceiling BELOW the lattice floor is a contradiction, not a number:
    # it would mean the printed dispersion is narrower than the quote
    # increment. Flag it rather than silently taking one side.
    out["bracket_ok"] = ~(np.isfinite(ceil) & np.isfinite(floor) & (ceil < floor))
    out["kill_threshold_used_bps"] = 2.0 * out["round_trip_used_bps"]
    cols = ["instrument", "family", "tenor_bucket", "venue", "unit", "reconciles_to_mid",
            "n", "n_trimmed",
            "n_days", "b0_bps", "h_fit_bps", "h_fit_se_bps_day_block", "s_fit_bps",
            "tau_bps", "separation_h_over_s", "fit_status", "mle_reliable", "flags",
            "tick_bps", "tick_hit_rate", "sd_trimmed_bps",
            "h_roll_bps", "h_meanabs_bps", "h_meanabs_1min_bps", "h_medtick_bps",
            "tick_pairs", "pairs_1min", "frac_dp_zero",
            "p90_abs_dp_bps", "p99_abs_dp_bps",
            "round_trip_fit_bps", "round_trip_roll_bps", "round_trip_meanabs1m_bps",
            "round_trip_lattice_bps", "round_trip_ceiling_bps",
            "round_trip_used_bps", "bracket_ok",
            "kill_threshold_used_bps", "bucket"]
    out = out[cols].sort_values(["instrument", "venue", "tenor_bucket"])
    out.to_csv(OUT / "costs.csv", index=False)
    _log(f"wrote {OUT / 'costs.csv'} ({len(out)} rows)")
    with pd.option_context("display.width", 260, "display.max_rows", 200,
                           "display.max_columns", 40):
        print(out.drop(columns=["bucket"]).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["validate", "s1", "s2", "fit"])
    a = ap.parse_args()
    {"validate": stage_validate, "s1": stage_s1, "s2": stage_s2,
     "fit": stage_fit}[a.stage]()


if __name__ == "__main__":
    main()
