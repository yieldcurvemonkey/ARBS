# %% [markdown]
# # H14 manufactured package — the QueryDrivenBacktest implementation
#
# Backlog item (b) of the standing rule. H14G is **DEAD, and dead by a checker's
# hand**: `V-SV-14G-KILL` found that the committed fly ledger *double-counted
# carry* — `fly_mtm` was the TOTAL PV change (which already realizes carry
# through the par-struck legs) and the expected roll `fly_carry` was added on
# top. Realized fly gross is **+8.8 bp**, not the +40.9 bp the maker reported,
# against 31.0 bp of maintenance: a **−22.2 bp** net contribution at 1×.
#
# That makes this the one backlog item with something to prove rather than
# something to re-express. **A `QueryDrivenBacktest` book cannot double-count
# carry.** Its equity is marked-to-market daily; the change in equity *is* the
# total PV change, once, with carry realized inside it and no separate carry
# bucket to add. So if the engine's fly book reproduces `fly_mtm` **alone**, the
# production engine has independently re-derived the checker's kill from a
# different code path — which is a far stronger statement than the maker
# agreeing with the checker.
#
# Scope: the **fly** only. The flattener side of the package is the structure
# `sv_qdb_certification` already certified end-to-end (`L-0045`, corr 0.9991),
# and re-running it here would add nothing.
#
# The 2-7-30 fly is three 1y-forward par swaps at PCA-solved weights, re-solved
# at the flattener's own 25 bp hedge-trigger days and at annual roll boundaries.
# The **solve schedule is taken from the committed artifact** — it is the graded
# strategy's own schedule, including its known omission (the checker found ~14
# re-initiations lost to `as_completed` dedup nondeterminism, in the direction
# that flatters the fly's maintenance bill). The **weights are re-derived**,
# because the artifact stores only |ΔDV01| per solve and never the levels; the
# re-derivation is reconciled against those deltas in section 3 rather than
# trusted.

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
sys.path.insert(0, str(_REPO / "scripts"))

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
PAIR_NAME = "USD 10Y10Y/20Y10Y"
PKG_DV01 = 100_000.0
FLY_TENORS = ("2Y", "7Y", "30Y")
FLY_FWD = "1Y"
PCA_WIN = 756
GRID = ["2Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"]
PCA_W = (1.0, 1.0, 1.0) + (0.0,) * (len(GRID) - 3)

# %% [markdown]
# ## 1. The planted-answer sign test, live
#
# The 2022-09 CPI week: a payer must gain, ±bpv must mirror. The fly's legs are
# signed by a solver, so a regressed direction seam would not announce itself
# anywhere else in this notebook.

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
# ## 2. The committed ledger, and the convention it is stored in
#
# **Read this before using `h14_fly_ledger_USD.parquet` for anything.** The
# artifact on disk is the **pre-fix** one: `fly_mtm` holds the total PV change
# and `fly_carry` the expected roll, and `V-SV-14G-KILL` is the statement that
# adding them double-counts. The *script* was subsequently repaired (commit
# `f362eac4`: `carry = rolled − pv`, `mtm = (pv − prev_pv) − carry`, so the two
# sum to the realized total once) but **was never re-run**, so code and artifact
# now disagree about what the columns mean. Re-running the script would produce
# a parquet in which `fly_mtm + fly_carry` *is* correct — the opposite of the
# file sitting here.
#
# This notebook therefore ties out against **`fly_mtm` alone**, and prints both
# readings so the discrepancy is visible rather than inferred.

# %%
fly_led = pd.read_parquet(DATA / "h14_fly_ledger_USD.parquet")
fly_led.index = pd.to_datetime(fly_led.index)
units = pd.read_parquet(DATA / "h13_units_USD.parquet").xs(PAIR_NAME, level="pair")
units.index = pd.to_datetime(units.index)
DV_MEAN = float((units["long_notional"].abs() * units["dv01_long_unit"])
                .replace(0, np.nan).mean())

trade_cols = [f"trade_{t}" for t in FLY_TENORS]
solve_mask = fly_led[trade_cols].fillna(0.0).sum(axis=1) > 0
SOLVE_DAYS = list(fly_led.index[solve_mask])
print(f"dv01 normaliser ${DV_MEAN:,.0f}/bp, {len(SOLVE_DAYS)} committed solves, "
      f"{len(fly_led)} ledger days")
