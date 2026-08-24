r"""GV block: the last gap -- is the CA-only book real?

The grid's strongest family is ``none``: no hedge at all, median gross Sharpe
0.571 against 0.251 for the incumbent hedge, and the only family still positive
at 1x its own costs.  If there is an edge anywhere in this data it is there, so
it gets the same battery the hedged finalists got, plus one thing they did not
need:

**How many DISTINCT books are those 42 cells?**  A ``none`` cell has beta = 0,
so the leg is not in the position at all -- ``A|GREENS|immF_2s5s10s|none`` and
``A|GREENS|le_10y10y_15y10y|none`` are the SAME book with different labels.
Counting them as separate trials inflates the declared count and therefore the
null bar, which would flatter the verdict rather than the strategy.  It is
measured and reported for exactly that reason: the correction runs AGAINST the
conclusion this block reached, so it has to be on the record.

Then: always-short control, placebo ladder, sub-period split, carry share, and
an engine certification of the best one.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
from dataclasses import replace as _replace

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import gv_engine as GE  # noqa: E402
from RVUtils.ConvexityRV import gv_grid as GG  # noqa: E402
from RVUtils.ConvexityRV import gv_signals as GS  # noqa: E402
from RVUtils.ConvexityRV import gv_sizing as S  # noqa: E402
from RVUtils.ConvexityRV import gv_universe as U  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CA = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
LEGS = pd.read_parquet(DATA / "p2_legs.parquet")
LEGS.index = pd.to_datetime(LEGS.index)
IDX = CA.index.intersection(LEGS.index)
CA, LEGS = CA.loc[IDX], LEGS.loc[IDX]
SPAN_Y = (IDX[-1] - IDX[0]).days / 365.25
ALL = list(U.PRIMARY_STRUCTURES) + list(U.SECONDARY_STRUCTURES)
HL = S.fit_denoise_halflives(CA, [U.ca_col(l) for l in ALL])["halflife_bd"].to_dict()
SEGS = U.roll_segments(IDX)
CA_DV01 = U.CA_DV01_DEFAULT
ANN = 252.0

st = pd.read_parquet(DATA / "p2_grid_stats.parquet")
ep = pd.read_parquet(DATA / "p2_grid_episodes.parquet")
cells = {c.cell_id: c for c in GG.declared_cells()}


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


def sharpe(d) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0]) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(ANN))


# ---------------------------------------------------------------------------
sec("1. How many of the 298 declared cells are DISTINCT books?")
# ---------------------------------------------------------------------------
# Fingerprint each cell by its realised episode set: a book is the same book if
# it enters and exits on the same dates with the same side and the same beta.
fp = {}
for cid, g in ep.groupby("cell_id"):
    g = g.sort_values("entry")
    key = tuple(zip(g["entry"].astype("int64"), g["exit"].astype("int64"),
                    g["side"], np.round(g["beta"].astype(float), 10),
                    np.round(g["ca_dv01"].astype(float), 6)))
    fp.setdefault(key, []).append(cid)

n_with_eps = len(set(ep["cell_id"]))
n_distinct = len(fp)
dupe_groups = {k: v for k, v in fp.items() if len(v) > 1}
print(f"cells declared                 {len(cells)}")
print(f"cells that produced episodes   {n_with_eps}")
print(f"DISTINCT episode sets          {n_distinct}")
print(f"groups holding duplicates      {len(dupe_groups)}")
print(f"cells collapsed by duplication {n_with_eps - n_distinct}")

_none = st[st["sizing"] == "none"]
_none_ids = set(_none["cell_id"]) & set(ep["cell_id"])
_none_fp = {k: [c for c in v if c in _none_ids] for k, v in fp.items()}
_none_fp = {k: v for k, v in _none_fp.items() if v}
print(f"\nthe `none` family: {len(_none)} declared cells, "
      f"{len(_none_ids)} with episodes, {len(_none_fp)} DISTINCT books")
print("A `none` cell has beta = 0, so the leg is not in the position at all "
      "and every leg_id gives the same book. Its 42 cells are "
      f"{len(_none_fp)} distinct things: "
      f"{len(U.PRIMARY_STRUCTURES)} structures x {len(GG.BOOK_SCALES)} book scales.")

from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe  # noqa: E402

sc = st[st["n_episodes"] >= 5]
_neff = float(sc["n_eff"].median())
for _label, _n in (("as declared", len(cells)), ("distinct books", n_distinct)):
    print(f"  E[max SR | null, {_label:15s} = {_n:3d}]  per-hold "
          f"{expected_max_sharpe(_n, 1.0 / _neff):.4f}   annualised "
          f"{expected_max_sharpe(_n, 1.0 / SPAN_Y):.4f}")
print("\nThe correction LOWERS the bar, i.e. it runs against this block's own "
      "verdict, which is why it is reported rather than left implicit. It moves "
      "the annualised bar by under 0.01 and changes nothing.")

# ---------------------------------------------------------------------------
sec("2. The CA-only books, one row each")
# ---------------------------------------------------------------------------
rows = []
for cid in sorted(_none_ids):
    r = st[st["cell_id"] == cid].iloc[0]
    if any(cid == v[0] for v in _none_fp.values()):
        rows.append({"cell_id": cid, "structure": r["structure"],
                     "book_scale": r["book_scale"],
                     "n_episodes": r["n_episodes"], "hit_rate": r["hit_rate"],
                     "net_0": r["net_0.0"], "sharpe_0": r["sharpe_0.0"],
                     "net_1": r["net_1.0"], "sharpe_1": r["sharpe_1.0"],
                     "carry_usd": r["carry_usd"], "residual_usd": r["residual_usd"],
                     "breakeven_bp": r["breakeven_bp"]})
NONE = pd.DataFrame(rows).sort_values("sharpe_0", ascending=False)
print(NONE.round(3).to_string(index=False))
_bar12 = expected_max_sharpe(12, 1.0 / SPAN_Y)
_bar_all = expected_max_sharpe(n_distinct, 1.0 / SPAN_Y)
print(f"\nbest CA-only annualised Sharpe {NONE['sharpe_0'].max():.4f}")
print(f"  vs E[max SR | null] at 12 trials  {_bar12:.4f}  -> clears: "
      f"{bool(NONE['sharpe_0'].max() > _bar12)}")
print(f"  vs E[max SR | null] at {n_distinct} distinct {_bar_all:.4f}  -> clears: "
      f"{bool(NONE['sharpe_0'].max() > _bar_all)}")

# ---------------------------------------------------------------------------
sec("3. The same battery the hedged finalists got")
# ---------------------------------------------------------------------------
TOPN = list(NONE["cell_id"].head(3))


def hold_book(structure: str, side: int) -> pd.Series:
    ca = CA[U.ca_col(structure)].dropna()
    zero = pd.Series(0.0, index=ca.index)
    eps = [GS.Episode(a, b, side, 0.0, CA_DV01, 0.0, "hold", i)
           for i, (a, b) in enumerate(SEGS)]
    return GS.book_daily(eps, ca, zero, leg_id=None, index=ca.index)


rows = []
for cid in TOPN:
    sp = cells[cid]
    base = st[st["cell_id"] == cid].iloc[0]
    sh = hold_book(sp.structure, -1)
    lo = hold_book(sp.structure, +1)
    row = {"cell_id": cid, "cell_net": base["net_0.0"],
           "cell_sharpe": base["sharpe_0.0"],
           "always_short_net": float(sh.sum()),
           "always_short_sharpe": sharpe(sh),
           "always_long_net": float(lo.sum()),
           "signal_adds_usd": base["net_0.0"] - float(sh.sum())}
    for lag in (0, 10, 20, 40, 60):
        r = GG.run_cell(_replace(sp, cfg=GS.SignalConfig(
            **{**sp.cfg.__dict__, "signal_lag_bd": lag})), CA, LEGS,
            halflives=HL, ca_dv01=CA_DV01)
        row[f"sr_lag{lag}"] = sharpe(r.daily_by_mult[0.0])
    r0 = GG.run_cell(sp, CA, LEGS, halflives=HL, ca_dv01=CA_DV01)
    d = r0.daily_by_mult[0.0]
    cut = pd.Timestamp("2024-01-01")
    row["sharpe_early"] = sharpe(d.loc[:cut])
    row["sharpe_late"] = sharpe(d.loc[cut:])
    rows.append(row)
BAT = pd.DataFrame(rows)
print(BAT.round(3).to_string(index=False))
print("\nThe placebo ladder is the discriminating column: a timing signal must "
      "fall below the noise floor as the lag grows.")

# ---------------------------------------------------------------------------
sec("4. Engine certification of the best CA-only book")
# ---------------------------------------------------------------------------
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

fut_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
swp_mdp = IRSwapsMDP(source="citivelo_excel_rl")

cert = {}
for cid in TOPN[:2]:
    sp = cells[cid]
    sub = ep[ep["cell_id"] == cid].sort_values("entry")
    specs = [GE.spec_from_episode(structure=sp.structure, leg_id=None,
                                  side=int(r["side"]),
                                  entry=pd.Timestamp(r["entry"]).date(),
                                  exit=pd.Timestamp(r["exit"]).date(),
                                  beta_entry=0.0, ca_dv01=float(r["ca_dv01"]))
             for _, r in sub.iterrows()]
    lo_, hi_ = min(s.entry for s in specs), max(s.exit for s in specs)
    days = [d for d in IDX if lo_ <= d.date() <= hi_]
    try:
        bt = GE.run_backtest(specs, days, futures_mdp=fut_mdp, swaps_mdp=swp_mdp)
        eq = GE.assert_ran(bt, specs)
    except Exception as exc:                                    # noqa: BLE001
        print(f"{cid}: ENGINE {type(exc).__name__}: {exc}")
        cert[cid] = {"status": f"{type(exc).__name__}"}
        continue
    eng = eq.diff().fillna(0.0)
    ca = CA[U.ca_col(sp.structure)].dropna()
    zero = pd.Series(0.0, index=ca.index)
    eps = [GS.Episode(pd.Timestamp(r["entry"]), pd.Timestamp(r["exit"]),
                      int(r["side"]), 0.0, float(r["ca_dv01"]), 0.0, "cert")
           for _, r in sub.iterrows()]
    pan = GS.book_daily(eps, ca, zero, leg_id=None,
                        index=pd.DatetimeIndex(days), cost_mult=0.0)
    j = pd.concat([eng.rename("e"), pan.rename("p")], axis=1).dropna()
    cert[cid] = {"status": "ok", "n_specs": len(specs),
                 "engine_terminal": float(j["e"].sum()),
                 "panel_terminal": float(j["p"].sum()),
                 "terminal_gap_pct": 100.0 * (float(j["e"].sum())
                                              - float(j["p"].sum()))
                 / abs(float(j["p"].sum())) if j["p"].sum() else float("nan"),
                 "daily_change_corr": float(j["e"].corr(j["p"])),
                 "engine_sharpe": sharpe(j["e"]),
                 "panel_sharpe": sharpe(j["p"])}
    c = cert[cid]
    print(f"{cid}\n  engine {c['engine_terminal']:>13,.0f} (SR "
          f"{c['engine_sharpe']:+.3f})   panel {c['panel_terminal']:>13,.0f} "
          f"(SR {c['panel_sharpe']:+.3f})   gap {c['terminal_gap_pct']:+.1f}%   "
          f"daily corr {c['daily_change_corr']:+.4f}")

summary = {"n_declared": len(cells), "n_with_episodes": n_with_eps,
           "n_distinct_books": n_distinct,
           "none_declared": int(len(_none)), "none_distinct": len(_none_fp),
           "best_ca_only_sharpe": float(NONE["sharpe_0"].max()),
           "bar_ann_12": float(_bar12), "bar_ann_distinct": float(_bar_all),
           "certification": cert}
(DATA / "p2_ca_only.json").write_text(json.dumps(summary, indent=1))
NONE.to_parquet(DATA / "p2_ca_only_books.parquet")
BAT.to_parquet(DATA / "p2_ca_only_battery.parquet")
print("\n" + json.dumps({k: v for k, v in summary.items()
                         if k != "certification"}, indent=1))
