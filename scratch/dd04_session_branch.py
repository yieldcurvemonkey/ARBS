"""Stage 4 - the SESSION BRANCH: strict in-session, bounded 2 h across the hole.

The rule (docs/2026-08-09-citivelo-minute-curve-fidelity.md §20):

    strict(minutes=1)                       when citi_session.publishes(curve, snap)
    asof / max_lag=2h / no future / raise   otherwise

and NOT a global ``max_lag=2h``, which would also admit two hours of staleness at
10:00 on a Tuesday - measured at 2.63 bp p90 against 0.87 bp for the same elapsed
time across the 23:00-00:59 ET hole.

Three demonstrations, in the order that makes each one mean something:

  D1  an in-session print: the branch picks STRICT and returns bit-identical
      numbers to the pure-strict run. Loosening the hole must not loosen the day.
  D2  an 00:xx ET print: pure strict raises SnapshotMiss, the branch prices it
      off the previous session's last published minute, and the lag it reports
      is the width of the hole and nothing more.
  D3  the counter-example that justifies the branch existing at all. On a day
      with a real INTERIOR gap, an in-session request inside that gap is
      **served** by a global 2 h policy (with a large lag, silently) and
      **refused** by the branch. If D3 does not separate the two policies, the
      branch is decoration and the global bound would do.
"""
from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from dd_common import (CURVE_FOR, curve_meta, hole_policy, load_sample,
                       make_pricer, snap_of, strict_policy)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)


class SessionBranchPricer:
    """Two ``CurvePricer`` instances, chosen per request by the Citi session.

    Two instances rather than one, because ``CurvePricer.curve_kwargs`` is fixed
    for the life of the object *on purpose*: its handle cache is keyed on
    ``(curve_name, ts)`` alone, so a per-call policy would let the first
    caller's terms be reused silently for the next caller's request for the same
    minute. Branching on the object keeps the cache key and the terms in
    agreement.
    """

    def __init__(self, *, strict_minutes: float = 1.0, hole_hours: float = 2.0):
        self.in_session = make_pricer(strict_policy(minutes=strict_minutes))
        self.out_session = make_pricer(hole_policy(hours=hole_hours))

    def pick(self, curve_name: str, snap) -> tuple[str, object]:
        from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes

        if publishes(curve_name, pd.Timestamp(snap)):
            return "strict", self.in_session
        return "hole", self.out_session

    def handle(self, curve_name: str, snap):
        branch, pricer = self.pick(curve_name, snap)
        return branch, pricer.handle(curve_name, pd.Timestamp(snap).to_pydatetime())

    def price_leg(self, curve_name, snap, effective_date, maturity_date, notional):
        branch, pricer = self.pick(curve_name, snap)
        ts = pd.Timestamp(snap).to_pydatetime()
        h = pricer.handle(curve_name, ts)
        lp = pricer.price_leg(curve_name, ts, effective_date, maturity_date, notional)
        return branch, lp, curve_meta(h)


def run_sample(sample: pd.DataFrame) -> pd.DataFrame:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    br = SessionBranchPricer()
    rows = []
    for _, r in sample.iterrows():
        snap = snap_of(r)
        curve = CURVE_FOR[r["index"]]
        branch, _ = br.pick(curve, snap)
        try:
            _, lp, meta = br.price_leg(curve, snap, r["effective_date"],
                                       r["expiration_date"], float(r["notional"]))
            mid, err = lp.mid_pct, None
        except SnapshotMiss as exc:
            mid, meta, err = None, {}, f"SnapshotMiss: {str(exc)[:90]}"
        except Exception as exc:  # noqa: BLE001
            mid, meta, err = None, {}, f"{type(exc).__name__}: {exc}"
        printed = float(r["fixed_rate"]) * 100.0
        rows.append({
            "trade_id": r["trade_id"], "index": r["index"], "tenor": r["tenor_label"],
            "snap_et": snap.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M"),
            "publishes": bool(r["publishes"]), "branch": branch,
            "printed_pct": round(printed, 6),
            "mid_pct": None if mid is None else round(mid, 6),
            "diff_bp": None if mid is None else round((printed - mid) * 100.0, 3),
            "lag_s": meta.get("lag_signed_s"),
            "lag_min": None if meta.get("lag_signed_s") is None
                       else round(meta["lag_signed_s"] / 60.0, 1),
            "served_utc": meta.get("served_utc"),
            "same_local_date": meta.get("same_local_date"),
            "from_future": meta.get("from_future"),
            "error": err,
        })
    return pd.DataFrame(rows)


def _probe(label: str, policy, curve: str, instant: pd.Timestamp) -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    p = make_pricer(policy)
    try:
        h = p.handle(curve, instant.to_pydatetime())
        m = curve_meta(h)
        print(f"  {label:46s} -> SERVED  lag={m['lag_signed_s']:.0f}s "
              f"({m['lag_signed_s']/60:.0f} min) from {m['served_utc']}")
    except SnapshotMiss:
        print(f"  {label:46s} -> REFUSED (SnapshotMiss)")


