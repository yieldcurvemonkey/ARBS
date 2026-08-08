# %% [markdown]
# # H13 grail-conditional flattener — the QueryDrivenBacktest implementation
#
# The standing rule: strategies the loop tests get engine-native
# `QueryDrivenBacktest` implementations as executed notebooks. H13 is
# **DEAD** (ledger `V-SV-13F`: 17 arms, median across arms +0.0 bp, DSR
# 0.000 at n=3,905; its mechanism wording withdrawn by the rival check,
# `L-0030`). Nothing here reopens it — this notebook re-expresses a dead
# strategy in the production engine and ties out against the committed panel
# artifacts, following `sv_qdb_certification`.
#
# **What is engine-native here.** The panel engine
# (`scripts/sv_citivelo_h13.py`) never enters or exits anything: it builds a
# UNIT aged-package ledger and *scales its daily flows by a {0,1} state*.
# That is a legitimate research shortcut and it is what every H13 number was
# graded on. The engine cannot do that. It has to actually
# **add a package when the state turns on and unwind it when the state turns
# off**, through `Trigger` machinery with the detector parquet as the signal
# panel (the `famb_fade_qdb` pattern, late-binding closures guarded by default
# arguments). Making the strategy executable forces three conventions into the
# open, and section 6 measures all three:
#
# 1. **Aged vs fresh.** The panel's package is struck at the *roll-segment*
#    start and is up to a year old when a state episode begins; the engine
#    strikes a fresh at-market package **at the entry**.
# 2. **Resizes.** The panel's unit ledger runs the 25 bp DV01-neutrality
#    resize rule (105 hedges fire inside this arm's episodes); the engine book
#    holds a fixed package per segment.
# 3. **The fill day.** The panel earns the flow *dated* at the first on-day,
#    and that flow is the move from the previous close — so the committed
#    ledger fills at the same close its signal is computed from. The engine
#    fills at the entry day's marks and earns from there. One day, in the
#    direction that flatters.
#
# Arm: **USD 15Y5Y/20Y10Y**, the flagship (best arm in `V-SV-13`: +106.7 bp
# net@1×, 116 episodes, occupancy 48.9%) — if any arm is worth expressing in
# the engine it is the one the verdict quoted.

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
MARKET = "USD"
PAIR_NAME = "USD 15Y5Y/20Y10Y"
SHORT_LEG, LONG_LEG = "15Yx5Y", "20Yx10Y"   # pay short, receive long = flattener
PKG_DV01 = 100_000.0
ROLL_MONTHS = 12
# Citi 2019 Fig-9, this pair's tier (sv_citivelo_h13._TIGHT): 0.75 bp one-way
# initiation, 0.30 bp one-way hedge/roll, per $100k DV01.
INITIATE_BP, ROLL_BP = 0.75, 0.30

# %% [markdown]
# ## 1. The planted-answer sign test, live
#
# Identical to the certification notebook's probe and run on every execution:
# the 2022-09 CPI week moved rates ~23 bp, so a payer must gain and ±bpv must
# mirror exactly. A regressed `RLIRSwapCurve.resolve_pricable` (ledger L-0012)
# would silently invert every number below; this is the tripwire.

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
# ## 2. The signal panel and the episodes
#
# The detector parquet is the signal panel (`famb_fade_qdb`'s pattern: the
# signal stays strategy-side, the engine owns marks and P&L). The state is the
# registered one — `grail_flattener` = repriced flattener carry ≥ 0 AND
# gamma_25 > 0 — shifted one day, evaluated on the committed unit ledger's own
# day index (already ghost-filtered: the holiday-ghost trap, L-0018).
#
# The episodes derived here are then **asserted equal** to the committed
# `h13_trades_*` entry/exit dates. If the notebook's signal reproduction had
# drifted from the graded one, everything downstream would be measuring a
# different strategy, so this is checked rather than assumed.

# %%
units = pd.read_parquet(DATA / "h13_units_USD.parquet").xs(PAIR_NAME, level="pair")
units.index = pd.to_datetime(units.index)
det = pd.read_parquet(DATA / "sv_detector_USD.parquet")
det["date"] = pd.to_datetime(det["date"])
det = det[det["pair"] == PAIR_NAME].set_index("date").sort_index()

