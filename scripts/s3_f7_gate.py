"""F7 gate: does conditioning a curve fade on FLOW beat the same fade unconditioned?

Two steps, exactly as fixed in L-0082 and for the reasons given there.

  STEP (i)  POND, consumes 0 trials. Perfect-direction |move| over the holding
            horizon against the governing round trip. An upper bound: failing it
            cannot be a false negative, passing it proves nothing.
  STEP (ii) INCREMENT, consumes K = 10. The registered rule's own realised gross,
            conditional-on-shock minus unconditional. Measured on the SIGNAL
            direction, never the perfect direction -- an increment measured on
            |move| would pass on volatility alone, since shock days are
            high-volatility days (the trap named in L-0082).

Conventions all fixed in H-F7 / L-0080 / L-0082:
  * flow aggregated by FILE DATE (dissemination), never execution timestamp
  * shock = top decile of the signature's own trailing 60-file-day count
  * entry |z| >= 1.0 with the same sign on two consecutive closes
  * lag-1 fill: signal at close t, enter at close t+1, exit at close t+1+h
  * mark = banked Citi QUOTED par grid, never a fitted curve
  * cost: governing = CM-2 measured flat 0.45bp/leg, RT = sum|w| x 2 x 0.45;
          sensitivity = RVUtils/cost_model's linear line; band x{0.5,1,2}

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_f7_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

BASIS = [2, 5, 7, 10, 15, 20, 30]
HORIZONS = [1, 5, 21]
Z_WIN, FLOW_WIN = 60, 60
Z_ENTRY = 1.0
SHOCK_Q = 0.90
CM2_HALF = 0.45                      # measured, flat in tenor (L-0060)
LAGS = [1, 2, 3, 5]                  # fill-lag monotonicity diagnostic


def cost_model_half(tenor: int) -> float:
    """RVUtils/cost_model's linear line, the pre-stated SENSITIVITY (design doc §cost)."""
    return 0.25 + 0.05 * min(tenor, 30)


def weights(sig: str) -> dict:
    t = [int(x) for x in sig.split("-")]
    if len(t) == 2:
        return {t[0]: -1.0, t[1]: 1.0}
    return {t[0]: -1.0, t[1]: 2.0, t[2]: -1.0}


def round_trips(sig: str) -> dict:
    w = weights(sig)
    sw = sum(abs(v) for v in w.values())
    return {
        "rt_cm2": 2.0 * sw * CM2_HALF,
        "rt_costmodel": 2.0 * sum(abs(v) * cost_model_half(k) for k, v in w.items()),
        "sum_abs_w": sw,
    }


# --------------------------------------------------------------------- panel
def structure_series(par: pd.DataFrame, sig: str) -> pd.Series:
    """Structure level in bp from quoted par rates (grid is in percent)."""
    w = weights(sig)
    cols = [f"{k}Y" for k in w]
    sub = par[cols].dropna()
    x = sum(v * sub[f"{k}Y"] for k, v in w.items()) * 100.0
    return x.rename(sig)


def zscore(x: pd.Series, win: int) -> pd.Series:
    m = x.rolling(win, min_periods=win).mean()
    s = x.rolling(win, min_periods=win).std(ddof=1)
    return (x - m) / s.replace(0.0, np.nan)


def shock_flags(flow: pd.Series, win: int, q: float) -> pd.Series:
    """Top-decile of the TRAILING window, strictly excluding today (walk-forward)."""
    thr = flow.shift(1).rolling(win, min_periods=win).quantile(q)
    return (flow >= thr) & thr.notna()


# ---------------------------------------------------------------- episodes
def episodes(x: pd.Series, z: pd.Series, enter_ok: pd.Series, h: int,
             lag: int = 1) -> pd.DataFrame:
    """Non-overlapping fade episodes. Signal at t, fill at t+lag, exit at t+lag+h."""
    idx = x.index
    n = len(idx)
    xv, zv = x.to_numpy(), z.to_numpy()
    ok = enter_ok.reindex(idx).fillna(False).to_numpy()

    rows, busy_until = [], -1
    for i in range(Z_WIN, n - lag - h):
        if i <= busy_until or not ok[i]:
            continue
        side = -np.sign(zv[i])                 # FADE the dislocation
        if side == 0:
            continue
        entry, exit_ = xv[i + lag], xv[i + lag + h]
        rows.append({
            "signal_date": idx[i], "entry_date": idx[i + lag], "exit_date": idx[i + lag + h],
            "z": zv[i], "side": side,
            "gross_bp": float(side * (exit_ - entry)),
            "abs_move_bp": float(abs(exit_ - entry)),
        })
        busy_until = i + lag + h
    return pd.DataFrame(rows)


