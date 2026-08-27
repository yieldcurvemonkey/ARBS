"""Robustness: does the guidance-era comparison rest on 2022?

The guidance era here runs 2021-01 to 2026-06 and contains the 2022 hiking
shock, when every meeting was a live 50/75 debate. A 2.3-month calm window
compared against that is not like-for-like, and three of the six results could
be manufactured by it:

  T3  the Warsh DISCRETIONARY response came out LOWER than guidance. If the
      guidance mean is a 2022 artefact, that is not a Warsh fact.
  T4  guidance-era events RESOLVE uncertainty. If that is 2022 -- when a
      meeting genuinely got decided at each event -- the DiD is a regime
      comparison, not an event comparison.
  T5  the absolute level of variance fell under Warsh. Same exposure.

Also tests the one mechanical alternative to T4: the Warsh window starts at a
high degeneracy distance (8.5 of a possible 12.5), so mean reversion alone would
push it DOWN, not up. Controlling for the pre level says whether the rise
survives.
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


def line(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88, flush=True)


line("R1. IS THE GUIDANCE-ERA BASELINE JUST 2022?")
for src in ("jpm", "fedlock"):
    U = R["T4"][src]["rows"].copy()
    U["year"] = pd.DatetimeIndex(U["date"]).year
    g = (U.groupby(["year", "klass"])
           .agg(n=("d_degen_t5", "size"), degen_pre=("degen_pre", "mean"),
                d_t5=("d_degen_t5", "mean"), abs_y=("abs_y", "mean"))
           .reset_index())
    print(f"\n[{src}] by year -- degen_pre, the t+5 change, and |y|")
    print("   " + g.to_string(index=False).replace("\n", "\n   "))

line("R2. T4 AGAINST A RECENCY-MATCHED GUIDANCE WINDOW")
print("Guidance events restricted to the 24 months before the boundary, so the")
print("comparison is calm-vs-calm rather than calm-vs-2022.\n")
CUT = W.WARSH_BOUNDARY - pd.DateOffset(months=24)
for src in ("jpm", "fedlock"):
    U = R["T4"][src]["rows"].copy()
    U["era"] = W.era_of(U["date"])
    U["klass"] = W.klass_of(U["type"])
    recent = U[(U["era"] == "guidance") & (pd.DatetimeIndex(U["date"]) >= CUT)]
    warsh = U[U["era"] == "warsh"]
    print(f"[{src}]  recency-matched guidance from {CUT.date()}  "
          f"(n {len(recent)}) vs warsh (n {len(warsh)})")
    for k in ("scheduled", "discretionary"):
        a = recent[recent["klass"] == k]
        b = warsh[warsh["klass"] == k]
        if a.empty or b.empty:
            continue
        for h in ("d_degen_t0", "d_degen_t1", "d_degen_t5"):
            print(f"   {k:14s} {h}: guidance24m {a[h].mean():+.4f} (n {len(a)})"
                  f"   warsh {b[h].mean():+.4f} (n {len(b)})"
                  f"   DiD {b[h].mean() - a[h].mean():+.4f}")
        print(f"   {k:14s} degen_pre : guidance24m {a['degen_pre'].mean():.3f}"
              f"   warsh {b['degen_pre'].mean():.3f}")
        print(f"   {k:14s} abs_y     : guidance24m {a['abs_y'].mean():.3f}"
              f"   warsh {b['abs_y'].mean():.3f}")
        print()

line("R3. MEAN REVERSION -- does the T4 rise survive controlling for the start?")
print("The Warsh window starts high (8.5 of a possible 12.5). Mean reversion")
print("alone predicts a FALL, so the observed RISE is already against that bias.")
print("This puts it in a regression: d_degen ~ degen_pre + warsh.\n")
for src in ("jpm", "fedlock"):
    U = R["T4"][src]["rows"].copy()
    U["warsh"] = (W.era_of(U["date"]) == "warsh").astype(float)
    U["klass"] = W.klass_of(U["type"])
    for h in ("d_degen_t0", "d_degen_t5"):
        d = U[[h, "degen_pre", "warsh"]].dropna()
        if d["warsh"].sum() < 3:
            continue
        m = sm.OLS(d[h], sm.add_constant(d[["degen_pre", "warsh"]])).fit(
            cov_type="HC3")
        print(f"[{src}] {h} ~ degen_pre + warsh    n {int(m.nobs)}")
        print(f"   degen_pre {m.params['degen_pre']:+.4f} (t {m.tvalues['degen_pre']:+.2f})"
              f"   warsh {m.params['warsh']:+.4f} (t {m.tvalues['warsh']:+.2f},"
              f" p {m.pvalues['warsh']:.4f})   R2 {m.rsquared:.3f}")
    print()

line("R4. THE SAME, WITH THE GUIDANCE SIDE RESTRICTED TO 24 MONTHS")
for src in ("jpm", "fedlock"):
    U = R["T4"][src]["rows"].copy()
    U["era"] = W.era_of(U["date"])
    U["warsh"] = (U["era"] == "warsh").astype(float)
    U = U[(U["era"] == "warsh") | (pd.DatetimeIndex(U["date"]) >= CUT)]
    for h in ("d_degen_t0", "d_degen_t5"):
        d = U[[h, "degen_pre", "warsh"]].dropna()
        if d["warsh"].sum() < 3:
            continue
        m = sm.OLS(d[h], sm.add_constant(d[["degen_pre", "warsh"]])).fit(
            cov_type="HC3")
        print(f"[{src}] {h} ~ degen_pre + warsh   (guidance >= {CUT.date()})  "
              f"n {int(m.nobs)}")
        print(f"   degen_pre {m.params['degen_pre']:+.4f} (t {m.tvalues['degen_pre']:+.2f})"
              f"   warsh {m.params['warsh']:+.4f} (t {m.tvalues['warsh']:+.2f},"
              f" p {m.pvalues['warsh']:.4f})   R2 {m.rsquared:.3f}")
    print()

line("R5. T5 VARIANCE LEVELS BY YEAR -- is the 'pie shrank' claim a 2022 story?")
print("Reported because T5's shares rose while every absolute RMS fell. If the")
print("guidance RMS is carried by 2022, the level comparison says nothing.\n")
try:
    hist = FEC.meeting_step_history("2021-01-27", "2026-08-25")
    dp = W.daily_path_change(hist, n_meetings=2)
    dp["year"] = pd.DatetimeIndex(dp.index).year
    dp["era"] = W.era_of(dp.index)
    by = dp.groupby("year")["dpath_bp"].agg(
        n="size", rms=lambda s: float(np.sqrt((s ** 2).mean())),
        mean_abs=lambda s: float(s.abs().mean()))
    print(by.to_string())
    g24 = dp[(dp["era"] == "guidance") & (dp.index >= CUT)]["dpath_bp"]
    wz = dp[dp["era"] == "warsh"]["dpath_bp"]
    print(f"\n   guidance last 24m: n {len(g24)}  rms {np.sqrt((g24**2).mean()):.3f}bp")
    print(f"   warsh            : n {len(wz)}  rms {np.sqrt((wz**2).mean()):.3f}bp")
    print(f"   ratio warsh/guidance24m = "
          f"{np.sqrt((wz**2).mean())/np.sqrt((g24**2).mean()):.3f}")
except Exception as exc:  # noqa: BLE001
    print(f"   FAILED {type(exc).__name__}: {exc}")

print("\nDONE", flush=True)
