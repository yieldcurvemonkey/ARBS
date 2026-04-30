"""Compare a primed SFR Convex Screener snapshot under listed vs delta_sparse
smile-fetch modes for the same as_of, to validate the methodology change.

Loads two pickled snapshots, both keyed on the same as_of date but on
different config-hashes (one for ``smile_strike_mode='listed'`` and one for
``smile_strike_mode='delta_sparse'``), and reports:

* top-5 ranking overlap by ``composite_score``
* per-structure asymmetry_ratio diff distribution

Usage::

    conda run -n stir python scripts/_check_smile_mode_parity.py \\
        --as-of 2026-04-28
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("smile_parity")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
)
from RVUtils.SFRConvexScreener._backtest_cache import snapshot_cache_key  # noqa: E402
from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache  # noqa: E402


def _make_cfg(*, smile_mode: str) -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        joint_methods=(
            JointMethod.HISTORICAL_GAUSSIAN_COPULA,
            JointMethod.PERFECT_CORRELATION,
        ),
        correlation_window=60,
        n_simulations=50_000,
        smile_strike_mode=smile_mode,
    )


def _load_snapshot(*, cache_root: Path, as_of: datetime.date,
                   smile_mode: str,
                   explicit_hash: Optional[str] = None) -> Optional[Any]:
    """Load a pickled snapshot. ``explicit_hash`` lets the caller bypass the
    config-summary -> hash computation, so old pickles whose hash predates
    the smile_strike_mode field can still be inspected by short-hash prefix.
    """
    if explicit_hash is not None:
        pkl = cache_root / f"{as_of.isoformat()}_{explicit_hash}.pkl"
    else:
        cfg = _make_cfg(smile_mode=smile_mode)
        summary = _config_summary_for_cache(cfg)
        key = snapshot_cache_key(as_of, summary)
        pkl = cache_root / f"{key}.pkl"
    if not pkl.exists():
        logger.warning("missing %s pickle for %s @ %s", smile_mode, as_of, pkl)
        return None
    try:
        with pkl.open("rb") as fh:
            return pickle.load(fh)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load %s: %r", pkl, exc)
        return None


def _summary_rows(snap: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in (snap.results or ()):
        primary = r.metrics_by_method.get(r.primary_method)
        if primary is None:
            continue
        out.append({
            "rank": r.rank,
            "structure_id": r.structure_def.structure_id,
            "type": r.structure_def.structure_type.value,
            "direction": r.direction(),
            "composite_score": float(r.composite_score),
            "asymmetry_ratio": float(getattr(primary, "asymmetry_ratio", float("nan"))),
            "p_profit": float(getattr(primary, "p_profit", float("nan"))),
            "expected_value_bp": float(getattr(primary, "expected_value_bp", float("nan"))),
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True)
    p.add_argument("--cache-root",
                   default="data/screener_results/sfr_convex_screener_backtest_cache")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--listed-hash", default=None,
                   help="Explicit hash for the listed pickle (e.g. legacy '60855039beb3' "
                        "from a config-summary that predates smile_strike_mode)")
    p.add_argument("--sparse-hash", default=None,
                   help="Explicit hash for the sparse pickle")
    args = p.parse_args()

    as_of = datetime.date.fromisoformat(args.as_of)
    cache_root = Path(args.cache_root)

    listed = _load_snapshot(cache_root=cache_root, as_of=as_of, smile_mode="listed",
                            explicit_hash=args.listed_hash)
    sparse = _load_snapshot(cache_root=cache_root, as_of=as_of, smile_mode="delta_sparse",
                            explicit_hash=args.sparse_hash)
    if listed is None or sparse is None:
        logger.error("Need both listed and sparse pickles for %s; aborting", as_of)
        return 2

    L = _summary_rows(listed)
    S = _summary_rows(sparse)
    L_by_id = {r["structure_id"]: r for r in L}
    S_by_id = {r["structure_id"]: r for r in S}

    L_sorted = sorted(L, key=lambda r: r["composite_score"], reverse=True)
    S_sorted = sorted(S, key=lambda r: r["composite_score"], reverse=True)

    print(f"\n=========== SMILE PARITY @ {as_of} ===========")
    print(f"  listed n={len(L)}  sparse n={len(S)}")

    # 1. Top-K overlap
    L_top = [r["structure_id"] for r in L_sorted[: args.top_k]]
    S_top = [r["structure_id"] for r in S_sorted[: args.top_k]]
    overlap = set(L_top) & set(S_top)
    print(f"\n--- top-{args.top_k} overlap: {len(overlap)} / {args.top_k}")
    print(f"  listed top-{args.top_k}: {L_top}")
    print(f"  sparse top-{args.top_k}: {S_top}")

    # 2. Per-structure asymmetry_ratio diff for shared structures
    common = sorted(set(L_by_id) & set(S_by_id))
    if not common:
        print("\nNO COMMON structures — universe may have changed!")
        return 0

    diffs: List[float] = []
    score_diffs: List[float] = []
    biggest: List[Dict[str, Any]] = []
    for sid in common:
        a_l = L_by_id[sid]["asymmetry_ratio"]
        a_s = S_by_id[sid]["asymmetry_ratio"]
        s_l = L_by_id[sid]["composite_score"]
        s_s = S_by_id[sid]["composite_score"]
        if a_l == a_l and a_s == a_s:  # both not NaN
            d = a_s - a_l
            diffs.append(d)
            biggest.append({"id": sid, "listed": a_l, "sparse": a_s, "delta": d})
        if s_l == s_l and s_s == s_s:
            score_diffs.append(s_s - s_l)

    biggest.sort(key=lambda r: abs(r["delta"]), reverse=True)
    if diffs:
        import statistics
        med = statistics.median(diffs)
        try:
            mean = statistics.mean(diffs)
            stdev = statistics.pstdev(diffs)
        except statistics.StatisticsError:
            mean = float("nan")
            stdev = float("nan")
        absmax = max(abs(d) for d in diffs)
        print(f"\n--- asymmetry_ratio diff (sparse - listed) over {len(diffs)} common structures")
        print(f"    median={med:+.4f}  mean={mean:+.4f}  stdev={stdev:.4f}  abs-max={absmax:.4f}")
        print("    biggest |delta|:")
        for row in biggest[:10]:
            print(f"      {row['id']:<40} listed={row['listed']:.4f} sparse={row['sparse']:.4f}"
                  f"  delta={row['delta']:+.4f}")
    if score_diffs:
        import statistics
        print(f"\n--- composite_score diff stats over {len(score_diffs)} common structures:"
              f" median={statistics.median(score_diffs):+.4f}"
              f"  abs-max={max(abs(d) for d in score_diffs):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
