"""Wing-premium panel: every listed strike's settle premium per (as_of, symbol).

Writes notebooks/data/fly_vs_vol/wing_premiums.parquet with columns:
as_of, symbol, right, strike_price, strike_rate, premium_bp, oi.
Uses the bulk smile path (fast, fully cached).
"""
import time

import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

SYMS = ["SFRU26", "SFRZ26", "SFRH27", "SFRM27", "SFRU27", "SFRZ27", "SFRH28", "SFRM28"]
DATES = [d.date() for d in pd.bdate_range("2025-06-02", "2026-07-27")]
OUT = r"notebooks/data/fly_vs_vol/wing_premiums.parquet"

mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
rows = []
for sym in SYMS:
    t0 = time.time()
    try:
        smiles = mdp.fetch_bulk_sabr_smile({
            "symbols": [sym], "timestamps": DATES, "strike_offsets_bps": "listed",
        }).get(sym, {}) or {}
    except Exception:
        smiles = {}
        for d in DATES:
            try:
                smiles[d] = mdp.fetch_sabr_smile({
                    "symbol": sym, "as_of": d, "strike_offsets_bps": "listed"})
            except Exception:
                continue
    n = 0
    for d, smile in smiles.items():
        for p in smile.points:
            if p.market_price is None:
                continue
            rows.append({
                "as_of": pd.Timestamp(d), "symbol": sym, "right": p.right,
                "strike_price": float(p.strike_price),
                "strike_rate": float(p.strike_rate),
                "premium_bp": float(p.market_price) * 100,
                "oi": float(p.open_interest or 0),
            })
            n += 1
    print(f"{sym}: {len(smiles)} dates, {n} quotes in {time.time() - t0:.0f}s", flush=True)

df = pd.DataFrame(rows).sort_values(["symbol", "as_of", "right", "strike_price"])
df.to_parquet(OUT, index=False)
print(f"wrote {OUT}: {df.shape}", flush=True)
