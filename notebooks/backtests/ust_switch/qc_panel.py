"""Data-quality gate on the bond panel, run BEFORE any result is believed.

The 100bp cross-rank gate in ``data.gate_ytm`` catches catastrophic yield-solver failures
(the 2015-01-02 10y printing -2.12%). It cannot catch a subtler one -- a yield off by 10bp
rather than 400 -- and a 10bp error on a spread whose true standard deviation is 0.86bp is
still fatal.

So this tests the PROPERTY that a real spread has and a corrupted one does not:
**autocorrelation**. Two Treasuries of the same original-issue tenor at adjacent ranks
differ by one auction cycle of maturity; their yield spread is a slow, persistent series.
Measured on the clean 2015-16 10y slice it has lag-1 autocorrelation of **+0.915**. The
same slice with one bad row in 2,004 has **+0.014** -- indistinguishable from white noise.

A tenor/pair whose post-gate autocorrelation is near zero has residual corruption, and no
backtest on it means anything. This prints the number for every cell so the reader can
check rather than assume.

Also reported:
* daily-change standard deviation -- the noise floor a trading rule must beat, and the
  reason this trade is hard: it is comparable in size to the premium itself.
* the implied per-trade signal-to-noise at a one-cycle holding period.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.USTSwitch.data import load_prepared  # noqa: E402
from RVUtils.USTSwitch.grid import PAIRS, TENORS  # noqa: E402

pd.set_option("display.width", 250)
OUT = pathlib.Path(__file__).resolve().parent / "_out"

#: Below this, the "spread" is not a spread. A genuine one runs 0.85-0.99.
MIN_PLAUSIBLE_AUTOCORR = 0.50


def main() -> int:
    panel, _ = load_prepared()
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for tenor in TENORS:
        p = panel[panel["tenor"] == tenor]
        if p.empty:
            continue
        piv = p.pivot_table(index="date", columns="rank", values="YTM", aggfunc="first") * 100.0
        for ry, ro in PAIRS:
            if ry not in piv.columns or ro not in piv.columns:
                continue
            s = (piv[ro] - piv[ry]).dropna()
            if len(s) < 50:
                continue
            ds = s.diff().dropna()
            # Holding one auction cycle: how big is the random walk over that horizon
            # versus the level the trade is trying to capture?
            hold = 63 if tenor in (10, 20, 30) else 21
            rows.append(
                {
                    "tenor": tenor,
                    "pair": f"{_lbl(ry)}v{_lbl(ro)}",
                    "n": len(s),
                    "mean_bp": s.mean(),
                    "sd_bp": s.std(ddof=1),
                    "autocorr1": s.autocorr(1),
                    "daily_chg_sd_bp": ds.std(ddof=1),
                    "horizon_noise_bp": ds.std(ddof=1) * np.sqrt(hold),
                    "signal_to_noise": abs(s.mean()) / (ds.std(ddof=1) * np.sqrt(hold)),
                }
            )
    qc = pd.DataFrame(rows)
    qc.to_csv(OUT / "qc_panel.csv", index=False)

    print("=== PANEL QC: is each rank spread a real series? ===")
    print(qc.round(4).to_string(index=False))

    bad = qc[qc["autocorr1"] < MIN_PLAUSIBLE_AUTOCORR]
    print(f"\ncells with lag-1 autocorrelation < {MIN_PLAUSIBLE_AUTOCORR}: {len(bad)} of {len(qc)}")
    if len(bad):
        print("  *** these have residual corruption -- do not believe results on them ***")
        print(bad.round(4).to_string(index=False))
    else:
        print("  none -- every rank spread behaves like a spread, not like noise")

    print("\nnoise floor vs premium (why this trade is hard):")
    print(f"  median premium level          {qc['mean_bp'].abs().median():.3f} bp")
    print(f"  median one-cycle random walk  {qc['horizon_noise_bp'].median():.3f} bp")
    print(f"  median signal/noise per trade {qc['signal_to_noise'].median():.3f}")
    return 0 if len(bad) == 0 else 1


def _lbl(r: int) -> str:
    return {0: "CT", 1: "O", 2: "OO", 3: "OOO"}[int(r)]


if __name__ == "__main__":
    sys.exit(main())
