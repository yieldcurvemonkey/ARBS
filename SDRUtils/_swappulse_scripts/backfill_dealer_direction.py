"""Materialise dealer direction and the signed risk-bucket ladder into Postgres.

    price    per tape day, parallel, expensive  -> parquet on D:
    publish  whole window, one process, cheap   -> four Postgres tables
    status   what exists, per stage

WHY TWO STAGES
==============

Repricing plus key-rate risk costs ~180 s of CPU per tape day and needs the
local Citi minute curve store. Everything after it -- the tau calibration, the
three direction rules, the ladder, the daily indicator -- is arithmetic over
frames and runs over the whole history in minutes.

Splitting there means a defect in the cheap half is repaired by re-running
``publish``, not by re-pricing for a day. That is the single most valuable
property of this runner and it is why ``price`` writes parquet rather than
going straight to the database.

``price`` is deliberately widened to the whole tape (from 2024-03-01) while
``publish`` starts at ``indicator.SAMPLE_FLOOR`` (2024-07-01). The tau
calibration is a trailing 60-day window that must end **strictly before** the
day it calibrates, so publishing from the floor with a calibrated first day
needs roughly a quarter of priced history in front of it. Those extra days are
priced and never published.

WHAT MAKES A DAY DONE
=====================

Not the exit code, and not the presence of a file. ``price`` writes atomically
(``.tmp.parquet`` then ``os.replace``) and ``assert_priced_complete`` re-reads
every parquet for every day in the target set. A half-written frame is not a
day and a missing day is not a quiet market -- the tape has prints on every
session, so an empty read is a failed read.

The day set comes from the tape itself (``SELECT DISTINCT as_of_date``), never
from a calendar. A calendar disagrees with the tape on exactly the days that
matter.

THE SORT KEY IS LOAD-BEARING
============================

Units are sorted on ``snapshot.snap_instant(u.clocks.pricing)``, never on
``execution_timestamp``. The KRD block anchor is set by the first unit to ask
for a block, so an out-of-order unit gets a curve from *after* its own print.
Measured on 2026-04-01 during the backend work: 167 of 4,329 legs, caught by
``krd.LookaheadCurve``. That is the circularity the whole exercise exists to
prevent, arriving through a sort key.
"""
from __future__ import annotations

import os

# Before anything can import Caching, which reads the flag at import time.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
# The citivelo curve path must never open Excel from a batch worker.
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")

import argparse  # noqa: E402
import contextlib  # noqa: E402
import dataclasses  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import pathlib  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import warnings  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = str(pathlib.Path(__file__).resolve().parents[2])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

DEFAULT_CACHE = pathlib.Path(os.getenv("DD_FE_CACHE", r"D:\ddfe_cache"))

#: Price from here. The tape starts 2024-03-01; everything before the publish
#: floor exists only to give the first published day a trailing calibration.
PRICE_FLOOR = "2024-03-01"

#: Both indices the universe admits. FED_FUNDS is carried on every row so a
#: consumer can filter it -- the no-bias curve result was measured on SOFR.
INDICES = ("SOFR", "FED_FUNDS")

#: Trailing calibration, matching the backend's own choice.
CALIB_WINDOW_DAYS = 60
CALIB_MIN_GAP_DAYS = 1
CALIB_STEP_DAYS = 5

BLOCK_MINUTES = 60
DUST_FRAC = 0.0
DEAD_ZONE_DELTA = 0.05

DIR_RECEIVED = "RECEIVED"
DIR_PAID = "PAID"
DIR_ABSTAINED = "ABSTAINED"


# ==========================================================================
# small helpers
# ==========================================================================

def connect():
    import psycopg2
    return psycopg2.connect(resolve_pg_url())


def _atomic_parquet(df: pd.DataFrame, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else f


def _as_date(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return pd.Timestamp(v).date()


def _s(v):
    """A string field read back from parquet, or None. NEVER a NaN.

    ``if r["pkg_exclusion"]:`` was true on every package unit for a day, and
    the reason is worth stating because it will happen again. A column in
    ``UNIT_COLS`` that no row on that day assigns is created by ``reindex`` as
    an all-NaN **float64** column. Parquet round-trips it as ``float64``,
    ``r.get(col)`` hands back ``nan`` -- and ``bool(nan) is True``, so a
    presence test on a string field silently fires on every row.

    The failure had no symptom of its own: the package units were marked
    excluded with the reason ``nan``, which is neither a reason nor a null, and
    it surfaced only because the coverage accounting refuses a unit with no
    reason. Every string field read out of the stage cache goes through here.
    """
    if v is None:
        return None
    if isinstance(v, float):
        return None                       # NaN or a float where a string goes
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v)
    return s or None


def tape_days(start: str, end: str) -> list[str]:
    """The day set, from the tape. Never from a calendar."""
    conn = connect()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_sql(
                f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} "
                "WHERE as_of_date BETWEEN %(s)s AND %(e)s ORDER BY as_of_date",
                conn, params={"s": start, "e": end})
    finally:
        conn.close()
    if df.empty:
        raise RuntimeError(
            f"the tape has no days in {start}..{end}; that is a failed read, "
            "not an empty range")
    return [pd.Timestamp(d).date().isoformat() for d in df["as_of_date"]]


class Paths:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.units = self.root / "units"
        self.plegs = self.root / "plegs"
        self.krd = self.root / "krd"
        self.covlegs = self.root / "covlegs"
        self.tmp = self.root / "tmp"

    @property
    def stage_dirs(self):
        return (self.units, self.plegs, self.krd, self.covlegs)

    def mkdirs(self):
        for d in (*self.stage_dirs, self.tmp):
            d.mkdir(parents=True, exist_ok=True)

    def day_files(self, day: str):
        return [d / f"{day}.parquet" for d in self.stage_dirs]


# ==========================================================================
# STAGE 1 -- price and project one day
# ==========================================================================

UNIT_COLS = [
    # identity -- BOTH keys, see the schema module for why
    "unit_key", "package_id", "as_of_date",
    # shape
    "kind", "n_legs", "rate_index", "venue_class", "series",
    "is_lifecycle", "is_block", "is_capped",
    "tenor_years", "tenor_band", "special_tenor_type",
    # clocks
    "visibility_ts", "visibility_date", "visibility_source",
    "pricing_ts", "pricing_clock_field", "execution_ts", "event_ts",
    "report_lag_seconds",
    # routing + marks
    "rule", "deviation_bps", "npv_pay", "upfront", "upfront_source",
    "structure_dv01", "gross_pv01", "package_transaction_price",
    # pricing provenance
    "curve_name", "curve_timestamp", "snapshot_policy", "snapshot_lag_s",
    "failure", "failure_detail", "flags",
    # universe-stage exclusion (present on EVERY unit, kept or not)
    "universe_exclusion", "universe_exclusion_detail", "dv01_proxy",
    "risk_sanity_reason",
    # package rule, resolved structurally in stage 1 because KRD needs the
    # base orientation and `package_price.classify` is tau-free
    "pkg_dealer_sign", "pkg_base_orientation", "pkg_deviation_bps",
    "pkg_tieout_bps", "pkg_margin_bps", "pkg_exclusion", "pkg_flags",
]

PLEG_COLS = ["unit_key", "leg_index", "trade_id", "other_payment_amount",
             "npv_pay", "pv01", "mid_pct"]

COVLEG_COLS = ["unit_key", "bucket_key", "venue_class", "series",
               "dv01_proxy", "as_of_date", "visibility_date"]

_REP = None
_PROJ = None


def _engines():
    """One repricer + projector per worker process, built on first use.

    ``KrdProjector`` takes the repricer's own pricer, so the mid and the risk
    price against the same served snapshots -- not merely the same source.
    """
    global _REP, _PROJ
    if _REP is None:
        from SDRUtils.dealer_direction import krd as krd_mod
        from SDRUtils.dealer_direction import midprice, snapshot
        _REP = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
        _PROJ = krd_mod.KrdProjector(_REP.pricer, block_minutes=BLOCK_MINUTES,
                                     dust_frac=DUST_FRAC)
    return _REP, _PROJ


def _first_non_new_trade(unit_legs) -> str:
    lt = unit_legs.loc[~unit_legs["_is_new_trade"], "lifecycle_type"]
    return str(lt.iloc[0]) if len(lt) else "NEW_TRADE"


