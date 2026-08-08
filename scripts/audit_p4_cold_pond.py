"""PROBE 4 -- cold, independent re-derivation of the F7 pond (abs_move_med, book='all').

Written from scratch. Does NOT import scripts/s3_f7_gate.py. Reads the par grid parquet
directly and rebuilds every number it needs.

Three measurements, deliberately separated so the difference between them is legible:

  (A) UNCONDITIONAL pond -- median |x(t+h) - x(t)| over NON-OVERLAPPING h-day blocks
      across the whole 2023-12-01..2026-07-21 window. This is the pond a strategy that
      trades on any day actually sees.
  (B) SDR-SUBSET unconditional pond -- same, but on the 643-row index the gate actually
      indexes (par-grid days that have a Part 43 file). Isolates the calendar-dilation
      effect of dropping 45 rows out of the middle of the series.
  (C) ENTRY-DAY pond -- my own independent reimplementation of the gate's episode
      constructor (|z|>=1 persistent, lag-1 fill, greedy non-overlap). This is what the
      committed f7_gate.parquet 'abs_move_med' claims to be, so (C) vs committed is the
      reproduction test, and (C) vs (A) is the entry-filter inflation.
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
LO, HI = pd.Timestamp("2023-12-01"), pd.Timestamp("2026-07-21")
RT_CM2 = {2: 1.8, 3: 3.6}   # 2 * sum|w| * 0.45


def level_bp(par: pd.DataFrame, sig: str) -> pd.Series:
    """Structure level in bp, built independently of the gate's weights()."""
    t = [int(v) for v in sig.split("-")]
    if len(t) == 2:
        a, b = t
        s = (par[f"{b}Y"] - par[f"{a}Y"]) * 100.0
    else:
        a, b, c = t
        s = (2.0 * par[f"{b}Y"] - par[f"{a}Y"] - par[f"{c}Y"]) * 100.0
    return s.dropna().rename(sig)


def nonoverlap_abs_moves(x: pd.Series, h: int, offset: int = 0) -> np.ndarray:
    """|x[i+h] - x[i]| on disjoint blocks starting at `offset`, stepping by h."""
    v = x.to_numpy()
    i = np.arange(offset, len(v) - h, h)
    return np.abs(v[i + h] - v[i])


def zscore(x: pd.Series, win: int = 60) -> pd.Series:
    m = x.rolling(win, min_periods=win).mean()
    s = x.rolling(win, min_periods=win).std(ddof=1)
    return (x - m) / s.replace(0.0, np.nan)


def entry_day_abs_moves(x: pd.Series, h: int, lag: int = 1, z_entry: float = 1.0,
                        warm: int = 60) -> np.ndarray:
    """Independent reimplementation of the gate's episode constructor.

    Greedy left-to-right, non-overlapping, entry gated on a persistent |z|>=1 with the
    same sign on two consecutive closes. Signal at i, fill at i+lag, exit at i+lag+h.
    """
    z = zscore(x, warm)
    zv, xv = z.to_numpy(), x.to_numpy()
    sgn = np.sign(zv)
    ok = np.zeros(len(xv), dtype=bool)
    ok[1:] = (np.abs(zv[1:]) >= z_entry) & (sgn[1:] == sgn[:-1]) & (np.abs(zv[:-1]) >= z_entry)
    ok = ok & np.isfinite(zv)

    moves, busy = [], -1
    for i in range(warm, len(xv) - lag - h):
        if i <= busy or not ok[i] or sgn[i] == 0:
            continue
        moves.append(abs(xv[i + lag + h] - xv[i + lag]))
        busy = i + lag + h
    return np.array(moves)