state = det["grail_flattener"].astype(float).shift(1).fillna(0.0)
state = state.reindex(units.index).fillna(0.0)


def episodes_of(s: pd.Series) -> list:
    """Contiguous on-blocks, as (first_on_day, last_on_day)."""
    out, entry, prev = [], None, None
    for d, flag in (s > 0).items():
        if flag and entry is None:
            entry = d
        elif not flag and entry is not None:
            out.append((entry, prev))
            entry = None
        prev = d
    if entry is not None:
        out.append((entry, prev))
    return out


EPISODES = episodes_of(state)
committed = pd.read_parquet(
    DATA / f"h13_trades_{MARKET}_{PAIR_NAME.replace(' ', '_').replace('/', '-')}.parquet")
committed["entry"] = pd.to_datetime(committed["entry"])
committed["exit"] = pd.to_datetime(committed["exit"])
print(f"episodes rebuilt {len(EPISODES)}  committed {len(committed)}")
assert len(EPISODES) == len(committed), "episode count differs from the graded artifact"
assert all(e == ce and x == cx for (e, x), (ce, cx)
           in zip(EPISODES, zip(committed["entry"], committed["exit"]))), \
    "episode boundaries differ from the graded artifact"
print("SIGNAL REPRODUCTION PASS: episodes are byte-equal to the graded ones")

print(f"occupancy {float((state > 0).mean()):.1%}, "
      f"median episode {int(np.median([len(units.loc[e:x]) for e, x in EPISODES]))}d, "
      f"longest {max(len(units.loc[e:x]) for e, x in EPISODES)}d")

# %% [markdown]
# ## 3. When the book is actually on — and the roll segments inside an episode
#
# **The fill day, decided explicitly rather than inherited.** The panel sums the
# flows *dated* `entry..exit`, and the flow dated at the entry is the move from
# the previous close. So the graded book is the one that **fills at the close of
# the day the signal fires** — `state = grail.shift(1)`, so the signal is
# `grail[entry−1]` and the fill is at `entry−1`'s close. That is the registered
# "entry lag-1 at state onset" read literally, and it is not lookahead: the
# state is computed from a curve that has already printed.
#
# It is also not a `t+1` fill, which is what the house bar asks for. So this
# notebook runs **both**, and reports the difference instead of picking one:
#
# * **Book A — panel-equivalent**: add at the signal day's close (`entry−1`),
#   unwind at `exit`. This is the tie-out book; it prices exactly the days the
#   committed ledger sums.
# * **Book B — strict t+1**: add one day later, at `entry`. Same exit.
#
# Both re-strike on the 12-month anniversary inside long episodes (the longest
# runs 804 days), the engine as unwind+add on the same step with **distinct tags
# per segment** — unwinds process after fills, so one shared tag would close the
# package the roll just opened — and the panel as one `CurvePricer` per
# sub-segment sharing the boundary date.

# %%
_idx = list(units.index)
_pos = {d: i for i, d in enumerate(_idx)}


def episode_days(e, x, *, fill_offset: int) -> list:
    """Days the book is priced over. ``fill_offset=0`` -> Book A, 1 -> Book B.

    The offset moves the WHOLE window, entry and exit together. Lagging only the
    entry would shorten every hold by a day and delete the 44 one-day episodes
    outright — that is a different strategy, not a later fill, and the A−B
    difference would then be measuring episode attrition rather than timing.
    """
    i0 = max(0, _pos[e] - 1 + fill_offset)
    i1 = min(len(_idx) - 1, _pos[x] + fill_offset)
    return _idx[i0:i1 + 1]


# %%
def sub_segments(days: list) -> list:
    """[(i, j), ...] index bounds of 12-month sub-segments, sharing boundaries."""
    bounds, i = [], 0
    while i < len(days) - 1:
        due = pd.Timestamp(days[i]) + pd.DateOffset(months=ROLL_MONTHS)
        j = i + 1
        while j < len(days) - 1 and pd.Timestamp(days[j]) < due:
            j += 1
        bounds.append((i, j))
        i = j
    return bounds or [(0, len(days) - 1)]