def _clocks_for(unit_legs, row):
    """Clocks for ANY unit, kept or excluded.

    ``universe.build_universe`` builds clocks only for the units it keeps, but
    the coverage denominator needs a visibility date for the excluded ones too
    -- otherwise the excluded DV01 is stamped on a different clock from the
    DV01 it is the denominator of. Reproduced here from the same inputs, and
    asserted equal against ``build_universe``'s own clocks on every kept unit
    of every day (``_assert_clocks_agree``), so the two cannot drift.
    """
    from SDRUtils.dealer_direction import universe
    head = unit_legs.iloc[0].to_dict()
    lifecycle = ("NEW_TRADE" if bool(unit_legs["_is_new_trade"].all())
                 else _first_non_new_trade(unit_legs))
    return universe.build_clocks(
        head,
        lifecycle_type=lifecycle,
        is_block=bool(row["is_block"]),
        is_capped=bool(row["is_capped"]),
        cleared=head.get("cleared"),
        platform_identifier=head.get("platform_identifier"),
    )


def _assert_clocks_agree(units, clock_by_group, u) -> None:
    """The helper above must reproduce ``build_universe`` exactly."""
    key_by_unit = {}
    for group, row in u.iterrows():
        key_by_unit[str(row["unit_key"])] = group
    for unit in units:
        group = key_by_unit.get(unit.unit_key)
        mine = clock_by_group.get(group)
        if mine is None:
            raise AssertionError(
                f"no locally-built clocks for kept unit {unit.unit_key!r}")
        theirs = unit.clocks
        # `pricing` is in this list deliberately. It is the clock F-22 exists
        # about -- a unit sorted or anchored on the wrong one gets a curve
        # from after its own print -- and it is the field this reimplementation
        # persists into the audit trail, so it is the one that must not drift.
        for field in ("pricing", "visibility", "execution", "event",
                      "visibility_source"):
            a, b = getattr(mine[0], field), getattr(theirs, field)
            if pd.isna(a) if not isinstance(a, str) else False:
                if not (pd.isna(b) if not isinstance(b, str) else False):
                    raise AssertionError(f"{unit.unit_key}: {field} differs")
                continue
            if a != b:
                raise AssertionError(
                    f"{unit.unit_key}: locally-built {field}={a!r} differs "
                    f"from build_universe's {b!r}")


def route_rule(unit) -> str | None:
    """Which rule this unit is decided by -- ``kind`` FIRST.

    ``conventions.base_orientation(PKG, n, RULE_UPFRONT)`` *succeeds* and
    returns ``(1,)*n``, so a leg-count-blind router silently sends a package
    into the upfront branch with every leg pointing the same way. Copied from
    ``dd_nb.route_rule`` for exactly that reason.
    """
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import package_price as pp
    if unit.kind == conv.PKG:
        return pp.RULE_PACKAGE_PRICE
    rule = conv.RULE_UPFRONT if unit.upfront is not None else conv.RULE_RATE
    try:
        conv.base_orientation(unit.kind, unit.n_legs, rule)
    except conv.UnorientableUnit:
        return None
    return rule


def price_one_day(day: str, paths: Paths) -> dict:
    """Legs -> units -> mid/NPV -> package orientation -> KRD. Writes 4 parquets."""
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import ladder as ladder_mod
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction import probability as P
    from SDRUtils.dealer_direction import snapshot, universe
    from SDRUtils.dealer_direction.types import DirectionCall

    t0 = time.perf_counter()
    conn = connect()
    try:
        legs = universe.load_legs(conn, day, day)
    finally:
        conn.close()
    if legs.empty:
        raise RuntimeError(
            f"{day}: the tape returned no legs. A session with no prints is a "
            "failed read, not a quiet market.")

    ann = universe.annotate_legs(legs)
    u = universe.unit_frame(legs)
    units, _excluded = universe.build_universe(legs)

    by_group = {k: v for k, v in ann.groupby("_unit_group", sort=False)}
    clock_by_group = {
        g: _clocks_for(by_group[g].reset_index(drop=True), u.loc[g])
        for g in u.index
    }
    _assert_clocks_agree(units, clock_by_group, u)

    # ---- coverage: maturity-point allocation of gross |DV01|, INDICATOR 2 ---
    # One row per LEG, bucketed on its own maturity, carrying the unit key so
    # `publish` can attach whichever reason finally applied. Stamped on the
    # unit's visibility date, because that is the clock the ladder aggregates
    # on and a coverage denominator on a different clock is not a denominator.
    group_meta = {}
    for g in u.index:
        row = u.loc[g]
        clocks = clock_by_group[g][0]
        group_meta[g] = {
            "venue_class": str(row["venue_class"]),
            "series": (ladder_mod.SERIES_LIFECYCLE if bool(row["is_lifecycle"])
                       else ladder_mod.SERIES_FLOW),
            "unit_key": str(row["unit_key"]),
            "visibility_date": ladder_mod.visibility_date(clocks.visibility),
        }
    years = ((pd.to_datetime(ann["expiration_date"], errors="coerce")
              - pd.Timestamp(day)).dt.days / 365.25)
    cov = pd.DataFrame({
        "unit_key": [group_meta[g]["unit_key"] for g in ann["_unit_group"]],
        "bucket_key": [ind.bucket_for_years(max(float(y), 0.0))
                       if pd.notna(y) else None for y in years],
        "venue_class": [group_meta[g]["venue_class"] for g in ann["_unit_group"]],
        "series": [group_meta[g]["series"] for g in ann["_unit_group"]],
        "dv01_proxy": ann["_dv01_proxy"].astype(float),
        "as_of_date": day,
        "visibility_date": [group_meta[g]["visibility_date"]
                            for g in ann["_unit_group"]],
    })
    cov = (cov.groupby(["unit_key", "bucket_key", "venue_class", "series",
                        "as_of_date", "visibility_date"],
                       dropna=False, observed=True)["dv01_proxy"]
           .sum().reset_index().reindex(columns=COVLEG_COLS))

    # ---- static rows for EVERY unit, kept or excluded ----------------------
    rows_by_key: dict[str, dict] = {}
    for g in u.index:
        row = u.loc[g]
        clocks, clock_field = clock_by_group[g]
        legs_g = by_group[g]
        tenor = _f(pd.to_numeric(legs_g["tenor_years"], errors="coerce").max())
        stt = legs_g["special_tenor_type"].iloc[0]
        rows_by_key[str(row["unit_key"])] = {
            "unit_key": str(row["unit_key"]),
            "package_id": str(row["package_id"]),
            "as_of_date": day,
            "kind": str(row["kind"]),
            "n_legs": int(row["n_legs"]),
            "rate_index": str(row["rate_index"]),
            "venue_class": str(row["venue_class"]),
            "series": (ladder_mod.SERIES_LIFECYCLE if bool(row["is_lifecycle"])
                       else ladder_mod.SERIES_FLOW),
            "is_lifecycle": bool(row["is_lifecycle"]),
            "is_block": bool(row["is_block"]),
            "is_capped": bool(row["is_capped"]),
            "tenor_years": tenor,
            "tenor_band": P.tenor_band(tenor),
            "special_tenor_type": ("STANDARD" if stt is None or pd.isna(stt)
                                   else str(stt)),
            "visibility_ts": clocks.visibility,
            "visibility_date": ladder_mod.visibility_date(clocks.visibility),
            "visibility_source": clocks.visibility_source,
            "pricing_ts": clocks.pricing,
            "pricing_clock_field": clock_field,
            "execution_ts": clocks.execution,
            "event_ts": clocks.event,
            "report_lag_seconds": _f(clocks.report_lag_seconds),
            "rule": None,
            "upfront": _f(row["upfront"]),
            "upfront_source": (None if pd.isna(row["upfront_source"])
                               else str(row["upfront_source"])),
            "package_transaction_price": _f(
                legs_g["package_transaction_price"].iloc[0]),
            "universe_exclusion": (None if pd.isna(row["exclusion"])
                                   else str(row["exclusion"])),
            "universe_exclusion_detail": (None if pd.isna(row["exclusion_detail"])
                                          else str(row["exclusion_detail"])),
            "dv01_proxy": _f(row["dv01_proxy"]),
            "risk_sanity_reason": _risk_reason(legs_g),
            "failure": None,
        }

    # ---- the pricing population -------------------------------------------
    pop, rules = [], {}
    for unit in units:
        if unit.rate_index not in INDICES:
            continue
        rule = route_rule(unit)
        if rule is None:
            # No quote convention orients it. `universe` already excluded the
            # families it knows about; this is the residue, and it must be
            # named rather than dropped or the coverage stops summing.
            rows_by_key[unit.unit_key]["failure"] = "UNORIENTABLE_PKG"
            continue
        pop.append(unit)
        rules[unit.unit_key] = rule
        rows_by_key[unit.unit_key]["rule"] = rule

    # THE SORT KEY. See the module docstring.
    pop.sort(key=lambda x: snapshot.snap_instant(x.clocks.pricing))

    rep, proj = _engines()
    pleg_rows: list[dict] = []
    krd_calls: list = []
    krd_units: list = []

    with rep.day_scope():
        for unit in pop:
            key = unit.unit_key
            rule = rules[key]
            base = rows_by_key[key]
            out = rep.price_unit(unit)
            base.update({
                "curve_name": out.pricing.curve_name,
                "curve_timestamp": out.pricing.curve_timestamp,
                "snapshot_policy": out.pricing.snapshot_policy,
                "snapshot_lag_s": _f(out.pricing.snapshot_lag_seconds),
                "npv_pay": _f(out.pricing.npv_pay),
                "structure_dv01": _f(out.pricing.structure_dv01),
                "gross_pv01": _f(out.gross_pv01),
                "failure": out.failure,
                "failure_detail": out.failure_detail,
                "flags": ",".join(out.flags) if out.flags else None,
            })
            if out.failure is not None:
                krd_units.append(unit)
                krd_calls.append(DirectionCall(
                    unit_key=key, rule=rule, deviation_bps=None, p=None,
                    signed_weight=None, dealer_sign=0, exclusion=out.failure))
                continue

            # The fee and the NPV are paired POSITIONALLY, and a package's
            # sign solve is only as good as that pairing: match the wrong fee
            # to the wrong leg and `package_price.classify` returns a
            # confident orientation for a scrambled input, with no symptom.
            # Measured on 2026-04-01 (`scratch/ddfe09_leg_alignment.py`): 0
            # mismatches over 621 multi-leg units. Asserted anyway, because
            # "it held on the day I looked" is not an invariant.
            for i, leg in enumerate(out.legs):
                want = str(unit.legs["trade_id"].iloc[i])
                if str(leg.trade_id) != want:
                    raise AssertionError(
                        f"unit {key!r} leg {i}: the repriced leg is "
                        f"{leg.trade_id!r} but unit.legs holds {want!r}; the "
                        "per-leg fee would be paired with the wrong NPV")
                pleg_rows.append({
                    "unit_key": key, "leg_index": i,
                    "trade_id": str(leg.trade_id),
                    "other_payment_amount": _f(
                        unit.legs["other_payment_amount"].iloc[i]),
                    "npv_pay": _f(leg.npv_pay),
                    "pv01": _f(leg.pv01),
                    "mid_pct": _f(leg.mid_pct),
                })

            if rule == conv.RULE_RATE:
                traded = [float(l["fixed_rate"]) * 100.0
                          for _, l in unit.legs.iterrows()]
                tp = conv.structure_price(traded, unit.kind, unit.n_legs, rule)
                mp = conv.structure_price(list(out.pricing.leg_mid_pct),
                                          unit.kind, unit.n_legs, rule)
                base["deviation_bps"] = _f(tp - mp)

            call = DirectionCall(
                unit_key=key, rule=rule, deviation_bps=base.get("deviation_bps"),
                p=None, signed_weight=None, dealer_sign=0)

            if rule == pp.RULE_PACKAGE_PRICE:
                # Structural only: `package_price.classify` reads no tau, and
                # KRD needs its base orientation. The borrowed `p` is attached
                # in `publish`, where the calibration lives.
                sub = [r for r in pleg_rows if r["unit_key"] == key]
                sub.sort(key=lambda r: r["leg_index"])
                c = pp.classify(
                    opas=[r["other_payment_amount"] for r in sub],
                    package_price=base["package_transaction_price"],
                    npv_pays=[r["npv_pay"] for r in sub],
                    pv01s=[r["pv01"] for r in sub],
                    structure_dv01=base["structure_dv01"],
                    is_lifecycle=bool(unit.is_lifecycle),
                    ufro_sum=None)
                base.update({
                    "pkg_dealer_sign": int(c.dealer_sign),
                    "pkg_base_orientation": (
                        None if c.base_orientation is None
                        else json.dumps([int(x) for x in c.base_orientation])),
                    "pkg_deviation_bps": _f(c.deviation_bps),
                    "pkg_tieout_bps": _f(c.tieout_bps),
                    "pkg_margin_bps": _f(c.margin_bps),
                    "pkg_exclusion": c.exclusion,
                    "pkg_flags": ",".join(c.flags) if c.flags else None,
                })
                call = DirectionCall(
                    unit_key=key, rule=rule, deviation_bps=_f(c.deviation_bps),
                    p=None, signed_weight=None, dealer_sign=int(c.dealer_sign),
                    exclusion=c.exclusion,
                    base_orientation=(None if c.base_orientation is None
                                      else tuple(c.base_orientation)))

            krd_units.append(unit)
            krd_calls.append(call)

    with proj.day_scope():
        krd_frame, krd_fail = proj.krd_frame(krd_units, krd_calls)

    # A KRD-stage failure is a named exclusion, not a silent absence.
    if len(krd_fail):
        for _, fr in krd_fail.iterrows():
            row = rows_by_key.get(str(fr["unit_key"]))
            if row is not None and row.get("failure") is None:
                row["failure"] = str(fr["failure_reason"])
                row["failure_detail"] = str(fr.get("failure_detail") or "")[:400]

    units_df = pd.DataFrame(list(rows_by_key.values())).reindex(columns=UNIT_COLS)
    _atomic_parquet(units_df, paths.units / f"{day}.parquet")
    _atomic_parquet(pd.DataFrame(pleg_rows).reindex(columns=PLEG_COLS),
                    paths.plegs / f"{day}.parquet")
    _atomic_parquet(pd.DataFrame(krd_frame).reindex(
        columns=["unit_key", "bucket_space", "bucket_key", "dv01_if_received"]),
        paths.krd / f"{day}.parquet")
    _atomic_parquet(cov, paths.covlegs / f"{day}.parquet")

    priced = int(units_df["rule"].notna().sum()
                 - units_df.loc[units_df["rule"].notna(), "failure"].notna().sum())
    return {"day": day, "legs": int(len(legs)), "units": int(len(units_df)),
            "population": int(len(pop)), "priced": priced,
            "krd_rows": int(len(krd_frame)), "krd_fail": int(len(krd_fail)),
            "cov_rows": int(len(cov)),
            "seconds": time.perf_counter() - t0}


