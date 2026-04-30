"""Print the cache filename hash for listed vs delta_sparse smile modes."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from RVUtils.SFRConvexScreener import JointMethod, SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener._backtest_cache import snapshot_cache_key
from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache


def main() -> int:
    common = dict(
        universe_size=12, include_outrights=True, jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        correlation_window=60, n_simulations=50_000,
    )
    cfg_listed = SFRConvexScreenerConfig(**common, smile_strike_mode="listed")
    cfg_sparse = SFRConvexScreenerConfig(**common, smile_strike_mode="delta_sparse")
    d = datetime.date(2026, 4, 28)
    print("listed:", snapshot_cache_key(d, _config_summary_for_cache(cfg_listed)))
    print("sparse:", snapshot_cache_key(d, _config_summary_for_cache(cfg_sparse)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
