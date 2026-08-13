"""S2 -- does daily dealer positioning predict multi-day reversal?

``docs/dealer_direction/signals/S_PREREG.md`` S2, committed at ``5ec6a7dd``
before any signal was estimated. **Design sample only.** Every date this module
touches -- tape query, curve mark, forward return -- is bounded by
:data:`DESIGN_END`; the hold-out (2025-09-01 .. 2026-08-07) is not opened, not
for a fit and not for a coverage count.

THE FORWARD WINDOW IS THE HOLD-OUT'S BACK DOOR, AND IT IS SHUT STRUCTURALLY
---------------------------------------------------------------------------
A signal stamped 2025-08-29 has its ``t+5`` exit mark in September -- inside the
hold-out. Reading that mark to close a design-sample position **is** opening the
hold-out. So the last signal day is :data:`LAST_SIGNAL_DAY` = 2025-08-22, five
sessions before :data:`DESIGN_END`, and the mark series itself stops at
:data:`DESIGN_END`. Both are module constants with no CLI override, so a
hold-out date cannot arrive by argument.

WHAT IS BUILT
-------------
The ladder's own daily output, through the ladder's own code:

    tape legs -> universe.build_universe        (the ladder's exclusion vocabulary)
              -> midprice.UnitRepricer          (Citi minute curve, T-1min snap)
              -> probability.Calibration        (TRAILING window, never the day itself)
              -> krd.KrdProjector               (rateslib delta ladder, 28 pillars)
              -> ladder.unit_ladder_rows        (weight = conventions.signed_weight)
              -> indicator.roll_up_to_tenor_buckets  (the 10 TENOR10 buckets)

and then, per (bucket, flow day): the D2C FLOW net ``delta_dv01``, its
own-history z, and the change in that bucket's par SOFR rate over the next five
sessions.

Stages, run in order::

    validate   estimators against known answers   (must pass before anything else)
    build      per-day repricing + KRD -> D:/dd_signals_cache/s2_pos/  (resumable)
    target     per-day 15:00 ET par rates          -> cache/rates.parquet
    signal     calibration -> p -> ladder -> bucket-day panel -> cache/panel.parquet
    test       the one regression, the verdict     -> out/s2_results.csv

===========================================================================
SPEC -- FROZEN BEFORE THE REGRESSION RAN
===========================================================================
Written first and left unedited afterwards. ``S_PREREG`` §5 allows one
specification per hypothesis, and this repo's memory records twelve post-hoc
defects that all happened to flatter the hypothesis.

| item | choice | why, decided in advance |
|---|---|---|
| population | SOFR, non-lifecycle (FLOW), every unit the ladder can orient: RATE rule for at-market OUTRIGHT/CURVE/FLY, UPFRONT rule where an other-payment is present (that is what keeps PKG-N in). | the ladder's own retained population. FED_FUNDS is dropped because the target is a SOFR par rate and the no-bias curve result was measured on SOFR (`WHAT_THE_LADDER_SUPPORTS` §3); it is ~3% of universe DV01. LIFECYCLE is a separate series by the ladder's own design (D8). |
| risk | rateslib delta ladder, 28 pillars, 60-min session blocks, rolled up by `indicator.PILLAR_BUCKET` | `LEDGER` D9 and the per-day-solver correction. Not a maturity-point allocation: "a signed KRD vector rather than a scalar" is one of the three things `S_PREREG` says is different this time. |
| weight | `conventions.signed_weight(p) = 2p-1`, never `p` | the task's own instruction and `ladder.py`'s contract. |
| calibration | `probability.Calibration.fit` on a **trailing 60-calendar-day** window ending the day before the classification date, refit every 5 sessions | a full-sample fit puts future deviations into day-t weights through `b0`. `rolling_calibrations`' own defaults (`window_days=60, min_gap_days=1`); `step_days=5` is a cost amortisation the same function documents. |
| flow window | `(D-1 15:00 ET, D 15:00 ET]` on the **visibility** clock | `S_PREREG`: stamp on availability, never execution. Ending the window *at* the entry mark is what makes the position takeable: no print in the signal can post-date the mark it is traded at. Matches S1's window so the two tests share a clock. |
| buckets | `indicator.TENOR_BUCKETS` minus **1-2Y** | `S_PREREG` S2 excludes 1-2Y (exclusion rate drifts +5.07 pp/yr, t=+3.21). |
| regressor | `z` = own-history standardisation of the bucket's D2C FLOW net `delta_dv01`, trailing 250 obs, min 60, zero-filled on no-print sessions | the indicator's own cross-bucket-safe view (`INDICATOR.md` §1: a constant retention factor cancels exactly in z). Levels may not be pooled across buckets; z may. `Z_WINDOW_OBS`/`Z_MIN_OBS` are the indicator's constants, not chosen here. |
| target | `dR = R(t+5) - R(t)`, `R` = par SOFR rate in bp at the bucket's **right-edge** tenor, from the same Citi minute curve at 15:00 ET | same curve family as the mid, so the two sides of the test share a measurement. Right edge fixed by rule, `30Y+ -> 40Y` (its 30Y edge collides with 20-30Y), `0-1Y -> 1Y`. |
| horizon | 5 sessions | `S_PREREG` S2: "over days t+1..t+5". |
| direction | **beta > 0** | `S_PREREG` S2, fixed in advance: dealer receives fixed -> long duration -> must sell -> the rate should **rise**. A significant negative beta is a different phenomenon, not a pass. |
| primary test | pooled panel over the nine tested buckets, `dR = a + b*z + e` | `S_PREREG` S2 is one hypothesis about one mechanism, not eight. Per-bucket coefficients are reported as diagnostics, not as extra hypotheses. |
| standard errors | **Driscoll-Kraay** = day-clustered + Bartlett lag 5 | `S_PREREG` §4 requires day clustering and `N_eff` = trading days; the overlapping 5-day forward return additionally makes the residual MA(4) *across* days, which day-clustering alone cannot see. DK is day-clustering plus that correction. The prereg-literal day-clustered SE (lag 0) is reported beside it; where they disagree the **larger** governs, because being wrong about a cost hurdle in the conservative direction is the only acceptable side. |
| secondary test | one interaction, `dR = a + b*z + c*(z*q) + d*q`, `q` = own-history z of `log((|D2D| + 1)/(|D2C| + 1))` in the same bucket-day | `S_PREREG` S2 declares exactly one conditioner (D2D/D2C volume ratio as a forced-dealer proxy) and says the unconditional test is primary. `log` because the ratio is a ratio; `+1` USD/bp guards a zero side; standardised so `b` keeps its unconditional meaning at the mean. |
| edge per trade | `mean(sign(z) * dR)` over bucket-days with a position, bp of rate | the quantity `S_PREREG` §1's kill rule is stated against. Every bucket-day with a defined z is one trade; there is no threshold, because a threshold is a search. |
| MDE | `(z_0.9875 + z_0.8) * SE = 3.083 * SE` | 80% power, two-sided at ALPHA = 0.025. Same formula as S1. |
| significance | p < 0.025, two-sided | `S_PREREG` §3, Bonferroni over the two hypotheses. |
| placebo | one: the flow series shifted **forward** five sessions (the signal predicts a return that already happened) | leakage detector. Its edge must be ~0 or the pipeline is reading the future. |

THE VERDICT LADDER, FIXED BEFORE THE RUN
----------------------------------------
Evaluated in this order, per cell, against that cell's own ``costs.csv`` row::

    1. usable bucket-days < 200                    -> UNINFORMATIVE_COVERAGE
    2. sign wrong AND p < 0.025                    -> WRONG_SIGN
    3. edge >= kill_threshold AND p < 0.025        -> PASS (hold-out may open)
    4. MDE > kill_threshold                        -> UNINFORMATIVE_POWER
    5. otherwise                                   -> UNINFORMATIVE_COST

**There is no DEAD band for S2, and that is not a softening.** ``COSTS.md``
reports S2's round trip as *unmeasured*: there is no quote lattice for a
negotiated par rate, so the only bound available is the ceiling
``2*sqrt(m2_trimmed)``, which is set by **our own curve error** (``s`` =
0.26-0.68 bp) rather than by any observed bid-offer. S1 can say DEAD because it
has a measured 0.125 bp lattice floor to say it against; S2 cannot. So the S2
kill rule is one-sided by construction: an edge **above** the ceiling hurdle
clears under any reading of the cost, and an edge **below** it is
``UNINFORMATIVE_COST``, not "no signal". Reporting S2 dead against 1.06-2.79 bp
would be reporting a curve-error artefact as a market fact.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"          # never open Excel
# C: was at 447 MB free while this ran. Nothing of ours lands there.
os.environ.setdefault("TMPDIR", "D:/dd_signals_cache/tmp")

import argparse
import datetime
import math
import pathlib
import sys
import time
import warnings

import numpy as np
import pandas as pd

REPO = "C:/Users/chris/clee/ARBS-dd"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

CACHE = pathlib.Path("D:/dd_signals_cache/s2_pos")
UNIT_DIR = CACHE / "units"
KRD_DIR = CACHE / "krd"
COV_DIR = CACHE / "coverage"
OUT = pathlib.Path(REPO) / "BT" / "dd_signals" / "out"

# --------------------------------------------------------------------------
# The pre-registered sample. NOT NEGOTIABLE AND NOT PARAMETERISED.
# --------------------------------------------------------------------------
DESIGN_START = "2024-03-01"
DESIGN_END = "2025-08-31"

#: Five sessions before the last mark this run may read. A signal stamped later
#: than this would need a September curve to close, which is the hold-out.
LAST_SIGNAL_DAY = "2025-08-22"

HORIZON = 5
ALPHA = 0.025
MDE_Z = 3.083                      # z(0.9875) + z(0.80)

#: The entry/exit mark and the right edge of the flow window, New York.
MARK_HOUR, MARK_MINUTE = 15, 0

#: `indicator.TENOR_BUCKETS` right edges, in the tenor string the curve wants.
#: 30Y+ maps to 40Y because its own right edge collides with 20-30Y's.
BUCKET_TENOR = {
    "0-1Y": "1Y", "1-2Y": "2Y", "2-3Y": "3Y", "3-5Y": "5Y", "5-7Y": "7Y",
    "7-10Y": "10Y", "10-15Y": "15Y", "15-20Y": "20Y", "20-30Y": "30Y",
    "30Y+": "40Y",
}
#: `S_PREREG` S2 excludes this bucket outright.
EXCLUDED_BUCKET = "1-2Y"

#: TENOR10 bucket -> the `costs.csv` tenor band whose D2C round trip governs it.
#: 0-1Y has four sub-year bands in the cost file; the widest is taken, which is
#: the conservative side of a one-sided kill rule.
COST_BAND = {
    "0-1Y": ("0-1M", "1M-3M", "3M-6M", "6M-1Y"), "1-2Y": ("1Y-2Y",),
    "2-3Y": ("2Y-3Y",), "3-5Y": ("3Y-5Y",), "5-7Y": ("5Y-7Y",),
    "7-10Y": ("7Y-10Y",), "10-15Y": ("10Y-15Y",), "15-20Y": ("15Y-20Y",),
    "20-30Y": ("20Y-30Y",), "30Y+": ("30Y+",),
}

#: Trailing calibration. `rolling_calibrations`' own defaults for the window and
#: the gap; the step is a cost amortisation that function documents.
CALIB_WINDOW_DAYS = 60
CALIB_MIN_GAP_DAYS = 1
CALIB_STEP_DAYS = 5

BOOT_SEED = 20260811


def _log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ==========================================================================
# database
# ==========================================================================

def connect():
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    return psycopg2.connect(resolve_pg_url())


def _legs_table() -> str:
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    return LEGS_TABLE


def tape_days() -> list[str]:
    """Every ``as_of_date`` in the build window. Read once, cached to disk."""
    path = CACHE / "days.txt"
    if path.exists():
        return path.read_text().split()
    conn = connect()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_sql(
            f"SELECT DISTINCT as_of_date FROM {_legs_table()} "
            "WHERE as_of_date BETWEEN %(a)s AND %(b)s ORDER BY as_of_date",
            conn, params={"a": DESIGN_START, "b": LAST_SIGNAL_DAY})
    conn.close()
    days = [str(x) for x in d["as_of_date"]]
    if not days:
        raise RuntimeError("the tape returned no days for the design window; "
                           "that is a failed read, not an empty market")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(days))
    return days


# ==========================================================================
# stage: build   (the expensive pass -- repricing + KRD, per as_of_date)
# ==========================================================================

_REP = None
_PROJ = None


def _engines():
    """One repricer and one projector per worker process, built lazily."""
    global _REP, _PROJ
    if _REP is None:
        from SDRUtils.dealer_direction import krd, midprice, snapshot

        _REP = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
        _PROJ = krd.KrdProjector(_REP.pricer)
    return _REP, _PROJ


UNIT_COLS = [
    "unit_key", "kind", "n_legs", "rule", "venue_class", "rate_index",
    "is_lifecycle", "is_block", "is_capped", "as_of_date", "tenor_years",
    "tenor_band", "special_tenor_type", "visibility_ts", "visibility_source",
    "pricing_ts", "execution_ts", "event_ts", "deviation_bps", "npv_pay",
    "upfront", "upfront_source", "structure_dv01", "gross_pv01",
    "snapshot_lag_s", "failure",
]


def _atomic_parquet(df: pd.DataFrame, path: pathlib.Path) -> None:
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def build_one_day(day: str) -> dict:
    """Price and project one ``as_of_date``. Writes three parquets, atomically."""
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import probability as P
    from SDRUtils.dealer_direction import snapshot, universe
    from SDRUtils.dealer_direction.types import DirectionCall

    t0 = time.perf_counter()
    conn = connect()
    legs = universe.load_legs(conn, day, day)
    conn.close()
    if legs.empty:
        raise RuntimeError(f"{day}: the tape returned no legs; a business day "
                           "with no prints is a failed read, not a quiet market")

    ann = universe.annotate_legs(legs)
    uf = universe.unit_frame(legs)
    units, _excluded = universe.build_universe(legs)

    # --- coverage: maturity-point allocation of gross |DV01|, per INDICATOR §2
    excl_by_group = uf["exclusion"].to_dict()
    years = (pd.to_datetime(ann["expiration_date"], errors="coerce")
             - pd.Timestamp(day)).dt.days / 365.25
    cov = pd.DataFrame({
        "bucket_key": [ind.bucket_for_years(max(float(y), 0.0))
                       if pd.notna(y) else None for y in years],
        "venue_class": ann["_venue"],
        "rate_index": ann["rate_index_clean"],
        "dv01": ann["_dv01_proxy"].astype(float),
        "kept": [excl_by_group.get(g) is None for g in ann["_unit_group"]],
    })
    cov = (cov.groupby(["bucket_key", "venue_class", "rate_index", "kept"],
                       dropna=False, observed=True)["dv01"].sum().reset_index())
    cov["as_of_date"] = day

    # --- the population -------------------------------------------------
    pop, calls, meta = [], [], []
    for u in units:
        if u.rate_index != "SOFR" or u.is_lifecycle:
            continue
        rule = (conv.RULE_UPFRONT if u.upfront is not None else conv.RULE_RATE)
        try:
            conv.base_orientation(u.kind, u.n_legs, rule)
        except conv.UnorientableUnit:
            continue
        pop.append(u)
        meta.append(rule)

    pop_meta = dict(zip((u.unit_key for u in pop), meta))
    pop.sort(key=lambda u: snapshot.snap_instant(u.clocks.pricing))

    rep, proj = _engines()
    rows = []
    with rep.day_scope():
        for u in pop:
            rule = pop_meta[u.unit_key]
            out = rep.price_unit(u)
            tenor = float(pd.to_numeric(u.legs["tenor_years"],
                                        errors="coerce").max())
            stt = u.legs["special_tenor_type"].iloc[0]
            base = {
                "unit_key": u.unit_key, "kind": u.kind, "n_legs": u.n_legs,
                "rule": rule, "venue_class": u.venue_class,
                "rate_index": u.rate_index, "is_lifecycle": u.is_lifecycle,
                "is_block": u.is_block, "is_capped": u.is_capped,
                "as_of_date": day, "tenor_years": tenor,
                "tenor_band": P.tenor_band(tenor),
                "special_tenor_type": ("STANDARD" if stt is None or pd.isna(stt)
                                       else str(stt)),
                "visibility_ts": u.clocks.visibility,
                "visibility_source": u.clocks.visibility_source,
                "pricing_ts": u.clocks.pricing,
                "execution_ts": u.clocks.execution,
                "event_ts": u.clocks.event,
                "upfront": u.upfront, "upfront_source": u.upfront_source,
            }
            if out.failure is not None:
                rows.append(base | {"failure": out.failure})
                calls.append(DirectionCall(
                    unit_key=u.unit_key, rule=rule, deviation_bps=None, p=None,
                    signed_weight=None, dealer_sign=0, exclusion=out.failure))
                continue
            dev = None
            if rule == conv.RULE_RATE:
                traded = [float(l["fixed_rate"]) * 100.0
                          for _, l in u.legs.iterrows()]
                dev = (conv.structure_price(traded, u.kind, u.n_legs, rule)
                       - conv.structure_price(list(out.pricing.leg_mid_pct),
                                              u.kind, u.n_legs, rule))
            rows.append(base | {
                "failure": None, "deviation_bps": dev,
                "npv_pay": out.pricing.npv_pay,
                "structure_dv01": out.pricing.structure_dv01,
                "gross_pv01": out.gross_pv01,
                "snapshot_lag_s": out.pricing.snapshot_lag_seconds})
            calls.append(DirectionCall(
                unit_key=u.unit_key, rule=rule, deviation_bps=dev, p=0.75,
                signed_weight=0.5, dealer_sign=1))

    with proj.day_scope():
        krd_frame, krd_fail = proj.krd_frame(pop, calls)

    units_df = pd.DataFrame(rows).reindex(columns=UNIT_COLS)
    _atomic_parquet(units_df, UNIT_DIR / f"{day}.parquet")
    _atomic_parquet(pd.DataFrame(krd_frame).reindex(
        columns=["unit_key", "bucket_space", "bucket_key", "dv01_if_received"]),
        KRD_DIR / f"{day}.parquet")
    _atomic_parquet(cov, COV_DIR / f"{day}.parquet")
    return {"day": day, "legs": len(legs), "units": len(pop),
            "priced": int(units_df["failure"].isna().sum()),
            "krd_rows": len(krd_frame), "krd_fail": len(krd_fail),
            "seconds": time.perf_counter() - t0}


def _build_worker(day: str):
    try:
        return build_one_day(day)
    except Exception as exc:                                  # noqa: BLE001
        return {"day": day, "error": f"{type(exc).__name__}: {exc}"[:400]}


def stage_build(workers: int, budget_min: float) -> None:
    import concurrent.futures as cf

    for d in (UNIT_DIR, KRD_DIR, COV_DIR, CACHE / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    days = tape_days()
    todo = [d for d in days
            if not ((UNIT_DIR / f"{d}.parquet").exists()
                    and (KRD_DIR / f"{d}.parquet").exists()
                    and (COV_DIR / f"{d}.parquet").exists())]
    _log(f"build: {len(days)} tape days, {len(todo)} still to do, "
         f"{workers} workers, budget {budget_min:.0f} min")
    if not todo:
        _log("build: complete")
        return
    deadline = time.time() + budget_min * 60.0
    done = 0
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        pending, it = set(), iter(todo)
        for _ in range(workers):
            nxt = next(it, None)
            if nxt is not None:
                pending.add(pool.submit(_build_worker, nxt))
        while pending:
            fin, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for f in fin:
                r = f.result()
                done += 1
                if "error" in r:
                    _log(f"  {r['day']}: ERROR {r['error']}")
                else:
                    _log(f"  {r['day']}: {r['units']} units, {r['priced']} priced, "
                         f"{r['krd_rows']} krd rows, {r['seconds']:.0f}s "
                         f"[{done}/{len(todo)}]")
                if time.time() < deadline:
                    nxt = next(it, None)
                    if nxt is not None:
                        pending.add(pool.submit(_build_worker, nxt))
    el = (time.time() - t0) / 60.0
    left = len(todo) - done
    _log(f"build: {done} days in {el:.1f} min ({el / max(done, 1) * 60:.0f} s/day "
         f"wall), {left} remaining"
         + (f", eta {el / max(done, 1) * left:.0f} min" if left else " -- COMPLETE"))


def assert_build_complete() -> list[str]:
    """The readable day set must equal the target set. A missing day is not a
    quiet market and a half-written parquet is not a day."""
    days = tape_days()
    bad = []
    for d in days:
        for sub in (UNIT_DIR, KRD_DIR, COV_DIR):
            p = sub / f"{d}.parquet"
            if not p.exists():
                bad.append(f"{d}:{sub.name}:MISSING")
                continue
            try:
                pd.read_parquet(p, columns=None if sub is COV_DIR else ["unit_key"])
            except Exception as exc:                          # noqa: BLE001
                bad.append(f"{d}:{sub.name}:UNREADABLE:{type(exc).__name__}")
    if bad:
        raise RuntimeError(f"{len(bad)} day/file(s) missing or unreadable, "
                           f"e.g. {bad[:8]}")
    return days


# ==========================================================================
# stage: target   (15:00 ET par SOFR rates at the bucket right edges)
# ==========================================================================

def mark_instant(day) -> pd.Timestamp:
    from SDRUtils.dealer_direction import snapshot

    return pd.Timestamp(pd.Timestamp(day).date(), tz=snapshot.NY) + pd.Timedelta(
        hours=MARK_HOUR, minutes=MARK_MINUTE)


def stage_target() -> None:
    import rateslib as rl

    from SDRUtils.dealer_direction import midprice, snapshot

    days = tape_days()
    # The exit marks run five sessions past the last signal day, and no further:
    # DESIGN_END bounds the series and LAST_SIGNAL_DAY bounds the signal.
    conn = connect()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        extra = pd.read_sql(
            f"SELECT DISTINCT as_of_date FROM {_legs_table()} "
            "WHERE as_of_date > %(a)s AND as_of_date <= %(b)s ORDER BY as_of_date",
            conn, params={"a": LAST_SIGNAL_DAY, "b": DESIGN_END})
    conn.close()
    mark_days = days + [str(x) for x in extra["as_of_date"]]
    assert max(mark_days) <= DESIGN_END, "a mark day escaped the design sample"

    cal = rl.get_calendar("nyc")
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    curve = rep.pricer.curve_for("SOFR")
    tenors = sorted(set(BUCKET_TENOR.values()),
                    key=lambda t: int(t.rstrip("Y")))

    rows = []
    for k, day in enumerate(mark_days, 1):
        inst = mark_instant(day)
        eff = cal.lag_bus_days(pd.Timestamp(day).to_pydatetime(), 2, True)
        with rep.pricer.day_scope():
            for t in tenors:
                mat = rl.add_tenor(eff, t, "MF", cal)
                try:
                    lp = rep.pricer.price_leg(curve, inst, eff, mat, 1e6)
                    rows.append({"mark_date": day, "tenor": t,
                                 "rate_bp": float(lp.mid_pct) * 100.0,
                                 "failure": None})
                except Exception as exc:                      # noqa: BLE001
                    rows.append({"mark_date": day, "tenor": t, "rate_bp": np.nan,
                                 "failure": f"{type(exc).__name__}: {str(exc)[:120]}"})
        if k % 25 == 0 or k == len(mark_days):
            _log(f"target: {k}/{len(mark_days)} marks")
    df = pd.DataFrame(rows)
    _atomic_parquet(df, CACHE / "rates.parquet")
    ok = df["failure"].isna().groupby(df["tenor"]).mean()
    _log(f"target: wrote {len(df)} rows; per-tenor success\n{ok.to_string()}")


# ==========================================================================
# stage: signal   (calibration -> p -> ladder -> the bucket-day panel)
# ==========================================================================

def _read_all(dirpath: pathlib.Path, days: list[str]) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(dirpath / f"{d}.parquet") for d in days],
                     ignore_index=True)


def flow_day_map(vis_ts: pd.Series, mark_days: list[str]) -> pd.Series:
    """Assign each print to the first 15:00 ET mark at or after its visibility."""
    from SDRUtils.dealer_direction import snapshot

    marks = pd.DatetimeIndex([mark_instant(d) for d in mark_days])
    # `utc=True` reads a tz-NAIVE stamp AS UTC, which would shift the date-only
    # degradation (`ladder.visibility_date`'s trap) four hours back and onto the
    # previous flow day -- a day of manufactured lookahead. Measured on this
    # build: 0 of 571,234 priced units carry a naive or null stamp, because the
    # date-only rows fail pricing (`EXCL_NO_CURVE`, "pricing clock is
    # date-only") and never reach here. Asserted rather than assumed.
    s = pd.Series(vis_ts)
    if getattr(s.dtype, "tz", None) is None:
        raise ValueError(
            f"visibility stamps arrived as {s.dtype}, not tz-aware; reading a "
            "naive stamp as UTC shifts the date-only degradation four hours "
            "back and onto the PREVIOUS flow day, which is manufactured "
            "lookahead (`ladder.visibility_date`'s trap)")
    if s.isna().any():
        raise ValueError(f"{int(s.isna().sum())} null visibility stamps; a "
                         "print with no availability clock cannot be dated")
    ts = pd.to_datetime(s, utc=True)
    ny = ts.dt.tz_convert(snapshot.NY)
    idx = marks.searchsorted(ny.to_numpy(), side="left")
    out = pd.Series(pd.NaT, index=vis_ts.index, dtype="datetime64[ns]")
    good = idx < len(marks)
    out[good] = pd.to_datetime([marks[i].date() for i in idx[good]])
    return out


def _upfront_p(units: pd.DataFrame, cal, key_of) -> pd.Series:
    """`p` for the upfront-rule rows, through `upfront.classify`."""
    from SDRUtils.dealer_direction import upfront as U

    out = {}
    for i, r in units.iterrows():
        fit = cal.for_key(key_of(r))
        resid = U.residual_bps(r["npv_pay"], r["upfront"], r["structure_dv01"],
                               bias_bps=fit.b0)
        out[i] = (resid, fit)
    return out


def _install_probability_clip() -> dict:
    """Let a `p` that has rounded a machine epsilon past 1 through, and nothing else.

    `upfront.classify` hands `conventions.signed_weight` the output of
    `p_marginalised`, a logistic-normal integral, and on a deeply off-market
    print that integral returns **1.0000000000000002**: `signed_weight` refuses
    it (rightly -- it cannot tell 1+2e-16 from a real 1.4) and the whole pass
    dies. Dropping those units instead would drop precisely the largest,
    most-confident upfront calls, which is a biased sample of the population
    the ladder is trying to measure.

    So the boundary is clipped, by **1e-9 and no more** -- anything further out
    still raises, because a `p` of 1.2 is a bug and must stay loud. Counted, and
    the count is logged: a guard that fires on half the population would be
    hiding something, and only the count can say so.
    """
    from SDRUtils.dealer_direction import conventions as C

    if getattr(C.signed_weight, "_clipped", False):
        return C.signed_weight._state                          # noqa: SLF001
    original = C.signed_weight
    state = {"n_high": 0, "n_low": 0, "worst": 0.0}

    def guarded(p):
        q = float(p)
        if 1.0 < q <= 1.0 + 1e-9:
            state["n_high"] += 1
            state["worst"] = max(state["worst"], q - 1.0)
            q = 1.0
        elif -1e-9 <= q < 0.0:
            state["n_low"] += 1
            state["worst"] = max(state["worst"], -q)
            q = 0.0
        return original(q)

    guarded._clipped = True
    guarded._state = state
    C.signed_weight = guarded
    return state


def stage_signal() -> None:
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import ladder
    from SDRUtils.dealer_direction import probability as P
    from SDRUtils.dealer_direction import types as T

    days = assert_build_complete()
    units = _read_all(UNIT_DIR, days)
    _log(f"signal: {len(units)} unit rows over {len(days)} days")

    rates = pd.read_parquet(CACHE / "rates.parquet")
    mark_days = sorted(rates.loc[rates["failure"].isna(), "mark_date"].unique())
    units["flow_day"] = flow_day_map(units["visibility_ts"], list(mark_days))

    priced = units[units["failure"].isna() & units["flow_day"].notna()].copy()
    _log(f"signal: {len(priced)} priced units land on a mark day "
         f"({len(units) - len(priced)} dropped: "
         f"{int(units['failure'].notna().sum())} pricing failures, "
         f"{int(units['flow_day'].isna().sum())} past the last mark)")

    # --- how much of the flow the 15:00 cut moves to the next session -----
    shifted = (pd.to_datetime(priced["flow_day"]).dt.date
               != pd.to_datetime(priced["as_of_date"]).dt.date)
    _log(f"signal: the 15:00 ET cut moves {shifted.mean():.1%} of priced units "
         "off their as_of_date")

    # --- trailing calibration, on the RATE-rule deviations ----------------
    rate_rows = priced[priced["rule"] == conv.RULE_RATE].copy()
    cal_df = rate_rows.rename(columns={"kind": "structure"})[
        ["deviation_bps", "venue_class", "rate_index", "structure",
         "special_tenor_type", "tenor_band"]].copy()
    cal_df["as_of_date"] = pd.to_datetime(rate_rows["flow_day"]).dt.date

    import pickle

    cal_path = CACHE / "calibrations.pkl"
    if cal_path.exists():
        with open(cal_path, "rb") as fh:
            cals = pickle.load(fh)
        _log(f"signal: reusing {len(cals)} cached calibrations")
    else:
        _log("signal: fitting rolling calibrations ...")
        t0 = time.time()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cals = P.rolling_calibrations(
                cal_df, window_days=CALIB_WINDOW_DAYS,
                min_gap_days=CALIB_MIN_GAP_DAYS, step_days=CALIB_STEP_DAYS)
        _log(f"signal: {len(cals)} calibrations in {time.time() - t0:.0f}s")
        with open(cal_path.with_suffix(".tmp"), "wb") as fh:
            pickle.dump(cals, fh)
        os.replace(cal_path.with_suffix(".tmp"), cal_path)

    # `rolling_calibrations` refits every `step_days`-th date and returns only
    # those. The days in between are classified by the most recent calibration
    # AT OR BEFORE them -- which is what "refit every 5 sessions" means, and
    # what `step_days` is documented as amortising. Requiring an exact-date key
    # would silently drop four days in five, and the run would look complete.
    cal_dates_sorted = sorted(cals)
    _governing = {}
    for d in sorted({pd.Timestamp(x).date() for x in cal_df["as_of_date"]}):
        i = np.searchsorted(cal_dates_sorted, d, side="right") - 1
        if i >= 0:
            _governing[d] = cal_dates_sorted[i]
    _log(f"signal: {len(_governing)} of "
         f"{cal_df['as_of_date'].nunique()} classification dates have a "
         f"governing calibration (max staleness "
         f"{max((d - c).days for d, c in _governing.items())} days)")

    # --- p, per unit, from the calibration that governs its day -----------
    from SDRUtils.dealer_direction import upfront as U

    clip_state = _install_probability_clip()

    ps, wts, drop = [], [], 0
    fit_memo: dict = {}
    t0 = time.time()
    for n_done, r in enumerate(priced.itertuples(index=False), 1):
        if n_done % 100000 == 0:
            _log(f"signal:   p for {n_done}/{len(priced)} units "
                 f"({time.time() - t0:.0f}s)")
        d = pd.Timestamp(r.flow_day).date()
        gov = _governing.get(d)
        if gov is None:
            ps.append(np.nan)
            wts.append(np.nan)
            drop += 1
            continue
        _lo, _hi, cal = cals[gov]
        key = P.BucketKey(venue_class=r.venue_class, rate_index=r.rate_index,
                          structure=r.kind,
                          special_tenor_type=r.special_tenor_type,
                          tenor_band=r.tenor_band)
        memo_key = (gov, key)
        fit = fit_memo.get(memo_key)
        if fit is None:
            fit = cal.for_key(key)
            fit_memo[memo_key] = fit
        if r.rule == conv.RULE_RATE:
            call = P.direction_probability(float(r.deviation_bps), fit)
            ps.append(call.p)
            wts.append(call.signed_weight)
        else:
            tau = U.TauUpfront(tau_bps=fit.tau, bias_bps=fit.b0,
                               half_spread_bps=fit.h, sigma_bps=fit.s,
                               n=fit.n_trimmed, population=U.POPULATION_FLOW,
                               bucket=fit.bucket)
            c = U.classify(npv_pay=r.npv_pay, upfront=r.upfront,
                           structure_dv01=r.structure_dv01,
                           upfront_source=r.upfront_source, tau=tau,
                           mid_sigma_bps=fit.s, mid_bias_bps=fit.b0)
            ps.append(c.p)
            wts.append(c.signed_weight)
    # `upfront.classify` may return `p = None` (it refuses to invent a
    # probability where the rule cannot produce one); coerced so the check
    # below compares numbers rather than raising on a None.
    priced["p"] = pd.to_numeric(pd.Series(ps, index=priced.index),
                                errors="coerce")
    priced["signed_weight"] = pd.to_numeric(pd.Series(wts, index=priced.index),
                                            errors="coerce")
    _log(f"signal: {drop} units had no trailing calibration (burn-in), "
         f"{int(priced['p'].isna().sum())} carry no p")
    _log(f"signal: boundary clip fired {clip_state['n_high']} high / "
         f"{clip_state['n_low']} low of {len(priced)} units "
         f"(worst overshoot {clip_state['worst']:.3e})")

    called = priced[priced["p"].notna()
                    & priced["signed_weight"].notna()].copy()
    _atomic_parquet(
        called[["unit_key", "flow_day", "rule", "venue_class", "kind",
                "tenor_band", "p", "signed_weight"]], CACHE / "calls.parquet")
    # `2p-1` is re-derived here rather than trusted, exactly as
    # `ladder._assert_weight_agrees_with_side` re-derives it.
    w = called["p"].map(conv.signed_weight)
    assert np.nanmax(np.abs(w - called["signed_weight"])) < 1e-12, \
        "signed_weight is not 2p-1"

    panel_from_calls(called, days, tag="")


def panel_from_calls(called: pd.DataFrame, days: list[str], *, tag: str = "",
                     sessions=None) -> pd.DataFrame:
    """calls -> the ladder -> the D2C bucket-day panel with `z` and `q`.

    Factored out so the RATE-rule-only robustness diagnostic runs off the same
    code and the same cached calls, rather than off a second implementation
    that could differ from the primary in some way nobody would see.
    """
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import types as T

    krd = _read_all(KRD_DIR, days)
    rows = krd.merge(called[["unit_key", "flow_day", "venue_class", "kind",
                             "signed_weight", "p", "rule"]],
                     on="unit_key", how="inner", validate="many_to_one")
    rows["delta_dv01"] = rows["signed_weight"] * rows["dv01_if_received"]
    rows["bucket_key"] = rows["bucket_key"].map(ind.PILLAR_BUCKET)
    if rows["bucket_key"].isna().any():
        raise RuntimeError("a KRD pillar has no TENOR10 bucket")

    panel = (rows.groupby(["bucket_key", "flow_day", "venue_class"],
                          observed=True)
             .agg(delta_dv01=("delta_dv01", "sum"),
                  abs_dv01=("dv01_if_received", lambda s: float(np.abs(s).sum())),
                  n_units=("unit_key", "nunique"))
             .reset_index())
    _atomic_parquet(panel, CACHE / f"panel_raw{tag}.parquet")
    _log(f"panel{tag}: {len(panel)} bucket-day-venue cells; "
         f"{panel['bucket_key'].nunique()} buckets, "
         f"{panel['flow_day'].nunique()} days")

    # The session calendar is the PRIMARY panel's, always: a diagnostic that
    # loses a session would silently re-index its own z window.
    if sessions is None:
        sessions = pd.to_datetime(sorted(
            set(pd.to_datetime(panel["flow_day"]).dt.normalize())))
    out = []
    for bucket in ind.TENOR_BUCKETS:
        for venue in (T.VENUE_D2C, T.VENUE_D2D):
            sub = panel[(panel["bucket_key"] == bucket)
                        & (panel["venue_class"] == venue)]
            s = (sub.set_index(pd.to_datetime(sub["flow_day"]))
                 .reindex(sessions)[["delta_dv01", "abs_dv01", "n_units"]])
            s["observed"] = s["delta_dv01"].notna()
            s = s.fillna(0.0)
            s["bucket_key"] = bucket
            s["venue_class"] = venue
            s["date"] = sessions
            out.append(s.reset_index(drop=True))
    cells = pd.concat(out, ignore_index=True)

    d2c = cells[cells["venue_class"] == T.VENUE_D2C].copy()
    d2d = cells[cells["venue_class"] == T.VENUE_D2D].copy()
    d2c = d2c.sort_values(["bucket_key", "date"])
    g = d2c.groupby("bucket_key", observed=True)["delta_dv01"]
    mu = g.transform(lambda x: x.rolling(ind.Z_WINDOW_OBS,
                                         min_periods=ind.Z_MIN_OBS).mean())
    sd = g.transform(lambda x: x.rolling(ind.Z_WINDOW_OBS,
                                         min_periods=ind.Z_MIN_OBS).std())
    d2c["z"] = (d2c["delta_dv01"] - mu) / sd.where(sd > 0)

    ratio = d2d.set_index(["bucket_key", "date"])["abs_dv01"].rename("abs_d2d")
    d2c = d2c.join(ratio, on=["bucket_key", "date"])
    d2c["log_ratio"] = np.log((d2c["abs_d2d"].fillna(0.0) + 1.0)
                              / (d2c["abs_dv01"] + 1.0))
    gr = d2c.groupby("bucket_key", observed=True)["log_ratio"]
    rmu = gr.transform(lambda x: x.rolling(ind.Z_WINDOW_OBS,
                                           min_periods=ind.Z_MIN_OBS).mean())
    rsd = gr.transform(lambda x: x.rolling(ind.Z_WINDOW_OBS,
                                           min_periods=ind.Z_MIN_OBS).std())
    d2c["q"] = (d2c["log_ratio"] - rmu) / rsd.where(rsd > 0)

    d2c = d2c.reset_index(drop=True)
    _atomic_parquet(d2c, CACHE / f"panel_d2c{tag}.parquet")
    _log(f"panel{tag}: wrote panel_d2c{tag} ({len(d2c)} rows, "
         f"{int(d2c['z'].notna().sum())} with a defined z)")
    return d2c


# ==========================================================================
# statistics
# ==========================================================================

def ols_dk(y, X, day_index, lag: int):
    """OLS with a Driscoll-Kraay covariance: day-clustered, Bartlett `lag`.

    ``lag = 0`` is the plain day-clustered (CRVE) estimator, which is what
    ``S_PREREG`` §4 asks for literally; ``lag = 5`` adds the correction the
    overlapping forward return needs. Both come out of this one function so
    they cannot drift apart.
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    e = y - X @ beta
    h = X * e[:, None]

    days = pd.Index(day_index)
    codes, uniq = pd.factorize(days, sort=True)
    T = len(uniq)
    H = np.zeros((T, k))
    np.add.at(H, codes, h)

    S = H.T @ H
    for l in range(1, lag + 1):
        if l >= T:
            break
        w = 1.0 - l / (lag + 1.0)
        G = H[l:].T @ H[:-l]
        S += w * (G + G.T)
    # Small-sample correction on the cluster count, as for any CRVE.
    S *= T / max(T - 1, 1)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    return beta, se, T, n


