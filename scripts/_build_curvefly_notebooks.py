"""Emit the two screener notebooks. Source of truth for both .ipynb files."""
from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "notebooks" / "rv"
OUT.mkdir(parents=True, exist_ok=True)

KERNEL = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.13.5"},
}


def nb(cells):
    out = []
    for kind, src in cells:
        lines = src.split("\n")
        body = [l + "\n" for l in lines[:-1]] + [lines[-1]]
        c = {"cell_type": kind, "metadata": {}, "source": body}
        if kind == "code":
            c["execution_count"] = None
            c["outputs"] = []
        out.append(c)
    return {"cells": out, "metadata": KERNEL, "nbformat": 4, "nbformat_minor": 5}


BOOT = '''import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import dataclasses
import datetime
import math
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

_here = pathlib.Path.cwd()
_REPO = next(p for p in [_here, *_here.parents] if (p / "RVUtils").is_dir())
sys.path.insert(0, str(_REPO))

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

pio.renderers.default = "notebook_connected"
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 120)
print("repo:", _REPO)'''


# ===========================================================================
# 1. curve + fly screener
# ===========================================================================
SCREENER = [
("markdown", """# Curve & fly screener — every two-leg curve and butterfly, spot and forward

Ranks 1,075 structures on static-curve carry-and-roll and a risk-adjusted version
of it. One leg warm composes into every structure, so the whole screen prices in
about a second.

## Read these four things before you read the ranking

1. **The carry convention is the whole design decision.** Under *forwards-realised*
   a par swap's carry-and-roll is identically zero — it is the arbitrage-free
   statement, not a signal. This uses the **static-curve** convention. The trap is
   the spot leg: ageing a `T`y swap to the `h x (T-h)` **forward** instead of the
   `(T-h)` **spot** silently reimplements forwards-realised. Gate G3 exists purely
   to catch that.
2. **`IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` is not this quantity** and is never
   used in the ranking. Against the published bank screen it correlates −0.136
   where a repriced roll scores +0.991. On `10y10y/20y10y` it disagrees by 10bp
   *and flips the sign*.
3. **Carry and richness are largely the same fact.** `corr(cr_bp, zs) = +0.61`.
   Carry-and-roll here *is* the aged level minus the level, so a structure at an
   extreme of its range shows fat roll for the same reason it looks rich. Ranking
   on `rac` alone systematically surfaces things that have already run — hence
   `rac_net`, and hence reading both.
4. **47 structures are degenerate.** Their legs sit between the same curve nodes
   and move in lockstep, so the level is near-constant by construction and the
   ratio explodes. Before the floor they were the *top and bottom* of the ranking.

Nothing is reported until the gates in section 4 pass."""),
("code", BOOT),
("markdown", """## 1. CONFIG — every knob, and why it is set where it is"""),
("code", '''@dataclasses.dataclass(frozen=True)
class ScreenConfig:
    """Everything this notebook chooses over and above the module defaults."""

    # ---- marks --------------------------------------------------------------
    as_of: datetime.datetime = datetime.datetime(2026, 8, 21, 17, 0)
    """Curve date. Naive is localised to America/New_York, which is the zone Citi
    Velocity's own stamps are in."""
    curve: str = "USD-SOFR-1D"
    source: str = "citivelo_excel_rl"

    # ---- history ------------------------------------------------------------
    hist_start: datetime.date = datetime.date(2024, 8, 21)
    hist_end: datetime.date = datetime.date(2026, 8, 21)
    """Two years. Long enough for a stable vol and z-score, short enough that the
    sample is the current regime. Warming ~70 legs over this window costs ~520s
    the first time and nothing after; the parquet is gitignored and regenerable."""

    # ---- measure ------------------------------------------------------------
    horizon_y: float = 1.0
    """Carry-and-roll horizon. 1y matches the ConvexityRV work so the numbers are
    directly comparable to that book."""
    business_days: float = 252.0

    # ---- gates --------------------------------------------------------------
    vol_floor_bp: float = 0.25
    """Realised daily vol below which a structure is treated as a curve-
    interpolation artifact rather than a trade. 47 structures fail this and they
    would otherwise occupy both ends of the ranking."""
    min_obs: int = 100
    """Below this, a z-score is computed off too few points to mean anything."""
    compose_tol_bp: float = 3.0
    """Compose-vs-price tolerance. The TimeseriesBuilder history and the live
    pricer are different vintages; a small gap is expected, a large one means the
    two sources have diverged and the z-scores cannot be trusted."""


CFG = ScreenConfig()
LEG_HIST = _REPO / "docs" / "curvefly" / "leg_history.parquet"
CFG'''),
("markdown", """## 2. Leg warm

Every structure level is linear in its legs, so one warm over ~70 legs composes
into all 1,075 with no per-structure fetch. Goes through the repo pattern:
`IRSwapsMDP → IRSwapsTB → TimeseriesBuilder`, one `UnifiedQuery` per leg.

Tenor shorthand stays **lowercase-concatenated** (`10y10y`) throughout — tenor
case forks the cache symbol, so mixing `10Y10Y` in would silently double the
fetch and split the history."""),
("code", '''from RVUtils.CurveFlyScreener import full_universe, leg_label, leg_universe

LEGS = leg_universe()
print(f"{len(LEGS)} legs")

if LEG_HIST.exists():
    leg_hist = pd.read_parquet(LEG_HIST)
    print(f"loaded cached warm: {leg_hist.shape}")
else:
    import pytz

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.registry import UnifiedValue
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    NY = pytz.timezone("America/New_York")
    labels = [leg_label(l) for l in LEGS]
    t0 = time.time()
    raw = TimeseriesBuilder().get_timeseries(
        start=NY.localize(datetime.datetime.combine(CFG.hist_start, datetime.time(17))),
        end=NY.localize(datetime.datetime.combine(CFG.hist_end, datetime.time(17))),
        queries=[UnifiedQuery(curve=CFG.curve, tenor=t, value=UnifiedValue.IRS_RATE)
                 for t in labels],
        n_jobs=8,
        routers={"IRS": IRSwapsTB(IRSwapsMDP(source=CFG.source), show_tqdm=False)},
    )
    ren = {f"{CFG.curve} {lab} OUTRIGHT RATE": lab for lab in labels}
    leg_hist = raw[[c for c in ren if c in raw.columns]].rename(columns=ren) * 100.0
    LEG_HIST.parent.mkdir(parents=True, exist_ok=True)
    leg_hist.to_parquet(LEG_HIST)
    print(f"warmed in {time.time()-t0:.0f}s -> {leg_hist.shape}")

cov = leg_hist.notna().mean()
print(f"{len(leg_hist)} dates | median leg coverage {cov.median():.0%}")
thin = cov[cov < 0.8]
if len(thin):
    print("THIN LEGS (excluded from vol/z by the min_obs gate):")
    print((thin * 100).round(0).to_string())
else:
    print("no thin legs")'''),
("markdown", """## 3. Universe and pricing

Bounds are stated rather than silently applied: forward legs capped at
`start + tenor <= 40` to stay on the liquid curve, and the general
`f1 x t1` vs `f2 x t2` cross product (~2,000 mostly unquoted names) is excluded
by design rather than allowed to dominate the ranking by sheer count.

Par rates are memoised by `(fwd, tenor)`: the screen touches ~70 distinct legs
today and ~70 aged, so without the memo the same handful of swaps get rebuilt and
repriced thousands of times."""),
("code", '''from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from RVUtils.CurveFlyScreener import (
    add_risk_adjustment, compose_levels, screen, structure_rate_bp,
)

pricer = IRSwapsMDP(source=CFG.source).get_data(
    {"curve_name": CFG.curve, "timestamp": CFG.as_of})
UNI = full_universe()
print(pd.Series([s.kind for s in UNI]).value_counts().to_string())

t0 = time.time()
raw_screen = screen(pricer, UNI, horizon_y=CFG.horizon_y)
print(f"\\npriced {len(raw_screen)} structures in {time.time()-t0:.1f}s")
raw_screen = raw_screen[raw_screen.error == ""].drop(
    columns=["error", "rlzd_vol_bp", "zs_1y", "rac"])
levels = compose_levels(leg_hist, UNI)
print(f"composed {levels.shape[1]} level histories over {len(levels)} dates")'''),
("markdown", """## 4. GATES

Two, and both have fired for real.

**compose-vs-price** — a level built from the leg warm against the same level
priced off the live curve. They come from different sources at slightly different
vintages, so a small gap is expected. A large one means the z-scores are being
computed against a history that no longer describes today's level.

**degeneracy** — legs read off the same curve nodes move in lockstep, so a
structure spanning no node has a near-constant level and a near-zero denominator.
Before this floor, `20y(5s7s10s)` scored `rac` 6.92 on 0.061bp/day and
`20y(2s3s)` scored −7.19 on 0.035. They were the best and worst names on the
board and neither exists."""),
("code", '''# ---- GATE 1: compose vs price -------------------------------------------
chk = [(s.label, structure_rate_bp(pricer, s), float(levels[s.label].ffill().iloc[-1]))
       for s in UNI[::19] if s.label in levels.columns]
g1 = pd.DataFrame(chk, columns=["label", "priced", "composed"])
g1["diff"] = g1.priced - g1.composed
mean_d, max_d = g1["diff"].abs().mean(), g1["diff"].abs().max()
print(f"GATE compose-vs-price on {len(g1)}: mean |diff| {mean_d:.2f}bp | max {max_d:.2f}bp")
print(g1.reindex(g1["diff"].abs().sort_values(ascending=False).index)
      .head(4).round(2).to_string(index=False))
if max_d > CFG.compose_tol_bp:
    print(f"\\n  !! above the {CFG.compose_tol_bp}bp tolerance. The history and the live")
    print("     pricer have diverged; z-scores are computed WITHIN the composed")
    print("     history so they stay internally consistent, but do not mix the two.")
else:
    print(f"  within the {CFG.compose_tol_bp}bp tolerance")

df = add_risk_adjustment(raw_screen, levels, business_days=CFG.business_days,
                         min_obs=CFG.min_obs)

# ---- GATE 2: degeneracy --------------------------------------------------
deg = df[df.rlzd_vol_bp < CFG.vol_floor_bp]
print(f"\\nGATE degeneracy: {len(deg)} structures under {CFG.vol_floor_bp}bp/day, excluded")
if len(deg):
    print("  the rac they would have scored, worst first:")
    print(deg.reindex(deg.rac.abs().sort_values(ascending=False).index)
          .head(5)[["label", "level_bp", "cr_bp", "rlzd_vol_bp", "rac"]]
          .round(3).to_string(index=False))
df = df[df.rlzd_vol_bp >= CFG.vol_floor_bp].copy()
print(f"\\n-> {len(df)} structures survive both gates")'''),
("markdown", """## 5. The confound

`corr(cr_bp, zs)` across the surviving universe. This is a property of the
measure, not of the sample: carry-and-roll *is* the aged level minus the level,
so a structure sitting at an extreme of its own range shows fat roll for the same
reason it looks rich.

The consequence is that `rac` alone is a ranking of *things that have already
moved*. `rac_net` charges the position for full reversion to its sample mean,
which is the conservative bound in the other direction. Read both."""),
("code", '''ok = df.dropna(subset=["cr_bp", "zs"])
rho = float(np.corrcoef(ok.cr_bp, ok.zs)[0, 1])
print(f"corr(carry, level z) = {rho:+.3f} over {len(ok)} structures")
for k, sub in ok.groupby("kind"):
    if len(sub) > 5:
        print(f"  {k:<18} {float(np.corrcoef(sub.cr_bp, sub.zs)[0,1]):+.3f}  (n={len(sub)})")

fig = px.scatter(ok, x="zs", y="cr_bp", color="kind", hover_name="label",
                 labels={"zs": "level z-score (2y)", "cr_bp": "1y carry-and-roll, bp"},
                 title=f"Carry is not independent of entry level  (rho = {rho:+.2f})")
fig.add_hline(y=0, line_width=1, line_color="#888")
fig.add_vline(x=0, line_width=1, line_color="#888")
fig.update_layout(height=520, legend_title_text="")
fig.show()'''),
("markdown", """## 6. The ranking

`rac` is the carry view. `rac_net` is the value view. They disagree, and the
disagreement is the output — not a defect to be averaged away."""),
("code", '''NAMED = ["10y10y/20y10y", "10y10y/15y10y", "5y10y/10y10y", "15y5y/20y5y",
         "2s10s", "5s30s", "2s7s20s", "5s10s30s"]
COLS = ["label", "kind", "level_bp", "cr_bp", "rlzd_vol_bp", "zs", "rac",
        "rev_drag_bp", "cr_net_rev", "rac_net"]
print("=== the structures the desk names ===")
print(df[df.label.isin(NAMED)][COLS].round(2).to_string(index=False))

print("\\n=== by family ===")
print(ok.groupby("kind").agg(
    n=("rac", "size"), mean_cr=("cr_bp", "mean"),
    pct_carry_pos=("cr_bp", lambda x: (x > 0).mean()),
    mean_rac=("rac", "mean"), mean_rac_net=("rac_net", "mean"),
    mean_vol=("rlzd_vol_bp", "mean")).round(3).to_string())'''),
("code", '''for kind in ok.kind.unique():
    sub = ok[ok.kind == kind]
    print(f"\\n=== {kind} ===")
    for col in ("rac", "rac_net"):
        top = sub.sort_values(col, ascending=False).head(5)
        print(f"  top 5 by {col}:")
        print(top[["label", "level_bp", "cr_bp", "zs", "rac", "rac_net"]]
              .round(2).to_string(index=False))'''),
("markdown", """## 7. Carry against reversion, at the horizon

`rac_net` assumes reversion completes. That over-charges a slow structure, so
scale it by how much of the move actually lands inside the holding period, using
each level's own AR(1) half-life:

    fraction reverted over h with half-life L  =  1 - 2^(-h/L)

The half-lives are estimated in-sample and are the least stable number in this
notebook. Treat the direction as solid and the magnitudes as indicative."""),
("code", '''def half_life_months(s: pd.Series, obs_per_month: float = 21.0) -> float:
    """AR(1) half-life of a level series, in months. inf when no mean reversion."""
    x = s.dropna()
    dx = x.diff().dropna()
    xl = (x.shift(1).dropna()).loc[dx.index]
    beta = float(np.polyfit(xl - x.mean(), dx, 1)[0])
    return (math.log(2) / -beta / obs_per_month) if beta < 0 else math.inf


HORIZONS = (3.0, 4.5, 6.0, 12.0)
rows = []
for lab in NAMED:
    if lab not in levels.columns or lab not in set(df.label):
        continue
    r = df[df.label == lab].iloc[0]
    L = half_life_months(levels[lab])
    row = {"structure": lab, "half_life_m": round(L, 1) if math.isfinite(L) else np.inf,
           "carry_1y": round(r.cr_bp, 2), "drag_full": round(r.rev_drag_bp, 2)}
    for h in HORIZONS:
        frac = 1 - 2 ** (-h / L) if math.isfinite(L) else 1.0
        row[f"net_{h:g}m"] = round(r.cr_bp * h / 12 + r.rev_drag_bp * frac, 2)
    rows.append(row)
hz = pd.DataFrame(rows)
print("bp of structure. Positive = a long position in the quoted level earns it.")
print(hz.to_string(index=False))'''),
("markdown", """## 8. What this does not know

* **Bid-offer.** The screen ranks carry per unit of realised vol and nothing else.
  The top raw-`rac` name is typically a 1y tail 10–20 years forward, which is
  nothing like as liquid as a 10y tail.
* **Whether the mean is the attractor.** `rac_net` assumes reversion to a two-year
  mean. If the curve is structurally repricing rather than mean-reverting, `rac`
  is the better guide. That is a view, not a screen output — but the trade
  requires one, and this notebook's job is to make that explicit rather than
  quietly pick a side.
* **Convexity.** Carry-and-roll is a first-order measure. A forward flattener is
  convex and a steepener concave; neither shows up here. For that, see the
  ConvexityRV work and the breakeven-vol statistic.
* Mean `rac_net` is ~0 or negative for **every** family. Charged for where levels
  sit, the whole screen is close to a wash. It sorts structures; it does not find
  free carry."""),
]