def _risk_reason(legs_g) -> str | None:
    if "_risk_reason" not in legs_g.columns:
        return None
    vals = [str(v) for v in legs_g["_risk_reason"] if isinstance(v, str) and v]
    return vals[0][:200] if vals else None


def _price_worker(args):
    day, root = args
    try:
        return price_one_day(day, Paths(pathlib.Path(root)))
    except Exception as exc:  # noqa: BLE001
        return {"day": day,
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": traceback.format_exc()[-1500:]}


def stage_price(days: list[str], paths: Paths, workers: int,
                budget_min: float) -> int:
    import concurrent.futures as cf

    paths.mkdirs()
    todo = [d for d in days if not all(p.exists() for p in paths.day_files(d))]
    print(f"price: {len(days)} target days, {len(todo)} to do, "
          f"{workers} workers, budget {budget_min:.0f} min", flush=True)
    if not todo:
        return 0

    deadline = time.time() + budget_min * 60.0
    done = errs = 0
    t0 = time.time()
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        pending, it = set(), iter(todo)
        for _ in range(workers):
            nxt = next(it, None)
            if nxt is not None:
                pending.add(pool.submit(_price_worker, (nxt, str(paths.root))))
        while pending:
            fin, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in fin:
                r = fut.result()
                done += 1
                if "error" in r:
                    errs += 1
                    print(f"  {r['day']}: ERROR {r['error']}", flush=True)
                    print(r.get("traceback", ""), flush=True)
                else:
                    print(f"  {r['day']}: {r['units']} units, {r['priced']} "
                          f"priced, {r['krd_rows']} krd rows, "
                          f"{r['seconds']:.0f}s  [{done}/{len(todo)}]",
                          flush=True)
                if time.time() < deadline:
                    nxt = next(it, None)
                    if nxt is not None:
                        pending.add(pool.submit(_price_worker,
                                                (nxt, str(paths.root))))
    wall = time.time() - t0
    print(f"price: {done} days in {wall / 60:.1f} min "
          f"({wall / max(done, 1):.1f} s/day wall), {errs} errors", flush=True)
    return 1 if errs else 0


def assert_priced_complete(days: list[str], paths: Paths) -> None:
    """The readable day set must equal the target set.

    ``exists()`` is not enough: a truncated parquet exists. Every file is
    re-read.
    """
    missing, unreadable = [], []
    for day in days:
        for p in paths.day_files(day):
            if not p.exists():
                missing.append(str(p))
                continue
            try:
                pd.read_parquet(p)
            except Exception as exc:  # noqa: BLE001
                unreadable.append(f"{p}: {type(exc).__name__}")
    if missing or unreadable:
        raise RuntimeError(
            f"priced stage incomplete: {len(missing)} missing file(s), "
            f"{len(unreadable)} unreadable. First few: "
            f"{(missing + unreadable)[:5]}")


# ==========================================================================
# STAGE 2 -- calibrate, classify, aggregate, publish
# ==========================================================================

@dataclasses.dataclass
class UnitShim:
    """Everything ``ladder._unit_meta`` reads, and nothing else.

    Rebuilding real ``types.Unit`` objects in `publish` would mean re-reading
    and re-annotating every day's legs. ``_unit_meta`` touches thirteen scalar
    attributes; this carries exactly those, so the ladder's own validation
    still runs unchanged over them.
    """
    unit_key: str
    venue_class: str
    is_lifecycle: bool
    clocks: object
    as_of_date: object
    rate_index: str
    kind: str
    n_legs: int
    is_block: bool
    is_capped: bool


@dataclasses.dataclass(frozen=True)
class ShimClocks:
    pricing: object
    execution: object
    event: object
    visibility: object
    visibility_source: str


def _shim(r) -> UnitShim:
    return UnitShim(
        unit_key=str(r["unit_key"]),
        venue_class=str(r["venue_class"]),
        is_lifecycle=bool(r["is_lifecycle"]),
        clocks=ShimClocks(
            pricing=r["pricing_ts"], execution=r["execution_ts"],
            event=r["event_ts"], visibility=r["visibility_ts"],
            visibility_source=str(r["visibility_source"])),
        as_of_date=_as_date(r["as_of_date"]),
        rate_index=str(r["rate_index"]),
        kind=str(r["kind"]),
        n_legs=int(r["n_legs"]),
        is_block=bool(r["is_block"]),
        is_capped=bool(r["is_capped"]),
    )


@contextlib.contextmanager
def probability_clip():
    """Let a ``p`` one machine epsilon past 1 through, and nothing else.

    ``upfront.p_marginalised`` is a logistic-normal integral and on a deeply
    off-market print it returns ``1.0000000000000002``. ``signed_weight``
    refuses it -- rightly, it cannot tell that from a real 1.4 -- and the pass
    dies. Dropping those units instead drops precisely the largest, most
    confident upfront calls, which is a biased sample. Clipped by 1e-9 and no
    more, with the firing count returned so a guard that fires on half the
    population cannot hide.
    """
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import ladder as ladder_mod
    from SDRUtils.dealer_direction import probability as P
    from SDRUtils.dealer_direction import upfront as U

    original = conv.signed_weight
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

    # Every consumer reaches this through the module object rather than by
    # importing the name, so rebinding the attribute is enough -- checked.
    for m in (U, P, ladder_mod):
        assert getattr(m, "conventions", None) is conv or \
            getattr(m, "conv", None) is conv, \
            f"{m.__name__} does not reach conventions through the module object"
    conv.signed_weight = guarded
    try:
        yield state
    finally:
        conv.signed_weight = original


def build_calibrations(paths: Paths, days: list[str], *, refresh: bool = False):
    """Trailing rolling mixture fits over the whole priced history.

    The backend's calibration pickle stops at 2025-08-22 -- it was built for a
    design window that ends there -- so it cannot serve this window. Refitted
    here from this runner's own deviations, with the same window / gap / step
    the backend used.

    **Cached, because it is the only slow thing in `publish`.** Measured: 22
    rolling fits over 112 priced days cost ~14 minutes, so the full 610-day
    window is a couple of hours of mixture MLEs. The whole point of splitting
    `price` from `publish` is that a defect in the ladder or the indicator is
    repaired in minutes; a two-hour refit on every run would take that back.

    The key is the exact input, not the window bounds: the day list, the fit
    parameters, and a **hash of the deviation values themselves**.

    A count would not do, and the difference matters. A re-price that changes
    what the deviations *are* without changing how many there are -- a curve
    fix, a snapshot-policy change, the exact class of edit that motivates a
    re-price at all -- would hit a stale cache and publish a calibration
    fitted to numbers that no longer exist, with nothing anywhere to say so.
    """
    import hashlib
    import pickle

    from SDRUtils.dealer_direction import probability as P

    cols = ["unit_key", "as_of_date", "rule", "deviation_bps", "venue_class",
            "rate_index", "kind", "special_tenor_type", "tenor_band", "failure"]
    parts = []
    for day in days:
        df = pd.read_parquet(paths.units / f"{day}.parquet", columns=cols)
        df = df[(df["rule"] == "RATE_VS_MID") & df["failure"].isna()
                & df["deviation_bps"].notna()]
        parts.append(df.drop(columns=["failure", "rule", "unit_key"]))
    cal_df = pd.concat(parts, ignore_index=True)
    cal_df = cal_df.rename(columns={"kind": "structure"})
    cal_df["as_of_date"] = pd.to_datetime(cal_df["as_of_date"]).dt.date
    print(f"calibration input: {len(cal_df):,} RATE_VS_MID deviations over "
          f"{cal_df['as_of_date'].nunique()} days", flush=True)
    content = int(pd.util.hash_pandas_object(cal_df, index=False).sum())
    key = hashlib.sha256(
        ("|".join(days)
         + f"|{CALIB_WINDOW_DAYS}|{CALIB_MIN_GAP_DAYS}|{CALIB_STEP_DAYS}"
         + f"|{len(cal_df)}|{content}").encode()
    ).hexdigest()[:16]
    cache = paths.root / "calibrations" / f"{key}.pkl"
    if cache.exists() and not refresh:
        with open(cache, "rb") as fh:
            cals = pickle.load(fh)
        print(f"calibration: {len(cals)} rolling fits from cache "
              f"({cache.name}), {min(cals)} .. {max(cals)}", flush=True)
        return cals

    t0 = time.time()
    cals = P.rolling_calibrations(cal_df, window_days=CALIB_WINDOW_DAYS,
                                  min_gap_days=CALIB_MIN_GAP_DAYS,
                                  step_days=CALIB_STEP_DAYS)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(cals, fh)
    os.replace(tmp, cache)
    print(f"calibration: {len(cals)} rolling fits in "
          f"{(time.time() - t0) / 60:.1f} min, {min(cals)} .. {max(cals)} "
          f"-> {cache.name}", flush=True)
    return cals


class TauSet:
    """The most recent fit whose window ends **strictly before** the day.

    Requiring an exact-date key would silently drop four days in five, since
    the fits step every 5 days. Requiring ``hi < d`` is what keeps a day's own
    deviations out of its own ``b0``.
    """

    def __init__(self, cals: dict):
        self._keys = sorted(cals)
        self._cals = cals
        self._memo: dict = {}

    def for_day(self, d):
        import bisect
        d = _as_date(d)
        hit = self._memo.get(d)
        if hit is not None:
            return hit
        i = bisect.bisect_right(self._keys, d) - 1
        while i >= 0:
            lo, hi, cal = self._cals[self._keys[i]]
            if _as_date(hi) < d:
                self._memo[d] = cal
                return cal
            i -= 1
        return None


def classify_day(units_df, plegs_df, tau_set):
    """The three rules -> ``(DirectionCall list, per-unit dict)``."""
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction import probability as P
    from SDRUtils.dealer_direction import types as T
    from SDRUtils.dealer_direction import upfront as U

    fit_memo: dict = {}
    calls, extra = [], {}
    plegs = ({} if plegs_df is None or plegs_df.empty
             else {k: v.sort_values("leg_index")
                   for k, v in plegs_df.groupby("unit_key", sort=False)})

    for r in units_df.to_dict("records"):
        key = str(r["unit_key"])
        # Every string field goes through `_s`. See its docstring: a column no
        # row assigned that day comes back as float NaN, and `bool(nan)` is
        # True, so a bare presence test fires on every row.
        rule = _s(r.get("rule"))
        universe_exclusion = _s(r.get("universe_exclusion"))
        failure = _s(r.get("failure"))
        pkg_exclusion = _s(r.get("pkg_exclusion"))
        pkg_orient = _s(r.get("pkg_base_orientation"))

        out = {"p": None, "signed_weight": None, "dealer_sign": 0,
               "tau_bucket": None, "tau_bps": None, "mid_bias_bps": None,
               "in_dead_zone": False, "exclusion": None,
               "deviation_bps": _f(r.get("deviation_bps"))}

        if universe_exclusion:
            out["exclusion"] = universe_exclusion
        elif rule is None:
            out["exclusion"] = failure or T.EXCL_UNORIENTABLE
        elif failure is not None:
            out["exclusion"] = failure

        if out["exclusion"] is not None:
            calls.append(T.DirectionCall(
                unit_key=key, rule=rule or conv.RULE_RATE,
                deviation_bps=_f(r.get("deviation_bps")), p=None,
                signed_weight=None, dealer_sign=0,
                exclusion=out["exclusion"]))
            extra[key] = out
            continue

        cal = tau_set.for_day(r["as_of_date"])
        if cal is None:
            out["exclusion"] = "NO_CALIBRATION"
            calls.append(T.DirectionCall(
                unit_key=key, rule=r["rule"], deviation_bps=None, p=None,
                signed_weight=None, dealer_sign=0, exclusion="NO_CALIBRATION"))
            extra[key] = out
            continue

        bk = P.BucketKey(venue_class=str(r["venue_class"]),
                         rate_index=str(r["rate_index"]),
                         structure=str(r["kind"]),
                         special_tenor_type=str(r["special_tenor_type"]),
                         tenor_band=str(r["tenor_band"]))
        memo = (id(cal), bk)
        fit = fit_memo.get(memo)
        if fit is None:
            fit = cal.for_key(bk)
            fit_memo[memo] = fit

        if rule == conv.RULE_RATE:
            dev = _f(r["deviation_bps"])
            if dev is None:
                out["exclusion"] = T.EXCL_PRICING_ERROR
                calls.append(T.DirectionCall(
                    unit_key=key, rule=rule, deviation_bps=None, p=None,
                    signed_weight=None, dealer_sign=0,
                    exclusion=T.EXCL_PRICING_ERROR))
                extra[key] = out
                continue
            c = P.direction_probability(dev, fit, DEAD_ZONE_DELTA)
            # `dealer_side` on the BIAS-CORRECTED deviation: p is a function of
            # (dev - b0), so the raw deviation disagrees with the weight on any
            # print between 0 and b0 and the ladder refuses that pair.
            side = conv.dealer_side(dev - fit.b0)
            out.update({"deviation_bps": dev, "p": c.p,
                        "signed_weight": c.signed_weight, "dealer_sign": side,
                        "tau_bucket": c.tau_bucket, "tau_bps": c.tau_bps,
                        "mid_bias_bps": c.mid_bias_bps,
                        "in_dead_zone": bool(c.in_dead_zone)})
            calls.append(T.DirectionCall(
                unit_key=key, rule=conv.RULE_RATE, deviation_bps=dev, p=c.p,
                signed_weight=c.signed_weight, dealer_sign=side,
                tau_bucket=c.tau_bucket, tau_bps=c.tau_bps,
                mid_bias_bps=c.mid_bias_bps,
                in_dead_zone=bool(c.in_dead_zone)))

        elif rule == conv.RULE_UPFRONT:
            tau = U.TauUpfront(
                tau_bps=fit.tau, bias_bps=fit.b0, half_spread_bps=fit.h,
                sigma_bps=fit.s, n=fit.n_trimmed,
                population=(U.POPULATION_LIFECYCLE if r["is_lifecycle"]
                            else U.POPULATION_FLOW),
                bucket=fit.bucket)
            c = U.classify(npv_pay=_f(r["npv_pay"]), upfront=_f(r["upfront"]),
                           structure_dv01=_f(r["structure_dv01"]),
                           upfront_source=_s(r["upfront_source"]),
                           is_lifecycle=bool(r["is_lifecycle"]),
                           is_capped=bool(r["is_capped"]),
                           tau=tau, mid_sigma_bps=fit.s, mid_bias_bps=fit.b0)
            if c.exclusion is not None or c.p is None or c.signed_weight is None:
                reason = c.exclusion or T.EXCL_PRICING_ERROR
                out.update({"exclusion": reason,
                            "deviation_bps": _f(c.edge_bps)})
                calls.append(T.DirectionCall(
                    unit_key=key, rule=conv.RULE_UPFRONT,
                    deviation_bps=_f(c.edge_bps), p=None, signed_weight=None,
                    dealer_sign=0, exclusion=reason))
                extra[key] = out
                continue
            # The point call and the marginalised p are two estimators and are
            # allowed to disagree inside the SIGN_FRAGILE set -- but the ladder
            # aggregates 2p-1, so the weight's own side is what is loaded.
            w = float(c.signed_weight)
            side = 1 if w > 0 else (-1 if w < 0 else 0)
            out.update({"deviation_bps": _f(c.edge_bps), "p": c.p,
                        "signed_weight": w, "dealer_sign": side,
                        "tau_bucket": c.tau_bucket, "tau_bps": c.tau_bps,
                        "mid_bias_bps": c.mid_bias_bps})
            calls.append(T.DirectionCall(
                unit_key=key, rule=conv.RULE_UPFRONT,
                deviation_bps=_f(c.edge_bps), p=c.p, signed_weight=w,
                dealer_sign=side, tau_bucket=c.tau_bucket, tau_bps=c.tau_bps,
                mid_bias_bps=c.mid_bias_bps))

        elif rule == pp.RULE_PACKAGE_PRICE:
            if pkg_exclusion:
                out.update({"exclusion": pkg_exclusion,
                            "deviation_bps": _f(r.get("pkg_deviation_bps"))})
                calls.append(T.DirectionCall(
                    unit_key=key, rule=pp.RULE_PACKAGE_PRICE,
                    deviation_bps=_f(r.get("pkg_deviation_bps")), p=None,
                    signed_weight=None, dealer_sign=0,
                    exclusion=pkg_exclusion))
                extra[key] = out
                continue
            dev = _f(r.get("pkg_deviation_bps"))
            orient = pkg_orient
            if dev is None or not orient:
                out["exclusion"] = T.EXCL_PRICING_ERROR
                calls.append(T.DirectionCall(
                    unit_key=key, rule=pp.RULE_PACKAGE_PRICE, deviation_bps=dev,
                    p=None, signed_weight=None, dealer_sign=0,
                    exclusion=T.EXCL_PRICING_ERROR))
                extra[key] = out
                continue
            # No package tau exists. Borrow the pooled rate-rule fit with b0
            # forced to zero: the rate-rule bias is in bp of the structure's
            # quoted price and this deviation is in bp of package DV01, so it
            # does not transfer -- and zeroing it makes sign(2p-1) equal
            # dealer_side(dev) by construction.
            p = float(P.p_customer_paid(dev, dataclasses.replace(fit, b0=0.0)))
            if r["is_lifecycle"]:
                p = 1.0 - p
            w = conv.signed_weight(p)
            side = int(_f(r["pkg_dealer_sign"]) or 0)
            if side != 0 and w != 0.0 and (w > 0) != (side > 0):
                raise AssertionError(
                    f"unit {key!r}: the borrowed p landed on the opposite side "
                    f"from package_price's own dealer_sign ({side}); the "
                    "b0-zeroing that makes those identical has been broken")
            label = f"BORROWED_B0_ZEROED:{fit.bucket}"
            half = P.dead_zone_half_width_bps(fit.tau)
            out.update({"deviation_bps": dev, "p": p, "signed_weight": w,
                        "dealer_sign": side, "tau_bucket": label,
                        "tau_bps": fit.tau, "mid_bias_bps": 0.0,
                        "in_dead_zone": bool(abs(dev) < half)})
            calls.append(T.DirectionCall(
                unit_key=key, rule=pp.RULE_PACKAGE_PRICE, deviation_bps=dev,
                p=p, signed_weight=w, dealer_sign=side, tau_bucket=label,
                tau_bps=fit.tau, mid_bias_bps=0.0,
                in_dead_zone=bool(abs(dev) < half),
                base_orientation=tuple(json.loads(orient))))
        else:
            raise ValueError(f"unrouted rule {rule!r}")

        extra[key] = out

    # Every unit leaves with either a probability or a reason, and the reason
    # is a string. Asserted rather than assumed: a NaN exclusion is neither a
    # reason nor a null, and it reads downstream as "excluded" with nothing to
    # say why.
    for key, out in extra.items():
        ex = out["exclusion"]
        if ex is not None and not isinstance(ex, str):
            raise TypeError(
                f"unit {key!r} carries a non-string exclusion {ex!r} "
                f"({type(ex).__name__}); see `_s`")
        if ex is None and (out["p"] is None or out["signed_weight"] is None):
            raise ValueError(
                f"unit {key!r} has neither a probability nor a reason")

    return calls, extra


def direction_label(dealer_sign, exclusion) -> str:
    """The word the front end renders.

    ``+1`` is ``RECEIVED``: customer pays fixed -> dealer received fixed ->
    dealer long duration -> ``delta_dv01 > 0``. This is the one mapping that,
    if inverted, teaches the reader the wrong thing permanently, so it is
    written once, here, and pinned by a hand-traced test.
    """
    if exclusion is not None:
        return DIR_ABSTAINED
    s = int(dealer_sign or 0)
    if s > 0:
        return DIR_RECEIVED
    if s < 0:
        return DIR_PAID
    return DIR_ABSTAINED


UNIT_DB_COLUMNS = [
    "package_id", "unit_key", "as_of_date",
    "execution_timestamp", "event_timestamp", "visibility_timestamp",
    "visibility_date", "visibility_source", "pricing_timestamp",
    "pricing_clock_field", "report_lag_seconds", "visibility_lag_seconds",
    "dealer_direction", "dealer_sign", "p", "signed_weight", "rule",
    "deviation_bps", "tau_bps", "tau_bucket", "mid_bias_bps", "in_dead_zone",
    "exclusion_reason", "exclusion_detail",
    "kind", "n_legs", "special_tenor_type", "rate_index", "venue_class",
    "series", "is_lifecycle", "is_block", "is_capped",
    "total_dv01_if_received", "total_delta_dv01", "structure_dv01",
    "dv01_proxy",
    "curve_name", "curve_timestamp", "snapshot_lag_seconds", "snapshot_policy",
    "curve_source", "notional_imputed", "notional_impute_factor",
    "risk_sanity_reason", "tape_generation", "code_vintage",
]

UNIT_BUCKET_DB_COLUMNS = [
    "package_id", "bucket_key", "unit_key", "as_of_date", "visibility_date",
    "venue_class", "series", "bucket_space", "dv01_if_received", "delta_dv01",
    "signed_weight", "code_vintage",
]

COVERAGE_DB_COLUMNS = [
    "visibility_date", "bucket_key", "venue_class", "series", "reason",
    "n_units", "dv01", "as_of_date", "code_vintage",
]

LADDER_DB_COLUMNS = [
    "bucket_space", "bucket_key", "visibility_date", "venue_class", "series",
    "observed", "delta_dv01", "delta_dv01_cov_adj", "abs_dv01", "n_units",
    "mean_abs_signed_weight", "z_raw", "z_cov_adj", "pct_raw", "z_n_obs",
    "coverage_frac", "coverage_smooth", "coverage_drift_flag",
    "coverage_trend_pp_per_yr", "coverage_drift_source",
    "frac_dv01_block", "frac_dv01_capped", "frac_dv01_dead_zone",
    "frac_dv01_visibility_measured", "code_vintage", "primary_level_basis",
    "coverage_dv01_kept", "coverage_dv01_total",
]


def _sanitize(v):
    """psycopg2 adapts neither numpy scalars nor NaN."""
    if v is None:
        return None
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        v = float(v)
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.to_pydatetime()
    if isinstance(v, np.datetime64):
        t = pd.Timestamp(v)
        return None if pd.isna(t) else t.to_pydatetime()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _write(conn, table: str, columns: list, rows: list,
           conflict: str, batch: int = 5000) -> int:
    from psycopg2.extras import execute_values
    if not rows:
        return 0
    keys = {c.strip() for c in conflict.split(",")}
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns
                        if c not in keys)
    sql = (f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
           f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}")
    n = 0
    for i in range(0, len(rows), batch):
        chunk = [tuple(_sanitize(r.get(c)) for c in columns)
                 for r in rows[i:i + batch]]
        with conn.cursor() as cur:
            execute_values(cur, sql, chunk, page_size=batch)
        conn.commit()
        n += len(chunk)
    return n


