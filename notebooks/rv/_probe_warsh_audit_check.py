"""Verify the adversarial audit's four load-bearing counterclaims before retracting.

The audit returned REFUTED on 8 of 12 lenses, including the study's headline. That
is a large retraction to make on someone else's arithmetic, and the desk rule is
not to take an agent's numbers at face value. Each counterclaim below is
recomputed here from the same sources the study used.

  A  T3 medians       -- the audit says discretionary is UP on medians, so the
                         "scheduled up / discretionary down" asymmetry is a
                         mean artefact and the anti-selection headline dies.
  B  T4 level control -- the audit says the 5-day change is mostly minus its own
                         starting level, event days happened to start lower, and
                         controlling for that collapses the contrast to ~+0.44
                         with p ~0.26.
  C  T6 silence       -- the audit says 3 of 5 Warsh "silence" gaps contain an
                         FOMC decision or a minutes release, because
                         silence_gaps() defines silence from the SPEECH book and
                         never consults the set-piece calendar. That is a code
                         bug if true.
  D  T1 subject       -- the audit says the arrival-rate test counts ~20 FOMC
                         speakers, not Warsh, so it cannot detect Warsh's own
                         silence at all.
"""
from __future__ import annotations

import dataclasses
import io
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import statsmodels.api as sm  # noqa: E402

import fed_event_conditioning as FEC  # noqa: E402
import warsh_guidance_information as W  # noqa: E402

pd.set_option("display.width", 220)
START, END = "2021-01-27", "2026-08-25"


def line(t):
    print("\n" + "=" * 86 + f"\n{t}\n" + "=" * 86, flush=True)


print("building ...", flush=True)
hist = FEC.meeting_step_history(START, END)
cal = FEC.setpiece_calendar(START, END)
setp = set(pd.DatetimeIndex(cal["date"]).normalize())

corp = {}
for src in ("jpm", "fedlock"):
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    sent, sc = FEC.load_daily_sentiment(cfg, START, END)
    ev = FEC.build_events(cfg, sc, START, END, calendar=cal)
    panel, _ = FEC.event_panel(ev, hist, sent, cfg)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["era"] = W.era_of(panel["date"])
    panel["klass"] = W.klass_of(panel["type"])
    panel["abs"] = panel["y"].abs()
    corp[src] = dict(scores=sc, events=ev, panel=panel)

# ------------------------------------------------------------------ A
line("A. T3 -- MEAN vs MEDIAN. Does 'discretionary went DOWN' survive?")
for src, d in corp.items():
    p = d["panel"]
    g = (p.groupby(["klass", "era"])["abs"]
           .agg(n="size", mean="mean", median="median").reset_index())
    print(f"[{src}]")
    print("   " + g.to_string(index=False).replace("\n", "\n   "))
    for k in ("scheduled", "discretionary"):
        s = g[g["klass"] == k]
        gm = float(s.loc[s["era"] == "guidance", "mean"].iloc[0])
        wm = float(s.loc[s["era"] == "warsh", "mean"].iloc[0])
        gd = float(s.loc[s["era"] == "guidance", "median"].iloc[0])
        wd = float(s.loc[s["era"] == "warsh", "median"].iloc[0])
        print(f"   -> {k:14s} MEAN {gm:.3f}->{wm:.3f} {'UP' if wm>gm else 'DOWN':4s}"
              f"   MEDIAN {gd:.3f}->{wd:.3f} {'UP' if wd>gd else 'DOWN'}")
    print()

# ------------------------------------------------------------------ B
line("B. T4 -- does the contrast survive controlling for the starting level?")
print("Every session measured identically, then event vs non-event WITHIN each era,")
print("with and without degen_pre on the right-hand side.\n")
sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
rows = []
for dt in sess:
    r = W.fixed_window_degeneracy(hist, dt)
    if r is not None:
        rows.append(r)
ALL = pd.DataFrame(rows).set_index("date")
ALL["era"] = W.era_of(ALL.index)

