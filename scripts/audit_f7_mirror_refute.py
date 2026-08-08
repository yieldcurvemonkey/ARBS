"""AUDIT PROBE (read-only): verify the 'no momentum book' claim against F7's gate.

Rebuilds the gate panel exactly as scripts/s3_f7_gate.py::main does, then runs the
episode constructor twice -- side_mult = -1 (the committed FADE) and side_mult = +1
(the MOMENTUM mirror that L-0082 promised and the gate never computed).

Writes nothing into the committed artifacts. Run:
  C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_mirror_refute.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

import s3_f7_gate as G  # noqa: E402

OUT = G.OUT


def episodes_sm(x, z, enter_ok, h, lag=1, side_mult=-1.0):
    """Byte-for-byte G.episodes with the ONE hardcoded sign made a parameter."""
    idx = x.index
    n = len(idx)
    xv, zv = x.to_numpy(), z.to_numpy()
    ok = enter_ok.reindex(idx).fillna(False).to_numpy()
    rows, busy_until = [], -1
    for i in range(G.Z_WIN, n - lag - h):
        if i <= busy_until or not ok[i]:
            continue
        side = side_mult * np.sign(zv[i])
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


def build_panels():
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
    dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    file_dates = pd.to_datetime(dg_all["file_date"])
    common = par.index.intersection(pd.DatetimeIndex(file_dates))

    panels = {}
    for sig in uni:
        x = G.structure_series(par, sig).reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = G.zscore(x, G.Z_WIN)
        shock = G.shock_flags(flow, G.FLOW_WIN, G.SHOCK_Q)
        persistent = (z.abs() >= G.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= G.Z_ENTRY)
        panels[sig] = dict(x=x, z=z, persistent=persistent, shock=shock,
                           rt=G.round_trips(sig))
    return uni, panels


def run(panels, uni, side_mult):
    """Returns (per-cell frame, headline dict) for one mirror."""
    rows = []
    for sig in uni:
        P = panels[sig]
        for h in G.HORIZONS:
            a = episodes_sm(P["x"], P["z"], P["persistent"] & P["shock"], h,
                            side_mult=side_mult)
            b = episodes_sm(P["x"], P["z"], P["persistent"] & ~P["shock"], h,
                            side_mult=side_mult)
            c = episodes_sm(P["x"], P["z"], P["persistent"], h, side_mult=side_mult)
            rt = P["rt"]["rt_cm2"]
            rows.append({
                "signature": sig, "h": h, "rt_cm2": rt,
                "n_shock": len(a), "n_noshock": len(b), "n_all": len(c),
                "gm_shock": float(a["gross_bp"].median()) if len(a) else np.nan,
                "gm_noshock": float(b["gross_bp"].median()) if len(b) else np.nan,
                "gm_all": float(c["gross_bp"].median()) if len(c) else np.nan,
                "gmean_shock": float(a["gross_bp"].mean()) if len(a) else np.nan,
                "net_mean_1x_shock": float(a["gross_bp"].mean() - rt) if len(a) else np.nan,
            })
    f = pd.DataFrame(rows)
    f["incr_vs_noshock"] = (f["gm_shock"] - f["gm_noshock"]).round(3)
    f["incr_vs_all"] = (f["gm_shock"] - f["gm_all"]).round(3)
    head = {}
    for h in G.HORIZONS:
        s = f[f["h"] == h]
        head[h] = {
            "median_incr_vs_noshock": float(s["incr_vs_noshock"].median()),
            "median_incr_vs_all": float(s["incr_vs_all"].median()),
            "median_shock_net_1x": float(s["net_mean_1x_shock"].median()),
            "n_positive_incr": int((s["incr_vs_noshock"] > 0).sum()),
            "n_sig_gross_med_shock_negative": int((s["gm_shock"] < 0).sum()),
            "n_sig_gross_med_all_negative": int((s["gm_all"] < 0).sum()),
            "n_shock_gross_med_beats_rt": int((s["gm_shock"] > s["rt_cm2"]).sum()),
            "n_shock_net_mean_positive": int((s["net_mean_1x_shock"] > 0).sum()),
        }
    return f, head


def main():
    uni, panels = build_panels()
    print("universe:", uni)

    fade, h_fade = run(panels, uni, -1.0)
    mom, h_mom = run(panels, uni, +1.0)

    print("\n=== FADE (side_mult=-1) -- must reproduce the committed headline ===")
    print(json.dumps({str(k): v for k, v in h_fade.items()}, indent=2))
    print("\n=== MOMENTUM (side_mult=+1) -- the mirror L-0082 promised ===")
    print(json.dumps({str(k): v for k, v in h_mom.items()}, indent=2))

    # committed verdict tie-out
    cv = json.loads((OUT / "f7_gate_verdict.json").read_text())["headline"]
    print("\n=== tie-out vs committed f7_gate_verdict.json ===")
    for h in G.HORIZONS:
        c = cv[str(h)]
        print(f"  h={h:>2}  committed incr_vs_noshock {c['median_incr_vs_noshock']:+.6f}  "
              f"reproduced {h_fade[h]['median_incr_vs_noshock']:+.6f}  "
              f"match={np.isclose(c['median_incr_vs_noshock'], h_fade[h]['median_incr_vs_noshock'])}"
              f" | committed net@1x {c['median_shock_net_1x']:+.6f} reproduced "
              f"{h_fade[h]['median_shock_net_1x']:+.6f} "
              f"match={np.isclose(c['median_shock_net_1x'], h_fade[h]['median_shock_net_1x'])}")

    # exact per-trade mirror test on all 30 signature-horizon cells, all three books
    print("\n=== exact per-trade mirror test (30 cells x 3 books) ===")
    bad, cells = [], 0
    for sig in uni:
        P = panels[sig]
        for h in G.HORIZONS:
            for name, mask in (("shock", P["persistent"] & P["shock"]),
                               ("noshock", P["persistent"] & ~P["shock"]),
                               ("all", P["persistent"])):
                a = episodes_sm(P["x"], P["z"], mask, h, side_mult=-1.0)
                b = episodes_sm(P["x"], P["z"], mask, h, side_mult=+1.0)
                cells += 1
                same_dates = (len(a) == len(b)) and (list(a.get("signal_date", [])) ==
                                                     list(b.get("signal_date", [])))
                neg = len(a) == len(b) and (len(a) == 0 or np.allclose(
                    a["gross_bp"].to_numpy(), -b["gross_bp"].to_numpy()))
                if not (same_dates and neg):
                    bad.append((sig, h, name, len(a), len(b)))
    print(f"  cells checked {cells}; mismatches {len(bad)} -> {bad[:5]}")

    # does the momentum mirror clear the boat?
    print("\n=== MOMENTUM shock book vs round trip, per signature ===")
    pd.set_option("display.width", 220)
    print(mom[["signature", "h", "rt_cm2", "n_shock", "gm_shock", "gmean_shock",
               "net_mean_1x_shock", "incr_vs_noshock"]].sort_values(["h", "signature"])
          .to_string(index=False))

    print("\n=== VERDICT ARITHMETIC ===")
    for h in G.HORIZONS:
        rtlo, rthi = 1.8, 3.6
        m = h_mom[h]["median_incr_vs_noshock"]
        print(f"  h={h:>2}  momentum median increment {m:+.3f}bp vs round trip "
              f"{rtlo}-{rthi}bp  -> {rthi/abs(m) if m else float('inf'):.1f}x SHORT of the "
              f"3-leg boat, {rtlo/abs(m) if m else float('inf'):.1f}x short of the 2-leg boat; "
              f"momentum median shock net@1x {h_mom[h]['median_shock_net_1x']:+.3f}bp")

    fade.to_csv(_REPO / "scripts" / "audit_f7_mirror_fade.csv", index=False)
    mom.to_csv(_REPO / "scripts" / "audit_f7_mirror_mom.csv", index=False)


if __name__ == "__main__":
    main()