print(f"committed fly_mtm        {fly_led['fly_mtm'].fillna(0).sum() / DV_MEAN:+7.2f} bp "
      "  <- realized total PV change (the checker's number)")
print(f"committed fly_carry      {fly_led['fly_carry'].fillna(0).sum() / DV_MEAN:+7.2f} bp "
      "  <- expected roll, already inside fly_mtm")
print(f"committed sum (as graded){fly_led[['fly_mtm', 'fly_carry']].fillna(0).sum().sum() / DV_MEAN:+7.2f} bp "
      "  <- the double count V-SV-14G-KILL removed")

# %% [markdown]
# ## 3. Re-deriving the solved weights, and reconciling them
#
# `fly_hedge_weights` returns `weights_bpv` — signed dollars per bp per leg — as
# a deterministic function of the day's curve and the trailing 756-day PCA fit.
# The committed ledger stores only `|ΔDV01|` per leg per solve, never the
# levels, so the levels have to be recomputed and then **reconciled against
# those deltas**. That reconciliation is the planted-answer test for this
# notebook: it decides whether the re-derived weight path is the graded one or
# merely a lookalike.
#
# Each committed trade volume must be one of exactly two things off the
# re-derived level path: `|L_d − L_prev|` if the solve was an **adjustment**, or
# `L_d` if it was a **re-initiation** (a fresh basket, `old = 0`, which is what
# each annual segment start was). Both readings are tested, at floating-point
# equality rather than a tolerance — 200-odd independent PCA solves do not agree
# to the last bit by accident.
#
# Weights are also solved at the 22 annual segment starts whether or not the
# ledger has a row there, because section 3b needs the levels the graded run
# used at boundaries it did not record.

