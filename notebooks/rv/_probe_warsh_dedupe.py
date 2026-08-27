"""Two checks the study's own gates did not cover.

D1 -- DUPLICATE SAME-DAY ROWS. Two scored communications on one day both inherit
that day's price window, so they carry an identical ``y``. The Warsh
discretionary cell is small enough for that to matter: FedLock's "n = 10" is
fewer distinct days than it looks, and a multi-speech day is double-weighted in
the mean. The T3a direction (Warsh discretionary BELOW guidance) has to survive
collapsing to one row per day, or it is a weighting artefact.

D2 -- WHAT IS IN THE NON-EVENT BUCKET. P1 found that inside the Warsh window
non-event days resolve uncertainty (-0.73) while event days do not (+0.09). The
non-event bucket contains the data releases. Splitting it says whether the
finding is really "the DATA resolves the path and the TALK does not", which is a
mechanism rather than a contrast.
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

import fed_event_conditioning as FEC  # noqa: E402
import warsh_guidance_information as W  # noqa: E402

pd.set_option("display.width", 220)
R = pickle.load(open(HERE / "warsh_guidance_results.pkl", "rb"))
START, END = "2021-01-27", "2026-08-25"


def line(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88, flush=True)


line("D1. DOES T3a SURVIVE ONE ROW PER DAY?")
print("A day with two scored speeches contributes the same |y| twice. Collapsing")
print("to one row per day removes that weighting entirely.\n")
for src in ("jpm", "fedlock"):
    P = R["T3"][src]["placement"]
    pan = None
    # rebuild the panel to get the full (guidance + warsh) frame
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    print(f"[{src}] placement rows {len(P)}, distinct dates {P['date'].nunique()}")
    dup = P[P.duplicated(subset=["date", "type"], keep=False)]
    if len(dup):
        print(f"   duplicated (date,type) rows: {len(dup)}")
        print("   " + dup[["date", "type", "abs_y_bp"]].to_string(index=False)
              .replace("\n", "\n   "))

print("\nrebuilding panels to collapse properly ...", flush=True)
hist = FEC.meeting_step_history(START, END)
cal = FEC.setpiece_calendar(START, END)
for src in ("jpm", "fedlock"):
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    sent, sc = FEC.load_daily_sentiment(cfg, START, END)
    ev = FEC.build_events(cfg, sc, START, END, calendar=cal)
    panel, _ = FEC.event_panel(ev, hist, sent, cfg)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["era"] = W.era_of(panel["date"])
    panel["klass"] = W.klass_of(panel["type"])
    panel["abs"] = panel["y"].abs()

    raw = (panel.groupby(["klass", "era"])["abs"]
                .agg(n="size", mean="mean", median="median").reset_index())
    ded = (panel.drop_duplicates(subset=["date", "klass"])
                .groupby(["klass", "era"])["abs"]
                .agg(n="size", mean="mean", median="median").reset_index())
    print(f"\n[{src}] RAW (one row per scored communication)")
    print("   " + raw.to_string(index=False).replace("\n", "\n   "))
    print(f"[{src}] DEDUPED (one row per day per class)")
    print("   " + ded.to_string(index=False).replace("\n", "\n   "))
    for k in ("discretionary", "scheduled"):
        s = ded[ded["klass"] == k]
        if set(s["era"]) >= {"guidance", "warsh"}:
            g = float(s.loc[s["era"] == "guidance", "mean"].iloc[0])
            w = float(s.loc[s["era"] == "warsh", "mean"].iloc[0])
            nw = int(s.loc[s["era"] == "warsh", "n"].iloc[0])
            print(f"   -> {k:14s} deduped: guidance {g:.3f}  warsh {w:.3f} "
                  f"(n {nw})  direction {'DOWN' if w < g else 'UP'}")

line("D2. INSIDE THE WARSH WINDOW: TALK vs DATA vs NOTHING")
print("Splitting P1's non-event column by whether a high-impact US release landed.")
print("If the data resolves and the talk does not, that is the mechanism.\n")
rel = set(W.release_days(START, END))
rows = []
sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
for d in sess:
    r = W.fixed_window_degeneracy(hist, d)
    if r is not None:
        rows.append(r)
ALL = pd.DataFrame(rows).set_index("date")
ALL["era"] = W.era_of(ALL.index)

for src in ("jpm", "fedlock"):
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    _s, sc = FEC.load_daily_sentiment(cfg, START, END)
    ev = FEC.build_events(cfg, sc, START, END, calendar=cal)
    evd = set(pd.DatetimeIndex(pd.to_datetime(ev["date"])).normalize())
    for era in ("warsh", "guidance"):
        A = ALL[ALL["era"] == era].copy()
        idx = pd.DatetimeIndex(A.index).normalize()
        A["bucket"] = np.where([x in evd for x in idx], "talk",
                               np.where([x in rel for x in idx], "data", "nothing"))
        g = (A.groupby("bucket")[["degen_pre", "d_degen_t0", "d_degen_t5"]]
               .agg(["size", "mean"]))
        print(f"[{src}] {era}")
        print("   " + g.to_string().replace("\n", "\n   "))
        print()

print("\nDONE", flush=True)