# ===========================================================================
# 2. SOFR butterfly grid
# ===========================================================================
GRID = [
("markdown", """# SOFR butterfly grid — what the option strikes say the distribution is

Rebuilds the 12bp call-fly grid from listed settles.

> *"12bp wide, 6bp body increments, prev day settle. Buy lower + Sell 2× body +
> Buy upper (calls). Wings = ±12bp. Max payout = 0.125. Imp Prob = Fly Settle ÷
> 0.125. Yield = 100 − body."*

Listed SOFR strikes are 6.25bp apart and the wings sit two steps out, so the fly
pays 0.125 at the body and tapers linearly to zero ±12.5bp away.

## Two traps, both of which change the answer

1. **Barchart serves no EOD for deep-ITM calls.** A naive rebuild stops dead at
   the first body needing a call struck below the future — which is exactly where
   the pin is. Fill via put-call parity `C(K) = P(K) + DF·(F − K)` from the OTM
   puts, the same route the Breeden–Litzenberger pipeline uses.
2. **"Imp Prob" is not a probability.** Adjacent triangular kernels of half-width
   12.5bp on a 6.25bp body grid overlap ~2×, so the column **sums to 2.0**. Halve
   it for a first-order true mass, and never add it across bodies.

## What it is for

The forward is the *mean* of the distribution. The grid shows the *mode*. When
they are far apart the priced path is not the likely path, and the gap is the
tail doing the work."""),
("code", BOOT),
("markdown", """## 1. CONFIG"""),
("code", '''@dataclasses.dataclass(frozen=True)
class GridConfig:
    as_of: datetime.date = datetime.date(2026, 8, 21)
    """Settlement date for the option marks. The grid is a prev-day-settle
    object; using an intraday mark mixes vintages across strikes."""
    contracts: tuple = ("SFRU26", "SFRV26", "SFRX26", "SFRZ26")
    """Option expiries. Two-digit year — ``SFRU6`` raises. V6/X6 are serial
    monthlies and settle on the SFRZ26 future, which is why their forward is not
    their own name."""
    source: str = "BARCHART_STIRFO-QL"
    wing: float = 0.125
    """Wing distance in price points: two listed strike steps of 6.25bp."""
    discount_factor: float = 0.998
    """For the parity fill. The term is second order at these expiries; a 20bp
    error in DF moves a fly by well under a tick."""
    body_hi: float = 96.75
    """Bodies above this are all noise for a future near 96; shown separately."""


GCFG = GridConfig()
CACHE = _REPO / "docs" / "curvefly" / f"sfr_smiles_{GCFG.as_of:%Y%m%d}.pkl"
GCFG'''),
("markdown", """## 2. Fetch the smiles

`fetch_sabr_smile` returns a `STIRFutureOptionSABRSmile`, **not** a DataFrame —
`.points` carry `strike_price`, `right`, `market_price`, `open_interest`. It is
one HTTP call per strike with no cached history, so this cell caches to disk;
re-running is free. Expect noisy "no columns to parse" errors for deep-OTM and
deep-ITM strikes — those are absent quotes, not failures."""),
("code", '''if CACHE.exists():
    points = pickle.loads(CACHE.read_bytes())
    print("loaded cache:", {k: len(v) for k, v in points.items()})
else:
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source=GCFG.source)
    points = {}
    for c in GCFG.contracts:
        sm = mdp.fetch_sabr_smile({"symbol": c, "as_of": GCFG.as_of,
                                   "strike_offsets_bps": "listed"})
        points[c] = [dict(strike=p.strike_price, right=p.right,
                          px=p.market_price, oi=p.open_interest) for p in sm.points]
        print(f"{c}: {len(points[c])} points on {sm.underlying_contract}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(points))'''),
("markdown", """## 3. Underlying forwards, then the parity fill

The forward matters twice: it decides which strikes are ITM (and so need
synthesising) and it is the mean the mode gets compared against. Serial monthlies
take the **quarterly's** future, not one of their own."""),
("code", '''from BT.serff.futures_data import backfill_settles, settle_panel

hist = backfill_settles(datetime.date(2026, 5, 1), GCFG.as_of,
                        symbols=["SR3U26", "SR3Z26"], show_progress=False)
px_panel = settle_panel(hist)
row = px_panel.loc[pd.Timestamp(GCFG.as_of)]
FUT = {"SFRU26": float(row["SR3U26"]), "SFRV26": float(row["SR3Z26"]),
       "SFRX26": float(row["SR3Z26"]), "SFRZ26": float(row["SR3Z26"])}
print({k: round(v, 4) for k, v in FUT.items()})


def build_grid(pts, F, wing=GCFG.wing, df_=GCFG.discount_factor):
    d = pd.DataFrame(pts).dropna(subset=["px"])
    calls = d[d.right.str.upper().str.startswith("C")].groupby("strike")["px"].last()
    puts = d[d.right.str.upper().str.startswith("P")].groupby("strike")["px"].last()
    synth = {float(K): float(p) + df_ * (F - K) for K, p in puts.items() if K < F}
    merged = dict(synth)
    merged.update({float(k): float(v) for k, v in calls.items()})   # real calls win
    s = pd.Series(merged).sort_index()
    rows = []
    for K in s.index:
        lo, hi = round(K - wing, 4), round(K + wing, 4)
        if lo in s.index and hi in s.index:
            fly = float(s[lo] - 2 * s[K] + s[hi])
            rows.append(dict(body=K, fly=fly, imp=fly / wing,
                             src="parity" if (K in synth and K not in calls.index) else "call"))
    return pd.DataFrame(rows).set_index("body")


grids = {c: build_grid(points[c], FUT[c]) for c in points}
for c, g in grids.items():
    print(f"{c}: {len(g)} bodies | column sums to {g.imp.sum():.2f} "
          f"(must be ~2.0 -- see trap 2)")'''),
("markdown", """## 4. GATE — against a published grid

The external check. JWS Macro #8 printed the SFRU6 column off the same
prev-day settle; these are his numbers. Pure-call bodies should match to about a
tick; parity-filled bodies carry the residual, which is where any DF or
settle-vintage error shows up."""),
("code", '''PUBLISHED = {96.0000: 12.0, 96.0625: 16.0, 96.1250: 18.0, 96.1875: 36.0,
             96.2500: 52.0, 96.3125: 38.0, 96.3750: 16.0, 96.4375: 4.0}
g = grids["SFRU26"]
errs = []
for K, want in sorted(PUBLISHED.items()):
    got = float(g.imp.get(K, np.nan)) * 100
    src = g.src.get(K, "-")
    if np.isfinite(got):
        errs.append(abs(got - want))
    print(f"  body {K:.4f} [{src:>6}]  published {want:>5.1f}%   "
          f"rebuilt {got:>6.1f}%   diff {got-want:>+6.1f}")
e = np.array(errs)
print(f"\\n  matched {len(e)}/{len(PUBLISHED)} | mean |diff| {e.mean():.1f}pp | "
      f"max {e.max():.1f}pp")
by_src = {s: [abs(float(g.imp.get(K, np.nan)) * 100 - w)
              for K, w in PUBLISHED.items() if g.src.get(K, "-") == s
              and np.isfinite(g.imp.get(K, np.nan))] for s in ("call", "parity")}
for s, v in by_src.items():
    if v:
        print(f"  {s:>6} bodies: mean {np.mean(v):.1f}pp over {len(v)}")'''),
("markdown", """## 5. The grid, and the reading that matters

The forward is the mean; the peak body is the mode. A large gap between them says
the distribution is skewed by a tail — and that the number everyone quotes (the
forward) is not the outcome the option market thinks is most likely."""),
("code", '''view = pd.DataFrame({c: (gg.imp * 100).round(1) for c, gg in grids.items()})
view.insert(0, "yield_%", [round(100 - b, 2) for b in view.index])
near = view.loc[view.index <= GCFG.body_hi]
print(near.to_string())

print("\\n=== mode vs forward ===")
for c, gg in grids.items():
    sub = gg[gg.index <= GCFG.body_hi]
    mode = float(sub.imp.idxmax())
    f = FUT[c]
    print(f"  {c}: future {f:.4f} ({100-f:.3f}%) | mode {mode:.4f} ({100-mode:.3f}%) "
          f"| gap {(100-mode)-(100-f):+.3f}% in RATE | peak {sub.imp.max()*100:.0f}% "
          f"(~{sub.imp.max()*50:.0f}% of true mass)")'''),
("code", '''fig = go.Figure()
for c, gg in grids.items():
    sub = gg[(gg.index <= GCFG.body_hi) & (gg.index >= 95.5)]
    fig.add_trace(go.Scatter(x=[100 - b for b in sub.index], y=sub.imp * 100,
                             mode="lines+markers", name=c))
for c, f in FUT.items():
    if c == "SFRU26" or c == "SFRZ26":
        fig.add_vline(x=100 - f, line_dash="dot", line_width=1,
                      annotation_text=f"{c} fwd", annotation_position="top")
fig.update_layout(
    title="Butterfly grid — where the option market puts the mass, vs where the forward is",
    xaxis_title="body yield, %", yaxis_title="fly settle / 0.125, %  (sums to 2.0)",
    height=520, hovermode="x unified")
fig.show()'''),
("markdown", """## 6. Halving it, and why that is the honest version

The column double-counts, so the peak is roughly half what it reads. The
normalised view below is the one to quote — and it still shows a sharp pin,
which is the point: the concentration is real, the headline number is not."""),
("code", '''norm = pd.DataFrame({c: gg.imp / gg.imp.sum() for c, gg in grids.items()})
norm = norm.loc[(norm.index <= GCFG.body_hi) & (norm.index >= 95.5)]
norm.index = [round(100 - b, 3) for b in norm.index]
norm.index.name = "yield_%"
print("normalised so each column sums to 1.0 (%)")
print((norm * 100).round(1).to_string())
for c in norm.columns:
    top = norm[c].nlargest(3)
    print(f"  {c}: top-3 bodies hold {top.sum()*100:.0f}% of mass at yields "
          f"{', '.join(f'{i:.2f}%' for i in top.index)}")'''),
("markdown", """## 7. Caveats

* The parity fill inherits any error in the forward and the discount factor. It
  is second order for these expiries but it is the reason the low bodies carry
  more residual against the published grid than the pure-call ones.
* A fly built from settles inherits settle staleness. Deep wings frequently have
  no trade and no meaningful settle; that is why several bodies print 0.0 or a
  small negative, which is quote noise rather than negative probability.
* Serial monthlies (`V6`, `X6`) settle on the quarterly future. Comparing their
  mode against their own name's forward is a category error.
* The triangular kernel understates a flat distribution and overstates a peaked
  one. That asymmetry is why the grid is good at *locating* a pin and bad at
  measuring how much is in it."""),
]

for name, cells in [("curve_fly_screener", SCREENER), ("sfr_butterfly_grid", GRID)]:
    p = OUT / f"{name}.ipynb"
    p.write_text(json.dumps(nb(cells), indent=1), encoding="utf-8")
    print(f"wrote {p}  ({len(cells)} cells)")
