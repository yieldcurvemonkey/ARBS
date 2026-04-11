"""
Fed Hawk/Dove — PM Feedback Analyses
1. Naive benchmark: flat pay-fixed on every eligible speech (no scoring)
2. Waller chronological P&L (label decay illustration)
3. T-cost sensitivity (extended)
"""

import sys
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

import datetime
import re
import pytz
import numpy as np
import pandas as pd
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.pylab as pylab

plt.style.use("ggplot")
params = {"legend.fontsize": "large", "figure.figsize": (12, 6),
          "axes.labelsize": "large", "axes.titlesize": "large",
          "xtick.labelsize": "medium", "ytick.labelsize": "medium"}
pylab.rcParams.update(params)

import QuantLib as ql
import rateslib as rl

NYC_tz = pytz.timezone("America/New_York")

# ── Config (must match notebook) ─────────────────────────────────────────────
ENTRY_OFFSET   = datetime.timedelta(hours=-1)
EXIT_OFFSET    = datetime.timedelta(hours=2)
CURVE          = "USD-SOFR-1D-Q12STIRT"
TENOR          = "IMM_3xIMM_4"
BASE_BPV       = 100_000
SCORE_METRIC   = "trailing_5_avg"
MDP_SOURCE     = "BARCHART_STIRF-RL"
BT_START       = "2023-01-01"
BT_END         = "2026-03-28"
EARLIEST_SPEECH = datetime.time(9, 0)
LATEST_SPEECH   = datetime.time(16, 0)
BLACKOUT_BD     = 1
MANUAL_SCORE_OVERRIDES = {"Miran": -1}

def score_to_bucket(score):
    if pd.isna(score): return 0
    if score >= 20:    return 2
    if score >= 10:    return 1
    if score > -10:    return 0
    if score > -20:    return -1
    return -2

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading ForexFactory calendar …")
from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher, ForexFactoryTheme
fetcher = ForexFactoryCalendarFetcher()
fed_speak_df = fetcher.fetch_range(BT_START, BT_END,
                                   themes=[ForexFactoryTheme.FED_SPEAKERS],
                                   show_tqdm=True, bulk_chunk_weeks=52)
print(f"  {len(fed_speak_df)} events loaded")

print("Loading JPM scores …")
jpm_scores = pd.read_csv(
    r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv"
)
jpm_scores["date"] = pd.to_datetime(jpm_scores["date"]).dt.date
jpm_scores = jpm_scores.sort_values(["speaker","date"]).reset_index(drop=True)
KNOWN_SPEAKERS = sorted(jpm_scores["speaker"].unique())

_speaker_score_cache = {}
for speaker, grp in jpm_scores.groupby("speaker"):
    grp_sorted = grp.sort_values("date")
    _speaker_score_cache[speaker] = (grp_sorted["date"].values,
                                      grp_sorted[SCORE_METRIC].values)

def get_speaker_score(speaker, as_of):
    if speaker not in _speaker_score_cache: return np.nan
    dates, scores = _speaker_score_cache[speaker]
    mask = dates < np.datetime64(as_of)
    if not mask.any(): return np.nan
    return float(scores[mask][-1])

def get_bucket(speaker, speech_date):
    if speaker in MANUAL_SCORE_OVERRIDES:
        return MANUAL_SCORE_OVERRIDES[speaker]
    return score_to_bucket(get_speaker_score(speaker, speech_date))

# FOMC dates
FOMC_DATES = [
    datetime.date(2023,2,1),  datetime.date(2023,3,22), datetime.date(2023,5,3),
    datetime.date(2023,6,14), datetime.date(2023,7,26), datetime.date(2023,9,20),
    datetime.date(2023,11,1), datetime.date(2023,12,13),
    datetime.date(2024,1,31), datetime.date(2024,3,20), datetime.date(2024,5,1),
    datetime.date(2024,6,12), datetime.date(2024,7,31), datetime.date(2024,9,18),
    datetime.date(2024,11,7), datetime.date(2024,12,18),
    datetime.date(2025,1,29), datetime.date(2025,3,19), datetime.date(2025,5,7),
    datetime.date(2025,6,18), datetime.date(2025,7,30), datetime.date(2025,9,17),
    datetime.date(2025,10,29),datetime.date(2025,12,10),
    datetime.date(2026,1,28), datetime.date(2026,3,18),
]
ql_cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

