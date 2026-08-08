"""H14 gate — does Peter's manufactured package manufacture the grail state?

Weekly over the USD history: build the 10y10y/20y10y DV01-neutral flattener,
solve the 1y-forward 2-7-30 fly at PCA weights (walk-forward PCA on the
trailing 3y of par-grid changes — causal), and measure the package's carry
with and without the received fly:

    carry_pure(t)  = flattener daily roll
    carry_manu(t)  = flattener roll + fly roll at solved weights

The claim under test (pre-reg H-SV-14): the fly's carry covers the flattener's
bleed, i.e. occupancy(carry_manu >= 0) >> occupancy(carry_pure >= 0), while
retaining the vega (combined Γ ~ flattener Γ) at acceptable factor risk
(residual_pca_norm / target_pca_norm reported per day). Also tests the 5:1
prior against the solved fly weights, and prices BOTH 2-7-30 and 2-7-29.

Descriptive gate; grading (four ledgers, per-leg costs) follows only if the
occupancy answer is not already a kill.

Run:  conda run -n stir python scripts/sv_citivelo_h14_gate.py [step_days=5]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PKG_DV01 = 100_000.0
GRID = ["2Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"]
PCA_WIN = 756
PCA_W = (1.0, 1.0, 1.0) + (0.0,) * (len(GRID) - 3)  # first 3 PCs, non-uniform


def main() -> None:
    import logging

    logging.disable(logging.WARNING)
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import (
        CITIVELO_MARKET_CURVES, CITIVELO_SOURCE, citivelo_pairs, stored_dates,
    )
    from RVUtils.StrikelessVol.constructions import fly_hedge_weights, legs_roll_usd
    from RVUtils.StrikelessVol.greeks import (
        build_package, daily_roll_usd, package_gamma, package_npv,
    )
    from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries

    step = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    par = pd.read_parquet(DATA / "par_grid_USD_SOFR.parquet")[GRID].dropna(how="any")
    par.index = pd.to_datetime(par.index)

    pair = next(p for p in citivelo_pairs(["USD"]) if p.name == "USD 10Y10Y/20Y10Y")
    days = stored_dates("USD")
    eval_days = days[PCA_WIN // 5:][::step]  # need trailing history for PCA
    eval_days = [d for d in eval_days
                 if len(par.loc[:pd.Timestamp(d)]) >= PCA_WIN]
    print(f"{len(eval_days)} weekly eval days {eval_days[0]}..{eval_days[-1]}", flush=True)

    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    rows = []
    t0 = time.time()
    CHUNK = 100
    for lo in range(0, len(eval_days), CHUNK):
        chunk = eval_days[lo:lo + CHUNK]
        cm = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES["USD"],
                                "timestamps": chunk, "offline": True})
        cm = {(k.date() if hasattr(k, "date") else k): v for k, v in cm.items()}
        for d in chunk:
            curve = cm.get(d)
            if curve is None:
                continue
            ref = curve.reference_date()
            if (ref.date() if hasattr(ref, "date") else ref) != d:
                continue  # holiday ghost (see sv_citivelo_screen_parallel)
            try:
                hist = par.loc[:pd.Timestamp(d)].tail(PCA_WIN)
                model, _ = fit_curve_pca_from_timeseries(hist)
                pkg = build_package(curve, pair, package_dv01_usd=PKG_DV01)
                roll_flat = daily_roll_usd(curve, pkg, next_date=pd.Timestamp(d) + pd.Timedelta(days=1))
                gamma_flat = package_gamma(curve, pkg)
                rec = {"date": pd.Timestamp(d), "roll_flat_usd": roll_flat,
                       "gamma_flat": gamma_flat}
                for tenors, tag in ((("2Y", "7Y", "30Y"), "2730"),
                                    (("2Y", "7Y", "29Y"), "2729")):
                    try:
                        fly = fly_hedge_weights(curve, pkg, pca_model=model,
                                                fly_tenors=tenors, fly_fwd="1Y",
                                                pca_weights=PCA_W)
                        roll_fly = legs_roll_usd(curve, list(fly["legs"].values()),
                                                 next_date=pd.Timestamp(d) + pd.Timedelta(days=1))
                        rec[f"roll_fly_{tag}"] = roll_fly
                        rec[f"belly_dir_{tag}"] = fly["belly_direction"]
                        rec[f"resid_norm_{tag}"] = fly["residual_pca_norm"]
                        rec[f"target_norm_{tag}"] = fly["target_pca_norm"]
                        rec[f"w_{tag}"] = "|".join(
                            f"{t}:{v:+.0f}" for t, v in fly["weights_bpv"].items())
                    except Exception as exc:  # noqa: BLE001
                        rec[f"err_{tag}"] = f"{type(exc).__name__}"
                rows.append(rec)
            except Exception:
                continue
        print(f"  {min(lo + CHUNK, len(eval_days))}/{len(eval_days)} "
              f"({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows).set_index("date").sort_index()
    out = DATA / "h14_gate_USD.parquet"
    df.to_parquet(out)
    have = df.dropna(subset=["roll_fly_2730"]) if "roll_fly_2730" in df else df.iloc[:0]
    if len(have):
        carry_pure = have["roll_flat_usd"]
        carry_manu = have["roll_flat_usd"] + have["roll_fly_2730"]
        print(f"\nn={len(have)} eval days")
        print(f"occupancy carry_pure>=0: {(carry_pure >= 0).mean():.1%}")
        print(f"occupancy carry_manu>=0: {(carry_manu >= 0).mean():.1%}")
        print(f"median roll_flat {carry_pure.median():+.0f} $/d, "
              f"median fly roll {have['roll_fly_2730'].median():+.0f} $/d")
        if "resid_norm_2730" in have:
            frac = (have["resid_norm_2730"] / have["target_norm_2730"]).median()
            print(f"median residual/target PCA norm: {frac:.2f} "
                  f"(1.0 = fly removed nothing)")
    print(f"wrote {out.name} ({len(df)} rows) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
