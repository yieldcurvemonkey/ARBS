"""Run the Fedspeak event-conditioning study headless and pickle the results.

    conda run -n stir python notebooks/rv/fed_event_conditioning_run.py

Order is deliberate and matches the brief: the forward read first (it is
arithmetic on an already-measured lead and it answers the question that prompted
the study), then the gates, then Study A, then the regime split. Study A's
verdict is applied by a pre-registered rule, not by reading the table.

Budget ~4 minutes, dominated by the meeting-step history (~1,400 business dates
at ~55 ms each). ``--quick`` shortens the sample for a wiring check.
"""
from __future__ import annotations

import argparse
import dataclasses
import io
import pathlib
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_event_conditioning as E  # noqa: E402

OUT = HERE / "fed_event_conditioning_results.pkl"
START, END = "2021-01-27", "2026-08-21"

#: The dates the forward read is asked about. Jackson Hole 2026 is the question
#: that prompted the study; the two December-adjacent dates are where the lead
#: says the recent soft patch actually lands.
FORWARD_DATES = ("2026-08-28", "2026-09-16", "2026-10-28", "2026-12-09")


def _p(*a):
    print(*a, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--null-draws", type=int, default=400)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    start = "2024-01-02" if args.quick else START
    draws = 60 if args.quick else args.null_draws

    res = {"start": start, "end": END}
    t_all = time.time()

    # ---- 0. the forward read ------------------------------------------
    _p("=" * 74); _p("0. what the MEASURED lead implies for the dates in question")
    _p("=" * 74)
    fr = E.forward_read(FORWARD_DATES)
    res["forward_read"] = fr
    _p(fr.to_string(index=False))
    _p("\n  z_composite > 0 means the data ran HOT into the window the lead points")
    _p("  at, i.e. the lead predicts Fedspeak leans HAWKISH on that date.")

    # ---- 1. gates -----------------------------------------------------
    _p("\n" + "=" * 74); _p("1. gates"); _p("=" * 74)
    sch = E.gate_schedule_choice()
    res["gate_schedule"] = sch
    _p(f"G-E1  the two in-repo FOMC schedules disagree on {len(sch)} dates:")
    _p("   " + sch.to_string(index=False).replace("\n", "\n   ") if len(sch)
       else "   (none)")
    _p("   this study uses SDRUtils.analytics.fomc throughout.")

    # ---- 2. the price side --------------------------------------------
    _p("\n" + "=" * 74); _p("2. the priced meeting step"); _p("=" * 74)
    t0 = time.time()
    hist = E.meeting_step_history(start, END)
    res["hist_span"] = (hist["as_of"].min(), hist["as_of"].max())
    nd = hist["as_of"].nunique()
    _p(f"  {nd} dates, {len(hist)} meeting rows, "
       f"{hist['as_of'].min().date()}..{hist['as_of'].max().date()} "
       f"in {time.time()-t0:.0f}s")
    _p(f"  stale legs: {int(hist['stale'].sum())} of {len(hist)} "
       f"({100*hist['stale'].mean():.1f}%) -- flagged by the ladder, dropped here")
    _p(f"  live meetings per date: median {hist.groupby('as_of')['n_live'].first().median():.0f}")
    res["hist_summary"] = {"dates": int(nd), "rows": int(len(hist)),
                           "stale_share": float(hist["stale"].mean())}

    # ---- 3. Study A, per source ---------------------------------------
    # One calendar, both arms. See setpiece_calendar's docstring: the JPM corpus
    # has no event-type field, so without this its set-piece universe would be
    # decisions and minutes only and the two arms would not be comparable.
    cal = E.setpiece_calendar(start, END)
    res["calendar"] = cal
    _p(f"\n  shared set-piece calendar: {len(cal)} events, by type "
       f"{dict(cal['type'].value_counts())}")

    # The third arm exists so that "the two judges disagree in sign" is a
    # statement about the JUDGES and not about the sample: it is FedLock scored,
    # on the JPM arm's own window.
    ARMS = (("jpm", start, "JPM, publication-gated -- TRADEABLE"),
            ("fedlock", start,
             "FedLock V3, one vintage -- HISTORICAL ASSOCIATION ONLY"),
            ("fedlock_jpm_window", None,
             "FedLock scores on the JPM arm's window -- isolates the JUDGE"))
    res["arms"] = {}
    jpm_start = None
    for source, arm_start, label in ARMS:
        real_source = "fedlock" if source == "fedlock_jpm_window" else source
        arm_start = arm_start or jpm_start or start
        cfg = dataclasses.replace(E.PRIMARY, source=real_source)
        _p("\n" + "=" * 74)
        _p(f"3. STUDY A on {source}   ({label})")
        _p(f"   window {arm_start} .. {END}"); _p("=" * 74)
        try:
            sent, scores = E.load_daily_sentiment(cfg, arm_start, END)
            if source == "jpm":
                fin = sent["z"].dropna()
                jpm_start = str(fin.index.min().date()) if len(fin) else start
            ev = E.build_events(cfg, scores, arm_start, END, calendar=cal)
            jh = E.gate_jackson_hole(ev, scores)
            panel, reasons = E.event_panel(ev, hist, sent, cfg)
            if arm_start != start:
                panel = panel[panel["date"] >= pd.Timestamp(arm_start)]
            g3 = E.gate_y_is_a_fixed_pair(panel)
        except Exception as exc:  # noqa: BLE001
            _p(f"  FAILED: {type(exc).__name__}: {exc}")
            res["arms"][source] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

        _p(f"  daily sentiment: {int(sent['sentiment'].notna().sum())} days finite, "
           f"z finite on {int(sent['z'].notna().sum())}")
        _p(f"  events built: {len(ev)}   by type: "
           f"{dict(ev['type'].value_counts())}")
        _p(f"  panel: {len(panel)} usable events;  drops: "
           f"{ {k: v for k, v in reasons.items() if k != 'kept'} }")
        _p(f"  G-E3 fixed-pair check: {g3}")
        if panel.empty:
            res["arms"][source] = {"error": "empty panel", "reasons": reasons}
            continue
        _p(f"  by type: {dict(panel['type'].value_counts())}")

        a = E.study_a(panel, ev, hist, sent, cfg, null_draws=draws)
        v = E.verdict(a)
        a.update({"arm": source, "window_start": arm_start,
                  "panel": panel, "events": ev, "reasons": reasons,
                  "jackson_hole_gate": jh, "gate_fixed_pair": g3,
                  "sentiment": sent, "verdict": v, "label": label})
        res["arms"][source] = a

        _p("\n" + a["table"].to_string(index=False))
        _p(f"\n  PRIMARY CUT ({a['primary_cut']}):")
        pr, bo, nu = a["primary"], a["primary_boot"], a["null"]
        _p(f"    beta   {pr['beta']:+.4f} bp per sd of sentiment   "
           f"(HC3 t {pr['t']:+.2f}, R2 {pr['r2']:.4f}, n {pr['n']})")
        _p(f"    boot   95% CI [{bo['lo']:+.4f}, {bo['hi']:+.4f}]   "
           f"share of draws positive {bo['share_positive']:.2f}")
        if nu.get("draws"):
            _p(f"    null   matched non-event days: median {nu['beta_q50']:+.4f}, "
               f"q05 {nu['beta_q05']:+.4f}, q95 {nu['beta_q95']:+.4f} "
               f"({nu['draws']} draws from {nu['pool_days']} pool days)")
        else:
            _p(f"    null   unavailable: {nu.get('note')}")
        pd_ = a["primary_dev"]
        _p(f"    x_dev  beta {pd_['beta']:+.4f} (t {pd_['t']:+.2f}, n {pd_['n']}) "
           f"-- the event's own score minus the running index")
        sz = a.get("size") or {}
        if sz:
            _p(f"    SIZE   a typical event moves the index {sz['sd_of_x']:.3f} sd, "
               f"so the fitted path move is {sz['bp_per_1sd_of_x']:+.3f}bp per "
               f"1-sd event")
            _p(f"           at a 90th-percentile event {sz['bp_at_the_90th_pct_event']:+.3f}bp, "
               f"against a {sz['sr3_round_trip_bp']:.2f}bp round trip -> "
               f"{'CLEARS' if sz['clears_the_spread'] else 'DOES NOT CLEAR'} it")
            _p(f"           {sz['events_per_year']:.1f} such events a year")
        pw = a.get("power") or {}
        if pw and np.isfinite(pw.get("events_for_abs_t_2", np.nan)):
            _p(f"    POWER  to reach |t| = 2 at this slope and this noise would "
               f"take {pw['events_for_abs_t_2']:.0f} events")
            _p(f"           i.e. {pw['extra_events_needed']:.0f} more than the "
               f"{pw['n_observed']} in hand = "
               f"{pw['years_at_this_rate']:.0f} more years at {sz['events_per_year']:.0f}/yr")
        if "terciles" in a:
            _p("\n  terciles of x (non-decision events):")
            _p("   " + a["terciles"].to_string().replace("\n", "\n   "))
        _p("\n  VERDICT (pre-registered rule):")
        for k, ok in v["tests"].items():
            _p(f"    [{'PASS' if ok else 'FAIL'}] {k}")
        _p(f"    -> {'ALIVE' if v['alive'] else 'DEAD -- stop at Study A'}")

    # ---- 4. the regime split ------------------------------------------
    _p("\n" + "=" * 74)
    _p("4. the regime reading of #491 -- does the lead track guidance regimes?")
    _p("=" * 74)
    try:
        rs = E.regime_lead_split()
        res["regime_split"] = rs
        _p(rs.to_string(index=False))
        _p("\n  FedLock scores are one jointly-fitted vintage, so this is a")
        _p("  HISTORICAL ASSOCIATION across regimes, not a backtest of any of them.")
    except Exception as exc:  # noqa: BLE001
        _p(f"  FAILED: {type(exc).__name__}: {exc}")
        res["regime_split"] = pd.DataFrame([{"error": str(exc)}])

    with open(args.out, "wb") as f:
        pickle.dump(res, f)
    _p(f"\nwrote {args.out}  ({time.time()-t_all:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
