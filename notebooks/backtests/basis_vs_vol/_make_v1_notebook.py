"""Build the configurable V1 (option-adjusted basis) backtest notebook.

Raw-JSON builder, same convention as `_make_bvv_notebook.py` and the intraday_fed_hawk_dove
config notebooks. Edit THIS file, never the .ipynb.
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "basis_v1_configurable_backtest.ipynb"
REPO = r"C:\Users\chris\clee\ARBS-bvv"

_n = 0


def md(src):
    global _n
    _n += 1
    return {"cell_type": "markdown", "id": f"md{_n:02d}", "metadata": {}, "source": src.splitlines(True)}


def code(src):
    global _n
    _n += 1
    return {"cell_type": "code", "id": f"cd{_n:02d}", "metadata": {}, "execution_count": None,
            "outputs": [], "source": src.splitlines(True)}


cells = []

cells.append(md(r"""# V1 — the option-adjusted Treasury futures basis

    OABNOC = BNOC_market  -  (switch option + wildcard option)

Buy the basis when the market pays less than the delivery option is worth; sell when it pays more.
This is the trade the dealer literature recommends directly — BofA's *"buy futures basis = cheap
options"* is a long-OABNOC position.

**P&L is exactly the change in net basis.** Long basis = long the CTD, short CF futures, financed.
Daily P&L per 100 face = `d(P_cash) − CF·d(F) + coupon − repo` = `d(gross basis) + one day's carry`
= **`d(net basis)`**. Carry is already inside the net basis, so a daily mark needs nothing else.
One 32nd on $1mm face is $312.50.

---

## What this backtest is, and what bounds it

* **Sample: daily mark-to-market** over whatever survives the consistency gate, front contract rolled 7 days before first notice.
  The panel is built by the repo's own basket machinery (`USTFuturesMDP.get_basis_report`) — CME
  conversion factors, FedInvest cash marks, Barchart futures settles.
* **Financing is the swaps/OIS term rate to each contract's own delivery date**, not an overnight
  fixing. Validated to ~1bp against J.P. Morgan's published term repo.
* **The delivery option is modelled with both components** — the two-bond switch *and* the wildcard.
  The design originally had only the switch, which the literature says is the sub-dominant one.
* **A roll is never a return** and neither is a data gap; both re-anchor the mark and claim nothing.

**Known weaknesses, stated up front.** The switch model is two-bond, so it under-prices a diffuse
basket (ZB has had seven live deliverables). Switch and wildcard are *added*, but they compete for
the same delivery decision, so the sum overstates. Post-close vol for the wildcard is a borrowed
constant (1bp/2hr), not measured. And the cash and futures marks come from different sources, so
day-to-day net basis carries a stitching noise that no model explains.
"""))

cells.append(md("## 0. Setup"))
cells.append(code(f'''%load_ext autoreload
%autoreload 2
import sys, json, pathlib, warnings
REPO = r"{REPO}"
if REPO not in sys.path: sys.path.insert(0, REPO)
warnings.filterwarnings("ignore")

import numpy as np, pandas as pd, matplotlib.pyplot as plt
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 60)
plt.rcParams.update({{"figure.figsize": (11, 4), "axes.grid": True, "grid.alpha": .25,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 10}})

from RVUtils.BasisVsVol import v1 as V1, analytics as A
from RVUtils.BasisVsVol.wildcard import wildcard_value
from RVUtils.BasisVsVol.switch import Deliverable, delivery_option_two_bond

DATA = pathlib.Path(REPO) / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
RESULTS = pathlib.Path(REPO) / "notebooks" / "backtests" / "basis_vs_vol" / "_results"

def load_panel(root, gate=True):
    """Load a panel and apply the internal-consistency gate.

    The futures price is pinned to the cheapest CF-adjusted forward, so the smallest gross basis in
    the basket must be small. Where it is not, the cash and futures feeds disagree about the same
    day and nothing computed from them is a net basis. Measured: 2024 gives ~0-5/32 and 2019 ~14/32,
    but early 2015 gives 135-509/32 across the WHOLE basket -- a feed break, not a market.
    """
    p = pd.read_parquet(DATA / f"basis_panel_{{root}}.parquet")
    if gate and "data_ok" in p:
        n0 = len(p)
        p = p[p["data_ok"]].reset_index(drop=True)
        if n0 != len(p):
            print(f"  {{root}}: consistency gate dropped {{n0-len(p)}} of {{n0}} days")
    return p

PANELS = {{r: load_panel(r) for r in ("ZB", "ZN", "UB") if (DATA / f"basis_panel_{{r}}.parquet").exists()}}
for r, p in PANELS.items():
    print(f"{{r}}: {{len(p):5d}} days  {{p['date'].min().date()}} -> {{p['date'].max().date()}}  "
          f"contracts={{p['symbol'].nunique()}}  median BNOC {{p['ctd_bnoc32'].median():+.2f}}/32")'''))

cells.append(md("""## 1. CONFIG"""))
cells.append(code('''CONFIG = dict(
    root            = "ZB",     # ZB (classic bond) | ZN (10y) | UB (ultra bond)
    # ---- delivery-option model ------------------------------------------
    switch_vol_bp   = 70.0,     # annualised bp vol of the forward yield (switch)
    sigma_yield_bp  = 1.0,      # post-close bp/2hr (wildcard); JPM house assumption
    wildcard_days   = 14,       # delivery days on which the wildcard is live
    use_switch      = True,
    use_wildcard    = True,
    # ---- signal ---------------------------------------------------------
    z_window        = 126,
    entry_z         = 1.5,
    exit_z          = 0.5,
    exec_lag_days   = 1,
    max_hold_days   = 21,
    max_gap_days    = 5,
    # ---- sizing / costs -------------------------------------------------
    face_mm         = 100.0,    # $mm of CTD face
    cost_32nds      = 0.5,      # round trip on the cash+futures package
    cost_mult       = 1.0,
)
CFG = V1.V1Config(**CONFIG)
RES = V1.run_v1(PANELS[CFG.root], CFG)
print(CFG.key()); print(json.dumps(RES.diagnostics, indent=1, default=str))'''))