def publish_day(conn, day: str, paths: Paths, tau_set, vintage: str,
                dry_run: bool):
    """One tape day: classify, ladder, roll up, write units + buckets.

    Returns the TENOR10 unit rows and the coverage rows, which the caller
    accumulates because the indicator is a whole-history object.
    """
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import ladder as ladder_mod
    from SDRUtils.dealer_direction import snapshot as snap

    units_df = pd.read_parquet(paths.units / f"{day}.parquet")
    plegs_df = pd.read_parquet(paths.plegs / f"{day}.parquet")
    krd_df = pd.read_parquet(paths.krd / f"{day}.parquet")
    cov_legs = pd.read_parquet(paths.covlegs / f"{day}.parquet")

    calls, extra = classify_day(units_df, plegs_df, tau_set)

    shims = [_shim(r) for r in units_df.to_dict("records")]
    keys = {s.unit_key for s in shims}
    krd_df = krd_df[krd_df["unit_key"].isin(keys)]

    rows, excluded = ladder_mod.unit_ladder_rows(
        shims, calls, krd_df, drop_dead_zone=False,
        curve_source=snap.CURVE_SOURCE)

    tenor_rows = (ind.roll_up_to_tenor_buckets(rows) if len(rows) else rows)

    # ---- the final reason per unit: universe -> ladder -> IN_LADDER --------
    ladder_reason = ({} if excluded.empty
                     else dict(zip(excluded["unit_key"].astype(str),
                                   excluded["failure_reason"].astype(str))))
    pkg_by_key = dict(zip(units_df["unit_key"].astype(str),
                          units_df["package_id"].astype(str)))

    reason_by_unit = {}
    for r in units_df.to_dict("records"):
        key = str(r["unit_key"])
        ex = _s(extra.get(key, {}).get("exclusion")) or _s(ladder_reason.get(key))
        reason_by_unit[key] = ex or S.IN_LADDER
    bad = {k: v for k, v in reason_by_unit.items() if not isinstance(v, str)}
    if bad:
        raise TypeError(f"{len(bad)} unit(s) carry a non-string reason, "
                        f"e.g. {list(bad.items())[:3]}")

    agg = ({} if tenor_rows.empty else
           tenor_rows.groupby("unit_key", observed=True)
           .agg(total_dv01_if_received=("dv01_if_received", "sum"),
                total_delta_dv01=("delta_dv01", "sum"))
           .to_dict("index"))

    unit_rows_db = []
    for r in units_df.to_dict("records"):
        key = str(r["unit_key"])
        e = extra.get(key, {})
        reason = reason_by_unit[key]
        excl = None if reason == S.IN_LADDER else reason
        a = agg.get(key, {})
        vis, exe = r["visibility_ts"], r["execution_ts"]
        lag = None
        if pd.notna(vis) and pd.notna(exe):
            lag = float((pd.Timestamp(vis) - pd.Timestamp(exe)).total_seconds())
        unit_rows_db.append({
            "package_id": str(r["package_id"]),
            "unit_key": key,
            "as_of_date": _as_date(r["as_of_date"]),
            "execution_timestamp": exe,
            "event_timestamp": r["event_ts"],
            "visibility_timestamp": vis,
            "visibility_date": _as_date(r["visibility_date"]),
            "visibility_source": r["visibility_source"],
            "pricing_timestamp": (r["pricing_ts"]
                                  if isinstance(r["pricing_ts"], pd.Timestamp)
                                  else None),
            "pricing_clock_field": _s(r["pricing_clock_field"]),
            "report_lag_seconds": _f(r["report_lag_seconds"]),
            "visibility_lag_seconds": lag,
            "dealer_direction": direction_label(e.get("dealer_sign"), excl),
            "dealer_sign": (None if excl is not None
                            else int(e.get("dealer_sign") or 0)),
            "p": _f(e.get("p")),
            "signed_weight": _f(e.get("signed_weight")),
            "rule": _s(r["rule"]),
            "deviation_bps": _f(e.get("deviation_bps")),
            "tau_bps": _f(e.get("tau_bps")),
            "tau_bucket": _s(e.get("tau_bucket")),
            "mid_bias_bps": _f(e.get("mid_bias_bps")),
            "in_dead_zone": bool(e.get("in_dead_zone")),
            "exclusion_reason": excl,
            "exclusion_detail": (_s(r["universe_exclusion_detail"])
                                 or _s(r["failure_detail"])
                                 or _s(r["pkg_flags"])),
            "kind": str(r["kind"]), "n_legs": int(r["n_legs"]),
            "special_tenor_type": _s(r["special_tenor_type"]),
            "rate_index": str(r["rate_index"]),
            "venue_class": str(r["venue_class"]),
            "series": str(r["series"]),
            "is_lifecycle": bool(r["is_lifecycle"]),
            "is_block": bool(r["is_block"]), "is_capped": bool(r["is_capped"]),
            "total_dv01_if_received": _f(a.get("total_dv01_if_received")),
            "total_delta_dv01": _f(a.get("total_delta_dv01")),
            "structure_dv01": _f(r["structure_dv01"]),
            "dv01_proxy": _f(r["dv01_proxy"]),
            "curve_name": _s(r["curve_name"]),
            "curve_timestamp": r["curve_timestamp"],
            "snapshot_lag_seconds": _f(r["snapshot_lag_s"]),
            "snapshot_policy": _s(r["snapshot_policy"]),
            "curve_source": snap.CURVE_SOURCE,
            # The capped-notional imputation is REPORTED, not applied: the
            # ladder's DV01 comes from the printed notional, so a capped unit
            # is flagged and its magnitude is a low reading. Applying the
            # multiplier here would silently inflate the level.
            "notional_imputed": bool(r["is_capped"]),
            "notional_impute_factor": None,
            "risk_sanity_reason": _s(r["risk_sanity_reason"]),
            "tape_generation": S.SOURCE_TAPE_GENERATION,
            "code_vintage": vintage,
        })

    ub_rows = []
    for r in tenor_rows.to_dict("records"):
        key = str(r["unit_key"])
        ub_rows.append({
            "package_id": pkg_by_key[key], "bucket_key": r["bucket_key"],
            "unit_key": key, "as_of_date": _as_date(r["as_of_date"]),
            "visibility_date": _as_date(r["visibility_date"]),
            "venue_class": r["venue_class"], "series": r["series"],
            "bucket_space": r["bucket_space"],
            "dv01_if_received": _f(r["dv01_if_received"]),
            "delta_dv01": _f(r["delta_dv01"]),
            "signed_weight": _f(r["signed_weight"]),
            "code_vintage": vintage,
        })

    cov = cov_legs.copy()
    cov["reason"] = cov["unit_key"].astype(str).map(reason_by_unit)
    if cov["reason"].isna().any():
        raise RuntimeError(
            f"{day}: {int(cov['reason'].isna().sum())} coverage leg(s) belong "
            "to a unit with no reason; the coverage accounting would not sum")
    cov = cov[cov["bucket_key"].notna()]
    cov_rows = (cov.groupby(["visibility_date", "bucket_key", "venue_class",
                             "series", "reason"], observed=True)
                .agg(n_units=("unit_key", "nunique"),
                     dv01=("dv01_proxy", "sum"))
                .reset_index())
    cov_rows["as_of_date"] = _as_date(day)
    cov_rows["code_vintage"] = vintage

    if not dry_run:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {S.UNIT_TABLE} WHERE as_of_date = %s",
                        (day,))
            cur.execute(f"DELETE FROM {S.UNIT_BUCKET_TABLE} "
                        "WHERE as_of_date = %s", (day,))
            cur.execute(f"DELETE FROM {S.COVERAGE_TABLE} WHERE as_of_date = %s",
                        (day,))
        conn.commit()
        _write(conn, S.UNIT_TABLE, UNIT_DB_COLUMNS, unit_rows_db, "package_id")
        _write(conn, S.UNIT_BUCKET_TABLE, UNIT_BUCKET_DB_COLUMNS, ub_rows,
               "package_id, bucket_key")
        _write(conn, S.COVERAGE_TABLE, COVERAGE_DB_COLUMNS,
               cov_rows.to_dict("records"),
               "visibility_date, bucket_key, venue_class, series, reason")

    return {
        "day": day,
        "n_units": len(unit_rows_db),
        "n_kept": int(sum(1 for r in unit_rows_db
                          if r["exclusion_reason"] is None)),
        "n_bucket_rows": len(ub_rows),
        "n_cov_rows": len(cov_rows),
        "tenor_rows": tenor_rows,
        "cov_rows": cov_rows,
    }


