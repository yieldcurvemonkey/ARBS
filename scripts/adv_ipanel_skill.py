r"""ADVERSARIAL CHECK 2b: the report compares MEAN |fly move| to cost. That is the
ceiling for a trader who trades EVERY fly. A real trader trades the ones he thinks will
move. 0.8-1.2% of seam flies DO move more than the 0.99 bp cost, so the mean-vs-cost
argument is not by itself a proof.

This asks the only question that matters: what forecasting skill would be needed to
find them? A signal with correlation rho to the realised move, trade the top-k flies by
predicted |move|, charge the cost on every trade, and report NET.

rho is imposed, not fitted: signal = rho*z + sqrt(1-rho^2)*noise, both standardised
against the realised move. rho=1.0 is perfect foresight -- the report's own ceiling.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")
COST = 0.9915
RNG = np.random.default_rng(20260820)


def build_moves(p, col, lo, hi, fresh_min=5, min_bonds=20):
    w = p[p["mark_time"].isin((lo, hi)) & p[col].notna()
          & p["stale_min_ytm"].le(fresh_min) & p["stale_min_px"].le(fresh_min)]
    piv = w.pivot_table(index=["date", "cusip"], columns="mark_time", values=col).dropna()
    ttm = w.groupby(["date", "cusip"])["ttm"].first()
    d = (piv[hi] - piv[lo]).rename("dres").to_frame().join(ttm)
    out = []
    for date, g in d.groupby(level=0):
        g = g.sort_values("ttm")
        if len(g) < min_bonds:
            continue
        v = g["dres"].to_numpy()
        f = 2.0 * v[1:-1] - v[:-2] - v[2:]
        out.append((date, f))
    return out


def skill_test(moves, rho, topk, n_draws=40):
    """Trade top-k flies per date ranked by a signal of correlation rho. Net bp."""
    nets = []
    for _ in range(n_draws):
        tot, ntr = 0.0, 0
        for _date, f in moves:
            z = (f - f.mean()) / (f.std() + 1e-12)
            sig = rho * z + np.sqrt(max(0.0, 1 - rho ** 2)) * RNG.standard_normal(z.size)
            # trade the k flies with the largest predicted |move|, in the predicted
            # direction; P&L is the realised move signed by the prediction
            idx = np.argsort(-np.abs(sig))[:topk]
            pnl = np.sign(sig[idx]) * f[idx] * f.std() / (f.std() + 1e-12)
            tot += float(np.sum(np.sign(sig[idx]) * f[idx]))
            ntr += len(idx)
        nets.append((tot, ntr))
    a = np.array(nets)
    gross_per_trade = a[:, 0].mean() / a[0, 1]
    return {"rho": rho, "topk": topk, "trades": int(a[0, 1]),
            "gross_bp_per_trade": gross_per_trade,
            "cost_bp_per_trade": COST,
            "net_bp_per_trade": gross_per_trade - COST}


def main() -> int:
    pd.set_option("display.width", 240)
    p = pd.read_parquet(DATA / "ipanel_mi01.parquet")
    p["date"] = pd.to_datetime(p["date"])

    rows = []
    for col in ("resid_bp", "resid_bp_tlt19"):
        moves = build_moves(p, col, "15:00", "16:00")
        allf = np.concatenate([f for _, f in moves])
        print(f"{col}: {len(moves)} dates, {allf.size:,} flies, "
              f"sd {allf.std():.4f} bp, mean|f| {np.abs(allf).mean():.4f} bp, "
              f"kurtosis {float(pd.Series(allf).kurt()):.1f}, "
              f"P(|f|>{COST}) {float((np.abs(allf)>COST).mean()):.4f}")
        for rho in (0.05, 0.10, 0.20, 0.50, 1.00):
            for topk in (1, 3, 10):
                r = skill_test(moves, rho, topk, n_draws=20 if rho < 1 else 1)
                r["col"] = col
                rows.append(r)
    t = pd.DataFrame(rows)[["col", "rho", "topk", "trades", "gross_bp_per_trade",
                            "cost_bp_per_trade", "net_bp_per_trade"]]
    print("\nSKILL REQUIRED TO MONETISE THE 15:00->16:00 SEAM TAIL")
    print("(gross is bp per butterfly per trade; cost is the measured 0.99 bp fly round trip)")
    print(t.round(4).to_string(index=False))
    t.to_csv(DATA / "adv_ipanel_skill.csv", index=False)

    best = t.loc[t["net_bp_per_trade"].idxmax()]
    print(f"\nBEST CELL: {best['col']} rho={best['rho']} topk={int(best['topk'])} "
          f"-> net {best['net_bp_per_trade']:.4f} bp/trade")
    print("wrote adv_ipanel_skill.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
