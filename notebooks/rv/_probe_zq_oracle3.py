"""The FF kink residual, with the saturation artifact removed.

The naive version of this measurement fits ~13 meeting jumps to 12 contracts.
That system is under-determined, so an unpenalised least-squares fit interpolates
and the "residual" is ~0 **by construction** -- the same tautology the SR3 lab
hit when it matched residual scales and got an identical r-squared for every
calendar. A residual of 0.38 ticks means nothing until the fit is constrained.

So the jump path is penalised on its **second difference** exactly as in the SR3
work (``RVUtils.MeanRev.meetings.solve_smooth_path``), and lambda is swept. The
two limits are interpretable:

    lambda -> 0     saturate: residual -> 0, no information
    lambda -> inf   force the jump path onto a straight line in meeting index --
                    a perfectly regular Fed -- and the residual is everything a
                    smoothly-accelerating policy path cannot express

The number that matters is the oracle on the residual across that whole range,
because if it is negative at EVERY lambda then no choice of smoothing makes the
FF kink tradeable.

Run: conda run -n stir python notebooks/rv/_probe_zq_oracle3.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40)

from RVUtils.MeanRev.diagnostics import move_profile
from RVUtils.MeanRev.ff import ZQ_TICK_BP, delivery_window, zq_exposure_vector
from RVUtils.MeanRev.meetings import fomc_decisions, solve_smooth_path

DATA = REPO / "notebooks" / "data" / "zq_kink_fade"
LAMS = (0.0, 0.1, 1.0, 10.0, 100.0, 1e3, 1e5)
MAX_RANK = 12


def main() -> int:
    c = pd.read_parquet(DATA / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    live = c[~c["accruing"]].copy()
    live["rank"] = live.groupby("as_of")["imm_start"].rank(method="first").astype(int)

    meetings = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2031, 12, 31))
    codes = sorted(live["code"].unique(), key=lambda k: delivery_window(k)[0])
    win = {k: delivery_window(k) for k in codes}
    exp = {k: zq_exposure_vector(win[k][:2], meetings) for k in codes}

    wide = live.pivot_table(index="as_of", columns="code", values="rate_pct",
                            aggfunc="first").sort_index()
    rank = live.pivot_table(index="as_of", columns="code", values="rank",
                            aggfunc="first").reindex(index=wide.index,
                                                     columns=wide.columns)
    m_arr = np.array([pd.Timestamp(m) for m in meetings])

    # ------------------------------------------------ the identification check
    print("=" * 100, flush=True)
    print("IDENTIFICATION: how many meetings does the strip have to fit?", flush=True)
    print("=" * 100, flush=True)
    cnt = []
    for d in wide.index[::50]:
        row = wide.loc[d].dropna()
        legs = [k for k in row.index if rank.at[d, k] <= MAX_RANK]
        if len(legs) < 6:
            continue
        lo = min(win[k][0] for k in legs)
        hi = max(win[k][1] for k in legs)
        n_m = int(((m_arr >= pd.Timestamp(lo)) & (m_arr < pd.Timestamp(hi))).sum())
        cnt.append({"as_of": d, "n_contracts": len(legs), "n_meetings": n_m,
                    "params": n_m + 1, "over_determined": len(legs) - (n_m + 1)})
    cn = pd.DataFrame(cnt)
    print(cn[["n_contracts", "n_meetings", "params", "over_determined"]]
          .describe().round(2).to_string(), flush=True)
    print(f"\n  dates where the fit is UNDER-determined (params > contracts): "
          f"{int((cn['over_determined'] < 0).sum())} of {len(cn)}")
    print("  -> an unpenalised fit interpolates, and its residual is an artifact.",
          flush=True)

    # -------------------------------------------------------- the lambda sweep
    print("\n" + "=" * 100, flush=True)
    print("RESIDUAL AND ORACLE ACROSS THE PENALTY SWEEP", flush=True)
    print("=" * 100, flush=True)

    pairs = [(codes[i], codes[i + 1]) for i in range(len(codes) - 1)
             if codes[i] in wide.columns and codes[i + 1] in wide.columns]
    flies = [(codes[i], codes[i + 1], codes[i + 2]) for i in range(len(codes) - 2)
             if all(x in wide.columns for x in codes[i:i + 3])]

    rows = []
    for lam in LAMS:
        resid = pd.DataFrame(np.nan, index=wide.index, columns=wide.columns)
        for d in wide.index:
            row = wide.loc[d].dropna()
            legs = [k for k in row.index if rank.at[d, k] <= MAX_RANK]
            if len(legs) < 6:
                continue
            lo = min(win[k][0] for k in legs)
            hi = max(win[k][1] for k in legs)
            sel = np.flatnonzero((m_arr >= pd.Timestamp(lo)) & (m_arr < pd.Timestamp(hi)))
            if sel.size == 0:
                continue
            W = np.vstack([exp[k][sel] for k in legs])
            y = row[legs].to_numpy(dtype=float) * 100.0
            fit = solve_smooth_path(y, W, lam=float(lam))
            resid.loc[d, legs] = fit["resid"]

        res_sd = float(resid.stack().std())
        row_out = {"lam": lam, "resid_sd_bp": res_sd,
                   "resid_sd_ticks": res_sd / ZQ_TICK_BP}
        for name, struct, w, cost in (("spread", pairs, (-1.0, 1.0), 1.0),
                                      ("fly", flies, (-1.0, 2.0, -1.0), 2.0)):
            lv = {}
            for legs in struct:
                if any(l not in resid.columns for l in legs):
                    continue
                ok = np.ones(len(wide), dtype=bool)
                for l in legs:
                    ok &= (rank[l] <= MAX_RANK).fillna(False).to_numpy()
                lv["-".join(legs)] = (sum(x * resid[l]
                                          for x, l in zip(w, legs))).where(ok)
            lv = pd.DataFrame(lv)
            p = move_profile(lv, None, horizons=(21,), round_trip_bp=cost).iloc[0]
            row_out[f"{name}_sd_bp"] = float(lv.stack().std())
            row_out[f"{name}_absmove_h21"] = p["mean_abs_bp"]
            row_out[f"{name}_oracle_h21"] = p["oracle_net_bp"]
            row_out[f"{name}_pbeat"] = p["p_beat_cost"]
        rows.append(row_out)
        print(f"  lam={lam:<8g} resid sd {res_sd:6.3f}bp ({res_sd / ZQ_TICK_BP:5.2f} ticks)"
              f"  spread oracle {row_out['spread_oracle_h21']:+7.3f}"
              f"  fly oracle {row_out['fly_oracle_h21']:+7.3f}", flush=True)

    sw = pd.DataFrame(rows)
    print("\n" + sw.round(3).to_string(index=False), flush=True)
    sw.to_csv(DATA / "residual_lambda_sweep.csv", index=False)

    print(f"""
  READ THE lam -> inf END. At lam=0 the fit saturates and the residual is an
  artifact of having more meetings than contracts. At the stiff end the model is
  a perfectly regular Fed and the residual is everything else -- the honest
  upper bound on what an FF kink could be worth.

  best spread oracle across the whole sweep: {sw['spread_oracle_h21'].max():+.3f}bp (cost 1.0bp)
  best fly    oracle across the whole sweep: {sw['fly_oracle_h21'].max():+.3f}bp (cost 2.0bp)
""", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
