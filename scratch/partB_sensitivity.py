"""Part B step 3: how much does the imputation depend on the tail threshold u?

The u = C/10 run returned Pareto alpha < 1 (infinite mean) in 10 of 18 cells.
That is not evidence of a monstrous tail; it is evidence that [C/10, C) is the
*body* of the notional distribution, where a Pareto has no business being
fitted.  This script re-fits at several thresholds -- both u = C/k and
u = the q-th quantile of the cell -- and reports how alpha, E[X|X>C] and the
imputed DV01 share move.

Pulls the (cell x notional) frequency table ONCE and caches it.
"""
from __future__ import annotations

import json
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, OUT)
sys.path.insert(0, os.path.dirname(OUT))

from partB_tail_fit import (  # noqa: E402
    LN_SIGMA_MAX, fit_cell, lognorm_mean_above, pareto_mean_above,
)

pd.set_option("display.width", 330)
pd.set_option("display.max_rows", 600)
pd.set_option("display.max_columns", 60)
pd.set_option("display.float_format", lambda v: f"{v:,.4g}")

CACHE = os.path.join(OUT, "partB_freq_cache.csv")


def load_freq() -> pd.DataFrame:
    if os.path.exists(CACHE):
        print(f"[cache] {CACHE}")
        return pd.read_csv(CACHE)

    import psycopg2

    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

    with open(os.path.join(OUT, "partB_cap_schedule.json")) as fh:
        sched = json.load(fh)
    switch, bands = sched["switch_date"], sched["bands"]
    whens = []
    for b in bands:
        vc = (f"as_of_date <  DATE '{switch}'" if b["vintage"] == "V1"
              else f"as_of_date >= DATE '{switch}'")
        whens.append(f"WHEN {vc} AND tenor_years >= {b['lo']} AND tenor_years < {b['hi']} "
                     f"THEN '{b['vintage']}|{b['lo']}|{b['hi']}|{b['cap']:.0f}'")
    CELL = "CASE\n  " + "\n  ".join(whens) + "\n  ELSE NULL END"
    FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"
    conn = psycopg2.connect(resolve_pg_url())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        freq = pd.read_sql(f"""
            SELECT {CELL} AS cell, is_capped, notional,
                   count(*) AS n, sum(tenor_years) AS sum_t,
                   sum(notional*tenor_years*1e-4) AS sum_dv01
            FROM {LEGS_TABLE}
            WHERE {FLOW} AND tenor_years>0 AND notional>0 AND notional<1e11
            GROUP BY 1,2,3
        """, conn)
    conn.close()
    freq.to_csv(CACHE, index=False)
    print(f"[pulled] {len(freq):,} rows -> {CACHE}")
    return freq


def prep(freq: pd.DataFrame) -> pd.DataFrame:
    f = freq.dropna(subset=["cell"]).copy()
    m = f["cell"].str.split("|", expand=True)
    f["vintage"], f["lo"], f["hi"], f["cap"] = m[0], m[1].astype(float), m[2].astype(float), m[3].astype(float)
    for c in ("notional", "n", "sum_t", "sum_dv01"):
        f[c] = f[c].astype(float)
    return f


