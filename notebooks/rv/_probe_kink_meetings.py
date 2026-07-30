"""Probe: does the meeting-weight machinery line up with the built SR3 panel?

Prints the contract panel schema, then the calendar quantities for a handful of
front butterflies, so the units and the sign are visible before anything is
backtested. No network, no curve build -- parquet only.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"

pd.set_option("display.width", 220, "display.max_columns", 60)

c = pd.read_parquet(DATA / "contracts.parquet")
print("=== contracts.parquet ===", flush=True)
print(c.dtypes.to_string(), flush=True)
print(f"rows={len(c)}  dates={c['as_of'].min()} -> {c['as_of'].max()}  "
      f"codes={c['code'].nunique()}", flush=True)
print(c.head(4).to_string(), flush=True)

s3 = pd.read_parquet(DATA / "structures_3m.parquet")
print("\n=== structures_3m.parquet ===", flush=True)
print(list(s3.columns), flush=True)
print(f"rows={len(s3)}  keys={s3['key'].nunique()}", flush=True)
r = s3.iloc[0]
hand = (2 * r["leg1_value"] - r["leg0_value"] - r["leg2_value"]) * 100.0
print(f"sign check: value={r['value']:.6f}  hand(2b-f-k)*100={hand:.6f}  "
      f"match={np.isclose(r['value'], hand)}", flush=True)

sp = pd.read_parquet(DATA / "slot_panel.parquet")
print("\n=== slot_panel.parquet ===", flush=True)
print(f"index={sp.index[:2].tolist()} cols={list(sp.columns)[:20]}", flush=True)
print(sp.iloc[-1].head(8).to_string(), flush=True)

from RVUtils.MeanRev.meetings import (  # noqa: E402
    calendar_fly_panel, contract_weight_table, fomc_decisions, fomc_schedule,
    meeting_residual_panel,
)

sch = fomc_schedule(pd.Timestamp("2018-01-01").date(),
                    pd.Timestamp("2031-12-31").date())
print("\n=== FOMC schedule ===", flush=True)
print(sch.groupby(["year", "source"]).size().unstack(fill_value=0).to_string(),
      flush=True)

mtgs = fomc_decisions(pd.Timestamp("2017-01-01").date(),
                      pd.Timestamp(c["imm_end"].max()).date())
wt = contract_weight_table(c, mtgs)
print(f"\ncontract_weight_table: {wt.shape}  (codes x meetings)", flush=True)
row = wt.loc[wt.index[0]]
print(f"  {wt.index[0]}: nonzero-partial weights = "
      f"{[(str(k.date()), round(v, 3)) for k, v in row.items() if 0 < v < 1]}",
      flush=True)

cal = calendar_fly_panel(s3, c)
print("\n=== calendar_fly_panel (3m) ===", flush=True)
print(f"rows={len(cal)}", flush=True)
print(cal.head(6).to_string(index=False), flush=True)
chk = (cal["phi_sum"] - cal["mtg_fly"]).abs().max()
print(f"phi_sum vs mtg_fly max |diff| = {chk:.3e}  (must be ~0)", flush=True)

merged = s3[["as_of", "key", "cm_label_short", "value"]].merge(
    cal, on=["as_of", "key"], how="inner")
print("\ncalendar curvature by CM slot (phi_sum, bp per 1bp/meeting path):",
      flush=True)
g = merged.groupby("cm_label_short")["phi_sum"]
tab = pd.DataFrame({"mean": g.mean(), "sd": g.std(), "min": g.min(),
                    "max": g.max()})
slot = merged.groupby("cm_label_short")["cm_slot"].first() if "cm_slot" in merged else None
print(tab.round(3).to_string(), flush=True)

print("\ncorrelation of the RAW fly with the calendar curvature, per CM slot:",
      flush=True)
for lbl, gg in merged.groupby("cm_label_short"):
    if len(gg) < 100:
        continue
    print(f"  {lbl:>14s}  n={len(gg):5d}  corr={gg['value'].corr(gg['phi_sum']):+.3f}"
          f"  asym0%={100.0 * (gg['asym'] == 0).mean():5.1f}", flush=True)

sub = c[c["as_of"] >= pd.Timestamp("2022-01-03")]
resid, extras = meeting_residual_panel(sub, lam=10.0, max_slot=16,
                                       return_extras=True)
print(f"\n=== meeting_residual_panel  lam=10  shape={resid.shape} ===", flush=True)
print("residual sd (bp) by slot:", flush=True)
print(resid.std().round(3).to_string(), flush=True)
print(f"median meetings used per date: {extras['n_meetings'].median():.0f}",
      flush=True)
print(f"projected-jump share: median {extras['proj_share'].median():.3f}  "
      f"max {extras['proj_share'].max():.3f}", flush=True)
print("DONE", flush=True)