def build_and_write_ladder(conn, tenor_rows, cov_rows, dry_run: bool) -> int:
    """The published indicator cell, rebuilt over the WHOLE history.

    Never appended to. ``indicator``'s adjusted level divides by
    ``mean(coverage)`` over the full sample and ``z`` is a trailing-250
    statistic, so extending history restates earlier cells; an appended table
    would mix cells computed against different sample lengths with nothing
    saying so.
    """
    from SDRUtils.dealer_direction import indicator as ind

    # Both sides of the coverage merge are forced to `datetime.date`.
    # `tenor_rows.visibility_date` is a fresh `datetime.date` out of
    # `ladder._unit_meta`; `cov_rows.visibility_date` has been through a
    # parquet round trip, which can hand back `datetime64[ns]` or an object
    # column of dates depending on the writer. A type mismatch here does not
    # raise -- the merge simply matches nothing, every published cell looks
    # uncovered, and `indicator.build` raises `CoverageGap` on the whole run.
    tenor_rows = tenor_rows.copy()
    cov_rows = cov_rows.copy()
    for frame in (tenor_rows, cov_rows):
        frame["visibility_date"] = (
            pd.to_datetime(frame["visibility_date"]).dt.date)

    # ---- the two clocks do not share a day boundary --------------------
    #
    # The tape's `as_of` day runs 20:00 ET the previous evening to 19:59 ET.
    # The ladder stamps on availability, a New York date. So for `as_of = D`
    # the visibility dates are {D-1, D}: a print at 20:30 ET on D-1 carries
    # `as_of = D` and becomes public on D-1.
    #
    # Publishing `as_of >= SAMPLE_FLOOR` therefore produces a cell stamped
    # FLOOR-1, built only from the sliver of FLOOR's prints that executed the
    # previous evening. `indicator.build` refuses the whole run over it, which
    # is the right behaviour and is how this was found -- the floor exists
    # because the DV01 exclusion rate steps 3.2 pp across the 2024-07 ingest
    # break and the tape carries no termination events before it.
    #
    # Dropped rather than published, and nothing that belongs to a published
    # day is lost with it: the FLOOR-1 cell would need `as_of = FLOOR-1`,
    # which is outside the window by construction.
    #
    # THE OTHER END IS DIFFERENT AND IS NOT DROPPED. The most recent
    # visibility day is missing the 20:00-23:59 ET prints that will arrive
    # with the next tape day's `as_of`, so it is *provisional* rather than
    # wrong, and it tops itself up on the next run. Dropping it would throw
    # away the freshest cell in the series -- the one a reader looks at first
    # -- to fix an under-read in the thinnest hours of the session. It is
    # stated in the consumer note instead.
    n_before = len(tenor_rows)
    floor = ind.SAMPLE_FLOOR
    tenor_rows = tenor_rows[tenor_rows["visibility_date"] >= floor]
    cov_rows = cov_rows[cov_rows["visibility_date"] >= floor]
    dropped = n_before - len(tenor_rows)
    if dropped:
        print(f"ladder: dropped {dropped:,} unit-bucket rows stamped before "
              f"the {floor} sample floor (prints that executed after 20:00 ET "
              "the previous evening and so carry the next tape day's as_of)",
              flush=True)
    if tenor_rows.empty:
        raise RuntimeError(
            f"every published row is stamped before the {floor} floor; "
            "nothing to build")

    kept = np.where(cov_rows["reason"].to_numpy() == S.IN_LADDER,
                    cov_rows["dv01"].to_numpy(), 0.0)
    coverage = (cov_rows.assign(_kept=kept)
                .groupby(["bucket_key", "visibility_date", "venue_class",
                          "series"], observed=True)
                .agg(dv01_kept=("_kept", "sum"), dv01_total=("dv01", "sum"))
                .reset_index())

    # ---- the level and the coverage are on two different grids ---------
    #
    # INDICATOR.md §2 says so, and this is where it bites. The LEVEL is
    # key-rate risk: rateslib's delta ladder puts a non-zero number at all 28
    # pillars for a single swap, so one 10Y trade publishes a cell in 0-1Y as
    # well as in 7-10Y. The COVERAGE is a maturity-point allocation of gross
    # |DV01| -- it has to be, because an excluded unit has no key-rate profile
    # *by construction*, which is why it was excluded -- so that same trade
    # contributes to the 7-10Y denominator and to nothing else.
    #
    # The two grids therefore do not have the same cell set, and
    # `indicator.build` requires one coverage row per published cell. Nothing
    # exercised this before: the backend's own `ddind_coverage.py` built the
    # coverage frame alone, and INDICATOR §6 records that no composed
    # pipeline existed to put a KRD-derived level beside it.
    #
    # A cell the ladder publishes with no coverage row is one where **no tape
    # DV01 matured in that bucket that day**: the risk in it is key-rate spill
    # from longer-dated trades. Its coverage is 0/0, and `coverage_fraction`
    # refuses that outright -- "a coverage fraction over no size reports
    # nothing" -- which is the right stance and not one to route around.
    #
    # Two ways not taken:
    #
    #   * publish it with an unknown coverage. The module refuses, and the
    #     refusal is correct: every cell here is meant to be gateable on its
    #     coverage, and one that cannot be gated is worse than absent.
    #   * allocate the NUMERATOR on the KRD grid and the denominator on the
    #     maturity grid, which would make the ratio cell-consistent by putting
    #     two different populations inside one fraction -- exactly the
    #     incoherence §2 exists to name.
    #
    # So the cells are dropped, and the cost is measured rather than assumed:
    # on the smoke window, 187 of 1,420 cells and **0.253% of |delta_dv01|**.
    # With `session_dates` passed, the affected day still appears in its
    # bucket's series as `observed=False` rather than vanishing.
    key = ["bucket_key", "visibility_date", "venue_class", "series"]
    cells = tenor_rows[key].drop_duplicates()
    orphan = (cells.merge(coverage, how="left", on=key, indicator=True)
              .query("_merge == 'left_only'")[key])
    if len(orphan):
        drop = tenor_rows.merge(orphan.assign(_o=1), on=key, how="left")
        mask = drop["_o"].notna().to_numpy()
        share = float(tenor_rows["delta_dv01"].abs().to_numpy()[mask].sum())
        total = float(tenor_rows["delta_dv01"].abs().sum())
        print(f"ladder: dropped {len(orphan):,} of {len(cells):,} cells where "
              f"no tape DV01 MATURED in that bucket-day, so the coverage "
              f"fraction would be 0/0 "
              f"({100.0 * share / max(total, 1e-9):.3f}% of |delta_dv01|)",
              flush=True)
        tenor_rows = tenor_rows[~mask]

    coverage = coverage[list(ind.COVERAGE_COLUMNS)]

    session_dates = sorted(set(
        pd.to_datetime(tenor_rows["visibility_date"]).dt.date.tolist()))
    obj = ind.build(tenor_rows, coverage=coverage, session_dates=session_dates)
    cells = obj._cells.copy()

    print(f"ladder: {len(cells):,} cells over {len(session_dates)} sessions, "
          f"{cells['bucket_key'].nunique()} buckets x "
          f"{cells['venue_class'].nunique()} venue classes x "
          f"{cells['series'].nunique()} series", flush=True)

    if dry_run:
        return len(cells)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {S.LADDER_TABLE}")
    conn.commit()
    return _write(
        conn, S.LADDER_TABLE, LADDER_DB_COLUMNS, cells.to_dict("records"),
        "bucket_space, bucket_key, visibility_date, venue_class, series")


