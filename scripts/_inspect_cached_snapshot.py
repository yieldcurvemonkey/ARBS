"""Load the cached snapshot for 2026-03-30 and inspect each signal's parameters."""
from __future__ import annotations
import datetime, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener._backtest_cache import SnapshotCache
from RVUtils.SFRConvexScreener._backtest_signals import build_signal_table_from_snapshots
from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache


from RVUtils.SFRConvexScreener._backtest_cache import snapshot_cache_key
import pickle

cfg = SFRConvexScreenerConfig(universe_size=12, jpm_method=True)
cache = SnapshotCache(root="data/screener_results/sfr_convex_screener_backtest_cache")
cs = _config_summary_for_cache(cfg)
print(f"current config_summary={cs}")
print(f"current cache_key for 2026-03-30: {snapshot_cache_key(datetime.date(2026, 3, 30), cs)}")

# Force-load by pickle path
direct_path = Path("data/screener_results/sfr_convex_screener_backtest_cache/2026-03-30_60855039beb3.pkl")
with direct_path.open("rb") as fh:
    snap = pickle.load(fh)
print(f"Direct load OK: as_of={snap.as_of}, results={len(snap.results)}")
print(f"snap.config_summary = {snap.config_summary}")
if snap is None:
    print("No cached snapshot for 2026-03-30")
    sys.exit(1)

sigtable = build_signal_table_from_snapshots([snap])
sigs = sigtable[datetime.date(2026, 3, 30)]
print(f"Signals on 2026-03-30: {len(sigs)}")
for s in sigs[:8]:
    sd = s.structure_def
    print(f"  {sd.structure_id} type={sd.structure_type.value} legs={len(sd.legs)} asym={s.asymmetry_ratio:.3f} composite={s.composite_score:.3f} flip={s.flip}")
    for leg in sd.legs:
        print(f"    {leg.contract} weight={leg.weight} price={leg.price}")