def build_books(fill_offset: int) -> tuple:
    ep_days = [episode_days(e, x, fill_offset=fill_offset) for e, x in EPISODES]
    ep_days = [d for d in ep_days if len(d) >= 2]   # a 1-day book cannot price
    ep_segs = [sub_segments(d) for d in ep_days]
    days = sorted({d for dd in ep_days for d in dd})
    return ep_days, ep_segs, days


BOOKS = {"A": build_books(0), "B": build_books(1)}
for name, (ep_days, ep_segs, days) in BOOKS.items():
    print(f"book {name}: {len(ep_days)} priceable episodes, "
          f"{sum(len(s) for s in ep_segs)} package segments, {len(days)} grid days")

# %% [markdown]
# ## 4. The engine run
#
# Pay `15Yx5Y` (+$100k/bp), receive `20Yx10Y` (−$100k/bp), marked by
# `IRSwapsMDP(source="CITIVELO_EXCEL")` off the warmed CurveStore. The
# `TimeGrid` carries only the held days: between episodes the book is flat, so
# the days in between would add marks and no information.
#
# Fees are charged at the unwind (`UnwindPositionsAction.fee` is the engine's
# only cost hook — design landmine 6). The round trip lands on the episode's
# closing unwind; intra-episode roll unwinds carry the roll charge. The GROSS
# series for the tie-out adds the fees back so both books are gross.

# %%
def run_engine(book: str) -> pd.DataFrame:
    ep_days, ep_segs, grid_days = BOOKS[book]
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    triggers, fee_events = [], []
    for k, (days, segs) in enumerate(zip(ep_days, ep_segs)):
        for s, (i, j) in enumerate(segs):
            tag = f"ep{k}s{s}"
            legs = [
                IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                            tenor=SHORT_LEG, curve=CURVE,
                            structure_kwargs={"bpv": +PKG_DV01}, tags=(tag,)),
                IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                            tenor=LONG_LEG, curve=CURVE,
                            structure_kwargs={"bpv": -PKG_DV01}, tags=(tag,)),
            ]
            # last segment of the episode closes the position (round trip);
            # earlier ones are re-strikes (roll charge).
            is_close = (s == len(segs) - 1)
            fee = (2.0 * INITIATE_BP if is_close else ROLL_BP) * PKG_DV01
            # DateTriggerRequirements tests ``state.date() in set(self.dates)``.
            # A pd.Timestamp in that set never compares equal to a datetime.date,
            # so the trigger becomes a SILENT no-op: the run completes, the
            # equity curve has no holes, and every mark is exactly zero. Caught
            # here by the assertion below, which is why it exists.
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[pd.Timestamp(days[i]).date()]),
                actions=[AddQueryAction(query=q, meta={"tags": [tag]}) for q in legs]))
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[pd.Timestamp(days[j]).date()]),
                actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))
            fee_events.append((pd.Timestamp(days[j]), fee))
    grid = TimeGrid([pd.Timestamp(d) for d in grid_days])
    strat = QueryStrategy(name=f"h13_grail_conditional_{book}", triggers=triggers)
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    print(f"engine {book}: {len(eq)} marks in {time.time() - t0:.0f}s")
    missing = set(pd.Timestamp(d) for d in grid_days) - set(eq.index)
    assert not missing, f"equity-curve holes (engine swallowed steps): {sorted(missing)[:3]}"
    # A book that never traded also has no holes and no NaNs. Prove it traded.
    n_closed = len(getattr(bt.portfolio, "closed_positions_log", []) or [])
    n_live = int((eq.abs() > 1e-9).sum())
    n_seg = sum(len(s) for s in ep_segs)
    print(f"  closed positions {n_closed}, days with non-zero equity {n_live}, "
          f"segments {n_seg}")
    assert n_live > 0, "engine equity is identically zero — no trigger ever fired"
    assert n_closed >= 2 * n_seg, f"expected >= {2 * n_seg} closed legs, got {n_closed}"
    out = eq.to_frame("equity_usd")
    fees = pd.Series(0.0, index=out.index)
    for d, f in fee_events:
        fees.loc[d] += f
    out["fees"] = fees
    out["equity_gross_usd"] = out["equity_usd"] + fees.cumsum()
    return out


