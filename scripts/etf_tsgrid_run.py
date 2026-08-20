r"""The timestamp grid: a SURFACE over time of day, not a top-10 list.

Axes, all of them counted
-------------------------
``mark_hour``   when the bonds are valued and the signal is standardised (New York clock)
``entry_hour``  when the package is executed; constrained ``>= mark_hour``
``hold``        0 (same session), 1, 5 or 21 business days
``exit_hour``   for ``hold = 0`` any hour after entry; for ``hold >= 1`` the entry hour or
                one of the two STRUCTURAL closes, 15:00 (cash) and 16:00 (NAV)
``signal``      7 holdings signals, 2 calendar-only nulls, 1 richness control
``orth``        raw, or cross-sectionally orthogonalised against richness at ``mark_hour``
``exec_lag``    1 or 2 business days on anything read from a holdings file
``cost``        3 anchors x 7 multipliers, applied to the gross of each cell

The last axis is applied analytically -- a multiplier cannot change a gross number -- so
the run evaluates ``N_gross`` cells and the reported configuration count is
``N_gross x 21``. Both are printed.

The placebo, which is the point
-------------------------------
Every cell is also run with three LABEL-PERMUTED signals: the same signal values, shuffled
across CUSIPs within each date. A permuted signal has no information by construction, so
whatever time-of-day structure appears in the placebo surface belongs to the return matrix
and the selection rule, not to the ladder. The real surface is only interesting where it
leaves the placebo surface.
"""
from __future__ import annotations

import itertools
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS
HOLDS = [0, 1, 5, 21]
STRUCTURAL_EXITS = (15, 16)
COST_MULTS = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0]
ANCHORS = ["measured", "flat", "sr1170"]
N_PLACEBO = 3


def exit_specs(entry: int):
    out = [(0, x) for x in H if x > entry]
    for hold in HOLDS[1:]:
        for x in dict.fromkeys((entry,) + STRUCTURAL_EXITS):
            out.append((hold, x))
    return out


