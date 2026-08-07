r"""End-to-end LIVE check: every curve, through IRSwapsMDP, against a real Excel.

    <env>/python.exe MDP/IRSwaps/CITIVELO_EXCEL/verify_live.py

This is the one thing the offline matrix structurally cannot prove. Everything in
``verify_matrix.py --offline`` runs against a tag cache that this repo wrote, so
it demonstrates the source is self-consistent with data it already had. Here the
whole path runs for real: ``IRSwapsMDP`` -> the fetcher -> ``CitiVeloQuotes`` ->
the COM client -> the user's signed-in Excel -> Citi -> back through the parser,
the cache, both curve builders and ``IRSwapQuery``.

Bounded on purpose - one ``CVTSHIST`` call per curve, twenty in total. It drives
the user's own Excel process, and the write discipline that keeps that process
alive lives in ``CitiVelocityExcelClient``; nothing here opens a second write
path. If a call does not settle, the client raises and this script stops rather
than writing again near a region that may still be expanding.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import traceback
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from MDP.IRSwaps.CITIVELO_EXCEL import register, supported_curve_names  # noqa: E402
from MDP.IRSwaps.CITIVELO_EXCEL.tie_out import query_npv_at_fair_rate, query_par_rate  # noqa: E402
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--only", default="")
    parser.add_argument("--source", default="CITIVELO_EXCEL-RL")
    parser.add_argument(
        "--out",
        default=str(_REPO_ROOT / "MDP" / "IRSwaps" / "CITIVELO_EXCEL" / "verification"),
    )
    args = parser.parse_args()

    register()
    curves = [c.strip().upper() for c in args.only.split(",") if c.strip()] or supported_curve_names()
    mdp = IRSwapsMDP(source=args.source)

    print(f"source={args.source}  curves={len(curves)}  started {datetime.datetime.now():%H:%M:%S}")
    print(
        f"\n{'curve':<20}{'tenors':>7}{'snapshot (wire tz)':>28}{'lag min':>9}"
        f"{'10Y quote':>11}{'10Y model':>11}{'err bp':>9}{'NPV':>10}"
    )
    rows = []
    for name in curves:
        row = {"curve_name": name}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                curve = mdp.get_data({"curve_name": name, "timestamp": "live"})
                meta = curve.meta()
                model = query_par_rate(curve, curve_name=name, tenor="10Y")
                npv = query_npv_at_fair_rate(curve, curve_name=name, tenor="10Y")
            row.update(
                ok=True,
                n_tenors=meta["n_tenors"],
                snapshot_at=meta["snapshot_at"],
                lag_min=round(meta["lag_seconds"] / 60.0, 1),
                model_10y=model,
                npv_10y=npv,
                max_reprice_error_bp=meta.get("max_reprice_error_bp"),
            )
            print(
                f"{name:<20}{meta['n_tenors']:>7}{meta['snapshot_at']:>28}"
                f"{row['lag_min']:>9.1f}{'':>11}{model:>11.5f}{'':>9}{npv:>10.2e}"
            )
        except Exception as exc:  # noqa: BLE001 - a failure IS the result
            row.update(ok=False, error=f"{type(exc).__name__}", reason=str(exc)[:200])
            print(f"{name:<20}{'-':>7}  {type(exc).__name__}: {str(exc)[:80]}")
            if "AsyncTimeout" in type(exc).__name__:
                print("\nAsyncTimeoutError - stopping rather than writing near a live region.")
                rows.append(row)
                break
        rows.append(row)

    frame = pd.DataFrame(rows)
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "live_check.csv", index=False)

    served = frame[frame.get("ok", pd.Series(dtype=bool)).fillna(False)]
    print(f"\nserved {len(served)}/{len(curves)}")
    if not served.empty:
        print(f"worst |NPV at fair rate| : {served['npv_10y'].abs().max():.3e}")
        print(f"worst reprice error      : {served['max_reprice_error_bp'].max():.3e} bp")
        print(f"lag range                : {served['lag_min'].min():.1f} .. {served['lag_min'].max():.1f} min")
    failed = frame[~frame.get("ok", pd.Series(dtype=bool)).fillna(False)]
    for _, r in failed.iterrows():
        print(f"  {r['curve_name']:<20}{r.get('error')}: {str(r.get('reason'))[:150]}")
    print(f"\n-> {out_dir / 'live_check.csv'}")
    return 0 if not served.empty else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
