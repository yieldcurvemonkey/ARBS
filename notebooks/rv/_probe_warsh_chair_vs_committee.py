"""Bianco's "BoE-fication": does the CHAIR carry less and the COMMITTEE more?

    "Fed watching is not a game of parsing the chairman's words... It's a vote
    tallying exercise."  -- Jim Bianco, MacroVoices 543, 30 Jul 2026

The study's headline pooled every Fed communication into one "talk" bucket and
found it resolves nothing under Warsh. Bianco's mechanism predicts that pooling
is exactly what would hide the effect: under Powell the chair whipped the votes,
so the chair's words were the information and a regional president's were noise;
under Warsh the votes are genuinely live -- three dissents at the July meeting --
so the chair non-answers while every other voter's reaction function becomes
worth knowing.

If both halves moved and they moved in OPPOSITE directions, the pooled bucket
washes to zero. Which is what it did.

    predicted, guidance era :  chair resolves a lot,  committee resolves little
    predicted, Warsh era    :  chair resolves little, committee resolves more

**EXPLORATORY.** This hypothesis arrived after the outcomes were seen. It is not
in the pre-registration and is not scored against it. Reported as a lead, with
its own n stated everywhere, and the chair leg is n=2 in the Warsh window before
anyone starts reading it.

Both measures are reported, because "carries information" is two questions:
how much the strip MOVES, and whether it ends up more DECIDED.
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

#: The sitting chair, by era. The only hand input here, and it is checkable.
CHAIRS = ("powell", "warsh")

#: Named by Bianco as the July-2026 dissenters plus the governor he expected to
#: be a fourth. Hand-entered FROM THE TRANSCRIPT, not verified against a vote
#: record in this repo -- so the split below is reported separately and is the
#: weaker of the two.
BIANCO_HAWKS = ("hammack", "logan", "kashkari", "waller")


def line(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88, flush=True)


print("building ...", flush=True)
hist = FEC.meeting_step_history(START, END)
cal = FEC.setpiece_calendar(START, END)
setp = set(pd.DatetimeIndex(cal["date"]).normalize())

sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
rows = []
for d in sess:
    r = W.fixed_window_degeneracy(hist, d)
    if r is not None:
        rows.append(r)
ALL = pd.DataFrame(rows).set_index("date")
ALL["era"] = W.era_of(ALL.index)
dpath = W.daily_path_change(hist, n_meetings=2)


def classify(sc: pd.DataFrame):
    """date -> set of speaker classes that spoke that day."""
    sc = sc.copy()
    sc["date"] = pd.to_datetime(sc["date"]).dt.normalize()
    spk = sc["speaker"].astype(str).str.lower()
    sc["is_chair"] = spk.str.contains("|".join(CHAIRS), na=False)
    sc["is_hawk"] = spk.str.contains("|".join(BIANCO_HAWKS), na=False)
    g = sc.groupby("date").agg(chair=("is_chair", "any"),
                               hawk=("is_hawk", "any"),
                               n=("is_chair", "size"))
    return g


for src in ("jpm", "fedlock"):
    cfg = dataclasses.replace(FEC.PRIMARY, source=src)
    _s, sc = FEC.load_daily_sentiment(cfg, START, END)
    g = classify(sc)

    line(f"[{src}] CHAIR vs COMMITTEE -- who was speaking, and what followed")
    A = ALL.copy()
    idx = pd.DatetimeIndex(A.index).normalize()
    A["spoke"] = [d in g.index for d in idx]
    A["chair"] = [bool(g["chair"].get(d, False)) for d in idx]
    A["hawk"] = [bool(g["hawk"].get(d, False)) for d in idx]
    A["setpiece"] = [d in setp for d in idx]
    A["dp"] = [abs(float(dpath["dpath_bp"].get(d, np.nan))) if d in dpath.index
               else np.nan for d in idx]

    def bucket(r):
        if not r["spoke"]:
            return "no talk"
        return "chair" if r["chair"] else "committee only"
    A["bucket"] = A.apply(bucket, axis=1)

    for era in ("guidance", "warsh"):
        sub = A[A["era"] == era]
        t = (sub.groupby("bucket")
                .agg(n=("d_degen_t5", "size"),
                     degen_pre=("degen_pre", "mean"),
                     resolve_t5=("d_degen_t5", "mean"),
                     move_bp=("dp", "mean"))
                .reindex(["chair", "committee only", "no talk"]))
        print(f"\n  --- {era} ---")
        print("  " + t.to_string().replace("\n", "\n  "))

    # level-controlled, because the audit showed the raw 5-day change is ~53%
    # just minus its own starting level inside the Warsh window
    print("\n  level-controlled (d_degen_t5 ~ degen_pre + chair + committee,"
          " baseline = no talk):")
    for era in ("guidance", "warsh"):
        sub = A[A["era"] == era].dropna(subset=["d_degen_t5", "degen_pre"]).copy()
        sub["c_chair"] = (sub["bucket"] == "chair").astype(float)
        sub["c_comm"] = (sub["bucket"] == "committee only").astype(float)
        if sub["c_chair"].sum() < 2:
            print(f"    {era:9s}: only {int(sub['c_chair'].sum())} chair days "
                  f"-- not estimable")
            continue
        m = sm.OLS(sub["d_degen_t5"],
                   sm.add_constant(sub[["degen_pre", "c_chair", "c_comm"]])
                   ).fit(cov_type="HC3")
        print(f"    {era:9s}  chair {m.params['c_chair']:+.3f} "
              f"(t {m.tvalues['c_chair']:+.2f}, p {m.pvalues['c_chair']:.3f}, "
              f"n {int(sub['c_chair'].sum())})"
              f"   committee {m.params['c_comm']:+.3f} "
              f"(t {m.tvalues['c_comm']:+.2f}, p {m.pvalues['c_comm']:.3f}, "
              f"n {int(sub['c_comm'].sum())})")

    # the same, excluding set-piece days so a presser is not doing the work
    print("\n  excluding set-piece days (no presser / decision / minutes):")
    for era in ("guidance", "warsh"):
        sub = A[(A["era"] == era) & (~A["setpiece"])]
        t = (sub.groupby("bucket")
                .agg(n=("d_degen_t5", "size"), resolve_t5=("d_degen_t5", "mean"),
                     move_bp=("dp", "mean"))
                .reindex(["chair", "committee only", "no talk"]))
        print(f"    {era}:")
        print("      " + t.to_string().replace("\n", "\n      "))

    line(f"[{src}] BIANCO'S NAMED HAWKS (hand-entered from the transcript)")
    for era in ("guidance", "warsh"):
        sub = A[(A["era"] == era) & A["spoke"] & (~A["chair"])]
        t = (sub.groupby("hawk")
                .agg(n=("d_degen_t5", "size"), resolve_t5=("d_degen_t5", "mean"),
                     move_bp=("dp", "mean")))
        t.index = ["other members" if not i else "Hammack/Logan/Kashkari/Waller"
                   for i in t.index]
        print(f"  {era}:")
        print("    " + t.to_string().replace("\n", "\n    "))

print("\nDONE", flush=True)
