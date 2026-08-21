r"""Is workflow 4's P&L convexity, or is it duration?

The codebase's own rule: report ``sharpe_ex_mtm`` next to every headline Sharpe,
and know what the statistic is a statistic *of*. The factor attribution is the
only thing that answers the direction question — an earlier block learned that
the hard way, concluding "it is mostly direction" from an mtm-share and having
the PCA overturn it.

Regresses daily W4 P&L on the shared level / slope / curvature / convexity
basis, with Newey-West t-stats.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import RVUtils.ConvexityRV.factor_attribution as FA  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
sys.stdout.reconfigure(line_buffering=True)

cfg = FA.FactorConfig(start=pd.Timestamp("2020-06-01").date(),
                      end=pd.Timestamp("2026-08-20").date())
print("building rate panel ...")
rates = FA.build_rate_panel(cfg)
print(f"  {rates.shape}")

fm = FA.fit_factor_model(rates, cfg)
lab = FA.classify_pcs(fm.loadings, list(rates.columns))
print("\nPC labels (tested on the loadings, not assumed):")
print(lab.to_string())
print(f"explained: {np.round(fm.explained * 100, 2).tolist()}")

par = FA.parallel_move(fm)
X = pd.DataFrame({
    "level": fm.scores.iloc[:, 0],
    "slope": fm.scores.iloc[:, 1],
    "curvature": fm.scores.iloc[:, 2],
    "convexity": FA.convexity_from_parallel(par),
})

rows = []
for tag in ("base", "zero_cost"):
    f = DATA / f"rac_w4_equity_{tag}.parquet"
    if not f.exists():
        print(f"missing {f}")
        continue
    eq = pd.read_parquet(f)["equity"]
    eq.index = pd.to_datetime(eq.index)
    y = eq.diff().dropna()
    res = FA.attribute(y, X, name=f"w4_{tag}", level="daily", unit="usd")
    shares = getattr(res, "shares", None)
    tstats = getattr(res, "tstats", None)
    print(f"\n=== W4 {tag} — daily attribution ===")
    print(f"  R2 {getattr(res, 'r2', float('nan')):.4f}   n {getattr(res, 'n', len(y))}")
    if shares is not None:
        print("  share of realised P&L by factor:")
        print(pd.DataFrame({"share_%": (pd.Series(shares) * 100).round(1),
                            "t": pd.Series(tstats).round(2)}).to_string())
    rows.append({"tag": tag, "r2": getattr(res, "r2", None),
                 "shares": {k: float(v) for k, v in dict(shares or {}).items()},
                 "t": {k: float(v) for k, v in dict(tstats or {}).items()}})

(DATA / "rac_w4_attribution.json").write_text(json.dumps(rows, indent=1, default=str))
print(f"\nwrote {DATA / 'rac_w4_attribution.json'}")
