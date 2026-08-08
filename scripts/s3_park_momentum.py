"""Park the momentum-OOS idea with its caveats, and correct V-F8's ratio denominator."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROW = {
    "ts": "2026-08-09T21:00:00", "id": "L-0090", "kind": "parked", "family": "F9-momentum",
    "supersedes": "V-F8 (its |incr|/RT DENOMINATOR only; the verdict and every other figure "
                  "stand, and the correction makes the family fail by more)",
    "text": (
        "PARKED WITH ITS REASONING, NOT RUN: curve-structure MOMENTUM on an out-of-sample window. "
        "F7 measured corr(z_t, the forward move) POSITIVE at +0.110 (h=5) and +0.127 (h=21), so "
        "these structures TREND rather than revert in 2024-2026, and the registered fade is the "
        "losing mirror. The tempting move is to register momentum on 2005-2023, which this loop "
        "has never looked at. FOUR REASONS IT IS PARKED RATHER THAN RUN, in order of weight. "
        "(1) IT CONTRADICTS L-0088, WRITTEN THIS SESSION: that row concludes 'not another family "
        "on this data', and superseding a freshly written conclusion with NO NEW INFORMATION is "
        "precisely the manufacture-a-family shape the mandate forbids. A future session may run "
        "it, but it must first write a superseding row with a better reason than 'I thought of one "
        "more'. (2) THE PRE-GATE ARITHMETIC LOOKS PRE-DEAD, and should be computed properly before "
        "anyone registers: expected momentum capture ~ corr x E|move| ~ 0.127 x ~6bp ~ 0.8bp at "
        "h=21 against a 1.8bp 2-leg round trip, i.e. ~0.4x the boat before any harvest haircut. If "
        "that estimate survives a careful recomputation the family never earns a registration. "
        "(3) THE 'CLEAN OOS WINDOW' IS LESS CLEAN THAN IT LOOKS: USD SOFR did not exist before "
        "~2018, so the 2005+ par grid there is a vendor splice/backcast - L-0006 flagged exactly "
        "this class for EUR pre-ESTR and required per-tenor masking. A momentum result on "
        "2005-2017 marks would be partly a result about the splice, and any registration must "
        "carry that. (4) THE MIRROR PROVENANCE MUST BE WRITTEN INTO THE REGISTRATION: the "
        "direction would be chosen AFTER seeing the 2024-2026 fade lose, which charter point 6 "
        "governs; out-of-sample testing plus counted trials is a legitimate handling of an "
        "in-sample-generated hypothesis, but it has to be stated rather than quietly relied on. "
        "|| SEPARATE AND UNRELATED, A CORRECTION TO MY OWN V-F8 ROW, of the L-0086 class (a number "
        "quoted at a parameter it was not computed at): V-F8's |incr|/RT figures used RT = 1.8bp, "
        "because s3_f8_gate.py builds its headline off a pivot_table whose value columns are only "
        "n / gross_med / net_mean_1x / sharpe_per_trade - rt_cm2 is NOT among them, so the "
        "`if 'rt_cm2' in s else 1.8` fallback fired silently. The registered universe is half "
        "spreads (RT 1.8) and half flies (RT 3.6), so the correct mixed-median round trip is "
        "2.7bp. CORRECTED: |incr|/RT is 0.016 at h=5 (published 0.023) and 0.164 at h=21 "
        "(published 0.247). BOTH ARE SMALLER, so the published figures were the MORE GENEROUS "
        "reading and F8 fails its registered bar by ~64x rather than ~43x at h=5. The verdict, the "
        "episode-floor prong, the placebo p-values and every per-signature number in V-F8 are "
        "unaffected. Recorded here rather than as a dedicated row because it changes no "
        "conclusion - but it is recorded, because a silent unit fallback inside a headline "
        "statistic is exactly what this program keeps finding."
    ),
    "trials_delta": 0, "trials_total": 65,
}


def main() -> None:
    existing = {json.loads(l)["id"] for l in
                LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()}
    if ROW["id"] in existing:
        print("SKIP", ROW["id"])
        return
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ROW) + "\n")
    print("APPEND", ROW["id"], f"({len(ROW['text'])} chars)")


if __name__ == "__main__":
    main()
