r"""Validate the bond values the first sweep missed, across the whole universe.

The first sweep used 8 values chosen from a USD Treasury and a US agency, which is
a biased sample: ASW_4_<CCY> turns out to be a sparse cross-currency asset-swap
matrix (a bund has ASW_4_USD/GBP/CHF/AUD but NOT ASW_4_EUR), and CAS is populated
on CNY/KRW paper though empty on US paper.

Values dropped after showing zero hits across 14 bonds spanning every currency in
the universe: ZSPREAD, YIELD_WORST, YIELD_NEXT, CONVEXITY, ASW, and
ASW_4_{SEK,NOK,DKK,CAD,NZD,MXN,BRL,CNY,KRW,ZAR}.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
NEW_VALUES = ["ASW_4_EUR", "ASW_4_GBP", "ASW_4_CHF", "ASW_4_AUD", "CAS"]
OLD = json.loads((SCRATCH / "bond_tags_validated.json").read_text())
CONTROL = "RATES.OIS.USD_SOFR.PAR.10Y"


def main():
    uni = json.loads((SCRATCH / "bond_isins.json").read_text())
    isins = sorted({b["isin"] for v in uni.values() for b in v})
    ccy_of = {}
    for key, bonds in uni.items():
        c = key.split(".")[1]
        for b in bonds:
            ccy_of.setdefault(b["isin"], c)

    tags = [f"RATES.BOND.{i}.{v}" for i in isins for v in NEW_VALUES]
    print(f"validating {len(tags):,} tags ({len(isins):,} ISINs x {len(NEW_VALUES)})",
          flush=True)

    p = Prober(SCRATCH / "bonds_full2_ckpt.json", batch=15)
    try:
        if p.probe_tshist([CONTROL])[CONTROL]["status"] != "valid":
            print("CONTROL FAILED"); return 1
        res = p.probe_tshist(tags, freq="DAILY", period="1M")
    finally:
        p.close()

    per_value = {v: 0 for v in NEW_VALUES}
    matrix = {}
    valid = []
    for t in tags:
        if res.get(t, {}).get("status") == "valid":
            valid.append(t)
            isin, v = t.split(".")[2], t.rsplit(".", 1)[1]
            per_value[v] += 1
            matrix.setdefault(ccy_of.get(isin, "?"), {}).setdefault(v, 0)
            matrix[ccy_of.get(isin, "?")][v] += 1

    print(f"\n{'VALUE':<12}{'valid':>7}  coverage")
    for v in NEW_VALUES:
        print(f"{v:<12}{per_value[v]:>7}  {per_value[v]/len(isins)*100:5.1f}%")

    print(f"\ncross-currency ASW matrix (bond ccy -> populated ASW legs):")
    for ccy in sorted(matrix):
        row = ", ".join(f"{k}={n}" for k, n in sorted(matrix[ccy].items()))
        print(f"   {ccy:<5} {row}")

    total = len(OLD["valid_tags"]) + len(valid)
    out = {"new_values": NEW_VALUES, "per_value": per_value,
           "ccy_matrix": matrix, "valid_tags": valid,
           "grand_total_valid": total}
    (SCRATCH / "bond_tags_validated2.json").write_text(json.dumps(out, indent=1))
    print(f"\nnew valid: {len(valid):,}")
    print(f"GRAND TOTAL validated bond tags: {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
