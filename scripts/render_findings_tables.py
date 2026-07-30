"""Render every gate artifact as markdown, for paste-free inclusion in the findings doc.

Why this exists rather than typing the tables: a findings report whose numbers were
hand-copied from a notebook cannot be checked against the run that produced it, and a
transcription slip is indistinguishable from a result. Everything here is generated
from the CSVs `BT/dealer_ladder/gates.py` wrote, each table carries its source
filename, and an artifact that is MISSING says so loudly instead of being quietly
omitted -- a gate that did not run must never read as a gate that passed.

    conda run -n stir python scripts/render_findings_tables.py \
        --results BT/results/dealer_ladder --out docs/.../findings_tables.md
    conda run -n stir python scripts/render_findings_tables.py --check

``--check`` exits non-zero when an expected artifact is absent, which is the cheap way
to ask "was that gate run complete?" before writing any prose about it.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RESULTS = os.path.join(REPO, "BT", "results", "dealer_ladder")

# (artifact, heading, required, column subset or None, sort spec or None, max rows)
SECTIONS = [
    ("verdicts", "Every gate verdict", True,
     ["gate", "pass", "headline"], None, None),

    ("g0_universe_summary", "G0 — the signed universe", True, None, None, None),
    ("g0_exclusion_ladder", "G0 — exclusion ladder", True, None, None, None),
    ("g0_skew_by_stratum", "G0 — PAID share by stratum (our labels)", False,
     None, None, None),
    ("g0_mid_offset_bps", "G0 — our mid vs the independent mid (bp)", False,
     None, None, None),
    ("g0_flip_by_confidence", "G0 — flip rate by our confidence tier", False,
     None, None, None),
    ("g0_flip_by_curve_bucket", "G0 — flip rate by curve bucket", False,
     None, None, None),
    ("g0_flip_by_trade_type", "G0 — flip rate by trade type", False, None, None, None),
    ("g0_flip_by_hour", "G0 — flip rate by execution hour (ET)", False,
     None, None, None),
    ("g0_skew_vs_independent", "G0 — PAID/RECEIVED skew, ours vs independent", False,
     None, None, None),
    ("g0_skew_vs_independent_by_hour",
     "G0 — PAID/RECEIVED skew by execution hour", False, None, None, 30),
    ("g0_flip_mechanism",
     "G0 — is a flip explained by the curve gap alone?", False, None, None, None),
    ("g0_pflip_calibration",
     "G0 — is p_flip calibrated against an independent mid?", False, None, None, None),
    ("g0_implied_accuracy", "G0 — implied bounds on direction accuracy", False,
     None, None, None),

    ("g1_audits", "G1 — arrival integrity (differential poison audits)", True,
     None, None, None),

    ("g2_lead_lag_summary_FUTURES", "G2 — lead-lag summary, SR3", True,
     None, None, None),
    ("g2_flow_response_FUTURES", "G2 — flow response event study, SR3", False,
     None, None, None),
    ("g2_peak_rho_summary_FUTURES", "G2 — signed peak correlation, SR3", False,
     None, None, None),
    ("g2_lead_lag_FUTURES", "G2 — lead-lag by lag, SR3", False, None, None, 80),
    ("g2_flow_events_FUTURES", "G2 — flow-response events, SR3", False, None, None, 40),

    ("g2_lead_lag_summary_FED_FUNDS", "G2 — lead-lag summary, ZQ (cross-check)",
     False, None, None, None),
    ("g2_peak_rho_summary_FED_FUNDS", "G2 — signed peak correlation, ZQ", False,
     None, None, None),
    ("g2_lead_lag_FED_FUNDS", "G2 — lead-lag by lag, ZQ", False, None, None, 80),
    ("g2_flow_response_FED_FUNDS", "G2 — flow response event study, ZQ", False,
     None, None, None),
    ("g2_flow_events_FED_FUNDS", "G2 — flow-response events, ZQ", False,
     None, None, 40),

    ("g3_horse_race_FUTURES", "G3 — horse race against our own basis", True,
     None, None, None),
    ("g3_horse_race_independent_FUTURES",
     "G3b — horse race against the INDEPENDENT (Citi) basis", False,
     None, None, None),
    ("g3_point_in_time_FUTURES", "G3 — point-in-time verification of the controls",
     False, None, None, None),
    ("g3_leave_one_out_FUTURES", "G3 — leave-one-bucket-out", False,
     None, None, None),
    ("g3_residual_race_FUTURES", "G3 — residualised signal", False, None, None, None),

    ("g3_horse_race_FED_FUNDS", "G3 — horse race, ZQ (cross-check)", False,
     None, None, None),
    ("g3_horse_race_independent_FED_FUNDS",
     "G3b — horse race vs the independent basis, ZQ", False, None, None, None),
    ("g3_point_in_time_FED_FUNDS",
     "G3 — point-in-time verification of the controls, ZQ", False, None, None, None),
    ("g3_leave_one_out_FED_FUNDS", "G3 — leave-one-bucket-out, ZQ", False,
     None, None, None),
    ("g3_residual_race_FED_FUNDS", "G3 — residualised signal, ZQ", False,
     None, None, None),

    ("g4_staleness_sensitivity", "G4 — staleness sensitivity of the primary", False,
     None, None, None),
    ("g4_best_and_median", "G4 — best vs median configuration", False,
     None, None, None),
    ("g4_league", "G4 — the full secondary grid", False, None, ("t", False), 400),
    ("g4_romano_wolf", "G4 — Romano-Wolf family-wise adjusted p", False,
     None, ("t", False), 60),
    ("g4_skipped_variants", "G4 — declared variants that could NOT run", False,
     None, None, 40),
    ("g4_placebos", "G4 — placebos", True, None, None, None),
    ("g4_label_free", "G4 — the label-free cell (unsigned print intensity)", False,
     None, None, None),
    ("g4_conditioning", "G4 — conditioning splits", False, None, None, None),

    ("g5_net_table", "G5 — gross, cost, net and the attenuation grid", False,
     None, None, None),
    ("g5_capacity", "G5 — capacity (participation-based, NOT measured depth)", False,
     None, None, None),

    ("trial_ledger", "Trial ledger — every configuration evaluated, in order", True,
     None, None, 400),
]

FLOAT_COLS_4DP = {"mean", "mean_bp", "net_bp", "gross_bp", "t", "se", "lo", "hi",
                  "coef", "peak_rho", "lls"}


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    """Round floats to a readable width without hiding a number's magnitude."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            dp = 4 if c in FLOAT_COLS_4DP else 3
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else f"{v:,.{dp}f}")
    return out