# %%
def solve_weights() -> pd.DataFrame:
    import logging

    logging.disable(logging.WARNING)
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, CITIVELO_SOURCE
    from RVUtils.StrikelessVol.constructions import fly_hedge_weights
    from RVUtils.StrikelessVol.citivelo import citivelo_pairs
    from RVUtils.StrikelessVol.greeks import _reprice_dv01, build_package
    from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries

    par = pd.read_parquet(DATA / "par_grid_USD_SOFR.parquet")[GRID].dropna(how="any")
    par.index = pd.to_datetime(par.index)
    pair = next(p for p in citivelo_pairs(["USD"]) if p.name == PAIR_NAME)
    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    curves = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES["USD"],
                                "timestamps": WANTED_DAYS, "offline": True})

    def _ok(ts, c):
        if c is None:
            return False
        ref = c.reference_date()
        rd = ref.date() if hasattr(ref, "date") else ref
        td = ts.date() if hasattr(ts, "date") else ts
        return rd == td

    curves = {pd.Timestamp(ts): c for ts, c in curves.items() if _ok(ts, c)}
    rows, t0 = [], time.time()
    for n, d in enumerate(WANTED_DAYS):
        curve = curves.get(pd.Timestamp(d))
        if curve is None:
            rows.append({"date": d, "err": "ghost/missing curve"})
            continue
        try:
            model, _ = fit_curve_pca_from_timeseries(par.loc[:d].tail(PCA_WIN))
            pkg = build_package(curve, pair, package_dv01_usd=PKG_DV01)
            fly = fly_hedge_weights(curve, pkg, pca_model=model,
                                    fly_tenors=FLY_TENORS, fly_fwd=FLY_FWD,
                                    pca_weights=PCA_W)
        except Exception as exc:  # noqa: BLE001 — a failed solve is data
            rows.append({"date": d, "err": f"{type(exc).__name__}: {exc}"[:80]})
            continue
        row = {"date": d, "belly_dir": fly["belly_direction"], "err": None}
        for t in FLY_TENORS:
            row[f"bpv_{t}"] = float(fly["weights_bpv"][t])
            row[f"dv01_{t}"] = abs(float(_reprice_dv01(curve, fly["legs"][t])))
        rows.append(row)
        if (n + 1) % 25 == 0:
            print(f"  solve {n + 1}/{len(WANTED_DAYS)} ({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows).set_index("date")


# %%
from sv_static_long_control import roll_segments
from RVUtils.StrikelessVol.citivelo import stored_dates

_days = stored_dates("USD")
_segs = roll_segments(_days, 12)
SEG_STARTS = [pd.Timestamp(_days[i]) for (i, _) in _segs]
WANTED_DAYS = sorted(set(SOLVE_DAYS) | set(SEG_STARTS))
print(f"{len(_segs)} annual segments; solving at {len(WANTED_DAYS)} days "
      f"({len(SOLVE_DAYS)} ledger solves + {len(set(SEG_STARTS) - set(SOLVE_DAYS))} "
      "segment starts the ledger has no row for)")

ART_W = DATA / "h14_qdb_weights.parquet"
if ART_W.exists():
    W = pd.read_parquet(ART_W)
    W.index = pd.to_datetime(W.index)
    print(f"loaded {ART_W.name}: {W.shape}")
else:
    W = solve_weights()
    W.to_parquet(ART_W)
    print(f"wrote {ART_W.name}")
print(f"solve errors: {int(W['err'].notna().sum())}; "
      f"belly received on {int((W['belly_dir'] == 'received').sum())}/{len(W)} solves")

# %%
def _err(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1.0)


recon, prev = [], {t: 0.0 for t in FLY_TENORS}
for d in SOLVE_DAYS:
    if W.loc[d, "err"] is not None and not pd.isna(W.loc[d, "err"]):
        continue
    lvl = {t: float(W.loc[d, f"dv01_{t}"]) for t in FLY_TENORS}
    com = {t: float(fly_led.loc[d, f"trade_{t}"]) for t in FLY_TENORS}
    e_reinit = max(_err(lvl[t], com[t]) for t in FLY_TENORS)
    e_adjust = max(_err(abs(lvl[t] - prev[t]), com[t]) for t in FLY_TENORS)
    kind = ("re-initiation" if e_reinit <= e_adjust else "adjustment")
    recon.append({"date": d, "kind": kind, "err": min(e_reinit, e_adjust),
                  "committed_2Y": com["2Y"], "level_2Y": lvl["2Y"]})
    prev = lvl
recon = pd.DataFrame(recon).set_index("date")
EXACT = recon["err"] < 1e-9
print(f"{int(EXACT.sum())} of {len(recon)} committed solves reproduce to "
      f"FLOATING-POINT EQUALITY off the re-derived level path "
      f"({int((recon['kind'] == 'adjustment')[EXACT].sum())} adjustments, "
      f"{int((recon['kind'] == 're-initiation')[EXACT].sum())} re-initiations)")
print(f"unexplained: {int((~EXACT).sum())}")
assert int(EXACT.sum()) >= 0.9 * len(recon), (
    "the re-derived weight path does not reproduce the committed trade volumes — "
    "nothing below is about H14")
print("WEIGHT RECONCILIATION PASS: the re-derived solve path is the graded one")

# %% [markdown]
# ### 3b. The 14 missing re-initiations, named
#
# The checker found that "~14 re-initiations [were] lost to `as_completed` dedup
# nondeterminism at segment boundaries", flattering the fly's maintenance bill.
# The reconciliation above pins that number exactly and without appealing to the
# checker's reasoning, because it counts from two independent directions that
# have to agree:
#
# * there are **22** annual segments, so there should be **22** re-initiations;
# * the ledger contains re-initiation rows for only some of them;
# * every solve the level path fails to explain is the **first solve following a
#   segment start whose re-initiation row is absent** — because the graded run
#   *did* re-initialise there (setting its `held_dv01`) and only the ledger row
#   was dropped, so the next delta is measured from a level this replay never
#   sees.
#
# The two counts are asserted to agree and to pair 1:1 by year. Then the missing
# bill is priced: those baskets were genuinely traded, so their DV01 belongs in
# the maintenance total.

# %%
# Per SEGMENT, not per date: a re-initiation row can land a day or two after the
# analytic boundary when the boundary day itself is a holiday ghost (2007's is at
# 01-05, not 01-03). The question for each segment is simply whether the FIRST
# ledger solve at or after its start is a re-initiation.
unexplained = list(recon.index[~EXACT])
recorded, missing_starts, first_after = [], [], {}
for s in SEG_STARTS:
    nxt = next((d for d in recon.index if d >= s), None)
    if nxt is None:
        continue
    first_after[s] = nxt
    (recorded if (EXACT[nxt] and recon.loc[nxt, "kind"] == "re-initiation")
     else missing_starts).append(s)
print(f"segments {len(SEG_STARTS)}: re-initiation recorded for {len(recorded)}, "
      f"absent for {len(missing_starts)}; unexplained solves {len(unexplained)}")
paired = [(s, first_after[s]) for s in missing_starts if first_after[s] in unexplained]
print(f"each missing boundary pairs with the first solve after it: "
      f"{len(paired)}/{len(missing_starts)}")
for s, u in paired[:5]:
    print(f"  segment start {s.date()} (no re-init row) -> unexplained solve {u.date()}")
assert len(paired) == len(missing_starts) == len(unexplained), (
    "the missing-re-initiation account does not close: "
    f"{len(missing_starts)} missing vs {len(unexplained)} unexplained")

from RVUtils.cost_model import transaction_cost_bps

HS = {t: transaction_cost_bps({"2Y": 2, "7Y": 7, "30Y": 30}[t], 1.0) for t in FLY_TENORS}
missing_bill_usd = 0.0
for s in missing_starts:
    if s not in W.index or (W.loc[s, "err"] is not None and not pd.isna(W.loc[s, "err"])):
        continue
    missing_bill_usd += sum(abs(float(W.loc[s, f"dv01_{t}"])) * HS[t] for t in FLY_TENORS)
MISSING_BILL_BP = missing_bill_usd / DV_MEAN
print(f"\nthe {len(missing_starts)} unrecorded re-initiations are worth "
      f"{MISSING_BILL_BP:+.2f} bp of maintenance at 1x that the graded bill never charged")

# %% [markdown]
# ## 4. The engine run — the fly as a held, re-solved book
#
# Three `IRSwapQuery` legs at `1Yx2Y` / `1Yx7Y` / `1Yx30Y`, sized to the solved
# signed bpv, re-struck at each solve as unwind(tag_k) + add(tag_{k+1}) on the
# same step with distinct tags. Costs are deliberately **not** charged in the
# engine: the maintenance bill is the committed artifact's, taken unchanged in
# section 6, so the engine number is a clean gross and the two are not mixed.

# %%
def run_engine(variant: str) -> pd.DataFrame:
    """``ledger`` re-strikes only where the artifact has a row; ``full`` also
    re-strikes at the 14 segment starts whose rows the dedup dropped — which is
    what the graded run actually held."""
    ok = W[W["err"].isna()]
    wanted = SOLVE_DAYS if variant == "ledger" else sorted(set(SOLVE_DAYS) | set(SEG_STARTS))
    solves = [d for d in wanted if d in ok.index]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    grid_days = [d for d in fly_led.index if d >= solves[0]]
    triggers = []
    for k, d in enumerate(solves):
        tag = f"fly{k}"
        end = solves[k + 1] if k + 1 < len(solves) else grid_days[-1]
        legs = [
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor=f"{FLY_FWD}x{t}", curve=CURVE,
                        structure_kwargs={"bpv": float(ok.loc[d, f"bpv_{t}"])},
                        tags=(tag,))
            for t in FLY_TENORS
        ]
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[pd.Timestamp(d).date()]),
            actions=[AddQueryAction(query=q, meta={"tags": [tag]}) for q in legs]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[pd.Timestamp(end).date()]),
            actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]))
    grid = TimeGrid([pd.Timestamp(d) for d in grid_days])
    strat = QueryStrategy(name=f"h14_fly_hold_{variant}", triggers=triggers)
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    print(f"engine[{variant}]: {len(eq)} marks, {len(solves)} solves, {time.time() - t0:.0f}s")
    missing = set(pd.Timestamp(d) for d in grid_days) - set(eq.index)
    assert not missing, f"equity-curve holes: {sorted(missing)[:3]}"
    n_closed = len(getattr(bt.portfolio, "closed_positions_log", []) or [])
    n_live = int((eq.abs() > 1e-9).sum())
    print(f"  closed legs {n_closed}, non-zero marks {n_live}")
    # The H13 notebook's lesson: a book whose triggers never fired also has no
    # holes and no NaNs, and every mark exactly zero.
    assert n_live > 0, "engine equity is identically zero — no trigger fired"
    assert n_closed >= 3 * len(solves) - 3, f"expected ~{3 * len(solves)} closed legs, got {n_closed}"
    return eq.to_frame("equity_usd")


