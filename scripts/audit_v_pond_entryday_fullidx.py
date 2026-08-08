"""VERIFY-A-CLAIM probe: does the SDR-subset index materially change STEP (i)?

The claim under test says `x = x_full.reindex(common)` (gate:254) makes h=21 span
~31.5 calendar days instead of ~29.4, and that this "inflates the pond ~3-4%".

The prior probe (audit_p4_cold_pond.py) compared UNCONDITIONAL block ponds. The
committed pond in f7_gate.parquet is the ENTRY-DAY CONDITIONAL pond, so this probe
re-runs the gate's own episode constructor on BOTH indices and compares like with
like, then asks the only question that matters: does any pond/round-trip verdict
cross 1.0x?

Writes nothing to any committed file.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 500)

OUT = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "citivelo_rv"

SPREADS = ["10-30", "2-10", "2-30", "5-10", "5-30"]
FLIES = ["10-15-30", "10-20-30", "2-5-10", "5-10-30", "5-7-10"]
ALL_SIGS = SPREADS + FLIES
HORIZONS = [1, 5, 21]
RT_CM2 = {2: 1.8, 3: 3.6}
WARM = 60


def level_bp(par: pd.DataFrame, sig: str) -> pd.Series:
    t = [int(v) for v in sig.split("-")]
    if len(t) == 2:
        a, b = t
        s = (par[f"{b}Y"] - par[f"{a}Y"]) * 100.0
    else:
        a, b, c = t
        s = (2.0 * par[f"{b}Y"] - par[f"{a}Y"] - par[f"{c}Y"]) * 100.0
    return s.dropna().rename(sig)


def zscore(x: pd.Series, win: int = WARM) -> pd.Series:
    m = x.rolling(win, min_periods=win).mean()
    s = x.rolling(win, min_periods=win).std(ddof=1)
    return (x - m) / s.replace(0.0, np.nan)


def entry_day_abs_moves(x: pd.Series, h: int, lag: int = 1, z_entry: float = 1.0):
    """The gate's constructor, reimplemented (verified bit-identical in probe 4)."""
    z = zscore(x, WARM)
    zv, xv = z.to_numpy(), x.to_numpy()
    sgn = np.sign(zv)
    ok = np.zeros(len(xv), dtype=bool)
    ok[1:] = (np.abs(zv[1:]) >= z_entry) & (sgn[1:] == sgn[:-1]) & (np.abs(zv[:-1]) >= z_entry)
    ok = ok & np.isfinite(zv)
    moves, busy = [], -1
    for i in range(WARM, len(xv) - lag - h):
        if i <= busy or not ok[i] or sgn[i] == 0:
            continue
        moves.append(abs(xv[i + lag + h] - xv[i + lag]))
        busy = i + lag + h
    return np.array(moves)


def nonoverlap_abs_moves(x: pd.Series, h: int, offset: int = 0) -> np.ndarray:
    v = x.to_numpy()
    i = np.arange(offset, len(v) - h, h)
    return np.abs(v[i + h] - v[i])


