"""Lean quotes-only backfill for old/missing SR3 option expiries (family B).

Fetches listed settle premiums per (symbol, day) through the same
fetch_sabr_smile path the lab panels used (per-symbol full-history EOD cache
makes day 1 cold and the rest warm), but stores ONLY the quote rows — no
SABR/BL/CDF. Forwards come from serff SR3 settles downstream. Checkpointed
per symbol; reruns skip finished symbols.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-xm")

import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from MDP.STIRFutures._sofr_option_contracts import sofr_option_last_trade_date

OUT = Path(r"C:\Users\chris\clee\ARBS-xm\notebooks\data\famb\parts")
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["SFRZ24", "SFRU24", "SFRM24", "SFRH24",
           "SFRZ23", "SFRU23", "SFRM23", "SFRH23",
           "SFRZ22", "SFRU22", "SFRM22", "SFRH22"]
MAX_DTE = 400          # rank<=3 books never need more


def run_symbol(mdp, sym: str) -> None:
    out_path = OUT / f"{sym}_quotes.parquet"
    if out_path.exists():
        print(f"[{sym}] warm — skip", flush=True)
        return
    expiry = sofr_option_last_trade_date(sym)
    days = pd.bdate_range(pd.Timestamp(expiry) - pd.Timedelta(days=MAX_DTE),
                          pd.Timestamp(expiry))
    rows, fails = [], 0
    t0 = time.time()
    for ts in days:
        try:
            sm = mdp.fetch_sabr_smile({"symbol": sym, "as_of": ts.date(),
                                       "strike_offsets_bps": "listed"})
            for p in sm.points:
                rows.append({
                    "as_of": ts, "symbol": sym, "right": p.right,
                    "strike_price": p.strike_price,
                    "strike_rate": p.strike_rate,
                    "premium_bp": p.market_price * 100.0,
                    "oi": p.open_interest, "volume": p.volume,
                })
        except Exception:
            fails += 1
    df = pd.DataFrame(rows)
    df.to_parquet(out_path, index=False)
    print(f"[{sym}] {len(df)} rows over {df['as_of'].nunique() if len(df) else 0}"
          f" days ({fails} empty/fail) in {time.time()-t0:.0f}s", flush=True)


def main():
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    for sym in SYMBOLS:
        run_symbol(mdp, sym)
    parts = sorted(OUT.glob("*_quotes.parquet"))
    merged = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    merged.to_parquet(OUT.parent / "quotes_old.parquet", index=False)
    print(f"MERGED {len(parts)} symbols -> {len(merged)} rows", flush=True)


if __name__ == "__main__":
    main()
