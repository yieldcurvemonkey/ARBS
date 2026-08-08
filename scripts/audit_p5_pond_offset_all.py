"""AUDIT probe: independent phase-offset sweep of the h=21 pond for ALL 10 signatures.

Written from scratch (does not import s3_f7_gate or audit_p4_offset_spread). Two jobs:
  1. independently reproduce the claimed spread sweep,
  2. close the blind spot -- the claim only swept the 5 SPREADS (the side that
     PASSED the pond). The verdict-relevant side is the 5 FLIES (all < 0.79x).
     If the same phase looseness lets a fly's luckiest offset cross 1.0x, that is
     the only way this claim could touch a verdict, so measure it.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib

import numpy as np
import pandas as pd

OUT = pathlib.Path(r"C:/Users/chris/clee/ARBS-rv/notebooks/data/citivelo_rv")
SPREADS = ["10-30", "2-10", "2-30", "5-10", "5-30"]
FLIES = ["10-15-30", "10-20-30", "2-5-10", "5-10-30", "5-7-10"]
LO, HI = pd.Timestamp("2023-12-01"), pd.Timestamp("2026-07-21")
H = 21


def lvl(par: pd.DataFrame, sig: str) -> np.ndarray:
    t = [int(v) for v in sig.split("-")]
    if len(t) == 2:
        s = par[f"{t[1]}Y"] - par[f"{t[0]}Y"]
    else:
        s = 2.0 * par[f"{t[1]}Y"] - par[f"{t[0]}Y"] - par[f"{t[2]}Y"]
    return (s * 100.0).dropna().to_numpy()


def main() -> None:
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    par = par.sort_index()
    win = par[(par.index >= LO) & (par.index <= HI)]

    gate = pd.read_parquet(OUT / "f7_gate.parquet")
    ga = gate[gate["book"] == "all"].set_index(["signature", "h"])

    print(f"window rows {len(win)}   h={H}")
    print(f"{'sig':>9} {'legs':>4} {'rt':>4} {'cmt_n':>5} {'cmt_pond':>8} "
          f"{'nblocks':>7} {'off_min':>7} {'off_med':>7} {'off_max':>7} "
          f"{'p_min':>6} {'p_med':>6} {'p_max':>6} {'crosses1x':>9}")
    for sig in SPREADS + FLIES:
        x = lvl(win, sig)
        legs = len(sig.split("-"))
        rt = 1.8 if legs == 2 else 3.6
        meds, nb = [], None
        for o in range(H):
            i = np.arange(o, len(x) - H, H)
            nb = len(i)
            meds.append(float(np.median(np.abs(x[i + H] - x[i]))))
        m = np.array(meds)
        cmt = float(ga.loc[(sig, H), "abs_move_med"])
        cn = int(ga.loc[(sig, H), "n"])
        cross = "YES" if m.max() / rt >= 1.0 else "no"
        print(f"{sig:>9} {legs:>4} {rt:>4.1f} {cn:>5} {cmt / rt:>8.2f} "
              f"{nb:>7} {m.min():>7.3f} {np.median(m):>7.3f} {m.max():>7.3f} "
              f"{m.min()/rt:>6.2f} {np.median(m)/rt:>6.2f} {m.max()/rt:>6.2f} {cross:>9}")

    print("\n--- decision boundary check: does ANY offset move a signature across 1.0x? ---")
    for sig in SPREADS + FLIES:
        x = lvl(win, sig)
        legs = len(sig.split("-"))
        rt = 1.8 if legs == 2 else 3.6
        p = np.array([np.median(np.abs(x[np.arange(o, len(x) - H, H) + H]
                                      - x[np.arange(o, len(x) - H, H)])) / rt
                      for o in range(H)])
        cmt = float(ga.loc[(sig, H), "abs_move_med"]) / rt
        side_cmt = "clears" if cmt >= 1.0 else "fails"
        n_cross = int((p >= 1.0).sum())
        print(f"  {sig:>9}  committed {cmt:5.2f}x ({side_cmt})   offsets >= 1.0x: "
              f"{n_cross}/{H}   sweep [{p.min():.2f}, {p.max():.2f}]")


if __name__ == "__main__":
    main()