def render(results_dir: str) -> tuple[str, list[str]]:
    lines, missing = [], []
    lines.append("<!-- GENERATED by scripts/render_findings_tables.py — do not edit "
                 "by hand. Re-run it instead, so every number here traces to the "
                 "artifact that produced it. -->")
    lines.append("")
    for name, heading, required, cols, sort, cap in SECTIONS:
        path = os.path.join(results_dir, f"{name}.csv")
        lines.append(f"### {heading}")
        lines.append("")
        if not os.path.exists(path):
            if required:
                lines.append(f"_**REQUIRED ARTIFACT MISSING** — `{name}.csv` was not "
                             f"written, so this stage did not run. Absence of a table "
                             f"is not a passing gate._")
                missing.append(name)
            else:
                lines.append(f"_Not produced in this run — `{name}.csv` is absent. "
                             f"Optional, so this may be a stage that legitimately had "
                             f"nothing to report (e.g. a cross-check space with no "
                             f"data); it is NOT a result._")
            lines.append("")
            continue
        df = pd.read_csv(path)
        if df.empty:
            lines.append(f"_`{name}.csv` is empty — the stage ran and produced no "
                         f"rows._")
            lines.append("")
            continue
        if cols:
            keep = [c for c in cols if c in df.columns]
            if keep:
                df = df[keep]
        df = df.loc[:, [c for c in df.columns if not c.startswith("Unnamed")]]
        if sort and sort[0] in df.columns:
            df = df.sort_values(sort[0], ascending=sort[1])
        truncated = 0
        if cap is not None and len(df) > cap:
            truncated = len(df) - cap
            df = df.head(cap)
        lines.append(_fmt(df).to_markdown(index=False))
        lines.append("")
        prov = f"_Source: `{name}.csv` ({len(df)} rows"
        if truncated:
            prov += f" shown, {truncated} more in the CSV — truncated for length only"
        prov += ")._"
        lines.append(prov)
        lines.append("")
    return "\n".join(lines), missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    ap.add_argument("--inject", default=None,
                    help="splice the output into this markdown file, between "
                         "<!-- BEGIN GENERATED TABLES --> and <!-- END GENERATED TABLES -->")
    ap.add_argument("--out", default=None,
                    help="write markdown here; default is stdout")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if a required artifact is missing")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.results):
        print(f"results dir does not exist: {args.results}", file=sys.stderr)
        return 2
    md, missing = render(args.results)
    if args.check:
        have = sorted(f[:-4] for f in os.listdir(args.results) if f.endswith(".csv"))
        print(f"{len(have)} artifacts in {args.results}")
        if missing:
            print("MISSING REQUIRED: " + ", ".join(missing), file=sys.stderr)
            return 1
        print("all required artifacts present")
        return 0
    if args.inject:
        from BT.dealer_ladder import report
        report.inject(args.inject, "GENERATED TABLES", md)
        print(f"spliced {len(md.splitlines())} lines into {args.inject}")
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md + "\n")
        print(f"wrote {args.out} ({len(md.splitlines())} lines)")
        if missing:
            print("MISSING REQUIRED: " + ", ".join(missing), file=sys.stderr)
    if not (args.inject or args.out):
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