ENGINE = {}
for _book in ("A", "B"):
    _art = DATA / f"h13_qdb_engine_{_book}.parquet"
    if _art.exists():
        ENGINE[_book] = pd.read_parquet(_art)
        ENGINE[_book].index = pd.to_datetime(ENGINE[_book].index)
        print(f"loaded {_art.name}: {ENGINE[_book].shape}")
    else:
        ENGINE[_book] = run_engine(_book)
        ENGINE[_book].to_parquet(_art)
        print(f"wrote {_art.name}")

# %% [markdown]
# ## 5. The matched-semantics panel comparable
#
# The committed unit ledger cannot be the tie-out target directly — it holds a
# package struck at a *roll-segment* start and resizes it at 25 bp. To ask "does
# the production engine reproduce the panel engine", both must price the same
# book, so this reruns `CurvePricer` + `simulate` with the package struck **at
# Book A's fill day** and the resize trigger out of reach (`trigger_bp=1e9`), on
# the same ghost-filtered curves. Section 7 measures the distance from there to
# the committed convention rather than hiding it.

# %%
def run_panel() -> pd.Series:
    ep_days, ep_segs, grid_days = BOOKS["A"]
    import logging

    logging.disable(logging.WARNING)
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, citivelo_pairs
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer, ReplicationConfig, simulate

    pair = next(p for p in citivelo_pairs([MARKET]) if p.name == PAIR_NAME)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    free = CostSchedule(multiplier=0.0)
    cfg = ReplicationConfig(trigger_bp=1e9, roll_months=1200,
                            package_dv01_usd=PKG_DV01)
    curves = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES[MARKET],
                                "timestamps": grid_days, "offline": True})

    def _ok(ts, c):
        if c is None:
            return False
        ref = c.reference_date()
        rd = ref.date() if hasattr(ref, "date") else ref
        td = ts.date() if hasattr(ts, "date") else ts
        return rd == td

    curves = {pd.Timestamp(ts): c for ts, c in curves.items() if _ok(ts, c)}
    pieces, t0 = [], time.time()
    for k, (days, segs) in enumerate(zip(ep_days, ep_segs)):
        for (i, j) in segs:
            seg_days = days[i:j + 1]
            cm = {pd.Timestamp(d): curves[pd.Timestamp(d)] for d in seg_days
                  if pd.Timestamp(d) in curves}
            assert len(cm) == len(seg_days), (
                f"curve missing for segment {seg_days[0]}..{seg_days[-1]} — the "
                "panel and engine would then price different day sets")
            ctx = CurvePricer(cm, pair, package_dv01_usd=PKG_DV01)
            led = simulate(ctx, ctx.dates(), cfg, free)
            pieces.append(led[["carry", "harvest", "mtm", "cross"]].sum(axis=1))
        if (k + 1) % 20 == 0:
            print(f"  episode {k + 1}/{len(ep_days)} ({time.time() - t0:.0f}s)", flush=True)
    return pd.concat(pieces).groupby(level=0).sum().sort_index()


ART2 = DATA / "h13_qdb_panel.parquet"
if ART2.exists():
    panel_daily = pd.read_parquet(ART2)["pnl"]
    panel_daily.index = pd.to_datetime(panel_daily.index)
    print(f"loaded {ART2.name}: {len(panel_daily)}")
else:
    panel_daily = run_panel()
    panel_daily.to_frame("pnl").to_parquet(ART2)
    print(f"wrote {ART2.name}")

# %% [markdown]
# ## 6. The tie-out
#
# Daily engine P&L (gross equity diff) against the panel's daily flows on
# common days. Bar: **corr ≥ 0.97** (the SERFF pattern the design doc fixes as
# the certification tolerance), terminal gap reported in bp of package DV01.
#
# Book A is the tie-out book: it prices exactly the days the committed ledger
# sums. Days on which an episode opens carry no P&L in either book — a fresh
# at-market package is worth zero — so the comparison is on the days that move.

