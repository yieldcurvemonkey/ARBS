"""Adversarial pass 6: a null MATCHED TO `deletion`, the report's only null-clearing cell.

Two nulls the report never ran:
 (a) permute `deletion`'s OWN labels across cusips within each date, 40 draws.  Keeps the
     3-level sparse marginal, destroys which bond is flagged.
 (b) MATCHED-BOUNDARY placebo: the same construction with the index's 20y drop boundary
     moved to 21..26y.  A boundary at 24y has no index meaning; if it scores like 20y the
     effect is the cubic's edge, not the reconstitution rule.
"""
from __future__ import annotations
import pathlib, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS
HOLDS = [0, 1, 5, 21]
SEX = (15, 16)


def exit_specs(entry):
    out = [(0, x) for x in H if x > entry]
    for hold in HOLDS[1:]:
        for x in dict.fromkeys((entry,) + SEX):
            out.append((hold, x))
    return out


t0 = time.time()
m = L.load_matrices()
legs = L.build_legs(m, step=1)
FLY = {h: L.fly_level(m, legs, h) for h in H}
COST = L.package_cost_bp(m, legs, anchor="measured")
RET = {}
for entry in H:
    for hold, ex in exit_specs(entry):
        fe = FLY[ex]
        if hold > 0:
            sh = np.full_like(fe, np.nan); sh[:-hold] = fe[hold:]; fe = sh
        RET[(entry, hold, ex)] = -(fe - FLY[entry]) * 100.0
ELIG = {(mk, en): (legs.valid & np.isfinite(FLY[mk]) & np.isfinite(FLY[en]))
        for mk in H for en in H if en >= mk}
pc = np.random.default_rng(L.TIE_SEED).permutation(m.T.shape[1]).astype(float)


def run_one(M0, lag=1, orths=(True,)):
    Ml = L.lag_matrix(M0, lag)
    Zb = L._xsec_z(Ml)
    rows = []
    for mark in H:
        for orth in orths:
            Z = L.orthogonalize(Zb, m.RESZ[mark]) if orth else Zb
            for entry in [e for e in H if e >= mark]:
                sel = L.select(Z, ELIG[(mark, entry)], n=3, rng_perm=pc)
                if not sel.usable.any():
                    continue
                for hold, ex in exit_specs(entry):
                    g, c, ntr = L.cell_pnl(RET[(entry, hold, ex)], COST, sel)
                    fin = np.isfinite(g)
                    if fin.sum() < 50:
                        continue
                    w = ntr[fin].astype(float)
                    rows.append(dict(mark=mark, entry=entry, hold=hold, exit=ex,
                                     gross=float(np.average(g[fin], weights=w)),
                                     cost=float(np.average(c[fin], weights=w)),
                                     t=L.newey_west_t(g, max(1, hold))))
    return pd.DataFrame(rows)


# ------------------------------------------------------------ rebuild deletion with a knob
act = pd.read_parquet(DATA / "fundfig_active_TLT.parquet")
act = act[act["cusip"].isin(set(m.cusips))]
act = act[act["date"] >= m.dates.min() - pd.Timedelta(days=400)].sort_values(["date", "cusip"])
hd = pd.DatetimeIndex(np.sort(act["date"].unique()))
TTM_H = act.pivot_table(index="date", columns="cusip", values="ttm",
                        aggfunc="last").reindex(index=hd, columns=m.cusips).to_numpy(float)


def deletion_at(bound: float) -> np.ndarray:
    me = hd + pd.offsets.MonthEnd(0)
    hit = np.full((hd.size, m.cusips.size), np.nan)
    for mth in range(3, -1, -1):
        rebal = me + pd.offsets.MonthEnd(mth)
        dd = ((rebal - hd).days.to_numpy(float) / 365.25)[:, None]
        hit = np.where((TTM_H - dd) < bound, float(mth), hit)
    v = -np.where(np.isfinite(hit), 4.0 - hit, 0.0) / 4.0
    df = pd.DataFrame(v, index=hd, columns=m.cusips)
    return df.reindex(m.dates, method="ffill", limit=5).to_numpy(float)


base = deletion_at(20.0)
d0 = run_one(base)
print("deletion(20y) REAL: cells %d max|t| %.2f max gross %.4f max BE %.4fx"
      % (len(d0), d0.t.abs().max(), d0.gross.max(), (d0.gross / d0.cost).max()), flush=True)

# ------------------------------------------------------------ (a) label permutation null
def permute_rows(M, seed):
    g = np.random.default_rng(seed)
    out = np.full_like(M, np.nan)
    for d in range(M.shape[0]):
        row = M[d]
        ok = np.where(np.isfinite(row))[0]
        if ok.size:
            out[d, g.permutation(ok)] = row[ok]
    return out


rows = []
for k in range(40):
    d = run_one(permute_rows(base, 55_000 + 17 * k))
    rows.append(dict(kind="perm", key=k, cells=len(d), max_abs_t=float(d.t.abs().max()),
                     max_gross=float(d.gross.max()), max_be=float((d.gross / d.cost).max())))
    if k % 10 == 0:
        print("  perm %d max|t| %.2f (%.0fs)" % (k, rows[-1]["max_abs_t"], time.time() - t0), flush=True)
pn = pd.DataFrame(rows)
print("\n(a) deletion label-permutation null over 40 draws: max|t| med %.2f p95 %.2f MAX %.2f"
      % (pn.max_abs_t.median(), pn.max_abs_t.quantile(.95), pn.max_abs_t.max()))
print("    real 4.58 -> p = %.3f" % float((pn.max_abs_t >= d0.t.abs().max()).mean()))
print("    max break-even: null med %.4fx p95 %.4fx vs real %.4fx"
      % (pn.max_be.median(), pn.max_be.quantile(.95), (d0.gross / d0.cost).max()))

# ------------------------------------------------------------ (b) matched boundary placebo
rows2 = []
for bnd in [19.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0]:
    M = deletion_at(bnd)
    nz = float(np.nanmean(M != 0))
    d = run_one(M)
    if not len(d):
        print("  boundary %.0fy: no usable cells (rarity %.4f)" % (bnd, nz))
        continue
    rows2.append(dict(boundary=bnd, nonzero_frac=nz, cells=len(d),
                      max_abs_t=float(d.t.abs().max()), max_gross=float(d.gross.max()),
                      max_be=float((d.gross / d.cost).max())))
    print("  boundary %.0fy: rarity %.4f cells %d max|t| %.2f max gross %.4f max BE %.4fx"
          % (bnd, nz, len(d), rows2[-1]["max_abs_t"], rows2[-1]["max_gross"], rows2[-1]["max_be"]), flush=True)
bp = pd.DataFrame(rows2)
real_row = dict(boundary=20.0, nonzero_frac=float(np.nanmean(base != 0)), cells=len(d0),
                max_abs_t=float(d0.t.abs().max()), max_gross=float(d0.gross.max()),
                max_be=float((d0.gross / d0.cost).max()))
bp = pd.concat([pd.DataFrame([real_row]), bp], ignore_index=True).sort_values("boundary")
bp.to_csv(DATA / "adv_ts_deletion_boundary_placebo.csv", index=False)
pn.to_csv(DATA / "adv_ts_deletion_perm_null.csv", index=False)
print("\n(b) MATCHED-BOUNDARY PLACEBO")
print(bp.to_string(index=False))
