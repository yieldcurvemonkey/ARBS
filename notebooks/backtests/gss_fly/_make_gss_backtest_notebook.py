"""Generate `gss_fly_configurable_backtest.ipynb`.

Written as a generator rather than by hand for the same reason the FOMC study is: a notebook is a
bad place to keep source, and regenerating it is how the prose and the code stay in step.

    conda run -n stir python notebooks/backtests/gss_fly/_make_gss_backtest_notebook.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "gss_fly_configurable_backtest.ipynb"
REPO = r"C:\Users\chris\clee\ARBS-rvx"

cells: list = []


def md(text: str) -> None:
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)})


def code(text: str) -> None:
    cells.append({"cell_type": "code", "execution_count": None, "metadata": {},
                  "outputs": [], "source": text.strip("\n").splitlines(True)})


# ---------------------------------------------------------------------------- 0
md(r"""
# GSS Cash-Bond Butterfly — Configurable Backtest on QueryDrivenBacktest

A fitted-curve residual on off-the-run USTs: fit a b-spline to the curve, call a bond **cheap** when
it yields more than the fit says it should, build a maturity-weighted butterfly around it, and wait
for the residual to close.

Every choice in that sentence was a decision. Here they are **a dict**, so changing one is an edit
to data rather than to code, and two configurations can be compared without either being privileged.

```python
CONFIG = {
    "construction": {...},   # how the signal and the flies are BUILT   -> costs a 267s scan
    "gate":         {...},   # which candidates are TRADED              -> costs ~8s
    "spline":       "S0_jpm",
}
```

### The split is not cosmetic — it is the whole performance model

    panel (cached)  ->  SCAN candidates  ->  gate  ->  QueryDrivenBacktest prices it

A full run is **251s, of which 247s is `scan_flies`**. The scan depends only on the *construction*
knobs; every gate knob merely filters the same candidate list. So the notebook scans once and then
moves the gates for about a second each — and the gating is still performed by the real
`GSSSignalEngine`, so a swept result cannot drift from a directly-run one. That equivalence is
asserted in §2 rather than assumed.

### What this notebook concludes

The book does not work, and it is worth being precise about *which* claim that is:

| | |
|---|---|
| Signal reproducible? | **Yes** — corr(s2c) 0.983 across a 1.25y knot shift |
| Selection stable? | **No** — the same shift rewrites 95% of the trades |
| Clears its costs? | **No** — m\* ≈ 0.21; costs are 4.5× gross |
| A best configuration? | **No** — DSR 0.177 over 1,164 configs |
""")

# ---------------------------------------------------------------------------- 1 setup
code(rf"""
%load_ext autoreload
%autoreload 2

import sys, time, json, itertools, warnings
from pathlib import Path

REPO = r"{REPO}"
sys.path.insert(0, REPO)
sys.path.insert(0, str(Path(REPO) / "scripts"))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.pylab as pylab

plt.style.use("ggplot")
pylab.rcParams.update({{"figure.figsize": (14, 6), "axes.titlesize": "large",
                       "axes.labelsize": "large"}})
pd.set_option("display.width", 180)

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from BT.gss_fly import GSSConfig, build_curve_panel, load_repo_from_workbook
from BT.gss_fly.backtest import run_gss_backtest
from BT.gss_fly.data import ust_business_days
from BT.gss_fly.signals import build_bond_signals
from BT.gss_fly.strategy import GSSSignalEngine, scan_candidates
from BT.gss_fly.conditioning import trade_set_jaccard
from RVUtils.StatisticalFinance.deflated_sharpe import deflated_sharpe_of_best, effective_trials
import gss_grid as G

MDP = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
CACHE = Path(REPO) / "notebooks" / "data" / "gss_fly" / "panel_cached"

# NOT bdate_range: it contains market holidays, which the source never serves and whose fetcher
# HANGS rather than refusing. One Labor Day stalled two separate panel builds.
DAYS = ust_business_days("2024-09-02", "2026-01-02")
PANEL = build_curve_panel(DAYS, MDP, cache_path=CACHE, show_progress=False)

REPO_WB = Path(r"C:/Users/chris/Downloads/gc_repo_hist_example.xlsx")
REPO_CURVE = load_repo_from_workbook(REPO_WB, "USTREASGC") if REPO_WB.exists() else None