def stage_publish(days_all: list, publish_days: list, paths: Paths,
                  dry_run: bool, refresh_calibration: bool = False) -> int:
    from SDRUtils.dealer_direction import provenance as prov
    from SDRUtils.dealer_direction import snapshot as snap

    assert_priced_complete(days_all, paths)
    vintage = prov.code_vintage(snap.CURVE_SOURCE)
    print(f"publish: vintage {vintage}, {len(publish_days)} days "
          f"({publish_days[0]} .. {publish_days[-1]}), "
          f"calibrating on {len(days_all)} priced days", flush=True)

    # Schema FIRST, on a throwaway connection, before the calibration.
    # The calibration is ~85 minutes on the full window; discovering a bad
    # ALTER after it, rather than in the first second, is the difference
    # between a typo and an evening. The connection is not held across the
    # calibration -- an idle session that long is its own problem.
    conn = connect()
    try:
        S.ensure_schema(conn)
    finally:
        conn.close()

    cals = build_calibrations(paths, days_all, refresh=refresh_calibration)
    tau_set = TauSet(cals)

    conn = connect()
    try:
        tenor_parts, cov_parts = [], []
        t0 = time.time()
        with probability_clip() as clip:
            for i, day in enumerate(publish_days, 1):
                started = datetime.datetime.now(datetime.timezone.utc)
                t1 = time.perf_counter()
                res = publish_day(conn, day, paths, tau_set, vintage, dry_run)
                tenor_parts.append(res.pop("tenor_rows"))
                cov_parts.append(res.pop("cov_rows"))
                secs = time.perf_counter() - t1
                if not dry_run:
                    _record_run(conn, day, "publish", started, "ok", res,
                                secs, vintage)
                print(f"  {day}: {res['n_units']} units, {res['n_kept']} kept, "
                      f"{res['n_bucket_rows']} bucket rows, "
                      f"{res['n_cov_rows']} coverage rows, {secs:.1f}s "
                      f"[{i}/{len(publish_days)}]", flush=True)
        print(f"probability clip fired: {dict(clip)}", flush=True)
        tenor_rows = pd.concat(tenor_parts, ignore_index=True)
        cov_rows = pd.concat(cov_parts, ignore_index=True)
        n_cells = build_and_write_ladder(conn, tenor_rows, cov_rows, dry_run)
        print(f"publish: {len(publish_days)} days, {len(tenor_rows):,} "
              f"unit-bucket rows, {n_cells:,} ladder cells, "
              f"{(time.time() - t0) / 60:.1f} min", flush=True)
        if not dry_run:
            _assert_published(conn, publish_days)
    finally:
        conn.close()
    return 0


