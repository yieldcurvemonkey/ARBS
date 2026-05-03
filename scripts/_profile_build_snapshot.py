"""Time the SFR Convex Screener build_snapshot phases for a single date.

Splits the per-date wall-time budget between:
* `load_market_data` — curve, futures snapshot, price panel, smiles
* `extract_bl_marginals`
* `_calibrate_joint`
* `_historical_correlation_matrix`
* per-structure analytics (BL/joint/copula/perfect-corr loop)
* outputs construction + scoring

so the operator can see where the prime is actually spending its wall time.

Usage::

    conda run -n stir python scripts/_profile_build_snapshot.py --as-of 2026-04-28
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("profile_build")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
)
from RVUtils.SFRConvexScreener._distributions import extract_bl_marginals  # noqa: E402
from RVUtils.SFRConvexScreener._market_data import load_market_data  # noqa: E402
from RVUtils.SFRConvexScreener._universe import enumerate_structures  # noqa: E402
from RVUtils.SFRConvexScreener.screener import (  # noqa: E402
    _calibrate_joint,
    _historical_correlation_matrix,
)


def _make_cfg(*, smile_mode: str) -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        correlation_window=60,
        n_simulations=50_000,
        smile_strike_mode=smile_mode,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True)
    p.add_argument("--smile-mode", default="delta_sparse",
                   choices=("delta_sparse", "listed"))
    args = p.parse_args()

    as_of = datetime.date.fromisoformat(args.as_of)
    cfg = _make_cfg(smile_mode=args.smile_mode)

    print(f"\n=== profile build_snapshot @ {as_of} | smile_mode={args.smile_mode} ===")

    t0 = time.monotonic()
    md = load_market_data(cfg, as_of=as_of)
    t_md = time.monotonic() - t0
    print(f"[{t_md:6.1f}s] load_market_data | symbols={len(md.symbols)} smiles={len(md.smiles)} warnings={len(md.warnings)}")

    t1 = time.monotonic()
    structures = enumerate_structures(md.symbols, cfg)
    t_enum = time.monotonic() - t1
    print(f"[{t_enum:6.1f}s] enumerate_structures | n={len(structures)}")

    t2 = time.monotonic()
    marginals = extract_bl_marginals(
        md.smiles,
        jpm_method=cfg.jpm_method,
        ghost_extension_bps=cfg.ghost_extension_bps,
    )
    t_bl = time.monotonic() - t2
    print(f"[{t_bl:6.1f}s] extract_bl_marginals | n_marginals={len(marginals)}")

    current_rate = float("nan")
    if not md.futures_df.empty and "rate" in md.futures_df.columns:
        front_rate = md.futures_df["rate"].dropna()
        if not front_rate.empty:
            current_rate = float(front_rate.iloc[0])
    if not np.isfinite(current_rate):
        current_rate = 4.33

    t3 = time.monotonic()
    if JointMethod.COMMON_STATE in cfg.joint_methods:
        joint_snapshot = _calibrate_joint(md.smiles, as_of=as_of, current_rate=current_rate)
    else:
        joint_snapshot = None
    t_joint = time.monotonic() - t3
    has_js = "yes" if joint_snapshot is not None else "no"
    print(f"[{t_joint:6.1f}s] _calibrate_joint | snapshot={has_js}")

    t4 = time.monotonic()
    corr = _historical_correlation_matrix(md.price_panel, window=cfg.correlation_window)
    t_corr = time.monotonic() - t4
    print(f"[{t_corr:6.1f}s] _historical_correlation_matrix | shape={corr.shape}")

    print(f"\nTOTAL pre-loop: {time.monotonic() - t0:.1f}s")
    print(f"  market_data:   {t_md:.1f}s  ({100*t_md/(time.monotonic()-t0):.0f}%)")
    print(f"  bl_marginals:  {t_bl:.1f}s")
    print(f"  joint_calib:   {t_joint:.1f}s  ({100*t_joint/(time.monotonic()-t0):.0f}%)")
    print(f"  corr_matrix:   {t_corr:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
