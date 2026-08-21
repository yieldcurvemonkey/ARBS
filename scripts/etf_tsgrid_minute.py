r"""H3 and H4 at MINUTE resolution, which is the only way to see a reconstitution footprint.

The hourly layer says the 15:00->16:00 hour is about twice as active on the last business
day of the month as on an ordinary day -- and so is the 16:00->17:00 hour, which no index
rule touches. An hourly bar cannot separate "the reconstitution prints into the cash market
at the 16:00 NAV strike" from "the whole late session is busier at month end". A minute
tape can, and the MI01 layer was warmed in month-turn blocks precisely to cover these days.

Also here, because it is the same read: the print-count covariate H4 needs. The hourly
staleness flag says whether a bond's 16:00 mark equals its 15:00 mark; the minute tape says
how many times it actually printed in between, which is the difference between a quiet bond
and an absent one.

Two controls are carried through every table:
* the **16:00->17:00 hour**, after the cash market's mark and after the NAV strike -- if the
  15:00->16:00 amplification is a reconstitution it should not be matched there; and
* **SIFMA early closes**, which are excluded and then re-included, because 11 of the 82 last
  business days in the sample are 14:00 closes and a 14:00 close makes the 15:00 and 16:00
  marks the same number by construction.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import etf_tsgrid_lib as L

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from RVUtils.ETFRebalance import intraday as itd
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

DATA = L.DATA
SESSION = (9 * 60, 17 * 60)          # minutes from midnight, New York


def main():
    t0 = time.time()
    m = L.load_matrices()
    legs = L.build_legs(m, step=1)
    uni = itd.universe()
    isin2cusip = dict(zip(uni["isin"].astype(str), uni["cusip"].astype(str)))

    q = CitiVeloQuotes(offline=True)
    fr = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "MI01")
    fr.columns = [isin2cusip.get(str(c).split(".")[2], str(c)) for c in fr.columns]
    fr = itd.drop_impossible(fr, "YIELD")
    idx = pd.DatetimeIndex(fr.index)
    mins = idx.hour * 60 + idx.minute
    fr = fr[(mins >= SESSION[0]) & (mins <= SESSION[1])]
    idx = pd.DatetimeIndex(fr.index)
    print(f"[min] MI01 session tape {fr.shape}, "
          f"{idx.normalize().nunique()} dates, {time.time()-t0:.0f}s", flush=True)

    # align columns to the matrix universe
    fr = fr.reindex(columns=m.cusips)
    day = idx.normalize()
    minute = (idx.hour * 60 + idx.minute).to_numpy()

    # PRINT COUNT per (date, bond) inside the seam hour and inside the control hour
    counts = {}
    for name, (lo, hi) in {"seam_1500_1600": (900, 960),
                           "ctrl_1600_1700": (960, 1020),
                           "ctrl_1400_1500": (840, 900)}.items():
        sel = (minute >= lo) & (minute < hi)
        sub = fr[sel]
        c = sub.notna().groupby(pd.DatetimeIndex(sub.index).normalize()).sum()
        counts[name] = c
    seam_prints = counts["seam_1500_1600"]

    # ---------------------------------------------------------------- minute grid
    # forward fill inside a day only, and only for 10 minutes: a 2-minute median gap is
    # this tape's liquidity, but a bond that has not printed for a quarter of an hour is
    # absent rather than quiet, and carrying it manufactures a zero move.
    grid_minutes = np.arange(SESSION[0], SESSION[1] + 1)
    days = pd.DatetimeIndex(np.unique(day))
    print(f"[min] {len(days)} minute-tape dates, {len(grid_minutes)} minutes each",
          flush=True)

    dpos = {d: i for i, d in enumerate(m.dates)}
    keep = [d for d in days if d in dpos]
    print(f"[min] {len(keep)} of them are in the hourly panel", flush=True)

    rows_prof = []
    rows_day = []
    fr_np = fr.to_numpy(float)
    day_np = day.to_numpy()
    for d in keep:
        sel = day_np == np.datetime64(d)
        y = fr_np[sel]
        mn = minute[sel]
        if y.shape[0] < 50:
            continue
        Yraw = pd.DataFrame(y, index=mn).reindex(grid_minutes)
        fresh = np.isfinite(Yraw.to_numpy()).sum(axis=1)   # FRESH prints, before any fill
        Y = Yraw.ffill(limit=10)
        i = dpos[d]
        val = legs.valid[i]
        if val.sum() < 12:
            continue
        a = legs.a[i]
        f = legs.front[i]
        b = legs.back[i]
        A = Y.to_numpy()
        R = A - a[None, :] * A[:, f] - (1.0 - a[None, :]) * A[:, b]
        R = np.where(val[None, :], R, np.nan)
        dR = np.diff(R, axis=0) * 100.0                     # bp per minute
        for k, mm in enumerate(grid_minutes[1:]):
            v = dR[k]
            v = v[np.isfinite(v)]
            if v.size < 8:
                continue
            rows_prof.append({"date": d, "minute": int(mm),
                              "n_flies": v.size,
                              "mean_abs_bp": float(np.mean(np.abs(v))),
                              "xsec_sd_bp": float(np.std(v)),
                              "n_fresh_prints": int(fresh[k + 1])})
        rows_day.append({"date": d, "n_minutes": int(np.isfinite(dR).any(axis=1).sum())})
    prof = pd.DataFrame(rows_prof)
    prof["is_last_bd"] = prof["date"].map(
        pd.Series(m.is_last_bd, index=m.dates)).fillna(False)
    prof["early_close"] = prof["date"].map(
        pd.Series(m.early_close, index=m.dates)).fillna(False)
    prof.to_parquet(DATA / "tsgrid_minute_profile_raw.parquet", index=False)
    print(f"[min] minute profile {prof.shape}, {time.time()-t0:.0f}s", flush=True)

    # ---------------------------------------------------------------- H3 minute answer
    lines = []

    def say(s):
        print(s, flush=True)
        lines.append(s)

    p = prof[~prof.early_close]
    say("=== H3-minute  activity by minute of the New York session ===")
    say(f"minute tape: {p['date'].nunique()} dates "
        f"({int(p.groupby('date')['is_last_bd'].first().sum())} last-business-days), "
        f"SIFMA early closes EXCLUDED")
    agg = p.groupby(["is_last_bd", p["minute"] // 15 * 15]).agg(
        mean_abs_bp=("mean_abs_bp", "mean"),
        xsec_sd_bp=("xsec_sd_bp", "mean")).reset_index()
    piv = agg.pivot(index="minute", columns="is_last_bd", values="mean_abs_bp")
    piv.columns = ["other_days", "last_bd"]
    piv["ratio"] = piv["last_bd"] / piv["other_days"]
    piv["clock"] = [f"{i//60:02d}:{i%60:02d}" for i in piv.index]
    pv = agg.pivot(index="minute", columns="is_last_bd", values="xsec_sd_bp")
    piv["xsd_other"] = pv[False]
    piv["xsd_lastbd"] = pv[True]
    piv2 = p.groupby(["is_last_bd", p["minute"] // 15 * 15])["n_fresh_prints"].mean().unstack(0)
    piv["fresh_prints_other"] = piv2[False]
    piv["fresh_prints_lastbd"] = piv2[True]
    piv["print_ratio"] = piv["fresh_prints_lastbd"] / piv["fresh_prints_other"]
    piv.to_csv(DATA / "tsgrid_h3_minute_profile.csv")
    say(piv.round(4).to_string())

    say("")
    say("=== H3-minute  the hour blocks, last business day vs the rest ===")
    blocks = {"10:00-11:00": (600, 660), "13:00-14:00": (780, 840),
              "14:00-15:00": (840, 900), "15:00-16:00 THE SEAM": (900, 960),
              "16:00-17:00 control": (960, 1020)}
    rows = []
    for excl_ec in (True, False):
        pp = prof[~prof.early_close] if excl_ec else prof
        for name, (lo, hi) in blocks.items():
            s = pp[(pp.minute > lo) & (pp.minute <= hi)]
            a = s[s.is_last_bd].groupby("date")["mean_abs_bp"].mean()
            b = s[~s.is_last_bd].groupby("date")["mean_abs_bp"].mean()
            if a.empty or b.empty:
                continue
            # a permutation test on the DAY labels: the ratio is a statistic about 70-80
            # days, and an eyeballed 2x on that many days is not automatically real
            allv = np.concatenate([a.to_numpy(), b.to_numpy()])
            na = a.size
            g = np.random.default_rng(L.TIE_SEED)
            obs = a.mean() / b.mean()
            null = np.empty(5000)
            for it in range(5000):
                perm = g.permutation(allv)
                null[it] = perm[:na].mean() / perm[na:].mean()
            rows.append({
                "exclude_early_close": excl_ec, "block": name,
                "n_lastbd": int(na), "n_other": int(b.size),
                "lastbd_mean_abs_bp": float(a.mean()),
                "other_mean_abs_bp": float(b.mean()),
                "ratio": float(obs),
                "perm_p": float((null >= obs).mean()),
                "perm_null_p95_ratio": float(np.quantile(null, 0.95)),
            })
    h3m = pd.DataFrame(rows)
    h3m.to_csv(DATA / "tsgrid_h3_minute_blocks.csv", index=False)
    say(h3m.round(4).to_string(index=False))

    # ---------------------------------------------------------------- H4 print counts
    say("")
    say("=== H4-minute  prints in the seam hour, and what a low count does ===")
    sp = seam_prints.reindex(m.dates)
    npr = sp.reindex(columns=m.cusips).to_numpy(float)
    elig = legs.valid & np.isfinite(L.fly_level(m, legs, 15)) & np.isfinite(
        L.fly_level(m, legs, 16))
    seam = -(L.fly_level(m, legs, 16) - L.fly_level(m, legs, 15)) * 100.0
    have = elig & np.isfinite(npr) & np.isfinite(seam)
    say(f"bond-dates with both an hourly seam move and a minute print count: "
        f"{int(have.sum()):,}")
    cnt = np.where(have, npr, np.nan)
    qs = np.nanquantile(cnt, [0.25, 0.5, 0.75])
    say(f"prints in the 15:00-16:00 hour per bond: p25 {qs[0]:.0f}  "
        f"median {qs[1]:.0f}  p75 {qs[2]:.0f}  "
        f"zero-print share {float(np.nanmean(cnt == 0)):.4f}")
    rows = []
    edges = [-0.5, 0.5, 5.5, 15.5, 30.5, 1e9]
    labs = ["0 prints", "1-5", "6-15", "16-30", "31+"]
    for lo, hi, lab in zip(edges[:-1], edges[1:], labs):
        mask = have & (npr > lo) & (npr <= hi)
        if mask.sum() < 50:
            continue
        v = np.where(mask, seam, np.nan)
        stale = np.where(mask, m.STALE[16], np.nan)
        rows.append({"print_bucket": lab, "bond_dates": int(mask.sum()),
                     "mean_abs_seam_bp": float(np.nanmean(np.abs(v))),
                     "sd_seam_bp": float(np.nanstd(v)),
                     "hourly_stale_frac": float(np.nanmean(stale))})
    h4 = pd.DataFrame(rows)
    h4.to_csv(DATA / "tsgrid_h4_print_buckets.csv", index=False)
    say(h4.round(4).to_string(index=False))

    # does the seam pond survive if only well-printed bonds are traded?
    for thresh in (0, 1, 6, 16):
        mask = have & (npr >= thresh)
        pf = L.perfect_foresight_per_date(np.where(mask, seam, np.nan), mask, n=3)
        say(f"  seam perfect-foresight ceiling with >= {thresh:2d} prints/hour: "
            f"{np.nanmean(pf):.4f} bp on {int(np.isfinite(pf).sum())} dates")

    # H3 again, on the HOURLY marks but only for bonds that actually printed a lot in the
    # window -- if the month-end amplification is a print-density artefact it must shrink.
    say("")
    say("=== H3 x H4  month-end amplification, restricted to well-printed bonds ===")
    ctrl_np = counts["ctrl_1600_1700"].reindex(m.dates).reindex(columns=m.cusips).to_numpy(float)
    ctrl_ret = -(L.fly_level(m, legs, 17) - L.fly_level(m, legs, 16)) * 100.0
    rows = []
    for wname, R, cnt_mat in (("15:00->16:00 THE SEAM", seam, npr),
                              ("16:00->17:00 control", ctrl_ret, ctrl_np)):
        for thresh in (0, 16, 31):
            base = legs.valid & np.isfinite(R) & np.isfinite(cnt_mat) & (cnt_mat >= thresh)
            a = np.nanmean(np.abs(np.where(base & m.is_last_bd[:, None], R, np.nan)))
            b = np.nanmean(np.abs(np.where(base & ~m.is_last_bd[:, None], R, np.nan)))
            rows.append({"window": wname, "min_prints_in_window": thresh,
                         "bond_dates": int(base.sum()),
                         "lastbd_mean_abs_bp": float(a), "other_mean_abs_bp": float(b),
                         "ratio": float(a / b)})
    h34 = pd.DataFrame(rows)
    h34.to_csv(DATA / "tsgrid_h3xh4_print_controlled.csv", index=False)
    say(h34.round(4).to_string(index=False))

    (DATA / "tsgrid_minute_findings.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"[min] done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
