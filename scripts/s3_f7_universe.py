"""Fix F7's universe and gate sequencing. Registered BEFORE any reversion number.

Universe = capacity floor (pre-registered in H-F7) INTERSECT enrichment-vs-shuffled-
null (a data-integrity filter designed after the collision measurement and before any
P&L number -- stated plainly rather than presented as pre-registered).

Also computes the L-0069 rank of the surviving position vectors in a common leg basis,
which is the number sd(SR) must be estimated over if F7 is ever graded.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_f7_universe.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER = _REPO / "docs" / "superpowers" / "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl"
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

BASIS = [2, 5, 7, 10, 15, 20, 30]


def weights(sig: str) -> np.ndarray:
    """Rate-space position vector: spread = -1/+1, fly = -1/+2/-1 (short-dated first)."""
    t = [int(x) for x in sig.split("-")]
    w = np.zeros(len(BASIS))
    if len(t) == 2:
        w[BASIS.index(t[0])], w[BASIS.index(t[1])] = -1.0, 1.0
    elif len(t) == 3:
        w[BASIS.index(t[0])] = -1.0
        w[BASIS.index(t[1])] = 2.0
        w[BASIS.index(t[2])] = -1.0
    return w


def main() -> None:
    cap = pd.read_parquet(OUT / "f7_capacity.parquet")
    enr = pd.read_parquet(OUT / "f7_enrichment.parquet")

    cap_pass = set(cap.loc[cap["passes"], "signature"])
    enr_pass = set(enr.loc[(enr["enrichment"] > 1.0) & (enr["z_vs_null"] >= 3.0), "signature"])
    universe = sorted(cap_pass & enr_pass, key=lambda s: (len(s.split("-")), s))

    depleted = sorted(enr.loc[enr["z_vs_null"] <= -3.0, "signature"])
    cap_only = sorted(cap_pass - enr_pass)
    enr_only = sorted(enr_pass - cap_pass)

    W = np.array([weights(s) for s in universe])
    rank = int(np.linalg.matrix_rank(W, tol=1e-9))

    res = {
        "universe": universe,
        "n_configs": len(universe),
        "rank_in_leg_basis": rank,
        "basis": BASIS,
        "capacity_pass": sorted(cap_pass),
        "enrichment_pass": sorted(enr_pass),
        "capacity_only_excluded": cap_only,
        "enrichment_only_excluded": enr_only,
        "actively_depleted_z_le_-3": depleted,
    }
    print(json.dumps(res, indent=2))
    (OUT / "f7_universe.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    row = {
        "ts": "2026-08-09T12:10:00", "id": "L-0082", "kind": "note", "family": "F7",
        "supersedes": "L-0080 and L-0081 (fixes the universe those rows were converging on); "
                      "H-F7 (fixes its gate SEQUENCING, which the registration left as one step)",
        "text": (
            "F7'S UNIVERSE AND GATE SEQUENCING FIXED, BEFORE ANY REVERSION OR P&L NUMBER EXISTS. "
            "|| THE STRUCTURAL FINDING, which is worth more than F7 and should outlive it: MOST "
            "APPARENT 2-LEG 'PACKAGES' IN A TIMESTAMP-LINKED SDR RECONSTRUCTION ARE COINCIDENCE, "
            "AND 3-LEG ONES ARE NOT. The shuffled-timestamp null permutes WHICH legs sit in each "
            "second while preserving the group-size distribution exactly, so it isolates tenor "
            "composition. Over 60 days x 20 draws the enrichment (as-built / null-mean) is "
            "5-10-30 13.8x (z 108.7), 2-5-10 8.2x (75.9), 5-7-10 11.9x (61.0), 10-15-30 24.9x "
            "(63.2), 10-20-30 24.2x (93.7), 15-20-30 28.2x, 10-15-20 24.4x - every liquid fly is "
            "an order of magnitude above chance. But among 2-leg signatures only 5-30 (2.44x), "
            "2-10 (2.28x), 10-30 (1.71x), 2-30 (1.53x) and 5-10 (1.23x) clear at all, and EIGHT "
            "ARE ACTIVELY DEPLETED at z <= -3: 7-10 (0.45x, z -7.8), 5-7 (0.51x), 10-20 (0.46x), "
            "5-20 (0.54x), 10-15 (0.46x), 2-7 (0.38x), 5-15 (0.39x), 15-30 (0.62x). A depleted "
            "signature is not a thin structure, it is NOT A STRUCTURE - two common tenors landing "
            "in the same second less often than chance. The raw capacity table would have handed "
            "F7 a universe containing four signatures (2-5, 5-7, 7-10, 7-30) that do not exist as "
            "traded packages, and the count would have flattered the capacity gate - the one gate "
            "F7 needed to pass. THE TEST'S LIMIT, stated because it is one-directional: for a pair "
            "of very common tenors the null is enormous (5-10's null mean is 817.6 against 1,007 "
            "as-built), so enrichment ~1 is LOW POWER, not evidence of unreality. Passing is "
            "evidence of reality; failing at z near 0 is 'not established', and only z <= -3 is "
            "evidence against. "
            "|| PROVENANCE, stated plainly: the capacity floor (>=60 packages per 60 trading days) "
            "and the canonical-leg restriction were registered before their numbers (H-F7, L-0080). "
            "THE ENRICHMENT FILTER WAS NOT - it was designed after seeing the collision "
            "measurement. It is admitted as a DATA-INTEGRITY filter on the same footing as the "
            "L-0018 holiday-ghost filter: it uses no P&L, no reversion, no cost and no horizon, "
            "only whether the instrument exists, and it was fixed before the first reversion "
            "number was computed. "
            "|| UNIVERSE = capacity INTERSECT enrichment = 10 signatures: FIVE spreads 2-10, 2-30, "
            "5-10, 5-30, 10-30 and FIVE flies 2-5-10, 5-7-10, 5-10-30, 10-15-30, 10-20-30. "
            "Excluded despite clearing capacity: 2-5, 5-7, 7-10, 7-30. Excluded despite clearing "
            "enrichment: 2-5-30, 7-10-15, 10-15-20, 15-20-30 (too thin to trade). L-0069 RANK, "
            "computed now rather than claimed later: the 10 position vectors in the common leg "
            f"basis {BASIS} have RANK {rank} - so F7 has 10 configs but only {rank} independent "
            "directions, and any sd(SR) claim over the registered set must be read against "
            f"{rank}, not 10. (H-F7's PRIMARY sd source remains the external 0.275843, unchanged.) "
            "|| GATE SEQUENCING FIXED IN TWO STEPS, because the single-step form registered in "
            "H-F7 contains a trap I would otherwise have walked into. STEP (i) POND, consumes 0 "
            "trials: perfect-direction |move| of each structure at h in {1,5,21}bd against the "
            "governing round trip. It is an upper bound, so failing it cannot be a false negative "
            "and passing it proves nothing. STEP (ii) INCREMENT, consumes K=10: signal-direction "
            "reversion, conditional-on-shock minus unconditional. THE TRAP, named so that it "
            "cannot be used: an increment measured on the PERFECT-DIRECTION statistic would pass "
            "almost automatically, because shock days are high-volatility days and |move| is "
            "larger on them for reasons that have nothing to do with mean reversion. The increment "
            "must therefore be measured on the SIGNAL-DIRECTION statistic - the registered rule's "
            "own realised gross - and per the V-V-17 precedent that consumes trials, which is why "
            "step (ii) charges all 10 whether or not any signature survives it. Both the fade and "
            "the momentum direction are reported (charter point 6): 'the better of two mirrors is "
            "not information', so fade must win AND the increment must be positive. Per-trade net "
            "bp and per-trade Sharpe are both reported, so a bigger pond bought with bigger risk "
            "cannot read as edge. MARK: the banked Citi quoted par grid par_grid_USD_SOFR.parquet, "
            "5,541 days x 44 tenors 2005-2026 - quoted par rates, never a fitted curve, per the "
            "design doc's marking policy. scripts/s3_f7_universe.py + f7_universe.json."
        ),
        "trials_delta": 0, "trials_total": 37,
    }
    existing = {json.loads(ln)["id"] for ln in
                LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()}
    if row["id"] not in existing:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"\nAPPEND {row['id']}")


if __name__ == "__main__":
    main()
