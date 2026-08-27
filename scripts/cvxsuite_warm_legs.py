"""Warm the CvxSuite leg-history panel (union of CurveFlyScreener legs + KINK_GRID).

Run:
    C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/cvxsuite_warm_legs.py

WHAT THIS IS: one TimeseriesBuilder warm of daily par rates for every leg the
suite composes from — the CurveFlyScreener universe (~71 legs) plus the kink
grid's additions (4y1y, 6y1y..9y1y, 12y3y, 25y5y, 30y10y, 40y10y). Window
2019-01-02..2026-08-25 EOD. Output: docs/cvxsuite/leg_history.parquet, wide,
bp, columns = lowercase leg labels ("10y10y") — the form the curve cache keys
on (case forks the cache symbol).

NETWORK: none permitted. The TB layer cannot forward ``offline`` to the curve
fetcher, so this script installs the Excel tripwire: any attempt to open the
Citi Velocity add-in raises immediately instead of silently going live. Store
misses on genuine business days are REPORTED and skipped, never fetched.
Supabase is disabled before any repo import.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import datetime
import time

import pandas as pd
import pytz

NY = pytz.timezone("America/New_York")
START = NY.localize(datetime.datetime(2019, 1, 2, 17, 0))
END = NY.localize(datetime.datetime(2026, 8, 25, 17, 0))
CURVE = "USD-SOFR-1D"
OUT = REPO / "docs" / "cvxsuite" / "leg_history.parquet"

# The kink grid's additions beyond the CurveFlyScreener universe.
KINK_EXTRA = [(4, 1), (6, 1), (7, 1), (8, 1), (9, 1), (12, 3), (25, 5), (30, 10), (40, 10)]


def install_excel_tripwire() -> None:
    """Any COM attach raises. The TB layer cannot pass offline; this can."""
    try:
        from MDP.CitiVelocityExcel import com_client
    except Exception:  # pragma: no cover - import surface may move
        return

    def _refuse(self, *a, **k):  # noqa: ANN001
        raise RuntimeError(
            "cvxsuite_warm_legs: Excel COM attach attempted — the warm must be "
            "served entirely from the curve store. A store miss on a business "
            "day is a warm gap, not a licence to go live."
        )

    com_client.CitiVelocityExcelClient.connect = _refuse  # type: ignore[assignment]


def main() -> int:
    install_excel_tripwire()

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from RVUtils.CurveFlyScreener.universe import leg_universe, leg_label
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    legs = {leg_label(l) for l in leg_universe()}
    for fwd, tenor in KINK_EXTRA:
        legs.add(f"{fwd:g}y{tenor:g}y" if fwd else f"{tenor:g}y")
    labels = sorted(legs)
    print(f"warming {len(labels)} legs {START.date()}..{END.date()}", flush=True)

    t0 = time.time()
    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    tb = TimeseriesBuilder()
    df = tb.get_timeseries(
        start=START,
        end=END,
        queries=[
            UnifiedQuery(curve=CURVE, tenor=t, value=UnifiedValue.IRS_RATE)
            for t in labels
        ],
        n_jobs=8,
        routers={"IRS": IRSwapsTB(mdp, show_tqdm=False)},
    )
    ren = {f"{CURVE} {t} OUTRIGHT RATE": t for t in labels}
    cols = [c for c in df.columns if c in ren]
    out = df[cols].rename(columns=ren) * 100.0  # percent -> bp
    out.index = pd.to_datetime(out.index)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT)
    cov = out.notna().mean().sort_values()
    print(f"done in {time.time() - t0:.0f}s -> {OUT}", flush=True)
    print(f"shape {out.shape}; coverage min {cov.iloc[0]:.1%} ({cov.index[0]}), "
          f"median {cov.median():.1%}", flush=True)
    thin = cov[cov < 0.8]
    if len(thin):
        print(f"THIN LEGS (<80%): {list(thin.index)}", flush=True)
    missing = [t for t in labels if t not in out.columns]
    if missing:
        print(f"MISSING COLUMNS: {missing}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