for src, d in corp.items():
    evd = set(pd.DatetimeIndex(pd.to_datetime(d["events"]["date"])).normalize())
    A = ALL.copy()
    A["is_event"] = [x in evd for x in pd.DatetimeIndex(A.index).normalize()]
    print(f"[{src}]")
    # how strongly does the 5-day change just undo its own starting level?
    for era in ("warsh", "guidance"):
        sub = A[A["era"] == era].dropna(subset=["d_degen_t5", "degen_pre"])
        m = sm.OLS(sub["d_degen_t5"], sm.add_constant(sub["degen_pre"])).fit()
        print(f"   {era:9s} d_t5 ~ degen_pre: slope {m.params['degen_pre']:+.3f} "
              f"(t {m.tvalues['degen_pre']:+.2f})  R2 {m.rsquared:.3f}  n {int(m.nobs)}")
    for era in ("warsh", "guidance"):
        sub = A[A["era"] == era].dropna(subset=["d_degen_t5", "degen_pre"]).copy()
        sub["ev"] = sub["is_event"].astype(float)
        pre_e = sub.loc[sub["ev"] == 1, "degen_pre"].mean()
        pre_n = sub.loc[sub["ev"] == 0, "degen_pre"].mean()
        raw = (sub.loc[sub["ev"] == 1, "d_degen_t5"].mean()
               - sub.loc[sub["ev"] == 0, "d_degen_t5"].mean())
        m = sm.OLS(sub["d_degen_t5"],
                   sm.add_constant(sub[["degen_pre", "ev"]])).fit(cov_type="HC3")
        print(f"   {era:9s} start level: event {pre_e:.3f} vs non-event {pre_n:.3f}"
              f"  (gap {pre_e-pre_n:+.3f})")
        print(f"   {era:9s} contrast RAW {raw:+.4f}   "
              f"LEVEL-CONTROLLED {m.params['ev']:+.4f} "
              f"(t {m.tvalues['ev']:+.2f}, p {m.pvalues['ev']:.4f})")
    print()

# ------------------------------------------------------------------ C
line("C. T6 -- do the Warsh 'silence' gaps contain set-piece events?")
dpath = W.daily_path_change(hist, n_meetings=2)
for src, d in corp.items():
    gaps = W.silence_gaps(d["scores"], dpath)
    wg = gaps[gaps["era"] == "warsh"]
    print(f"[{src}] {len(wg)} Warsh gaps")
    bad = 0
    for _, r in wg.iterrows():
        span = pd.bdate_range(r["start"], r["end"]).normalize()
        hits = sorted(set(span) & setp)
        if hits:
            bad += 1
            kinds = cal[cal["date"].isin(hits)]["type"].unique().tolist()
            print(f"   {r['start'].date()}..{r['end'].date()} ({int(r['len_bd'])}bd)"
                  f"  CONTAINS {[str(h.date()) for h in hits]} {kinds}")
        else:
            print(f"   {r['start'].date()}..{r['end'].date()} ({int(r['len_bd'])}bd)  clean")
    print(f"   -> {bad} of {len(wg)} Warsh 'silence' gaps contain a set-piece\n")

# ------------------------------------------------------------------ D
line("D. T1 -- whose speeches is the arrival rate actually counting?")
for src, d in corp.items():
    sc = d["scores"].copy()
    sc["date"] = pd.to_datetime(sc["date"])
    spk = None
    for c in ("speaker", "Speaker", "name"):
        if c in sc.columns:
            spk = c; break
    if spk is None:
        print(f"[{src}] no speaker column: {list(sc.columns)[:12]}")
        continue
    win = sc[(sc["date"] >= "2026-06-18") & (sc["date"] <= "2026-08-25")]
    print(f"[{src}] {sc[spk].nunique()} distinct speakers in the whole book; "
          f"{win[spk].nunique()} in the Warsh window")
    print("   Warsh-window speakers: "
          + ", ".join(f"{k}({v})" for k, v in win[spk].value_counts().items()))
    # chair-only, same calendar window each year
    def chair_rows(name_frag, y):
        lo = pd.Timestamp(year=y, month=6, day=18); hi = pd.Timestamp(year=y, month=8, day=25)
        m = sc[(sc["date"] >= lo) & (sc["date"] <= hi)]
        return int(m[spk].astype(str).str.contains(name_frag, case=False, na=False).sum())
    print("   chair-only counts in the 18 Jun - 25 Aug window:")
    for y in range(2021, 2027):
        print(f"      {y}: Powell {chair_rows('powell', y):2d}   "
              f"Warsh {chair_rows('warsh', y):2d}")
    print(f"   last row in the score book: {sc['date'].max().date()}")
    print()

print("\nDONE", flush=True)