def stats(tr: pd.DataFrame, rt: float) -> dict:
    if tr.empty:
        return {"n": 0}
    g = tr["gross_bp"].to_numpy()
    net = g - rt
    sd = g.std(ddof=1) if len(g) > 1 else np.nan
    return {
        "n": int(len(g)),
        "gross_med": float(np.median(g)), "gross_mean": float(g.mean()),
        "net_med_1x": float(np.median(net)), "net_mean_1x": float(net.mean()),
        "net_mean_0p5x": float((g - 0.5 * rt).mean()),
        "net_mean_2x": float((g - 2.0 * rt).mean()),
        "sharpe_per_trade": float(g.mean() / sd) if sd and sd > 0 else np.nan,
        "hit": float((g > 0).mean()),
        "abs_move_med": float(tr["abs_move_bp"].median()),
    }


# ------------------------------------------------------------------ selftest
def _synthetic(n_days: int, sig: str, dislocation: float, h: int, shock_every: int):
    """A par grid in which the structure dislocates on known days and reverts linearly.

    The point of building it as a PAR GRID rather than as a structure series is that
    it moves everything the code actually indexes -- the grid, the weights, the
    z-window and the fill offsets -- so a wrong-day mutant cannot return the same
    answer (V-V-17B: a self-test on frozen inputs is structurally blind).
    """
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rng = np.random.default_rng(7)
    base = pd.DataFrame(
        {f"{k}Y": 3.0 + 0.01 * np.cumsum(rng.normal(0, 0.02, n_days)) for k in BASIS},
        index=dates)
    base.index.name = "Date"
    w = weights(sig)
    belly = max(w, key=lambda k: w[k])       # push the whole dislocation into one leg
    bump = np.zeros(n_days)
    shocks = list(range(Z_WIN + 5, n_days - h - 5, shock_every))
    for s in shocks:
        for j in range(h + 1):
            if s + j < n_days:
                bump[s + j] += (dislocation / 100.0) * (1 - j / h) / w[belly]
    base[f"{belly}Y"] = base[f"{belly}Y"] + bump
    flow = pd.Series(1.0, index=dates)
    flow.iloc[shocks] = 99.0
    return base, flow, shocks


def selftest() -> dict:
    """Planted value plus TWO mutants that must each move the answer.

    The planted dislocation decays linearly from D at the shock day s to 0 at s+h,
    so with a lag-1 fill the fade captures D*(h-1)/h exactly. The mutants are chosen
    to be the two defect classes this program has actually been bitten by:
      * lag 0  -- the H13 fill-day defect (L-0051): filling at the signal's own close
                  captures the whole D instead of D*(h-1)/h;
      * h = 3   -- a wrong holding horizon, which exits while the dislocation is only
                  partly decayed. (h-1 = 4 is deliberately NOT used: the planted decay
                  is already zero by then, so that mutant is degenerate and a test
                  built on it would be blind -- the V-V-17B failure exactly.)
    """
    sig, D, h = "5-10-30", 20.0, 5
    par, flow, shocks = _synthetic(400, sig, D, h, shock_every=40)
    x = structure_series(par, sig)
    z = zscore(x, Z_WIN)
    ok = pd.Series(False, index=x.index)
    ok.iloc[shocks] = True                      # enter ONLY on planted dislocations

    def cap(h_, lag_):
        t = episodes(x, z, ok, h=h_, lag=lag_)
        return (int(len(t)), float(t["gross_bp"].median()) if len(t) else np.nan)

    n1, c1 = cap(h, 1)                          # the real convention
    n0, c0 = cap(h, 0)                          # mutant A: fill on the signal's own close
    n3, c3 = cap(3, 1)                          # mutant B: wrong horizon
    expected = D * (h - 1) / h                  # = 16.0
    exp_lag0 = D                                # = 20.0
    exp_h3 = D * (1 - 4 / h)                    # = 4.0 captured from 16.0 -> gross 12.0

    res = {
        "planted_dislocation_bp": D, "horizon": h, "n_episodes": n1,
        "captured_median_bp": c1, "expected_bp": expected,
        "mutant_lag0_captured_bp": c0, "mutant_lag0_expected_bp": exp_lag0, "n_lag0": n0,
        "mutant_h3_captured_bp": c3, "mutant_h3_expected_bp": D - exp_h3, "n_h3": n3,
        "planted_within_tol": bool(np.isfinite(c1) and abs(c1 - expected) < 1.0),
        "mutant_lag0_differs": bool(np.isfinite(c0) and abs(c0 - c1) > 1.0),
        "mutant_h3_differs": bool(np.isfinite(c3) and abs(c3 - c1) > 1.0),
    }
    print("=== SELF-TEST (planted value on a grid that MOVES; two live mutants) ===")
    print(json.dumps(res, indent=2))
    if n1 < 5:
        raise SystemExit(f"SELF-TEST FAILED: only {n1} planted episodes -- nothing measured.")
    if not res["planted_within_tol"]:
        raise SystemExit(f"SELF-TEST FAILED: planted capture {c1:.3f} != expected "
                         f"{expected:.3f} within tolerance.")
    if not (res["mutant_lag0_differs"] and res["mutant_h3_differs"]):
        raise SystemExit("SELF-TEST BLIND: a mutant returned the same answer -- the test "
                         "cannot see the class of defect it is cited for.")
    return res