cells.append(md("""## 2. The delivery option the model is charging for

Both components, over the whole sample. The wildcard is a `1/CF − 1` phenomenon so it is largest in
the low-conversion-factor Ultra contract; the switch depends on where yields sit relative to the 6%
notional coupon."""))
cells.append(code('''p = RES.panel
fig, ax = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
ax[0].plot(p["date"], p["ctd_bnoc32"], lw=.8, label="market BNOC")
ax[0].plot(p["date"], p["dov32"], lw=1.2, label="model delivery option")
ax[0].legend(); ax[0].set_ylabel("32nds"); ax[0].set_title(f"{CFG.root}: net basis vs modelled option")
ax[1].plot(p["date"], p["switch32"], lw=.9, label="switch")
ax[1].plot(p["date"], p["wildcard32"], lw=.9, label="wildcard")
ax[1].legend(); ax[1].set_ylabel("32nds"); plt.tight_layout(); plt.show()

display(p[["ctd_bnoc32","switch32","wildcard32","dov32","oabnoc32","repo_pct"]]
        .describe().T.round(3))
print("wildcard share of the modelled option: "
      f"{np.nanmedian(p['wildcard32']/p['dov32'].replace(0,np.nan)):.1%}")'''))

cells.append(md("""## 3. Data-quality funnel"""))
cells.append(code('''rows = [("panel days", len(p)),
        ("  rolls", int(p["is_roll"].sum())),
        ("  gaps > 5d", int((pd.Series(p["date"]).diff().dt.days > 5).sum())),
        ("days with a modelled option", int(p["dov32"].notna().sum())),
        ("days with a z-score", int(p["z"].notna().sum())),
        ("trades", len(RES.trades))]
display(pd.DataFrame(rows, columns=["stage","n"]))
print("\\nnet-basis day-to-day noise (a stitching artefact between cash and futures sources):")
d = p["ctd_bnoc32"].diff().abs()
print(f"  median |dBNOC| = {d.median():.2f}/32,  95th pct = {d.quantile(.95):.2f}/32")'''))