ENGINE = {}
for _v in ("ledger", "full"):
    _art = DATA / f"h14_qdb_engine_{_v}.parquet"
    if _art.exists():
        ENGINE[_v] = pd.read_parquet(_art)
        ENGINE[_v].index = pd.to_datetime(ENGINE[_v].index)
        print(f"loaded {_art.name}: {ENGINE[_v].shape}")
    else:
        ENGINE[_v] = run_engine(_v)
        ENGINE[_v].to_parquet(_art)
        print(f"wrote {_art.name}")
engine = ENGINE["full"]

# %% [markdown]
# ## 5. The tie-out — and the checker's kill, re-derived
#
# The engine's daily equity change is the fly book's total PV change. Against
# the committed ledger it must track **`fly_mtm`**, not `fly_mtm + fly_carry`.
#
# **Correlation cannot decide this and is not asked to.** `fly_carry` is a
# smooth ~0.006 bp/day drift, so both readings correlate at ~0.995 with anything
# that tracks the fly at all. The statistic that discriminates is the **terminal
# level**: one reading is a few bp away and the other is tens.

# %%
def compare(eq: pd.Series) -> dict:
    d = eq.diff().dropna()
    c = pd.DataFrame({
        "engine": d,
        "fly_mtm": fly_led["fly_mtm"].fillna(0.0),
        "fly_mtm_plus_carry": fly_led[["fly_mtm", "fly_carry"]].fillna(0.0).sum(axis=1),
    }).dropna()
    return {"n": int(len(c)),
            "corr_mtm": float(c["engine"].corr(c["fly_mtm"])),
            "corr_both": float(c["engine"].corr(c["fly_mtm_plus_carry"])),
            "eng_bp": float(c["engine"].sum() / DV_MEAN),
            "mtm_bp": float(c["fly_mtm"].sum() / DV_MEAN),
            "both_bp": float(c["fly_mtm_plus_carry"].sum() / DV_MEAN)}


