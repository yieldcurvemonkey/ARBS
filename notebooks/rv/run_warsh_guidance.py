"""Run the Warsh-guidance information study and print every result.

    conda run -n stir python notebooks/rv/run_warsh_guidance.py

Offline: ZQ settles from the shared cache, speech corpora from disk, the
release calendar from its parquet core. No Excel, no COM.

The prediction table this is scored against was fixed before the run, in
``docs/reports/2026-08-25-warsh-guidance-information-PREREG.md``.
"""
from __future__ import annotations

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

import fed_event_conditioning as FEC  # noqa: E402
import warsh_guidance_information as W  # noqa: E402

pd.set_option("display.width", 210)
START, END = "2021-01-27", "2026-08-25"
OUT = HERE / "warsh_guidance_results.pkl"


def _p(*a):
    print(*a, flush=True)


def line(t):
    _p("\n" + "=" * 88); _p(t); _p("=" * 88)


def main() -> int:
    t0 = time.time()
    res = {}

    line("0. BUILD + GATES")
    hist = FEC.meeting_step_history(START, END)
    _p(f"ladder: {hist.shape}  {hist['as_of'].min().date()}..{hist['as_of'].max().date()}"
       f"   {hist['as_of'].nunique()} sessions")

    g1 = W.gate_boundary_is_a_real_meeting(hist)
    _p(f"G-W1 boundary is a real meeting: {g1}")

    dpath = W.daily_path_change(hist, n_meetings=2)
    _p(f"daily path changes: {len(dpath)} steps "
       f"{dpath.index.min().date()}..{dpath.index.max().date()}")
    g2 = W.gate_dpath_never_spans_a_resolution(hist, dpath)
    _p(f"G-W2 no step spans a resolution: {g2}")

    cal = FEC.setpiece_calendar(START, END)
    corpora = {}
    for src in ("jpm", "fedlock"):
        cfg = dataclasses.replace(FEC.PRIMARY, source=src)
        sent, sc = FEC.load_daily_sentiment(cfg, START, END)
        ev = FEC.build_events(cfg, sc, START, END, calendar=cal)
        panel, reasons = FEC.event_panel(ev, hist, sent, cfg)
        corpora[src] = dict(cfg=cfg, sent=sent, scores=sc, events=ev,
                            panel=panel, reasons=reasons)
        _p(f"[{src}] {len(sc)} scored rows -> {len(ev)} events -> "
           f"{len(panel)} usable panel rows   drops {reasons}")
        g3 = W.gate_warsh_window_is_not_empty(panel)
        _p(f"       G-W3 {g3['counts']}")
    res["gates"] = {"G-W1": g1, "G-W2": g2}

    # ---------------------------------------------------------------- T1
    line("T1. ARRIVAL RATE -- is he speaking less? (SEASON MATCHED)")
    _p("The window is 18 Jun to 25 Aug, which contains the summer recess and the")
    _p("run-up to Jackson Hole. Matched to the same calendar window of prior")
    _p("years, not to an all-season base rate.\n")
    t1 = {}
    for src, d in corpora.items():
        dense = pd.Timestamp("2023-01-01") if src == "jpm" else None
        sp = d["scores"]
        # discretionary only: drop days that are set-piece calendar days
        spd = pd.to_datetime(sp["date"]).dt.normalize()
        setp = set(pd.DatetimeIndex(cal["date"]).normalize())
        disc = sp[~spd.isin(setp)]
        a = W.arrival_rate(disc, dense_from=dense)
        t1[src] = a
        _p(f"[{src}]  (corpus dense from {dense.date() if dense is not None else 'start'})")
        _p("   " + a.to_string(index=False).replace("\n", "\n   "))
        _p(f"   matched mean {a.attrs.get('matched_mean_per_bd', float('nan')):.4f}/bd"
           f"   warsh {a.attrs.get('warsh_per_bd', float('nan')):.4f}/bd"
           f"   ratio {a.attrs.get('ratio', float('nan')):.3f}"
           f"   exact-Poisson p {a.attrs.get('poisson_p', float('nan')):.4f}")
    res["T1"] = t1

    # ---------------------------------------------------------------- T2
    line("T2. THE PREMISE -- is the priced path less degenerate under Warsh?")
    _p("Distance from an all-or-nothing outcome: |jump - 25*round(jump/25)|,")
    _p("averaged over the next 4 live meetings. 0 = every meeting priced as a")
    _p("near-certainty, 12.5 = every meeting priced as a coin toss.\n")
    dg = W.degeneracy_distance(hist, n_meetings=4)
    dg["era"] = W.era_of(dg.index)
    t2 = (dg.groupby("era")[["degen_dist_bp", "degen_dist_front_bp"]]
            .agg(["size", "mean", "median", "std"]))
    res["T2"] = {"daily": dg, "summary": t2}
    _p(t2.to_string())
    from scipy import stats as _st
    a_ = dg.loc[dg["era"] == "guidance", "degen_dist_bp"].dropna()
    b_ = dg.loc[dg["era"] == "warsh", "degen_dist_bp"].dropna()
    if len(b_) > 2:
        u = _st.mannwhitneyu(b_, a_, alternative="two-sided")
        _p(f"\n   Mann-Whitney warsh vs guidance: U {u.statistic:.0f}  p {u.pvalue:.4g}"
           f"   (n {len(b_)} vs {len(a_)})")
        _p(f"   warsh mean {b_.mean():.3f}bp vs guidance {a_.mean():.3f}bp"
           f"   -> {'MORE' if b_.mean() > a_.mean() else 'LESS'} coin-toss-like")
        _p(f"   NOTE: daily values are heavily autocorrelated; this p is a")
        _p(f"   description of the two samples, not {len(b_)} independent draws.")
    _p("\n   the last 10 sessions, front meeting:")
    _p("   " + dg.tail(10)[["degen_dist_bp", "degen_dist_front_bp", "abs_path_bp"]]
       .to_string().replace("\n", "\n   "))

    # ---------------------------------------------------------------- T3
    line("T3. PER-EVENT RESPONSE -- scheduled vs discretionary")
    t3 = {}
    for src, d in corpora.items():
        summ = W.response_summary(d["panel"])
        place = W.placement_table(d["panel"])
        t3[src] = {"summary": summ, "placement": place}
        _p(f"\n[{src}] |y| = |change in the summed jump of a FIXED meeting pair|, bp")
        _p("   " + summ.to_string(index=False).replace("\n", "\n   "))
        _p(f"\n   every Warsh-era event, placed in the guidance distribution of its OWN type:")
        _p("   " + place.to_string(index=False).replace("\n", "\n   "))
        sch = place[place["klass"] == "scheduled"]
        if len(sch):
            _p(f"\n   scheduled Warsh events: n {len(sch)}, median placement "
               f"{sch['pct_in_guidance'].median():.0f}th percentile")
            _p("   NO t-statistic is computed on this. Six percentiles are the result.")
    # when does the scheduled test become decidable?
    n_sched_warsh = int((W.klass_of(corpora['jpm']['panel']['type']) == 'scheduled').sum()
                        & 1) if False else None
    pl = t3["jpm"]["placement"]
    n_now = int((pl["klass"] == "scheduled").sum())
    for need in (20, 30):
        when = W.decidable_date(n_now, need, per_month=2.65)
        _p(f"\n   at 2.65 scheduled events/month, n={need} is reached {when.date()}"
           f"  (have {n_now})")
    res["T3"] = t3

    # ---------------------------------------------------------------- T4
    line("T4. INFORMATION OR CONFUSION -- does uncertainty FALL at events?")
    _p("Change in degeneracy distance across each event window, on a meeting set")
    _p("fixed strictly after t+5 so every horizon reads the same meetings.")
    _p("Information -> distance FALLS (the market becomes more decided).")
    _p("Opacity (the Citadel reading) -> it does not fall, or rises after.\n")
    t4 = {}
    for src, d in corpora.items():
        rows = []
        for _, e in d["panel"].iterrows():
            r = W.fixed_window_degeneracy(hist, pd.Timestamp(e["date"]))
            if r is None:
                continue
            r["type"] = e["type"]
            r["abs_y"] = abs(float(e["y"]))
            rows.append(r)
        U = pd.DataFrame(rows)
        if U.empty:
            _p(f"[{src}] no usable windows"); continue
        U["era"] = W.era_of(U["date"])
        U["klass"] = W.klass_of(U["type"])
        agg = (U.groupby(["klass", "era"])
                 .agg(n=("d_degen_t0", "size"),
                      degen_pre=("degen_pre", "mean"),
                      d_t0=("d_degen_t0", "mean"),
                      d_t1=("d_degen_t1", "mean"),
                      d_t5=("d_degen_t5", "mean"),
                      abs_y=("abs_y", "mean"))
                 .reset_index())
        t4[src] = {"rows": U, "agg": agg}
        _p(f"[{src}]")
        _p("   " + agg.to_string(index=False).replace("\n", "\n   "))
        for k in ("scheduled", "discretionary"):
            s = agg[agg["klass"] == k]
            if set(s["era"]) >= {"warsh", "guidance"}:
                for h in ("d_t0", "d_t1", "d_t5"):
                    wv = float(s.loc[s["era"] == "warsh", h].iloc[0])
                    gv = float(s.loc[s["era"] == "guidance", h].iloc[0])
                    _p(f"   DiD {k:14s} {h}: warsh {wv:+.4f} - guidance {gv:+.4f}"
                       f" = {wv - gv:+.4f} bp"
                       f"   ({'uncertainty falls MORE' if wv - gv < 0 else 'uncertainty falls LESS / rises'})")
    res["T4"] = t4

    # ---------------------------------------------------------------- T5
    line("T5. VARIANCE DECOMPOSITION -- speaker / release / quiet")
    rel = W.release_days(START, END)
    _p(f"high-impact USD releases: {len(rel)} days "
       f"{rel.min().date()}..{rel.max().date()}")
    t5 = {}
    for src, d in corpora.items():
        evd = pd.DatetimeIndex(pd.to_datetime(d["events"]["date"])).normalize()
        vb = W.variance_buckets(dpath, evd, rel)
        t5[src] = vb
        _p(f"\n[{src}] speaker days take precedence over release days on collision")
        _p("   " + vb.to_string(index=False).replace("\n", "\n   "))
        q = vb[(vb["bucket"] == "quiet")]
        for _, r in q.iterrows():
            if r["days"] < 10:
                _p(f"   WARNING: the quiet bucket in the {r['era']} era holds only "
                   f"{int(r['days'])} days -- its share is not interpretable.")
    res["T5"] = t5

    # ---------------------------------------------------------------- T6
    line("T6. SILENCE GAPS -- does the strip do more work when he is quiet?")
    t6 = {}
    for src, d in corpora.items():
        gaps = W.silence_gaps(d["scores"], dpath,
                              setpiece=pd.DatetimeIndex(cal["date"]))
        if gaps.empty:
            _p(f"[{src}] no gaps"); continue
        agg = (gaps.groupby("era")
                   .agg(n=("len_bd", "size"), mean_len=("len_bd", "mean"),
                        mean_abs=("abs_move_bp", "mean"),
                        mean_rms=("rms_bp", "mean")).reset_index())
        # like-for-like on length: per business day inside the gap
        gaps["abs_per_bd"] = gaps["abs_move_bp"] / gaps["len_bd"]
        agg2 = gaps.groupby("era")["abs_per_bd"].agg(["size", "mean", "median"])
        t6[src] = {"gaps": gaps, "agg": agg, "per_bd": agg2}
        _p(f"\n[{src}] gaps of >= 3 consecutive non-speech business days")
        _p("   " + agg.to_string(index=False).replace("\n", "\n   "))
        _p("   per business day INSIDE the gap (length-matched):")
        _p("   " + agg2.to_string().replace("\n", "\n   "))
    res["T6"] = t6

    with open(OUT, "wb") as f:
        pickle.dump(res, f)
    _p(f"\nwrote {OUT}   ({time.time() - t0:.0f}s)")
    _p("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