# %%
eng_daily = ENGINE["A"]["equity_gross_usd"].diff().dropna()
j = pd.DataFrame({"engine": eng_daily, "panel": panel_daily}).dropna()
corr = float(j["engine"].corr(j["panel"]))
term_gap_bp = float((j["engine"].sum() - j["panel"].sum()) / PKG_DV01)
mad_bp = float((j["engine"] - j["panel"]).abs().median() / PKG_DV01)
print(f"common days {len(j)}, corr {corr:.4f}, terminal gap {term_gap_bp:+.2f}bp, "
      f"median |daily diff| {mad_bp:.4f}bp")
assert corr >= 0.97, f"tie-out FAILED the SERFF bar: corr {corr:.4f}"
print("TIE-OUT PASS")

# %% [markdown]
# ## 7. What the engine forced into the open
#
# Three conventions separate the executable book from the committed graded
# ledger. Each is measured here in bp of package DV01 over the same episodes, so
# the size of each is on the record rather than the fact of it.
#
# * **the fill day** — Book A fills at the signal close (what the committed
#   ledger prices), Book B one day later (a strict `t+1` fill, what the house
#   bar asks for). `A − B` is what the graded number owes to filling on the
#   signal's own close.
# * **resizes** — the committed unit ledger's `harvest` bucket is the P&L of the
#   25 bp DV01-neutrality resizes; both engine books hold a fixed package per
#   segment.
# * **aged vs fresh** — the remainder: the committed package is struck at a
#   roll-segment start and can be a year old at entry; the engine's is struck at
#   the fill.
#
# The DV01 denominators differ by construction — the committed per-episode bp is
# normalised by the *realised* average DV01 of an aged, resized package
# (`CurvePricer`'s docstring: mean $98,813, range $52,672–$148,915), the engine's
# by the $100k it was struck to — so the residual absorbs that too and is
# labelled as a residual, not as an aging measurement.
#
# The engine-vs-panel terminal gap of ~4% of gross (section 6) is the same
# forward-swap convention gap the certification notebook carries (+0.28 on
# +9.34 bp, 3%); both books carry it identically, so it cancels in `A − B`.

# %%
denom = (units["long_notional"].abs() * units["dv01_long_unit"]).replace(0, np.nan)
flows = units[["carry", "harvest", "mtm", "cross"]].sum(axis=1)

harvest_bp = committed_bp = committed_shift_bp = 0.0
entry_day_bp = post_exit_day_bp = 0.0
for (e, x) in EPISODES:
    d = float(denom.loc[e:x][denom.loc[e:x] > 0].mean())
    if not np.isfinite(d) or d == 0:
        continue
    committed_bp += float(flows.loc[e:x].sum()) / d
    harvest_bp += float(units.loc[e:x, "harvest"].sum()) / d
    # the SAME aged panel package, window moved one day later: what the graded
    # artifact would have printed under a t+1 fill. The shift does two separable
    # things and they are worth different amounts, so both ends are kept apart:
    # it DROPS the entry-dated flow (the move that generated the signal) and it
    # ADDS the day after the exit (holding one day past the state).
    i0, i1 = _pos[e] + 1, min(len(_idx) - 1, _pos[x] + 1)
    committed_shift_bp += float(flows.iloc[i0:i1 + 1].sum()) / d
    entry_day_bp += float(flows.loc[e]) / d
    post_exit_day_bp += float(flows.iloc[i1]) / d if i1 > _pos[x] else 0.0

GROSS_BP = {b: float(ENGINE[b]["equity_gross_usd"].diff().sum() / PKG_DV01)
            for b in ("A", "B")}
eng_ep_bp = GROSS_BP["A"]

audit = {
    "committed_gross_bp": committed_bp,
    "committed_gross_bp_artifact": float(committed["gross_bp"].sum()),
    "committed_gross_bp_window_shifted_t_plus_1": committed_shift_bp,
    "committed_registered_cost_bp_at_1x": 2 * INITIATE_BP * len(EPISODES),
    "engine_gross_bp_bookA_signal_close_fill": GROSS_BP["A"],
    "engine_gross_bp_bookB_t_plus_1_fill": GROSS_BP["B"],
    "fill_day_cost_bp_engine": GROSS_BP["A"] - GROSS_BP["B"],
    "fill_day_cost_bp_committed_panel": committed_bp - committed_shift_bp,
    "  of which entry_day_flow_dropped_bp": entry_day_bp,
    "  of which post_exit_day_flow_added_bp": post_exit_day_bp,
    "resize_harvest_bp": harvest_bp,
    "aged_vs_fresh_and_dv01_residual_bp": committed_bp - harvest_bp - GROSS_BP["A"],
}
print(json.dumps(audit, indent=1))
print(f"\nfilling at t+1 instead of the signal close costs "
      f"{GROSS_BP['A'] - GROSS_BP['B']:+.1f}bp of the {GROSS_BP['A']:+.1f}bp Book-A gross "
      f"(engine), {committed_bp - committed_shift_bp:+.1f}bp of the {committed_bp:+.1f}bp "
      f"committed gross (same aged panel package, window moved one day)")