CMPS = {v: compare(ENGINE[v]["equity_usd"]) for v in ("ledger", "full")}
for v, r in CMPS.items():
    print(f"[{v:6s}] {r['n']} days   engine {r['eng_bp']:+7.2f} bp"
          f"   vs fly_mtm {r['mtm_bp']:+6.2f} (gap {r['eng_bp'] - r['mtm_bp']:+6.2f}, "
          f"corr {r['corr_mtm']:.4f})"
          f"   vs fly_mtm+carry {r['both_bp']:+6.2f} (gap {r['eng_bp'] - r['both_bp']:+6.2f}, "
          f"corr {r['corr_both']:.4f})")

R = CMPS["full"]
corr_mtm, corr_both = R["corr_mtm"], R["corr_both"]
eng_bp, mtm_bp, both_bp = R["eng_bp"], R["mtm_bp"], R["both_bp"]
assert corr_mtm >= 0.97, f"engine does not track the fly at all: corr {corr_mtm:.4f}"
assert abs(eng_bp - mtm_bp) < abs(eng_bp - both_bp) / 3, (
    "the engine is not decisively closer to fly_mtm than to fly_mtm + fly_carry")
print(f"\nTIE-OUT PASS: the engine lands {abs(eng_bp - mtm_bp):.2f} bp from fly_mtm "
      f"and {abs(eng_bp - both_bp):.2f} bp from fly_mtm + fly_carry.")
print("A QueryDrivenBacktest book cannot double-count carry — its equity change IS")
print("the total PV change, once — and it lands on the checker's number, not the")
print("maker's. V-SV-14G-KILL is re-derived from an independent code path.")
print(f"\nRestoring the 14 dropped re-strikes moves the engine gross by only "
      f"{CMPS['full']['eng_bp'] - CMPS['ledger']['eng_bp']:+.2f} bp.")
print("That is the useful negative: the dropped rows barely touch the P&L path — a")
print("re-struck basket is close to the one it replaces — so their damage is almost")
print(f"entirely in the COST bill they never charged ({MISSING_BILL_BP:+.2f} bp at 1x).")

# %% [markdown]
# ## 6. The net contribution, at the committed maintenance bill
#
# The maintenance bill is the graded one, taken unchanged from the artifact's
# `trade_*` volumes at `RVUtils/cost_model` half-spreads — including its known
# omission (~14 re-initiations lost to the dedup nondeterminism the checker
# found, all in the direction that **understates** this bill).

# %%
maint_bp, maint_full_bp = {}, {}
for mult in (0.5, 1.0, 2.0):
    maint_bp[mult] = sum(float(fly_led[f"trade_{t}"].fillna(0.0).sum()) * HS[t] * mult
                         for t in FLY_TENORS) / DV_MEAN
    maint_full_bp[mult] = maint_bp[mult] + MISSING_BILL_BP * mult
rows = [{"mult": m,
         "maintenance_bp_as_graded": maint_bp[m],
         "maintenance_bp_with_missing_reinits": maint_full_bp[m],
         "engine_gross_bp": eng_bp,
         "net_contribution_bp": eng_bp - maint_full_bp[m],
         "as_graded_net_bp": both_bp - maint_bp[m]} for m in (0.5, 1.0, 2.0)]