def main() -> None:
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet").sort_index()
    par.index = pd.to_datetime(par.index)
    dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    fd = pd.DatetimeIndex(pd.to_datetime(dg["file_date"]).unique()).sort_values()
    lo, hi = fd.min(), fd.max()
    win = par[(par.index >= lo) & (par.index <= hi)]
    common = win.index.intersection(fd)
    bd = pd.bdate_range(lo, hi)

    print("=== A. CALENDAR FACT (does the dilation reproduce?) ===")
    print(f"window {lo.date()}..{hi.date()}  bdate_range {len(bd)}  par rows {len(win)}  "
          f"par rows with an SDR file {len(common)}  dropped {len(win) - len(common)}")
    st_sub = pd.Series(common).diff().dt.days.dropna()
    st_full = pd.Series(win.index).diff().dt.days.dropna()
    print(f"mean calendar step: subset {st_sub.mean():.3f}  full-par {st_full.mean():.3f}  "
          f"ratio {st_sub.mean() / st_full.mean():.4f}")
    # honest span: the ACTUAL calendar span of a 21-row window, not 21 x mean step
    for name, idx in (("subset", common), ("full-par", win.index)):
        sp = np.array([(idx[i + 21] - idx[i]).days for i in range(len(idx) - 21)])
        print(f"  true 21-row calendar span on {name:>8}: mean {sp.mean():.2f}d  "
              f"median {np.median(sp):.1f}d")

    print("\n=== B. UNCONDITIONAL pond, PAIRED BY SIGNATURE (the claim's own metric) ===")
    rows = []
    for sig in ALL_SIGS:
        xf = level_bp(par, sig)
        x_full = xf.reindex(win.index).dropna()
        x_sub = xf.reindex(common).dropna()
        for h in HORIZONS:
            b = float(np.median([np.median(nonoverlap_abs_moves(x_sub, h, o)) for o in range(h)]))
            a = float(np.median([np.median(nonoverlap_abs_moves(x_full, h, o)) for o in range(h)]))
            rows.append({"sig": sig, "h": h, "uncond_subset": b, "uncond_fullpar": a,
                         "pct_subset_vs_full": 100.0 * (b / a - 1.0),
                         "n_blocks_sub": len(nonoverlap_abs_moves(x_sub, h, 0)),
                         "n_blocks_full": len(nonoverlap_abs_moves(x_full, h, 0))})
    u = pd.DataFrame(rows)
    print(u[u["h"] == 21].round(3).to_string(index=False))
    s21 = u[(u["h"] == 21) & (u["sig"].isin(SPREADS))]
    print(f"\n  h=21 spreads: median subset-vs-full change {s21['pct_subset_vs_full'].median():+.2f}%"
          f"   n signatures INFLATED by the subset: "
          f"{int((s21['pct_subset_vs_full'] > 0).sum())}/5")
    print(f"  all 10 sigs @h=21: median {u[u['h']==21]['pct_subset_vs_full'].median():+.2f}%  "
          f"inflated {int((u[u['h']==21]['pct_subset_vs_full']>0).sum())}/10")

    # bootstrap: is a +-3% difference distinguishable from median sampling noise?
    rng = np.random.default_rng(11)
    print("\n  bootstrap of the h=21 subset median (2000 resamples of the block set):")
    for sig in SPREADS:
        xf = level_bp(par, sig)
        m = nonoverlap_abs_moves(xf.reindex(common).dropna(), 21, 0)
        bs = np.array([np.median(rng.choice(m, len(m), replace=True)) for _ in range(2000)])
        print(f"    {sig:>8}  point {np.median(m):6.3f}  boot sd {bs.std(ddof=1):5.3f} "
              f"({100*bs.std(ddof=1)/np.median(m):5.1f}% of level)  n_blocks {len(m)}")

    print("\n=== C. THE VERDICT TEST: gate's own ENTRY-DAY pond on both indices ===")
    gate = pd.read_parquet(OUT / "f7_gate.parquet")
    gate_all = gate[gate["book"] == "all"].set_index(["signature", "h"])
    rows = []
    for sig in ALL_SIGS:
        xf = level_bp(par, sig)
        x_full = xf.reindex(win.index).dropna()
        x_sub = xf.reindex(common).dropna()
        rt = RT_CM2[len(sig.split("-"))]
        for h in HORIZONS:
            ms = entry_day_abs_moves(x_sub, h)
            mf = entry_day_abs_moves(x_full, h)
            rows.append({
                "sig": sig, "legs": len(sig.split("-")), "h": h, "rt": rt,
                "committed": float(gate_all.loc[(sig, h), "abs_move_med"]),
                "pond_subset": float(np.median(ms)) / rt if len(ms) else np.nan,
                "pond_fullpar": float(np.median(mf)) / rt if len(mf) else np.nan,
                "n_sub": len(ms), "n_full": len(mf),
            })
    p = pd.DataFrame(rows)
    p["pond_committed"] = p["committed"] / p["rt"]
    p["delta_pond"] = p["pond_fullpar"] - p["pond_subset"]
    print(p[["sig", "legs", "h", "rt", "pond_committed", "pond_subset", "pond_fullpar",
             "delta_pond", "n_sub", "n_full"]].round(3).to_string(index=False))

    fl = p[p["legs"] == 3]
    sp21 = p[(p["legs"] == 2) & (p["h"] == 21)]
    print(f"\n  FLIES (all horizons): max pond on subset {fl['pond_subset'].max():.3f}x, "
          f"on full-par index {fl['pond_fullpar'].max():.3f}x  -- threshold 1.0x  "
          f"=> crossings: {int((fl['pond_fullpar'] >= 1.0).sum())}")
    print(f"  SPREADS @h=21: pond range subset "
          f"{sp21['pond_subset'].min():.2f}-{sp21['pond_subset'].max():.2f}x, full-par "
          f"{sp21['pond_fullpar'].min():.2f}-{sp21['pond_fullpar'].max():.2f}x  "
          f"=> any dropping below 1.0x: {int((sp21['pond_fullpar'] < 1.0).sum())}")

    print("\n=== D. how far the pond would have to move to overturn the DEATH ===")
    vd = pd.read_json(OUT / "f7_gate_verdict.json", typ="series")
    print("committed headline:", vd["headline"])
    print("the death is STEP (ii): increment must clear a 1.8bp (spread) / 3.6bp (fly) "
          "round trip; a pond that is 7% larger moves nothing in STEP (ii) because the "
          "shock and no-shock books are built on the SAME index.")


if __name__ == "__main__":
    main()
