"""The completeness pass, computed rather than remembered.

The protocol asks, at the end: *which modality, stratum or diagnostic did we not run,
and why?* Answered from memory that becomes a list of comfortable omissions — the ones
easy to justify — while the awkward gaps go unmentioned because nobody thought of them.

So the inventory is derived from the DECLARATIONS in code (the grid cross-product,
the control lists, the conditioning splits, the placebo set, the audit battery, the
gate stages) and diffed against what the results directory actually contains. Anything
declared but absent is reported, and anything absent WITHOUT a recorded reason is
flagged **UNEXPLAINED** — which is the whole point. A reason is only accepted from
``g4_skipped_variants.csv``, written by the runner at the moment it skipped something,
not supplied afterwards.

    conda run -n stir python scripts/dealer_ladder_completeness.py \
        --results BT/results/dealer_ladder --out completeness.md
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from BT.dealer_ladder import config as cfg, controls  # noqa: E402

# Stages the protocol declares, and the artifact that proves each one ran.
STAGES = {
    "G0 labels and provenance": ["g0_universe_summary", "g0_exclusion_ladder"],
    "G0 independent-mid flip study": ["g0_label_recon", "g0_mid_offset_bps"],
    "G0 flip by confidence tier": ["g0_flip_by_confidence"],
    "G0 flip by curve bucket": ["g0_flip_by_curve_bucket"],
    "G0 flip by trade type": ["g0_flip_by_trade_type"],
    "G0 flip by execution hour": ["g0_flip_by_hour"],
    "G0 PAID share by stratum": ["g0_skew_by_stratum"],
    "G0 direction-skew adjudication": ["g0_skew_vs_independent"],
    "G0 direction skew by hour": ["g0_skew_vs_independent_by_hour"],
    "G0 flip mechanism (curve gap vs distance to mid)": ["g0_flip_mechanism"],
    "G0 p_flip calibration": ["g0_pflip_calibration"],
    "G0 implied accuracy bounds": ["g0_implied_accuracy"],
    "G1 arrival integrity": ["g1_audits"],
    "G2 lead-lag, SR3": ["g2_lead_lag_summary_FUTURES"],
    "G2 lead-lag, ZQ cross-check": ["g2_lead_lag_summary_FED_FUNDS"],
    "G2 signed peak correlation, SR3": ["g2_peak_rho_summary_FUTURES"],
    "G2 signed peak correlation, ZQ": ["g2_peak_rho_summary_FED_FUNDS"],
    "G3 horse race, ZQ cross-check": ["g3_horse_race_FED_FUNDS"],
    "G2 flow-response event study, SR3": ["g2_flow_response_FUTURES"],
    "G2 flow-response event study, ZQ": ["g2_flow_response_FED_FUNDS"],
    "G2 lead-lag by lag, SR3": ["g2_lead_lag_FUTURES"],
    "G2 lead-lag by lag, ZQ": ["g2_lead_lag_FED_FUNDS"],
    "G2 flow-response events, SR3": ["g2_flow_events_FUTURES"],
    "G2 flow-response events, ZQ": ["g2_flow_events_FED_FUNDS"],
    "G3 horse race vs our basis": ["g3_horse_race_FUTURES"],
    "G3b horse race vs independent basis": ["g3_horse_race_independent_FUTURES"],
    "G3 point-in-time verification": ["g3_point_in_time_FUTURES"],
    "G3 leave-one-bucket-out": ["g3_leave_one_out_FUTURES"],
    "G3 residualised signal": ["g3_residual_race_FUTURES"],
    "G3b horse race vs independent basis, ZQ": ["g3_horse_race_independent_FED_FUNDS"],
    "G3 point-in-time verification, ZQ": ["g3_point_in_time_FED_FUNDS"],
    "G3 leave-one-bucket-out, ZQ": ["g3_leave_one_out_FED_FUNDS"],
    "G3 residualised signal, ZQ": ["g3_residual_race_FED_FUNDS"],
    "G4 primary (in-sample)": ["verdicts"],
    "G4 staleness sensitivity": ["g4_staleness_sensitivity"],
    "G4 secondary grid": ["g4_league"],
    "G4 variants that could not run": ["g4_skipped_variants"],
    "G4 Romano-Wolf family-wise": ["g4_romano_wolf"],
    "G4 best-vs-median anti-selection": ["g4_best_and_median"],
    "G4 placebos": ["g4_placebos"],
    "G4 label-free cell": ["g4_label_free"],
    "G4 conditioning splits": ["g4_conditioning"],
    "G4 conditioners that could not be split": ["g4_conditioning_skipped"],
    "G5 economics": ["g5_net_table"],
    "G5 capacity": ["g5_capacity"],
    "Trial ledger": ["trial_ledger"],
    "One-shot lockout": ["LOCKOUT_USED.json"],
}

DECLARED_PLACEBOS = (
    "none (reference)", "sign shuffle within session", "arrival +1 grid step later",
    "live parity (visibility floored at exec+15m)", "rotated buckets",
    "pre-arrival window",
)

DECLARED_AUDITS = (
    "visibility_delays", "not_yet_visible_poison", "future_poison",
    "trailing_moments",
)


def _load(results_dir, name):
    path = os.path.join(results_dir, f"{name}.csv")
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _exists(results_dir, name):
    for candidate in (f"{name}.csv", name):
        if os.path.exists(os.path.join(results_dir, candidate)):
            return True
    return False


def declared_grid(config) -> list[str]:
    g = config.grid
    return [f"{s}->{t}|hl{int(hl)}|{w}|h{h}"
            for t, s, hl, w, h in itertools.product(
                g.target_spaces, g.spaces, g.half_lives_min, g.weightings,
                g.horizons_min)]


def audit(results_dir, config) -> dict:
    rows = []

    # ---- stages
    for stage, artifacts in STAGES.items():
        present = [a for a in artifacts if _exists(results_dir, a)]
        rows.append({"kind": "stage", "item": stage,
                     "ran": len(present) == len(artifacts),
                     "detail": (f"{len(present)}/{len(artifacts)} artifacts"
                                if present else "no artifact"),
                     "reason": ""})

    # ---- grid variants: declared cross-product vs league rows vs recorded skips
    league = _load(results_dir, "g4_league")
    skipped = _load(results_dir, "g4_skipped_variants")
    ran = set(league["variant"]) if league is not None and "variant" in league else set()
    reasons = (dict(zip(skipped["variant"], skipped["reason"]))
               if skipped is not None and "variant" in skipped else {})
    for v in declared_grid(config):
        if v in ran:
            continue
        rows.append({"kind": "grid variant", "item": v, "ran": False,
                     "detail": "declared but no league row",
                     "reason": reasons.get(v, "")})

    # ---- controls actually used by the horse race
    race = _load(results_dir, "g3_horse_race_FUTURES")
    used = set(race["term"]) if race is not None and "term" in race else set()
    for c in controls.DEFAULT_CONTROLS:
        if c not in used:
            rows.append({"kind": "control", "item": c, "ran": False,
                         "detail": "declared in DEFAULT_CONTROLS, absent from the "
                                   "fitted horse race",
                         "reason": ""})
    indep = _load(results_dir, "g3_horse_race_independent_FUTURES")
    iused = set(indep["term"]) if indep is not None and "term" in indep else set()
    for c in controls.INDEPENDENT_CONTROLS:
        if c not in iused:
            rows.append({"kind": "independent control", "item": c, "ran": False,
                         "detail": "declared, absent from the independent race",
                         "reason": ""})

    # ---- conditioning splits
    cond = _load(results_dir, "g4_conditioning")
    cused = set()
    if cond is not None:
        for col in ("split", "conditioner", "panel"):
            if col in cond.columns:
                cused |= set(cond[col].astype(str))
    for c in controls.CONDITIONING_PANELS + controls.CONDITIONING_SERIES:
        if not any(c in s for s in cused):
            rows.append({"kind": "conditioning split", "item": c, "ran": False,
                         "detail": "declared, no stratum reported", "reason": ""})

    # ---- placebos
    plac = _load(results_dir, "g4_placebos")
    pused = set(plac["placebo"].astype(str)) if plac is not None \
        and "placebo" in plac else set()
    for p in DECLARED_PLACEBOS:
        if p not in pused:
            rows.append({"kind": "placebo", "item": p, "ran": False,
                         "detail": "pre-specified, not reported", "reason": ""})

    # ---- audits
    aud = _load(results_dir, "g1_audits")
    aused = set(aud["audit"].astype(str)) if aud is not None \
        and "audit" in aud else set()
    for a in DECLARED_AUDITS:
        if a not in aused:
            rows.append({"kind": "audit", "item": a, "ran": False,
                         "detail": "declared in the battery, not reported",
                         "reason": ""})

    out = pd.DataFrame(rows)
    if not out.empty:
        out["unexplained"] = (~out["ran"]) & (out["reason"].fillna("") == "")
    return {"inventory": out}


def render(res, results_dir, title=True) -> str:
    inv = res["inventory"]
    lines = (["## Completeness pass", ""] if title else []) + [
             "<!-- GENERATED by scripts/dealer_ladder_completeness.py. The inventory "
             "is derived from the DECLARATIONS in code, not from recollection, so a "
             "gap nobody thought of still appears. -->", ""]
    if inv.empty:
        lines.append("_No declarations found to audit._")
        return "\n".join(lines)

    stages = inv[inv["kind"] == "stage"]
    ran, total = int(stages["ran"].sum()), len(stages)
    missing = inv[~inv["ran"]]
    unexplained = missing[missing["unexplained"]]
    lines += [f"- **{ran}/{total} protocol stages produced their artifacts.**",
              f"- **{len(missing)} declared items did not run**, of which "
              f"**{len(unexplained)} have no recorded reason**.", ""]

    if len(unexplained):
        lines += ["### Not run, and NOT explained", "",
                  "A reason is only accepted from `g4_skipped_variants.csv`, written by "
                  "the runner at the moment it skipped something. Everything here needs "
                  "a reason written into the findings doc by hand, or the omission is "
                  "not accounted for.", "",
                  unexplained[["kind", "item", "detail"]].to_markdown(index=False), ""]
    else:
        lines += ["### Not run, and NOT explained", "",
                  "_None — every gap carries a machine-recorded reason._", ""]

    explained = missing[~missing["unexplained"]]
    if len(explained):
        by_reason = (explained.groupby("reason").size()
                     .rename("items").to_frame().reset_index())
        lines += ["### Not run, with a recorded reason", "",
                  by_reason.to_markdown(index=False), "",
                  "<details><summary>every item</summary>", "",
                  explained[["kind", "item", "reason"]].to_markdown(index=False),
                  "", "</details>", ""]

    lines += ["### Ran", "",
              inv[inv["ran"]][["kind", "item", "detail"]].to_markdown(index=False), ""]
    lines.append(f"_Audited against `{results_dir}`._")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=os.path.join(REPO, "BT", "results",
                                                      "dealer_ladder"))
    ap.add_argument("--inject", default=None,
                    help="splice the output into this markdown file, between "
                         "<!-- BEGIN GENERATED COMPLETENESS --> and <!-- END GENERATED COMPLETENESS -->")
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero while any gap is UNEXPLAINED")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not os.path.isdir(args.results):
        print(f"results dir does not exist: {args.results}", file=sys.stderr)
        return 2
    res = audit(args.results, cfg.LadderStudyConfig())
    # no duplicate heading when the target document supplies its own
    md = render(res, args.results, title=not args.inject)
    if args.inject:
        from BT.dealer_ladder import report
        report.inject(args.inject, "GENERATED COMPLETENESS", md)
        print(f"spliced into {args.inject}")
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md + "\n")
        print(f"wrote {args.out}")
    if not (args.inject or args.out):
        print(md)

    inv = res["inventory"]
    n_unexplained = 0 if inv.empty else int(inv["unexplained"].sum())
    if n_unexplained:
        print(f"{n_unexplained} declared items did not run and have no recorded "
              f"reason", file=sys.stderr)
    return 1 if (args.strict and n_unexplained) else 0


if __name__ == "__main__":
    raise SystemExit(main())
