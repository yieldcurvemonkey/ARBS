# %% [markdown]
# # Linear-vs-vol backtest grid — the league
#
# Every strategy family that trades the measured gap between the FF/ZQ
# lattice and the SR3 option surface, on 2 years of listed marks
# (2024-07 → 2026-07), lag-1, per-contract costs, both directions.
#
# Families: **A** bucket convergence (6.25bp boundary verticals, ZQ-basket
# hedged, resolution exits) · **B** modal 25bp butterfly (long fly = short
# dispersion) · **C** off-lattice tail verticals · **E** decomposed ICS
# residual (10:6 futures) · **P1/P2** placebos of family A (Gaussian tree /
# wrong calendar). Family D (cross-expiry conditional) excluded by design —
# its identification was measured at fit_L1 ≈ 0.35 in the triangle notebook;
# running configs on that signal is trial-count inflation.

# %%
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append("../../")
sys.path.append(".")

from BT.signals.deflated_sharpe import deflated_sharpe  # noqa: E402
from RVUtils.SFRRVLab.stats import verdict  # noqa: E402
from linvol_grid_common import pick_winner  # noqa: E402

DATA = Path("../data/linvol_grid")
league = pd.read_parquet(DATA / "league.parquet")
real = league[league["family"].isin(["A", "B", "C", "E"])].copy()
placebo = league[~league["family"].isin(["A", "B", "C", "E"])].copy()
print(f"league: {len(real)} real config rows + {len(placebo)} placebo rows")
print(f"rows with trades: {(real['n_trades'] > 0).sum()} real, "
      f"{(placebo['n_trades'] > 0).sum()} placebo")

# %% [markdown]
# ## The league — top of the table and per-family best

# %%
live = real[real["n_trades"] > 0].copy()
cols = ["family", "boundary", "dte", "gated", "thr", "direction", "n_trades",
        "hit", "total_gross_bp", "net_1x_bp", "net_2x_bp", "avg_net_1x_bp",
        "t_stat"]
top = live.sort_values("net_1x_bp", ascending=False).head(15)
print("=== top 15 by net @1x costs (raw — mind n_trades!) ===")
print(top[cols].round(2).to_string(index=False))
solid = live[live["n_trades"] >= 10]
print(f"\n=== rows clearing the n>=10 verdict floor: {len(solid)} ===")
if len(solid):
    print(solid.sort_values("net_1x_bp", ascending=False).head(10)[cols]
          .round(2).to_string(index=False))

print("\n=== best per family (net @1x) ===")
fam_best = live.loc[live.groupby("family")["net_1x_bp"].idxmax()]
print(fam_best[cols].round(2).to_string(index=False))

# %% [markdown]
# ## Sign tests — fade vs momentum must mirror for a real mechanism

# %%
def _mirror(df, a, b, label):
    da = df[df["direction"] == a]["net_1x_bp"]
    db = df[df["direction"] == b]["net_1x_bp"]
    if len(da) and len(db):
        print(f"  {label}: median {a} {da.median():+8.1f}  "
              f"median {b} {db.median():+8.1f}")

print("sign tests (median net@1x across the family's configs):")
_mirror(real[real.family == "A"], "fade", "momentum", "A  ")
_mirror(real[real.family == "B"], "short_disp", "long_disp", "B  ")
_mirror(real[real.family == "C"], "sell_tail", "buy_tail", "C  ")
_mirror(real[real.family == "E"], "fade", "momentum", "E  ")

# %% [markdown]
# ## Multiple-testing discipline — deflated Sharpe over the FULL trial count
#
# Units caveat: families report PnL in their own bp basis (probability-unit
# bp for A, premium bp for B/C, spread bp for E), so the pooled DSR is a
# rank-order screen, not a portfolio statement; per-family DSR is the
# binding one.

# %%
# DSR of each family's WINNER trade log (per-trade periods), deflated by the
# family's full config count; sweep variance from cross-config per-trade
# Sharpes (t / sqrt(n)). Fewer than 5 trades -> undefined, treated as 0 in
# the verdict (conservative: cannot certify ALIVE on a starved log).
def family_dsr(fam):
    n_total = int((real["family"] == fam).sum())
    g = live[live["family"] == fam]
    tl_path = DATA / f"trades_{fam}_best.parquet"
    if not tl_path.exists() or g.empty:
        return {"dsr_prob": np.nan, "n_trials": n_total}
    nets = pd.read_parquet(tl_path)["net_1x_bp"].astype(float).dropna()
    if len(nets) < 5:
        return {"dsr_prob": np.nan, "n_trials": n_total}
    sr_pp = (g["t_stat"] / np.sqrt(g["n_trades"].clip(lower=1))).dropna()
    var = float(sr_pp.var(ddof=1)) if len(sr_pp) > 2 else None
    out = deflated_sharpe(nets.to_numpy(), n_trials=n_total,
                          sr_variance=var, annualisation=1.0)
    out["n_trials"] = n_total
    return out


