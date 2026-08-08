"""Record CM-3: a negative result about my own idea, and the diagnostic it produced."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROW = {
    "ts": "2026-08-09T20:30:00", "id": "L-0089", "kind": "note", "family": None,
    "text": (
        "CM-3 ATTEMPTED AND FAILED, AND THE FAILURE IS WORTH MORE THAN THE ATTEMPT. THE IDEA: "
        "CM-2 is decisive on the SHAPE of the linear cost line but not on its LEVEL, because "
        "|print - EOD mid| contains the execution spread PLUS intraday drift to the 15:00 ET stamp "
        "and is therefore an admitted UPPER BOUND (L-0060). Roll (1984) estimates an effective "
        "spread from the TRANSACTION SERIES ALONE - consecutive price changes carry a serial "
        "covariance of -s^2/4 under bid-ask bounce - so it needs no mid, no curve and no drift "
        "model. The design rested on the DIRECTION OF ITS BIAS: drift and information make "
        "consecutive changes more positively correlated, pushing the implied spread DOWN, so Roll "
        "should be a LOWER bound and the two together would BRACKET a level neither can pin alone. "
        "|| THE ESTIMATOR IS CORRECTLY IMPLEMENTED. Planted spreads of 0.2 / 0.5 / 1.0 bp are "
        "recovered at 0.192 / 0.505 / 0.956 (within 4.4%); on 200 spreadless random walks it "
        "returns a median 0.0063bp (p95 0.0169, no estimate at all on 41.5% of runs), negligible "
        "against the smallest case; and it is unmoved by pure drift (ratio 1.015 at mu=0.02, 1.013 "
        "at mu=0.10) and by momentum in the efficient rate (0.501 against a planted 0.5). "
        "|| THE ANSWER IS NEVERTHELESS IMPOSSIBLE. Run on 4,293 (tenor, day) cells over 641 days, "
        "the implied HALF-spread is 1.6-13.3bp by tenor (overall median 7.46bp, estimable on 94.4% "
        "of cells) - that is 3 to 30 TIMES a MEASURED UPPER BOUND of 0.32-0.53bp. Two estimates of "
        "one quantity cannot sit on opposite sides of a bound by an order of magnitude, so this is "
        "not a competing estimate; it is proof the estimator is inapplicable here. Note which way "
        "it fails: the number is far too BIG, so nothing in this program's cost line was ever "
        "flattered by it. "
        "|| THE DIAGNOSTIC IS THE ACTUAL RESULT, and it is decisive in the one direction that "
        "matters. Roll assumes consecutive prints are the SAME instrument at the SAME efficient "
        "price differing only by which side was crossed. A '10Y' cell in this tape is nothing of "
        "the sort: it pools every maturity inside a 15-day bucket, every effective date inside the "
        "5-day spot window, package legs struck away from mid, and prints spread over an 8-hour "
        "session. Removing that heterogeneity step by step collapses the estimate MONOTONICALLY: "
        "tenor bucket 10.616bp (23.6x CM-2) -> one EXACT maturity date 3.762bp (8.4x) -> plus one "
        "exact effective date 3.189bp (7.1x) -> plus a single one-hour window 0.830bp (1.8x). A "
        "12.8x collapse from pooling alone. SO ROLL ON AN SDR TAPE MEASURES INSTRUMENT DISPERSION "
        "AND INTRADAY RATE MOVEMENT, NOT THE BID-ASK, and about 92% of the naive estimate is "
        "contamination. "
        "|| WHAT THIS COSTS AND WHAT IT BUYS. It COSTS the bracket: Roll cannot lower-bound the "
        "linear cost line here, because its contamination is positive and large rather than "
        "negative as the design assumed, so CM-2's LEVEL REMAINS UNCLAIMABLE and L-0060 stands "
        "unchanged. It BUYS two things. (1) A number for anyone who later builds a trade-only cost "
        "estimator on this or any SDR tape: at the tightest homogeneity available (one instrument, "
        "one hour, ~30 prints) the estimate is 0.830bp and STILL falling, i.e. still contaminated - "
        "the route to a real trade-only level is tighter windows and more prints, and the sample "
        "thins fast. (2) A method warning that generalises past this program: A VALIDATED "
        "ESTIMATOR CAN STILL BE INAPPLICABLE, because validation on simulated data only tests the "
        "arithmetic, never whether the REAL data satisfies the assumptions the simulation was "
        "built to embody. My simulation planted bounce around a single efficient price; the tape "
        "supplies many instruments around many prices, and no amount of planted-value testing "
        "would have revealed that. The companion to L-0084 (how often does a test fire when "
        "nothing is wrong) is this: WHAT DOES MY SIMULATION ASSUME ABOUT THE DATA THAT THE DATA "
        "DOES NOT SATISFY? "
        "|| L-0068's named next step - the impact-exponent eta by metaorder reconstruction with a "
        "Naviglio concavity correction - is UNAFFECTED and still open; CM-3 was a cheaper attempt "
        "at the same target and it did not land. trials_delta 0 (a measurement; no strategy config "
        "examined). scripts/s3_cm3_roll_spread.py + s3_cm3_homogeneity.py; cm3_roll_cells.parquet, "
        "cm3_roll_verdict.json, cm3_homogeneity.parquet, cm3_homogeneity.json."
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
