"""Two cheap gates from panels already on disk (families F4-event, F5-volfly).

GATE A — FOMC event windows on ultra-long forwards: the 2019 thesis says the
10y10y/20y10y spread "has nothing to do with policy"; if decision days move it
anyway, the move is a candidate fade. Measure |Δspread| on FOMC decision days
vs ordinary days (USD screen panel), and the 5/21bd reversion of the
decision-day move — the STIR graveyard's FOMC result (the move STICKS) is the
prior to beat.

GATE B — expiry-kink vol flies (Citi vol-lab catalog): 3M2Y/6M2Y/1Y2Y and
6M1Y/1Y1Y/2Y1Y ATM vol flies (50/50), z vs trailing 252d, non-overlapping
5/21bd forward moves on |z|>=1.5 fires vs the CM-1 3-leg round trip
(2x half-spread per leg summed).

Run: conda run -n stir python scripts/f4_event_and_volfly_gates.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"


def fomc_dates():
    from Query.IRSwaps import _CENTRAL_BANK_DATES as CB

    m = CB._CENTRAL_BANK_DATES["USD-SOFR-1D"]  # {label: (decision, next_decision)}
    return {pd.Timestamp(v[0]).normalize() for v in m.values()}


def gate_a() -> None:
    screen = pd.read_parquet(DATA / "sv_screen_USD.parquet")
    screen["date"] = pd.to_datetime(screen["date"])
    try:
        fomc = fomc_dates()
    except Exception as exc:  # noqa: BLE001
        print(f"GATE A: no FOMC calendar source ({type(exc).__name__}: {exc}) — SKIPPED")
        return
    print(f"GATE A — FOMC decision-day moves ({len(fomc)} dates in calendar):")
    for pair in ["USD 10Y10Y/20Y10Y", "USD 15Y5Y/20Y10Y"]:
        g = screen[screen["pair"] == pair].set_index("date").sort_index()
        ds = g["spread_bp"].diff()
        is_fomc = pd.Series(g.index.normalize().isin(fomc), index=g.index)
        ev, base = ds[is_fomc].abs().dropna(), ds[~is_fomc].abs().dropna()
        # reversion of the signed decision-day move
        rows = []
        for h in (5, 21):
            fwd = g["spread_bp"].shift(-h) - g["spread_bp"]
            move = ds[is_fomc]
            rev = (-np.sign(move) * fwd[is_fomc]).dropna()  # + = reverts
            rows.append((h, float(rev.median()), float((rev > 0).mean())))
        print(f"  {pair}: |move| median event {ev.median():.2f}bp vs base "
              f"{base.median():.2f}bp (ratio {ev.median()/base.median():.2f}, "
              f"n_ev {len(ev)}); reversion med "
              + ", ".join(f"{h}bd {m:+.2f}bp (frac {f:.0%})" for h, m, f in rows))


def gate_b() -> None:
    vol = pd.read_parquet(DATA / "vol_panel.parquet")
    atm = vol[vol["offset_bp"] == 0.0].copy()
    atm["cell"] = atm["expiry"] + "x" + atm["tenor"]
    mat = atm.pivot_table(index="date", columns="cell", values="vol_bp",
                          aggfunc="last").sort_index()
    mat.index = pd.to_datetime(mat.index)
    CM1 = {"3M": 0.38, "6M": 0.25, "1Y": 0.21, "2Y": 0.23}
    print("\nGATE B — expiry-kink ATM vol flies (50/50), |z|>=1.5 non-overlap fires:")
    for legs, tail in ((("3M", "6M", "1Y"), "2Y"), (("6M", "1Y", "2Y"), "1Y")):
        f, b, k = (f"{legs[0]}x{tail}", f"{legs[1]}x{tail}", f"{legs[2]}x{tail}")
        if not all(c in mat.columns for c in (f, b, k)):
            continue
        fly = mat[b] - 0.5 * (mat[f] + mat[k])
        mu = fly.rolling(252, min_periods=126).mean()
        sd = fly.rolling(252, min_periods=126).std()
        z = (fly - mu) / sd
        rt = 2.0 * sum(CM1[e] for e in legs)  # 3 legs, RT each
        # non-overlapping fires
        fires = []
        i, idx = 0, fly.index
        zv = z.to_numpy()
        while i < len(idx) - 21:
            if np.isfinite(zv[i]) and abs(zv[i]) >= 1.5:
                fires.append(i)
                i += 21
            else:
                i += 1
        revs5, revs21 = [], []
        for i in fires:
            d0 = fly.iloc[i] - mu.iloc[i]
            for h, acc in ((5, revs5), (21, revs21)):
                if i + h < len(idx) and np.isfinite(fly.iloc[i + h]):
                    acc.append(float(np.sign(d0) * (fly.iloc[i] - fly.iloc[i + h])))
        print(f"  {legs[1]}{tail} fly ({f}/{b}/{k}): {len(fires)} fires | "
              f"fly sd {fly.std():.2f}bp | med rev 5bd "
              f"{np.median(revs5) if revs5 else float('nan'):+.2f} / 21bd "
              f"{np.median(revs21) if revs21 else float('nan'):+.2f}bp vs RT {rt:.2f}bp "
              f"| frac21>RT {np.mean([r > rt for r in revs21]) if revs21 else float('nan'):.0%}")


if __name__ == "__main__":
    gate_a()
    gate_b()
