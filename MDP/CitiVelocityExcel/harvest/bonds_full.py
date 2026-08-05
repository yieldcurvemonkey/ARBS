r"""Harvest every ISIN from CVCURVEBOND, then validate ISIN x value exhaustively.

CVCURVEBOND is the bond universe (RATES.BOND does not enumerate). Values confirmed
in rounds 1-3: PRICE YIELD SPREAD_TSY ASW_4_USD ASW_4_JPY OAS DURATION DV01.
Everything else in the desk's measure list is unpopulated even on agency paper.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober, show  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent
DATE = "20260803"
ISIN_FILE = SCRATCH / "bond_isins.json"
OUT = SCRATCH / "bond_tags_validated.json"

CURVES = [
    ("USA", "USD", ["GOVT", "AGENCY"]), ("GBR", "GBP", ["GOVT", "AGENCY"]),
    ("DEU", "EUR", ["GOVT", "AGENCY", "COVERED"]),
    ("FRA", "EUR", ["GOVT", "AGENCY", "COVERED"]),
    ("ITA", "EUR", ["GOVT", "AGENCY"]), ("ESP", "EUR", ["GOVT", "AGENCY"]),
    ("JPN", "JPY", ["GOVT"]), ("NLD", "EUR", ["GOVT", "AGENCY", "COVERED"]),
    ("CHE", "CHF", ["GOVT"]), ("SWE", "SEK", ["GOVT"]), ("NOR", "NOK", ["GOVT"]),
    ("DNK", "DKK", ["GOVT"]), ("NZL", "NZD", ["GOVT"]), ("MEX", "MXN", ["GOVT"]),
    ("BRA", "BRL", ["GOVT"]), ("CHN", "CNY", ["GOVT", "AGENCY"]),
    ("KOR", "KRW", ["GOVT"]), ("ZAF", "ZAR", ["GOVT"]),
]
VALUES = ["PRICE", "YIELD", "SPREAD_TSY", "ASW_4_USD", "ASW_4_JPY",
          "OAS", "DURATION", "DV01"]
CONTROLS = ["RATES.OIS.USD_SOFR.PAR.10Y", "RATES.BOND.US912810UA42.YIELD"]


def curvebond(p, tag):
    anchor = p._anchor(30)
    p.ws.Range(anchor).Formula = f'=CVCURVEBOND("{tag}",FALSE)'
    try:
        p.app.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass
    p._settle(anchor, timeout=180)
    reg = p.ws.Range(anchor).CurrentRegion
    p._advance_past(anchor, reg)
    vals = reg.Value
    if not isinstance(vals, tuple):
        return []
    rows = [list(r) if isinstance(r, tuple) else [r] for r in vals]
    hdr = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Date"), None)
    if hdr is None:
        return []
    out = []
    for r in rows[hdr + 1:]:
        if len(r) > 2 and r[1]:
            out.append({"isin": str(r[1]), "desc": str(r[2]) if r[2] else "",
                        "maturity": str(r[0])})
    return out


def main():
    p = Prober(SCRATCH / "bonds_full_ckpt.json", batch=15)
    try:
        ctl = p.probe_tshist(CONTROLS)
        if any(ctl[t]["status"] != "valid" for t in CONTROLS):
            print("CONTROLS FAILED:", {t: ctl[t] for t in CONTROLS}); return 1
        print("controls pass\n", flush=True)

        # --- 1. harvest ISINs ---
        if ISIN_FILE.exists():
            universe = json.loads(ISIN_FILE.read_text())
            print(f"resumed {sum(len(v) for v in universe.values())} ISINs", flush=True)
        else:
            universe = {}
        for ctry, ccy, types in CURVES:
            for at in types:
                key = f"{ctry}.{ccy}.{at}"
                if key in universe:
                    continue
                tag = f"RATES.BONDS.BY_COUNTRY.{ctry}.{ccy}.ASSET_TYPE_{at}.YIELD.{DATE}"
                bonds = curvebond(p, tag)
                universe[key] = bonds
                print(f"  {key:<20} {len(bonds):>5} bonds", flush=True)
                ISIN_FILE.write_text(json.dumps(universe, indent=1))

        isins = sorted({b["isin"] for v in universe.values() for b in v})
        print(f"\ntotal distinct ISINs: {len(isins):,}", flush=True)

        # --- 2. validate ISIN x value ---
        tags = [f"RATES.BOND.{i}.{v}" for i in isins for v in VALUES]
        print(f"validating {len(tags):,} bond tags "
              f"({len(isins):,} ISINs x {len(VALUES)} values)", flush=True)
        res = p.probe_tshist(tags, freq="DAILY", period="1M")

        per_value = {v: 0 for v in VALUES}
        valid = []
        for t in tags:
            if res.get(t, {}).get("status") == "valid":
                valid.append(t)
                per_value[t.rsplit(".", 1)[1]] += 1
        print(f"\n{'VALUE':<14}{'valid':>8}{'/':^3}{'ISINs':<8}  coverage")
        for v in VALUES:
            print(f"{v:<14}{per_value[v]:>8}{'/':^3}{len(isins):<8}"
                  f"  {per_value[v]/len(isins)*100:5.1f}%")
        print(f"\nTOTAL valid bond tags: {len(valid):,} / {len(tags):,}")

        OUT.write_text(json.dumps({
            "isins": len(isins), "values": VALUES, "universe_keys": list(universe),
            "per_value": per_value, "valid_tags": valid}, indent=1))
        print(f"written -> {OUT.name}", flush=True)
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
