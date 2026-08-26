"""What actually survives, and is it more than multiplicity?

k5 left three cells with |t| > 2 after release-cleaning and fixed effects:
  rank 3 [0->+5]  clean+month FE +0.065 (t 2.32), clean+day FE +0.113 (t 2.33)
  rank 1 [0->+30] clean+month FE +0.068 (t 2.10)
  rank 3 [0->+30] clean+day FE   +0.201 (t 2.06)

Two questions decide whether those are a finding or a lottery ticket:
  (a) COHERENCE.  A real reaction is monotone in the horizon over the first
      hour.  Print the whole offset grid, both ranks, under the strictest spec,
      and look for a shape rather than a cell.
  (b) MULTIPLICITY.  Count every rank x offset x specification cell computed in
      k1-k5 and compare the |t|>2 count with what the null predicts.

Then the two remaining live conditioners: the days_to_fomc gradient and the
2024 concentration, each re-run release-clean and with month FE.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(str(HERE))

from c_common import cluster_mean_se, cluster_ols, OFFSETS  # noqa: E402
from k1_release_window import load_calendar, flag_windows  # noqa: E402
from k2_trend_confound import fe_slope, identifying_groups  # noqa: E402

pd.set_option("display.width", 250)


def main():
    cal_all, rel = load_calendar()
    CAL_END = cal_all["release_ts_ny"].max()
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    res = {}
    tstats = []

    print("=" * 104)
    print("(a) COHERENCE -- the POST-SPEECH-ONLY leg [0 -> +off] across the whole grid")
    print("    raw / release-clean / clean+MONTH FE / clean+DAY FE, bp and (t)")
    print("=" * 104)
    post_offsets = [o for o in OFFSETS if o > 0]
    for rank in (1, 3):
        e = ev[ev["contract_rank"] == rank]
        meta = e.drop_duplicates("event_id").set_index("event_id").copy()
        meta["month"] = meta["speech_ts"].dt.strftime("%Y-%m")
        yy = {o: e[e["offset_min"] == o].set_index("event_id")["d_rate_bp_from_baseline"]
              .reindex(meta.index) for o in [0] + post_offsets}
        base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        v0 = yy[0][base].to_numpy()
        print(f"\n  RANK {rank}")
        print(f"  {'offset':>7s} {'n':>5s} | {'raw':>16s} {'clean':>16s} "
              f"{'clean+monthFE':>16s} {'clean+dayFE':>16s}")
        for off in post_offsets:
            post = yy[off][base].to_numpy() - v0
            f, _ = flag_windows(mb, rel_hm, 0, off)
            cl = ~f
            a = cluster_mean_se(post * sgn, clus)
            b = cluster_mean_se(post[cl] * sgn[cl], clus[cl])
            X = np.column_stack([np.ones(int(cl.sum())), sgn[cl],
                                 pd.get_dummies(pd.Series(mb["month"].to_numpy()[cl]),
                                                drop_first=True).to_numpy(float)])
            c = cluster_ols(post[cl], X, clus[cl],
                            names=["const", "s"] + [f"g{i}" for i in range(X.shape[1] - 2)])["s"]
            X2 = np.column_stack([np.ones(int(cl.sum())), sgn[cl],
                                  pd.get_dummies(pd.Series(mb["date"].to_numpy()[cl]),
                                                 drop_first=True).to_numpy(float)])
            d = cluster_ols(post[cl], X2, clus[cl],
                            names=["const", "s"] + [f"g{i}" for i in range(X2.shape[1] - 2)])["s"]
            tstats += [a["t"], b["t"], c["t"], d["t"]]
            print(f"  {'+' + str(off):>7s} {a['n']:>5d} | "
                  f"{a['mean']:+7.4f} ({a['t']:+5.2f}) {b['mean']:+7.4f} ({b['t']:+5.2f}) "
                  f"{c['coef']:+7.4f} ({c['t']:+5.2f}) {d['coef']:+7.4f} ({d['t']:+5.2f})")
            res[f"grid_r{rank}_{off}"] = dict(raw=a, clean=b, month=c, day=d)

    # ---------------------------------------------------------------- (b)
    tt = np.array([t for t in tstats if np.isfinite(t)])
    n_hit = int((np.abs(tt) > 1.96).sum())
    print("\n" + "=" * 104)
    print("(b) MULTIPLICITY over the coherence grid alone")
    print("=" * 104)
    print(f"  cells computed: {len(tt)}   |t|>1.96: {n_hit} ({n_hit / len(tt):.1%})   "
          f"expected under the null: {0.05 * len(tt):.1f} (5.0%)")
    print(f"  max |t| = {np.abs(tt).max():.2f};  a Bonferroni-5% threshold over {len(tt)} cells "
          f"is |t| > {abs(round(float(__import__('scipy.stats', fromlist=['norm']).norm.ppf(1 - 0.025 / len(tt))), 2)):.2f}")
    res["multiplicity"] = dict(n_cells=len(tt), n_hits=n_hit, max_abs_t=float(np.abs(tt).max()))

    # ---------------------------------------------------------------- (c)
    print("\n" + "=" * 104)
    print("(c) the two remaining live conditioners")
    print("=" * 104)
    for rank in (1, 3):
        e = ev[ev["contract_rank"] == rank]
        meta = e.drop_duplicates("event_id").set_index("event_id").copy()
        meta["month"] = meta["speech_ts"].dt.strftime("%Y-%m")
        v = e[e["offset_min"] == 240].set_index("event_id")["d_rate_bp_from_baseline"].reindex(meta.index)
        base = ((meta["stance_sign"] != 0) & (meta["speech_ts"] <= CAL_END)).to_numpy()
        mb = meta[base]
        sgn = mb["stance_sign"].to_numpy().astype(float)
        clus = mb["date"].to_numpy()
        vv = v[base].to_numpy()
        f, _ = flag_windows(mb, rel_hm, -60, 240)
        cl = ~f
        yr = mb["speech_ts"].dt.year.to_numpy()
        dtf = mb["days_to_fomc"].to_numpy()
        hi = dtf > np.quantile(dtf, 2 / 3)
        print(f"\n  RANK {rank} at +240")
        print(f"    2024 share of the high-days_to_fomc tercile: {(yr[hi] == 2024).mean():.0%} "
              f"vs {(yr[~hi] == 2024).mean():.0%} elsewhere")
        for nm, m in (("2024 only", yr == 2024), ("high days_to_fomc", hi),
                      ("2024 AND high days_to_fomc", (yr == 2024) & hi),
                      ("everything else", ~((yr == 2024) | hi))):
            a = cluster_mean_se(vv[m] * sgn[m], clus[m])
            b = cluster_mean_se(vv[m & cl] * sgn[m & cl], clus[m & cl])
            print(f"    {nm:<28s} all: {a['mean']:+7.4f} (t {a['t']:+5.2f}, n {a['n']:>3d})   "
                  f"release-clean: {b['mean']:+7.4f} (t {b['t']:+5.2f}, n {b['n']:>3d})")
            res[f"cond_r{rank}_{nm}"] = dict(all=a, clean=b)
        nm_, tot = identifying_groups(mb["month"].to_numpy(), sgn)
        nd_, totd = identifying_groups(mb["date"].to_numpy(), sgn)
        print(f"    (identification: {nm_}/{tot} months and {nd_}/{totd} days carry both arms)")

    with open(HERE / "k6_survivors.json", "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
