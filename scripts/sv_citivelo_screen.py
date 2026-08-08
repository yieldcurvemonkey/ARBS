"""Full-history StrikelessVol screen on the Citi Velocity curves (Task 30/26).

Per (market, pair, stored EOD day): repriced greeks — spread, DV01s, Γ(10/25/50),
daily $ roll, BE(h) — via the study package's own ``compute_greeks``. Output is
one parquet per market under ``notebooks/data/citivelo_rv/sv_screen_<MKT>.parquet``,
the input to the grail-quadrant detector (H13), the BE/RV screen and the oracle
gate. Descriptive: nothing here selects on performance.

Run:  conda run -n stir python scripts/sv_citivelo_screen.py USD [start] [end]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import logging
import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import pandas as pd

logging.basicConfig(level=logging.WARNING)
logging.getLogger("RVUtils.StrikelessVol").setLevel(logging.ERROR)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from RVUtils.StrikelessVol.citivelo import (
    CITIVELO_MARKET_CURVES,
    CITIVELO_SOURCE,
    citivelo_pairs,
    stored_dates,
)
from RVUtils.StrikelessVol.greeks import compute_greeks

OUT_DIR = _REPO / "notebooks" / "data" / "citivelo_rv"
CHUNK = 250


def run_market(market: str, start: datetime.date, end: datetime.date) -> pathlib.Path:
    pairs = citivelo_pairs([market])
    days = stored_dates(market, start, end)
    print(f"{market}: {len(days)} stored days {days[0] if days else '-'}..{days[-1] if days else '-'}, "
          f"{len(pairs)} pairs", flush=True)
    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    curve_name = CITIVELO_MARKET_CURVES[market]

    rows = []
    dropped = 0
    t0 = time.time()
    for lo in range(0, len(days), CHUNK):
        chunk = days[lo:lo + CHUNK]
        curve_map = mdp.bulk_get_data(
            {"curve_name": curve_name, "timestamps": chunk, "offline": True}
        )
        for ts in sorted(curve_map, key=str):
            curve = curve_map[ts]
            if curve is None:
                dropped += 1
                continue
            for pair in pairs:
                try:
                    g = compute_greeks(curve, pair)
                except Exception:  # one pair failing one day must not stop 20 years
                    dropped += 1
                    continue
                rows.append({
                    "market": market,
                    "pair": pair.name,
                    "date": pd.Timestamp(g.date),
                    "short_rate": g.short_rate,
                    "long_rate": g.long_rate,
                    "spread_bp": g.spread_bp,
                    "short_dv01": g.short_dv01,
                    "long_dv01": g.long_dv01,
                    "package_dv01": g.package_dv01,
                    "gamma_10": g.gamma_by_h.get(10.0),
                    "gamma_25": g.gamma_by_h.get(25.0),
                    "gamma_50": g.gamma_by_h.get(50.0),
                    "daily_roll_usd": g.daily_roll_usd,
                    "be_10": g.breakeven_by_h.get(10.0),
                    "be_25": g.breakeven_by_h.get(25.0),
                    "be_50": g.breakeven_by_h.get(50.0),
                })
        del curve_map
        done = min(lo + CHUNK, len(days))
        rate = done / max(time.time() - t0, 1e-9)
        print(f"  {market} {done}/{len(days)} days ({rate:.1f} d/s, {dropped} drops)", flush=True)

    df = pd.DataFrame(rows).sort_values(["pair", "date"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"sv_screen_{market}.parquet"
    df.to_parquet(out, index=False)
    print(f"{market}: wrote {out.name} {len(df):,} rows, {dropped} drops, "
          f"{time.time() - t0:.0f}s", flush=True)
    return out


if __name__ == "__main__":
    market = (sys.argv[1] if len(sys.argv) > 1 else "USD").upper()
    start = datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else datetime.date(2005, 1, 1)
    end = datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else datetime.date(2026, 8, 7)
    run_market(market, start, end)
