"""Record CM-4's result."""
import json
import pathlib

LEDGER = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers" /
          "ledgers" / "2026-08-08-citivelo-rv-loop-ledger.jsonl")

ROW = {
    "ts": "2026-08-09T22:00:00", "id": "L-0092", "kind": "gate", "family": None,
    "text": (
        "CM-4 RESULT - THE IMPACT EXPONENT IS MEASURABLE, AND IT IS NEARLY FLAT. Fitted per the "
        "design registered at L-0091, before any number existed: 211,027 consecutive print pairs "
        "inside 7,230 HOMOGENEOUS cells (one exact instrument - maturity AND effective date - "
        "inside a single hour, >= 20 spot USD OIS NEWT+TRAD prints), within-cell slope of "
        "log|move| on log(size) with cell means removed. "
        "|| THE NUMBER: eta = 0.0885 (2Y), 0.0313 (5Y), 0.0833 (10Y), 0.0908 (30Y), 0.0677 pooled, "
        "on the PRIMARY uncapped arm; the pre-stated capped-at-floor SENSITIVITY gives 0.1003 / "
        "0.0406 / 0.0957 / 0.0989 / 0.0785, higher exactly as predicted (recording a capped print "
        "at its floor understates its size and biases the exponent UP), so the two arms BRACKET "
        "eta in roughly [0.03, 0.10]. Observable size range p5-p95: $8mm-$357mm (2Y), $4mm-$200mm "
        "(5Y), $3mm-$120mm (10Y), $2mm-$53mm (30Y). "
        "|| SIZE MATTERS, AND THE CONTROL SAYS SO. The pre-registered shuffle null - sizes "
        "permuted WITHIN each cell, 200 draws, so ambient hourly volatility and cell composition "
        "are held fixed - centres on ZERO everywhere (null means -0.0009..+0.0005) and the "
        "measured exponent sits 5.2 to 25.0 standard deviations outside it. The reverse-causality "
        "confound the design named (large prints cluster in volatile hours) is handled by "
        "construction, because the fit is within-cell. So the effect is real and it is about size. "
        "|| BUT 0.07 IS NOT 0.5, AND THE HONEST READING IS THAT IT IS A LOWER BOUND. The "
        "square-root law would put eta ~ 0.5; the measured exponent is about a seventh of that, "
        "which would mean a 10x larger trade moves the rate only 10^0.07 ~ 1.17x as far. TWO "
        "READINGS, AND THIS STUDY CANNOT SEPARATE THEM: (a) cleared USD OIS genuinely has a much "
        "flatter impact curve than equities, which is economically plausible for an RFQ/block "
        "market where dealers quote size-insensitive spreads for standard clips; (b) THE ESTIMATE "
        "IS DILUTED - the dependent variable is |move between two consecutive prints|, which "
        "contains the second print's impact PLUS all ambient rate movement over the intervening "
        "minutes, and when ambient dominates, log|move| becomes nearly independent of size and the "
        "slope is pulled toward zero. Dilution can only push eta DOWN, so 0.03-0.10 is a LOWER "
        "BOUND and the square-root law is NOT refuted here - it is unreachable with this "
        "identification, which needs a clean pre-print reference price this tape does not supply. "
        "|| WHAT IT NEVERTHELESS BUYS, AND IT IS THE USEFUL PART: EVERY BACKTEST IN THIS PROGRAM "
        "CHARGES A SIZE-INDEPENDENT HALF-SPREAD, and that modelling assumption has never been "
        "checked. CM-4 checks it over the size range these strategies would actually trade: at "
        "eta <= 0.10, a FIFTY-FOLD change in clip size moves impact by at most 50^0.10 ~ 1.48x, "
        "and at the pooled 0.068 by 1.31x. So the flat cost line this program uses is a "
        "defensible approximation across the observable range - which is a validation of an "
        "assumption underneath fourteen verdicts, obtained from the tape rather than assumed. It "
        "does NOT license extrapolation above ~$350mm (2Y) or ~$50mm (30Y), where the data stops "
        "and the cap censors. "
        "|| RELATION TO CM-2 AND CM-3: this is an exponent, not a level, so it neither rescues nor "
        "damages CM-2's unclaimable level (L-0060 stands, L-0089 unchanged). L-0068's named step "
        "asked for eta by metaorder reconstruction with a Naviglio concavity correction; what is "
        "delivered is the simpler per-print version on homogeneous cells, and the metaorder form - "
        "which needs prints grouped into parent orders, and therefore a counterparty or "
        "package identifier the public tape withholds - REMAINS OPEN. trials_delta 0 (a "
        "measurement; no strategy config examined). scripts/s3_cm4_impact_exponent.py; "
        "cm4_pairs.parquet + cm4_eta_verdict.json."
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