def is_in_blackout(event_date):
    for fomc in FOMC_DATES:
        s = ql.Date(fomc.day, fomc.month, fomc.year)
        lo = ql_cal.advance(s, ql.Period(-BLACKOUT_BD, ql.Days), ql.Preceding)
        hi = ql_cal.advance(s, ql.Period( BLACKOUT_BD, ql.Days), ql.Following)
        lo_d = datetime.date(lo.year(), lo.month(), lo.dayOfMonth())
        hi_d = datetime.date(hi.year(), hi.month(), hi.dayOfMonth())
        if lo_d <= event_date <= hi_d: return True
    return False

def cap_exit(exit_ts, entry_ts):
    if exit_ts.hour >= 17:
        return exit_ts.replace(hour=16, minute=59, second=0, microsecond=0)
    exit_ql = ql.Date(exit_ts.day, exit_ts.month, exit_ts.year)
    if not ql_cal.isBusinessDay(exit_ql):
        return entry_ts.replace(hour=16, minute=59, second=0, microsecond=0)
    return exit_ts

def extract_speaker(title):
    cleaned = re.sub(r"\b(Speaks?|Testifies|Testimony)\b", "", title).strip()
    parts = cleaned.split()
    return parts[-1] if parts else ""

ELIGIBLE_SPEAKERS = set(KNOWN_SPEAKERS) | set(MANUAL_SCORE_OVERRIDES.keys())

# ─────────────────────────────────────────────────────────────────────────────
# Build two event lists:
#   (A) signal_events  — original strategy (scored, non-neutral only)
#   (B) naive_events   — flat pay-fixed on EVERY eligible speech, bucket=+1
# ─────────────────────────────────────────────────────────────────────────────
def build_events(use_signal: bool):
    """
    use_signal=True  → original bucketed strategy (skip neutral)
    use_signal=False → naive: every eligible speech gets bucket=+1, bpv=-BASE_BPV
    """
    raw = []
    excl = defaultdict(int)

    for _, row in fed_speak_df.iterrows():
        title = row["Title"]
        speaker = extract_speaker(title)

        if speaker not in ELIGIBLE_SPEAKERS:
            excl["unknown_speaker"] += 1; continue

        ts_nyc = row["TimestampNYC"]
        if pd.isna(ts_nyc):
            excl["no_timestamp"] += 1; continue
        if ts_nyc.tzinfo is None:
            ts_nyc = NYC_tz.localize(ts_nyc)

        speech_date = ts_nyc.date()
        speech_time = ts_nyc.time()

        if speech_time < EARLIEST_SPEECH or speech_time > LATEST_SPEECH:
            excl["outside_market_hours"] += 1; continue
        if is_in_blackout(speech_date):
            excl["fomc_blackout"] += 1; continue
        if "press conference" in title.lower():
            excl["press_conference"] += 1; continue

        raw_score = get_speaker_score(speaker, speech_date)

        if use_signal:
            bucket = get_bucket(speaker, speech_date)
            if bucket == 0:
                excl["neutral_score"] += 1; continue
        else:
            # Naive: always pay fixed, flat size
            bucket = +1

        entry_ts = ts_nyc + ENTRY_OFFSET
        exit_ts  = ts_nyc + EXIT_OFFSET
        entry_ql = ql.Date(entry_ts.day, entry_ts.month, entry_ts.year)
        if not ql_cal.isBusinessDay(entry_ql):
            excl["entry_not_bday"] += 1; continue

        exit_ts = cap_exit(exit_ts, entry_ts)

        raw.append({
            "event_id":  row.get("EventId", len(raw)),
            "speaker":   speaker,
            "speech_ts": ts_nyc,
            "entry_ts":  entry_ts,
            "exit_ts":   exit_ts,
            "raw_score": raw_score,
            "bucket":    bucket,
            "bpv":       -bucket * BASE_BPV,
            "tag":       f"speech_{row.get('EventId', len(raw))}",
        })

    # No-stack filter
    raw.sort(key=lambda e: e["entry_ts"])
    filtered, last_exit = [], None
    for ev in raw:
        if last_exit is not None and ev["entry_ts"] < last_exit:
            continue
        filtered.append(ev)
        last_exit = ev["exit_ts"]

    label = "signal" if use_signal else "naive"
    print(f"  [{label}] tradeable after filters + no-stack: {len(filtered)}")
    return filtered


print("\nBuilding event lists …")
signal_events = build_events(use_signal=True)
naive_events  = build_events(use_signal=False)

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

