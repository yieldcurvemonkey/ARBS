"""Build the Strategy-3 panels: the daily screen and the unit delta-hedge ledgers.

Both artifacts are pure market measurements — no strategy decision is taken here
— so they are computed once, cached to parquet, and read by the two notebooks.

    conda-free:  C:/Users/chris/anaconda3/envs/stir/python.exe scripts/strat3_build_panels.py [what] [workers]

``what`` in {screen, ledgers, all}. Outputs land in
``notebooks/data/convexity_rv/``:

``strat3_leg_panel.parquet``    (date, leg) -> rate_bp, dv01, gamma, roll_1y, roll_1d
``strat3_screen.parquet``       (date, pair) -> the Figure-7 screen, daily
``strat3_ledgers.parquet``      (pair, variant, date) -> the zero-cost unit ledger

The screen is CONSTANT-MATURITY and priced fresh every day: it is a statement
about the market ("the 20y10y has moved", "this curve is 2 sigma steep"), not
about a position. The ledgers hold an AGED package. Mixing the two is the
vintage trap; they are built by different passes here for exactly that reason.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

OUT = _REPO / "notebooks" / "data" / "convexity_rv"
CURVE = "USD-SOFR-1D"
MARKET = "USD"
PKG_DV01 = 100_000.0

#: z-scores need trailing history; P&L is only ever earned in the SAMPLE window.
WARMUP_START = dt.date(2013, 1, 1)
SAMPLE_START = dt.date(2019, 1, 1)
SAMPLE_END = dt.date(2026, 8, 14)

#: The hedging grid. ``roll_months`` changes the segmentation and therefore the
#: packages, so it is the only axis that costs a second cold pass; thresholds,
#: betas and resize modes all ride the same warm CurvePricer cache.
THRESHOLDS = (10.0, 15.0, 20.0, 25.0, 30.0, 40.0)
RESIZE_MODES = ("neutral", "always_decrease")
BETAS = (1.0, 1.025)
ROLL_MONTHS = (12, 24)


def _ok(ts, c) -> bool:
    """Holiday-ghost filter: drop curves whose resolved reference date is not
    the requested day (the store will serve the previous close for a holiday,
    which would silently duplicate a day of P&L)."""
    if c is None:
        return False
    ref = c.reference_date()
    ref_d = ref.date() if hasattr(ref, "date") else ref
    ts_d = ts.date() if hasattr(ts, "date") else ts
    return ref_d == ts_d


def _load_curves(days):
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    cm = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": list(days), "offline": True})
    return {pd.Timestamp(k): v for k, v in cm.items() if k != "live" and _ok(k, v)}


# ---------------------------------------------------------------------------
# 1. leg metrics panel
# ---------------------------------------------------------------------------


def _leg_chunk(days) -> dict:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    sys.path.insert(0, str(_REPO))
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3

    curves = _load_curves(days)
    labels = S3.leg_labels()
    rows = []
    for ts in sorted(curves):
        p = curves[ts]
        horizons = (("1y", ts + pd.DateOffset(years=1)), ("1d", ts + pd.Timedelta(days=1)))
        for lab in labels:
            try:
                m = S3.leg_metrics(p, lab, roll_horizons=horizons)
            except Exception:  # one bad leg on one day must not lose the chunk
                continue
            m["date"] = ts
            m["leg"] = lab
            rows.append(m)
    return {"rows": rows}


def build_leg_panel(workers: int = 6) -> pd.DataFrame:
    from RVUtils.StrikelessVol.citivelo import stored_dates

    days = stored_dates(MARKET, WARMUP_START, SAMPLE_END)
    chunks = [days[i:i + 120] for i in range(0, len(days), 120)]
    print(f"leg panel: {len(days)} days in {len(chunks)} chunks, {workers} workers", flush=True)
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_leg_chunk, c): k for k, c in enumerate(chunks)}
        done = 0
        for fut in as_completed(futs):
            rows.extend(fut.result()["rows"])
            done += 1
            print(f"  chunk {done}/{len(chunks)} ({time.time() - t0:.0f}s)", flush=True)
    panel = pd.DataFrame(rows).set_index(["date", "leg"]).sort_index()
    OUT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUT / "strat3_leg_panel.parquet")
    print(f"leg panel {panel.shape} -> {OUT / 'strat3_leg_panel.parquet'} "
          f"({time.time() - t0:.0f}s)", flush=True)
    return panel


def build_screen(panel: pd.DataFrame | None = None) -> pd.DataFrame:
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3

    if panel is None:
        panel = pd.read_parquet(OUT / "strat3_leg_panel.parquet")
    scr = S3.screen_panel_from_legs(panel, S3.PAIRS_15, package_dv01_usd=PKG_DV01)
    scr = S3.add_screen_stats(scr, panel)
    scr.to_parquet(OUT / "strat3_screen.parquet")
    print(f"screen {scr.shape} -> {OUT / 'strat3_screen.parquet'}", flush=True)
    return scr


# ---------------------------------------------------------------------------
# 2. unit delta-hedge ledgers
# ---------------------------------------------------------------------------


def _variants() -> list:
    return [dict(hedge_threshold_bp=t, resize_mode=m, beta=b)
            for t in THRESHOLDS for m in RESIZE_MODES for b in BETAS]


def _ledger_segment(seg_days, roll_months: int) -> dict:
    """One roll segment: load its curves once, then every pair x every variant.

    The cold cost is the aged-package repricing, which is identical across
    thresholds, betas and resize modes because ``CurvePricer`` caches unit PV,
    unit roll and unit DV01 per date. Measured: 8.3s cold vs 0.25s warm for a
    254-day segment, so the 24 variants ride essentially free.
    """
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    sys.path.insert(0, str(_REPO))
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer

    free = CostSchedule(multiplier=0.0)
    curves = _load_curves(seg_days)
    days = sorted(curves)
    out = {}
    for short, long in S3.PAIRS_15:
        try:
            pair = S3.forward_pair(short, long, market=MARKET, curve_name=CURVE)
            ctx = CurvePricer(curves, pair, package_dv01_usd=PKG_DV01)
            base = S3.Strat3Config(short_leg=short, long_leg=long, market=MARKET,
                                   curve_name=CURVE, package_dv01_usd=PKG_DV01,
                                   roll_months=roll_months)
            for v in _variants():
                cfg = base.with_(**v)
                led = S3.simulate_strat3(ctx, days, cfg, free)
                key = (f"{short}/{long}", roll_months, cfg.hedge_threshold_bp,
                       cfg.beta, cfg.resize_mode)
                out[key] = led.reset_index().to_dict("list")
        except Exception as exc:  # noqa: BLE001 - a pair failing a segment is recorded
            out[(f"{short}/{long}", roll_months, -1.0, -1.0, f"ERROR:{type(exc).__name__}:{exc}")] = {}
    return out


def build_ledgers(workers: int = 5) -> pd.DataFrame:
    import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
    from RVUtils.StrikelessVol.citivelo import stored_dates

    days = stored_dates(MARKET, SAMPLE_START, SAMPLE_END)
    tasks = []
    for rm in ROLL_MONTHS:
        for (i, j) in S3.roll_segments(days, rm):
            tasks.append((days[i:j + 1], rm))
    print(f"ledgers: {len(days)} days -> {len(tasks)} segment tasks, {workers} workers",
          flush=True)
    t0 = time.time()
    collected: dict = {}
    errors: list = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_ledger_segment, sd, rm): (len(sd), rm) for sd, rm in tasks}
        done = 0
        for fut in as_completed(futs):
            for key, payload in fut.result().items():
                if not payload:
                    errors.append(key)
                    continue
                df = pd.DataFrame(payload).set_index("date")
                df.index = pd.to_datetime(df.index)
                collected.setdefault(key[:4] + (key[4],), []).append(df)
            done += 1
            print(f"  seg {done}/{len(tasks)} ({time.time() - t0:.0f}s)", flush=True)
    if errors:
        print(f"  !! {len(errors)} pair-segments failed: {errors[:5]}", flush=True)

    stitched = {}
    for key, frames in collected.items():
        frames = sorted(frames, key=lambda f: f.index[0])
        stitched[key] = S3.stitch_segments(frames)
    out = pd.concat(stitched, names=["pair", "roll_months", "threshold_bp", "beta",
                                     "resize_mode", "date"])
    out.to_parquet(OUT / "strat3_ledgers.parquet")
    print(f"ledgers {out.shape} -> {OUT / 'strat3_ledgers.parquet'} "
          f"({time.time() - t0:.0f}s)", flush=True)
    return out


def main() -> None:
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    OUT.mkdir(parents=True, exist_ok=True)
    if what in ("all", "screen"):
        panel = build_leg_panel(workers)
        build_screen(panel)
    if what in ("all", "ledgers"):
        build_ledgers(min(workers, 5))


if __name__ == "__main__":
    main()
