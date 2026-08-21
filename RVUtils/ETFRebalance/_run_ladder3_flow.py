"""Part 5: bucket ladder conditioned on a rebalance actually happening, held-composition
return (the same tradeable return definition as _run_ladder2.py's primary pass).

Restricts to dates where TLT's total held par changed by >=1% day/day -- a proxy for "a
creation/redemption basket is being assembled and the manager is actually trading",
against the unconditioned sample.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                       "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance._run_ladder import build_bucket_panel, add_hist_z, cs_z_by_date, orthogonalise, ic_across_dates  # noqa: E402
from RVUtils.ETFRebalance._run_ladder2 import attach_held_fwd  # noqa: E402

pd.set_option("display.width", 220)
HORIZONS = (5, 10, 21, 42, 63)
WIDTHS = (0.25, 0.5)
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "notebooks", "backtests", "etf_rebalance", "_data")


def main() -> int:
    fund, start, exec_lag = "TLT", "2016-01-01", 1
    sp = spec(fund)
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build([fund], panel=panel)
    cfg = EN.merge_config({"fund": fund, "universe": {"start": start}})
    uni, _ = EN.prepare_universe(cfg, joined=joined, panel=panel)
    uni_fwd = IC.forward_residual_return(uni, HORIZONS)

    flows = HP.flag_flow_days(joined[joined["ticker"] == fund], threshold=0.02)
    flows["d_par"] = flows.groupby("ticker")["fund_par"].diff()
    flows["par_pct"] = flows["d_par"] / flows.groupby("ticker")["fund_par"].shift()
    flow_dates = set(flows.loc[flows["par_pct"].abs() >= 0.01, "date"])
    print(f"flagged {len(flow_dates)} of {flows['date'].nunique()} dates as material "
          f"total-par change (>=1% day/day) -- info date, trades at +{exec_lag}", flush=True)

    rows = []
    for width in WIDTHS:
        g = build_bucket_panel(uni, sp, width)
        g = add_hist_z(g, col="w_f", out_col="raw_bucket_hist_z", lookback=250)
        g = attach_held_fwd(g, uni_fwd, sp, width, HORIZONS)
        g["z_bucket_active"] = cs_z_by_date(g["raw_bucket_active"], g["date"])
        g["z_bucket_hist_z"] = cs_z_by_date(g["raw_bucket_hist_z"], g["date"])
        g["z_resid"] = cs_z_by_date(g["resid_med"], g["date"])
        n_buckets_med = int(g.groupby("date")["bucket"].nunique().median())
        min_names_full = max(5, n_buckets_med // 3)

        gl = g.sort_values(["bucket", "date"]).copy()
        for c in ("z_bucket_active", "z_bucket_hist_z", "z_resid"):
            gl[f"{c}_lag"] = gl.groupby("bucket")[c].shift(exec_lag)
        gl_flow = gl[gl["date"].isin(flow_dates)].copy()
        gl_rest = gl[~gl["date"].isin(flow_dates)].copy()

        for sname, scol in (("bucket_active", "z_bucket_active_lag"),
                            ("bucket_hist_z", "z_bucket_hist_z_lag")):
            for subset_name, sub in (("flow_days", gl_flow), ("non_flow_days", gl_rest)):
                pcol = orthogonalise(sub, scol, "z_resid_lag")
                sub2 = sub.copy()
                sub2["_p"] = pcol
                for h in HORIZONS:
                    retcol = f"held_fwd_{h}"
                    mn = max(5, min_names_full // 2) if subset_name == "flow_days" else min_names_full
                    r_raw = ic_across_dates(sub, scol, retcol, min_names=mn)
                    r_p = ic_across_dates(sub2, "_p", retcol, min_names=mn)
                    rows.append({"width": width, "signal": sname, "subset": subset_name,
                                 "horizon": h, "n_dates_available": sub["date"].nunique(),
                                 "ic_raw": r_raw.get("ic"), "t_raw": r_raw.get("t"),
                                 "n_obs_raw": r_raw.get("n_dates"),
                                 "ic_partial": r_p.get("ic"), "t_partial": r_p.get("t"),
                                 "n_obs_partial": r_p.get("n_dates")})

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT_DIR, "ladder3_flow_conditioned_held.csv"), index=False)
    print("\n" + "=" * 110)
    print("5. HELD-COMPOSITION RETURN, CONDITIONED ON A MATERIAL TOTAL-PAR-CHANGE DAY")
    print("=" * 110)
    print(out.round(4).to_string(index=False))
    print("\nDONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