print(PANEL.summary())
print(f"repo curve     : {{REPO_CURVE}}")
print(f"grid           : {{len(DAYS)}} UST trading days")
""")

# ---------------------------------------------------------------------------- 2 config
md(r"""
## 1. The config

One dict fully describes one backtest. The comments name what each knob *does to the book*, taken
from the decision-space measurements in §5 — a knob whose one-step Jaccard is 0.08 is not a tuning
parameter, it is a different strategy.
""")

code(r"""
CONFIG = {
    "name": "incumbent",

    # HOW THE SIGNAL AND FLIES ARE BUILT ----------------------------------
    # Changing any of these costs a fresh 267s scan. They are also the knobs with the most
    # authority over the book: one step moves 55-92% of the trades (see section 5).
    "construction": {
        "signal.ts_weight":             0.75,   # blend of time-series vs cross-sectional z
        "signal.smoothing_halflife":    3.0,
        "signal.scoring_com":           20.0,   # NB the source passes this POSITIONALLY to
                                                # pd.ewma, so it is `com`, not halflife
        "universe.min_ttm":             3.0,
        "fly.wing_range_1":             2.0,    # +/- TTM the wings are drawn from, per bucket
        "fly.wing_range_2":             5.0,
        "fly.std_halflife":            20.0,    # the sigma in ZSig = |z| * sigma_fly
        "fly.fly_smoothing_halflife":   2.0,
        "fly.fly_scoring_com":         30.0,
        "fly.wing_objective":  "signal_gap",    # or "legacy_ttm_bug" — see section 5.1
    },

    # WHICH CANDIDATES ARE TRADED ----------------------------------------
    # Replayed against the cached scan, so each of these costs only its pricing (~8s).
    "gate": {
        "backtest.entry_zsig_bp":       3.0,    # enter when ZSig = |z|*sigma exceeds this
        "costs.repo_penalty_bp":        2.5,    # exit when ZSig decays below this
        "backtest.exit_abs_z":          0.5,
        "backtest.require_turning_point": True, # |z| must already be shrinking: buy the turn
        "backtest.reentry_cooldown_days": 5,
        "backtest.max_concurrent":       10,
        "costs.cost_legs":            "all",    # or "belly_only" — what the GSS source charges
        "costs.scale":                  1.0,    # multiplies the whole half-spread table
    },

    # THE CURVE THE RESIDUAL IS MEASURED AGAINST -------------------------
    # S0_jpm | S1_coarse | S2_dense | S3_shift | S4_with_otr.  A new fit costs a ~19min refit
    # and gets its own cache directory — the day cache is keyed by DATE, so two fits sharing a
    # directory would interleave into a panel that loads, reconciles, and means nothing.
    "spline": "S0_jpm",
}


def build(cfg=CONFIG):
    return G.make_cfg(cfg["construction"], cfg["gate"])


def scan(cfg=CONFIG, panel=None):
    '''The expensive half: candidates per date. Depends ONLY on the construction knobs.'''
    panel = panel if panel is not None else PANEL
    c = build(cfg)
    sig = build_bond_signals(panel.s2c, c.signal)["signal"]
    t0 = time.time()
    cands = scan_candidates(GSSSignalEngine(panel, sig, c, repo_curve=REPO_CURVE), panel.dates)
    return cands, sig, time.time() - t0


def run(cfg=CONFIG, cands=None, panel=None, sig=None):
    '''The cheap half. Pass `cands` from a prior scan when only the gate changed.'''
    panel = panel if panel is not None else PANEL
    return run_gss_backtest(panel, MDP, cfg=build(cfg), repo_curve=REPO_CURVE,
                            show_progress=False, strict=False, candidates=cands)


CANDS, SIG, SCAN_S = scan()
print(f"scan: {sum(len(v) for v in CANDS.values()):,} candidate-days in {SCAN_S:.0f}s")
""")

# ---------------------------------------------------------------------------- 3 known answer
md(r"""
## 2. Does the machine give the right answer to a question we already know?

A configurable backtest is a measuring instrument, and an instrument that is itself wrong reports
success while hiding the thing it was built to find. Two things are checked before any new number
is read.

