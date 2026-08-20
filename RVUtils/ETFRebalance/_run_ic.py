"""The IC surface for every signal, on every fund with a band. Run before any grid."""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402
from RVUtils.ETFRebalance import ic as IC  # noqa: E402
from RVUtils.ETFRebalance import signals as SIG  # noqa: E402

pd.set_option("display.width", 220)

HORIZONS = (1, 5, 10, 21, 42, 63)


def build_scores(uni: pd.DataFrame, sp) -> tuple[pd.DataFrame, list[str]]:
    """Every registered signal as its own standardised column -- no blending."""
    kw = {
        "deletion": {"band_low": sp.band_low or 0.0},
        "addition": {"band_high": sp.band_high or np.inf},
        "flow": {"window": 5},
        "active_chg": {"window": 5},
        "ownership_chg": {"window": 21},
    }
    cols = []
    out = uni.copy()
    for name in SIG.REGISTRY:
        try:
            raw = SIG.REGISTRY[name](out, **kw.get(name, {}))
        except Exception as exc:
            print(f"  {name}: SKIPPED ({type(exc).__name__}: {exc})", flush=True)
            continue
        z = SIG.cross_sectional_z(raw, out["date"], robust=True).clip(-5, 5)
        if z.notna().sum() < 5000:
            print(f"  {name}: too few finite values ({int(z.notna().sum())}), skipped", flush=True)
            continue
        out[f"z_{name}"] = z
        cols.append(f"z_{name}")
    return out, cols


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", default="TLT")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--exec-lag", type=int, default=1)
    a = ap.parse_args()

    panel = FP.asof_join(BP.load(), FP.load())
    funds = [f.strip().upper() for f in a.funds.split(",") if f.strip()]
    joined = HP.build(funds, panel=panel)

    all_ic, all_ls = [], {}
    for fund in funds:
        sp = spec(fund)
        cfg = EN.merge_config({"fund": fund, "universe": {"start": a.start}})
        t0 = time.time()
        uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
        print(f"\n{'=' * 78}\n{fund}: {len(uni):,} gated bond-days, "
              f"{uni['date'].nunique():,} dates, {uni['cusip'].nunique()} cusips "
              f"({time.time() - t0:.1f}s)")
        if uni.empty:
            continue

        q = CV.residual_quality(uni)
        print(f"  residual: median lag-1 autocorr {q['autocorr_1'].median():.4f}  "
              f"median sd {q['sd_bp'].median():.3f}bp  "
              f"(a real richness series runs 0.85-0.99; near zero means noise)")
        hl = CV.half_life_days(uni)
        fin = hl[np.isfinite(hl)]
        if len(fin):
            print(f"  residual OU half-life: median {fin.median():.0f} business days "
                  f"over {len(fin)} CUSIPs -- the horizon a mean-reversion trade should "
                  f"be measured against")

        scored, cols = build_scores(uni, sp)
        tab = IC.ic_table(scored, cols, HORIZONS, exec_lag=a.exec_lag)
        tab.insert(0, "fund", fund)
        all_ic.append(tab)

        piv = tab.pivot_table(index="signal", columns="horizon", values="ic_mean")
        piv_t = tab.pivot_table(index="signal", columns="horizon", values="ic_t")
        print(f"\n  mean cross-sectional IC vs forward residual richening "
              f"(exec_lag={a.exec_lag}):")
        print("  " + piv.round(4).to_string().replace("\n", "\n  "))
        print("\n  t-statistic across dates:")
        print("  " + piv_t.round(2).to_string().replace("\n", "\n  "))

        best = tab.reindex(tab["ic_t"].abs().sort_values(ascending=False).index).head(6)
        print("\n  strongest cells by |t|:")
        print("  " + best.round(4).to_string(index=False).replace("\n", "\n  "))

        for _, r in best.head(3).iterrows():
            ds = IC.decile_spread(scored, r["signal"], int(r["horizon"]),
                                  n_buckets=5, exec_lag=a.exec_lag)
            print(f"\n  {r['signal']} @ {int(r['horizon'])}d -- forward return by quintile (bp):")
            print("  " + ds.round(4).to_string().replace("\n", "\n  "))
            ls = IC.long_short_series(scored, r["signal"], int(r["horizon"]),
                                      n_names=3, exec_lag=a.exec_lag)
            all_ls[f"{fund}:{r['signal']}@{int(r['horizon'])}"] = ls
            if len(ls) > 20:
                print(f"  costless top3-minus-bottom3, {int(r['horizon'])}d holding: "
                      f"mean {ls.mean():+.4f}bp  t {ls.mean() / (ls.std(ddof=1) / np.sqrt(len(ls))):+.2f}  "
                      f"n={len(ls)}")

    if all_ic:
        out = pd.concat(all_ic, ignore_index=True)
        p = BP.panel_dir() / "ic_surface.parquet"
        out.to_parquet(p, index=False)
        print(f"\nwrote {p}  ({len(out)} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