def d3_interior_gap() -> None:
    """A real in-session gap: global 2 h serves it, the session branch refuses.

    Day chosen by ``dd04b_gapscan.py``, which scanned all 763 stored SOFR days
    in the tape span: 2026-06-01 carries the widest gap that is both inside the
    published session and narrower than two hours - i.e. the exact interval
    where the two policies must disagree. (2026-01-16's 257-minute gap is wider
    than the hole bound, so *both* policies refuse it and it proves nothing.)
    """
    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes

    asset, curve = "USD-SOFR-1D-CITIVELOEXCELMIN", "USD-SOFR-1D"
    store = CurveStore.default()
    day = datetime.date(2026, 6, 1)
    frame = store.read_raw_day(asset, day)
    stamps = pd.to_datetime(pd.Series(frame["timestamp_utc"]), utc=True).sort_values().reset_index(drop=True)
    diffs = diffs = stamps.diff().fillna(pd.Timedelta(0))
    i = int(np.argmax(diffs.to_numpy()))
    a, b = stamps.iloc[i - 1], stamps.iloc[i]
    inside = (a + (b - a) / 2).floor("1min")
    print(f"\n=== D3: in-session interior gap on {day} ===")
    print(f"  gap {a} -> {b}  ({(b-a).total_seconds()/60:.0f} min), all published minutes: "
          f"{publishes(curve, a)} / {publishes(curve, b)}")
    print(f"  probing {inside.tz_convert('America/New_York')} ET  "
          f"publishes={publishes(curve, inside)}  -> the branch must pick STRICT here")
    _probe("global max_lag=2h  (the WRONG design)", hole_policy(2.0), curve, inside)
    _probe("session branch -> strict 60 s", strict_policy(1.0), curve, inside)


def d4_truncated_night() -> None:
    """The 2 h bound is not decoration: a night after a truncated day is refused.

    A day cut short at 19:59 ET by *our* chunk boundary (not Citi's close) leaves
    the following 00:xx hour four to six hours from the last curve. The hole
    branch refuses it, which is the intended behaviour - those legs need the
    partition repaired, not a wider tolerance.
    """
    import csv

    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import is_truncated

    store = CurveStore.default()
    curve, asset = "USD-SOFR-1D", "USD-SOFR-1D-CITIVELOEXCELMIN"
    with open("C:/Users/chris/clee/ARBS-dd/docs/2026-08-10-citivelo-minute-repair-list.csv") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["curve"] == curve and r["reason"] == "truncated_end"
                and "2024-03-01" <= r["local_date"] <= "2026-08-07"]
    print(f"\n=== D4: the night after a truncated session ({len(rows)} such SOFR days in span) ===")
    shown = 0
    for r in rows:
        day = datetime.date.fromisoformat(r["local_date"])
        nxt = day + datetime.timedelta(days=1)
        if nxt.weekday() > 4:
            continue
        frame = store.read_raw_day(asset, day)
        if frame.empty:
            continue
        last = pd.to_datetime(pd.Series(frame["timestamp_utc"]), utc=True).max()
        if not is_truncated(curve, day, last):
            continue
        probe = pd.Timestamp(datetime.datetime.combine(nxt, datetime.time(0, 30)),
                             tz="America/New_York")
        gap_h = (probe - last).total_seconds() / 3600.0
        print(f"  {day} last stored {last.tz_convert('America/New_York')} ET; "
              f"probe {probe:%Y-%m-%d %H:%M} ET is {gap_h:.1f} h later")
        _probe("hole branch max_lag=2h", hole_policy(2.0), curve, probe)
        shown += 1
        if shown >= 2:
            break


def main() -> None:
    sample = load_sample()
    out = run_sample(sample)
    out.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_branch_prices.csv", index=False)

    print("=== session branch over the whole sample ===")
    print(out[["trade_id", "index", "tenor", "snap_et", "publishes", "branch",
               "printed_pct", "mid_pct", "diff_bp", "lag_min", "same_local_date"]].to_string())

    print("\n=== D1: in-session prints must be bit-identical to pure strict ===")
    strict = pd.read_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_strict_prices.csv")
    m = out.merge(strict[["trade_id", "mid_pct", "lag_s"]], on="trade_id",
                  suffixes=("", "_strict"))
    ins = m[m["branch"] == "strict"]
    same = ins["mid_pct"].round(9).equals(ins["mid_pct_strict"].round(9))
    print(f"  {len(ins)} in-session prints; mids identical to the pure-strict run: {same}")
    if not same:
        print(ins[["trade_id", "mid_pct", "mid_pct_strict"]].to_string())

    print("\n=== D2: hour-00 prints - strict raised, the branch prices them ===")
    h0 = out[out["branch"] == "hole"]
    print(h0[["trade_id", "index", "snap_et", "mid_pct", "diff_bp", "lag_min",
              "same_local_date", "from_future", "error"]].to_string())
    good = h0[h0["mid_pct"].notna()]
    if len(good):
        print(f"  priced {len(good)}/{len(h0)} out-of-session prints; "
              f"lag min/median/max = {good['lag_min'].min():.0f} / "
              f"{good['lag_min'].median():.0f} / {good['lag_min'].max():.0f} minutes")
        print(f"  any served from the future: {bool(good['from_future'].any())}")

    d3_interior_gap()
    d4_truncated_night()


if __name__ == "__main__":
    main()
