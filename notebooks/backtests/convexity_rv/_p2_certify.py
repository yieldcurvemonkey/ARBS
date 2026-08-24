r"""GV block: engine certification of the finalists, plus the SFR12 adjudication.

Two jobs.

**1. Is SFR12's edge executable, or is it a mark?**  The grid's only cell that
clears its own annualised null bar is ``S|SFR12|immM_2s5s10s|beta_lvl``.  The
mark-noise model is structurally blind to its likely pathology: ``noise_fit``
detects i.i.d. (MA(1)) error only, so a curve-versus-futures dislocation that
PERSISTS for several days reads as a real level move while being a price nobody
could trade.  SFR12's measured AC1 of -0.056 therefore says "no i.i.d. noise",
not "clean".  Two independent witnesses:

  a. ``ca_diagnostics.flag_quality`` over the cell's own entry/exit dates;
  b. an end-to-end ``QueryDrivenBacktest`` on real contracts and an
     independently-marked swap curve.  If the engine does not reproduce the
     panel episodes, the grid's only survivor is a phantom.

**2. The pre-registration's finalist certification.**  Note, dated 2026-08-24:
the pre-registration says "top <=3 by DSR", which is unimplementable here --
``deflated_sharpe_of_best`` returns NaN at n<=12 observations and every cell has
8-12 episodes.  Finalists are therefore chosen by the STATED alternative
criteria and named explicitly rather than silently substituted:
  * the best cell by gross annualised Sharpe (SFR12 x immM_2s5s10s);
  * the cell that BEHAVES like a timing signal (GREENS x le_10y10y_15y10y --
    the only one whose P&L dies under a 60 bd placebo lag);
  * the sign-flip null's own best cell (GOLDS x imm2_2s5s10s x inv_vol), which
    carried a family-wise p of 0.0225 and was never in the Sharpe-ranked top 8,
    so it never faced the always-short control or the placebo ladder.
"""
from __future__ import annotations

import json
import math
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

st = pd.read_parquet(DATA / "p2_grid_stats.parquet")
ep = pd.read_parquet(DATA / "p2_grid_episodes.parquet")
cells = {c.cell_id: c for c in GG.declared_cells()}

FINALISTS = [
    "S|SFR12|immM_2s5s10s|beta_lvl|const_dv01",
    "A|GREENS|le_10y10y_15y10y|beta_chg|const_dv01",
    "A|GOLDS|imm2_2s5s10s|beta_lvl|inv_vol",
]


def sec(t: str) -> None:
    print(f"\n{'=' * 80}\n{t}\n{'=' * 80}")


def sharpe(d: pd.Series) -> float:
    d = pd.Series(d).astype(float)
    if len(d[d != 0]) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(252.0))


# ---------------------------------------------------------------------------
sec("1. SFR12 mark quality on its own trading dates")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV.ca_diagnostics import flag_quality  # noqa: E402

rows = []
for lab in ("SFR12", "SFR16", "SFR20", "GREENS", "BLUES", "GOLDS"):
    ca = CA[U.ca_col(lab)].dropna()
    w = U.time_weight_series(ca.index, lab)
    t1 = U.mean_t1_series(ca.index, lab)
    df = pd.DataFrame({"ca_bp": ca, "implied_vol_bp": S.ca_implied_vol_bp(ca, w),
                       "t1_first": t1})
    q = flag_quality(df, syn_col=None)
    rows.append({"structure": lab, "n": len(q),
                 "frac_negative_ca": float(q["flag_negative_ca"].mean()),
                 "frac_implausible_vol": float(q["flag_implausible_vol"].mean()),
                 "frac_ok": float(q["ok"].mean())})
qual = pd.DataFrame(rows).set_index("structure")
print(qual.round(4).to_string())

print("\nquality on the FINALIST cells' own entry/exit dates:")
for cid in FINALISTS:
    sp = cells[cid]
    lab = sp.structure
    ca = CA[U.ca_col(lab)].dropna()
    w = U.time_weight_series(ca.index, lab)
    t1 = U.mean_t1_series(ca.index, lab)
    q = flag_quality(pd.DataFrame({"ca_bp": ca,
                                   "implied_vol_bp": S.ca_implied_vol_bp(ca, w),
                                   "t1_first": t1}), syn_col=None)
    sub = ep[ep["cell_id"] == cid]
    dts = pd.DatetimeIndex(sorted(set(sub["entry"]) | set(sub["exit"])))
    dts = dts.intersection(q.index)
    print(f"  {cid:48s} n_dates={len(dts):3d}  frac_ok={q.loc[dts, 'ok'].mean():.3f}")