# %% [markdown]
# ## 8. Costs, and the verdict this re-expresses
#
# The registered schedule for this pair: 0.75 bp one-way initiation (so a 1.5 bp
# round trip per episode) and 0.30 bp per intra-episode re-strike, per $100k
# DV01, at multipliers {0.5, 1, 2}. 116 episodes at 1× is 174 bp of initiation
# alone against a gross the same order of magnitude — which is the whole H13
# autopsy in one line, and why `V-SV-13F` reads DEAD.

# %%
rows = []
for book in ("A", "B"):
    ep_days, ep_segs, _ = BOOKS[book]
    n_ep, n_rolls = len(ep_days), sum(len(s) - 1 for s in ep_segs)
    for mult in (0.5, 1.0, 2.0):
        cost_bp = mult * (2 * INITIATE_BP * n_ep + ROLL_BP * n_rolls)
        rows.append({"book": book, "n_episodes": n_ep, "n_rolls": n_rolls,
                     "mult": mult, "cost_bp": cost_bp,
                     "gross_bp": GROSS_BP[book],
                     "net_bp": GROSS_BP[book] - cost_bp})
costs = pd.DataFrame(rows)
print(costs.to_string(index=False))

# %% [markdown]
# ### The house verdict on the engine book
#
# A gross number in bp is not a verdict, and this one is *larger* than the
# graded arm's (the engine's package is struck fresh at every entry, so it
# carries its full $100k of DV01 where the aged panel package had drifted). The
# bar is applied here explicitly, on the engine's own per-episode net series,
# with DSR at the same family count the grade used (`N_sv` 3,888 + 17 arms =
# 3,905) and the same cross-trial Sharpe variance, so this notebook cannot be
# read as reviving anything.

# %%
from BT.signals.deflated_sharpe import deflated_sharpe
from RVUtils.SFRRVLab.stats import nonoverlapping_sharpe, nw_tstat, verdict

N_TRIALS_FAMILY = 3888 + 17
grade = pd.read_parquet(DATA / "h13_grade.parquet")
VAR_SR = float(np.var(grade["per_trade_sharpe"].dropna().to_numpy(), ddof=1))


def episode_net_bp(book: str, mult: float) -> pd.Series:
    ep_days, ep_segs, _ = BOOKS[book]
    eq = ENGINE[book]["equity_gross_usd"]
    out = {}
    for days, segs in zip(ep_days, ep_segs):
        gross = float(eq.loc[days[-1]] - eq.loc[days[0]])
        cost = mult * (2 * INITIATE_BP + ROLL_BP * (len(segs) - 1)) * PKG_DV01
        out[days[0]] = (gross - cost) / PKG_DV01
    return pd.Series(out).sort_index()


house = {}
for book in ("A", "B"):
    net = episode_net_bp(book, 1.0)
    dsr = float(deflated_sharpe(net.to_numpy(dtype=float),
                                n_trials=N_TRIALS_FAMILY,
                                sr_variance=VAR_SR)["dsr_prob"])
    v = verdict(net_bp_at_taker=float(net.sum()),
                net_bp_at_maker=float(net.sum()),
                dsr_prob=dsr, median_net_bp=float(net.median()),
                n_trades=int(len(net)))
    house[book] = {
        "n_episodes": int(len(net)), "net_bp_at_1x": float(net.sum()),
        "median_episode_bp": float(net.median()),
        "per_episode_sharpe": float(net.mean() / net.std()),
        "hit_rate": float((net > 0).mean()),
        "biggest_episode_frac_of_net": float(net.abs().max() / abs(net.sum())),
        "nw_t": float(nw_tstat(net)),
        "dsr_prob_at_3905": dsr, "verdict": v,
    }
    print(f"book {book}: {v}  net {net.sum():+.1f}bp  median {net.median():+.3f}bp  "
          f"DSR {dsr:.3g}  per-episode SR {net.mean() / net.std():.3f}")

