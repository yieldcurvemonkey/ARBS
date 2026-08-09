"""Measure the copula coordinate across every session we can, not one.

The published lambda_wing = 0.54 was computed on a single session -- and on the session with
the deepest trough in an eight-day window, which is the favourable end of a range, not its
centre. This walks a real history so the range itself is measurable.

    python notebooks/rv/sr3_zq_lambda_backfill.py --symbols SFRZ26,SFRU26 \
        --start 2026-04-01 --end 2026-08-07 --out notebooks/data/sr3_zq_lambda/panel.csv

Run from the repo root with the env python directly. Barchart fetches are SERIALIZED: the
per-symbol raw-EOD cache holds full history, so the first session of a contract pays for its
whole option chain and every later session is free.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import traceback

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from RVUtils.SR3ZQDistributionScreener._lambda_signal import (  # noqa: E402
    build_meeting_set,
    measure_lambda,
)

DEFAULT_OUT = "notebooks/data/sr3_zq_lambda/panel.csv"


def zq_universe(years=(24, 25, 26, 27, 28)):
    return [f"ZQ{c}{y}" for y in years for c in "FGHJKMNQUVXZ"]


#: Prebuilt full-history ZQ panel. It lives in the PRIMARY checkout because notebooks/data is
#: gitignored, so a worktree that used the relative default would find an empty directory and
#: silently start a multi-hour Barchart backfill instead of reading 103k rows that exist.
ZQ_PANEL_PARQUET = r"C:\Users\chris\clee\ARBS\notebooks\data\zq_kink_fade\contracts.parquet"


def load_zq_panel(start: datetime.date, end: datetime.date, refresh: bool) -> pd.DataFrame:
    """Wide date x ZQ-symbol settle panel, prebuilt history overlaid with the serff tail.

    Neither source alone is enough: the prebuilt panel stops weeks before today, and the
    serff EOD cache only holds whatever windows happen to have been fetched -- for the 2026
    front months that is nine bars. Where both have a session the serff value wins, because
    it is the one that gets refreshed.
    """
    from RVUtils.MeetingProb.ladder import zq_settle_panel

    frames = []
    if os.path.exists(ZQ_PANEL_PARQUET):
        raw = pd.read_parquet(ZQ_PANEL_PARQUET, columns=["as_of", "code", "settle"])
        raw["symbol"] = "ZQ" + raw["code"].astype(str)  # the panel's `code` is BARE ("F18")
        wide = raw.pivot_table(index="as_of", columns="symbol", values="settle", aggfunc="last")
        wide.index = pd.to_datetime(wide.index)
        frames.append(wide)
        print(f"  prebuilt ZQ panel: {wide.shape[0]} sessions x {wide.shape[1]} contracts, "
              f"{wide.index.min().date()} .. {wide.index.max().date()}")
    else:
        print(f"  WARNING: no prebuilt ZQ panel at {ZQ_PANEL_PARQUET}")

    syms = zq_universe()
    tail = zq_settle_panel(syms)
    if not tail.empty:
        tail.index = pd.to_datetime(tail.index)
        frames.append(tail)
        print(f"  serff ZQ cache:    {tail.shape[0]} sessions x {tail.shape[1]} contracts, "
              f"{tail.index.min().date()} .. {tail.index.max().date()}")

    if not frames:
        raise SystemExit("no ZQ settle source available")

    panel = frames[0]
    for extra in frames[1:]:
        panel = extra.combine_first(panel)
    panel = panel.sort_index()

    need_end = pd.Timestamp(end)
    if refresh or panel.index.max() < need_end:
        from BT.serff.futures_data import backfill_settles

        print(f"  panel ends {panel.index.max().date()}; backfilling ZQ settles to {end}")
        backfill_settles(start - datetime.timedelta(days=45), end, symbols=syms, show_progress=True)
        tail = zq_settle_panel(syms)
        tail.index = pd.to_datetime(tail.index)
        panel = tail.combine_first(panel).sort_index()
    return panel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SFRZ26")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--refresh-zq", action="store_true")
    ap.add_argument("--non-meeting-vol-bp", type=float, default=40.0)
    ap.add_argument("--max-sessions", type=int, default=0, help="0 = no cap")
    ap.add_argument(
        "--auto-window",
        action="store_true",
        help=(
            "per contract, measure only [expiry-lookback, expiry-min-dte]. Outside that the "
            "chain is either not quoted yet or the meeting set is too large for the option "
            "strike range to span, and every wasted session is a Barchart request"
        ),
    )
    ap.add_argument("--lookback-days", type=int, default=260)
    ap.add_argument("--min-dte-days", type=int, default=14)
    args = ap.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
    from RVUtils.ImpliedDistribution import SFRImpliedDistribution
    from SDRUtils.analytics.fomc import load_fomc_schedule

    fomc = load_fomc_schedule("USD-SOFR-1D")
    zq = load_zq_panel(start, end, args.refresh_zq)
    sessions = [d.date() for d in zq.index if start <= d.date() <= end]
    if args.max_sessions:
        sessions = sessions[-args.max_sessions:]
    print(f"  {len(sessions)} ZQ sessions in range, {len(symbols)} contract(s)")

    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    # The exact configuration the framework requires: observed premiums, no open-interest
    # screen, OTM only, NO silent SABR substitution, and a vol-space fit (price space scales
    # quote noise by 1/dK^2 and at dK=0.125 with a 0.0025 tick it is unusable).
    dist = SFRImpliedDistribution(
        use_sabr_vols=False,
        raw_market_open_interest_min=None,
        raw_market_otm_only=True,
        allow_sabr_fallback=False,
        fit_space="vol",
    )

    rows = []
    failures: dict[str, int] = {}
    t0 = time.time()
    for symbol in symbols:
        symbol_sessions = sessions
        if args.auto_window:
            from MDP.STIRFutures.STIRFutureOptionMDP import _sofr_option_expiry_date

            expiry = _sofr_option_expiry_date(symbol.replace("SFR", "SR3"), symbol[-3:])
            lo = expiry - datetime.timedelta(days=args.lookback_days)
            hi = expiry - datetime.timedelta(days=args.min_dte_days)
            symbol_sessions = [d for d in sessions if lo <= d <= hi]
            print(f"  {symbol}: expiry {expiry}, window {lo} .. {hi} -> {len(symbol_sessions)} sessions")
            if not symbol_sessions:
                continue
        for i, d in enumerate(symbol_sessions):
            ts = pd.Timestamp(d)
            prices = {s: float(zq.loc[ts, s]) for s in zq.columns
                      if ts in zq.index and np.isfinite(zq.loc[ts, s])}
            if len(prices) < 6:
                failures["too few ZQ prices"] = failures.get("too few ZQ prices", 0) + 1
                continue
            try:
                smile = opt_mdp.fetch_sabr_smile(
                    {"symbol": symbol, "as_of": d, "strike_offsets_bps": "listed"}
                )
                snap = dist.extract(smile, run_gm=False, run_bkm=True)
                bl = snap.bl_result
                if bl is None:
                    raise ValueError("no BL result")
            except Exception as exc:  # noqa: BLE001 - a thin chain is a data fact, not a crash
                key = f"{type(exc).__name__}: {str(exc)[:60]}"
                failures[key] = failures.get(key, 0) + 1
                continue

            try:
                ms = build_meeting_set(
                    as_of=d, symbol=symbol, zq_prices=prices,
                    fomc_schedule=fomc, expiry=bl.input.expiry_date,
                )
                m = measure_lambda(
                    meeting_set=ms, bl_result=bl,
                    sr3_forward_rate_pct=float(bl.input.forward_rate),
                    non_meeting_vol_bp_per_sqrt_year=args.non_meeting_vol_bp,
                )
            except Exception as exc:  # noqa: BLE001
                key = f"measure {type(exc).__name__}: {str(exc)[:60]}"
                failures[key] = failures.get(key, 0) + 1
                continue

            row = m.to_row()
            row["forward_price"] = float(bl.input.forward_price)
            row["time_to_expiry"] = float(bl.input.time_to_expiry)
            row["expiry"] = bl.input.expiry_date
            row["n_meetings"] = ms.n_resolved
            row["meeting_labels"] = ",".join(ms.resolved_labels)
            row["bkm_std_bp"] = (
                float(snap.bkm_result.std_rate) * 100.0 if snap.bkm_result is not None else float("nan")
            )
            row["is_model_density"] = snap.is_model_density
            rows.append(row)

            if (i + 1) % 10 == 0:
                print(f"    {symbol} {d}  n={len(rows)}  elapsed {time.time() - t0:.0f}s")

    if not rows:
        print("  NO ROWS. failures:")
        for k, v in sorted(failures.items(), key=lambda kv: -kv[1]):
            print(f"    {v:5d}  {k}")
        return 1

    df = pd.DataFrame(rows)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n  wrote {len(df)} rows -> {out}  ({time.time() - t0:.0f}s)")
    if failures:
        print("  skipped sessions by reason:")
        for k, v in sorted(failures.items(), key=lambda kv: -kv[1]):
            print(f"    {v:5d}  {k}")

    ok = df[df.ok]
    print(f"\n  {len(ok)} usable of {len(df)}")
    if len(ok):
        for col in ("lambda_wing", "lambda_wing_renorm", "lambda_var", "lambda_atom_spread",
                    "trough_peak_ratio", "forward_residual_bp", "basis_bp"):
            s = pd.to_numeric(ok[col], errors="coerce").dropna()
            if len(s):
                print(f"    {col:22s} n={len(s):3d}  mean {s.mean():+.3f}  sd {s.std():.3f}  "
                      f"min {s.min():+.3f}  p25 {s.quantile(.25):+.3f}  med {s.median():+.3f}  "
                      f"p75 {s.quantile(.75):+.3f}  max {s.max():+.3f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