def run_backtest(events, label=""):
    if not events:
        print(f"  [{label}] No events — skipping"); return pd.DataFrame()

    exit_ts_set = set(e["exit_ts"] for e in events)
    all_ts = sorted(set(e["entry_ts"] for e in events) | exit_ts_set)

    exit_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt, _ets=exit_ts_set: s in _ets
        ),
        actions=[UnwindPositionsAction(match_all=True, fee=0.0)],
    )

    entry_trigs = []
    for ev in events:
        _ts = ev["entry_ts"]
        _q  = IRSwapQuery(
            curve=CURVE, tenor=TENOR, value=IRSwapValue.NPV,
            structure_kwargs={"bpv": ev["bpv"]},
            tags=(ev["tag"],),
            meta={"speaker": ev["speaker"], "bucket": ev["bucket"],
                  "raw_score": ev["raw_score"]},
        )
        def _mk(ts):
            def fn(s, bt):
                return s == ts and len(bt.portfolio.positions) == 0
            return fn
        entry_trigs.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_mk(_ts)),
            actions=[AddQueryAction(query=_q)],
        ))

    strat = QueryStrategy(name=label, triggers=[exit_trig] + entry_trigs)
    bt    = QueryDrivenBacktest(time_grid=TimeGrid(all_ts), mdp=curve_mdp,
                                 strategy=strat, show_progress=True,
                                 progress_desc=label)
    bt.run()

    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    if cl.empty:
        print(f"  [{label}] WARNING: no closed positions"); return cl

    cl["speaker"]   = cl["source_query"].apply(lambda q: q.meta.get("speaker",""))
    cl["bucket"]    = cl["source_query"].apply(lambda q: q.meta.get("bucket",0))
    cl["raw_score"] = cl["source_query"].apply(lambda q: q.meta.get("raw_score",0))
    cl["opened_at"] = pd.to_datetime(cl["opened_at"])
    cl["closed_at"] = pd.to_datetime(cl["closed_at"])
    cl["year"]      = cl["opened_at"].dt.year
    cl["profitable"]= cl["realized_pnl"] > 0
    print(f"  [{label}] {len(cl)} trades closed, cum P&L ${cl['realized_pnl'].sum():,.0f}")
    return cl


print("\nRunning signal backtest …")
sig_cl = run_backtest(signal_events, "Signal (scored)")

print("\nRunning naive backtest …")
nav_cl = run_backtest(naive_events, "Naive (flat pay-fixed)")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: annualised metrics
# ─────────────────────────────────────────────────────────────────────────────
def metrics(cl):
    if cl.empty: return {}
    n   = len(cl)
    yrs = max((cl["opened_at"].max() - cl["opened_at"].min()).days / 365.25, 0.5)
    tpy = n / yrs
    avg = cl["realized_pnl"].mean()
    std = cl["realized_pnl"].std()
    sr  = (avg / std * np.sqrt(tpy)) if std > 0 else 0
    cum = cl["realized_pnl"].sum()
    hit = cl["profitable"].mean()
    mdd = (cl["realized_pnl"].cumsum() - cl["realized_pnl"].cumsum().cummax()).min()
    return {"trades": n, "cum_pnl": cum, "avg_pnl": avg, "std_pnl": std,
            "hit_rate": hit, "sharpe": sr, "max_dd": mdd, "tpy": tpy}


# ─────────────────────────────────────────────────────────────────────────────
# 1. NAIVE BENCHMARK COMPARISON
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  1. NAIVE BENCHMARK — flat pay-fixed vs scored signal")
print("="*65)

sm = metrics(sig_cl)
nm = metrics(nav_cl)

rows = []
for label, m in [("Signal (scored)", sm), ("Naive (flat pay-fixed)", nm)]:
    rows.append({
        "Strategy":    label,
        "Trades":      m["trades"],
        "Trades/yr":   f"{m['tpy']:.0f}",
        "Cum P&L":     f"${m['cum_pnl']:,.0f}",
        "Avg P&L":     f"${m['avg_pnl']:,.0f}",
        "Hit Rate":    f"{m['hit_rate']:.1%}",
        "Sharpe":      f"{m['sharpe']:.2f}",
        "Max DD":      f"${m['max_dd']:,.0f}",
    })
comp_df = pd.DataFrame(rows)
print(comp_df.to_string(index=False))