def run(freq: pd.DataFrame, thresh) -> pd.DataFrame:
    """thresh: ('div', k) -> u = C/k   |   ('q', q) -> u = q-quantile of the cell."""
    rows = []
    for cell, g in freq.groupby("cell", sort=True):
        C = g["cap"].iloc[0]
        cap_rows, sub_rows = g[g["is_capped"]], g[~g["is_capped"]]
        n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
        if thresh[0] == "div":
            u = C / thresh[1]
        else:
            v = g.sort_values("notional")
            cw = v["n"].cumsum() / v["n"].sum()
            u = float(v.loc[cw >= thresh[1], "notional"].iloc[0])
            u = min(max(u, C / 50), C / 1.8)
        t = sub_rows[(sub_rows["notional"] >= u) & (sub_rows["notional"] < C)]
        fit = fit_cell(t["notional"].to_numpy(), t["n"].to_numpy(), u, C, n_cap) if len(t) else None
        rec = {"vintage": g["vintage"].iloc[0], "lo": g["lo"].iloc[0],
               "hi": g["hi"].iloc[0], "cap": C, "u": u, "n_cap": n_cap,
               "tot_notional": float((g["notional"] * g["n"]).sum()),
               "tot_dv01": float(g["sum_dv01"].sum()),
               "cap_mean_t": float(cap_rows["sum_t"].sum() / cap_rows["n"].sum())}
        if fit:
            rec.update({k: fit[k] for k in (
                "n_sub", "par_alpha_cens", "ln_mu_cens", "ln_sigma_cens",
                "E_above_par_cens", "E_above_ln_cens", "pred_ncap_ln_cens",
                "pred_ncap_par_cens", "ks_pareto", "ks_lognorm", "ln_degenerate")})
        rows.append(rec)
    d = pd.DataFrame(rows)
    d["ln_mult"] = d["E_above_ln_cens"] / d["cap"]
    d["par_mult"] = d["E_above_par_cens"] / d["cap"]
    d["ncap_err_ln"] = d["pred_ncap_ln_cens"] / d["n_cap"] - 1.0
    d["exc_notional_ln"] = d["n_cap"] * np.maximum(d["E_above_ln_cens"] - d["cap"], 0)
    d["exc_dv01_ln"] = d["exc_notional_ln"] * d["cap_mean_t"] * 1e-4
    return d.sort_values(["vintage", "lo"]).reset_index(drop=True)


def main() -> int:
    freq = prep(load_freq())
    grid = [("div", 2.0), ("div", 4.0), ("div", 10.0), ("div", 20.0),
            ("q", 0.90), ("q", 0.95)]

    print("\n" + "=" * 110)
    print("SENSITIVITY OF THE HEADLINE NUMBER TO THE TAIL THRESHOLD u")
    print("=" * 110)
    head = []
    per_thresh = {}
    for th in grid:
        d = run(freq, th)
        per_thresh[th] = d
        n_inf = int((~np.isfinite(d["E_above_par_cens"])).sum())
        n_alpha_lt1 = int((d["par_alpha_cens"] < 1.0).sum())
        n_deg = int(d["ln_degenerate"].fillna(False).sum())
        tn, te = d["tot_notional"].sum(), d["exc_notional_ln"].sum()
        td, ted = d["tot_dv01"].sum(), d["exc_dv01_ln"].sum()
        head.append({
            "threshold": f"u=C/{th[1]:g}" if th[0] == "div" else f"u=q{th[1]:.2f}",
            "median_alpha": d["par_alpha_cens"].median(),
            "cells_alpha<1": n_alpha_lt1, "pareto_mean_inf": n_inf,
            "ln_degenerate": n_deg,
            "median_ln_mult": d["ln_mult"].median(),
            "max_abs_ncap_err": d["ncap_err_ln"].abs().max(),
            "imp_share_notional": te / (tn + te),
            "imp_share_dv01": ted / (td + ted),
        })
    H = pd.DataFrame(head)
    print(H.to_string(index=False))

    print("\n" + "=" * 110)
    print("PER-CELL, at the three most defensible thresholds (lognormal censored)")
    print("=" * 110)
    for th in (("div", 4.0), ("q", 0.90), ("q", 0.95)):
        d = per_thresh[th]
        lab = f"u=C/{th[1]:g}" if th[0] == "div" else f"u = cell quantile {th[1]:.2f}"
        print(f"\n--- {lab} ---")
        print(d[["vintage", "lo", "hi", "cap", "u", "n_sub", "n_cap",
                 "par_alpha_cens", "ln_sigma_cens", "ln_degenerate", "ln_mult",
                 "ncap_err_ln", "ks_lognorm", "ks_pareto"]].to_string(index=False))
        tn, te = d["tot_notional"].sum(), d["exc_notional_ln"].sum()
        td, ted = d["tot_dv01"].sum(), d["exc_dv01_ln"].sum()
        print(f"  imputed notional share {te/(tn+te):.3%}   "
              f"imputed DV01-proxy share {ted/(td+ted):.3%}")

    best = per_thresh[("q", 0.90)]
    best.to_csv(os.path.join(OUT, "partB_final_imputation.csv"), index=False)
    print(f"\nwrote {os.path.join(OUT, 'partB_final_imputation.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