dsr_by_family = {}
for fam in sorted(live["family"].unique()):
    d = family_dsr(fam)
    dsr_by_family[fam] = d
    print(f"  {fam}: trials={d['n_trials']}  "
          f"dsr_prob={d['dsr_prob']:.3f}" if np.isfinite(d["dsr_prob"])
          else f"  {fam}: trials={d['n_trials']}  dsr_prob=n/a (winner log "
               "< 5 trades)")

# %% [markdown]
# ## Placebos — is the family-A edge lattice information?

# %%
a_best = live[live.family == "A"].sort_values("net_1x_bp").iloc[-1:] \
    if (live.family == "A").any() else pd.DataFrame()
for tag, name in (("P1_gauss", "P1 Gaussian tree (no lattice)"),
                  ("P2_calendar", "P2 wrong calendar")):
    p = placebo[placebo.family == tag]
    pl = p[p["n_trades"] > 0]
    b = pl["net_1x_bp"].max() if len(pl) else np.nan
    med = pl["net_1x_bp"].median() if len(pl) else np.nan
    print(f"{name}: best net1x {b:+.1f}bp  median {med:+.1f}bp  "
          f"live rows {len(pl)}/{len(p)}")
if len(a_best):
    print(f"family A real:  best net1x {a_best['net_1x_bp'].iloc[0]:+.1f}bp")
    print("\nRead: if the placebo best rivals the real best, the 'edge' is "
          "option mean-reversion / selection, not lattice information.")

# %% [markdown]
# ## Verdicts — the house taxonomy, per family best

# %%
rows = []
for fam, g in live.groupby("family"):
    b = pick_winner(g)                     # same row the trade log belongs to
    med = float(real[real["family"] == fam]["net_1x_bp"].fillna(0.0).median())
    dsr = dsr_by_family[fam]["dsr_prob"]
    dsr = float(dsr) if np.isfinite(dsr) else 0.0
    v = verdict(net_bp_at_taker=float(b["net_2x_bp"]),
                net_bp_at_maker=float(b["total_gross_bp"]),
                dsr_prob=dsr,
                median_net_bp=med, n_trades=int(b["n_trades"]))
    rows.append({"family": fam, "best_config": f"{b['boundary']}|{b['dte']}|"
                 f"thr{b['thr']}|{b['direction']}|gated={b['gated']}",
                 "n_trades": int(b["n_trades"]),
                 "gross_bp": round(float(b["total_gross_bp"]), 1),
                 "net_1x": round(float(b["net_1x_bp"]), 1),
                 "net_2x": round(float(b["net_2x_bp"]), 1),
                 "median_cfg_net": round(med, 1),
                 "dsr": round(float(dsr_by_family[fam]["dsr_prob"]), 3),
                 "verdict": v})
verdicts = pd.DataFrame(rows)
print(verdicts.to_string(index=False))
verdicts.to_csv(DATA / "verdicts.csv", index=False)

# %% [markdown]
# ## Chronological-half stability of the overall winner
#
# Underpowered by construction (episodic trades, one cycle) — reported as a
# stability check, not a validation.

# %%
if len(live):
    w = pick_winner(live)
    print(f"overall winner: {w['family']} {w['boundary']} {w['dte']} "
          f"thr{w['thr']} {w['direction']} gated={w['gated']} "
          f"-> {w['net_1x_bp']:+.1f}bp over {int(w['n_trades'])} trades")
    tl_path = DATA / f"trades_{w['family']}_best.parquet"
    if tl_path.exists():
        tl = pd.read_parquet(tl_path)
        tl["entry"] = pd.to_datetime(tl["entry"])
        mid = tl["entry"].min() + (tl["entry"].max() - tl["entry"].min()) / 2
        for name, seg in (("H1", tl[tl["entry"] <= mid]),
                          ("H2", tl[tl["entry"] > mid])):
            if len(seg):
                print(f"  {name}: {len(seg)} trades  "
                      f"net1x {seg['net_1x_bp'].sum():+.1f}bp  "
                      f"hit {(seg['net_1x_bp'] > 0).mean():.0%}")
            else:
                print(f"  {name}: 0 trades")
        print("(halves of the BEST row's own log — selection bias inside, "
              "stability signal only)")

league.to_parquet(DATA / "league.parquet", index=False)
print("\nleague persisted; verdicts.csv written")
