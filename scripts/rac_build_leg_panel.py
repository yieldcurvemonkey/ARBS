r"""Daily per-leg metrics for the ultra-long forward pairs, once.

    C:/Users/chris/anaconda3/envs/stir/python.exe scripts/rac_build_leg_panel.py \
        --start 2018-01-01 --end 2026-08-20 [workers]

``RVUtils.ConvexityRV.strat3_strikeless_vol.screen_panel_from_legs`` turns a
long-format ``(date, leg) -> rate_bp, dv01, gamma, roll_1y, roll_1d`` panel into
the whole fifteen-pair risk-adjusted-carry screen with pure column algebra. Nine
legs cover all fifteen pairs, so a day costs nine repricing passes rather than
thirty, and the expensive part -- one Citi curve build per date -- is paid once.

WHY A LOOKBACK THAT STARTS BEFORE THE BACKTEST
==============================================
The screen's z-scores are trailing 1y and 3y windows, so a backtest that begins
2021-01-01 needs leg history from 2018-01-01 or its first three years of
z-scores are computed on a truncated window and are quietly wrong at the start.

Citi's screen carries a "ZS since 2000" column. **This cannot be reproduced
here**: the Citi Velocity curve store's earliest partition is 2005-01-03. The
long window is therefore labelled by its actual start rather than borrowing
Citi's name for it.

NETWORK
=======
Runs inside ``listed_cache_guard.cache_only()``: an outbound request raises
rather than being sent, and the blocked count is written to the sidecar. It must
be zero. Curve builds come from the CurveStore, which is warm for this window.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pandas as pd  # noqa: E402

OUT = _REPO / "notebooks" / "data" / "convexity_rv"
PANEL = OUT / "rac_leg_panel.parquet"
SIDECAR = OUT / "rac_leg_panel_skips.json"

CURVE = "USD-SOFR-1D"


def _legs() -> list[str]:
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3

    return S3.leg_labels(S3.PAIRS_15)


def _chunk(dates: list[dt.date]) -> tuple[list[dict], dict]:
    """One worker: build the curve per date, then nine ``leg_metrics`` calls."""
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked

    labels = _legs()
    rows: list[dict] = []
    skips = {"ok": 0, "curve": 0, "leg": 0}

    with cache_only():
        mdp = IRSwapsMDP(source=CURVE and "CITIVELO_EXCEL")
        for d in dates:
            try:
                pricer = mdp._get_curve(curve_name=CURVE, timestamp=d)
            except Exception:
                skips["curve"] += 1
                continue
            ts = pd.Timestamp(d)
            horizons = (("1y", ts + pd.DateOffset(years=1)),
                        ("1d", ts + pd.Timedelta(days=1)))
            n_ok = 0
            for lab in labels:
                try:
                    m = S3.leg_metrics(pricer, lab, roll_horizons=horizons)
                except Exception:
                    skips["leg"] += 1
                    continue
                rows.append({"date": ts, "leg": lab,
                             "rate_bp": float(m["rate_bp"]),
                             "dv01": float(m["dv01"]),
                             "gamma": float(m["gamma"]),
                             "roll_1y": float(m["roll_1y"]),
                             "roll_1d": float(m["roll_1d"])})
                n_ok += 1
            if n_ok == len(labels):
                skips["ok"] += 1
        skips["blocked_requests"] = int(network_calls_blocked())
    return rows, skips


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2018, 1, 1))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 8, 20))
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)

    dates = [d.date() for d in pd.bdate_range(a.start, a.end)]
    print(f"legs={_legs()}")
    print(f"{len(dates)} business days {a.start} .. {a.end}, {a.workers} workers")

    n = max(1, len(dates) // (a.workers * 4))
    chunks = [dates[i:i + n] for i in range(0, len(dates), n)]

    t0 = time.time()
    rows: list[dict] = []
    tally = {"ok": 0, "curve": 0, "leg": 0, "blocked_requests": 0}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_chunk, c) for c in chunks]
        for i, f in enumerate(as_completed(futs), 1):
            r, s = f.result()
            rows.extend(r)
            for k, v in s.items():
                tally[k] = tally.get(k, 0) + v
            if i % 5 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)} chunks, {len(rows):,} rows, "
                      f"{time.time() - t0:.0f}s")

    if not rows:
        print("NOTHING BUILT")
        return 1

    panel = (pd.DataFrame(rows)
             .drop_duplicates(subset=["date", "leg"], keep="last")
             .set_index(["date", "leg"]).sort_index())
    OUT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL)
    SIDECAR.write_text(json.dumps(tally, indent=1))

    n_dates = panel.index.get_level_values("date").nunique()
    print(f"\n{len(panel):,} rows x {n_dates:,} dates -> {PANEL} ({time.time() - t0:.0f}s)")
    print(f"skips: {tally}")
    if tally["blocked_requests"]:
        print(f"WARNING: {tally['blocked_requests']} outbound requests were "
              "attempted and refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
