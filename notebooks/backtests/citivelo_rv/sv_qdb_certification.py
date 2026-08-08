# %% [markdown]
# # QueryDrivenBacktest certification — the ultra-long forward flattener
#
# The loop's design doc reserves the daily-MTM **QueryDrivenBacktest** pass for
# certification: a headline is only certifiable if the production engine
# reproduces the panel engine within stated tolerance (the SERFF pattern,
# corr ≥ 0.97). Session 1 killed every candidate before this stage; the user
# asked for the pass to be **run anyway** — so this notebook certifies the
# PIPELINE on the always-on USD 10y10y/20y10y flattener, the structure every
# SV verdict was built on.
#
# What this exercises, deliberately:
# - the **signed-bpv seam fix** (ledger L-0012): buy/sell must mirror through
#   the engine — the planted-answer test runs live in this notebook;
# - forward-starting legs through `IRSwapQuery` OUTRIGHT with the
#   ``"20Yx10Y"`` shorthand, marked by `IRSwapsMDP(source="CITIVELO_EXCEL")`
#   off the warmed CurveStore (offline; no Excel path reachable);
# - annual rolls as unwind+re-add with **distinct tags per segment** (unwinds
#   process after fills in the same step — one shared tag would close the
#   fresh package on the roll day);
# - the engine-vs-panel tie-out against the sv `replication.simulate` ledger
#   run **hedge-disabled** (trigger out of reach) on the same curves — the
#   QDB book carries no intra-segment resizes, so the comparable is the
#   unhedged aged package, and both books are GROSS (costs applied identically
#   to both afterward as the registered flat roll fee).
#
# Scope: 2022-01-03 → 2026-08-06 (hiking + cutting regimes, ~1,140 stored
# days). Ghost days are excluded on both sides by the reference-date filter.
# Heavy cells are run-or-load: artifacts persist to
# ``notebooks/data/citivelo_rv/qdb_cert_*.parquet`` and re-execution loads.

# %%
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3] if "__file__" in dir() else pathlib.Path.cwd().parents[2]
sys.path.insert(0, str(_REPO))

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
CURVE = "USD-SOFR-1D"
PKG_DV01 = 100_000.0
START, END = datetime.date(2022, 1, 3), datetime.date(2026, 8, 6)
ROLL_MONTHS = 12
RT_BP = 1.5  # registered round trip per roll cycle (Citi Fig-9 initiation x2)

# %% [markdown]
# ## 1. The planted-answer sign test, live
#
# 2022-09 CPI week: rates rose ~23bp. A payer (+bpv) must gain; ±bpv must
# mirror exactly. This ran the day the seam was fixed; it runs again on every
# execution of this notebook so the certification can never silently rest on
# a regressed engine.

# %%
def _run_sign_probe(bpv: float) -> float:
    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])
    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                    tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv},
                    tags=("probe",))
    strat = QueryStrategy(name=f"sign_{bpv:+.0f}", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
    ])
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp)
    bt.run()
    return float(pd.Series(bt.mtm_history).iloc[-1])


plus, minus = _run_sign_probe(+PKG_DV01), _run_sign_probe(-PKG_DV01)
print(f"+bpv {plus:+,.0f}  -bpv {minus:+,.0f}")
assert plus > 0, "payer must gain in the 2022-09 selloff"
assert abs(plus + minus) < 1e-6 * abs(plus), "buy/sell must mirror — seam regressed?"
print("SIGN TEST PASS: mirror exact, payer gains")

# %% [markdown]
# ## 2. The engine run — annual-roll flattener through QueryDrivenBacktest
#
# Pay 10Yx10Y (+$100k/bp), receive 20Yx10Y (−$100k/bp), re-struck at each
# roll anniversary via unwind(tag_k) + add(tag_{k+1}) on the same step. The
# registered fee (1.5bp × DV01 per cycle) is charged at each unwind; the
# GROSS series used for the tie-out strips it back out (both books gross).

# %%
def stored_days() -> list:
    from RVUtils.StrikelessVol.citivelo import stored_dates

    return stored_dates("USD", START, END)


def roll_bounds(days: list) -> list:
    bounds, i = [], 0
    while i < len(days) - 1:
        due = pd.Timestamp(days[i]) + pd.DateOffset(months=ROLL_MONTHS)
        j = i + 1
        while j < len(days) - 1 and pd.Timestamp(days[j]) < due:
            j += 1
        bounds.append((i, j))
        i = j
    return bounds


def run_qdb() -> pd.DataFrame:
    days = stored_days()
    segs = roll_bounds(days)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    triggers = []
    for k, (i, j) in enumerate(segs):
        tag = f"fl{k}"
        legs = [
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor="10Yx10Y", curve=CURVE,
                        structure_kwargs={"bpv": +PKG_DV01}, tags=(tag,)),
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor="20Yx10Y", curve=CURVE,
                        structure_kwargs={"bpv": -PKG_DV01}, tags=(tag,)),
        ]
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[days[i]]),
            actions=[AddQueryAction(query=q, meta={"tags": [tag]}) for q in legs]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[days[j]]),
            actions=[UnwindPositionsAction(match_tag=tag, fee=RT_BP * PKG_DV01)]))
    grid = TimeGrid([pd.Timestamp(d) for d in days])
    strat = QueryStrategy(name="sv_flattener_cert", triggers=triggers)
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    print(f"engine: {len(eq)} marks in {time.time() - t0:.0f}s, "
          f"{len(segs)} roll segments")
    missing = set(pd.Timestamp(d) for d in days) - set(eq.index)
    assert not missing, f"equity-curve holes (engine swallowed steps): {sorted(missing)[:3]}"
    out = eq.to_frame("equity_usd")
    out["fees_cum"] = 0.0
    fee_days = [pd.Timestamp(days[j]) for _, j in segs]
    fees = pd.Series(0.0, index=out.index)
    fees.loc[fees.index.isin(fee_days)] = RT_BP * PKG_DV01
    out["fees_cum"] = fees.cumsum()
    out["equity_gross_usd"] = out["equity_usd"] + out["fees_cum"]
    return out


