"""Adversarial pass 8: attack the ONE surviving claim (H3), the cost anchor, and staleness.

H3 attack
---------
The report's carry-forward is "a butterfly moves ~1.75x more per minute in 15:00-17:00 on
the last business day".  Three ways that can be true and uninteresting:
 (i)  the whole DAY is more volatile at month end and the late session merely inherits it
      -> normalise each day's late-session |dR| by its OWN midday |dR|;
 (ii) it is not a BUTTERFLY fact at all, just the outright market -> run the identical
      statistic on |dy| of the bonds themselves;
 (iii) it is a handful of days -> leave-one-out and per-year.

Staleness
---------
Re-run the report's own headline cells with eligibility restricted to bond-hours whose
mark is NOT a carry-forward of the prior hour, at mark, entry and exit.
"""
from __future__ import annotations
import pathlib, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
rng = np.random.default_rng(4242)

# =============================================================== H3 on the minute profile
prof = pd.read_parquet(DATA / "tsgrid_minute_profile_raw.parquet")
print("minute profile:", prof.shape, "dates", prof.date.nunique(),
      "last-bd", int(prof.groupby("date")["is_last_bd"].first().sum()))
p = prof[~prof.early_close].copy()
p["blk"] = np.where((p.minute > 900) & (p.minute <= 1020), "late",
                    np.where((p.minute > 660) & (p.minute <= 840), "midday", "other"))

day = p.pivot_table(index="date", columns="blk", values="mean_abs_bp", aggfunc="mean")
day["is_last_bd"] = p.groupby("date")["is_last_bd"].first()
day = day.dropna(subset=["late", "midday"])
a, b = day[day.is_last_bd], day[~day.is_last_bd]
print("\nn last-bd %d, n other %d" % (len(a), len(b)))


def perm_p(x, y, stat, n=20000):
    obs = stat(x, y)
    allv = np.concatenate([x, y])
    na = len(x)
    null = np.empty(n)
    for i in range(n):
        pp = rng.permutation(allv)
        null[i] = stat(pp[:na], pp[na:])
    return obs, float((null >= obs).mean()), float(np.quantile(null, .95))


rat = lambda u, v: u.mean() / v.mean()
o1, p1, q1 = perm_p(a["late"].to_numpy(), b["late"].to_numpy(), rat)
o2, p2, q2 = perm_p(a["midday"].to_numpy(), b["midday"].to_numpy(), rat)
nl_a = (a["late"] / a["midday"]).to_numpy()
nl_b = (b["late"] / b["midday"]).to_numpy()
o3, p3, q3 = perm_p(nl_a, nl_b, rat)
print("\n=== H3 (i) day-level normalisation, fly |dR| per minute ===")
print("  raw late-session ratio  lastBD/other = %.3f  perm p %.4f  null p95 %.3f" % (o1, p1, q1))
print("  raw MIDDAY      ratio  lastBD/other = %.3f  perm p %.4f  null p95 %.3f" % (o2, p2, q2))
print("  late/midday RATIO-OF-RATIOS          = %.3f  perm p %.4f  null p95 %.3f" % (o3, p3, q3))

# ---- (iii) leave-one-out and per-year on the raw late ratio
loo = np.array([a["late"].drop(d).mean() / b["late"].mean() for d in a.index])
print("\n=== H3 (iii) leave-one-out on the %d last-BDs ===" % len(a))
print("  late ratio: full %.3f  LOO min %.3f max %.3f" % (o1, loo.min(), loo.max()))
yr = day.groupby([day.index.year, "is_last_bd"])["late"].mean().unstack()
yr["ratio"] = yr[True] / yr[False]
yr["n_lastbd"] = a.groupby(a.index.year).size()
print(yr.round(4).to_string())
yr.to_csv(DATA / "adv_ts_h3_by_year.csv")

# =============================================================== H3 (ii) outright vs fly
print("\n=== H3 (ii) is it a BUTTERFLY fact or just the outright market? ===")
try:
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
    from RVUtils.ETFRebalance import intraday as itd
    uni = itd.universe()
    i2c = dict(zip(uni["isin"].astype(str), uni["cusip"].astype(str)))
    q = CitiVeloQuotes(offline=True)
    MIN = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "MI01")
    MIN.columns = [i2c.get(str(c).split(".")[2], str(c)) for c in MIN.columns]
    MIN = itd.drop_impossible(MIN, "YIELD")
    mi = pd.DatetimeIndex(MIN.index)
    mm = (mi.hour * 60 + mi.minute).to_numpy()
    sel = (mm >= 540) & (mm <= 1020)
    MIN, mi, mm = MIN[sel], mi[sel], mm[sel]
    dnorm = mi.normalize()
    m = L.load_matrices()
    lb = pd.Series(m.is_last_bd, index=m.dates)
    ec = pd.Series(m.early_close, index=m.dates)
    rows = []
    for d, gi in pd.Series(np.arange(len(mi)), index=dnorm).groupby(level=0):
        if d not in lb.index or ec.get(d, False):
            continue
        idx = gi.to_numpy()
        sub = MIN.iloc[idx]
        mns = mm[idx]
        G = sub.set_axis(mns).reindex(np.arange(540, 1021)).ffill(limit=10)
        dy = np.abs(np.diff(G.to_numpy(), axis=0)) * 100.0
        gm = np.arange(541, 1021)
        late = np.nanmean(dy[(gm > 900) & (gm <= 1020)])
        mid = np.nanmean(dy[(gm > 660) & (gm <= 840)])
        if np.isfinite(late) and np.isfinite(mid):
            rows.append(dict(date=d, late=late, midday=mid, is_last_bd=bool(lb[d])))
    oy = pd.DataFrame(rows)
    ay, by = oy[oy.is_last_bd], oy[~oy.is_last_bd]
    r1, pp1, _ = perm_p(ay["late"].to_numpy(), by["late"].to_numpy(), rat)
    r2, pp2, _ = perm_p((ay.late / ay.midday).to_numpy(), (by.late / by.midday).to_numpy(), rat)
    print("  OUTRIGHT |dy|/min: late-session lastBD/other = %.3f (p %.4f); "
          "late/midday ratio-of-ratios = %.3f (p %.4f)  n=%d/%d"
          % (r1, pp1, r2, pp2, len(ay), len(by)))
    oy.to_csv(DATA / "adv_ts_h3_outright.csv", index=False)