def _record_run(conn, day, stage, started, status, res, secs, vintage) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {S.RUNS_TABLE} (as_of_date, stage, started_at, "
            "ended_at, status, n_units, n_units_kept, n_unit_rows, "
            "n_coverage_rows, seconds, code_vintage) "
            "VALUES (%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s)",
            (day, stage, started, status, res.get("n_units"),
             res.get("n_kept"), res.get("n_bucket_rows"),
             res.get("n_cov_rows"), secs, vintage))
    conn.commit()


def _assert_published(conn, days: list) -> None:
    """A day succeeded only if the rows it was supposed to produce exist."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # ::date[] is load-bearing -- psycopg2 sends a Python list of ISO
        # strings as text[], and `date = text` has no operator, so the check
        # that a day produced rows would itself fail rather than report.
        got = pd.read_sql(
            f"SELECT as_of_date, count(*) n FROM {S.UNIT_TABLE} "
            "WHERE as_of_date = ANY(%(d)s::date[]) GROUP BY as_of_date",
            conn, params={"d": list(days)})
    have = {pd.Timestamp(d).date().isoformat() for d in got["as_of_date"]}
    missing = [d for d in days if d not in have]
    if missing:
        raise RuntimeError(
            f"{len(missing)} published day(s) wrote no unit rows, e.g. "
            f"{missing[:5]}. Exit code 0 is not evidence a day produced "
            "anything.")
    if len(got[got["n"] == 0]):
        raise RuntimeError("some day(s) wrote zero rows")


def stage_status(days: list, paths: Paths) -> int:
    have = sum(1 for d in days if all(p.exists() for p in paths.day_files(d)))
    print(f"priced: {have}/{len(days)} days under {paths.root}")
    missing = [d for d in days
               if not all(p.exists() for p in paths.day_files(d))]
    if missing:
        print(f"  first missing: {missing[:10]}")
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        print(f"  (no db: {exc})")
        return 0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for table in (S.UNIT_TABLE, S.UNIT_BUCKET_TABLE, S.COVERAGE_TABLE,
                          S.LADDER_TABLE):
                col = ("visibility_date" if table == S.LADDER_TABLE
                       else "as_of_date")
                try:
                    df = pd.read_sql(
                        f"SELECT count(*) n, min({col}) lo, max({col}) hi "
                        f"FROM {table}", conn)
                    print(f"  {table}: {int(df['n'][0]):,} rows "
                          f"{df['lo'][0]} .. {df['hi'][0]}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {table}: {type(exc).__name__}")
                    conn.rollback()
    finally:
        conn.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Materialise dealer direction and the risk-bucket ladder")
    ap.add_argument("stage", choices=["price", "publish", "status", "schema"])
    ap.add_argument("--start", default=PRICE_FLOOR)
    ap.add_argument("--end", default=None)
    ap.add_argument("--publish-start", default=None,
                    help="defaults to indicator.SAMPLE_FLOOR (2024-07-01)")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--budget-min", type=float, default=10_000.0)
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-calibration", action="store_true",
                    help="refit the rolling calibrations even if cached")
    args = ap.parse_args(argv)

    os.environ.setdefault("TMPDIR", str(pathlib.Path(args.cache_dir) / "tmp"))
    paths = Paths(pathlib.Path(args.cache_dir))
    paths.mkdirs()

    if args.stage == "schema":
        conn = connect()
        try:
            S.ensure_schema(conn)
        finally:
            conn.close()
        print("schema ensured: " + ", ".join(
            (S.UNIT_TABLE, S.UNIT_BUCKET_TABLE, S.COVERAGE_TABLE,
             S.LADDER_TABLE, S.RUNS_TABLE)))
        return 0

    end = args.end or datetime.date.today().isoformat()
    days = tape_days(args.start, end)

    if args.stage == "price":
        return stage_price(days, paths, args.workers, args.budget_min)
    if args.stage == "status":
        return stage_status(days, paths)

    from SDRUtils.dealer_direction import indicator as ind
    floor = args.publish_start or ind.SAMPLE_FLOOR.isoformat()
    pdays = [d for d in days if d >= floor]
    if not pdays:
        raise RuntimeError(f"no priced days at or after the floor {floor}")
    return stage_publish(days, pdays, paths, args.dry_run,
                         args.refresh_calibration)


if __name__ == "__main__":
    sys.exit(main())