def main():
    t0 = time.time()
    m = L.load_matrices()
    D, N = m.T.shape
    print(f"[grid] matrices {D} dates x {N} bonds, {m.dates.min().date()}"
          f"..{m.dates.max().date()}", flush=True)

    legs = L.build_legs(m, step=1)
    print(f"[grid] flies buildable on {legs.valid.sum():,} bond-dates "
          f"({legs.valid.sum()/max(1,np.isfinite(m.T).sum()):.3f} of priced bond-dates)",
          flush=True)

    FLY = {h: L.fly_level(m, legs, h) for h in H}
    COST = {a: L.package_cost_bp(m, legs, anchor=a) for a in ANCHORS}
    for a in ANCHORS:
        print(f"[grid] cost anchor {a:9s} median package round trip "
              f"{np.nanmedian(COST[a]):.4f} bp", flush=True)

    # ------------------------------------------------------------------ return matrices
    RET = {}
    for entry in H:
        for hold, ex in exit_specs(entry):
            fe = FLY[ex]
            if hold > 0:
                shifted = np.full_like(fe, np.nan)
                shifted[:-hold] = fe[hold:]
                fe = shifted
            RET[(entry, hold, ex)] = -(fe - FLY[entry]) * 100.0
    print(f"[grid] {len(RET)} distinct return matrices", flush=True)

    # Perfect-foresight ceiling per (mark, entry, hold, exit): the mean |move| of the six
    # biggest movers that were tradeable at that mark and entry. Every cell is asserted
    # against it, so a selection bug shows up as an impossible gross rather than as alpha.
    ELIG = {}
    for mark in H:
        for entry in [e for e in H if e >= mark]:
            ELIG[(mark, entry)] = (legs.valid & np.isfinite(FLY[mark])
                                   & np.isfinite(FLY[entry]))
    PFD = {}
    for (mark, entry), el in ELIG.items():
        for hold, ex in exit_specs(entry):
            PFD[(mark, entry, hold, ex)] = L.perfect_foresight_per_date(
                RET[(entry, hold, ex)], el, n=3)
    print(f"[grid] {len(PFD)} perfect-foresight vectors, {time.time()-t0:.0f}s",
          flush=True)

    # ------------------------------------------------------------------ signal matrices
    raw = L.build_signal_matrices(m, fund="TLT")
    raw["resid"] = m.RES[16]          # placeholder; replaced per mark_hour below
    rng = np.random.default_rng(L.TIE_SEED)

    def permuted(M: np.ndarray, k: int) -> np.ndarray:
        """Shuffle the signal ACROSS CUSIPS within each date. Keeps every marginal."""
        g = np.random.default_rng(L.TIE_SEED + 977 * k)
        out = np.full_like(M, np.nan)
        for d in range(M.shape[0]):
            row = M[d]
            ok = np.where(np.isfinite(row))[0]
            if ok.size:
                out[d, g.permutation(ok)] = row[ok]
        return out

    sig_names = list(L.ALL_SIGNALS)
    families = {}
    for s in sig_names:
        families[(s, "real")] = raw[s]
    for k in range(N_PLACEBO):
        families[(f"PLACEBO{k}", "placebo")] = permuted(raw["active_w"], k)
    print(f"[grid] {len(families)} signal families "
          f"({len(sig_names)} real + {N_PLACEBO} label-permuted)", flush=True)

    # ------------------------------------------------------------------ the grid
    rows = []
    perm = rng.permutation(N).astype(float)
    n_gross = 0
    for (sname, kind), M0 in families.items():
        for lag in (1, 2):
            Ml = L.lag_matrix(M0, lag)
            for mark in H:
                if sname == "resid":
                    Zbase = m.RESZ[mark]
                else:
                    Zbase = L._xsec_z(Ml)
                for orth in (False, True):
                    if orth and sname == "resid":
                        continue                       # resid orthogonal to itself is 0
                    Z = L.orthogonalize(Zbase, m.RESZ[mark]) if orth else Zbase
                    for entry in [e for e in H if e >= mark]:
                        elig = ELIG[(mark, entry)]
                        sel = L.select(Z, elig, n=3, rng_perm=perm)
                        if not sel.usable.any():
                            continue
                        for hold, ex in exit_specs(entry):
                            ret = RET[(entry, hold, ex)]
                            g, c_meas, ntr = L.cell_pnl(ret, COST["measured"], sel)
                            fin = np.isfinite(g)
                            if fin.sum() < 50:
                                continue
                            n_gross += 1
                            w = ntr[fin].astype(float)
                            gross = float(np.average(g[fin], weights=w))
                            # perfect-foresight ceiling on the SAME dates and universe
                            pfd = PFD[(mark, entry, hold, ex)]
                            pfok = fin & np.isfinite(pfd)
                            pf = (float(np.average(pfd[pfok], weights=ntr[pfok]))
                                  if pfok.any() else np.nan)
                            costs = {}
                            for a in ANCHORS:
                                _, ca, _ = L.cell_pnl(ret, COST[a], sel)
                                costs[a] = float(np.average(ca[fin], weights=w))
                            lags_nw = max(1, hold)
                            rows.append({
                                "signal": sname, "kind": kind, "orth": orth, "lag": lag,
                                "mark": mark, "entry": entry, "hold": hold, "exit": ex,
                                "n_dates": int(fin.sum()), "n_trades": int(ntr.sum()),
                                "gross_bp": gross,
                                "t_nw": L.newey_west_t(g, lags_nw),
                                "pf_bp": pf,
                                "gross_over_pf": gross / pf if pf > 0 else np.nan,
                                "cost_measured": costs["measured"],
                                "cost_flat": costs["flat"],
                                "cost_sr1170": costs["sr1170"],
                            })
        print(f"[grid] {sname:14s} done, {len(rows):,} cells, "
              f"{time.time()-t0:.0f}s", flush=True)

    grid = pd.DataFrame(rows)
    grid.to_csv(DATA / "tsgrid_grid.csv", index=False)
    print(f"[grid] {len(grid):,} gross cells written; "
          f"x{len(COST_MULTS)*len(ANCHORS)} cost variants "
          f"= {len(grid)*len(COST_MULTS)*len(ANCHORS):,} configurations", flush=True)

    # ------------------------------------------------------------------ hard assertions
    bad = grid[grid["gross_over_pf"].abs() > 1.0 + 1e-9]
    print(f"[grid] ASSERT gross <= perfect foresight: "
          f"{len(bad)} violations of {len(grid)}", flush=True)
    if len(bad):
        bad.to_csv(DATA / "tsgrid_ASSERT_VIOLATIONS.csv", index=False)
    print(f"[grid] done in {time.time()-t0:.0f}s", flush=True)
    return grid


if __name__ == "__main__":
    main()
