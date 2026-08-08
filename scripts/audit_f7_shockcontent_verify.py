"""VERIFY-A-CLAIM probe: "the POND is measured on 18-22 non-overlapping episodes,
and on ALL entry days 2-5-10 @h=21 flips 0.79x -> 1.08x" (probe shock-content).

Written independently of s3_f7_gate.py (nothing imported from it) but rebuilding the
SAME panel, so step 1 is a tie-out: if my episode reconstruction does not reproduce
the committed f7_gate.parquet book=='all' abs_move_med cell-by-cell, MY probe is the
broken thing and no downstream number is admissible.

Then three questions, in the order that decides materiality:
  A. does the 0.79x -> 1.08x flip reproduce, and by how much do the other cells move?
  B. does the pond FILTER anything, i.e. is step (ii) computed only for pond-passers?
  C. does the INCREMENT -- the number that actually killed F7 -- move at all when the
     same overlapping all-entry-day construction is used instead of episodes()?

Writes nothing to any committed file.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 500)

OUT = pathlib.Path(r"C:/Users/chris/clee/ARBS-rv/notebooks/data/citivelo_rv")

HORIZONS = [1, 5, 21]
Z_WIN = FLOW_WIN = 60
Z_ENTRY = 1.0
SHOCK_Q = 0.90
CM2_HALF = 0.45


def w_of(sig):
    t = [int(v) for v in sig.split("-")]
    return {t[0]: -1.0, t[1]: 1.0} if len(t) == 2 else {t[0]: -1.0, t[1]: 2.0, t[2]: -1.0}


def rt_cm2(sig):
    return 2.0 * sum(abs(v) for v in w_of(sig).values()) * CM2_HALF


def level_bp(par, sig):
    w = w_of(sig)
    sub = par[[f"{k}Y" for k in w]].dropna()
    return (sum(v * sub[f"{k}Y"] for k, v in w.items()) * 100.0).rename(sig)


def zscore(x, win=Z_WIN):
    m = x.rolling(win, min_periods=win).mean()
    s = x.rolling(win, min_periods=win).std(ddof=1)
    return (x - m) / s.replace(0.0, np.nan)


def episodes_moves(x, z, ok, h, lag=1):
    """Non-overlapping, as the gate does. Returns (abs_move array, gross array)."""
    xv, zv = x.to_numpy(), z.to_numpy()
    okv = ok.reindex(x.index).fillna(False).to_numpy()
    am, gr, busy = [], [], -1
    for i in range(Z_WIN, len(xv) - lag - h):
        if i <= busy or not okv[i]:
            continue
        side = -np.sign(zv[i])
        if side == 0:
            continue
        e, xo = xv[i + lag], xv[i + lag + h]
        am.append(abs(xo - e))
        gr.append(float(side * (xo - e)))
        busy = i + lag + h
    return np.array(am), np.array(gr)


def allday_moves(x, z, ok, h, lag=1):
    """EVERY qualifying entry day, overlapping. Same range guard as the gate."""
    xv, zv = x.to_numpy(), z.to_numpy()
    okv = ok.reindex(x.index).fillna(False).to_numpy()
    am, gr = [], []
    for i in range(Z_WIN, len(xv) - lag - h):
        if not okv[i]:
            continue
        side = -np.sign(zv[i])
        if side == 0:
            continue
        e, xo = xv[i + lag], xv[i + lag + h]
        am.append(abs(xo - e))
        gr.append(float(side * (xo - e)))
    return np.array(am), np.array(gr)


def main():
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet").sort_index()
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]

    dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    fdates = pd.to_datetime(dg_all["file_date"])
    common = par.index.intersection(pd.DatetimeIndex(fdates))

    gate = pd.read_parquet(OUT / "f7_gate.parquet")
    g_all = gate[gate["book"] == "all"].set_index(["signature", "h"])
    g_sh = gate[gate["book"] == "shock"].set_index(["signature", "h"])
    g_ns = gate[gate["book"] == "noshock"].set_index(["signature", "h"])

    panels = {}
    for sig in uni:
        x = level_bp(par, sig).reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = zscore(x)
        thr = flow.shift(1).rolling(FLOW_WIN, min_periods=FLOW_WIN).quantile(SHOCK_Q)
        shock = (flow >= thr) & thr.notna()
        persistent = ((z.abs() >= Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                      & (z.shift(1).abs() >= Z_ENTRY))
        panels[sig] = (x, z, persistent, shock)

    # ---------------- STEP 0: TIE-OUT (validate the probe before trusting it) ----
    print("=== 0. TIE-OUT of my episode reconstruction vs committed f7_gate.parquet ===")
    bad = 0
    for sig in uni:
        x, z, pers, shock = panels[sig]
        for h in HORIZONS:
            am, gr = episodes_moves(x, z, pers, h)
            cn, cm = int(g_all.loc[(sig, h), "n"]), float(g_all.loc[(sig, h), "abs_move_med"])
            cg = float(g_all.loc[(sig, h), "gross_med"])
            ok = (len(am) == cn and abs(np.median(am) - cm) < 1e-9
                  and abs(np.median(gr) - cg) < 1e-9)
            bad += (not ok)
            if not ok:
                print(f"  MISMATCH {sig} h={h}: mine n={len(am)} med={np.median(am):.6f} "
                      f"gross={np.median(gr):.6f} | committed n={cn} med={cm:.6f} gross={cg:.6f}")
    print(f"  cells checked {len(uni)*len(HORIZONS)}   mismatches {bad}"
          f"   -> {'PROBE VALID' if bad == 0 else 'PROBE BROKEN, STOP'}")
    if bad:
        raise SystemExit("probe does not reproduce the committed gate; nothing below is admissible")

    # ---------------- A: pond, episode vs all-day --------------------------------
    print("\n=== A. POND: episode (committed) vs ALL entry days ===")
    rows = []
    for sig in uni:
        x, z, pers, shock = panels[sig]
        rt = rt_cm2(sig)
        for h in HORIZONS:
            am_e, _ = episodes_moves(x, z, pers, h)
            am_a, _ = allday_moves(x, z, pers, h)
            rows.append({"sig": sig, "legs": len(sig.split("-")), "h": h, "rt": rt,
                         "n_epi": len(am_e), "n_all": len(am_a),
                         "med_epi": float(np.median(am_e)) if len(am_e) else np.nan,
                         "med_all": float(np.median(am_a)) if len(am_a) else np.nan})
    p = pd.DataFrame(rows)
    p["pond_epi"] = p["med_epi"] / p["rt"]
    p["pond_all"] = p["med_all"] / p["rt"]
    p["pct_understate"] = 100.0 * (p["med_epi"] / p["med_all"] - 1.0)
    print(p.round(3).to_string(index=False))
    f21 = p[(p["legs"] == 3) & (p["h"] == 21)]
    print("\n  FLIES @h=21 (the cited cells):")
    for _, r in f21.iterrows():
        print(f"    {r['sig']:>9}  episode {r['pond_epi']:.2f}x (n={int(r['n_epi'])})   "
              f"all-day {r['pond_all']:.2f}x (n={int(r['n_all'])})")
    print(f"  median episode-vs-all understatement @h=21 over 10 sigs: "
          f"{p[p['h']==21]['pct_understate'].median():+.1f}%")
    print(f"  FLY cells (15) with all-day pond >= 1.0x: "
          f"{int((p[p['legs']==3]['pond_all'] >= 1.0).sum())}/15   "
          f"max fly all-day pond {p[p['legs']==3]['pond_all'].max():.2f}x")

    # ---------------- B: does the pond gate anything? ----------------------------
    print("\n=== B. DOES THE POND FILTER STEP (ii)? ===")
    inc = pd.read_parquet(OUT / "f7_gate_increment.parquet")
    print(f"  f7_gate_increment.parquet rows {len(inc)}  distinct signatures "
          f"{inc['signature'].nunique()}  horizons {sorted(inc['h'].unique())}")
    pf = p[(p["legs"] == 3)]
    failed = sorted(set(pf[pf["pond_epi"] < 1.0]["sig"]))
    print(f"  signatures whose committed pond FAILED at every h: {failed}")
    present = sorted(set(inc[inc["signature"].isin(failed)]["signature"]))
    print(f"  ...of which still measured in step (ii): {present}")
    print("  => the pond is descriptive; every signature is carried into the increment.")

    # ---------------- C: the increment on the all-day construction ---------------
    print("\n=== C. INCREMENT (the killing number) recomputed on ALL entry days ===")
    out = []
    for sig in uni:
        x, z, pers, shock = panels[sig]
        rt = rt_cm2(sig)
        for h in HORIZONS:
            _, g_sh_e = episodes_moves(x, z, pers & shock, h)
            _, g_ns_e = episodes_moves(x, z, pers & ~shock, h)
            _, g_sh_a = allday_moves(x, z, pers & shock, h)
            _, g_ns_a = allday_moves(x, z, pers & ~shock, h)
            out.append({
                "sig": sig, "h": h, "rt": rt,
                "n_sh_e": len(g_sh_e), "n_ns_e": len(g_ns_e),
                "n_sh_a": len(g_sh_a), "n_ns_a": len(g_ns_a),
                "incr_epi": (float(np.median(g_sh_e) - np.median(g_ns_e))
                             if len(g_sh_e) and len(g_ns_e) else np.nan),
                "incr_all": (float(np.median(g_sh_a) - np.median(g_ns_a))
                             if len(g_sh_a) and len(g_ns_a) else np.nan),
                "net_sh_epi": (float(np.mean(g_sh_e) - rt) if len(g_sh_e) else np.nan),
                "net_sh_all": (float(np.mean(g_sh_a) - rt) if len(g_sh_a) else np.nan),
            })
    c = pd.DataFrame(out)
    print(c.round(3).to_string(index=False))
    print("\n  MEDIAN ACROSS THE 10 SIGNATURES (the registered headline statistic):")
    for h in HORIZONS:
        s = c[c["h"] == h]
        print(f"    h={h:>2}  incr episode {s['incr_epi'].median():+.3f}bp   "
              f"incr all-day {s['incr_all'].median():+.3f}bp   |  "
              f"shock net@1x episode {s['net_sh_epi'].median():+.3f}bp   "
              f"all-day {s['net_sh_all'].median():+.3f}bp   |  "
              f"sigs with positive all-day incr {int((s['incr_all'] > 0).sum())}/10")

    # ---------------- D: could the ONE flipped cell be alive on its own? ---------
    print("\n=== D. 2-5-10 @h=21 in full, on BOTH constructions ===")
    x, z, pers, shock = panels["2-5-10"]
    rt = rt_cm2("2-5-10")
    for name, fn in (("episode", episodes_moves), ("all-day", allday_moves)):
        am, gr = fn(x, z, pers, 21)
        am_s, gr_s = fn(x, z, pers & shock, 21)
        print(f"  {name:>8}: n={len(am):4d}  perfect-dir |move| med {np.median(am):6.3f}bp "
              f"({np.median(am)/rt:4.2f}x rt={rt}bp)   SIGNAL-dir gross med "
              f"{np.median(gr):+6.3f}bp  net@1x {np.median(gr)-rt:+6.3f}bp   "
              f"| shock book n={len(gr_s)} gross med "
              f"{(np.median(gr_s) if len(gr_s) else float('nan')):+6.3f}bp")
    print("\n  (the pond is the PERFECT-direction oracle: it knows the sign of the move in "
          "advance. The realised rule trades the SIGNAL direction, column 'gross med'.)")


if __name__ == "__main__":
    main()
