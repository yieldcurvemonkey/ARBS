"""Print ASSET_IDS_MAP entries for EUR/GBP/JPY from the GS swaption coverage.

Run this, paste the printed dict literals into definitions/IRSwaptions.py.
Generated rather than hand-typed: 240 assetIds are not worth transcribing.
"""
import re
import sys
from collections import defaultdict

from gs_quant.data import Dataset

from MDP.IRSwaptions.GSQUANT.ql.grid import _ensure_gs_session

CURVE_BY_CCY = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "GBP": "GBP-SONIA",
    "JPY": "JPY-TONAR",
}

NAME_RE = re.compile(
    r"^Swaption (?P<ccy>[A-Z]{3})-\S+ Payer (?P<expiry>\S+) (?P<tail>\S+) ATM"
)

# Every StrikelessVol market carries the identical 8-expiry x 6-tail ATM
# grid (measured directly against IR_SWAPTION_VOLS_V1_STANDARD's coverage,
# 2026-08-04). A NAME_RE format change that stops matching some currency's
# rows would otherwise fail silently -- the row is just `continue`d past,
# and the only trace is a smaller number in the stderr summary line. This
# turns that into a loud failure instead.
EXPECTED_STRUCTURES_PER_CURVE = 48


def main() -> None:
    _ensure_gs_session()
    cov = Dataset("IR_SWAPTION_VOLS_V1_STANDARD").get_coverage()
    out = defaultdict(dict)
    for _, row in cov.iterrows():
        m = NAME_RE.match(str(row["name"]))
        if not m:
            continue
        curve = CURVE_BY_CCY.get(m.group("ccy"))
        if curve is None:
            continue
        out[curve][row["assetId"]] = f"{m.group('expiry')} {m.group('tail')}"

    for curve, mapping in sorted(out.items()):
        print(f'    "{curve}": {{')
        for aid, struct in sorted(mapping.items(), key=lambda kv: kv[1]):
            print(f'        "{aid}": "{struct}",')
        print("    },")
        print(f"    # {curve}: {len(mapping)} structures", file=sys.stderr)

    counts = {curve: len(out.get(curve, {})) for curve in CURVE_BY_CCY.values()}
    bad = {c: n for c, n in counts.items() if n != EXPECTED_STRUCTURES_PER_CURVE}
    if bad:
        raise AssertionError(
            f"Structure count mismatch (expected {EXPECTED_STRUCTURES_PER_CURVE} "
            f"per curve, got {bad}). NAME_RE likely stopped matching some rows "
            "-- check IR_SWAPTION_VOLS_V1_STANDARD's coverage name format "
            "before trusting the printed dict literals above."
        )


if __name__ == "__main__":
    main()
