r"""Preflight probe: are the IMM-dated fly legs and long-end forward curves live?

Measures, on a SHORT window so the cost is bounded:
  * IMM-rolling fly            USD-SOFR-1D IMM_1x2y/IMM_1x5y/IMM_1x10y
  * IMM-dated (fixed) fly      USD-SOFR-1D IMM_U26x2y/IMM_U26x5y/IMM_U26x10y
  * long-end forward curves    10y10y/20y10y and 10y10y/15y10y
  * swaption ATMF nvol         3Yx1Y (the vega leg)
  * the CA panel               BLUES via IRSwapsTB.sfr_cvx_adj

Prints shape, head/tail, and the level correlation against BLUES CA so the
numbers can be graded against the user's published OLS (BLUES CA on the IMM fly:
n=161, R2=0.394, beta=+0.1461, const=+7.6893; BLUES CA on 10y10y/20y10y:
n=410, R2=0.505, beta=-0.0993, const=-0.3514).
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP  # noqa: E402
from Query.Unified.UnifiedQuery import UnifiedQuery  # noqa: E402
from Query.Unified.registry import UnifiedStructure, UnifiedValue  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402
from TB.IRSwaptionsTB import IRSwaptionsTB  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402

START = dt.date(2026, 1, 2)
END = dt.date(2026, 8, 21)

curve_mdp = IRSwapsMDP(source="citivelo_excel_rl")
vol_mdp = IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl",
                        request_defaults={"verify": False})

QUERIES = [
    ("imm1_fly", UnifiedQuery(curve="USD-SOFR-1D",
                              tenor="IMM_1x2y/IMM_1x5y/IMM_1x10y",
                              value=UnifiedValue.IRS_RATE)),
    ("imm2_fly", UnifiedQuery(curve="USD-SOFR-1D",
                              tenor="IMM_2x2y/IMM_2x5y/IMM_2x10y",
                              value=UnifiedValue.IRS_RATE)),
    ("immU26_fly", UnifiedQuery(curve="USD-SOFR-1D",
                                tenor="IMM_U26x2y/IMM_U26x5y/IMM_U26x10y",
                                value=UnifiedValue.IRS_RATE)),
    ("le_10y10y_20y10y", UnifiedQuery(curve="USD-SOFR-1D",
                                      tenor="10y10y/20y10y",
                                      value=UnifiedValue.IRS_RATE)),
    ("le_10y10y_15y10y", UnifiedQuery(curve="USD-SOFR-1D",
                                      tenor="10y10y/15y10y",
                                      value=UnifiedValue.IRS_RATE)),
    ("nvol_3y1y", UnifiedQuery(curve="USD-SOFR-1D",
                               selector={"shorthand": "3Yx1Y", "strike": "ATMF"},
                               structure=UnifiedStructure.IRSWAPTION_STRADDLE,
                               value=UnifiedValue.IRSWAPTION_NVOL)),
]


def main() -> None:
    t0 = time.time()
    tb_irs = IRSwapsTB(curve_mdp, show_tqdm=False)
    tb_vol = IRSwaptionsTB(vol_mdp, show_tqdm=False)

    print("=== CA panel (BLUES/GOLDS) ===")
    t = time.time()
    ca = tb_irs.sfr_cvx_adj(["GREENS", "BLUES", "GOLDS"], START, END)
    print(f"  shape {ca.shape}  {ca.index.min().date()}..{ca.index.max().date()} "
          f"({time.time()-t:.0f}s)")
    print(ca.notna().sum().to_string())
    print(ca.tail(3).round(3).to_string())

    out = {}
    for name, q in QUERIES:
        t = time.time()
        try:
            df = TimeseriesBuilder().get_timeseries(
                start=START, end=END, queries=[q], n_jobs=8,
                routers={"IRS": tb_irs, "IRSWAPTION": tb_vol},
            )
            col = df.columns[0]
            s = df[col].dropna()
            out[name] = s
            print(f"\n[{name}] OK col={col!r} n={len(s)} "
                  f"{s.index.min().date()}..{s.index.max().date()} "
                  f"({time.time()-t:.0f}s)")
            print(f"  head {s.iloc[:2].round(4).to_dict()}")
            print(f"  tail {s.iloc[-2:].round(4).to_dict()}")
            print(f"  mean {s.mean():.4f}  sd {s.std():.4f}  "
                  f"d-sd {s.diff().std():.4f}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[{name}] FAILED {type(exc).__name__}: {exc}")

    print("\n=== level OLS of BLUES CA on each regressor ===")
    y_full = ca["USD-SOFR-1D BLUES PACKS CVX_ADJ"] if \
        "USD-SOFR-1D BLUES PACKS CVX_ADJ" in ca.columns else ca.iloc[:, 1]
    for name, s in out.items():
        j = pd.concat([y_full.rename("y"), s.rename("x")], axis=1).dropna()
        if len(j) < 20:
            print(f"{name:20s} n={len(j)} -- too few")
            continue
        x = np.column_stack([np.ones(len(j)), j["x"].to_numpy()])
        b, *_ = np.linalg.lstsq(x, j["y"].to_numpy(), rcond=None)
        resid = j["y"].to_numpy() - x @ b
        r2 = 1.0 - resid.var(ddof=0) / j["y"].to_numpy().var(ddof=0)
        dw = float(np.sum(np.diff(resid) ** 2) / np.sum(resid ** 2))
        dj = j.diff().dropna()
        dr = float(dj["y"].corr(dj["x"]))
        dbeta = float(dj["y"].cov(dj["x"]) / dj["x"].var(ddof=1))
        print(f"{name:20s} n={len(j):4d} const={b[0]:+8.4f} beta={b[1]:+8.4f} "
              f"R2={r2:.3f} DW={dw:.3f} | dcorr={dr:+.3f} dbeta={dbeta:+.4f}")

    tb_irs.close()
    print(f"\ntotal {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
