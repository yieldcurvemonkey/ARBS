"""Process-parallel wrapper for the Citi StrikelessVol screen.

Windows-spawn-safe: workers import this module, build their own MDP, price a
chunk of stored days, and return rows; the parent writes one parquet per
market. No ``max_tasks_per_child`` (Windows, per repo memory).

Run:  conda run -n stir python scripts/sv_citivelo_screen_parallel.py USD [workers]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

CHUNK = 120


def _price_chunk(market: str, days: list) -> list:
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    import pandas as pd  # noqa: F401

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, CITIVELO_SOURCE, citivelo_pairs
    from RVUtils.StrikelessVol.greeks import compute_greeks

    pairs = citivelo_pairs([market])
    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    # offline=True reaches the fetcher's fall-through path (fetcher_kwargs picks
    # it off by name) so a store miss re-solves from the banked tag cache and can
    # NEVER open a COM transport into Excel mid-run.
    curve_map = mdp.bulk_get_data(
        {"curve_name": CITIVELO_MARKET_CURVES[market], "timestamps": days, "offline": True}
    )
    rows = []
    for ts in sorted(curve_map, key=str):
        curve = curve_map[ts]
        if curve is None:
            continue
        # Holiday-ghost filter: some stored days (Good Friday etc.) carry
        # London-stamped data whose curve resolves to the PRIOR US session's
        # reference date — two different curves under one label (990 duplicate
        # rows measured on the first USD run, all value-DIFFERING). Keep only
        # curves whose reference date is the day requested.
        ref = curve.reference_date()
        ref_d = ref.date() if hasattr(ref, "date") else ref
        ts_d = ts.date() if hasattr(ts, "date") else ts
        if ref_d != ts_d:
            continue
        for pair in pairs:
            try:
                g = compute_greeks(curve, pair)
            except Exception:
                continue
            rows.append({
                "market": market, "pair": pair.name, "date": str(g.date),
                "short_rate": g.short_rate, "long_rate": g.long_rate,
                "spread_bp": g.spread_bp, "short_dv01": g.short_dv01,
                "long_dv01": g.long_dv01, "package_dv01": g.package_dv01,
                "gamma_10": g.gamma_by_h.get(10.0), "gamma_25": g.gamma_by_h.get(25.0),
                "gamma_50": g.gamma_by_h.get(50.0), "daily_roll_usd": g.daily_roll_usd,
                "be_10": g.breakeven_by_h.get(10.0), "be_25": g.breakeven_by_h.get(25.0),
                "be_50": g.breakeven_by_h.get(50.0),
            })
    return rows


def main() -> None:
    import pandas as pd

    from RVUtils.StrikelessVol.citivelo import stored_dates

    market = (sys.argv[1] if len(sys.argv) > 1 else "USD").upper()
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    start = datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else datetime.date(2005, 1, 1)
    end = datetime.date.fromisoformat(sys.argv[4]) if len(sys.argv) > 4 else datetime.date(2026, 8, 7)

    days = stored_dates(market, start, end)
    chunks = [days[i:i + CHUNK] for i in range(0, len(days), CHUNK)]
    print(f"{market}: {len(days)} days in {len(chunks)} chunks, {workers} workers", flush=True)

    all_rows = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_price_chunk, market, c): i for i, c in enumerate(chunks)}
        done = 0
        for fut in as_completed(futs):
            all_rows.extend(fut.result())
            done += 1
            if done % 5 == 0 or done == len(chunks):
                print(f"  {done}/{len(chunks)} chunks, {len(all_rows):,} rows, "
                      f"{time.time() - t0:.0f}s", flush=True)

    df = pd.DataFrame(all_rows)
    # Hollow-output guard: workers swallow per-(day, pair) failures, so a
    # systematic breakage (missing node, bad curve def) would otherwise write a
    # near-empty parquet indistinguishable from a calm market.
    from RVUtils.StrikelessVol.citivelo import citivelo_pairs

    expected = len(days) * len(citivelo_pairs([market]))
    produced_frac = len(df) / expected if expected else 0.0
    print(f"{market}: produced {len(df):,}/{expected:,} rows ({produced_frac:.1%})", flush=True)
    if expected and produced_frac < 0.8:
        raise SystemExit(
            f"{market}: only {produced_frac:.1%} of expected rows produced - "
            "systematic pricing failure, refusing to write a hollow parquet."
        )
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["pair", "date"])
    out_dir = _REPO / "notebooks" / "data" / "citivelo_rv"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"sv_screen_{market}.parquet"
    df.to_parquet(out, index=False)
    print(f"{market}: wrote {out.name} {len(df):,} rows in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