**The cached-candidate path must be identical to a live scan.** If it is not, every swept result is
measured on a different book from the one the incumbent was measured on. Asserted on the trade log
*and* the full equity series — not on a summary statistic, because a summary can agree while the
book differs.

**The P&L decomposition must reconcile.** `equity = bond_ledger + financing_ledger − fees +
open_mark`, identically. That assertion refuted two successive and confident explanations of this
book's P&L during development, including one that had already been reported, so it is not
decoration.
""")

code(r"""
res = run(cands=CANDS)
sm  = res.summary()

live = run(cands=None)                     # the slow path, no candidate cache
same_log = res.trade_log[["date", "event", "fly_id"]].reset_index(drop=True).equals(
           live.trade_log[["date", "event", "fly_id"]].reset_index(drop=True))
same_eq  = float(np.nanmax(np.abs(res.equity.dropna().to_numpy()
                                  - live.equity.dropna().to_numpy())))

checks = [
    ("cached scan == live scan (trade log)", same_log, True),
    ("cached scan == live scan (equity, USD)", same_eq < 1e-9, True),
    ("equity holes", res.diagnostics["equity_holes"], 0),
    ("reconciliation gap (USD)", abs(sm["reconciliation_gap_usd"]) < 1e-6, True),
    ("closed >= signal exits", res.diagnostics["closed_positions"] >= res.diagnostics["signal_exits"], True),
]
for name, got, want in checks:
    print(f"  {'PASS' if got == want else 'FAIL'}  {name:42s} {got}")

print(f"\n  entries {res.diagnostics['signal_entries']}   closed {res.diagnostics['closed_positions']}"
      f"   still open {res.diagnostics['still_open']}")
print(f"  end equity  {sm['end_equity_usd']:>14,.0f} USD")
""")

# ---------------------------------------------------------------------------- 4 funnel
md(r"""
## 3. What this config actually trades

The gate is not arbitrary-tight; it sits at the top of the distribution it is cutting into.
`ZSig = |z| · sigma_fly` and the median fly vol is **0.55bp**, so a 3.0bp threshold demands
**|z| > 5.5 sigma**. That number came from the source's EGB book and did not survive the change of
market.
""")

code(r"""
from BT.gss_fly.data import apply_universe_filter

cfg = build()
rows = []
for ts in PANEL.dates:
    curve = PANEL.curve_on(ts)
    if curve.empty:
        continue
    curve = curve.rename(columns={"s2c": "_s2c"})
    curve["signal"] = SIG.loc[ts].reindex(curve.index) if ts in SIG.index else np.nan
    elig = apply_universe_filter(curve, cfg.universe)
    flies = CANDS.get(pd.Timestamp(ts), [])
    zs = np.array([f.zsig_bp for f in flies], float) if flies else np.array([])
    rows.append({
        "date": ts, "bonds": len(curve), "eligible": len(elig), "flies": len(flies),
        "zsig_pass": int((zs > cfg.backtest.entry_zsig_bp).sum()) if zs.size else 0,
        "turn_pass": sum(1 for f in flies if f.zsig_bp > cfg.backtest.entry_zsig_bp
                         and np.isfinite(f.d_abs_z) and f.d_abs_z < 0),
        "zsig_max": float(np.nanmax(zs)) if zs.size else np.nan,
        "std_med": float(np.nanmedian([f.std_bp for f in flies])) if flies else np.nan,
    })
F = pd.DataFrame(rows).set_index("date")

print("survivors per date")
for c in ("bonds", "eligible", "flies", "zsig_pass", "turn_pass"):
    print(f"  {c:>10}: mean {F[c].mean():8.1f}   median {F[c].median():7.1f}"
          f"   dates>0 {int((F[c] > 0).sum()):4d}/{len(F)}")
print(f"  {'zsig_max':>10}: median {F.zsig_max.median():.2f}bp   p90 {F.zsig_max.quantile(.9):.2f}bp")
print(f"  {'sigma_fly':>10}: median {F.std_med.median():.2f}bp"
      f"   -> the {cfg.backtest.entry_zsig_bp}bp gate needs |z| > {cfg.backtest.entry_zsig_bp/F.std_med.median():.1f}")

fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
F[["eligible", "flies"]].plot(ax=ax[0], lw=1).set_ylabel("count")
ax[0].set_title("universe and candidate flies per date")
F["zsig_max"].plot(ax=ax[1], lw=1, color="#4a7", label="best fly of the day")
ax[1].axhline(cfg.backtest.entry_zsig_bp, color="r", ls="--", label="entry gate")
ax[1].set_ylabel("ZSig (bp)"); ax[1].legend(); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 5 performance
md(r"""
## 4. How this config performed

Four **disjoint** terms that sum to the equity curve. The split matters more than the total: the
book pays carry to collect convergence, and hands most of the difference to the bid/offer.

`per_trade_pnl_usd` is deliberately **not** one of the four. It is a different cut of the same
money — already net of fees, already containing the carry realised at unwind — and adding it to the
ledgers double-counted every unwind by $10.7m in an earlier version of this analysis.
""")

code(r"""
def perf(sm, label=""):
    g, f = sm["gross_before_fees_usd"], -sm["fees_usd"]
    print(f"{label}")
    print(f"  carry during hold   {sm['carry_during_hold_usd']:>15,.0f}")
    print(f"  unwind proceeds     {sm['unwind_proceeds_usd']:>15,.0f}")
    print(f"  fees                {sm['fees_usd']:>15,.0f}")
    print(f"  open mark           {sm['open_mtm_usd']:>15,.0f}")
    print(f"  {'-'*36}")
    print(f"  = end equity        {sm['end_equity_usd']:>15,.0f}   (gap {sm['reconciliation_gap_usd']:.2e})")
    print(f"\n  gross before fees   {g:>15,.0f}")
    print(f"  cost share of gross {f/g if g else np.nan:>15.1%}")
    print(f"  m* (payable share)  {sm.get('breakeven_cost_multiplier', np.nan):>15.3f}"
          f"   <- >=1 survives its own cost table")
    print(f"  daily Sharpe (ann)  {sm['daily_sharpe_ann']:>15.2f}   +/- {np.sqrt(252/sm['marked_days']):.2f} SE")
    print(f"  max drawdown        {sm['max_dd_usd']:>15,.0f}")
    print(f"  trades / median hold {sm['closed_trades']:>10} / {sm['median_hold_days']:.1f}d")

perf(sm, CONFIG["name"])

eq = res.equity.dropna()
fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True,
                       gridspec_kw={"height_ratios": [2, 1]})
eq.plot(ax=ax[0], lw=1.6, color="#4dabf7")
ax[0].axhline(0, color="k", lw=0.8); ax[0].set_ylabel("USD")
ax[0].set_title("cumulative total P&L (engine mtm_history: realized + open mark, net of fees)")
(eq - eq.cummax()).plot(ax=ax[1], lw=1.2, color="#d55")
ax[1].fill_between((eq - eq.cummax()).index, (eq - eq.cummax()).to_numpy(), 0,
                   color="#d55", alpha=.2)
ax[1].set_ylabel("drawdown (USD)"); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 6 the level knob
md(r"""
## 5. The entry / exit level knob — and the boundary the shipped config sits next to

Entry and exit are thresholds on the **same statistic**: enter when `zsig > E`, exit when
`zsig <= X`. Nothing enforces `X < E`. Whenever `E <= X` a fly is entered and *immediately*
qualifies to exit — a full round trip for nothing.

The incumbent is `E = 3.0, X = 2.5`. **Half a basis point from that boundary.**
""")

code(r"""
EX = [(e, x) for e in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5) for x in (0.25, 1.0, 2.5)]
rows = []
for e, x in EX:
    c = json.loads(json.dumps(CONFIG))
    c["gate"]["backtest.entry_zsig_bp"], c["gate"]["costs.repo_penalty_bp"] = e, x
    r = run(c, cands=CANDS); s = r.summary()
    rows.append({"E": e, "X": x, "inverted": x >= e, "trades": s["closed_trades"],
                 "hold_d": s["median_hold_days"], "equity": s["end_equity_usd"],
                 "m_star": s.get("breakeven_cost_multiplier", np.nan),
                 "sharpe": s["daily_sharpe_ann"]})
