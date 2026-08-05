r"""Bonds round 2.

1. Re-test the values that came back "recognised but no rows" on a 1W window with a
   much longer window - an empty short window is not evidence a measure is absent.
2. Probe further candidate values now that DV01 (absent from the desk's measure
   list) turned out to be valid.
3. Establish where the ISIN universe comes from: RATES.BOND does not enumerate, so
   CVCURVEBOND is the candidate source.
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import PENDING, XL_ERR, Prober, show  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
ISIN = "US912810UA42"

EMPTY_1W = ["YIELD_WORST", "YIELD_NEXT", "ZSPREAD", "CAS", "OAS",
            "ASW_4_EUR", "ASW_4_GBP", "ASW_4_CHF", "CONVEXITY", "ASW"]

MORE = [
    "ASW_4_JPY", "ASW_4_AUD", "ASW_4_CAD", "ASW_4_SEK", "ASW_C", "ASW_2_USD",
    "ZSPREAD_WORST", "OAS_MAT", "OAS_CALL", "GSPRD", "SPRD_TSY", "SPREAD",
    "BENCHMARK_SPREAD", "TSY_SPREAD", "REAL_YIELD", "BREAKEVEN", "INFL_BREAKEVEN",
    "MODDUR", "MACDUR", "EFF_DURATION", "SPREAD_DURATION", "KRD", "YIELD_MAT",
    "TRUE_YIELD", "CURRENT_YIELD", "ACCRUED_INTEREST", "REPO_RATE", "SPECIALNESS",
    "AMOUNT_OUTSTANDING", "FLOAT_AMT", "TOTAL_RETURN", "EXCESS_RETURN", "CARRY_ROLL",
]

CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y"]


def main():
    p = Prober(SCRATCH / "bond_probe2.json", batch=10)
    try:
        ctl = p.probe_tshist(CONTROLS)
        if ctl[CONTROLS[0]]["status"] != "valid":
            print("CONTROL FAILED"); return 1

        print("=== 1. re-test 'empty' values over a 5Y window ===", flush=True)
        tags = [f"RATES.BOND.{ISIN}.{m}" for m in EMPTY_1W]
        res = p.probe_tshist(tags, freq="DAILY", period="5Y")
        real, still = [], []
        for m in EMPTY_1W:
            r = res[f"RATES.BOND.{ISIN}.{m}"]
            (real if r["status"] == "valid" else still).append(m)
            print(f"   {m:<16} {r['status']:<7} sample={r.get('sample')}", flush=True)
        print(f"   -> real on longer window: {real}")
        print(f"   -> still empty: {still}")

        print("\n=== 2. further candidate values ===", flush=True)
        tags2 = [f"RATES.BOND.{ISIN}.{m}" for m in MORE]
        res2 = p.probe_tshist(tags2, freq="DAILY", period="5Y")
        extra = [m for m in MORE if res2[f"RATES.BOND.{ISIN}.{m}"]["status"] == "valid"]
        emptyx = [m for m in MORE if res2[f"RATES.BOND.{ISIN}.{m}"]["status"] == "empty"]
        print(f"   valid : {extra}")
        print(f"   empty : {emptyx}")

        print("\n=== 3. CVCURVEBOND: where do ISINs come from? ===", flush=True)
        anchor = p._anchor(40)
        f = ('=CVCURVEBOND("RATES.BONDS.BY_COUNTRY.USA.USD.ASSET_TYPE_GOVT.YIELD.20260803",FALSE)')
        p.ws.Range(anchor).Formula = f
        try:
            p.app.CalculateUntilAsyncQueriesDone()
        except Exception:
            pass
        v = p._settle(anchor, timeout=120)
        reg = p.ws.Range(anchor).CurrentRegion
        p._advance_past(anchor, reg)
        print(f"   anchor={show(v)!r} region={reg.Address} {reg.Rows.Count}x{reg.Columns.Count}",
              flush=True)
        vals = reg.Value
        rows = [list(r) if isinstance(r, tuple) else [r] for r in vals] if isinstance(vals, tuple) else [[vals]]
        for r in rows[:8]:
            print("     ", [str(c)[:26] for c in r[:8]], flush=True)

        out = {"isin": ISIN,
               "valid_1w": ["PRICE", "YIELD", "SPREAD_TSY", "ASW_4_USD", "DURATION", "DV01"],
               "valid_5y_only": real, "still_empty": still, "extra_valid": extra,
               "extra_empty": emptyx}
        (SCRATCH / "bond_values2.json").write_text(json.dumps(out, indent=1))
        print("\nwritten -> bond_values2.json")
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