def two_sided_p(t: float, df: int) -> float:
    from scipy import stats

    return float(2.0 * stats.t.sf(abs(t), max(df, 1)))


def _sim_panel(rng, nb: int, nd: int, rho: float = 0.6):
    """A null panel with THIS test's dependence: 5-day overlapping returns, a
    common daily rate factor, and a regressor that is itself persistent and
    cross-sectionally correlated -- which is what the real ``z`` is (one day's
    flow is correlated across the curve, and the ladder's own ``properties()``
    reports autocorrelation). An iid regressor does not exercise the problem:
    OLS standard errors are approximately right when ``x`` is independent
    noise no matter how dependent ``y`` is, so a simulation built that way
    would report every estimator as fine and check nothing.
    """
    f = rng.standard_normal(nd + HORIZON)
    idio = rng.standard_normal((nb, nd + HORIZON))
    r = 0.8 * f[None, :] + 0.6 * idio
    cum = np.cumsum(r, axis=1)
    y = cum[:, HORIZON:] - cum[:, :nd]
    xf = np.zeros(nd)
    xi = np.zeros((nb, nd))
    ef = rng.standard_normal(nd)
    ei = rng.standard_normal((nb, nd))
    for t in range(1, nd):
        xf[t] = rho * xf[t - 1] + ef[t]
        xi[:, t] = rho * xi[:, t - 1] + ei[:, t]
    x = 0.8 * xf[None, :] + 0.6 * xi
    return y, x