# a witness the i.i.d. noise model cannot see: multi-day persistence of the
# CA's deviation from its own EWMA -- a dislocation that snaps back over days.
print("\nPERSISTENT dislocation (what an MA(1) noise model is blind to):")
for lab in ("SFR12", "SFR16", "GREENS", "BLUES", "GOLDS"):
    ca = CA[U.ca_col(lab)].dropna()
    dev = ca - S.denoise(ca, 10.0)
    print(f"  {lab:7s} sd(dev from 10d EWMA) {dev.std(ddof=1):6.3f} bp   "
          f"AC1(dev) {dev.autocorr(1):+.3f}   AC5(dev) {dev.autocorr(5):+.3f}   "
          f"frac |dev|>2bp {float((dev.abs() > 2).mean()):.3f}")

# ---------------------------------------------------------------------------
sec("2. Engine certification of the finalists")
# ---------------------------------------------------------------------------
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

fut_mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
swp_mdp = IRSwapsMDP(source="citivelo_excel_rl")

cert = {}
for cid in FINALISTS:
    sp = cells[cid]
    sub = ep[ep["cell_id"] == cid].sort_values("entry")
    if sub.empty:
        print(f"{cid}: no episodes, nothing to certify")
        continue
    ca = CA[U.ca_col(sp.structure)].dropna()
    leg = U.leg_series(LEGS, sp.leg_id, sp.structure).reindex(ca.index)

    specs = []
    for _, r in sub.iterrows():
        specs.append(GE.spec_from_episode(
            structure=sp.structure, leg_id=sp.leg_id, side=int(r["side"]),
            entry=pd.Timestamp(r["entry"]).date(),
            exit=pd.Timestamp(r["exit"]).date(),
            beta_entry=float(r["beta"]), ca_dv01=float(r["ca_dv01"])))
    lo = min(s.entry for s in specs)
    hi = max(s.exit for s in specs)
    days = [d for d in IDX if lo <= d.date() <= hi]
    print(f"\n{cid}\n  {len(specs)} episodes, {len(days)} marks "
          f"{lo}..{hi}, legs/episode = {len(specs[0].symbols)}+1"
          f"{'+1' if specs[0].leg else ''}")
    t0 = time.time()
    try:
        bt = GE.run_backtest(specs, days, futures_mdp=fut_mdp, swaps_mdp=swp_mdp)
        eq = GE.assert_ran(bt, specs)
    except AssertionError as exc:
        print(f"  ENGINE FAILED: {exc}")
        cert[cid] = {"status": "failed", "error": str(exc)}
        continue
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ENGINE ERROR: {type(exc).__name__}: {exc}")
        cert[cid] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        continue
    eng = eq.diff().fillna(0.0)

    eps = [GS.Episode(pd.Timestamp(r["entry"]), pd.Timestamp(r["exit"]),
                      int(r["side"]), float(r["beta"]), float(r["ca_dv01"]),
                      0.0, "cert") for _, r in sub.iterrows()]
    pan = GS.book_daily(eps, ca, leg, leg_id=sp.leg_id,
                        index=pd.DatetimeIndex(days), cost_mult=0.0)
    j = pd.concat([eng.rename("engine"), pan.rename("panel")], axis=1).dropna()
    corr = float(j["engine"].corr(j["panel"]))
    gap = (float(j["engine"].sum()) - float(j["panel"].sum()))
    cert[cid] = {
        "status": "ok", "n_specs": len(specs), "n_marks": len(days),
        "engine_terminal": float(j["engine"].sum()),
        "panel_terminal": float(j["panel"].sum()),
        "terminal_gap_usd": gap,
        "terminal_gap_pct": (100.0 * gap / abs(float(j["panel"].sum()))
                             if j["panel"].sum() else float("nan")),
        "daily_change_corr": corr,
        "engine_sharpe": sharpe(j["engine"]), "panel_sharpe": sharpe(j["panel"]),
        "elapsed_s": round(time.time() - t0, 1),
    }
    print(f"  engine terminal {cert[cid]['engine_terminal']:>15,.0f}   "
          f"panel {cert[cid]['panel_terminal']:>15,.0f}   "
          f"gap {cert[cid]['terminal_gap_pct']:+7.1f}%")
    print(f"  daily-change corr {corr:+.4f}   engine Sharpe "
          f"{cert[cid]['engine_sharpe']:.3f} vs panel "
          f"{cert[cid]['panel_sharpe']:.3f}   ({cert[cid]['elapsed_s']}s)")

(DATA / "p2_certification.json").write_text(json.dumps(cert, indent=1))

# ---------------------------------------------------------------------------
sec("3. The sign-flip null's own best cell, through the full battery")
# ---------------------------------------------------------------------------
cid = "A|GOLDS|imm2_2s5s10s|beta_lvl|inv_vol"
sp = cells[cid]
base = st[st["cell_id"] == cid].iloc[0]
g = ep[ep["cell_id"] == cid]
print(f"{cid}\n  n_episodes {int(base['n_episodes'])}  net {base['net_0.0']:,.0f}  "
      f"ann Sharpe {base['sharpe_0.0']:.3f}  per-episode SR "
      f"{g['pnl_usd'].mean() / g['pnl_usd'].std(ddof=1):.3f}")
