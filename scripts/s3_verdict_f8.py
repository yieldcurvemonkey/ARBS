"""Write F8's death row and the axis-closure note."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROWS = [
    {
        "ts": "2026-08-09T19:00:00", "id": "V-F8", "kind": "verdict", "family": "F8",
        "text": (
            "F8 PERSISTENT FLOW-INTENSITY REGIME: DEAD AT GATE, on ALL THREE registered "
            "falsification prongs. Fourteenth family, and with it THE FLOW-CONDITIONING AXIS IS "
            "CLOSED (L-0088). "
            "|| PRONG 1, THE REGISTERED BAR. H-F8's bar is direction-free by construction - "
            "|median increment across signatures| > 1x the governing round trip - because F7 had "
            "already shown me on this same sample that the fade is the losing mirror, and a "
            "direction registered afterwards would launder a post-hoc choice (charter point 6). "
            "MEASURED: h=5 median increment -0.042bp against a 1.8bp round trip, |incr|/RT = "
            "0.023; h=21 -0.444bp, |incr|/RT = 0.247. The bar is missed by 43x and 4x. H-F8 stated "
            "in advance that F7's event-shaped state came in 8-17x short and that persistence "
            "would need an order of magnitude more; it delivered less, not more. "
            "|| PRONG 2, THE EPISODE FLOOR - AND IT IS THE HONEST LIMIT OF THE h=21 ARM. At h=21 "
            "ZERO of 10 signatures reach 10 non-overlapping episodes (n_regime runs 2 to 7). So "
            "the h=21 numbers - including the -0.444bp headline and the eye-catching per-signature "
            "swings from +2.691 (2-30) to -4.691 (2-10 and 5-10) - CARRY ALMOST NO INFORMATION and "
            "are not quotable as evidence in either direction. THE INFORMATIVE ARM IS h=5, where 6 "
            "of 10 signatures clear the floor (5-17 episodes), and it says nothing is there: "
            "increment -0.042bp against a placebo null sd of 0.321bp, i.e. 0.13 null standard "
            "deviations from zero. THE THINNESS IS STRUCTURAL, NOT BAD LUCK: the state needs a "
            "21-day trailing mean ranked against a 252-day trailing window, consuming 273 of 643 "
            "file-days before the >=10-consecutive-day persistence requirement thins it further. "
            "A PERSISTENT STATE AND A 643-DAY TAPE ARE CLOSE TO INCOMPATIBLE - carry that to any "
            "future session that wants to condition on a regime using this data. "
            "|| PRONG 3, THE PLACEBO COVERS IT AT BOTH HORIZONS. Wrong-day circular shift, "
            "scale-matched, 200 draws, two-sided because the registered bar is on the absolute "
            "increment: p(|null| >= |real|) = 0.895 at h=5 and 0.445 at h=21, against a registered "
            "kill threshold of p >= 0.10. A randomly-dated regime reproduces the measured "
            "increment about nine times out of ten at the horizon that has the episodes. "
            "|| AND THE LEVEL IS NEVER IN QUESTION. The regime book's own net at 1x is a median "
            "-3.583bp (h=5) and -4.250bp (h=21), and every one of the 20 signature-horizon cells "
            "is negative, ranging -2.93 to -9.71bp. As in F7, no cost line inside the pre-stated "
            "x{0.5,2} band brings that near zero. "
            "|| METHOD. Everything except the STATE was inherited verbatim from H-F7 and its "
            "amendments - the same 10-signature universe of rank 6, the same |z|>=1 "
            "two-consecutive-close entry, the same lag-1 fill on the same Citi quoted par grid, "
            "the same CM-2 governing cost line with cost_model as the pre-stated sensitivity, the "
            "same median-across-signatures headline, the same sd(SR) sources - so F8 tests the "
            "state and nothing else. Per L-0084 NO fill-lag kill criterion was registered; the "
            "profile is a diagnostic only (h=5: +0.064 / -0.449 / -0.042 / +0.002 at t+1/2/3/5), "
            "and at these episode counts it would have fired on noise regardless, which is exactly "
            "why L-0084 demoted it one family earlier. trials_delta 10 (the registered configs, "
            "one per signature, horizons registered as a pair) -> trials_total 65. "
            "scripts/s3_f8_gate.py + f8_gate.parquet, f8_gate_increment.parquet, "
            "f8_gate_verdict.json."
        ),
        "trials_delta": 10, "trials_total": 65,
    },
    {
        "ts": "2026-08-09T19:10:00", "id": "L-0088", "kind": "note", "family": None,
        "text": (
            "THE FLOW-CONDITIONING AXIS IS CLOSED. The session-3 handover named exactly ONE "
            "genuinely unexplored conditioning axis - every dead family here is a fade, and not "
            "one conditioned on WHY the dislocation exists (Huggins-Schaller ch1: fade transient "
            "richness, do not fade structural hedging demand). It has now been explored in all "
            "three of its available shapes, on the only dataset that carries the information, and "
            "none works. "
            "(1) MAGNITUDE, event-shaped - F7, a single-day top-decile flow shock. DEAD: the "
            "shock's information is REAL but resolved SAME-SESSION (1.548x move elevation at the "
            "signal day, 1.075x by the lag-1 fill, ~1.0 across the holding window); 0/18 "
            "signatures clear the round trip at h=1 and h=5 and 1/18 at h=21 against a >=2 rule; "
            "the increment sits inside its own placebo null under both registered shock "
            "definitions. "
            "(2) COMPOSITION - new-risk versus unwind, the one directional-ish thing the SDR "
            "yields even though SIDE does not (L-0073). NOT TESTABLE, and measured to be so BEFORE "
            "it was registered: unwinds are 2.75% of USD OIS flow (106/day against 3,553) and the "
            "unwind share has autocorrelation +0.105 / +0.098 / +0.118 / +0.012 at ~5/25/50/105 "
            "trading days - there is no unwind-dominance REGIME in this tape to condition on "
            "(L-0087). "
            "(3) PERSISTENCE, regime-shaped - F8, a trailing-21d intensity regime held >= 10 "
            "consecutive days, which is the one shape L-0085 explicitly left alive. DEAD on all "
            "three registered prongs, with the h=5 increment 0.13 null-sd from zero at placebo "
            "p = 0.895 (V-F8). "
            "|| THE CLAIM, SCOPE-CONDITIONED RATHER THAN UNIVERSAL: on USD spot curve packages, at "
            "EOD frequency, marked on quoted par rates and costed at the measured CM-2 line, "
            "KNOWING WHAT TRADED DOES NOT HELP YOU FADE WHAT MOVED. The reason is L-0085 and it is "
            "MECHANICAL rather than statistical - the price impact of curve-package flow is "
            "substantially resolved inside the session in which it prints, so any state built from "
            "the public tape is informative on day t and spent by day t+1. "
            "|| WHAT THIS DOES NOT SAY, named so the next session cannot over-read it: it does NOT "
            "test an intraday fill (F6 killed that separately, on cost arithmetic - the boat is "
            "frequency-invariant while the pond shrinks); it does NOT test a private flow feed "
            "carrying side; and it does NOT test a state built from something other than flow. "
            "|| WHAT REMAINS, stated honestly as thin: L-0085 leaves two shapes - an intraday fill "
            "and a signal whose information is not resolved same-session - and this loop has now "
            "closed the flow route to the second. A NON-FLOW persistent state (dealer positioning, "
            "issuance and supply calendars, index-extension demand, mortgage convexity triggers) "
            "is the remaining candidate class, and NONE of it lives in the Citi or DTCC data this "
            "mandate covers. So the honest next move is either NEW DATA or the machine work named "
            "at L-0068 - the CM-2 impact-exponent calibration, which the F7 package extract "
            "already supports - and NOT another family on this data. FOURTEEN families dead, "
            "nothing ALIVE, trials_total 65."
        ),
        "trials_delta": 0, "trials_total": 65,
    },
]


def main() -> None:
    existing = {json.loads(l)["id"] for l in
                LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()}
    with LEDGER.open("a", encoding="utf-8") as fh:
        for r in ROWS:
            if r["id"] in existing:
                print("SKIP", r["id"])
                continue
            fh.write(json.dumps(r) + "\n")
            print("APPEND", r["id"], f"({len(r['text'])} chars)")


if __name__ == "__main__":
    main()
