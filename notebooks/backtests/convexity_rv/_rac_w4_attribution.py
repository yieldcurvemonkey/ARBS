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
# `classify_pcs` must be given the tenors the model actually FIT, not every
# column of the panel. `build_rate_panel` also returns `extra_tenors` (1Y), so
# passing `rates.columns` hands the classifier 12 labels for 11 loadings and it
# reports a phantom sign flip -- which is how PC1 came back labelled "slope"
# when its loadings are 0.258-0.342, all positive, on 87.76 % of the variance.
lab = FA.classify_pcs(fm.loadings, list(fm.tenors))
print("\nPC labels (tested on the loadings, not assumed):")
print(lab.to_string())
ev = fm.explained_variance
print(f"explained variance: {(ev / ev.sum() * 100).round(2).to_dict()}")
print()
print("PC1 loadings by tenor (the label is a claim about THESE):")
print(fm.loadings.iloc[:, 0].round(4).to_string())

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
    shares, tstats = res.shares, res.tstats
    inc = res.incremental_r2
    print(f"\n=== W4 {tag} — daily attribution ===")
    print(f"  R2 {res.r2:.4f}  adj {res.r2_adj:.4f}   n {res.n_obs}   total {res.total_pnl:,.0f}")
    if shares is not None:
        print("  share of realised P&L by factor:")
        print(pd.DataFrame({"share_%": (pd.Series(shares) * 100).round(1),
                            "t": pd.Series(tstats).round(2),
                            "incr_R2": pd.Series(inc).round(4)}).to_string())
    # `shares or {}` on a Series raises: a Series has no truth value. Convert
    # explicitly rather than relying on falsiness.
    rows.append({"tag": tag, "r2": float(res.r2), "r2_adj": float(res.r2_adj),
                 "n_obs": int(res.n_obs), "total_pnl": float(res.total_pnl),
                 "shares": {str(k): float(v) for k, v in shares.items()},
                 "t": {str(k): float(v) for k, v in tstats.items()},
                 "incremental_r2": {str(k): float(v) for k, v in inc.items()}})

(DATA / "rac_w4_attribution.json").write_text(json.dumps(rows, indent=1, default=str))
print(f"\nwrote {DATA / 'rac_w4_attribution.json'}")
