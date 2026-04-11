"""
PM Feedback Results — extract summary text from signal+naive backtests.
Runs both backtests (progress bars suppressed) and prints all tables.
Saves sig_cl to CSV checkpoint so t-cost can re-run independently.
"""

import sys, os
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
os.environ["TQDM_DISABLE"] = "1"  # suppress all tqdm

import datetime, re, pytz, numpy as np, pandas as pd
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import QuantLib as ql

NYC_tz = pytz.timezone("America/New_York")

ENTRY_OFFSET    = datetime.timedelta(hours=-1)
EXIT_OFFSET     = datetime.timedelta(hours=2)
CURVE           = "USD-SOFR-1D-Q12STIRT"
TENOR           = "IMM_3xIMM_4"
BASE_BPV        = 100_000
SCORE_METRIC    = "trailing_5_avg"
MDP_SOURCE      = "BARCHART_STIRF-RL"
BT_START, BT_END = "2023-01-01", "2026-03-28"
EARLIEST_SPEECH = datetime.time(9,0)
LATEST_SPEECH   = datetime.time(16,0)
BLACKOUT_BD     = 1
MANUAL_SCORE_OVERRIDES = {"Miran": -1}
CHECKPOINT      = r"C:\Users\chris\clee\ARBS\notebooks\backtests\sig_closed.csv"
NAV_CHECKPOINT  = r"C:\Users\chris\clee\ARBS\notebooks\backtests\nav_closed.csv"

def score_to_bucket(s):
    if pd.isna(s): return 0
    if s>=20: return 2
    if s>=10: return 1
    if s>-10: return 0
    if s>-20: return -1
    return -2

# ── Load shared data ──────────────────────────────────────────────────────────
print("Loading ForexFactory + JPM …", flush=True)
from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher, ForexFactoryTheme
fetcher = ForexFactoryCalendarFetcher()
fed_speak_df = fetcher.fetch_range(BT_START, BT_END,
    themes=[ForexFactoryTheme.FED_SPEAKERS], show_tqdm=False, bulk_chunk_weeks=52)

