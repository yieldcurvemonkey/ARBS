"""Stage 5b - sweep EVERY distinct curve-minute of one tape day.

Two things stage 5 left open:

  * T2 sampled ``minutes[1:201]`` - the 200 EARLIEST distinct minutes of the day,
    which are exactly the 00:xx-02:xx ET block where the nightly hole lives. Its
    44/200 strict misses are therefore not the day's miss rate and must not be
    quoted as one. This sweeps all of them and splits by
    ``citi_session.publishes``.
  * T2's 2.65 ms is fast enough to be worth disproving: if the handle cache or
    the day frame were being reused, every minute would return the SAME curve
    and the timing would be measuring nothing. The sweep records the served
    stamp for each minute and checks they are distinct and equal to what was
    asked for.
"""
from __future__ import annotations

import collections
import datetime
import os
import statistics
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import psycopg2

from dd_common import curve_meta, hole_policy, make_pricer, strict_policy
from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import publishes
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow.pricing import snap_timestamp

DAY = datetime.date(2026, 4, 1)
CURVE = "USD-SOFR-1D"


def main() -> None:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    conn = psycopg2.connect(resolve_pg_url())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        legs = pd.read_sql(f"""
            SELECT execution_timestamp, original_execution_timestamp
            FROM {LEGS_TABLE}
            WHERE as_of_date = %(d)s AND rate_index_clean = 'SOFR'
              AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow""",
            conn, params={"d": DAY})
    conn.close()
    snaps = pd.to_datetime(pd.Series([
        snap_timestamp(a, b) for a, b in
        zip(legs["original_execution_timestamp"], legs["execution_timestamp"])
    ]), utc=True).dt.tz_convert("America/New_York")
    per_minute = collections.Counter(snaps)
    minutes = sorted(per_minute)
    print(f"{len(legs)} SOFR flow legs on {DAY} -> {len(minutes)} distinct snapped minutes")

    strict_p = make_pricer(strict_policy(1))
    branch_h = make_pricer(hole_policy(2.0))
    served, times = {}, []
    n_strict_ok = n_strict_miss = n_branch_ok = n_branch_miss = 0
    miss_in_session = miss_out_session = 0
    legs_missed = 0
    for m in minutes:
        in_sess = publishes(CURVE, m)
        t0 = time.perf_counter()
        try:
            h = strict_p.handle(CURVE, m.to_pydatetime())
            times.append(time.perf_counter() - t0)
            served[m] = curve_meta(h)["served_utc"]
            n_strict_ok += 1
            continue
        except SnapshotMiss:
            n_strict_miss += 1
            if in_sess:
                miss_in_session += 1
            else:
                miss_out_session += 1
        # the session branch's second arm
        if in_sess:
            n_branch_miss += 1
            legs_missed += per_minute[m]
            continue
        try:
            h = branch_h.handle(CURVE, m.to_pydatetime())
            served[m] = curve_meta(h)["served_utc"]
            n_branch_ok += 1
        except SnapshotMiss:
            n_branch_miss += 1
            legs_missed += per_minute[m]

    n = len(minutes)
    print(f"\nstrict(60 s)  served {n_strict_ok}/{n} minutes ({n_strict_ok/n:.1%}); "
          f"missed {n_strict_miss} ({miss_in_session} in-session, {miss_out_session} out)")
    print(f"session branch total served {n_strict_ok + n_branch_ok}/{n} "
          f"({(n_strict_ok+n_branch_ok)/n:.1%}); still missing {n_branch_miss} minutes "
          f"= {legs_missed} legs of {len(legs)} ({legs_missed/len(legs):.2%})")

    print(f"\nT2 over ALL served in-session minutes (n={len(times)}): "
          f"mean {statistics.mean(times)*1000:.2f} ms  p50 {statistics.median(times)*1000:.2f}  "
          f"p90 {sorted(times)[int(0.9*len(times))]*1000:.2f}")

    # ---- disprove "it is serving the same curve every time" -----------------
    # Split by session: the out-of-session minutes are SUPPOSED to collide -
    # every minute of the nightly hole is answered by the same 22:59 ET curve,
    # and that shared stamp is itself one of the in-session minutes, so a naive
    # global uniqueness check reports a collision for the correct behaviour.
    ins = {m: v for m, v in served.items() if v and publishes(CURVE, m)}
    outs = {m: v for m, v in served.items() if v and not publishes(CURVE, m)}
    print(f"\nin-session minutes answered: {len(ins)}, distinct served stamps: "
          f"{len(set(ins.values()))} -> "
          f"{'OK, one curve per minute' if len(set(ins.values())) == len(ins) else 'COLLISIONS'}")
    exact = sum(1 for m, v in ins.items() if pd.Timestamp(v) == m.tz_convert("UTC"))
    print(f"in-session served the EXACT minute asked for: {exact}/{len(ins)} "
          f"({exact/max(len(ins),1):.1%})")
    print(f"out-of-session minutes answered: {len(outs)}, distinct served stamps: "
          f"{len(set(outs.values()))} (expected 1 per night - all fall back to the "
          f"session's last published minute): {sorted(set(outs.values()))}")


if __name__ == "__main__":
    main()
