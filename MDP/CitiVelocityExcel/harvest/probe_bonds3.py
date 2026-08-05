r"""Bonds round 3: map CVCURVEBOND's tag vocabulary and confirm that the
"empty" bond values are bond-TYPE dependent rather than absent.

US912810UA42 is a straight Treasury, so YIELD_WORST / ZSPREAD / CAS / OAS-to-call
have nothing to say. Pulling a corporate or callable ISIN out of CVCURVEBOND and
re-testing those measures settles it.

RATES.BONDS.* (plural) is NOT one of the 33 families in the timeseries DAG - it is
a separate curve namespace used only by CVCURVEBOND.
"""

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober, show  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
DATE = "20260803"

COUNTRIES = ["USA", "GBR", "DEU", "FRA", "ITA", "ESP", "JPN", "CAN", "AUS", "NLD",
             "CHE", "SWE", "NOR", "DNK", "NZL", "MEX", "BRA", "CHN", "KOR", "ZAF"]
CCY_FOR = {"USA": "USD", "GBR": "GBP", "DEU": "EUR", "FRA": "EUR", "ITA": "EUR",
           "ESP": "EUR", "JPN": "JPY", "CAN": "CAD", "AUS": "AUD", "NLD": "EUR",
           "CHE": "CHF", "SWE": "SEK", "NOR": "NOK", "DNK": "DKK", "NZL": "NZD",
           "MEX": "MXN", "BRA": "BRL", "CHN": "CNY", "KOR": "KRW", "ZAF": "ZAR"}
ASSET_TYPES = ["GOVT", "CORP", "AGENCY", "MUNI", "SUPRA", "SSA", "TIPS", "INFL",
               "ILB", "COVERED", "SOVEREIGN", "QUASI"]
MEASURES = ["YIELD", "PRICE", "SPREAD_TSY", "ASW_4_USD", "OAS", "ZSPREAD",
            "DURATION", "DV01"]

EMPTY_VALUES = ["YIELD_WORST", "YIELD_NEXT", "ZSPREAD", "CAS", "ASW_4_EUR",
                "ASW_4_GBP", "ASW_4_CHF", "CONVEXITY", "ASW", "OAS", "PRICE", "YIELD"]


def curvebond(p, tag, timeout=120):
    """Run CVCURVEBOND and return (nrows, isins, sample) - [] if the tag is bad."""
    anchor = p._anchor(30)
    p.ws.Range(anchor).Formula = f'=CVCURVEBOND("{tag}",FALSE)'
    try:
        p.app.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass
    v = p._settle(anchor, timeout=timeout)
    reg = p.ws.Range(anchor).CurrentRegion
    p._advance_past(anchor, reg)
    if reg.Rows.Count < 3:
        return 0, [], show(v)
    vals = reg.Value
    rows = [list(r) if isinstance(r, tuple) else [r] for r in vals] if isinstance(vals, tuple) else []
    hdr = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Date"), None)
    if hdr is None:
        return 0, [], show(v)
    body = rows[hdr + 1:]
    isins = [str(r[1]) for r in body if len(r) > 1 and r[1]]
    return len(body), isins, None


def main():
    p = Prober(SCRATCH / "bond_probe3.json", batch=10)
    found = {}
    try:
        print("=== A. CVCURVEBOND country x asset-type ===", flush=True)
        for ctry in COUNTRIES:
            ccy = CCY_FOR[ctry]
            hits = []
            for at in ASSET_TYPES:
                tag = f"RATES.BONDS.BY_COUNTRY.{ctry}.{ccy}.ASSET_TYPE_{at}.YIELD.{DATE}"
                n, isins, err = curvebond(p, tag)
                if n:
                    hits.append((at, n))
                    found[f"{ctry}/{at}"] = {"n": n, "sample_isins": isins[:3]}
            print(f"   {ctry} ({ccy}): " +
                  (", ".join(f"{a}={n}" for a, n in hits) if hits else "none"), flush=True)
            (SCRATCH / "bond_curves.json").write_text(json.dumps(found, indent=1))

        print("\n=== B. measures accepted by CVCURVEBOND (USA/GOVT) ===", flush=True)
        ok_meas = []
        for m in MEASURES:
            tag = f"RATES.BONDS.BY_COUNTRY.USA.USD.ASSET_TYPE_GOVT.{m}.{DATE}"
            n, _, err = curvebond(p, tag)
            print(f"   {m:<12} rows={n}", flush=True)
            if n:
                ok_meas.append(m)

        print("\n=== C. are 'empty' bond values type-dependent? ===", flush=True)
        corp = None
        for key, info in found.items():
            if key.endswith("/CORP") and info["sample_isins"]:
                corp = info["sample_isins"][0]
                break
        if corp is None:
            for key, info in found.items():
                if not key.endswith("/GOVT") and info["sample_isins"]:
                    corp = info["sample_isins"][0]
                    break
        if corp:
            print(f"   testing non-govt ISIN {corp}", flush=True)
            tags = [f"RATES.BOND.{corp}.{m}" for m in EMPTY_VALUES]
            res = p.probe_tshist(tags, freq="DAILY", period="5Y")
            for m in EMPTY_VALUES:
                r = res[f"RATES.BOND.{corp}.{m}"]
                print(f"      {m:<14} {r['status']:<7} sample={r.get('sample')}", flush=True)
        else:
            print("   no non-govt ISIN found to test with", flush=True)

        (SCRATCH / "bond_curves.json").write_text(
            json.dumps({"curves": found, "measures": ok_meas}, indent=1))
        print("\nwritten -> bond_curves.json", flush=True)
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
