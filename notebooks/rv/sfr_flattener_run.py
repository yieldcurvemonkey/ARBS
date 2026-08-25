"""Price the flattener candidates and print the structuring answer.

    conda run -n stir python notebooks/rv/sfr_flattener_run.py

Offline: SR3 settles from the shared BT/serff cache, the meeting ladder from the
ZQ cache. No network, no Excel/COM.
"""
from __future__ import annotations

import io
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sfr_flattener_structuring as S  # noqa: E402

AS_OF = pd.Timestamp("2026-08-21")
#: Every flattener a dovish few-month view could sensibly use, by RANK. On
#: 2026-08-21 rank 3 = H27, 4 = M27, 5 = U27, 6 = Z27, 7 = H28, 8 = M28.
PAIRS = [(1, 3), (2, 4), (2, 6), (1, 5), (3, 4), (3, 5), (3, 6), (3, 7),
         (3, 8), (4, 6), (4, 8), (5, 7), (5, 8), (6, 8)]
HORIZON_BD = 63          # ~3 months
OUT = HERE / "sfr_flattener_results.pkl"


def _p(*a):
    print(*a, flush=True)


def main() -> int:
    t0 = time.time()
    pd.set_option("display.width", 200)
    res = {}

    rates = S.rate_panel()
    res["panel"] = (rates.shape, rates.index.min(), rates.index.max())
    _p(f"SR3 rate panel {rates.shape} {rates.index.min().date()}"
       f"..{rates.index.max().date()}\n")

    _p("=" * 78); _p(f"1. THE STRIP on {AS_OF.date()}"); _p("=" * 78)
    strip = S.strip_today(rates, AS_OF)
    res["strip"] = strip
    _p(strip.to_string(index=False))
    _p("\n  The curve is already flat out here. That is the whole problem with a")
    _p("  flattener: there is very little tightening left in it to be short of.")

    _p("\n" + "=" * 78)
    _p("2. WHAT EACH CANDIDATE IS SHORT, AND WHAT THAT COSTS")
    _p("=" * 78)
    cand = S.candidate_table(rates, AS_OF, PAIRS)
    res["candidates"] = cand
    _p(cand.to_string(index=False))
    _p(f"\n  cost is {S.SPREAD_ROUND_TRIP_BP:.2f}bp round trip on a two-leg SR3")
    _p(f"  calendar spread -- TWICE an outright's {S.OUTRIGHT_ROUND_TRIP_BP:.2f}bp,")
    _p("  because the cost is per CONTRACT and a spread is two of them.")

    _p("\n" + "=" * 78)
    _p("3. THE MEETINGS INSIDE THE TWO STRUCTURES ASKED ABOUT")
    _p("=" * 78)
    try:
        from RVUtils.MeetingProb import meeting_ladder, zq_settle_panel
        from SDRUtils.analytics.fomc import load_fomc_schedule
        import fed_detachment_prices as PX

        codes = "FGHJKMNQUVXZ"
        zq = zq_settle_panel([f"ZQ{c}{y}" for y in range(24, 29) for c in codes])
        lad = meeting_ladder(AS_OF.date(), zq, load_fomc_schedule("USD-SOFR-1D"))
        res["ladder"] = [(m.effective, m.jump_bp, m.stale) for m in lad]
        _p(f"  priced meeting steps on {AS_OF.date()}:")
        for m in lad:
            _p(f"     {m.effective}  {m.jump_bp:+7.2f}bp  {m.contract}"
               + ("  STALE" if m.stale else ""))
        for name, (i, j) in (("H7U7 (r3-r5)", (3, 5)), ("H7Z7 (r3-r6)", (3, 6))):
            f_, b_ = (PX.rank_symbol(AS_OF.date(), i),
                      PX.rank_symbol(AS_OF.date(), j))
            mb = S.meetings_between(lad, f_, b_)
            res[f"meetings_{name}"] = mb
            _p(f"\n  {name}  =  {f_} vs {b_}")
            if mb.empty:
                _p("     no meetings between the reference windows")
            else:
                _p("     " + mb.to_string(index=False).replace("\n", "\n     "))
                _p(f"     sum of live steps: {mb.attrs.get('sum_bp', float('nan')):+.2f}bp")
    except Exception as exc:  # noqa: BLE001
        _p(f"  ladder unavailable: {type(exc).__name__}: {exc}")

    _p("\n" + "=" * 78)
    _p(f"4. A {HORIZON_BD}-BUSINESS-DAY HOLD, ROLL-SAFE, FIXED LEGS")
    _p("=" * 78)
    rows = []
    for i, j in PAIRS:
        mv = S.horizon_moves(rates, i, j, horizon_bd=HORIZON_BD)
        if mv.empty:
            continue
        cur = float(cand.loc[cand["pair"] == f"r{i}-r{j}", "spread_bp"].iloc[0])
        s = S.horizon_summary(mv)
        c = S.conditional_on_level(mv, cur)
        rows.append({"pair": f"r{i}-r{j}", "spread_now_bp": cur, **{
            f"all_{k}": v for k, v in s.items()
            if k in ("n", "flattener_mean_bp", "hit_rate", "q10_bp", "q90_bp",
                     "worst_bp")},
            "from_here_n": c.get("n"),
            "from_here_mean_bp": c.get("flattener_mean_bp"),
            "from_here_hit": c.get("hit_rate")})
    HZ = pd.DataFrame(rows)
    res["horizon"] = HZ
    _p(HZ.to_string(index=False))
    _p("\n  flattener_pnl is -(spread change) minus the 1.00bp round trip.")
    _p("  'from_here' restricts to historical starts within 5bp of today's level:")
    _p("  a flattener entered at +40bp and one entered at +3bp are different")
    _p("  trades and pooling them describes neither.")

    _p("\n" + "=" * 78)
    _p("5. DOES IT FLATTEN IN BOTH DIRECTIONS?")
    _p("=" * 78)
    rows = []
    for i, j in [(3, 5), (3, 6), (3, 8), (2, 6), (1, 5), (4, 8), (5, 8), (5, 7), (6, 8)]:
        bw = S.both_ways(rates, i, j)
        if "beta_all" not in bw:
            continue
        rows.append({k: v for k, v in bw.items() if k != "frame"})
    BW = pd.DataFrame(rows)
    res["both_ways"] = BW
    _p(BW.to_string(index=False))
    _p("\n  A flattener profits when the spread FALLS. 'Wins both ways' therefore")
    _p("  needs beta_up < 0 (spread falls as the strip sells off) AND beta_dn > 0")
    _p("  (spread falls as the strip rallies). Both columns must be True.")

    _p("\n" + "=" * 78)
    _p("6. WHERE IS THE TWIST POINT?")
    _p("=" * 78)
    tw = S.twist_point(rates)
    res["twist"] = tw
    _p(tw.to_string(index=False))
    _p("\n  beta_to_level > 1 means the rank moves MORE than the strip. A")
    _p("  flattener needs its BACK leg to have the lower beta; where the ordering")
    _p("  turns is the pivot the 'wins both ways' argument depends on.")

    with open(OUT, "wb") as f:
        pickle.dump(res, f)
    _p(f"\nwrote {OUT}  ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