segs = U.roll_segments(IDX)
ca = CA[U.ca_col(sp.structure)].dropna()
leg = U.leg_series(LEGS, sp.leg_id, sp.structure).reindex(ca.index)
b = float(base["mean_abs_beta"]) if np.isfinite(base["mean_abs_beta"]) else 0.0
for side, name in ((-1, "always-short"), (1, "always-long")):
    eps = [GS.Episode(a, bb, side, b, U.CA_DV01_DEFAULT, 0.0, "hold", i)
           for i, (a, bb) in enumerate(segs)]
    d = GS.book_daily(eps, ca, leg, leg_id=sp.leg_id, index=ca.index)
    print(f"  {name:13s} net {float(d.sum()):>15,.0f}  Sharpe {sharpe(d):+.3f}")
from dataclasses import replace as _replace  # noqa: E402
for lag in (0, 20, 60):
    r = GG.run_cell(_replace(sp, cfg=GS.SignalConfig(
        **{**sp.cfg.__dict__, "signal_lag_bd": lag})), CA, LEGS, halflives=HL)
    d = r.daily_by_mult[0.0]
    print(f"  placebo lag {lag:2d} bd  net {float(d.sum()):>15,.0f}  "
          f"Sharpe {sharpe(d):+.3f}  n_ep {r.n_episodes}")

# ---------------------------------------------------------------------------
sec("4. Declared sensitivity: z_entry 1.5 on the finalists (winner-only)")
# ---------------------------------------------------------------------------
rows = []
for cid in FINALISTS:
    sp = cells[cid]
    for z in (1.5, 2.0, 2.5):
        r = GG.run_cell(_replace(sp, cfg=GS.SignalConfig(
            **{**sp.cfg.__dict__, "z_entry": z})), CA, LEGS, halflives=HL)
        s0 = GG.grid_stats_frame([r], span_years=SPAN_Y).iloc[0]
        rows.append({"cell_id": cid, "z_entry": z,
                     "n_episodes": s0["n_episodes"], "net_0": s0["net_0.0"],
                     "sharpe_0": s0["sharpe_0.0"], "net_1": s0["net_1.0"],
                     "sharpe_1": s0["sharpe_1.0"]})
zs = pd.DataFrame(rows)
print(zs.round(3).to_string(index=False))
zs.to_parquet(DATA / "p2_certify_zsens.parquet")

# ---------------------------------------------------------------------------
sec("5. Declared overlays C and D on the finalists (positioning, CCP basis)")
# ---------------------------------------------------------------------------
try:
    from RVUtils.ConvexityRV.ca_signals import build_positioning_panel
    pos = build_positioning_panel()
    print(f"positioning panel {pos.shape}, {pos.index.min()}..{pos.index.max()}")
    print(pos.tail(3).round(1).to_string())
except Exception as exc:                                        # noqa: BLE001
    pos = None
    print(f"positioning unavailable: {type(exc).__name__}: {exc}")
try:
    from RVUtils.ConvexityRV.ca_signals import ccp_basis_panel
    bas = ccp_basis_panel()
    print(f"\nCCP basis panel {bas.shape}, {bas.index.min()}..{bas.index.max()}")
except Exception as exc:                                        # noqa: BLE001
    bas = None
    print(f"CCP basis unavailable: {type(exc).__name__}: {exc}")

if pos is not None:
    col = next((c for c in pos.columns if "dealer" in c.lower()), None)
    if col:
        dz = ((pos[col] - pos[col].rolling(104, min_periods=52).mean())
              / pos[col].rolling(104, min_periods=52).std(ddof=1))
        rows = []
        for cid in FINALISTS:
            sub = ep[ep["cell_id"] == cid]
            if sub.empty:
                continue
            keep = []
            for _, r in sub.iterrows():
                v = dz.dropna().asof(pd.Timestamp(r["entry"]))
                if not np.isfinite(v):
                    continue
                ok = (v >= 1.0) if r["side"] < 0 else (v <= -1.0)
                keep.append((ok, r["pnl_usd"]))
            if not keep:
                continue
            k = pd.DataFrame(keep, columns=["ok", "pnl"])
            rows.append({"cell_id": cid, "n": len(k),
                         "n_pass": int(k["ok"].sum()),
                         "pnl_all": float(k["pnl"].sum()),
                         "pnl_conditioned": float(k.loc[k["ok"], "pnl"].sum())})
        if rows:
            print("\nCiti's positioning mechanism as a conditioning overlay "
                  "(dealer net z >= +1 for short-CA, <= -1 for long-CA):")
            print(pd.DataFrame(rows).round(1).to_string(index=False))

print("\nwrote", DATA / "p2_certification.json")
