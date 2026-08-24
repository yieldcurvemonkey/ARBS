r"""CA-vs-fly block: certify representative grid cells through the engine.

Panel dollars are arithmetic on spliced label series; engine dollars are daily
marks on real instruments (N futures legs + date-pinned matched swap +
date-pinned fly) held across whatever the market did, rolls included. The gap
between them is a MEASUREMENT this block reports, not an error to hide:

* between rolls the CA leg must track (the strat2 precedent certified at
  0.997–0.999 daily-change correlation);
* an episode that crosses an IMM roll holds its ORIGINAL contracts in the
  engine while the panel rolls at zero cost — those episodes are split out;
* the fly leg ages in the engine (the panel's is constant-maturity) — the
  drift that kept only 32–49% of panel dollars in the previous grid.

Cells certified: Citi's own structure (BLUES × spot 2s5s10s), the deep
matched-start book (GOLDS × 2s5s10s@5Y), and the grid's top-gross outright
(SFR20 × 1s2s3s@5Y). Engine trigger dates are the panel's FILL dates, so the
two books transact on the same marks.

Output: cavf_certification.json + per-cell engine equity parquets.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from RVUtils.ConvexityRV import cavf_engine as E  # noqa: E402
from RVUtils.ConvexityRV import cavf_signals as S  # noqa: E402
from RVUtils.ConvexityRV import cavf_universe as U  # noqa: E402
from RVUtils.ConvexityRV import strat2_fly_universe as FU  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CELLS = ("A|BLUES|2s5s10s|p", "A|GOLDS|2s5s10s@5Y|p", "A|SFR20|1s2s3s@5Y|p")

t0 = time.time()

ca_wide = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
ca_wide.index = pd.to_datetime(ca_wide.index)
cols = {c.split()[1]: c for c in ca_wide.columns}
ROLLS = S.imm_roll_dates(ca_wide.index)

legs = pd.read_parquet(DATA / "cavf_fly_legs.parquet")
wide = FU.legs_wide(legs)
wide.index = pd.to_datetime(wide.index)
FLIES = {f.fly_id: f for f in U.tradeable_fly_specs()}

eps = pd.read_parquet(DATA / "cavf_grid_episodes.parquet")

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

swaps_mdp = IRSwapsMDP(source="citivelo_excel_rl")
futures_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

report = {}
VARIANTS = [(c, True) for c in CELLS] + [(CELLS[0], False)]
for cell, with_fly in VARIANTS:
    label, fly_id = cell.split("|")[1], cell.split("|")[2]
    vname = cell if with_fly else f"{cell}__nofly"
    ca_raw = ca_wide[cols[label]].dropna()
    ca_spl = S.roll_splice(ca_raw, ROLLS)
    fly_series = FU.fly_rate_series(wide, FLIES[fly_id], 0.5, 0.5).dropna()
    idx = ca_spl.index

    cell_eps = eps[eps.cell_id == cell].reset_index(drop=True)
    if cell_eps.empty:
        report[vname] = {"n_episodes": 0, "note": "cell never traded"}
        print(f"{vname}: no episodes")
        continue

    specs, panel_by_tag = [], {}
    for _, r in cell_eps.iterrows():
        entry_fill = S.fill_date(idx, pd.Timestamp(r["entry"]), 1)
        exit_fill = S.fill_date(idx, pd.Timestamp(r["exit"]), 1) or idx[-1]
        if entry_fill is None or exit_fill <= entry_fill:
            continue
        beta = float(r["beta_entry"]) if with_fly else 0.0
        ep = S.Episode(pd.Timestamp(r["entry"]), pd.Timestamp(r["exit"]),
                       int(r["side"]), beta,
                       float(r["z_at_entry"]), str(r["exit_reason"]))
        spec = E.spec_from_episode(
            label=label, side=int(r["side"]), entry=entry_fill.date(),
            exit=exit_fill.date(), beta_entry=beta,
            fly=FLIES[fly_id] if with_fly else None)
        specs.append(spec)
        p = S.episode_pnl(ep, ca_spl, fly_series if with_fly else None,
                          U.CA_DV01_DEFAULT, exec_lag_bd=1)
        crosses = bool(len(ROLLS.intersection(
            pd.date_range(entry_fill, exit_fill))))
        panel_by_tag[spec.tag] = {"pnl": p, "crosses_roll": crosses,
                                  "entry": entry_fill, "exit": exit_fill}

    lo = min(s.entry for s in specs)
    hi = max(s.exit for s in specs)
    days = [d for d in idx if lo <= d.date() <= hi]
    print(f"{vname}: {len(specs)} episodes, grid {days[0].date()}..{days[-1].date()} "
          f"({len(days)} marks)")

    bt = E.run_backtest(specs, days, futures_mdp=futures_mdp,
                        swaps_mdp=swaps_mdp, name=vname, show_progress=False)
    eq = E.assert_ran(bt, specs, expect_days=len(days))
    eq.to_frame("equity").to_parquet(
        DATA / f"cavf_engine_{vname.replace('|', '_')}.parquet")

    panel_daily = pd.Series(0.0, index=pd.DatetimeIndex(days))
    for tag, d in panel_by_tag.items():
        panel_daily = panel_daily.add(d["pnl"], fill_value=0.0)
    eng_daily = eq.diff().reindex(panel_daily.index)

    both = pd.concat([eng_daily.rename("eng"), panel_daily.rename("panel")],
                     axis=1).dropna()
    active = both[(both["panel"] != 0.0) | (both["eng"].abs() > 1.0)]
    corr = float(active["eng"].corr(active["panel"])) if len(active) > 10 else np.nan

    # per-episode split: the roll-crossing episodes differ by construction
    # (engine holds the original contracts; the panel rolls at zero cost)
    per_ep = []
    for spec, d in zip(specs, panel_by_tag.values()):
        w = both.loc[d["entry"]:d["exit"]]
        w = w[(w["panel"] != 0.0) | (w["eng"].abs() > 1.0)]
        if len(w) < 3:
            continue
        per_ep.append({"crosses": d["crosses_roll"],
                       "corr": float(w["eng"].corr(w["panel"])),
                       "eng": float(w["eng"].sum()),
                       "panel": float(w["panel"].sum())})
    pe = pd.DataFrame(per_ep)
    clean = pe[~pe["crosses"]] if len(pe) else pe
    n_cross = sum(1 for d in panel_by_tag.values() if d["crosses_roll"])
    report[vname] = {
        "n_episodes": len(specs),
        "n_crossing_rolls": n_cross,
        "n_marks": len(days),
        "corr_daily": corr,
        "corr_daily_nonroll_median": (float(clean["corr"].median())
                                      if len(clean) else np.nan),
        "engine_terminal": float(eq.iloc[-1]),
        "panel_terminal": float(panel_daily.sum()),
        "active_days": int(len(active)),
        "seconds": round(time.time() - t0, 1),
    }
    print(f"  corr(daily) {corr:+.4f}  non-roll median per-episode corr "
          f"{report[vname]['corr_daily_nonroll_median']:+.4f}  "
          f"engine ${float(eq.iloc[-1]):,.0f} vs panel "
          f"${float(panel_daily.sum()):,.0f}  ({n_cross}/{len(specs)} cross a roll)")

(DATA / "cavf_certification.json").write_text(json.dumps(report, indent=1))
print(f"\nwrote cavf_certification.json  total {time.time() - t0:.0f}s")