except Exception as exc:                                    # pragma: no cover
    print("  outright leg failed:", exc)

# =============================================================== staleness re-run
print("\n=== STALENESS: re-run headline cells with stale marks excluded ===")
m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in L.CLOCK_HOURS}
COST = L.package_cost_bp(m, legs, anchor="measured")
raw = L.build_signal_matrices(m, fund="TLT")
pc = np.random.default_rng(L.TIE_SEED).permutation(m.T.shape[1]).astype(float)
print("hourly stale fraction by clock hour:",
      {h: round(float(m.STALE[h].mean()), 4) for h in L.CLOCK_HOURS})

CELLS = [("deletion", True, 15, 15, 1, 15), ("deletion", True, 10, 10, 21, 10),
         ("not_held", False, 10, 10, 21, 15), ("resid", False, 15, 15, 1, 15),
         ("flow", True, 10, 11, 0, 17)]
out = []
for sname, orth, mk, en, hold, ex in CELLS:
    Zb = m.RESZ[mk] if sname == "resid" else L._xsec_z(L.lag_matrix(raw[sname], 1))
    Z = L.orthogonalize(Zb, m.RESZ[mk]) if orth else Zb
    fe = FLY[ex]
    if hold > 0:
        sh = np.full_like(fe, np.nan); sh[:-hold] = fe[hold:]; fe = sh
    ret = -(fe - FLY[en]) * 100.0
    for tag, extra in (("all", None), ("fresh", "fresh")):
        el = legs.valid & np.isfinite(FLY[mk]) & np.isfinite(FLY[en])
        if extra:
            fresh = ~m.STALE[mk] & ~m.STALE[en] & ~m.STALE[ex]
            el = el & fresh
        sel = L.select(Z, el, n=3, rng_perm=pc)
        g, c, n = L.cell_pnl(ret, COST, sel)
        fin = np.isfinite(g)
        if fin.sum() < 20:
            out.append(dict(signal=sname, orth=orth, mark=mk, entry=en, hold=hold,
                            exit=ex, subset=tag, n_dates=int(fin.sum())))
            continue
        w = n[fin].astype(float)
        gr = float(np.average(g[fin], weights=w)); cs = float(np.average(c[fin], weights=w))
        out.append(dict(signal=sname, orth=orth, mark=mk, entry=en, hold=hold, exit=ex,
                        subset=tag, n_dates=int(fin.sum()), gross_bp=gr,
                        t_nw=float(L.newey_west_t(g, max(1, hold))), cost_bp=cs,
                        breakeven_x=gr / cs))
st = pd.DataFrame(out)
st.to_csv(DATA / "adv_ts_stale_rerun.csv", index=False)
print(st.round(5).to_string(index=False))

# =============================================================== cost anchor
print("\n=== COST ANCHOR ===")
for anc in ("measured", "flat", "sr1170"):
    C = L.package_cost_bp(m, legs, anchor=anc)
    print("  %-9s package round trip bp: med %.4f mean %.4f p10 %.4f p90 %.4f"
          % (anc, np.nanmedian(C), np.nanmean(C), np.nanpercentile(C, 10), np.nanpercentile(C, 90)))
Cm = L.package_cost_bp(m, legs, anchor="measured")
byyr = pd.Series(np.nanmedian(Cm, axis=1), index=m.dates).groupby(m.dates.year).median()
print("  measured median package round trip by year:")
print(byyr.round(4).to_string())
leg_y = np.where(m.SPREAD_PX >= 0.5, m.SPREAD_PX, np.nan) / m.MODDUR
print("  per-LEG yield-bp spread: med %.4f p90 %.4f  (price bp med %.3f, mod dur med %.2f)"
      % (np.nanmedian(leg_y), np.nanpercentile(leg_y, 90),
         np.nanmedian(m.SPREAD_PX), np.nanmedian(m.MODDUR)))
byyr.to_csv(DATA / "adv_ts_cost_by_year.csv")