def main() -> None:
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    par = par.sort_index()
    win = par[(par.index >= LO) & (par.index <= HI)]

    dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    fd = pd.DatetimeIndex(pd.to_datetime(dg["file_date"]).unique()).sort_values()
    common = win.index.intersection(fd)

    # -- calendar sanity: is the par index every business day in the window? ----
    bd = pd.bdate_range(LO, HI)
    print(f"window {LO.date()}..{HI.date()}: bdate_range {len(bd)}, par rows {len(win)}, "
          f"par rows with an SDR file {len(common)}")
    missing = bd.difference(win.index)
    print(f"  business days absent from the par grid: {len(missing)}  "
          f"(first few {[str(d.date()) for d in missing[:6]]})")
    gaps = pd.Series(common).diff().dt.days.dropna()
    print(f"  SDR-subset step in CALENDAR days: mean {gaps.mean():.3f}  "
          f"vs full par index {pd.Series(win.index).diff().dt.days.dropna().mean():.3f}")
    print(f"  => 21 SDR-subset rows span {21 * gaps.mean():.1f} calendar days vs "
          f"{21 * pd.Series(win.index).diff().dt.days.dropna().mean():.1f} for 21 par rows")

    gate = pd.read_parquet(OUT / "f7_gate.parquet")
    gate_all = gate[gate["book"] == "all"].set_index(["signature", "h"])

    rows = []
    for sig in ALL_SIGS:
        x_full = level_bp(par, sig)
        x_win = x_full.reindex(win.index).dropna()             # (A) all par days
        x_sdr = x_full.reindex(common).dropna()                # (B)/(C) gate's index
        nlegs = len(sig.split("-"))
        rt = RT_CM2[nlegs]
        for h in HORIZONS:
            # (A) unconditional, all par days, averaged over every phase offset so the
            #     answer does not depend on where the first block happens to start
            a_off = [float(np.median(nonoverlap_abs_moves(x_win, h, o))) for o in range(h)]
            a_med = float(np.median(a_off))
            a_n = len(nonoverlap_abs_moves(x_win, h, 0))

            # (B) unconditional on the SDR subset
            b_off = [float(np.median(nonoverlap_abs_moves(x_sdr, h, o))) for o in range(h)]
            b_med = float(np.median(b_off))

            # (C) entry-day, gate's own constructor, reimplemented
            m = entry_day_abs_moves(x_sdr, h)
            c_med = float(np.median(m)) if len(m) else np.nan

            committed = gate_all.loc[(sig, h)]
            rows.append({
                "sig": sig, "legs": nlegs, "h": h, "rt_cm2": rt,
                "committed_abs_move_med": float(committed["abs_move_med"]),
                "committed_n": int(committed["n"]),
                "cold_entry_med": c_med, "cold_entry_n": int(len(m)),
                "uncond_all_par": a_med, "uncond_all_par_n": a_n,
                "uncond_sdr_sub": b_med,
                "pond_committed": float(committed["abs_move_med"]) / rt,
                "pond_uncond": a_med / rt,
                "entry_inflation": c_med / a_med if a_med else np.nan,
                "match": abs(c_med - float(committed["abs_move_med"])),
            })

    r = pd.DataFrame(rows)
    print("\n=== REPRODUCTION: my entry-day constructor vs committed abs_move_med ===")
    print(r[["sig", "legs", "h", "committed_abs_move_med", "committed_n",
             "cold_entry_med", "cold_entry_n", "match"]].to_string(index=False))
    print(f"\nmax abs difference cold-vs-committed: {r['match'].max():.6f}  "
          f"(n mismatch rows: {(r['committed_n'] != r['cold_entry_n']).sum()})")

    print("\n=== POND: conditional (committed) vs UNCONDITIONAL, in round trips ===")
    print(r[["sig", "legs", "h", "rt_cm2", "committed_abs_move_med", "uncond_sdr_sub",
             "uncond_all_par", "uncond_all_par_n", "pond_committed", "pond_uncond",
             "entry_inflation"]].round(3).to_string(index=False))

    print("\n=== SPREADS @ h=21, the only thing that passed ===")
    s = r[(r["sig"].isin(SPREADS)) & (r["h"] == 21)]
    print(s[["sig", "committed_abs_move_med", "uncond_all_par", "pond_committed",
             "pond_uncond", "entry_inflation"]].round(3).to_string(index=False))
    print(f"  committed pond/boat range {s['pond_committed'].min():.2f}-"
          f"{s['pond_committed'].max():.2f}x  |  unconditional "
          f"{s['pond_uncond'].min():.2f}-{s['pond_uncond'].max():.2f}x")
    print(f"  median entry-filter inflation across the 5 spreads @h=21: "
          f"{s['entry_inflation'].median():.3f}x")

    r.to_parquet(OUT / "audit_p4_cold_pond.parquet", index=False)


if __name__ == "__main__":
    main()