ART = DATA / "qdb_cert_engine.parquet"
if ART.exists():
    engine = pd.read_parquet(ART)
    print(f"loaded {ART.name}: {engine.shape}")
else:
    engine = run_qdb()
    engine.to_parquet(ART)
    print(f"wrote {ART.name}")

# %% [markdown]
# ## 3. The panel comparable — sv `simulate`, hedge-disabled, same curves
#
# `CurvePricer` + `simulate` per roll segment with the resize trigger out of
# reach (no intra-segment hedges → the same unhedged aged package the QDB
# holds), stitched with flows summed on shared boundary dates. Ghost days
# drop on both sides via the reference-date filter.

# %%
def run_panel() -> pd.Series:
    import logging

    logging.disable(logging.WARNING)
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, citivelo_pairs
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer, ReplicationConfig, simulate

    pair = next(p for p in citivelo_pairs(["USD"]) if p.name == "USD 10Y10Y/20Y10Y")
    days = stored_days()
    segs = roll_bounds(days)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    free = CostSchedule(multiplier=0.0)
    cfg = ReplicationConfig(trigger_bp=1e9, roll_months=1200,
                            package_dv01_usd=PKG_DV01)
    pieces = []
    t0 = time.time()
    for k, (i, j) in enumerate(segs):
        seg_days = days[i:j + 1]
        cm = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES["USD"],
                                "timestamps": seg_days, "offline": True})
        def _ok(ts, c):
            if c is None:
                return False
            ref = c.reference_date()
            rd = ref.date() if hasattr(ref, "date") else ref
            td = ts.date() if hasattr(ts, "date") else ts
            return rd == td
        cm = {ts: c for ts, c in cm.items() if _ok(ts, c)}
        ctx = CurvePricer(cm, pair, package_dv01_usd=PKG_DV01)
        led = simulate(ctx, ctx.dates(), cfg, free)
        pieces.append(led[["carry", "harvest", "mtm", "cross"]].sum(axis=1))
        print(f"  seg {k + 1}/{len(segs)} ({time.time() - t0:.0f}s)")
    stacked = pd.concat(pieces)
    daily = stacked.groupby(level=0).sum()
    return daily.sort_index()


ART2 = DATA / "qdb_cert_panel.parquet"
if ART2.exists():
    panel_daily = pd.read_parquet(ART2)["pnl"]
    panel_daily.index = pd.to_datetime(panel_daily.index)
    print(f"loaded {ART2.name}: {len(panel_daily)}")
else:
    panel_daily = run_panel()
    panel_daily.to_frame("pnl").to_parquet(ART2)
    print(f"wrote {ART2.name}")

# %% [markdown]
# ## 4. The tie-out — the certification verdict
#
# Daily engine P&L (gross equity diff) vs the panel's daily flows, aligned on
# common days; roll-boundary steps carry the re-strike on both sides. Bar:
# **corr ≥ 0.97** (SERFF), terminal gap reported in bp of package DV01.

# %%
eng_daily = engine["equity_gross_usd"].diff().dropna()
j = pd.DataFrame({"engine": eng_daily, "panel": panel_daily}).dropna()
corr = float(j["engine"].corr(j["panel"]))
term_gap_bp = float((j["engine"].sum() - j["panel"].sum()) / PKG_DV01)
mad_bp = float((j["engine"] - j["panel"]).abs().median() / PKG_DV01)
print(f"common days {len(j)}, corr {corr:.4f}, terminal gap {term_gap_bp:+.2f}bp, "
      f"median |daily diff| {mad_bp:.4f}bp")
verdict = {
    "window": f"{START}..{END}",
    "n_common_days": int(len(j)),
    "daily_corr": corr,
    "terminal_gap_bp": term_gap_bp,
    "median_abs_daily_diff_bp": mad_bp,
    "engine_gross_bp": float(j["engine"].sum() / PKG_DV01),
    "panel_gross_bp": float(j["panel"].sum() / PKG_DV01),
    "net_at_registered_fee_bp": float((engine["equity_usd"].iloc[-1]) / PKG_DV01),
    "bar": "corr >= 0.97",
    "pass": bool(corr >= 0.97),
}
(DATA / "qdb_cert_verdict.json").write_text(json.dumps(verdict, indent=1))
print(json.dumps(verdict, indent=1))
assert verdict["pass"], "certification tie-out FAILED the SERFF bar"
print("CERTIFICATION TIE-OUT PASS")

# %% [markdown]
# ## 5. What this does and does not certify
#
# Certifies: the production daily-MTM path (store-served Citi curves →
# `IRSwapQuery` forward legs → engine bookkeeping) reproduces the panel
# engine every SV verdict was graded on, with correct direction semantics,
# no equity-curve holes, and rolls handled as real unwind/re-strike events.
#
# Does **not** certify a strategy: every registered hypothesis on this
# structure is DEAD (ledger V-SV-13F, V-SV-14G-KILL, V-SV-16, V-SV-16B) and
# nothing here reopens them. The engine number at the registered fee is the
# always-on control's economics, already known un-ALIVE at the family DSR.