cells.append(md("""## 4. Performance"""))
cells.append(code('''summ = A.summarize(RES.daily, RES.trades)
display(pd.Series(summ).to_frame("value").style.format(precision=3))
fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios":[2,1]})
ax[0].plot(RES.daily.index, RES.daily["equity"], lw=1.3, color="#1f4e79"); ax[0].axhline(0, color="k", lw=.7)
ax[0].set_ylabel("cumulative $"); ax[0].set_title(f"V1 equity — {CFG.key()}")
t = RES.trades
if len(t):
    ax[1].bar(pd.to_datetime(t["exit_date"]), t["pnl"], width=pd.Timedelta(days=6),
              color=np.where(t["pnl"]>0, "#2e7d32", "#c62828"))
ax[1].axhline(0, color="k", lw=.7); ax[1].set_ylabel("per-trade $")
plt.tight_layout(); plt.show()
if len(t): display(t.groupby("reason")["pnl"].agg(["count","mean","sum"]).round(0))'''))

cells.append(md("""## 5. Knob sweeps"""))
cells.append(code('''from dataclasses import replace as _rep
rows = []
for root in PANELS:
    for ez in (1.0, 1.5, 2.0, 2.5):
        for mh in (10, 21, 42):
            c = _rep(CFG, root=root, entry_z=ez, max_hold_days=mh)
            r = V1.run_v1(PANELS[root], c)
            if r.daily.empty: continue
            s = A.summarize(r.daily, r.trades); s.update(root=root, entry_z=ez, max_hold=mh)
            rows.append(s)
SWEEP = pd.DataFrame(rows)
display(SWEEP.sort_values("sharpe", ascending=False)
        [["root","entry_z","max_hold","n_trades","mean_volbp","hit_rate","sharpe","t_nw","top3_share"]]
        .head(12).round(3))'''))
cells.append(code('''fig, axes = plt.subplots(1, len(PANELS), figsize=(5*len(PANELS), 3.6), squeeze=False)
for ax, root in zip(axes[0], PANELS):
    piv = SWEEP[SWEEP.root==root].pivot_table(index="entry_z", columns="max_hold", values="sharpe")
    im = ax.imshow(piv.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(piv.columns)), piv.columns); ax.set_yticks(range(len(piv.index)), piv.index)
    ax.set_title(f"{root} Sharpe"); ax.set_xlabel("max hold"); ax.set_ylabel("entry z"); ax.grid(False)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax.text(j, i, f"{piv.values[i,j]:.2f}", ha="center", va="center", fontsize=8)
    plt.colorbar(im, ax=ax)
plt.tight_layout(); plt.show()'''))

cells.append(md("""## 6. Cost curve and break-even

The whole prize is ~1 tick (BofA: *"probably somewhere around 1 tick fair value"*), so the
break-even cost multiple is the headline, not the net P&L."""))
cells.append(code('''ladder = []
for cm in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
    r = V1.run_v1(PANELS[CFG.root], _rep(CFG, cost_mult=cm))
    s = A.summarize(r.daily, r.trades); s["cost_mult"] = cm; ladder.append(s)
LAD = pd.DataFrame(ladder)
display(LAD[["cost_mult","n_trades","mean_volbp","hit_rate","sharpe","t_nw"]].round(3))
alive = LAD[LAD.sharpe>0]["cost_mult"]
print(f"break-even cost multiple: {alive.max() if len(alive) else 0:.2f}x  "
      f"(1.0x = {CFG.cost_32nds}/32 round trip)")
plt.plot(LAD.cost_mult, LAD.sharpe, "o-"); plt.axhline(0, color="k", lw=.8)
plt.xlabel("cost multiple"); plt.ylabel("Sharpe"); plt.show()'''))

cells.append(md("""## 7. Model ablation — is the option model doing any work?

If OABNOC and raw BNOC give the same answer, the delivery-option model is decoration and the signal
is just a net-basis z-score."""))
cells.append(code('''abl = []
for lbl, kw in (("switch + wildcard", {}),
                ("switch only",       dict(use_wildcard=False)),
                ("wildcard only",     dict(use_switch=False)),
                ("no model (raw BNOC)", dict(use_switch=False, use_wildcard=False))):
    r = V1.run_v1(PANELS[CFG.root], _rep(CFG, **kw))
    s = A.summarize(r.daily, r.trades); s["model"] = lbl; abl.append(s)
ABL = pd.DataFrame(abl)
display(ABL[["model","n_trades","mean_volbp","hit_rate","sharpe","t_nw","top3_share"]].round(3))'''))