# Cumulative P&L overlay
if not sig_cl.empty and not nav_cl.empty:
    fig, ax = plt.subplots(figsize=(13, 6))

    # Normalize naive to same base DV01 per trade as signal (bucket=+1 always → comparable)
    ax.plot(sig_cl["opened_at"], sig_cl["realized_pnl"].cumsum(),
            label=f"Signal (scored)  SR={sm['sharpe']:.2f}", color="steelblue", lw=2)
    ax.plot(nav_cl["opened_at"], nav_cl["realized_pnl"].cumsum(),
            label=f"Naive (flat pay) SR={nm['sharpe']:.2f}", color="darkorange",
            lw=2, ls="--")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title("Signal vs Naive Benchmark — Cumulative P&L")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(r"C:\Users\chris\clee\ARBS\notebooks\backtests\pm_feedback_naive_vs_signal.png", dpi=150)
    plt.close()
    print("  → Saved pm_feedback_naive_vs_signal.png")


# ─────────────────────────────────────────────────────────────────────────────
# 2. WALLER CHRONOLOGICAL P&L (label decay)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  2. WALLER CHRONOLOGICAL P&L — label decay illustration")
print("="*65)

if not sig_cl.empty:
    waller = sig_cl[sig_cl["speaker"] == "Waller"].copy().sort_values("opened_at")

    if waller.empty:
        print("  No Waller trades found in closed log.")
    else:
        waller["cum_pnl"] = waller["realized_pnl"].cumsum()

        # Split at 2025-06-01 as rough pivot date
        pivot = pd.Timestamp("2025-06-01", tz="America/New_York")
        pre   = waller[waller["opened_at"] <  pivot]
        post  = waller[waller["opened_at"] >= pivot]

        print(f"  Total Waller trades: {len(waller)}")
        print(f"  Total P&L:           ${waller['realized_pnl'].sum():,.0f}")
        print(f"  Hit rate:            {waller['profitable'].mean():.1%}")
        print(f"  Pre-Jun 2025  ({len(pre):2d} trades): ${pre['realized_pnl'].sum():,.0f}  "
              f"hit={pre['profitable'].mean():.0%}")
        print(f"  Post-Jun 2025 ({len(post):2d} trades): ${post['realized_pnl'].sum():,.0f}  "
              f"hit={post['profitable'].mean():.0%}" if not post.empty else
              f"  Post-Jun 2025:  (no trades)")

        fig, axes = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={"height_ratios":[2,1]})

        # Cumulative P&L
        ax1 = axes[0]
        ax1.plot(waller["opened_at"], waller["cum_pnl"], color="navy", lw=2)
        ax1.fill_between(waller["opened_at"], 0, waller["cum_pnl"],
                         where=waller["cum_pnl"] >= 0, alpha=0.15, color="green")
        ax1.fill_between(waller["opened_at"], 0, waller["cum_pnl"],
                         where=waller["cum_pnl"] < 0,  alpha=0.15, color="red")
        ax1.axvline(pd.Timestamp("2025-01-01", tz="America/New_York"),
                    color="gray", ls="--", lw=1, label="2025 start")
        ax1.axvline(pivot, color="orange", ls="--", lw=1.5, label="Jun 2025 (pivot)")
        ax1.axhline(0, color="k", lw=0.5)
        ax1.set_title("Waller Cumulative P&L — Label Decay Illustration")
        ax1.set_ylabel("Cumulative P&L ($)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Per-trade bar
        ax2 = axes[1]
        colors = ["green" if x > 0 else "red" for x in waller["realized_pnl"]]
        ax2.bar(range(len(waller)), waller["realized_pnl"].values, color=colors, alpha=0.7)
        ax2.axhline(0, color="k", lw=0.5)
        ax2.set_xlabel("Trade #")
        ax2.set_ylabel("Trade P&L ($)")
        ax2.grid(True, alpha=0.3)

        # Annotate raw_score on x-axis
        for i, (_, r) in enumerate(waller.iterrows()):
            ax2.text(i, min(r["realized_pnl"], 0) - 5000,
                     f"{r['raw_score']:.0f}" if not pd.isna(r["raw_score"]) else "?",
                     ha="center", va="top", fontsize=7, color="gray")

        plt.tight_layout()
        plt.savefig(r"C:\Users\chris\clee\ARBS\notebooks\backtests\pm_feedback_waller_decay.png", dpi=150)
        plt.close()
        print("  → Saved pm_feedback_waller_decay.png")


# ─────────────────────────────────────────────────────────────────────────────
# 3. TRANSACTION COST SENSITIVITY (extended — also shows breakeven bps)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("  3. TRANSACTION COST SENSITIVITY")
print("="*65)

if not sig_cl.empty:
    avg_abs_bucket = sig_cl["bucket"].abs().mean()
    cost_bps_levels = [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]
    cost_rows = []

    for cost_bps in cost_bps_levels:
        # Round-trip cost = cost_bps * DV01 per trade (entry + exit legs)
        # DV01 = |bucket| * BASE_BPV; cost in $ = cost_bps * DV01 / 10_000 * 2 sides
        # Simplification used in notebook: cost_bps * |bucket| * BASE_BPV / 10_000
        rt_cost = sig_cl["bucket"].abs() * BASE_BPV * cost_bps / 10_000
        adj = sig_cl["realized_pnl"] - rt_cost
        adj_cum  = adj.sum()
        adj_avg  = adj.mean()
        adj_std  = adj.std()
        adj_sr   = (adj_avg / adj_std * np.sqrt(sm["tpy"])) if adj_std > 0 else 0
        adj_hit  = (adj > 0).mean()
        cost_rows.append({
            "Cost (bps RT)":   cost_bps,
            "Cost/trade ($)":  rt_cost.mean(),
            "Cum P&L":         adj_cum,
            "Avg P&L":         adj_avg,
            "Hit Rate":        adj_hit,
            "Sharpe":          adj_sr,
            "Sharpe Δ":        adj_sr - sm["sharpe"],
        })

    cost_df = pd.DataFrame(cost_rows)
    fmt = {
        "Cost (bps RT)":  "{:.2f}",
        "Cost/trade ($)": "${:,.0f}",
        "Cum P&L":        "${:,.0f}",
        "Avg P&L":        "${:,.0f}",
        "Hit Rate":       "{:.1%}",
        "Sharpe":         "{:.2f}",
        "Sharpe Δ":       "{:+.2f}",
    }
    for col, f in fmt.items():
        cost_df[col] = cost_df[col].apply(lambda x: f.format(x))
    print(cost_df.to_string(index=False))

    # Find breakeven cost
    be_df = pd.DataFrame(cost_rows)
    be_idx = (be_df["Cum P&L"] <= 0).idxmax()
    if be_df.loc[be_idx, "Cum P&L"] > 0:
        print(f"\n  Breakeven: > {cost_bps_levels[-1]} bps RT (strategy profitable at all tested levels)")
    else:
        be_bps = cost_bps_levels[be_idx]
        print(f"\n  Breakeven: ~{be_bps} bps RT (cum P&L turns negative)")

    fig, ax = plt.subplots(figsize=(10, 5))
    raw_rows = pd.DataFrame([{
        "cost_bps": r["cost_bps"] if isinstance(r, dict) else cost_bps_levels[i],
        "sharpe":   float(r["Sharpe"]) if isinstance(r, str) else r,
    } for i, r in enumerate(cost_rows)])
    raw_rows2 = pd.DataFrame(cost_rows[:])  # original numeric rows
    sharpes = [r["Sharpe"] for r in cost_rows]
    # Re-compute numeric
    numeric_rows = []
    for cost_bps in cost_bps_levels:
        rt_cost = sig_cl["bucket"].abs() * BASE_BPV * cost_bps / 10_000
        adj = sig_cl["realized_pnl"] - rt_cost
        adj_avg = adj.mean(); adj_std = adj.std()
        adj_sr  = (adj_avg / adj_std * np.sqrt(sm["tpy"])) if adj_std > 0 else 0
        numeric_rows.append({"bps": cost_bps, "sharpe": adj_sr, "cum_pnl": adj.sum()})
    nr_df = pd.DataFrame(numeric_rows)
    ax.plot(nr_df["bps"], nr_df["sharpe"], "o-", color="steelblue", lw=2)
    ax.axhline(0, color="k", lw=0.5)
    ax.axhline(sm["sharpe"], color="green", ls="--", lw=1, label=f"Zero-cost Sharpe={sm['sharpe']:.2f}")
    ax.set_xlabel("Round-trip transaction cost (bps)")
    ax.set_ylabel("Sharpe Ratio")
    ax.set_title("Sharpe Ratio vs Transaction Cost")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(r"C:\Users\chris\clee\ARBS\notebooks\backtests\pm_feedback_tcost.png", dpi=150)
    plt.close()
    print("  → Saved pm_feedback_tcost.png")

print("\nAll analyses complete.")