def stage_validate() -> None:
    """Every estimator against a known answer, before it is pointed at data."""
    rng = np.random.default_rng(BOOT_SEED)
    print("=" * 74)
    print("VALIDATION -- the checking tools, against answers known in advance")
    print("=" * 74)

    # 1. the SE estimator under the null, with the real dependence structure
    nb, nd, reps = 8, 260, 400
    rej_cl, rej_dk, rej_ols = 0, 0, 0
    for _ in range(reps):
        y, x = _sim_panel(rng, nb, nd)
        yy, xx = y.ravel(), x.ravel()
        dd = np.tile(np.arange(nd), nb)
        X = np.column_stack([np.ones(yy.size), xx])
        for lag, box in ((0, "cl"), (HORIZON, "dk")):
            b, se, T, n = ols_dk(yy, X, dd, lag)
            p = two_sided_p(b[1] / se[1], T - 1)
            if p < 0.05:
                if box == "cl":
                    rej_cl += 1
                else:
                    rej_dk += 1
        # naive iid OLS, for contrast
        bo = np.linalg.pinv(X.T @ X) @ (X.T @ yy)
        s2 = np.sum((yy - X @ bo) ** 2) / (yy.size - 2)
        se_ols = math.sqrt(s2 * np.linalg.pinv(X.T @ X)[1, 1])
        if two_sided_p(bo[1] / se_ols, yy.size - 2) < 0.05:
            rej_ols += 1
    print(f"  null rejection at 5% over {reps} panels ({nb} buckets x {nd} days, "
          "5-day overlap, common rate factor, persistent correlated regressor):")
    print(f"    iid OLS        {rej_ols / reps:6.1%}   <- must be badly oversized")
    print(f"    day-clustered  {rej_cl / reps:6.1%}")
    print(f"    Driscoll-Kraay {rej_dk / reps:6.1%}   <- must be nearest 5%")
    assert rej_ols / reps > 0.20, "the contrast case did not misbehave; the " \
        "simulation is not exercising the dependence it claims to"
    assert abs(rej_dk / reps - 0.05) < 0.04, "DK does not cover under the null"
    assert rej_dk < rej_cl, "DK is not tighter than day-clustering under overlap"

    # 2. the estimator must FIND an effect that is there (power, known answer)
    hits = 0
    for _ in range(200):
        y, x = _sim_panel(rng, nb, nd)
        y = y + 0.5 * x                                 # a real +0.5 effect
        X = np.column_stack([np.ones(y.size), x.ravel()])
        b, se, T, _ = ols_dk(y.ravel(), X, np.tile(np.arange(nd), nb), HORIZON)
        if two_sided_p((b[1] - 0.5) / se[1], T - 1) > 0.05 and b[1] > 0:
            hits += 1
    print(f"  recovers a planted beta=+0.5 within its own CI: {hits / 200:.1%} "
          "(must be ~95%)")
    assert hits / 200 > 0.85, "the estimator does not recover a known coefficient"

    # 3. the vectorised weighting must equal `ladder.unit_ladder_rows`
    _validate_ladder_equivalence()
    print("VALIDATION: all checks passed")


