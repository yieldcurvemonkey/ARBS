"""The Warsh dummy is a PERIOD dummy. Two tests that can tell them apart.

R3/R4 found the Warsh indicator survives a mean-reversion control at t > 5.4.
That number cannot be taken at face value, for a reason that has nothing to do
with the data quality: **every Warsh event sits inside one 2.3-month window**.
So the regression cannot distinguish

    (a) "Warsh events fail to resolve uncertainty"          -- an EVENT effect
    (b) "uncertainty rose over the summer of 2026"          -- a PERIOD effect

They are observationally equivalent with one period, and an HC3 standard error
that treats 23 overlapping five-day windows as 23 independent draws will report
a t of 5.5 for either.

**P1 -- within-window event vs non-event.** Inside the Warsh window only,
compare the five-day change in degeneracy distance following an event day
against the same quantity following a NON-event day. A period trend lifts both
equally; only an event effect separates them. This is the test that matters.

**P2 -- the period placebo.** Slide a 49-business-day window through the
guidance era, label its events "pseudo-Warsh", and refit. That yields the
distribution of the dummy coefficient for an arbitrary quiet period of the same
length -- the correct null for a one-period indicator. If +2.0bp with t 5.5 is
ordinary among those, the finding is a period, not a regime.
"""
from __future__ import annotations

import dataclasses
import io
import pathlib
import pickle
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
R = pickle.load(open(HERE / "warsh_guidance_results.pkl", "rb"))
START, END = "2021-01-27", "2026-08-25"


def line(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88, flush=True)


print("rebuilding the ladder ...", flush=True)
hist = FEC.meeting_step_history(START, END)
sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
cal = FEC.setpiece_calendar(START, END)

# every session gets the same fixed-window degeneracy measure the events got,
# so an event day and a non-event day are measured identically
print("measuring every session ...", flush=True)
rows = []
for d in sess:
    r = W.fixed_window_degeneracy(hist, d)
    if r is not None:
        rows.append(r)
ALL = pd.DataFrame(rows).set_index("date")
ALL["era"] = W.era_of(ALL.index)
print(f"  {len(ALL)} sessions measured  "
      f"{ALL.index.min().date()}..{ALL.index.max().date()}")

corpora = {}
for src in ("jpm", "fedlock"):
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    sent, sc = FEC.load_daily_sentiment(cfg, START, END)
    ev = FEC.build_events(cfg, sc, START, END, calendar=cal)
    corpora[src] = pd.DatetimeIndex(pd.to_datetime(ev["date"])).normalize()

line("P1. INSIDE THE WARSH WINDOW -- event days vs NON-event days")
print("If uncertainty simply rose all summer, both columns rise together and the")
print("difference is zero. Only an event effect separates them.\n")
for src, evd in corpora.items():
    A = ALL[ALL["era"] == "warsh"].copy()
    idx = pd.DatetimeIndex(A.index).normalize()
    A["is_event"] = [x in set(evd) for x in idx]
    g = A.groupby("is_event")[["degen_pre", "d_degen_t0", "d_degen_t1",
                               "d_degen_t5"]].agg(["size", "mean"])
    print(f"[{src}]")
    print("   " + g.to_string().replace("\n", "\n   "))
    e = A[A["is_event"]]
    n = A[~A["is_event"]]
    if len(e) > 2 and len(n) > 2:
        for h in ("d_degen_t0", "d_degen_t5"):
            diff = e[h].mean() - n[h].mean()
            from scipy import stats as st
            t = st.mannwhitneyu(e[h].dropna(), n[h].dropna(),
                                alternative="two-sided")
            print(f"   {h}: event {e[h].mean():+.4f} (n {len(e)})  "
                  f"non-event {n[h].mean():+.4f} (n {len(n)})  "
                  f"DIFF {diff:+.4f}   Mann-Whitney p {t.pvalue:.4f}")
    print()

line("P1b. THE SAME CONTRAST IN THE GUIDANCE ERA (the comparison it needs)")
print("Guidance-era events resolved uncertainty. Did guidance-era NON-event days")
print("do it too? If they did, T4 was never about events in either regime.\n")
for src, evd in corpora.items():
    A = ALL[ALL["era"] == "guidance"].copy()
    idx = pd.DatetimeIndex(A.index).normalize()
    A["is_event"] = [x in set(evd) for x in idx]
    e, n = A[A["is_event"]], A[~A["is_event"]]
    print(f"[{src}]")
    for h in ("d_degen_t0", "d_degen_t5"):
        print(f"   {h}: event {e[h].mean():+.4f} (n {len(e)})  "
              f"non-event {n[h].mean():+.4f} (n {len(n)})  "
              f"DIFF {e[h].mean() - n[h].mean():+.4f}")
    print()

line("P2. THE PERIOD PLACEBO -- is +2.0bp unusual for ANY 49-day window?")
print("Slide a 49-business-day window through the guidance era; label its events")
print("pseudo-Warsh; refit d_degen_t5 ~ degen_pre + pseudo. This is the null for")
print("a one-period indicator.\n")
WIN = 49
for src in ("jpm", "fedlock"):
    U = R["T4"][src]["rows"].copy()
    U["date"] = pd.to_datetime(U["date"])
    U["era"] = W.era_of(U["date"])
    G = U[U["era"] == "guidance"].sort_values("date").reset_index(drop=True)
    gsess = sess[sess < W.WARSH_BOUNDARY]
    coefs, ts = [], []
    for k in range(0, len(gsess) - WIN, 5):          # step 5bd
        lo, hi = gsess[k], gsess[k + WIN]
        d = G[["d_degen_t5", "degen_pre"]].copy()
        d["pseudo"] = ((G["date"] >= lo) & (G["date"] <= hi)).astype(float)
        d = d.dropna()
        if d["pseudo"].sum() < 5:
            continue
        try:
            m = sm.OLS(d["d_degen_t5"],
                       sm.add_constant(d[["degen_pre", "pseudo"]])).fit(
                cov_type="HC3")
            coefs.append(float(m.params["pseudo"]))
            ts.append(float(m.tvalues["pseudo"]))
        except Exception:  # noqa: BLE001
            continue
    coefs = np.asarray(coefs); ts = np.asarray(ts)
    # the real thing, same specification
    d = U[["d_degen_t5", "degen_pre"]].copy()
    d["pseudo"] = (U["era"] == "warsh").astype(float)
    d = d.dropna()
    m = sm.OLS(d["d_degen_t5"],
               sm.add_constant(d[["degen_pre", "pseudo"]])).fit(cov_type="HC3")
    b_real, t_real = float(m.params["pseudo"]), float(m.tvalues["pseudo"])
    print(f"[{src}] {len(coefs)} placebo windows of {WIN} business days")
    print(f"   placebo coefficient: mean {coefs.mean():+.3f}  sd {coefs.std():.3f}  "
          f"min {coefs.min():+.3f}  max {coefs.max():+.3f}")
    print(f"   placebo |t|        : median {np.median(np.abs(ts)):.2f}  "
          f"q95 {np.quantile(np.abs(ts), 0.95):.2f}  max {np.abs(ts).max():.2f}")
    print(f"   REAL warsh         : coef {b_real:+.3f}   t {t_real:+.2f}")
    print(f"   p(placebo coef >= real)  = {float((coefs >= b_real).mean()):.4f}")
    print(f"   p(placebo |t| >= real|t|) = {float((np.abs(ts) >= abs(t_real)).mean()):.4f}")
    print()

print("\nDONE", flush=True)
