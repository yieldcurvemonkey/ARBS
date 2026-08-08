"""Write F7's death rows. Run AFTER the adversarial audit reported."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROWS = [
    {
        "ts": "2026-08-09T16:30:00", "id": "V-F7", "kind": "verdict", "family": "F7",
        "text": (
            "F7 FLOW-CONDITIONED CURVE FADE: DEAD AT GATE. The thirteenth family dies, and it is "
            "the first one that got past the CAPACITY gate - the exact structures trade 10,000+ "
            "times in 643 days, so for once 'does the instrument trade' was not the question. "
            "|| GROUND 1, DECISIVE, AND IT SURVIVES ADMITTING EVERYTHING I EXCLUDED. H-F7 clause "
            "(5) passes the gate only if the conditional book clears the round trip on >= 2 "
            "signatures AT THE SAME h. The gate was re-run over the full 18-signature SUPERSET - "
            "the 10 registered plus all 8 the universe filter excluded - so that no exclusion of "
            "mine can be the reason it failed. Shock-book median gross against the round trip: at "
            "h=1, ZERO of 18 clear (best 5-10-30 +0.322 vs 3.60). At h=5, ZERO of 18 clear (best "
            "5-10-30 +0.731 vs 3.60). At h=21, EXACTLY ONE clears - 2-5 at +3.791 vs 1.80 - and "
            "every other cell fails, including 5-10 at +1.318 vs 1.80 and 2-5-10 at +0.536 vs "
            "3.60. One signature cannot satisfy a >=2 rule. F7 fails its own registered gate at "
            "every horizon even when the universe filter is switched off entirely. "
            "|| GROUND 2, THE MECHANISM, and it is the reason rather than a restatement of the "
            "result: THE FLOW SHOCK'S INFORMATION IS SAME-DAY AND IT IS GONE BY THE FILL. The "
            "shock variable is emphatically not broken - it fires on 11.7-14.2% of eligible days "
            "for all 10 signatures and it coincides with genuinely larger moves: median |dx| ratio "
            "1.548x on shock days, above 1 in 10 of 10 signatures, Mann-Whitney p<0.05 in 8 of 10, "
            "Spearman(flow, |dx|) +0.134..+0.335 with p <= 1.2e-3 in 10 of 10. But that elevation "
            "is 1.548x at the SIGNAL day t, 1.075x at the FILL day t+1, and 1.056 / 1.016 / 0.883 "
            "across the h=1/5/21 holding windows. By the time the registered lag-1 rule is in the "
            "trade there is no differential left to monetise. "
            "|| GROUND 3, THE INCREMENT IS INSIDE ITS OWN NULL, UNDER BOTH REGISTERED SHOCK "
            "DEFINITIONS. Count-based (primary): median increment vs the disjoint no-shock book "
            "-0.123 / -0.216 / -0.215 bp at h=1/5/21, wrong-day circular-shift placebo p(null >= "
            "real) = 0.880 / 0.615 / 0.775 with null sd 0.096 / 0.213 / 0.446. Notional-weighted "
            "(the registered SENSITIVITY, run and reported rather than skipped): -0.064 / -0.272 / "
            "-0.225 bp, placebo p 0.695 / 0.755 / 0.765. A randomly-dated shock beats the real one "
            "62-88% of the time and the null's own dispersion is larger than the effect, under "
            "both definitions. "
            "|| THE EXECUTABLE CHECK AGREES. The QDB notebook runs the gate's single MOST "
            "FAVOURABLE cell - 5-10 at h=21, increment +3.750 bp, the largest anywhere in the "
            "table - and it dies: 15 episodes, per-trade Sharpe -0.549, net -3.108 bp against the "
            "1.80 bp registered round trip, hit 47%, NW t -4.06, engine ends -$4,175,985 on a "
            "$100k/bp package, DSR 0.0000 / 0.0002 / 0.0000 at N=55 under the PRIMARY external "
            "sd(SR)=0.275843, the narrowed 0.103300 and F7's own 0.364848. Engine-vs-panel "
            "per-episode corr 0.9729 clears the 0.97 bar, though median |diff| is 1.069 bp against "
            "a 1.318 bp gross median - stated, not smoothed. And that cell is the cleanest "
            "possible demonstration of why L-0082 registered the MEDIAN as the headline: its "
            "+3.750 bp increment is not the shock book being good, it is the CONTROL being "
            "unusually bad there (no-shock hit rate 10%, gross median -2.432 bp). Selecting the "
            "max-increment cell selects a bad control. "
            "|| THE MARK IS EXONERATED BY AN INDEPENDENT DATASET. The obvious way to manufacture a "
            "fly death is a smoothed vendor curve that annihilates curvature - the model-mark "
            "mirage this program has now hit three times. It did not happen: rebuilding every "
            "structure from the TRADED leg rates in the Part 43 tape (a different dataset from the "
            "Citi grid entirely, daily median across packages) gives traded-minus-grid deviation "
            "medians of +0.12 bp (5-10-30), -0.01 (2-5-10), -0.05 (5-7-10), +0.01 (10-15-30), "
            "-0.07 (10-20-30), -0.05 (10-30), +0.06 (5-10), and the pond ratios agree to two "
            "decimals at h=21. "
            "|| THE FADE IS THE LOSING MIRROR, AND THE MIRROR IS NOT CLAIMABLE. corr(z_t, the "
            "forward move) is POSITIVE - median +0.110 at h=5 and +0.127 at h=21 - so these "
            "structures TREND at these horizons in this sample rather than revert. Momentum "
            "therefore wins by construction, and its increment is the exact per-trade negation "
            "(+0.123 / +0.216 / +0.215 bp, verified to allclose on all 90 cells). Charter point 6 "
            "governs: the better of two mirrors is not information. And it does not matter "
            "arithmetically either - +0.216 bp is 8.3x short of the 1.80 bp 2-leg round trip and "
            "16.7x short of the 3.60 bp fly. Any momentum family must be registered on a sample "
            "these numbers were NOT read from. "
            "|| SCOPE, AND WHAT SURVIVES. The POND is real and is the largest this program has "
            "measured: the five 2-leg spreads clear the perfect-direction upper bound at h=21 by "
            "2.05-4.88x on the governing CM-2 line (5-30 4.88, 2-30 4.86, 10-30 2.66, 2-10 2.50, "
            "5-10 2.05) and by 0.96-2.08x on the pre-stated sensitivity line. What is dead is the "
            "HARVEST: neither the conditional nor the unconditional fade collects it, and flow "
            "conditioning adds nothing. trials_delta 18 (the registered K=10 plus the 8 superset "
            "signatures the robustness re-run examined - charged rather than treated as free, per "
            "L-0082's conservative reading) -> trials_total 55. Artifacts: f7_packages.parquet, "
            "f7_capacity.parquet, f7_enrichment.parquet, f7_universe.json, f7_gate.parquet, "
            "f7_gate_increment.parquet, f7_gate_verdict.json, f7_qdb_verdict.json, "
            "audit_f7_notional_result.json; notebook f7_flow_conditioned_qdb.ipynb (0 errors)."
        ),
        "trials_delta": 18, "trials_total": 55,
    },
    {
        "ts": "2026-08-09T16:35:00", "id": "L-0083", "kind": "checker", "family": "F7",
        "supersedes": "the grounds stated in commit f77aa245's message, which V-F7 replaces",
        "text": (
            "ADVERSARIAL AUDIT OF THE F7 DEATH - dispatched BEFORE the verdict row was written, "
            "with the brief INVERTED per the session-2 lesson: F7 is a death, so the maker's "
            "failure mode is not wishful thinking but killing a real family with a bug, and four "
            "independent probes were told to hunt defects that MANUFACTURE A DEATH or HIDE AN "
            "EFFECT. 15 agents, 296 tool calls; every claimed defect then went to a fresh agent "
            "briefed to REFUTE it. ALL FOUR PROBES RETURNED 'death_is_sound'. "
            "|| WHAT IT CONFIRMED BY RUNNING CODE RATHER THAN READING IT: the fade SIGN is correct "
            "(gross_bp hand-recomputed for 9 real episodes straight from the raw par columns, "
            "bypassing structure_series and zscore entirely - all 9 matched to <1e-9); the "
            "self-test is NOT blind to the one defect class that would manufacture this death "
            "(mutating side to +np.sign(z) makes it fail as designed: 'planted capture -15.963 != "
            "expected 16.000'); the pipeline is STRICTLY CAUSAL (recomputing z and shock on data "
            "truncated at 12 dates gives 0 mismatches at the boundary); the loop bounds lose no "
            "episode at either end; the flow join is intact and hand-verified; the shock threshold "
            "fires; the increment is robust to removing the non-overlap lock (-0.079/-0.380/-0.202 "
            "vs the committed -0.123/-0.216/-0.215); the cost convention matches L-0061 exactly; "
            "and the gate reproduces BIT-IDENTICALLY on a cold re-run (git status clean after). "
            "The 45 dropped tape-less days are 28 US holidays plus a contiguous 17-business-day "
            "cache gap 2023-12-07..12-29 that sits ENTIRELY inside the 60-day warmup and costs the "
            "gate nothing. "
            "|| WHAT IT WITHDREW - THREE OF THE FOUR HEADLINE NUMBERS THE MAKER WAS ABOUT TO PUT "
            "IN THE DEATH ROW. (1) 'All five flies fail the pond at every horizon, best 0.79x' is "
            "FALSE on every better estimator: 2-5-10 at h=21 is 1.08x on all eligible entry days, "
            "1.23x unconditional and 1.30x on the traded-rate mark. That fly dies at step (ii), "
            "NOT at pond, and V-F7 says so. (2) THE FILL-LAG MONOTONICITY CRITERION IS NOT "
            "EVIDENCE AT THIS SAMPLE SIZE - see L-0084. (3) The increment POINT ESTIMATES flip "
            "sign under a one-day change in the entry rule and every reading sits inside the "
            "placebo null, so the only honest step-(ii) headline is the p-values, not "
            "-0.123/-0.216/-0.215. V-F7 is written to those three corrections. "
            "|| ALSO CORRECTED, AND NOTE THE DIRECTION: the '2.0-4.1x' spread pond quoted in "
            "commit f77aa245 matches neither committed cost line. It was traced to the SUPERSEDED "
            "pre-fix run on the union sample (before the 45 tape-less days were dropped), which "
            "reproduces as 1.98-4.14x. The committed figures are 2.05-4.88x on the governing line "
            "and 0.96-2.08x on the sensitivity line - so the stale digit UNDERSTATED the pond, "
            "i.e. for once the error flattered the DEATH rather than the maker. A second surviving "
            "note: the h=21 pond is a median over only 19-21 non-overlapping episodes and a sweep "
            "of all 21 block-phase offsets puts 10-30 anywhere in 1.49-3.23x against a committed "
            "2.66x - the estimate is real in sign but not pinned to better than a factor of two. "
            "It never crosses 1.0x at any offset, so it changes no decision, but a future session "
            "must not size anything against the point estimate. Third: f7_packages.notional_sum "
            "can come out NEGATIVE (-70,000,000 on the audited case, +410,000,000 sign-guarded) "
            "because the raw notional strings are not sign-guarded; it propagates to 0 of 30 "
            "increment cells and 0 of 643 shock flags because the primary shock is COUNT-based, "
            "and the notional arm was re-run with the guard and still reports p 0.695/0.755/0.765. "
            "|| THE TALLY CHANGES SHAPE. Session 1: twelve defects, twelve flattered the maker. "
            "Session 2: seven, all seven flattered the maker. Session 3's audit found defects that "
            "flatter the DEATH - which is what an inverted brief is for, and it is the first time "
            "this program has caught that direction. The maker!=checker machinery caught them "
            "BEFORE the verdict row existed rather than after, which is the V-V-17 -> V-V-17B "
            "sequence run in the right order for the first time."
        ),
        "trials_delta": 0, "trials_total": 55,
    },
    {
        "ts": "2026-08-09T16:40:00", "id": "L-0084", "kind": "note", "family": None,
        "supersedes": "H-F7 clause (8a) and L-0069's fill-lag import (as a KILL CRITERION; both "
                      "remain valid as diagnostics)",
        "text": (
            "A REGISTERED KILL CRITERION THAT FIRES ON NOISE 88-95% OF THE TIME IS NOT A TEST. "
            "H-F7 clause (8a) made the FILL-LAG MONOTONICITY PROFILE the spine of its placebo "
            "battery, on L-0069's import from the sibling program: a real immediacy premium decays "
            "MONOTONICALLY in fill lag, so a NON-MONOTONIC profile is a noise signature and is a "
            "KILL. The audit measured what that criterion actually does at this sample size and "
            "the answer is that it fires on 88-95% OF PURE-NOISE DRAWS. With 4 lag points and "
            "11-38 episodes per cell, exact monotonicity is a low-probability event whether or not "
            "an edge exists, so 'non-monotonic' carries almost no information and 'monotonic' "
            "would have been the surprising outcome. THE IMPORT WAS NOT WRONG, IT WAS UNPOWERED: "
            "the sibling applied it to books with hundreds of trades, where the profile is "
            "estimated well enough to be informative. BINDING FROM HERE: a fill-lag profile may be "
            "REPORTED as a diagnostic at any n, but it may only be registered as a KILL CRITERION "
            "alongside a stated false-positive rate computed at the family's own episode count - "
            "and if that rate is above ~20% the criterion must be registered as descriptive "
            "instead. This generalises past fill lag and is the natural companion to the "
            "session-2 rule about self-tests: BEFORE CITING A TEST, ASK NOT ONLY WHAT MUTATION IT "
            "WOULD FAIL TO CATCH (V-V-17B) BUT ALSO HOW OFTEN IT FIRES WHEN NOTHING IS WRONG. F7's "
            "verdict does not rest on it; V-F7 rests on the >=2-signature rule, the same-day "
            "mechanism and the placebo p-values."
        ),
        "trials_delta": 0, "trials_total": 55,
    },
    {
        "ts": "2026-08-09T16:45:00", "id": "L-0085", "kind": "note", "family": None,
        "text": (
            "THE THIRD INDEPENDENT INSTANCE OF THE SAME MECHANISM, AND THE FIRST ONE MEASURED ON A "
            "SIGNAL THAT IS NOT THE MARK. This program's central empirical finding now has three "
            "legs, and F7's is the cleanest because its trigger comes from a DIFFERENT DATASET "
            "than its P&L. (1) H13: the entire graded net was the entry-day flow - +70.9 bp of a "
            "+106.7 bp arm, entry days averaging 17x the unconditional daily mean, permutation p "
            "0.0006 (L-0051, L-0058, L-0065). (2) The Citi CM spread's own ac1 = -0.392 against "
            "per-leg -0.045/-0.023, so ~39% of a daily spread move is one-day-reversing vendor "
            "bootstrap noise (L-0066); and the sibling pfin/ARBS retired a +5.24-Sharpe butterfly "
            "book on d(spread) AR(1) ~ -0.25 with lag-1 alone removing ~80% of every Sharpe "
            "(L-0067). (3) NOW F7: a flow shock measured on the DTCC Part 43 tape - which cannot "
            "inherit the Citi curve's bootstrap noise, because it is not read off that curve at "
            "all - coincides with a 1.548x elevation in the structure's SAME-DAY absolute move "
            "(10/10 signatures, Spearman p <= 1.2e-3), and that elevation is 1.075x by the fill "
            "day and 1.056/1.016/0.883 across the holding windows. "
            "|| THE SENTENCE THIS EARNS: the information in a curve-RV signal at daily frequency "
            "is concentrated in the bar the signal is computed from, and this is now demonstrated "
            "for a vendor-mark signal, a same-mark signal, and an INDEPENDENT-DATASET signal. The "
            "third case is the important one, because it removes the obvious escape - 'the effect "
            "was the mark's noise, so a cleaner signal would survive'. F7's signal has no exposure "
            "to the mark's noise and the effect still dies at the fill. What is being measured is "
            "not a data-quality artifact; it is that price impact from curve-package flow is "
            "substantially resolved within the session in which it prints. THAT IS ALSO THE "
            "SHARPEST STATEMENT OF WHAT AN ALIVE CANDIDATE IN THIS DATA CLASS WOULD NEED: either "
            "an intraday fill (which F6 already killed on cost arithmetic - the boat is "
            "frequency-invariant while the pond shrinks), or a signal whose information is NOT "
            "resolved same-session. Everything this loop has tested is the former."
        ),
        "trials_delta": 0, "trials_total": 55,
    },
]


def main() -> None:
    existing = {json.loads(ln)["id"] for ln in
                LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()}
    with LEDGER.open("a", encoding="utf-8") as fh:
        for r in ROWS:
            if r["id"] in existing:
                print(f"SKIP {r['id']}")
                continue
            fh.write(json.dumps(r) + "\n")
            print(f"APPEND {r['id']} ({len(r['text'])} chars)")


if __name__ == "__main__":
    main()
