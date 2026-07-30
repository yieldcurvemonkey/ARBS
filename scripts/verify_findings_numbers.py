#!/usr/bin/env python
"""Check every headline number quoted in the findings doc against the artifact that produced it.

The generated tables in §10 are rendered from the CSVs and cannot drift. The PROSE is written by
hand, and prose is where transcription errors live. This caught one: the Romano-Wolf |t| range
was written as "79 to 311", read off the head of a table sorted descending, when the true minimum
is 0.89 and the median is 18.

Run it after editing the findings doc, and after any re-run that changes the artifacts.

    python scripts/verify_findings_numbers.py [--results DIR] [--doc PATH]

Exit code 1 if any quoted number does not match its source, so it can gate a commit.

Deliberately checks the direction of each claim, not only the digits: that the gross row carries
no significance stars, that no secondary variant is profitable, that the placebo arms straddle
zero on gross. A digit can match while the sentence around it says the opposite.
"""
from __future__ import annotations

import argparse
import io
import os
import sys

import pandas as pd

DEFAULT_DOC = "docs/superpowers/plans/2026-07-30-dealer-ladder-signal-findings.md"
DEFAULT_RESULTS = "BT/results/dealer_ladder"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    ap.add_argument("--doc", default=DEFAULT_DOC)
    args = ap.parse_args()

    doc = io.open(args.doc, encoding="utf-8").read()

    def load(name):
        p = os.path.join(args.results, f"{name}.csv")
        return pd.read_csv(p) if os.path.exists(p) else None

    v, g5 = load("verdicts"), load("g5_net_table")
    rw, pl = load("g4_romano_wolf"), load("g4_placebos")
    if v is None or g5 is None:
        print(f"missing artifacts under {args.results}")
        return 1

    checks: list[tuple[str, bool, str]] = []

    def chk(label, ok, detail=""):
        checks.append((label, bool(ok), detail))

    def in_doc(s):
        return s in doc

    heads = " ".join(str(x) for x in v["headline"])

    # --- G5: the number the whole verdict rests on
    gross = g5[g5["measure"] == "gross"].iloc[0]
    chk("G5 gross mean quoted", in_doc(f"{gross['mean_bp']:.4f}"),
        f"{gross['mean_bp']:.4f}")
    chk("G5 gross t quoted", in_doc(f"{gross['t']:.2f}"), f"{gross['t']:.2f}")
    chk("gross is NOT significant", str(gross.get("stars", "")) in ("nan", "", "None"),
        "a starred gross would invert the verdict")

    # --- the primary, whose t is the one most likely to be misquoted as a result
    prim = v[v["gate"].astype(str).str.startswith("G4-primary")]
    if len(prim):
        h = str(prim["headline"].iloc[0])
        for tok in ("-0.5458", "-9.44", "1639"):
            chk(f"primary {tok} traced to verdicts.csv", tok in h and in_doc(tok), tok)
        chk("primary t is labelled as the COST, not a result",
            "cost constant" in doc.lower(),
            "the -9.44 must never appear without that qualification")

    # --- Romano-Wolf: the range that was wrong
    if rw is not None:
        a = rw["t"].abs()
        chk("RW variant count", in_doc(f"{len(rw)} variants") or in_doc(f"{len(rw)} of"),
            str(len(rw)))
        chk("RW median mean quoted", in_doc(f"{rw['mean'].median():.4f}"),
            f"{rw['mean'].median():.4f}")
        chk("RW max |t| quoted", in_doc(f"{a.max():.0f}"), f"{a.max():.0f}")
        chk("RW median |t| quoted", in_doc(f"median {a.median():.0f}"),
            f"median {a.median():.0f}")
        chk("RW min se quoted", in_doc(f"{rw['se'].min():.4f}"), f"{rw['se'].min():.4f}")
        chk("no RW variant is profitable", int((rw["mean"] > 0).sum()) == 0,
            f"{int((rw['mean'] > 0).sum())} positive")
        chk("'not one ... positive' claim present",
            "not one" in doc.lower() and "positive" in doc.lower(), "")
        # the specific error this script exists to prevent
        chk("stale '79 to 311' range is gone", "79 and 311" not in doc
            and "79 to 311" not in doc, "corrected 2026-07-30")

    # --- placebos: the gross figures are the ones that carry the reading
    if pl is not None and "mean" in pl.columns:
        chk("placebo net min quoted", in_doc(f"{pl['mean'].min():.3f}"),
            f"{pl['mean'].min():.3f}")
        if "gross_mean" in pl.columns:
            g = pl["gross_mean"]
            chk("placebo gross straddles zero (measured)",
                bool((g > 0).any() and (g < 0).any()),
                "gross arms on both sides of zero is the discriminating result")
        else:
            chk("gross placebos flagged as DERIVED when not measured",
                "derived" in doc.lower(),
                "g4_placebos.csv has no gross_mean; the doc must say so")

    # --- mechanism figures
    for tok in ("-4.769", "-19.88", "0.14", "-0.01176", "0.398", "-0.6402"):
        chk(f"{tok} traced to a verdict", tok in heads and in_doc(tok), tok)

    # --- the lockout must be unburned AND said to be.
    #
    # Substring-matching "lockout was opened" does not work: that phrase occurs inside
    # "written down before the lockout was opened", which is a statement about the ORDER in
    # which the limitation was recorded, not a claim that the holdout was spent. Test the
    # assertion the doc actually makes, and require a lockout verdict row when it was spent.
    burned = os.path.exists(os.path.join(args.results, "LOCKOUT_USED.json"))
    says_unopened = ("NOT opened" in doc) or ("unburned" in doc.lower())
    has_lockout_row = bool(
        v["gate"].astype(str).str.contains("lockout", case=False).any())
    chk("lockout ledger state matches the doc",
        (burned and has_lockout_row and not says_unopened)
        or (not burned and says_unopened and not has_lockout_row),
        f"ledger={'BURNED' if burned else 'absent'}, "
        f"doc says unopened={says_unopened}, lockout verdict row={has_lockout_row}")

    bad = [c for c in checks if not c[1]]
    for label, ok, detail in checks:
        print(("  OK   " if ok else "  FAIL ") + f"{label:46s} {detail}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} verified")
    if bad:
        print("\nA quoted number does not match its artifact. Fix the PROSE, not the artifact.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
