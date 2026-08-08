"""H14-graded — the manufactured package as a HOLD (pre-reg H-SV-14G).

Always-on USD 10y10y/20y10y flattener (the H13 unit ledger, already computed on
ghost-filtered curves) + a received 1y-fwd 2-7-30 fly at walk-forward
PCA-solved weights. The fly ledger is priced here: legs built at each solve,
AGED daily (npv on each day's curve), re-solved at the flattener's actual
25bp-trigger hedge days (from the unit ledger's ``n_hedges``) and at annual
roll boundaries; per-leg costs on |ΔDV01| per leg at
``RVUtils/cost_model.transaction_cost_bps`` half-spreads x{0.5,1,2}.

Headline: does the fly's carry net of its own maintenance improve the pure
book at 1x — full sample AND halves AND 2017+ (the H13 half-split honesty) —
with vega/gamma retention reported. 2-7-29 runs as a robustness arm.

Run: conda run -n stir python scripts/sv_citivelo_h14_graded.py [workers=5]
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"
PKG_DV01 = 100_000.0
PCA_WIN = 756
GRID = ["2Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"]
PCA_W = (1.0, 1.0, 1.0) + (0.0,) * (len(GRID) - 3)
PAIR_NAME = "USD 10Y10Y/20Y10Y"


def _fly_segment(seg_days: list, solve_days: list, tenors: tuple) -> dict:
    """Price the fly ledger for one roll segment. Worker-safe.

    Returns per-day rows: fly_mtm, fly_carry, resolve_trade_dv01 (per leg,
    summed at cost_model half-spreads outside).
    """
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    import logging

    logging.disable(logging.WARNING)
    import pandas as pd

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import CITIVELO_MARKET_CURVES, CITIVELO_SOURCE, citivelo_pairs
    from RVUtils.StrikelessVol.constructions import fly_hedge_weights
    from RVUtils.StrikelessVol.greeks import build_package, _reprice_dv01
    from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries
    from RVUtils.cost_model import transaction_cost_bps

    par = pd.read_parquet(DATA / "par_grid_USD_SOFR.parquet")[GRID].dropna(how="any")
    par.index = pd.to_datetime(par.index)

    mdp = IRSwapsMDP(source=CITIVELO_SOURCE)
    cm = mdp.bulk_get_data({"curve_name": CITIVELO_MARKET_CURVES["USD"],
                            "timestamps": seg_days, "offline": True})

    def _ok(ts, c):
        if c is None:
            return False
        ref = c.reference_date()
        ref_d = ref.date() if hasattr(ref, "date") else ref
        ts_d = ts.date() if hasattr(ts, "date") else ts
        return ref_d == ts_d

    curves = {pd.Timestamp(ts): c for ts, c in cm.items() if _ok(ts, c)}
    days = sorted(curves)
    if len(days) < 3:
        return {"rows": [], "err": "too few curves"}
    pair = next(p for p in citivelo_pairs(["USD"]) if p.name == PAIR_NAME)
    solve_set = {pd.Timestamp(d) for d in solve_days}

    leg_halfspread = {t: transaction_cost_bps({"2Y": 2, "7Y": 7, "29Y": 29,
                                               "30Y": 30}[t], 1.0)
                      for t in tenors}

    rows = []
    held = None          # dict tenor -> rl swap
    held_dv01 = None     # dict tenor -> $/bp at build
    prev_pv = None
    for d in days:
        curve = curves[d]
        resolve_dv01 = {}
        if d in solve_set or held is None:
            # book the OLD basket's final-day MTM before replacing it
            mtm_old = 0.0
            if held is not None and prev_pv is not None:
                try:
                    pv_old = sum(float(leg.npv(curves=curve.handle()).real)
                                 for leg in held.values())
                    mtm_old = pv_old - prev_pv
                except Exception:  # noqa: BLE001
                    mtm_old = 0.0
            try:
                hist = par.loc[:d].tail(PCA_WIN)
                model, _ = fit_curve_pca_from_timeseries(hist)
                pkg = build_package(curve, pair, package_dv01_usd=PKG_DV01)
                fly = fly_hedge_weights(curve, pkg, pca_model=model,
                                        fly_tenors=tenors, fly_fwd="1Y",
                                        pca_weights=PCA_W)
            except Exception as exc:  # noqa: BLE001
                rows.append({"date": str(d.date()), "err": type(exc).__name__})
                continue
            new_legs = fly["legs"]
            new_dv01 = {t: abs(_reprice_dv01(curve, leg)) for t, leg in new_legs.items()}
            for t in tenors:
                old = held_dv01.get(t, 0.0) if held_dv01 else 0.0
                resolve_dv01[t] = abs(new_dv01[t] - old)
            held, held_dv01 = new_legs, new_dv01
            prev_pv = sum(float(leg.npv(curves=curve.handle()).real)
                          for leg in held.values())
            rows.append({"date": str(d.date()), "fly_mtm": mtm_old, "fly_carry": 0.0,
                         **{f"trade_{t}": v for t, v in resolve_dv01.items()},
                         "belly_dir": fly["belly_direction"]})
            continue
        try:
            h = curve.handle()
            pv = sum(float(leg.npv(curves=h).real) for leg in held.values())
            rolled = sum(float(leg.npv(curves=h.roll(str((days[days.index(d)] - days[days.index(d) - 1]).days) + "d")).real)
                         for leg in held.values())
        except Exception as exc:  # noqa: BLE001
            rows.append({"date": str(d.date()), "err": type(exc).__name__})
            continue
        # CHECKER KILL (ledger V-SV-14G-KILL): an earlier version booked
        # mtm = pv - prev_pv (TOTAL PV change, which already realizes carry via
        # the par-struck legs) AND fly_carry on top — a carry double-count that
        # inflated the fly's gross from +8.8bp realized to +40.9bp. The ledger
        # now matches replication.simulate's convention: carry is the expected
        # roll and mtm is the REST of the PV change, so their sum is the
        # realized total, once.
        carry = rolled - pv
        mtm = (pv - prev_pv) - carry
        prev_pv = pv
        rows.append({"date": str(d.date()), "fly_mtm": mtm, "fly_carry": carry})
    return {"rows": rows, "leg_halfspread": leg_halfspread}


def main() -> None:
    from RVUtils.StrikelessVol.citivelo import stored_dates
    sys.path.insert(0, str(_REPO / "scripts"))
    from sv_static_long_control import roll_segments

    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    tenors = ("2Y", "7Y", "30Y")

    units = pd.read_parquet(DATA / "h13_units_USD.parquet").xs(PAIR_NAME, level="pair")
    hedge_days = list(units.index[units["n_hedges"] > 0])

    days = stored_dates("USD")
    segs = roll_segments(days, 12)
    seg_days = [days[i:j + 1] for (i, j) in segs]
    seg_solves = []
    for sd in seg_days:
        s0, s1 = pd.Timestamp(sd[0]), pd.Timestamp(sd[-1])
        seg_solves.append([d for d in hedge_days if s0 < d <= s1])
    print(f"{len(days)} days, {len(segs)} segments, {len(hedge_days)} hedge-trigger "
          f"re-solves, {workers} workers", flush=True)

    t0 = time.time()
    frames = []
    leg_hs = None
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fly_segment, sd, sv, tenors): k
                for k, (sd, sv) in enumerate(zip(seg_days, seg_solves))}
        done = 0
        for fut in as_completed(futs):
            out = fut.result()
            if out["rows"]:
                frames.append(pd.DataFrame(out["rows"]))
                leg_hs = out.get("leg_halfspread") or leg_hs
            done += 1
            print(f"  seg {done}/{len(segs)} ({time.time() - t0:.0f}s)", flush=True)

    fly = pd.concat(frames)
    fly["date"] = pd.to_datetime(fly["date"])
    # CHECKER KILL follow-up (V-SV-14G-KILL): boundary dates appear in BOTH the
    # segment that held the old fly (its P&L row) and the one that re-solved
    # (its trade row). The earlier keep="first" on as_completed order dropped
    # whichever arrived second — nondeterministic, and it deleted ~14 of ~21
    # re-initiations from the maintenance bill. Aggregate instead: sum the P&L
    # and trade columns, keep the last non-null label columns.
    num_cols = [c for c in fly.columns if c.startswith(("fly_", "trade_"))]
    lab_cols = [c for c in fly.columns if c not in num_cols and c != "date"]
    agg = {c: "sum" for c in num_cols}
    agg.update({c: "last" for c in lab_cols})
    fly = fly.groupby("date").agg(agg).sort_index()
    out = DATA / "h14_fly_ledger_USD.parquet"
    fly.to_parquet(out)

    n_err = int(fly.get("err").notna().sum()) if "err" in fly else 0
    trade_cols = [c for c in fly.columns if c.startswith("trade_")]
    fly_gross = fly[["fly_mtm", "fly_carry"]].fillna(0.0).sum(axis=1)
    maint_by_mult = {}
    for mult in (0.5, 1.0, 2.0):
        bill = 0.0
        for c in trade_cols:
            t = c.split("_")[1]
            bill += float(fly[c].fillna(0.0).sum()) * leg_hs[t] * mult
        maint_by_mult[mult] = bill

    pure_flows = units[["carry", "harvest", "mtm", "cross"]].sum(axis=1)
    dv = (units["long_notional"].abs() * units["dv01_long_unit"]).replace(0, np.nan)
    dv_mean = float(dv.mean())

    def bp(x):
        return float(x) / dv_mean

    joint = pd.DataFrame({"pure": pure_flows, "fly": fly_gross}).dropna()
    halves_ix = joint.index[len(joint) // 2]
    res = {
        "n_days": int(len(joint)),
        "n_resolves": int((fly[trade_cols].fillna(0.0).sum(axis=1) > 0).sum()),
        "n_errors": n_err,
        "pure_gross_bp": bp(joint["pure"].sum()),
        "fly_gross_bp": bp(joint["fly"].sum()),
        "fly_maintenance_bp": {str(k): bp(v) for k, v in maint_by_mult.items()},
        "combined_gross_bp": bp(joint.sum(axis=1).sum()),
        "fly_net_contribution_bp": {str(k): bp(joint["fly"].sum() - v)
                                    for k, v in maint_by_mult.items()},
        "half1_fly_net_bp": bp(joint.loc[:halves_ix, "fly"].sum() - maint_by_mult[1.0] / 2),
        "half2_fly_net_bp": bp(joint.loc[halves_ix:, "fly"].sum() - maint_by_mult[1.0] / 2),
        "post2017_fly_gross_bp": bp(joint.loc["2017":, "fly"].sum()),
        "post2017_pure_gross_bp": bp(joint.loc["2017":, "pure"].sum()),
        "daily_vol_pure_bp": bp(joint["pure"].std() * np.sqrt(252)),
        "daily_vol_combined_bp": bp(joint.sum(axis=1).std() * np.sqrt(252)),
    }
    with open(DATA / "h14_graded_USD.json", "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
    print(f"wrote {out.name} + h14_graded_USD.json in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
