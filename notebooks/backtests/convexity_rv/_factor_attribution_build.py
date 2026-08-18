"""Artifact builder for the cross-strategy factor attribution.

The only slow input is the daily par-rate panel: ~1,900 business days x 12
tenors of curve pricing, ~7 minutes cold and seconds warm. nbconvert's timeout
does not like the cold path, so it is built here and the notebook loads the
parquet.

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_factor_attribution_build.py rates
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV.factor_attribution import FactorConfig, build_rate_panel

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)


def build_rates() -> None:
    cfg = FactorConfig()
    out = DATA / "factor_rate_panel.parquet"
    t0 = time.time()
    panel = build_rate_panel(cfg, n_jobs=8, show_tqdm=True)
    panel.to_parquet(out)
    print(f"wrote {out.name} {panel.shape} in {time.time() - t0:.0f}s", flush=True)
    print(panel.notna().sum().to_string(), flush=True)
    print(panel.head(2).to_string(), flush=True)
    print(panel.tail(2).to_string(), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rates"
    if cmd == "rates":
        build_rates()
    else:
        raise SystemExit(f"unknown command {cmd!r}")
