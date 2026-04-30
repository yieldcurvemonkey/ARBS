"""Benchmark sparse vs listed SABR smile fetch on a single uncached as_of.

Times one ``fetch_sabr_smile`` call per contract for a 12-contract SR3 universe
under two strike-fan-out modes:

* ``listed`` — current screener default (full ATM ladder, ~30-50 strikes/contract).
* ``delta_sparse`` — default delta-mode grid (5/10/.../50-delta C+P,
  ~20 strikes/contract).

Captures wall time per contract, total HTTP request count, and (best-effort)
HTTP 429 count from BarchartFetcher's per-symbol status map. Prints a side-by-side
report so the operator can decide whether the sparse path is worth shipping.

Usage::

    conda run -n stir python scripts/_bench_smile_fetch.py \\
        --as-of 2026-04-23 --symbols SR3M26 SR3U26 SR3Z26
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bench_smile")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _imm_cutoff, _next_contracts  # noqa: E402
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP  # noqa: E402


def _resolve_universe(as_of: datetime.date, count: int) -> List[str]:
    return list(_next_contracts(
        as_of, prefix="SR3", count=count,
        valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff,
    ))


def _fetch_one_smile(mdp: STIRFutureOptionMDP, *, sr3_symbol: str,
                     as_of: datetime.date, mode: str, force_refresh: bool) -> Dict[str, Any]:
    """Time a single fetch_sabr_smile call. Mode is 'listed' or 'delta_sparse'."""
    request: Dict[str, Any] = {
        "symbol": sr3_symbol.replace("SR3", "SFR", 1),
        "as_of": as_of,
        "force_refresh": force_refresh,
    }
    if mode == "listed":
        request["strike_offsets_bps"] = "listed"
    elif mode == "delta_sparse":
        # Omitting both strike_offsets_bps and deltas selects the default
        # delta grid: [5, 10, 15, 20, 25, 30, 35, 40, 45, 50] -> 20 strikes.
        pass
    else:
        raise ValueError(f"unknown mode: {mode}")

    t0 = time.monotonic()
    err: Any = None
    n_legs = 0
    try:
        smile = mdp.fetch_sabr_smile(request)
        n_legs = len(getattr(smile, "vol_legs", []) or [])
    except Exception as exc:  # noqa: BLE001
        err = repr(exc)
    elapsed = time.monotonic() - t0
    return {
        "symbol": sr3_symbol,
        "mode": mode,
        "elapsed_s": round(elapsed, 2),
        "n_legs": n_legs,
        "error": err,
    }


def _summarize_history_status(mdp: STIRFutureOptionMDP) -> Dict[str, int]:
    """Best-effort tally of HTTP requests + 429 hits from BarchartFetcher state."""
    out = {"requests": 0, "saw_429": 0}
    bcf = getattr(mdp, "_barchart_fetcher_singleton", None) or getattr(mdp, "_barchart_fetcher", None)
    if bcf is None:
        return out
    try:
        statuses = bcf.get_history_statuses() if hasattr(bcf, "get_history_statuses") else {}
    except Exception:  # noqa: BLE001
        statuses = {}
    for _, st in (statuses or {}).items():
        out["requests"] += 1
        if st.get("saw_429"):
            out["saw_429"] += 1
    return out


def _bench_mode(mdp: STIRFutureOptionMDP, *, sr3_symbols: Sequence[str],
                as_of: datetime.date, mode: str, force_refresh: bool) -> Dict[str, Any]:
    logger.info("---- mode=%s | as_of=%s | %d contracts (force_refresh=%s) ----",
                mode, as_of, len(sr3_symbols), force_refresh)
    rows: List[Dict[str, Any]] = []
    t0 = time.monotonic()
    for sr3 in sr3_symbols:
        row = _fetch_one_smile(mdp, sr3_symbol=sr3, as_of=as_of, mode=mode,
                               force_refresh=force_refresh)
        logger.info("  %s | %s | %.1fs | n_legs=%d | err=%s",
                    row["symbol"], row["mode"], row["elapsed_s"], row["n_legs"], row["error"])
        rows.append(row)
    total = time.monotonic() - t0
    status = _summarize_history_status(mdp)
    n_ok = sum(1 for r in rows if not r["error"])
    n_fail = len(rows) - n_ok
    return {
        "mode": mode,
        "n_contracts": len(sr3_symbols),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "total_s": round(total, 1),
        "avg_per_contract_s": round(total / max(len(sr3_symbols), 1), 1),
        "n_http_requests": status["requests"],
        "n_http_429": status["saw_429"],
        "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True, help="ISO as_of date")
    p.add_argument("--symbols", nargs="*", default=None,
                   help="Optional explicit SR3 symbols. Defaults to first N from the SR3 strip.")
    p.add_argument("--n-contracts", type=int, default=12,
                   help="Number of contracts when --symbols is omitted")
    p.add_argument("--mode", choices=("listed", "delta_sparse", "both"), default="both")
    p.add_argument("--force-refresh", action="store_true",
                   help="Bypass on-disk smile cache (ensures actual HTTP fan-out)")
    p.add_argument("--source", default="BARCHART_STIRFO-QL")
    args = p.parse_args()

    as_of = datetime.date.fromisoformat(args.as_of)
    if args.symbols:
        sr3_symbols = list(args.symbols)
    else:
        sr3_symbols = _resolve_universe(as_of, args.n_contracts)

    logger.info("benchmark | as_of=%s | source=%s | symbols=%s",
                as_of, args.source, sr3_symbols)
    results: List[Dict[str, Any]] = []
    if args.mode in ("listed", "both"):
        mdp_listed = STIRFutureOptionMDP(source=args.source)
        results.append(_bench_mode(mdp_listed, sr3_symbols=sr3_symbols, as_of=as_of,
                                   mode="listed", force_refresh=args.force_refresh))
    if args.mode in ("delta_sparse", "both"):
        mdp_sparse = STIRFutureOptionMDP(source=args.source)
        results.append(_bench_mode(mdp_sparse, sr3_symbols=sr3_symbols, as_of=as_of,
                                   mode="delta_sparse", force_refresh=args.force_refresh))

    print("\n=========== SMILE FETCH BENCHMARK ===========")
    print(f"as_of={as_of}  contracts={len(sr3_symbols)}")
    print(f"{'mode':>14} {'total_s':>10} {'avg/c':>8} {'ok':>4} {'fail':>5} {'requests':>10} {'429':>6}")
    for r in results:
        print(f"{r['mode']:>14} {r['total_s']:>10.1f} {r['avg_per_contract_s']:>8.1f} "
              f"{r['n_ok']:>4} {r['n_fail']:>5} {r['n_http_requests']:>10} {r['n_http_429']:>6}")
    if len(results) == 2:
        listed = results[0] if results[0]["mode"] == "listed" else results[1]
        sparse = results[0] if results[0]["mode"] == "delta_sparse" else results[1]
        if sparse["total_s"] > 0:
            speedup = listed["total_s"] / max(sparse["total_s"], 0.1)
            print(f"\nspeedup (listed_total / sparse_total): {speedup:.2f}x")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