jpm = pd.read_csv(r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv")
jpm["date"] = pd.to_datetime(jpm["date"]).dt.date
jpm = jpm.sort_values(["speaker","date"]).reset_index(drop=True)
KNOWN_SPEAKERS = sorted(jpm["speaker"].unique())

cache = {}
for sp, g in jpm.groupby("speaker"):
    g2 = g.sort_values("date")
    cache[sp] = (g2["date"].values, g2[SCORE_METRIC].values)

def get_score(sp, as_of):
    if sp not in cache: return np.nan
    ds, ss = cache[sp]; mask = ds < np.datetime64(as_of)
    return float(ss[mask][-1]) if mask.any() else np.nan

FOMC_DATES = [
    datetime.date(2023,2,1), datetime.date(2023,3,22), datetime.date(2023,5,3),
    datetime.date(2023,6,14), datetime.date(2023,7,26), datetime.date(2023,9,20),
    datetime.date(2023,11,1), datetime.date(2023,12,13), datetime.date(2024,1,31),
    datetime.date(2024,3,20), datetime.date(2024,5,1), datetime.date(2024,6,12),
    datetime.date(2024,7,31), datetime.date(2024,9,18), datetime.date(2024,11,7),
    datetime.date(2024,12,18), datetime.date(2025,1,29), datetime.date(2025,3,19),
    datetime.date(2025,5,7), datetime.date(2025,6,18), datetime.date(2025,7,30),
    datetime.date(2025,9,17), datetime.date(2025,10,29), datetime.date(2025,12,10),
    datetime.date(2026,1,28), datetime.date(2026,3,18),
]
ql_cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

def is_blackout(d):
    for f in FOMC_DATES:
        s = ql.Date(f.day,f.month,f.year)
        lo = ql_cal.advance(s, ql.Period(-BLACKOUT_BD,ql.Days), ql.Preceding)
        hi = ql_cal.advance(s, ql.Period( BLACKOUT_BD,ql.Days), ql.Following)
        if datetime.date(lo.year(),lo.month(),lo.dayOfMonth()) <= d <= datetime.date(hi.year(),hi.month(),hi.dayOfMonth()): return True
    return False

def extract_speaker(title):
    cleaned = re.sub(r"\b(Speaks?|Testifies|Testimony)\b","",title).strip()
    parts = cleaned.split(); return parts[-1] if parts else ""

ELIGIBLE = set(KNOWN_SPEAKERS) | set(MANUAL_SCORE_OVERRIDES)

def cap_exit(exit_ts, entry_ts):
    if exit_ts.hour >= 17: return exit_ts.replace(hour=16,minute=59,second=0,microsecond=0)
    eq = ql.Date(exit_ts.day,exit_ts.month,exit_ts.year)
    if not ql_cal.isBusinessDay(eq): return entry_ts.replace(hour=16,minute=59,second=0,microsecond=0)
    return exit_ts

def build_events(use_signal):
    raw = []
    for _, row in fed_speak_df.iterrows():
        sp = extract_speaker(row["Title"])
        if sp not in ELIGIBLE: continue
        ts = row["TimestampNYC"]
        if pd.isna(ts): continue
        if ts.tzinfo is None: ts = NYC_tz.localize(ts)
        d, t = ts.date(), ts.time()
        if t < EARLIEST_SPEECH or t > LATEST_SPEECH: continue
        if is_blackout(d): continue
        if "press conference" in row["Title"].lower(): continue
        raw_score = get_score(sp, d)
        if use_signal:
            bucket = (MANUAL_SCORE_OVERRIDES[sp] if sp in MANUAL_SCORE_OVERRIDES
                      else score_to_bucket(raw_score))
            if bucket == 0: continue
        else:
            bucket = +1  # naive: always pay fixed flat
        entry_ts = ts + ENTRY_OFFSET
        exit_ts  = ts + EXIT_OFFSET
        ql_e = ql.Date(entry_ts.day,entry_ts.month,entry_ts.year)
        if not ql_cal.isBusinessDay(ql_e): continue
        exit_ts = cap_exit(exit_ts, entry_ts)
        raw.append({"speaker":sp,"speech_ts":ts,"entry_ts":entry_ts,"exit_ts":exit_ts,
                    "raw_score":raw_score,"bucket":bucket,"bpv":-bucket*BASE_BPV,
                    "tag":f"speech_{row.get('EventId',len(raw))}"})
    raw.sort(key=lambda e: e["entry_ts"])
    filtered, last_exit = [], None
    for ev in raw:
        if last_exit and ev["entry_ts"] < last_exit: continue
        filtered.append(ev); last_exit = ev["exit_ts"]
    return filtered

signal_events = build_events(True)
naive_events  = build_events(False)
print(f"Signal events: {len(signal_events)} | Naive events: {len(naive_events)}", flush=True)

# ── Backtest runner ───────────────────────────────────────────────────────────
from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

curve_mdp = IRSwapsMDP(source=MDP_SOURCE)

def run_backtest(events, label):
    if not events: return pd.DataFrame()
    exit_ts_set = set(e["exit_ts"] for e in events)
    all_ts = sorted(set(e["entry_ts"] for e in events) | exit_ts_set)
    exit_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt, _ets=exit_ts_set: s in _ets),
        actions=[UnwindPositionsAction(match_all=True, fee=0.0)])
    entry_trigs = []
    for ev in events:
        _ts = ev["entry_ts"]
        _q = IRSwapQuery(curve=CURVE, tenor=TENOR, value=IRSwapValue.NPV,
                         structure_kwargs={"bpv": ev["bpv"]}, tags=(ev["tag"],),
                         meta={"speaker":ev["speaker"],"bucket":ev["bucket"],"raw_score":ev["raw_score"]})
        def _mk(ts):
            def fn(s, bt): return s == ts and len(bt.portfolio.positions) == 0
            return fn
        entry_trigs.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_mk(_ts)),
            actions=[AddQueryAction(query=_q)]))
    strat = QueryStrategy(name=label, triggers=[exit_trig]+entry_trigs)
    bt = QueryDrivenBacktest(time_grid=TimeGrid(all_ts), mdp=curve_mdp,
                              strategy=strat, show_progress=False)
    bt.run()
    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    if cl.empty: return cl
    cl["speaker"]   = cl["source_query"].apply(lambda q: q.meta.get("speaker",""))
    cl["bucket"]    = cl["source_query"].apply(lambda q: q.meta.get("bucket",0))
    cl["raw_score"] = cl["source_query"].apply(lambda q: q.meta.get("raw_score",np.nan))
    cl["opened_at"] = pd.to_datetime(cl["opened_at"])
    cl["closed_at"] = pd.to_datetime(cl["closed_at"])
    cl["year"]      = cl["opened_at"].dt.year
    cl["profitable"]= cl["realized_pnl"] > 0
    return cl

