"""Skeptic probe 2: (a) is there a buried REAL signal anywhere -- especially the
rank-1 / DiD cells the agent downgraded; (b) SVB week in the wider book;
(c) multiplicity census; (d) tail-dependence of every cell that reaches |t|>2.
"""
from __future__ import annotations

import io
import json
import re
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
    v = np.asarray(v, float)
    day = np.asarray(day)
    ok = np.isfinite(v)
    v, day = v[ok], day[ok]
    if v.size < 3:
        return dict(n=int(v.size), mean=np.nan, t=np.nan, n_days=0)
    r = sm.OLS(v, np.ones((v.size, 1))).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(day)[0]})
    return dict(n=int(v.size), n_days=int(len(set(day.tolist()))),
                mean=float(v.mean()), t=float(r.tvalues[0]), p=float(r.pvalues[0]))


def main():
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    ev["day"] = pd.to_datetime(ev["date"].astype(str))
    pl["day"] = pd.to_datetime(pl["date"].astype(str))
    sg = ev[ev["stance_sign"] != 0]

    # ---------------------------------------------------------------- SVB
    p("=" * 100)
    p("(b) SVB WEEK 2023-03-06..2023-03-17")
    p("=" * 100)
    svb = (ev["day"] >= "2023-03-06") & (ev["day"] <= "2023-03-17")
    p(f"  ALL rank3 events in SVB week: {ev.loc[svb & (ev['contract_rank']==3),'event_id'].nunique()}")
    p(f"  SIGNED rank3 events in SVB week: "
      f"{sg.loc[(sg['day']>='2023-03-06')&(sg['day']<='2023-03-17')&(sg['contract_rank']==3),'event_id'].nunique()}")
    a3 = sg[(sg["contract_rank"] == 3) & (sg["offset_min"] == 240)].dropna(subset=["signed_d_bp"])
    m_svb = (a3["day"] >= "2023-03-06") & (a3["day"] <= "2023-03-17")
    ss = (a3["signed_d_bp"] ** 2).sum()
    p(f"  ALL-EVENTS book at +240: n={len(a3)}; SVB-week events {int(m_svb.sum())}; "
      f"share of squared variation {100*(a3.loc[m_svb,'signed_d_bp']**2).sum()/ss:.2f}%")
    OUT["svb_all_events_n"] = int(m_svb.sum())
    OUT["svb_all_events_share_sqvar_pct"] = float(100 * (a3.loc[m_svb, "signed_d_bp"] ** 2).sum() / ss)
    base = clt(a3["signed_d_bp"], a3["day"])
    exs = clt(a3.loc[~m_svb, "signed_d_bp"], a3.loc[~m_svb, "day"])
    p(f"  all-events +240 signed: base {base['mean']:+.4f}bp t={base['t']:+.3f} (n={base['n']})")
    p(f"                 ex-SVB : {exs['mean']:+.4f}bp t={exs['t']:+.3f} (n={exs['n']})")
    OUT["all_events_240_base"] = base
    OUT["all_events_240_exsvb"] = exs
    # top days of the ALL-events book
    dmm = a3.groupby("day")["signed_d_bp"].mean()
    k = max(1, int(np.ceil(0.01 * dmm.size)))
    worst = dmm.abs().sort_values(ascending=False).head(k)
    p(f"  top 1% of days ({k} of {dmm.size}) by |day mean|: "
      f"{[(str(d.date()), round(float(dmm.loc[d]),2)) for d in worst.index]}")
    tt = a3[~a3["day"].isin(worst.index)]
    r = clt(tt["signed_d_bp"], tt["day"])
    p(f"  all-events +240 TRIMMED top1% days: {r['mean']:+.4f}bp t={r['t']:+.3f} (n={r['n']})")
    OUT["all_events_240_trim1pct"] = r
    OUT["all_events_trim_days"] = [str(d.date()) for d in worst.index]

    # -------------------------------------------------- (a) buried signal hunt
    p("")
    p("=" * 100)
    p("(a) BURIED-SIGNAL HUNT: every rank x offset cell, day-clustered, base vs trimmed")
    p("=" * 100)
    p(f"  {'rank':>4} {'off':>5} | {'n':>5} {'mean':>9} {'t_clu':>7} | "
      f"{'trim mean':>10} {'t_trim':>7} | {'excess':>8} {'t_exc':>7}")
    cells = []
    for rk in (1, 2, 3, 4, 5):
        for off in (5, 15, 30, 60, 120, 240, 300):
            d = sg[(sg["contract_rank"] == rk) & (sg["offset_min"] == off)].dropna(subset=["signed_d_bp"])
            if len(d) < 20:
                continue
            b = clt(d["signed_d_bp"], d["day"])
            dm = d.groupby("day")["signed_d_bp"].mean()
            kk = max(1, int(np.ceil(0.01 * dm.size)))
            w = dm.abs().sort_values(ascending=False).head(kk)
            dt_ = d[~d["day"].isin(w.index)]
            tr = clt(dt_["signed_d_bp"], dt_["day"])
            pz = pl[(pl["contract_rank"] == rk) & (pl["offset_min"] == off)
                    & (pl["stance_sign"] != 0)].dropna(subset=["signed_d_bp"])
            st = pd.concat([d.assign(real=1.0)[["signed_d_bp", "day", "real"]],
                            pz.assign(real=0.0)[["signed_d_bp", "day", "real"]]])
            X = sm.add_constant(st["real"].to_numpy())
            rr = sm.OLS(st["signed_d_bp"].to_numpy(), X).fit(
                cov_type="cluster", cov_kwds={"groups": pd.factorize(st["day"])[0]})
            cells.append(dict(rank=rk, offset=off, n=b["n"], mean=b["mean"], t=b["t"],
                              trim_mean=tr["mean"], t_trim=tr["t"],
                              excess=float(rr.params[1]), t_excess=float(rr.tvalues[1])))
            p(f"  {rk:>4} {off:>5} | {b['n']:>5} {b['mean']:>+9.4f} {b['t']:>+7.3f} | "
              f"{tr['mean']:>+10.4f} {tr['t']:>+7.3f} | {rr.params[1]:>+8.4f} {rr.tvalues[1]:>+7.3f}")
    cd = pd.DataFrame(cells)
    OUT["cells"] = cd.to_dict(orient="records")
    n_t2 = int((cd["t"].abs() > 2).sum())
    n_t2_trim = int((cd["t_trim"].abs() > 2).sum())
    n_t2_exc = int((cd["t_excess"].abs() > 2).sum())
    p(f"\n  cells tested {len(cd)};  |t|>2 raw {n_t2};  |t|>2 AFTER 1% day trim {n_t2_trim};  "
      f"|t|>2 on excess-vs-placebo {n_t2_exc}")
    p(f"  expected |t|>2 count under a global null at 5%: {0.05*len(cd):.1f}")
    OUT["cells_n"] = len(cd)
    OUT["cells_t2_raw"] = n_t2
    OUT["cells_t2_trim"] = n_t2_trim
    OUT["cells_t2_excess"] = n_t2_exc

    # rank-1 +240 specifically (the agent's disclosed t=2.10 cell)
    d = sg[(sg["contract_rank"] == 1) & (sg["offset_min"] == 240)].dropna(subset=["signed_d_bp"])
    b = clt(d["signed_d_bp"], d["day"])
    nz = d.loc[d["signed_d_bp"] != 0, "signed_d_bp"]
    bt = stats.binomtest(int((nz > 0).sum()), len(nz), 0.5)
    p(f"\n  RANK1 +240 detail: mean {b['mean']:+.4f}bp t_clu={b['t']:+.3f} n={b['n']}; "
      f"median {np.median(d['signed_d_bp']):+.3f}; sign test {100*(nz>0).mean():.1f}% p={bt.pvalue:.3f}")
    OUT["rank1_240"] = dict(**b, median=float(np.median(d["signed_d_bp"])),
                            sign_pct=float(100 * (nz > 0).mean()), sign_p=float(bt.pvalue))

    # ------------------------------------------------- (c) multiplicity census
    p("")
    p("=" * 100)
    p("(c) MULTIPLICITY CENSUS - count of reported test statistics on disk")
    p("=" * 100)
    tot = 0
    for f in sorted(HERE.glob("*.json")):
        if f.name.startswith("skeptic"):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        n = len(re.findall(r'"[^"]*(?:_t|^t|t_|tstat|t_stat|pval|_p|p_value|pvalue|ci95|ci)"\s*:', txt, re.I))
        n2 = len(re.findall(r'"[^"]*t[^"]*"\s*:\s*-?\d', txt))
        p(f"  {f.name:<32} {f.stat().st_size/1024:7.1f} KB   t/p-like keys ~{max(n,n2)}")
        tot += max(n, n2)
    p(f"  TOTAL t/p-like statistics stored in the agent's own JSON: ~{tot}")
    OUT["multiplicity_json_stats"] = int(tot)

    (HERE / "skeptic_probe2.json").write_text(json.dumps(OUT, indent=1, default=float),
                                              encoding="utf-8")
    p("\nwrote skeptic_probe2.json")


if __name__ == "__main__":
    main()