verdict = {
    "arm": PAIR_NAME,
    "n_episodes": len(EPISODES),
    "tie_out": {"n_common_days": int(len(j)), "daily_corr": corr,
                "terminal_gap_bp": term_gap_bp,
                "median_abs_daily_diff_bp": mad_bp,
                "bar": "corr >= 0.97", "pass": bool(corr >= 0.97)},
    "convention_audit_bp": audit,
    "net_bp": {f"book{r['book']}_x{r['mult']}": r["net_bp"]
               for _, r in costs.iterrows()},
    "house_bar": house,
    "re_expresses": "V-SV-13F (H13 FINAL: DEAD, DSR 0.000 at n=3,905)",
    "changes_verdict": False,
    "trials_delta": 0,
}
(DATA / "h13_qdb_verdict.json").write_text(json.dumps(verdict, indent=1))
print(json.dumps(verdict, indent=1))

# %% [markdown]
# ## 9. What the fill day means for the graded arm
#
# The number worth carrying out of this notebook is not the tie-out; it is what
# the tie-out made it necessary to decide.
#
# On the **committed aged panel package**, moving the window one day later takes
# the flagship arm's gross from **+282.7 bp to +166.1 bp**. The registered cost
# at 1× is 2 × 0.75 bp × 116 episodes = **174.0 bp**. So the arm that was graded
# at **+106.7 bp net** is **−7.9 bp net** under a `t+1` fill — and the engine
# book agrees in direction and size (+162.4 bp → −13.8 bp, `SELECTION-ARTIFACT`
# → `DEAD`).
#
# The shift does **two separable** things, so the audit keeps them apart rather
# than quoting only the net, and **both ends are material**:
#
# * dropping the entry-dated flow costs **+70.9 bp** — the move that generated
#   the signal;
# * adding the day after the exit costs a further **−45.6 bp** — one extra day
#   held past the state is a large loss.
#
# That pairing is the finding. The state does not merely *begin* on a big
# favourable day; it *ends* just before a big adverse one. Both boundaries are
# timed on same-day information, and the graded book collects at one end and
# steps aside at the other. This is what `L-0027` saw as the state "chattering
# at the carry-zero boundary" and what `L-0030` measured when occupancy-matched
# raw spread-z states reproduced 137% of the grail state's ex-carry: the state
# is a spread-extreme bracket. Mechanically, `grail_flattener` is a **carry-zero
# crossing** (`carry ≥ 0 AND gamma_25 > 0`) and carry crosses zero on days the
# spread moves — in both directions.
#
# **The alternative reading, stated rather than buried:** a desk running this
# framework prices the state intraday and can trade before the close, so a
# same-close fill is not absurd as a description of practice. What it is not is
# the convention this program grades on — the design doc's marking policy says
# "lag-1 fills (signal on day t, execute at day t+1 marks)" and the checker
# charter asks "Fills at t+1?". By the house bar, Book B is the graded book.
#
# ## 10. What this does and does not certify
#
# Certifies: the H13 rule is expressible in the production engine — the detector
# state drives real `AddQueryAction`/`UnwindPositionsAction` events on
# `IRSwapQuery` forward legs, the episodes reproduce the graded ones exactly,
# there are no equity-curve holes, direction semantics are checked live, and the
# engine's daily P&L reproduces a matched-semantics panel run at corr 0.9999.
#
# Does **not** certify a strategy, and does not reopen one. H13 is DEAD
# (`V-SV-13F`); this notebook consumes no trials and changes no verdict. Every
# number it adds moves the graded arm *down*, which is the only direction a
# post-hoc convention audit is allowed to be trusted in without a fresh checker
# — and it is the direction the program's own record predicts, because every
# defect found in this lab so far has flattered the maker.