tbl = pd.DataFrame(rows)
print(tbl.to_string(index=False))
print(f"\nper-leg half-spreads (bp): {json.dumps({k: round(v, 4) for k, v in HS.items()})}")

verdict = {
    "scope": "the 2-7-30 fly leg only; the flattener is certified in L-0045",
    "n_committed_solves": len(SOLVE_DAYS),
    "n_engine_solves": int(W["err"].isna().sum()),
    "n_solves_reproduced_exactly": int(EXACT.sum()),
    "tie_out": {"n_common_days": R["n"],
                "corr_vs_fly_mtm": corr_mtm,
                "corr_vs_fly_mtm_plus_carry": corr_both,
                "engine_gross_bp": eng_bp,
                "engine_gross_bp_ledger_solves_only": CMPS["ledger"]["eng_bp"],
                "committed_fly_mtm_bp": mtm_bp,
                "committed_as_graded_bp": both_bp,
                "gap_to_fly_mtm_bp": eng_bp - mtm_bp,
                "gap_to_as_graded_bp": eng_bp - both_bp,
                "bar": "closer to fly_mtm than to fly_mtm+fly_carry by >3x",
                "pass": bool(abs(eng_bp - mtm_bp) < abs(eng_bp - both_bp) / 3)},
    "n_segments": len(SEG_STARTS),
    "n_reinitiations_recorded": int((recon["kind"] == "re-initiation")[EXACT].sum()),
    "n_reinitiations_missing": len(missing_starts),
    "missing_reinit_maintenance_bp_at_1x": MISSING_BILL_BP,
    "maintenance_bp_as_graded": {str(k): v for k, v in maint_bp.items()},
    "maintenance_bp_with_missing_reinits": {str(k): v for k, v in maint_full_bp.items()},
    "engine_net_contribution_bp": {str(m): eng_bp - maint_full_bp[m] for m in (0.5, 1.0, 2.0)},
    "re_expresses": "V-SV-14G-KILL (H14G: mechanism NOT confirmed full-sample; DEAD)",
    "changes_verdict": False,
    "trials_delta": 0,
}
(DATA / "h14_qdb_verdict.json").write_text(json.dumps(verdict, indent=1))
print(json.dumps(verdict, indent=1))

# %% [markdown]
# ## 7. What this does and does not certify
#
# Certifies: the manufactured package's fly leg is expressible in the production
# engine at PCA-solved weights on a replayed solve schedule, the re-derived
# weight path reconciles against the committed artifact's own trade volumes, and
# the engine's daily P&L reproduces `fly_mtm` — **the checker's realized gross,
# not the maker's**. An engine that marks to market daily has no way to add an
# expected roll on top of a total PV change, so this is a structural check on
# the accounting rather than another opinion about it.
#
# Does **not** certify a strategy. H14G is DEAD (`V-SV-14G-KILL`); the fly's net
# contribution is **negative at every cost multiplier** (−5.1 / −23.2 / −59.5 bp
# at 0.5× / 1× / 2×) once the carry is counted once and the unrecorded
# re-initiations are charged, and the gamma-retention figure the maker quoted
# stays retracted (`V-SV-14G-KILL`: no committed computation). No trials are
# consumed and no verdict is reopened.
#
# What this notebook adds to the kill, beyond re-deriving it:
#
# * the checker's "~14 re-initiations" is **exactly 14**, of 22 annual segments,
#   and they are named;
# * they are worth **+5.27 bp** of maintenance at 1× that the graded bill never
#   charged — a number the checker could only sign as "understated";
# * and the engine's own residual gap to `fly_mtm` (+4.2 bp on a +8.8 bp
#   quantity) is honestly large in relative terms. It is the same
#   forward-swap-convention and fresh-vs-aged-leg gap the other two notebooks
#   carry, and it is a fifth of the distance to the maker's reading — enough to
#   settle which accounting is right, not enough to price the fly to the bp.
#
# One live trap recorded rather than repaired: `h14_fly_ledger_USD.parquet` is
# stored in the **pre-fix** convention while `scripts/sv_citivelo_h14_graded.py`
# has been repaired, so re-running the script inverts the meaning of its
# columns. Anything reading that parquet must use `fly_mtm` alone; anything
# reading a freshly generated one must use the sum.