def _validate_ladder_equivalence() -> None:
    """`delta_dv01 = signed_weight * dv01_if_received`, merged -- against the
    ladder's own loop, on a real day. A reimplementation that is only *nearly*
    the ladder is how a signal stops being the ladder's output."""
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import ladder
    from SDRUtils.dealer_direction.types import Clocks, DirectionCall

    days = sorted(p.stem for p in UNIT_DIR.glob("*.parquet"))
    if not days:
        print("  ladder equivalence: SKIPPED (no built days yet)")
        return
    day = days[len(days) // 2]
    u = pd.read_parquet(UNIT_DIR / f"{day}.parquet")
    k = pd.read_parquet(KRD_DIR / f"{day}.parquet")
    u = u[u["failure"].isna()].head(200)
    k = k[k["unit_key"].isin(set(u["unit_key"]))]

    rng = np.random.default_rng(7)
    p = pd.Series(rng.uniform(0.05, 0.95, len(u)), index=u.index)

    class _Stub:
        pass

    units, calls = [], []
    for (i, r), pi in zip(u.iterrows(), p):
        s = _Stub()
        s.unit_key = r["unit_key"]
        s.venue_class = r["venue_class"]
        s.is_lifecycle = False
        s.clocks = Clocks(pricing=r["pricing_ts"], execution=r["execution_ts"],
                          event=r["event_ts"], visibility=r["visibility_ts"],
                          visibility_source=r["visibility_source"])
        s.as_of_date = pd.Timestamp(r["as_of_date"]).date()
        s.rate_index = r["rate_index"]
        s.kind = r["kind"]
        s.n_legs = int(r["n_legs"])
        s.is_block = bool(r["is_block"])
        s.is_capped = bool(r["is_capped"])
        units.append(s)
        calls.append(DirectionCall(
            unit_key=r["unit_key"], rule=r["rule"], deviation_bps=0.0, p=float(pi),
            signed_weight=conv.signed_weight(float(pi)),
            dealer_sign=1 if pi > 0.5 else -1))
    ref, _ = ladder.unit_ladder_rows(units, calls, k)
    ref_agg = (ref.groupby(["bucket_key"], observed=True)["delta_dv01"].sum()
               .sort_index())

    w = pd.Series(conv.signed_weight(float(x)) for x in p)
    mine = k.merge(pd.DataFrame({"unit_key": u["unit_key"].to_numpy(),
                                 "signed_weight": w.to_numpy()}),
                   on="unit_key", how="inner")
    mine_agg = (mine.assign(delta_dv01=mine["signed_weight"] * mine["dv01_if_received"])
                .groupby("bucket_key", observed=True)["delta_dv01"].sum().sort_index())
    diff = float((ref_agg - mine_agg).abs().max())
    print(f"  ladder equivalence on {day} ({len(units)} units, "
          f"{len(ref)} ladder rows): max |diff| = {diff:.3e}")
    assert diff < 1e-9, "the vectorised weighting is not the ladder's own"


# ==========================================================================
# stage: describe   (what the panel is, before what it predicts)
# ==========================================================================

def stage_describe() -> None:
    """The panel's own properties. Written before the regression is read,
    because ``N_eff`` and the coverage floor are what decide whether a null is
    a null, and both are properties of the panel rather than of the answer."""
    d2c = pd.read_parquet(CACHE / "panel_d2c.parquet")
    d2c["date"] = pd.to_datetime(d2c["date"])
    rows = []
    for b, s in d2c.sort_values("date").groupby("bucket_key", observed=True):
        z = s["z"]
        rows.append({
            "bucket_key": b,
            "n_sessions": len(s),
            "frac_observed": float(s["observed"].mean()),
            "n_z": int(z.notna().sum()),
            "z_ac1": float(z.autocorr(1)) if z.notna().sum() > 10 else np.nan,
            "z_ac5": float(z.autocorr(5)) if z.notna().sum() > 10 else np.nan,
            "level_mean_usd_per_bp": float(s["delta_dv01"].mean()),
            "level_sd_usd_per_bp": float(s["delta_dv01"].std()),
            "abs_dv01_mean": float(s["abs_dv01"].mean()),
            "mean_n_units": float(s["n_units"].mean()),
        })
    desc = pd.DataFrame(rows)
    piv = d2c.pivot(index="date", columns="bucket_key", values="z")
    cc = piv.corr()
    off = cc.where(~np.eye(len(cc), dtype=bool)).stack()
    print(desc.round(3).to_string(index=False))
    print(f"\ncross-bucket z correlation: mean {off.mean():.3f}, "
          f"median {off.median():.3f}, max {off.max():.3f}")
    print("\nz autocorrelation is the series' own persistence; the cross-bucket "
          "correlation is why a day is the cluster and why N_eff is nearer the "
          "session count than the bucket-day count.")
    desc.to_csv(OUT / "s2_panel_description.csv", index=False)
    cc.round(3).to_csv(OUT / "s2_z_cross_correlation.csv")
    _log(f"describe: wrote {OUT / 's2_panel_description.csv'}")


# ==========================================================================
# stage: test
# ==========================================================================

def _cost_hurdles() -> pd.DataFrame:
    c = pd.read_csv(OUT / "costs.csv", comment="#")
    s2 = c[(c["instrument"] == "S2_OUTRIGHT_SOFR") & (c["venue"] == "D2C")]
    rt = s2.set_index("tenor_bucket")["round_trip_used_bps"]
    rows = []
    for b, bands in COST_BAND.items():
        v = max(float(rt[x]) for x in bands if x in rt.index)
        rows.append({"bucket_key": b, "round_trip_bps": v,
                     "kill_threshold_bps": 2.0 * v})
    return pd.DataFrame(rows)


def _marks():
    rates = pd.read_parquet(CACHE / "rates.parquet")
    rates = rates[rates["failure"].isna()]
    rates["mark_date"] = pd.to_datetime(rates["mark_date"])
    return rates.pivot(index="mark_date", columns="tenor",
                       values="rate_bp").sort_index()


def attach_target(d2c: pd.DataFrame, wide: pd.DataFrame) -> pd.DataFrame:
    """`dR` = the bucket's own par rate five marks on, minus its rate today."""
    d2c = d2c.copy()
    d2c["tenor"] = d2c["bucket_key"].map(BUCKET_TENOR)
    d2c["date"] = pd.to_datetime(d2c["date"])
    marks = wide.index
    pos = pd.Series(np.arange(len(marks)), index=marks)

    d2c["i"] = d2c["date"].map(pos)
    d2c = d2c[d2c["i"].notna()].copy()
    d2c["i"] = d2c["i"].astype(int)
    j = d2c["i"] + HORIZON
    valid = j < len(marks)
    d2c = d2c[valid].copy()
    j = j[valid]
    r0 = np.array([wide.iloc[i][t] for i, t in zip(d2c["i"], d2c["tenor"])])
    r1 = np.array([wide.iloc[i][t] for i, t in zip(j, d2c["tenor"])])
    d2c["dR"] = r1 - r0
    d2c["exit_date"] = marks[j.to_numpy()]
    # The hold-out's back door, checked after the fact rather than trusted.
    assert d2c["exit_date"].max() <= pd.Timestamp(DESIGN_END), \
        "an exit mark escaped the design sample"
    assert d2c["date"].max() <= pd.Timestamp(LAST_SIGNAL_DAY), \
        "a signal day escaped the pre-registered last signal day"
    return d2c[(d2c["bucket_key"] != EXCLUDED_BUCKET) & d2c["z"].notna()
               & d2c["dR"].notna()].copy()


def stage_test() -> None:
    wide = _marks()
    use = attach_target(pd.read_parquet(CACHE / "panel_d2c.parquet"), wide)
    hurdles = _cost_hurdles().set_index("bucket_key")
    _log(f"test: {len(use)} bucket-days, {use['date'].nunique()} sessions, "
         f"{use['bucket_key'].nunique()} buckets, "
         f"{use['date'].min().date()} .. {use['date'].max().date()}")

    results = []

    def _record(cell, y, X, names, day_index, edge_series=None, n_bd=None):
        row = {"cell": cell, "n_obs": len(y), "n_days": int(pd.Index(day_index).nunique())}
        for lag, tag in ((HORIZON, "dk"), (0, "cl")):
            b, se, T, _ = ols_dk(y, X, day_index, lag)
            for nm, bi, si in zip(names, b, se):
                if nm == "const":
                    continue
                row[f"beta_{nm}"] = bi
                row[f"se_{nm}_{tag}"] = si
                row[f"t_{nm}_{tag}"] = bi / si if si > 0 else np.nan
                row[f"p_{nm}_{tag}"] = two_sided_p(bi / si, T - 1) if si > 0 else np.nan
        if edge_series is not None:
            e = np.asarray(edge_series, dtype=float)
            Xc = np.ones((len(e), 1))
            for lag, tag in ((HORIZON, "dk"), (0, "cl")):
                b, se, T, _ = ols_dk(e, Xc, day_index, lag)
                row[f"edge_bps"] = b[0]
                row[f"edge_se_{tag}"] = se[0]
                row[f"edge_t_{tag}"] = b[0] / se[0] if se[0] > 0 else np.nan
                row[f"edge_p_{tag}"] = (two_sided_p(b[0] / se[0], T - 1)
                                        if se[0] > 0 else np.nan)
        if n_bd is not None:
            row["n_bucket_days"] = n_bd
        results.append(row)
        return row

    # ---- PRIMARY: pooled, unconditional ---------------------------------
    y = use["dR"].to_numpy()
    z = use["z"].to_numpy()
    X = np.column_stack([np.ones(len(y)), z])
    edge = np.sign(z) * y
    prim = _record("POOLED_UNCONDITIONAL", y, X, ["const", "z"], use["date"],
                   edge_series=edge, n_bd=len(use))
    prim["mde_beta_dk"] = MDE_Z * prim["se_z_dk"]
    prim["mde_edge_dk"] = MDE_Z * prim["edge_se_dk"]
    prim["mean_abs_z"] = float(np.mean(np.abs(z)))

    # ---- SECONDARY: the one declared conditioner ------------------------
    sec = use[use["q"].notna()].copy()
    ys = sec["dR"].to_numpy()
    zs = sec["z"].to_numpy()
    qs = sec["q"].to_numpy()
    Xs = np.column_stack([np.ones(len(ys)), zs, zs * qs, qs])
    s_row = _record("POOLED_CONDITIONAL_D2D_RATIO", ys, Xs,
                    ["const", "z", "zq", "q"], sec["date"], n_bd=len(sec))
    s_row["mde_beta_dk"] = MDE_Z * s_row["se_zq_dk"]

    # ---- diagnostics: per bucket ----------------------------------------
    for b, sub in use.groupby("bucket_key", observed=True):
        yb = sub["dR"].to_numpy()
        zb = sub["z"].to_numpy()
        Xb = np.column_stack([np.ones(len(yb)), zb])
        row = _record(f"BUCKET::{b}", yb, Xb, ["const", "z"], sub["date"],
                      edge_series=np.sign(zb) * yb, n_bd=len(sub))
        row["mde_beta_dk"] = MDE_Z * row["se_z_dk"]
        row["mde_edge_dk"] = MDE_Z * row["edge_se_dk"]
        row["round_trip_bps"] = float(hurdles.loc[b, "round_trip_bps"])
        row["kill_threshold_bps"] = float(hurdles.loc[b, "kill_threshold_bps"])

    # ---- diagnostic: the RATE rule alone --------------------------------
    # The upfront-rule rows (30% of units) take their `tau` from the same
    # bucket's RATE-rule fit rather than from a fit on upfront residuals, which
    # saturates their |2p-1| towards 1. That is a WEIGHT distortion, not a
    # direction one -- the upfront sign comes from the edge-capture logic -- but
    # it is a deviation, so the primary is reported beside the panel that does
    # not contain it. Same code, same cached calls, same session calendar.
    calls_path = CACHE / "calls.parquet"
    if calls_path.exists():
        calls = pd.read_parquet(calls_path)
        ronly = calls[calls["rule"] == "RATE_VS_MID"]
        sessions = pd.to_datetime(sorted(set(
            pd.to_datetime(pd.read_parquet(CACHE / "panel_d2c.parquet")["date"]))))
        pr = panel_from_calls(ronly, assert_build_complete(), tag="_rateonly",
                              sessions=sessions)
        ur = attach_target(pr, wide)
        yr = ur["dR"].to_numpy()
        zr = ur["z"].to_numpy()
        Xr = np.column_stack([np.ones(len(yr)), zr])
        rr = _record("DIAGNOSTIC_RATE_RULE_ONLY", yr, Xr, ["const", "z"],
                     ur["date"], edge_series=np.sign(zr) * yr, n_bd=len(ur))
        rr["mde_edge_dk"] = MDE_Z * rr["edge_se_dk"]

    # ---- placebo: the flow shifted FORWARD five sessions -----------------
    pl = use.sort_values(["bucket_key", "date"]).copy()
    pl["z_placebo"] = pl.groupby("bucket_key", observed=True)["z"].shift(-HORIZON)
    pl = pl[pl["z_placebo"].notna()]
    yp = pl["dR"].to_numpy()
    zp = pl["z_placebo"].to_numpy()
    Xp = np.column_stack([np.ones(len(yp)), zp])
    _record("PLACEBO_FLOW_LEADS_RETURN", yp, Xp, ["const", "z"], pl["date"],
            edge_series=np.sign(zp) * yp, n_bd=len(pl))

    res = pd.DataFrame(results)

    # ---- the verdict ladder, applied ------------------------------------
    # `bucket_key` arrives from parquet as a CategoricalIndex and `hurdles` is
    # indexed by plain strings; multiplying the two aligns on nothing and the
    # pooled hurdle silently becomes NaN, which then loses every comparison in
    # the verdict ladder and lands on the last band by default. Cast, then
    # assert -- a hurdle that is not a number is not a hurdle.
    share = (use.groupby(use["bucket_key"].astype(str), observed=True).size()
             / len(use))
    tw = float((share * hurdles["kill_threshold_bps"].astype(float)).sum())
    if not np.isfinite(tw) or tw <= 0:
        raise RuntimeError(f"the trade-count-weighted pooled hurdle came out "
                           f"{tw!r}; buckets in the panel "
                           f"{sorted(share.index)} vs in costs.csv "
                           f"{sorted(hurdles.index)}")
    _log(f"test: trade-count-weighted pooled kill threshold {tw:.3f} bp")
    verdicts = []
    for _, r in res.iterrows():
        cell = r["cell"]
        if cell.startswith("BUCKET::"):
            kill = r["kill_threshold_bps"]
        elif cell.startswith("POOLED"):
            kill = tw
        else:
            kill = np.nan
        # The governing p and SE are the LARGER of the two estimators, because
        # the validation measured the prereg-literal day-clustered one
        # rejecting a true null 21.8% of the time at a nominal 5% under this
        # test's own overlap. Being wrong conservatively is the only acceptable
        # side of a cost hurdle.
        se = max(r.get("se_z_dk", np.nan), r.get("se_z_cl", np.nan))
        beta = r.get("beta_z", np.nan)
        p_beta = max(r.get("p_z_dk", np.nan), r.get("p_z_cl", np.nan))
        edge = r.get("edge_bps", np.nan)
        p_edge = max(r.get("edge_p_dk", np.nan), r.get("edge_p_cl", np.nan))
        mde = MDE_Z * se if se == se else np.nan
        se_edge = max(r.get("edge_se_dk", np.nan), r.get("edge_se_cl", np.nan))
        mde_edge = MDE_Z * se_edge if se_edge == se_edge else np.nan
        if (cell.startswith("PLACEBO") or cell.startswith("DIAGNOSTIC")
                or cell.endswith("D2D_RATIO")):
            v = "DIAGNOSTIC"
        elif r["n_bucket_days"] < 200:
            v = "UNINFORMATIVE_COVERAGE"
        elif beta < 0 and p_beta < ALPHA:
            v = "WRONG_SIGN"
        elif edge == edge and edge >= kill and p_edge < ALPHA:
            v = "PASS"
        elif mde_edge == mde_edge and mde_edge > kill:
            v = "UNINFORMATIVE_POWER"
        else:
            v = "UNINFORMATIVE_COST"
        verdicts.append({"cell": cell, "kill_threshold_bps": kill,
                         "p_beta_governing": p_beta, "p_edge_governing": p_edge,
                         "mde_beta": mde, "mde_edge_bps": mde_edge,
                         "verdict": v})
    # The per-bucket rows already carry a `kill_threshold_bps` from `_record`;
    # the verdict frame carries the one the ladder actually used (the pooled
    # cells' count-weighted hurdle). Keeping both under one name would print
    # the stale one beside a verdict decided by the other.
    res = res.drop(columns=["kill_threshold_bps"], errors="ignore")
    res = res.merge(pd.DataFrame(verdicts), on="cell", suffixes=("", "_v"))
    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "s2_results.csv", index=False)
    use.to_parquet(OUT / "s2_panel.parquet", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 60)
    show = ["cell", "n_bucket_days", "n_days", "beta_z", "se_z_dk", "t_z_dk",
            "p_z_dk", "t_z_cl", "edge_bps", "edge_se_dk", "edge_se_cl",
            "edge_p_dk", "mde_edge_bps", "kill_threshold_bps", "verdict"]
    print(res.reindex(columns=[c for c in show if c in res.columns]).to_string(index=False))
    _log(f"test: wrote {OUT / 's2_results.csv'}")


# ==========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["validate", "build", "target", "signal",
                                      "describe", "test", "status"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget-min", type=float, default=8.5)
    a = ap.parse_args()
    if a.stage == "validate":
        stage_validate()
    elif a.stage == "build":
        stage_build(a.workers, a.budget_min)
    elif a.stage == "target":
        stage_target()
    elif a.stage == "signal":
        stage_signal()
    elif a.stage == "describe":
        stage_describe()
    elif a.stage == "test":
        stage_test()
    elif a.stage == "status":
        days = tape_days()
        have = sum((UNIT_DIR / f"{d}.parquet").exists() for d in days)
        _log(f"{have}/{len(days)} days built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
