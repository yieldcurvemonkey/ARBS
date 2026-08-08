"""F3 gate — liquid-tenor cross-sectional curve-RV reversion, non-overlapping.

A FRESH registration (not ING-lineage; that family died at its fidelity gate,
V-FING): per-day cross-sectional poly fit on the LIQUID forward strip only
(k = 2..19, where every underlying par tenor prints — the 21–29Y sawtooth
that blocked F-ING sits outside the universe by construction), residual vs
trailing 3y bands, and the tested NON-OVERLAPPING episode gate (v1's
overlap-inflation fixed). Post-splice restriction per currency. Descriptive:
median independent-episode reversion at 21/63bd vs a 1.0bp package round trip.

Run: conda run -n stir python scripts/f3_xsec_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

from RVUtils.INGCurve.xsec import episode_reversion_gate, xsec_residuals
from RVUtils.INGCurve.screen import residual_percentiles

sys.path.insert(0, str(_REPO / "notebooks" / "backtests" / "citivelo_rv"))
from ing_xsec_screen import build_panel  # reuses bootstrap/forwards, unmodified

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
CCYS = {"EUR": ("par_grid_EUR_EUROSTR.parquet", "2019-10-01"),
        "USD": ("par_grid_USD_SOFR.parquet", "2010-01-01"),
        "GBP": ("par_grid_GBP_SONIA.parquet", "2018-04-23"),
        "JPY": ("par_grid_JPY_TONAR.parquet", "2021-12-31")}
KS_MIN, KS_MAX = 2, 19
RT_BP = 1.0  # direction-neutral package round trip benchmark (design-doc swap costs)


def main() -> None:
    all_stats = []
    for ccy, (fn, splice) in CCYS.items():
        par = pd.read_parquet(DATA / fn)
        par.index = pd.to_datetime(par.index)
        p = build_panel(par, "poly", ks_min=KS_MIN, ks_max=KS_MAX)
        if p is None:
            print(f"{ccy}: no panel")
            continue
        resid = p["resid"]
        pct = residual_percentiles(resid, window=756, min_obs=252)
        mask = pd.Series(resid.index >= pd.Timestamp(splice), index=resid.index)
        stats, episodes = episode_reversion_gate(
            resid, pct["rank"], pct["p50"], restrict_mask=mask)
        stats["ccy"] = ccy
        all_stats.append(stats)
        episodes.to_parquet(DATA / f"f3_episodes_{ccy}.parquet", index=False)
        comp = episodes[(episodes["complete"]) & (episodes["in_restriction"])]
        if len(comp):
            med_d = comp["dislocation_bp"].abs().median()
            med21 = comp["reversion_21bd"].median()
            med63 = comp["reversion_63bd"].median()
            frac = float((comp["reversion_63bd"]
                          >= 0.5 * comp["dislocation_bp"].abs()).mean())
            print(f"{ccy}: {len(comp)} independent post-splice episodes | "
                  f"med |disloc| {med_d:5.1f}bp | med rev 21bd {med21:+5.2f} / "
                  f"63bd {med63:+5.2f}bp vs RT {RT_BP}bp | frac>50% {frac:.0%}",
                  flush=True)
        else:
            print(f"{ccy}: no complete post-splice episodes", flush=True)

    rep = pd.concat(all_stats, ignore_index=True)
    rep.to_parquet(DATA / "f3_gate_stats.parquet", index=False)
    print("\nper-tenor detail written to f3_gate_stats.parquet / f3_episodes_<ccy>.parquet")


if __name__ == "__main__":
    main()
