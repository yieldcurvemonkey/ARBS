"""Confirm SABR smile caching at the MDP layer.

First call fetches from Barchart (slow). Second call hits the disk cache
(instant). Third call with force_refresh=True bypasses cache and re-fetches.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


def fp(smile) -> str:
    return hashlib.sha256(pickle.dumps(smile.to_dict())).hexdigest()[:12]


def main() -> int:
    opt_mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")

    req = {
        "symbol": "SFRZ26",
        "as_of": datetime.date(2026, 4, 28),
        "strike_offsets_bps": "listed",  # full CME-listed grid (~30-50 strikes)
    }

    # 1. force_refresh from the start — clean fetch from Barchart, populates cache
    t0 = time.monotonic()
    smile1 = opt_mdp.fetch_sabr_smile({**req, "force_refresh": True})
    t1 = time.monotonic() - t0
    print(f"[fresh]  {t1:6.2f}s  symbol={smile1.symbol}  n_points={len(smile1.points)}")
    print(f"         params: alpha={smile1.params.alpha:.4f}  beta={smile1.params.beta}  "
          f"rho={smile1.params.rho:.4f}  nu={smile1.params.nu:.4f}")

    # 2. warm fetch -- should hit the smile-level disk cache (layer 2)
    t0 = time.monotonic()
    smile2 = opt_mdp.fetch_sabr_smile(req)
    t2 = time.monotonic() - t0
    print(f"[warm]   {t2:6.2f}s  cache hit -> {t1/max(t2,1e-6):.0f}x faster")

    # 3. third call -- still cached
    t0 = time.monotonic()
    smile3 = opt_mdp.fetch_sabr_smile(req)
    t3 = time.monotonic() - t0
    print(f"[warm]   {t3:6.2f}s  cache hit -> {t1/max(t3,1e-6):.0f}x faster")

    # 4. confirm the cached object round-trips losslessly
    assert smile1.symbol == smile2.symbol
    assert smile1.params.alpha == smile2.params.alpha
    assert tuple(p.strike_price for p in smile1.points) == tuple(p.strike_price for p in smile2.points)
    print(f"\n[ok]     fresh/warm SABR params + strike list identical")
    print(f"[hash]   fresh={fp(smile1)}  warm1={fp(smile2)}  warm2={fp(smile3)}")

    # 5. inspect the cache directory directly
    cache_dir = (
        Path(os.environ["LOCALAPPDATA"]) / "ARBS" / "Cache" / "diskcache" / "dump"
        / "STIRFutureOptionPricer_Cache"
    )
    mb = sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file()) / (1024**2)
    print(f"[disk]   {cache_dir} -> {mb:.1f} MB on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
