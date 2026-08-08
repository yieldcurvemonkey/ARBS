"""F6 gate — the intraday pond, measured on the minute curves (last unmined asset).

The STIR-intraday lesson is the prior: a round trip costs the same at every
frequency while E|move| shrinks with horizon, so intraday makes the killing
ratio strictly worse. This gate measures the swap version: hourly snapshots
from the 1-min USD curve store (asset USD-SOFR-1D-CITIVELO, 2023-01..2026-07),
forward par rates computed VECTORIZED from stored DF nodes (log-DF linear
interpolation, annual annuity approximation — verified against one rateslib
reconstruction before use), then E|Δ| at 1h/4h/1d/5d horizons for the SV
spreads and generic structures vs their frequency-invariant round trips.

Run: conda run -n stir python scripts/f6_intraday_pond_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
ASSET = "USD-SOFR-1D-CITIVELO"
HOURLY_MINUTES = 60  # subsample stride within each day's snapshots


def annual_grid_forwards(node_days: np.ndarray, log_dfs: np.ndarray,
                         max_years: int = 30) -> np.ndarray:
    """Annual DFs D(1..max_years) by linear interp of log-DF in ACT/365 time."""
    t_nodes = node_days / 365.0
    t_grid = np.arange(1, max_years + 1, dtype=float)
    return np.exp(np.interp(t_grid, t_nodes, log_dfs))


def par_forward(D: np.ndarray, a: int, b: int) -> float:
    """Par rate of an a-year-forward b-year swap, annual unit-dcf annuity.

    D is the annual DF grid D[0]=D(1y)..D[n-1]=D(n y); prepend D(0)=1
    implicitly: start DF is D(a) (a=0 -> 1.0).
    """
    Da = 1.0 if a == 0 else D[a - 1]
    Db = D[a + b - 1]
    annuity = D[a:a + b].sum()
    return (Da - Db) / annuity


STRUCTS = {
    # label -> (weights on par_forward args, round-trip bp)
    # SV forward spreads at the registered package schedule (0.75bp initiation RT x2 legs? no:
    # the Fig-9 initiation 0.75bp is the PACKAGE one-way -> RT 1.5bp for enter+exit)
    "10y10y/20y10y": ([( (10, 10), -1.0), ((20, 10), +1.0)], 1.5),
    "15y5y/20y10y": ([((15, 5), -1.0), ((20, 10), +1.0)], 1.5),
    # spot 2s10s30s fly (cost_model half-spreads: 2y 0.35, 10y 0.75, 30y 1.75 ->
    # package RT = sum |w|*halfspread*2 with 0.5/1/0.5 weights = 2*(0.5*0.35+1*0.75+0.5*1.75) = 3.6)
    "2s10s30s": ([((0, 2), -0.5), ((0, 10), +1.0), ((0, 30), -0.5)], 3.6),
    # 10y outright (RT = 2*0.75)
    "10y": ([((0, 10), +1.0)], 1.5),
}


def snapshot_rates(row) -> dict:
    ref = pd.Timestamp(row["trading_date"])
    nd = pd.to_datetime(pd.Series(list(row["node_dates"])))
    days = (nd - ref).dt.days.to_numpy(dtype=float)
    dfs = np.asarray(list(row["discount_factors"]), dtype=float)
    keep = days > 0
    D = annual_grid_forwards(days[keep], np.log(dfs[keep]))
    out = {}
    for name, (legs, _) in STRUCTS.items():
        out[name] = sum(w * par_forward(D, a, b) for (a, b), w in legs) * 1e4  # bp
    return out


def verify_against_rateslib(day: datetime.date) -> None:
    """Rule 13: the DF-space calculator vs one rateslib reconstruction."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Caching.curve_store import CurveStore

    cs = CurveStore.default()
    raw = cs.read_raw_day(ASSET, day)
    row = raw.iloc[len(raw) // 2]
    mine = snapshot_rates(row)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    cm = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": [day],
                            "offline": True})
    curve = [c for c in cm.values() if c is not None][0]
    rl_1010 = float(curve.fair_rate(curve.build_irswap(fwd="10Y", tenor="10Y"))) * 1e4
    rl_2010 = float(curve.fair_rate(curve.build_irswap(fwd="20Y", tenor="10Y"))) * 1e4
    rl_spread = rl_2010 - rl_1010
    diff = mine["10y10y/20y10y"] - rl_spread
    print(f"verify {day}: DF-space 10y10y/20y10y {mine['10y10y/20y10y']:+.1f}bp vs "
          f"rateslib EOD {rl_spread:+.1f}bp -> level basis {diff:+.2f}bp "
          f"(intraday-vs-EOD + annuity approx; MOVES are what the gate uses)")
    if abs(diff) > 8.0:
        raise SystemExit("DF-space calculator disagrees with rateslib by >8bp - refusing")


def main() -> None:
    from Caching.curve_store import CurveStore

    cs = CurveStore.default()
    days = cs.available_dates(ASSET)
    print(f"{ASSET}: {len(days)} days {days[0]}..{days[-1]}")
    verify_against_rateslib(days[len(days) // 2])

    t0 = time.time()
    rows = []
    for i, d in enumerate(days):
        raw = cs.read_raw_day(ASSET, d)
        if raw is None or not len(raw):
            continue
        raw = raw.sort_values("session_minute")
        sub = raw.iloc[::HOURLY_MINUTES]
        for _, r in sub.iterrows():
            rec = snapshot_rates(r)
            rec["ts"] = r["timestamp_utc"]
            rows.append(rec)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(days)} days ({time.time() - t0:.0f}s)", flush=True)

    panel = pd.DataFrame(rows).set_index("ts").sort_index()
    panel.to_parquet(DATA / "f6_intraday_panel.parquet")
    print(f"panel: {panel.shape} in {time.time() - t0:.0f}s")

    print("\nPOND TABLE — median |Δ| in bp at horizon vs frequency-invariant RT:")
    hours = pd.Series(panel.index).diff().dt.total_seconds().div(3600).median()
    for name, (_, rt) in STRUCTS.items():
        s = panel[name]
        line = [f"{name:>14s} (RT {rt:.1f}bp):"]
        for h_steps, label in ((1, "1h"), (4, "4h"), (8, "1d"), (40, "5d")):
            d = s.diff(h_steps).abs().dropna()
            med = float(d.median())
            line.append(f"{label} {med:5.2f} ({med / rt:4.2f}x)")
        print("  " + "  ".join(line))


if __name__ == "__main__":
    main()