EXT = pd.DataFrame(rows)
print(EXT.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
print("\ninverted = X >= E: every entry immediately qualifies to exit.")
print(f"churn multiple at E=1.0: {EXT.query('E==1.0 and X==2.5').trades.iloc[0]:.0f} trades "
      f"vs {EXT.query('E==1.0 and X==0.25').trades.iloc[0]:.0f} properly ordered")

piv = EXT.pivot(index="X", columns="E", values="trades")
fig, ax = plt.subplots(1, 2, figsize=(14, 4.5))
im = ax[0].imshow(piv.values, aspect="auto", cmap="magma_r")
ax[0].set_xticks(range(len(piv.columns)), piv.columns); ax[0].set_yticks(range(len(piv.index)), piv.index)
ax[0].set_xlabel("entry E (bp)"); ax[0].set_ylabel("exit hurdle X (bp)"); ax[0].set_title("trades")
plt.colorbar(im, ax=ax[0])
for x_, gdf in EXT.groupby("X"):
    ax[1].plot(gdf.E, gdf.equity, marker="o", label=f"X={x_}")
ax[1].axhline(0, color="k", lw=.8); ax[1].set_xlabel("entry E (bp)"); ax[1].set_ylabel("end equity (USD)")
ax[1].legend(); ax[1].set_title("equity vs the entry level"); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 7 construction
md(r"""
## 6. The construction knobs — measured where there is no estimation error

Performance cannot rank these. At ~154 active marks `SE(annualised Sharpe) = 0.87` and the whole
cross-config spread is 0.88, so the spread *is* the noise (see §8).

**Which trades a config takes is deterministic**, so that is where conditioning is measurable.
Jaccard against the incumbent, one step per knob: `J ~ 0.9` is a nuisance knob, `J ~ 0.5` means the
knob redefines the book, `J <= 0.2` means a different strategy entirely.

Each row here costs a fresh 267s scan, so this cell is the slow one.
""")

code(r"""
base_log = res.trade_log
rows = []
for knob, levels in G.CONSTRUCTION_LEVELS.items():
    for lv in levels:
        if lv == CONFIG["construction"][knob]:
            continue
        c = json.loads(json.dumps(CONFIG)); c["construction"][knob] = lv
        if not G.valid_construction(c["construction"]):
            continue
        cd, _, _ = scan(c)
        r = run(c, cands=cd)
        rows.append({"knob": knob, "level": lv,
                     "trades": r.diagnostics["signal_entries"],
                     "jaccard": trade_set_jaccard(base_log, r.trade_log),
                     "jaccard_tol3": trade_set_jaccard(base_log, r.trade_log, tolerance_days=3)})
CJ = pd.DataFrame(rows)
prof = (CJ.groupby("knob").agg(steps=("level", "count"), min_J=("jaccard", "min"),
                               median_J=("jaccard", "median"), median_tol=("jaccard_tol3", "median"))
          .assign(timing_gap=lambda d: d.median_tol - d.median_J)
          .sort_values("median_J"))
print(prof.to_string(float_format=lambda v: f"{v:.3f}"))
print("\ntiming_gap ~ 0 means the knob changes WHICH trades, not WHEN — not jitter around a"
      " stable book.")
prof["median_J"].plot(kind="barh", figsize=(11, 5), color="#4a7")
plt.axvline(0.5, color="r", ls="--"); plt.xlabel("Jaccard vs incumbent")
plt.title("one step of each construction knob"); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 8 costs
md(r"""
## 7. Costs — the binding constraint

`m* = gross / fees` is the fraction of the charged bid/offer the book can actually pay. `m* >= 1`
survives; the incumbent is **0.245**, i.e. execution would have to be about **4× tighter**.

The fee never feeds back into the trade decision, so the whole cost axis is recoverable in closed
form from one run — no re-pricing needed.
""")

code(r"""
from BT.gss_fly.conditioning import breakeven_cost_multiplier, equity_at_cost_multiplier

for legs in ("all", "belly_only"):
    c = json.loads(json.dumps(CONFIG)); c["gate"]["costs.cost_legs"] = legs
    r = run(c, cands=CANDS); s = r.summary()
    print(f"  cost_legs={legs:11s} fees {s['fees_usd']:>13,.0f}  equity {s['end_equity_usd']:>13,.0f}"
          f"  m* {s.get('breakeven_cost_multiplier', np.nan):.3f}")

ms = np.linspace(0, 1.5, 31)
ends = [equity_at_cost_multiplier(res.equity, res.closed, m).iloc[-1] for m in ms]
mstar = breakeven_cost_multiplier(res.equity, res.closed)
plt.figure(figsize=(11, 4.5))
plt.plot(ms, ends, lw=2); plt.axhline(0, color="k", lw=.8)
plt.axvline(1.0, color="r", ls="--", label="charged cost")
plt.axvline(mstar, color="g", ls=":", label=f"break-even m* = {mstar:.3f}")
plt.xlabel("cost multiplier"); plt.ylabel("end equity (USD)")
plt.title("how much cheaper would execution have to be?"); plt.legend(); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 9 spline
md(r"""
## 8. The spline knob — signal or selection?

The residual is measured against a fitted curve, so the obvious worry is that the fit manufactures
it. `S3_shift` tests exactly that: the **same number of knots, slid 1.25 years**. Nothing about the
market changes, only where the spline may bend.

**A trade-set Jaccard cannot answer this question**, and reading one as if it could is a mistake
this analysis actually made. Jaccard came back 0.045 and the first conclusion drawn was "the signal
reads the interpolator". The discriminating quantity is the s2c **values**:

| | S0 vs S3 |
|---|---|
| corr(s2c) | **0.983** |
| Spearman rank | **0.944** |
| trade Jaccard | **0.045** |

The signal barely moves and the book is rewritten anyway, because selection is a hard top-N over
~173 near-tied candidates a day and 0.26bp — a seventh of a standard deviation — reorders the top
of the list. **The selection is chaotic; the signal is not.** That is a fixable design fault
(rank-average across fits, require a gap to the next-best candidate, size by conviction) rather than
a dead idea — though it does not rescue the economics in §7.

Requires the alternate panel; skipped cleanly if it has not been built.
""")

code(r"""
alt = "S3_shift"
try:
    P_ALT = build_curve_panel(DAYS, MDP, cache_path=CACHE, show_progress=False,
                              spline_config=G.spline_variants()[alt])
except Exception as exc:
    P_ALT = None
    print(f"{alt} panel not built ({type(exc).__name__}); "
          f"run scripts/gss_spline_panels.py --spline {alt}")

if P_ALT is not None:
    A, B = PANEL.s2c, P_ALT.s2c
    cols, idx = A.columns.intersection(B.columns), A.index.intersection(B.index)
    cs, rk = [], []
    for t in idx:
        x, y = A.loc[t, cols], B.loc[t, cols]
        m = x.notna() & y.notna()
        if m.sum() > 10:
            cs.append(np.corrcoef(x[m], y[m])[0, 1])
            rk.append(x[m].rank().corr(y[m].rank(), method="spearman"))
    cd_alt, sig_alt, _ = scan(CONFIG, panel=P_ALT)
    r_alt = run(CONFIG, cands=cd_alt, panel=P_ALT)
    print(f"  corr(s2c)        median {np.median(cs):.4f}   p05 {np.percentile(cs,5):.4f}")
    print(f"  Spearman rank    median {np.median(rk):.4f}")
    print(f"  trade Jaccard    {trade_set_jaccard(res.trade_log, r_alt.trade_log):.4f}")
    print(f"  entries          {res.diagnostics['signal_entries']} -> {r_alt.diagnostics['signal_entries']}")
    print("\n  A high correlation with a low Jaccard means the SELECTION is chaotic, not the signal.")
""")

# ---------------------------------------------------------------------------- 10 search cost
md(r"""
## 9. What the search cost

Every knob turned above is a trial, and the maximum of many noisy estimates is large even when
nothing has an edge. The Deflated Sharpe asks the only useful question: **is this Sharpe bigger than
the best one this search would have produced by chance?**

Over the full 1,164-config sweep (`scripts/gss_grid.py`) the answer is no — the best config lands
**below** the bar its own search sets. The bar is high because a Sharpe on 331 daily marks has a
standard error of 0.87, not because the test is harsh: cross-config sd is 0.884 against a per-config
SE of 0.873, a ratio of 1.013, so the entire spread across the parameter space *is* estimation noise.
""")

code(r"""
GRID = Path(REPO) / "notebooks" / "data" / "gss_fly" / "grid" / "S0_jpm" / "rows"
files = sorted(GRID.glob("*.parquet"))
if not files:
    print("no sweep on disk; run scripts/gss_grid.py --workers 20")
else:
    sweep = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    sweep = sweep[sweep.get("ok", False) == True]                                  # noqa: E712
    series = [np.asarray(json.loads(s), float) for s in sweep["daily_pnl"]]
    series = [s for s in series if len(s) > 20 and np.isfinite(s).all() and s.std() > 0]
    out = deflated_sharpe_of_best(series)
    ann = np.sqrt(252)
    print(f"  configs                 {len(series):,}")
    print(f"  effective ind. trials   {out['n_trials_effective']:.0f} "
          f"({out['n_trials_effective']/len(series):.0%})")
    print(f"  best Sharpe             {out['best_sharpe']*ann:+.2f} ann")
    print(f"  SR0 (the bar)           {out['sr0']*ann:+.2f} ann")
    print(f"  DSR                     {out['dsr']:.3f}     (needs > 0.95)")
    s_ann = sweep["sharpe_ann"].replace([np.inf, -np.inf], np.nan).dropna()
    se = np.sqrt(252 / sweep["n_obs"].median())
    print(f"\n  cross-config sd {s_ann.std():.3f} vs per-config SE {se:.3f}"
          f"  -> ratio {s_ann.std()/se:.3f}  (1.0 = the spread IS the noise)")
    plt.figure(figsize=(11, 4.5))
    plt.hist(s_ann, bins=60, color="#4dabf7", alpha=.85)
    plt.axvline(out["sr0"]*ann, color="r", ls="--", label=f"SR0 {out['sr0']*ann:+.2f}")
    plt.axvline(s_ann.max(), color="g", ls=":", label=f"best {s_ann.max():+.2f}")
    plt.xlabel("annualised Sharpe"); plt.ylabel("configs")
    plt.title("the search, and the bar it has to clear"); plt.legend(); plt.tight_layout()
""")

# ---------------------------------------------------------------------------- 11 trade log
md(r"""
## 10. Trade log
""")

code(r"""
if not res.closed.empty:
    cols = [c for c in ("opened_at", "closed_at", "holding_period_days", "realized_pnl",
                        "gross_realized_pnl", "fee_allocated") if c in res.closed.columns]
    T = res.closed[cols].copy()
    T["fly"] = [ (m or {}).get("fly_id") for m in res.closed.get("position_meta", [{}]*len(res.closed)) ]
    print(T.to_string(index=False, float_format=lambda v: f"{v:,.0f}"))
    print(f"\nNOTE realized_pnl is the PER-TRADE cut: already net of fees and already containing "
          f"the carry realised at unwind.\nIt sums to {res.closed['realized_pnl'].sum():,.0f} "
          f"against a book that made {sm['end_equity_usd']:,.0f}. They are different questions.")
""")

# ---------------------------------------------------------------------------- 12 reading
md(r"""
## 11. Reading this notebook

**Do not rank configurations by Sharpe.** With 331 daily marks the standard error is 0.87
annualised and the entire cross-config spread is 0.88. Any "best config" chosen here is a draw from
noise, and §9 shows the best of 1,164 lands below the bar the search itself sets.

**The knobs are not tuning parameters.** Twelve of sixteen change more than half the trade set in
one step; the worst is a boolean. "The GSS strategy" is one arbitrary point whose neighbours are
different strategies sharing a name — so a performance figure quoted for it describes that point,
not the idea.

**Three claims this analysis got wrong and corrected**, kept here because each was reported before
it was checked:

1. *"Cost-dead everywhere"* — too absolute. 13% of the space does cover its charged spread; those
   configs are what the DSR then rejects.
2. *"The signal reads the interpolator"* — wrong. corr(s2c) = 0.983; it was the argmax cascading.
   A trade-set Jaccard cannot distinguish the two, and §8 measures the quantity that can.
3. *"31× swing from `entry_zsig_bp`"* — misattributed. It is an `E`/`X` interaction, and the real
   finding is that the shipped config sits 0.5bp from a churn boundary.

**What holds.** The signal is reproducible. The selection built on it is not. The book pays about
$7.9m of carry to collect $10.7m of convergence and hands $5.6m to the bid/offer, so m\* ≈ 0.21 —
and no configuration in the sampled space is defensible.
""")

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.13"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
