r"""Discover the available values under RATES.BOND.<ISIN>.<value>.

RATES.BOND has no children in the DAG (far too many ISINs to enumerate), so the
value vocabulary is probed directly against CVTSHIST using the desk's bond measure
catalogue as candidates, plus dotted/underscored variants and plausible extras.

Then the confirmed vocabulary is re-tested on further ISINs to prove it generalises
rather than being specific to one bond.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
CKPT = SCRATCH / "bond_probe.json"

PRIMARY = "US912810UA42"
OTHER_ISINS = ["US91282CQQ77", "US912810UU06", "US91282CRB99"]

MARKET_DATA = [
    "PRICE", "YIELD", "YIELD_WORST", "YIELD_NEXT",
    "SPREAD_BENCH.AT_ISSUANCE", "SPREAD_BENCH.YAS_BENCHMARK",
    "SPREAD_TSY", "ZSPREAD_CALL", "ZSPREAD_MAT", "ZSPREAD", "CAS", "OAS",
    "ASW_4_LCL", "ASW_C_LCL", "ASW_4_USD", "ASW_C_USD", "ASW_4_EUR", "ASW_C_EUR",
    "ASW_4_GBP", "ASW_C_GBP", "ASW_4_CHF", "ASW_C_CHF",
    "CONVEXITY", "DOLLAR_DURATION", "DURATION",
]
REFERENCE_DATA = [
    "MATURITYDATEYYYYMMDD", "COUPON_TYPE", "COUPONDIVIDENDRATE", "ISSUECURRENCY",
    "COUNTRY", "ISSUERNAME", "BBT", "INDUSTRY_SECTOR", "INDUSTRY_SUBGROUP",
    "MARKETSECTORDESCRIPTION", "RATING", "RATING_FITCH", "RATING_MOODY",
    "SENIORITY", "ISSUE_SIZE", "ISSUE_STATUS", "SEDOL", "RIC",
]
# dotted measures may be encoded with an underscore inside a tag segment
VARIANTS = [
    "SPREAD_BENCH_AT_ISSUANCE", "SPREAD_BENCH_YAS_BENCHMARK", "SPREAD_BENCH",
]
EXTRAS = [
    "MID", "BID", "ASK", "ACCRUED", "DV01", "MODIFIED_DURATION", "MAC_DURATION",
    "REPO", "CARRY", "ROLL", "ASW", "GSPREAD", "ISPREAD", "OAS_VOL", "PVBP",
    "CLEAN_PRICE", "DIRTY_PRICE", "YTM", "YTW", "AMT_OUTSTANDING", "ISIN",
]

ALL = MARKET_DATA + REFERENCE_DATA + VARIANTS + EXTRAS
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.TSY.TSY.OTR.10Y.YIELD"]


def main():
    p = Prober(CKPT, batch=12)
    try:
        ctl = p.probe_tshist(CONTROLS)
        if any(ctl[t]["status"] != "valid" for t in CONTROLS):
            print("CONTROLS FAILED:", ctl)
            return 1
        print("controls pass\n")

        tags = [f"RATES.BOND.{PRIMARY}.{m}" for m in ALL]
        print(f"probing {len(tags)} candidate values on {PRIMARY}", flush=True)
        res = p.probe_tshist(tags)

        good, empty, bad = [], [], []
        for m in ALL:
            t = f"RATES.BOND.{PRIMARY}.{m}"
            st = res[t]["status"]
            (good if st == "valid" else empty if st == "empty" else bad).append(m)

        print(f"\n=== VALID values on {PRIMARY}: {len(good)} ===")
        for m in good:
            print(f"   {m:<32} sample={res[f'RATES.BOND.{PRIMARY}.{m}'].get('sample')}")
        if empty:
            print(f"\n=== recognised but no rows in window: {len(empty)} ===\n   {empty}")
        print(f"\n=== rejected: {len(bad)} ===\n   {bad}")

        if good:
            print(f"\n=== does the vocabulary generalise to other ISINs? ===", flush=True)
            cross = [f"RATES.BOND.{i}.{m}" for i in OTHER_ISINS for m in good]
            r2 = p.probe_tshist(cross)
            for i in OTHER_ISINS:
                ok = sum(1 for m in good if r2[f"RATES.BOND.{i}.{m}"]["status"] == "valid")
                print(f"   {i}: {ok}/{len(good)} valid", flush=True)

        out = {"isin": PRIMARY, "valid": good, "empty": empty, "rejected": bad}
        (SCRATCH / "bond_values.json").write_text(json.dumps(out, indent=1))
        print(f"\nwritten -> bond_values.json")
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
