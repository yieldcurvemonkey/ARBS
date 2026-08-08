# scripts/sv_check_curve_coverage.py
"""Print the GS instrument names available for each strikeless-vol curve."""
import re
from pathlib import Path

import pandas as pd

COVERAGE = (
    Path(__file__).resolve().parents[1]
    / "MDP" / "IRSwaps" / "GSQUANT" / "COVERAGE"
    / "IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx"
)

PATTERNS = {
    "USD-OIS": r"^USD Swap OIS 1y ATM 0b to (\d+)y LCH Cleared$",
    "EUR-ESTR": r"^EUR Swap EuroSTR 1y ATM 0b to (\d+)y LCH Cleared$",
    "JPY-TONAR": r"^JPY Swap JPY-TONA-OIS-COMPOUND 1y ATM 0b to (\d+)y LCH Cleared$",
    "GBP-SONIA": r"^GBP Swap OIS 1y ATM 0b to (\d+)y LCH Cleared$",
}


def main() -> None:
    df = pd.read_excel(COVERAGE)
    df["name"] = df["name"].astype(str)
    for curve, pat in PATTERNS.items():
        sub = df[df["name"].str.match(pat)].copy()
        yrs = sorted(int(re.match(pat, n).group(1)) for n in sub["name"])
        starts = sub["historyStartDate"].astype(str)
        print(f"{curve:10s} n={len(yrs):3d} max={max(yrs) if yrs else 0:3d}y "
              f"earliest_start={starts.min() if len(starts) else 'n/a'}")
        print(f"   tenors: {yrs}")
    # Front-end (meeting-dated) instruments, if any, for GBP.
    gbp_front = [n for n in df["name"] if n.startswith("GBP Swap OIS ATM ")]
    print(f"\nGBP meeting-dated front-end candidates: {gbp_front[:10]}")


if __name__ == "__main__":
    main()
