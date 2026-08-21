r"""Citi Figure 4 on SOFR: does dealer positioning explain the CA residual?

Citi, *Sell Eurodollar convexity in Blues*, Fig 4, monthly 2013-01..2017-12:

    d(Blues CA - model) on d(dealer positioning): y = 2e-06x - 0.1053, R2 = 0.2724

Reproduces the METHOD on USD SOFR 2021-2026. The published number is a EURODOLLAR
result on a different decade, so agreement in sign and order of magnitude is the
most that can be claimed, and disagreement is a finding rather than a bug.
"""
from __future__ import annotations

import datetime as dt
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

from RVUtils.ConvexityRV import ca_signals as S  # noqa: E402
from RVUtils.ConvexityRV.strat2_sofr_convexity import (  # noqa: E402
    Strat2Config, model_timeseries)

sys.stdout.reconfigure(line_buffering=True)
DATA = REPO / "notebooks" / "data" / "convexity_rv"

panel = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
panel = panel[panel["gate_ok"]]
print(f"gated CA panel: {len(panel):,} rows, {panel['date'].nunique():,} dates, "
      f"{panel['date'].min().date()} .. {panel['date'].max().date()}")
print("rows per colour:")
print(panel.groupby("colour")["date"].nunique().to_string())

# ranks 2..17, so Reds/Greens/Blues/Golds are all inside the fitted range.
# WHITES CANNOT BE MODELLED: Strat2Config enforces rank_start >= 2 because the
# 3m roll column needs a nearer pack to difference against, and rank 1 has none.
# That is structural, not a coverage gap, and Whites is reported as excluded
# rather than silently returning an empty series.
cfg_s2 = Strat2Config(start=dt.date(2021, 1, 1), end=dt.date(2026, 8, 20),
                      rank_start=2, n_packs=16, n_contracts=20)
model = model_timeseries(panel, cfg_s2)
print(f"\nmodel keys: {list(model)}")

cfg = S.EnrichmentConfig()
enr, prov = S.build_enrichment_panel(cfg)
print(f"\nenrichment panel {enr.shape}, columns {list(enr.columns)}")
for k, v in prov.items():
    print(f"  {k:18} {v}")

if "dealer_net" not in enr.columns:
    print("\nNO POSITIONING AVAILABLE -- stopping")
    raise SystemExit(0)

pos = enr["dealer_net"].dropna()
print(f"\ndealer_net: {len(pos):,} rows {pos.index.min().date()}..{pos.index.max().date()}"
      f"  range {pos.min():,.0f} .. {pos.max():,.0f}")

rows = []
for colour in ("Whites", "Reds", "Greens", "Blues", "Golds"):
    resid = S.residual_series(panel, cfg_s2, colour=colour, model=model)
    if resid.empty:
        print(f"{colour}: no residual series")
        continue
    resid = resid[(resid.index >= pd.Timestamp(cfg.start))
                  & (resid.index <= pd.Timestamp(cfg.end))]
    fit = S.positioning_regression(resid, pos, freq=cfg.regression_freq)
    rows.append({"colour": colour, "n_resid": len(resid), **fit.to_dict()})
    print(f"\n=== {colour} ===")
    print(f"  residual n={len(resid):,}  {resid.index.min().date()}..{resid.index.max().date()}"
          f"  mean {resid.mean():+.3f}bp sd {resid.std():.3f}")
    print(f"  monthly-change regression on d(dealer_net): n={fit.n}")
    print(f"    slope {fit.slope:+.3e} bp/contract   t {fit.tstat:+.2f}   "
          f"p {fit.pvalue:.4f}   R2 {fit.r2:.4f}")

c = S.CITI_FIG4_BLUES
print(f"\nCiti published (Eurodollars, {c['window'][0]}..{c['window'][1]}): "
      f"slope {c['slope']:.2e}, R2 {c['r2']:.4f}")
blues = [r for r in rows if r["colour"] == "Blues"]
if blues:
    b = blues[0]
    print(f"ours     (SOFR,        {b['window'][0]}..{b['window'][1]}): "
          f"slope {b['slope']:.2e}, R2 {b['r2']:.4f}")
    print(f"  sign agrees: {np.sign(b['slope']) == np.sign(c['slope'])}")

out = pd.DataFrame(rows)
out.to_csv(DATA / "ca_positioning_regression.csv", index=False)
(DATA / "ca_positioning_provenance.json").write_text(json.dumps(prov, indent=1))
print(f"\nwrote {DATA / 'ca_positioning_regression.csv'}")
