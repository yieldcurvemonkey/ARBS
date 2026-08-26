"""Skeptic probe 3: is the rank-1 cell a buried signal or a tail artefact, and is
the placebo band biased by its blackout-day composition (which would bias the
DiD toward FINDING an effect)?
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = {}


def p(*a):
    print(" ".join(str(x) for x in a), flush=True)


def clt(v, day):
    v = np.asarray(v, float); day = np.asarray(day)
    ok = np.isfinite(v); v, day = v[ok], day[ok]
    r = sm.OLS(v, np.ones((v.size, 1))).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(day)[0]})
    return dict(n=int(v.size), mean=float(v.mean()), t=float(r.tvalues[0]), p=float(r.pvalues[0]))


def excess(real, fake):
    st = pd.concat([real.assign(r=1.0)[["signed_d_bp", "day", "r"]],
                    fake.assign(r=0.0)[["signed_d_bp", "day", "r"]]])
    X = sm.add_constant(st["r"].to_numpy())
    m = sm.OLS(st["signed_d_bp"].to_numpy(), X).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(st["day"])[0]})
    return dict(coef=float(m.params[1]), t=float(m.tvalues[1]), p=float(m.pvalues[1]))


def main():
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    ev["day"] = pd.to_datetime(ev["date"].astype(str))
    pl["day"] = pd.to_datetime(pl["date"].astype(str))
    sg = ev[ev["stance_sign"] != 0]

    # ---------------------------------------- rank1 +240: reconcile + stress
    p("=" * 100)
    p("RANK 1 @ +240 -- the strongest cell in the whole book. Is it real?")
    p("=" * 100)
    for tag, d in (("ALL events", sg[(sg["contract_rank"] == 1) & (sg["offset_min"] == 240)]),
                   ("NON-OVERLAP", sg[(sg["contract_rank"] == 1) & (sg["offset_min"] == 240)
                                      & (~sg["is_overlapping"])])):
        d = d.dropna(subset=["signed_d_bp"])
        b = clt(d["signed_d_bp"], d["day"])
        dm = d.groupby("day")["signed_d_bp"].mean()
        k = max(1, int(np.ceil(0.01 * dm.size)))
        w = dm.abs().sort_values(ascending=False).head(k)
        tr = clt(d.loc[~d["day"].isin(w.index), "signed_d_bp"], d.loc[~d["day"].isin(w.index), "day"])
        nz = d.loc[d["signed_d_bp"] != 0, "signed_d_bp"]
        bt = stats.binomtest(int((nz > 0).sum()), len(nz), 0.5)
        p(f"  {tag:<12} n={b['n']:4d}  mean {b['mean']:+.4f}bp t_clu {b['t']:+.3f} | "
          f"trim1%days {tr['mean']:+.4f}bp t {tr['t']:+.3f} | median {np.median(d['signed_d_bp']):+.3f} | "
          f"sign {100*(nz>0).mean():.1f}% p={bt.pvalue:.3f}")
        OUT[f"rank1_240_{tag.replace(' ','_').replace('-','_')}"] = dict(
            base=b, trim=tr, median=float(np.median(d["signed_d_bp"])),
            sign_pct=float(100 * (nz > 0).mean()), sign_p=float(bt.pvalue),
            trim_days=[str(x.date()) for x in w.index])

    # per-year stability of rank1 +240 (a real effect should not live in one year)
    p("\n  rank1 +240 by YEAR (all events):")
    d = sg[(sg["contract_rank"] == 1) & (sg["offset_min"] == 240)].dropna(subset=["signed_d_bp"])
    yr = {}
    for y, g in d.groupby(d["day"].dt.year):
        b = clt(g["signed_d_bp"], g["day"])
        p(f"    {y}: n={b['n']:4d}  {b['mean']:+.4f}bp  t={b['t']:+.3f}")
        yr[int(y)] = b
    OUT["rank1_240_by_year"] = yr

    # ---------------------------------------- placebo composition bias
    p("")
    p("=" * 100)
    p("PLACEBO COMPOSITION: does the null band sit on systematically QUIETER days?")
    p("=" * 100)
    r3 = sg[(sg["contract_rank"] == 3) & (sg["offset_min"] == 240)].dropna(subset=["signed_d_bp"])
    p3 = pl[(pl["contract_rank"] == 3) & (pl["offset_min"] == 240)
            & (pl["stance_sign"] != 0)].dropna(subset=["signed_d_bp"])
    for tag, d in (("real", r3), ("placebo", p3)):
        v = d["d_rate_bp_from_baseline"].abs()
        p(f"  {tag:<8} |d_rate| at +240: mean {v.mean():.3f}  median {v.median():.3f}  "
          f"sd {d['d_rate_bp_from_baseline'].std():.3f}  p90 {v.quantile(0.9):.3f}  "
          f"zero-share {100*(v==0).mean():.1f}%   days_to_fomc mean {d['days_to_fomc'].mean():.1f}")
        OUT[f"vol_{tag}"] = dict(mean_abs=float(v.mean()), median_abs=float(v.median()),
                                 sd=float(d["d_rate_bp_from_baseline"].std()),
                                 p90_abs=float(v.quantile(0.9)),
                                 zero_share_pct=float(100 * (v == 0).mean()),
                                 mean_days_to_fomc=float(d["days_to_fomc"].mean()))
    rat = p3["d_rate_bp_from_baseline"].std() / r3["d_rate_bp_from_baseline"].std()
    p(f"  --> placebo/real SD ratio = {rat:.3f}. <1 means the null band is drawn from "
      f"QUIETER days than the events, which biases any excess-over-placebo UPWARD.")
    OUT["placebo_over_real_sd_ratio"] = float(rat)
    # blackout proxy: days_to_fomc <= 10 (blackout starts ~T-10)
    for tag, d in (("real", r3), ("placebo", p3)):
        p(f"  {tag:<8} share within 10d before next FOMC (blackout proxy): "
          f"{100*(d['days_to_fomc']<=10).mean():.1f}%")
        OUT[f"blackout_share_{tag}"] = float(100 * (d["days_to_fomc"] <= 10).mean())

    # ---------------------------------------- 1-week window claim (Finding 4)
    p("")
    p("=" * 100)
    p("FINDING 4 CROSS-CHECK: does anything at all survive on the LONGEST offset here?")
    p("=" * 100)
    for off in (240, 300):
        d = sg[(sg["contract_rank"] == 3) & (sg["offset_min"] == off)].dropna(subset=["signed_d_bp"])
        b = clt(d["signed_d_bp"], d["day"])
        p(f"  rank3 +{off}: {b['mean']:+.4f}bp t={b['t']:+.3f} n={b['n']}")
    p("  (the 1-day/1-week windows are built in c4 from a different series and are not")
    p("   reproducible from this panel, whose widest offset is +300 min)")

    # ---------------------------------------- overlap dependence audit
    p("")
    p("=" * 100)
    p("OVERLAP AUDIT: how much price-path reuse is there really?")
    p("=" * 100)
    e1 = ev.drop_duplicates("event_id")
    p(f"  events {len(e1)}: overlapping {int(e1['is_overlapping'].sum())} "
      f"({100*e1['is_overlapping'].mean():.1f}%), clean {int((~e1['is_overlapping']).sum())}")
    p(f"  n_other_in_window distribution: {e1['n_other_in_window'].value_counts().sort_index().head(10).to_dict()}")
    ec = e1[e1["stance_sign"] != 0]
    p(f"  SIGNED events {len(ec)}: clean {int((~ec['is_overlapping']).sum())}")
    dupe = e1.groupby(["date", "symbol"]).size()
    p(f"  events per (day, symbol): max {dupe.max()}, mean {dupe.mean():.2f}, "
      f"share of events on a day carrying >1 event {100*(1-(dupe==1).sum()/len(e1)):.1f}%")
    OUT["overlap"] = dict(n_events=int(len(e1)), n_overlapping=int(e1["is_overlapping"].sum()),
                          n_clean=int((~e1["is_overlapping"]).sum()),
                          max_events_per_day_symbol=int(dupe.max()))
    # do two events sharing a window get the SAME signed move booked twice?
    g = ev[(ev["contract_rank"] == 3) & (ev["offset_min"] == 240)].dropna(subset=["d_rate_bp_from_baseline"])
    dd = g.groupby(["date", "symbol"])["d_rate_bp_from_baseline"].nunique()
    nn = g.groupby(["date", "symbol"]).size()
    same = ((nn > 1) & (dd == 1)).sum()
    p(f"  (day,symbol) groups with >1 event: {int((nn>1).sum())}; of those, "
      f"{int(same)} have an IDENTICAL +240 move booked to every event in the group")
    OUT["identical_move_groups"] = dict(multi_groups=int((nn > 1).sum()), identical=int(same))

    (HERE / "skeptic_probe3.json").write_text(json.dumps(OUT, indent=1, default=float),
                                              encoding="utf-8")
    p("\nwrote skeptic_probe3.json")


if __name__ == "__main__":
    main()
