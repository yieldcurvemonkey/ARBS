"""Stage 3 - reprice the sample against the Citi minute curve under STRICT policy.

Two known-answer checks run FIRST, because a repricing tool that is itself wrong
reports plausible basis points and hides the thing it was built to find:

  K1  three liquid in-session on-market SOFR outrights must land within a couple
      of basis points of mid. If the units, the curve or the schedule were wrong
      the error would be tens of bp or worse, not tenths.
  K2  a 23:30 ET instant - inside Citi's nightly hole, where no snapshot exists
      within 60 s - must RAISE SnapshotMiss. If it returns a curve, the strict
      policy is not reaching the code path it is meant to govern and every
      number after it is unearned.

Only if both hold does the script price the sample.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datetime

import pandas as pd

from dd_common import (CURVE_FOR, curve_meta, load_sample, make_pricer, snap_of,
                       strict_policy)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)


def price_one(pricer, row, snap):
    """(mid_pct, meta, error) for one print, never raising."""
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    curve = CURVE_FOR[row["index"]]
    try:
        h = pricer.handle(curve, snap.to_pydatetime())
    except SnapshotMiss as exc:
        return None, {}, f"SnapshotMiss: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, {}, f"{type(exc).__name__}: {exc}"
    meta = curve_meta(h)
    try:
        lp = pricer.price_leg(
            curve, snap.to_pydatetime(),
            row["effective_date"], row["expiration_date"],
            float(row["notional"]),
        )
    except Exception as exc:  # noqa: BLE001
        return None, meta, f"price_leg {type(exc).__name__}: {exc}"
    return lp.mid_pct, meta, None


def known_answer_checks(sample: pd.DataFrame) -> bool:
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    ok = True
    pricer = make_pricer(strict_policy(minutes=1))

    print("=== K1: liquid in-session SOFR outrights should sit within ~2 bp of mid ===")
    liquid = sample[(sample["index"] == "SOFR") & sample["publishes"]
                    & sample["tenor_label"].isin(["2Y", "5Y", "10Y", "3Y", "7Y"])].head(3)
    for _, r in liquid.iterrows():
        snap = snap_of(r)
        mid, meta, err = price_one(pricer, r, snap)
        if err:
            print(f"  FAIL {r['trade_id']}: {err}")
            ok = False
            continue
        printed_pct = float(r["fixed_rate"]) * 100.0
        bp = (printed_pct - mid) * 100.0
        verdict = "ok" if abs(bp) <= 3.0 else "OUT OF RANGE"
        print(f"  {r['trade_id']} {r['tenor_label']:>4s} {snap.tz_convert('America/New_York')} "
              f"printed={printed_pct:.5f}% mid={mid:.5f}% diff={bp:+.3f}bp "
              f"lag={meta.get('lag_signed_s')}s  {verdict}")
        if abs(bp) > 3.0:
            ok = False

    print("\n=== K2: 23:30 ET (Citi's nightly hole) must RAISE under strict ===")
    # A weekday inside a dense stored day. 22:59 ET is the last published minute.
    hole = pd.Timestamp("2026-04-01 23:30:00", tz="America/New_York")
    try:
        pricer.handle("USD-SOFR-1D", hole.to_pydatetime())
        print("  FAIL: strict policy served a curve for 23:30 ET")
        ok = False
    except SnapshotMiss as exc:
        print(f"  ok: SnapshotMiss -> {str(exc)[:150]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: wrong exception {type(exc).__name__}: {exc}")
        ok = False

    print("\n=== K2b: control - 22:59 ET the same evening must SUCCEED ===")
    good = pd.Timestamp("2026-04-01 22:59:00", tz="America/New_York")
    try:
        h = pricer.handle("USD-SOFR-1D", good.to_pydatetime())
        m = curve_meta(h)
        print(f"  ok: served {m['served_utc']} lag={m['lag_signed_s']}s")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        ok = False
    return ok


def main() -> None:
    sample = load_sample()
    if not known_answer_checks(sample):
        print("\nKNOWN-ANSWER CHECKS FAILED - not pricing the sample.")
        return

    print("\n\n=== STRICT (asof, 60 s, no future, raise) over the whole sample ===")
    pricer = make_pricer(strict_policy(minutes=1))
    rows = []
    for _, r in sample.iterrows():
        snap = snap_of(r)
        t0 = time.perf_counter()
        mid, meta, err = price_one(pricer, r, snap)
        dt = time.perf_counter() - t0
        printed_pct = float(r["fixed_rate"]) * 100.0
        rows.append({
            "trade_id": r["trade_id"],
            "index": r["index"],
            "tenor": r["tenor_label"],
            "snap_et": snap.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M"),
            "dow": int(r["et_dow"]),
            "publishes": bool(r["publishes"]),
            "printed_pct": round(printed_pct, 6),
            "mid_pct": None if mid is None else round(mid, 6),
            "diff_bp": None if mid is None else round((printed_pct - mid) * 100.0, 3),
            "lag_s": meta.get("lag_signed_s"),
            "served_utc": meta.get("served_utc"),
            "secs": round(dt, 3),
            "error": None if err is None else err.split("\n")[0][:110],
        })
    out = pd.DataFrame(rows)
    out.to_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_strict_prices.csv", index=False)
    print(out[["trade_id", "index", "tenor", "snap_et", "dow", "publishes",
               "printed_pct", "mid_pct", "diff_bp", "lag_s", "secs"]].to_string())
    print("\nerrors:")
    for _, r in out[out["error"].notna()].iterrows():
        print(f"  {r['trade_id']} {r['snap_et']} publishes={r['publishes']} -> {r['error']}")
    n_ok = int(out["mid_pct"].notna().sum())
    print(f"\npriced {n_ok}/{len(out)} under strict; "
          f"{int((~out['publishes']).sum())} of the sample are outside Citi's session")
    d = out["diff_bp"].dropna()
    if len(d):
        print(f"diff_bp (printed - mid): median {d.median():+.3f}  "
              f"IQR [{d.quantile(0.25):+.3f}, {d.quantile(0.75):+.3f}]  "
              f"within +/-0.1bp: {(d.abs() <= 0.1).mean():.1%}")


if __name__ == "__main__":
    main()