cells.append(md("""## 8. Permutation and multiple testing"""))
cells.append(code('''rng = np.random.default_rng(20260814)
tr = RES.trades
if len(tr):
    base = tr["pnl"].to_numpy(float) * tr["side"].to_numpy(float)
    draws = rng.choice([-1.0, 1.0], size=(2000, len(base)))
    tot = (base * draws).sum(axis=1)
    act = tr["pnl"].sum(); pct = float((tot < act).mean())
    plt.hist(tot, bins=50, color="#90a4ae"); plt.axvline(act, color="#c62828", lw=2,
             label=f"actual {act:,.0f}  (pct {pct:.2f})")
    plt.legend(); plt.title("sign-flip permutation (2,000 draws)"); plt.show()
else:
    pct = float("nan")

num = pd.to_numeric(SWEEP["sharpe"], errors="coerce").dropna()
n_trials, var = len(num), float(num.var(ddof=1))
emax = A.expected_max_sharpe(n_trials, var)
best = SWEEP.sort_values("sharpe", ascending=False).iloc[0]
bcfg = _rep(CFG, root=best["root"], entry_z=best["entry_z"], max_hold_days=int(best["max_hold"]))
bres = V1.run_v1(PANELS[best["root"]], bcfg)
dsr = A.deflated_sharpe(bres.daily["pnl_volbp"], n_trials, var)
lo, hi = A.block_bootstrap_ci(bres.daily["pnl_volbp"], block=21, n_boot=2000)
print(f"n_trials={n_trials}  E[max Sharpe|null]={emax:.3f}  best={best['sharpe']:.3f}  DSR={dsr:.4f}")
print(f"block-bootstrap 95% CI on Sharpe: [{lo:.2f}, {hi:.2f}]   permutation pct={pct:.3f}")
ALIVE = (dsr > 0.95) and (best["top3_share"] < 0.6) and (pct > 0.95)
print(f"\\nALIVE = {ALIVE}")'''))

cells.append(md("""## 9. Regime split"""))
cells.append(code('''display(A.regime_split(bres.daily, col="pnl_volbp").round(3))
plt.plot(bres.daily.index, bres.daily["equity"], lw=1.3); plt.axhline(0, color="k", lw=.7)
plt.title(f"best cell — {bcfg.key()}"); plt.ylabel("cumulative $"); plt.show()'''))

cells.append(md("""## 10. QueryDrivenBacktest cross-check

The same schedule through the repo's engine — MDP, query, adapter, position handler, triggers —
against the standalone loop. Costs are zeroed for the comparison because the framework has no
entry-side fee hook, so the two cost conventions differ by construction. Pricing must agree."""))
cells.append(code('''from BT.signals.basis_pair import run_v1_qdb, qdb_equity
c0 = _rep(CFG, cost_32nds=0.0)
bt, ref = run_v1_qdb(PANELS[CFG.root], c0)
q = float(qdb_equity(bt).iloc[-1]); r = float(ref.daily["gross_pnl"].sum())
print(f"QueryDrivenBacktest : {q:,.2f}\\nreference engine    : {r:,.2f}\\ndifference          : {q-r:,.6f}")
print(f"closed positions    : {len(bt.portfolio.closed_positions_log)} vs {len(ref.trades)} trades")
assert abs(q-r) < 1e-2, "engines disagree"
plt.plot(qdb_equity(bt).index, qdb_equity(bt).values, lw=1.3, label="QueryDrivenBacktest")
plt.plot(ref.daily.index, ref.daily["gross_pnl"].cumsum(), lw=1.0, ls="--", label="reference")
plt.legend(); plt.ylabel("cumulative $ (gross)"); plt.title("two engines, one P&L"); plt.show()'''))

cells.append(md(r"""## 11. Reading guide

| § | question |
|---|---|
| 2 | how big is the option the model is charging for, and which component dominates? |
| 3 | how much of the net-basis series is stitching noise rather than signal? |
| 5 | does the edge live in one cell or across the surface? |
| 6 | how much of it is a cost assumption? |
| 7 | **is the option model doing any work at all, or is this a raw BNOC z-score?** |
| 8 | what did the search cost, and does the winner clear it? |
| 10 | do two independent engines agree on the P&L? |

**Kill conditions, pre-registered.** Alive requires DSR > 0.95, top-3 trade share < 0.6, a
permutation percentile > 0.95, and survival at 2× costs. §7 is the one specific to V1: if the
no-model ablation matches the full model, the delivery-option machinery is not earning its place
and the honest description of the strategy is "fade the net basis".
"""))

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT} ({len(cells)} cells)")