def get_metrics(cl):
    if cl.empty: return {}
    n = len(cl)
    yrs = max((cl["opened_at"].max()-cl["opened_at"].min()).days/365.25, 0.5)
    tpy = n/yrs; avg=cl["realized_pnl"].mean(); std=cl["realized_pnl"].std()
    sr = (avg/std*np.sqrt(tpy)) if std>0 else 0
    return {"n":n,"cum":cl["realized_pnl"].sum(),"avg":avg,"std":std,
            "hit":cl["profitable"].mean(),"sr":sr,"tpy":tpy,
            "mdd":(cl["realized_pnl"].cumsum()-cl["realized_pnl"].cumsum().cummax()).min()}

# ── Run / load from checkpoint ────────────────────────────────────────────────
if os.path.exists(CHECKPOINT):
    print(f"Loading signal checkpoint from {CHECKPOINT}", flush=True)
    sig_cl = pd.read_csv(CHECKPOINT, parse_dates=["opened_at","closed_at"])
    sig_cl["profitable"] = sig_cl["realized_pnl"] > 0
    sig_cl["year"] = sig_cl["opened_at"].dt.year
else:
    print("Running signal backtest …", flush=True)
    sig_cl = run_backtest(signal_events, "Signal")
    if not sig_cl.empty:
        sig_cl.to_csv(CHECKPOINT, index=False)
        print(f"  Saved to {CHECKPOINT}", flush=True)

if os.path.exists(NAV_CHECKPOINT):
    print(f"Loading naive checkpoint from {NAV_CHECKPOINT}", flush=True)
    nav_cl = pd.read_csv(NAV_CHECKPOINT, parse_dates=["opened_at","closed_at"])
    nav_cl["profitable"] = nav_cl["realized_pnl"] > 0
    nav_cl["year"] = nav_cl["opened_at"].dt.year
else:
    print("Running naive backtest …", flush=True)
    nav_cl = run_backtest(naive_events, "Naive")
    if not nav_cl.empty:
        nav_cl.to_csv(NAV_CHECKPOINT, index=False)
        print(f"  Saved to {NAV_CHECKPOINT}", flush=True)

sm = get_metrics(sig_cl)
nm = get_metrics(nav_cl)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*65)
print("  1. NAIVE BENCHMARK vs SIGNAL")
print("═"*65)
print(f"{'':30s} {'Signal':>15s} {'Naive':>15s}")
print(f"{'─'*65}")
print(f"{'Trades':30s} {sm['n']:>15d} {nm['n']:>15d}")
print(f"{'Trades/year':30s} {sm['tpy']:>15.0f} {nm['tpy']:>15.0f}")
print(f"{'Cumulative P&L':30s} ${sm['cum']:>14,.0f} ${nm['cum']:>14,.0f}")
print(f"{'Avg P&L / trade':30s} ${sm['avg']:>14,.0f} ${nm['avg']:>14,.0f}")
print(f"{'Std P&L / trade':30s} ${sm['std']:>14,.0f} ${nm['std']:>14,.0f}")
print(f"{'Hit Rate':30s} {sm['hit']:>14.1%} {nm['hit']:>14.1%}")
print(f"{'Sharpe':30s} {sm['sr']:>15.2f} {nm['sr']:>15.2f}")
print(f"{'Max Drawdown':30s} ${sm['mdd']:>14,.0f} ${nm['mdd']:>14,.0f}")