# ---------------------------------------------------------------------- main
def main() -> None:
    st = selftest()

    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]

    # ---- sample: only dates on which an SDR file EXISTS ---------------------
    # Reindexing flow onto every par-grid date silently turns "no tape that day"
    # into "zero flow that day", which cannot be a shock and therefore lands in
    # the CONTROL book. That contaminates the very comparison F7 is about, so the
    # sample is the intersection, not the union.
    dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    file_dates = pd.to_datetime(dg_all["file_date"])
    lo, hi = file_dates.min(), file_dates.max()
    common = par.index.intersection(pd.DatetimeIndex(file_dates))
    print(f"\nSDR window {lo.date()} .. {hi.date()} ({len(file_dates)} files); par grid "
          f"{par.index.min().date()} .. {par.index.max().date()}")
    par_in_window = par[(par.index >= lo) & (par.index <= hi)]
    print(f"par-grid days in window {len(par_in_window)}; with an SDR file {len(common)}  "
          f"-> {len(par_in_window) - len(common)} dropped as tape-less")

    # ---- data integrity: stale/duplicated par rows (charter point 13) -------
    key_cols = [f"{k}Y" for k in BASIS]
    pw = par_in_window[key_cols]
    unchanged = (pw.diff().abs().sum(axis=1) == 0).mean()
    print(f"par-grid unchanged-day fraction on {key_cols}: {unchanged:.2%}; "
          f"duplicate index rows: {int(par_in_window.index.duplicated().sum())}")

    rows, diag, panels = [], [], {}
    for sig in uni:
        x_full = structure_series(par, sig)
        x = x_full.reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = zscore(x, Z_WIN)
        shock = shock_flags(flow, FLOW_WIN, SHOCK_Q)

        persistent = (z.abs() >= Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= Z_ENTRY)
        rt = round_trips(sig)
        panels[sig] = dict(x=x, z=z, persistent=persistent, shock=shock, rt=rt)

        diag.append({"signature": sig, "days": int(len(x)),
                     "flow_total": int(flow.sum()), "flow_med": float(flow.median()),
                     "shock_days": int(shock.sum()),
                     "entry_days": int(persistent.sum()),
                     "entry_and_shock": int((persistent & shock).sum()),
                     **rt})

        for h in HORIZONS:
            all_tr = episodes(x, z, persistent, h)
            con_tr = episodes(x, z, persistent & shock, h)
            unc_tr = episodes(x, z, persistent & ~shock, h)
            base = dict(signature=sig, n_legs=len(sig.split("-")), h=h, **rt)
            rows.append({**base, "book": "all", **stats(all_tr, rt["rt_cm2"])})
            rows.append({**base, "book": "shock", **stats(con_tr, rt["rt_cm2"])})
            rows.append({**base, "book": "noshock", **stats(unc_tr, rt["rt_cm2"])})

            # fill-lag monotonicity diagnostic (placebo spine), shock book only
            for lag in LAGS:
                t = episodes(x, z, persistent & shock, h, lag=lag)
                rows.append({**base, "book": f"shock_lag{lag}", **stats(t, rt["rt_cm2"])})

    res = pd.DataFrame(rows)
    dg = pd.DataFrame(diag)
    res.to_parquet(OUT / "f7_gate.parquet", index=False)
    dg.to_parquet(OUT / "f7_gate_diag.parquet", index=False)

    print("\n=== per-signature diagnostics ===")
    print(dg.to_string(index=False))

    # ---- STEP (i) POND: perfect-direction |move| vs round trip ----
    print("\n=== STEP (i) POND: perfect-direction |move| median vs round trip (CM-2 line) ===")
    pond = res[res["book"] == "all"].copy()
    pond["pond_over_boat"] = (pond["abs_move_med"] / pond["rt_cm2"]).round(2)
    pond["pond_over_boat_costmodel"] = (pond["abs_move_med"] / pond["rt_costmodel"]).round(2)
    print(pond[["signature", "h", "n", "abs_move_med", "rt_cm2", "pond_over_boat",
                "rt_costmodel", "pond_over_boat_costmodel"]].to_string(index=False))

    # ---- STEP (ii) INCREMENT ----
    print("\n=== STEP (ii) INCREMENT: signal-direction fade, shock vs unconditional ===")
    piv = res[res["book"].isin(["all", "shock", "noshock"])].pivot_table(
        index=["signature", "h"], columns="book",
        values=["n", "gross_med", "net_mean_1x", "sharpe_per_trade"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv["incr_gross_vs_all"] = (piv["gross_med_shock"] - piv["gross_med_all"]).round(3)
    piv["incr_gross_vs_noshock"] = (piv["gross_med_shock"] - piv["gross_med_noshock"]).round(3)
    piv = piv.reset_index()
    print(piv[["signature", "h", "n_shock", "n_noshock", "gross_med_shock",
               "gross_med_noshock", "gross_med_all", "incr_gross_vs_all",
               "incr_gross_vs_noshock", "net_mean_1x_shock"]].to_string(index=False))
    piv.to_parquet(OUT / "f7_gate_increment.parquet", index=False)

    print("\n=== HEADLINE (L-0082: the median across signatures, never the best) ===")
    for h in HORIZONS:
        s = piv[piv["h"] == h]
        print(f"  h={h:>2}bd  median incr vs all {s['incr_gross_vs_all'].median():+.3f}bp  "
              f"vs noshock {s['incr_gross_vs_noshock'].median():+.3f}bp  |  "
              f"median shock net@1x {s['net_mean_1x_shock'].median():+.3f}bp  "
              f"| signatures with positive incr: "
              f"{int((s['incr_gross_vs_noshock'] > 0).sum())}/{len(s)}")

    print("\n=== fill-lag monotonicity (shock book, median across signatures) ===")
    for h in HORIZONS:
        line = []
        for lag in LAGS:
            v = res[(res["book"] == f"shock_lag{lag}") & (res["h"] == h)]["gross_med"]
            line.append(f"t+{lag}: {v.median():+.3f}")
        print(f"  h={h:>2}bd  " + "  ".join(line))

    # ---- registered placebo: wrong-day shock, scale-matched ----------------
    # A circular shift of the shock series preserves the fire-day COUNT exactly,
    # so the placebo is scale-matched by construction (charter point 5). It gives
    # the noise scale of the increment, which is what makes "median incr ~ 0"
    # readable as a number rather than an impression.
    print("\n=== wrong-day shock placebo (circular shift, scale-matched, 200 draws) ===")
    rng = np.random.default_rng(20260809)
    placebo = {}
    for h in HORIZONS:
        real = float(piv[piv["h"] == h]["incr_gross_vs_noshock"].median())
        draws = []
        for _ in range(200):
            incs = []
            for sig, P in panels.items():
                k = int(rng.integers(20, len(P["x"]) - 20))
                sh = pd.Series(np.roll(P["shock"].to_numpy(), k), index=P["x"].index)
                a = episodes(P["x"], P["z"], P["persistent"] & sh, h)
                b = episodes(P["x"], P["z"], P["persistent"] & ~sh, h)
                if len(a) and len(b):
                    incs.append(float(a["gross_bp"].median() - b["gross_bp"].median()))
            if incs:
                draws.append(float(np.median(incs)))
        d = np.array(draws)
        p = float((d >= real).mean())
        placebo[h] = {"real": real, "null_mean": float(d.mean()), "null_sd": float(d.std(ddof=1)),
                      "null_p05": float(np.percentile(d, 5)),
                      "null_p95": float(np.percentile(d, 95)), "p_value": p,
                      "draws": len(d)}
        print(f"  h={h:>2}bd  real {real:+.3f}bp   null mean {d.mean():+.3f} "
              f"sd {d.std(ddof=1):.3f}  [p05 {np.percentile(d, 5):+.3f}, "
              f"p95 {np.percentile(d, 95):+.3f}]   p(null >= real) = {p:.3f}")

    (OUT / "f7_gate_verdict.json").write_text(json.dumps({
        "selftest": st,
        "placebo_wrong_day": placebo,
        "sample": {"start": str(lo.date()), "end": str(hi.date()),
                   "par_days_in_window": int(len(par_in_window)),
                   "days_with_sdr_file": int(len(common)),
                   "par_unchanged_day_frac": float(unchanged)},
        "universe": uni,
        "headline": {
            str(h): {
                "median_incr_vs_all": float(piv[piv["h"] == h]["incr_gross_vs_all"].median()),
                "median_incr_vs_noshock": float(piv[piv["h"] == h]["incr_gross_vs_noshock"].median()),
                "median_shock_net_1x": float(piv[piv["h"] == h]["net_mean_1x_shock"].median()),
                "n_positive_incr": int((piv[piv["h"] == h]["incr_gross_vs_noshock"] > 0).sum()),
                "n_signatures": int(len(piv[piv["h"] == h])),
            } for h in HORIZONS},
    }, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
