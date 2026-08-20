"""Adversarial pass 7: one trade, end to end, from the RAW MINUTE TAPE.

Takes the report's named cell (deletion orth, mark 15 / entry 15 / hold 1bd / exit 15),
picks a date with MI01 coverage, and rebuilds one butterfly's gross bp by hand:
raw minute yields -> hourly marks -> fly level -> P&L -> engine's own per-date number.
Also prints the cost decomposition for that package.
"""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from RVUtils.ETFRebalance import intraday as itd
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
import etf_tsgrid_lib as L

DATA = L.DATA
m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in L.CLOCK_HOURS}
COSTm = L.package_cost_bp(m, legs, anchor="measured")
raw = L.build_signal_matrices(m, fund="TLT")

MARK, ENTRY, HOLD, EXIT, LAG = 15, 15, 1, 15, 1
Z = L.orthogonalize(L._xsec_z(L.lag_matrix(raw["deletion"], LAG)), m.RESZ[MARK])
elig = legs.valid & np.isfinite(FLY[MARK]) & np.isfinite(FLY[ENTRY])
pc = np.random.default_rng(L.TIE_SEED).permutation(m.T.shape[1]).astype(float)
sel = L.select(Z, elig, n=3, rng_perm=pc)

fe = FLY[EXIT]; sh = np.full_like(fe, np.nan); sh[:-HOLD] = fe[HOLD:]
ret = -(sh - FLY[ENTRY]) * 100.0
g, c, ntr = L.cell_pnl(ret, COSTm, sel)

uni = itd.universe()
i2c = dict(zip(uni["isin"].astype(str), uni["cusip"].astype(str)))
c2i = {v: k for k, v in i2c.items()}
q = CitiVeloQuotes(offline=True)
MIN = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "MI01")
MIN.columns = [i2c.get(str(c).split(".")[2], str(c)) for c in MIN.columns]
mi = pd.DatetimeIndex(MIN.index)
mindays = set(pd.DatetimeIndex(mi.normalize()).unique())

# a date that is usable, has a next trading day, and has minute coverage on BOTH days
cand = [d for d in range(len(m.dates) - 1)
        if sel.usable[d] and np.isfinite(g[d])
        and m.dates[d] in mindays and m.dates[d + HOLD] in mindays]
print("candidate dates:", len(cand))
d = cand[len(cand) // 2]
D0, D1 = m.dates[d], m.dates[d + HOLD]
print("\n=== HAND TRADE: entry %s, exit %s (hold %d panel rows) ===" % (D0.date(), D1.date(), HOLD))

top, bot = sel.top[d], sel.bot[d]
print("selected LONG bellies :", [m.cusips[i] for i in top])
print("selected SHORT bellies:", [m.cusips[i] for i in bot])

def hand_mark(cusip, day, clock_hour):
    """Last MI01 print at or before (clock_hour-1):59 on `day` -- the panel's own convention."""
    st = itd.ny_stamp(clock_hour)
    s = MIN[cusip][(mi.normalize() == day) & (mi.hour == st)].dropna()
    return (float(s.iloc[-1]), s.index[-1]) if len(s) else (np.nan, pd.NaT)

tot = []
for lbl, idxs, sgn in (("LONG", top, +1.0), ("SHORT", bot, -1.0)):
    for j in idxs:
        f, b, a = legs.front[d, j], legs.back[d, j], legs.a[d, j]
        names = [m.cusips[j], m.cusips[f], m.cusips[b]]
        rowsy = {}
        for day, tag in ((D0, "entry"), (D1, "exit")):
            vals, stamps = [], []
            for nm in names:
                v, ts = hand_mark(nm, day, ENTRY if tag == "entry" else EXIT)
                vals.append(v); stamps.append(ts)
            rowsy[tag] = (vals, stamps)
        (ye, se), (yx, sx) = rowsy["entry"], rowsy["exit"]
        R0 = ye[0] - a * ye[1] - (1 - a) * ye[2]
        R1 = yx[0] - a * yx[1] - (1 - a) * yx[2]
        hand = -(R1 - R0) * 100.0 * sgn
        eng = sgn * ret[d, j]
        print("\n%s belly %s (front %s back %s) a=%.4f  ttm %.2f/%.2f/%.2f"
              % (lbl, names[0], names[1], names[2], a, m.T[d, j], m.T[d, f], m.T[d, b]))
        print("  entry minute marks %s -> y = %.5f %.5f %.5f  R0=%.6f%%"
              % ([str(s)[11:16] for s in se], ye[0], ye[1], ye[2], R0))
        print("  exit  minute marks %s -> y = %.5f %.5f %.5f  R1=%.6f%%"
              % ([str(s)[11:16] for s in sx], yx[0], yx[1], yx[2], R1))
        print("  HAND gross %+.5f bp   ENGINE %+.5f bp   diff %.2e"
              % (hand, eng, abs(hand - eng)))
        print("  package cost: %.4f bp  (belly leg %.4f, |a|=%.3f, |1-a|=%.3f)"
              % (COSTm[d, j], COSTm[d, j] / (1 + abs(a) + abs(1 - a)), abs(a), abs(1 - a)))
        tot.append((hand, eng, COSTm[d, j]))

h = np.array([t[0] for t in tot]); e = np.array([t[1] for t in tot]); cc = np.array([t[2] for t in tot])
print("\nBOOK for %s: hand mean gross %+.5f bp, engine mean %+.5f bp (engine g[d]=%+.5f)"
      % (D0.date(), np.nanmean(h), np.nanmean(e), g[d]))
print("           mean package cost %.4f bp -> NET %+.5f bp" % (np.nanmean(cc), np.nanmean(h) - np.nanmean(cc)))
print("           max |hand - engine| over the 6 legs = %.3e bp" % np.nanmax(np.abs(h - e)))