# Year-by-year comparison
sig_yr = sig_cl.groupby("year")["realized_pnl"].sum()
nav_yr = nav_cl.groupby("year")["realized_pnl"].sum()
print(f"\n{'Year-by-year P&L':30s} {'Signal':>15s} {'Naive':>15s}")
print(f"{'─'*65}")
for yr in sorted(set(sig_yr.index) | set(nav_yr.index)):
    sp = sig_yr.get(yr, 0); np_ = nav_yr.get(yr, 0)
    print(f"  {yr:28d} ${sp:>14,.0f} ${np_:>14,.0f}")

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*65)
print("  2. WALLER CHRONOLOGICAL P&L")
print("═"*65)
waller = sig_cl[sig_cl["speaker"]=="Waller"].copy().sort_values("opened_at").reset_index(drop=True)
if waller.empty:
    print("  No Waller trades.")
else:
    waller["cum_pnl"] = waller["realized_pnl"].cumsum()
    pivot = pd.Timestamp("2025-06-01", tz="America/New_York")
    # Handle tz-naive opened_at
    if waller["opened_at"].dt.tz is None:
        pivot_cmp = pd.Timestamp("2025-06-01")
    else:
        pivot_cmp = pivot
    pre  = waller[waller["opened_at"] <  pivot_cmp]
    post = waller[waller["opened_at"] >= pivot_cmp]

    print(f"  Total trades: {len(waller)} | Total P&L: ${waller['realized_pnl'].sum():,.0f} | Hit: {waller['profitable'].mean():.1%}")
    print(f"  Pre  Jun-2025 ({len(pre):2d} trades): ${pre['realized_pnl'].sum():,.0f}   hit={pre['profitable'].mean():.0%}")
    if not post.empty:
        print(f"  Post Jun-2025 ({len(post):2d} trades): ${post['realized_pnl'].sum():,.0f}   hit={post['profitable'].mean():.0%}")

    print(f"\n  {'#':>3} {'Date':12s} {'Score':>7} {'Bucket':>7} {'P&L':>12} {'Cum P&L':>14}")
    print(f"  {'─'*60}")
    for i, row in waller.iterrows():
        score_str = f"{row['raw_score']:.0f}" if not pd.isna(row['raw_score']) else "N/A"
        marker = " ◄ pivot" if row["opened_at"] >= pivot_cmp and (i==0 or waller.loc[i-1,"opened_at"] < pivot_cmp) else ""
        print(f"  {i+1:>3} {str(row['opened_at'].date()):12s} {score_str:>7} {int(row['bucket']):>+7d} "
              f"${row['realized_pnl']:>10,.0f} ${row['cum_pnl']:>12,.0f}{marker}")

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*65)
print("  3. TRANSACTION COST SENSITIVITY")
print("═"*65)
cost_levels = [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
print(f"  {'Cost(bps RT)':>12} {'Cost/trade':>12} {'Cum P&L':>14} {'Avg P&L':>12} {'Hit':>8} {'Sharpe':>8} {'ΔSharpe':>9}")
print(f"  {'─'*80}")
for bps in cost_levels:
    rt = sig_cl["bucket"].abs() * BASE_BPV * bps / 10_000
    adj = sig_cl["realized_pnl"] - rt
    a_avg=adj.mean(); a_std=adj.std()
    a_sr=(a_avg/a_std*np.sqrt(sm["tpy"])) if a_std>0 else 0
    a_hit=(adj>0).mean(); a_cum=adj.sum()
    print(f"  {bps:>12.2f} ${rt.mean():>10,.0f} ${a_cum:>13,.0f} ${a_avg:>10,.0f} "
          f"{a_hit:>7.1%} {a_sr:>8.2f} {a_sr-sm['sr']:>+9.2f}")

# Breakeven
for bps in [x/10 for x in range(0,51)]:
    rt = sig_cl["bucket"].abs() * BASE_BPV * bps / 10_000
    if (sig_cl["realized_pnl"] - rt).sum() <= 0:
        print(f"\n  Breakeven: ~{bps:.1f} bps RT")
        break
else:
    print(f"\n  Profitable through {cost_levels[-1]} bps RT")

# As % of avg P&L
avg_rt_per_unit = BASE_BPV / 10_000  # $ per 1 bp RT for bucket=1
print(f"\n  Note: 1 bp RT costs ~${avg_rt_per_unit:,.0f}/bucket-unit vs avg P&L ${sm['avg']:,.0f}")
print(f"  1 bp RT = {avg_rt_per_unit/sm['avg']*100:.1f}% of avg gross P&L")

print("\n  Done.", flush=True)
