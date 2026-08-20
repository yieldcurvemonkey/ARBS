r"""H1-H4, stated as hypotheses about the market's plumbing and tested as such.

H1  The 15:00 cash mark against the 16:00 NAV strike.
H2  Does the signal read better at one hour than another?
H3  The last business day, where the index reconstitutes.
H4  Is any of it just staleness?

Each answer is a number with a unit and a comparison, never an IC or a t on its own.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

import etf_tsgrid_lib as L

DATA = L.DATA
H = L.CLOCK_HOURS


def per_date_spearman(Z, R, mask, min_n=12, min_u=6):
    D = Z.shape[0]
    out = np.full(D, np.nan)
    for d in range(D):
        ok = mask[d] & np.isfinite(Z[d]) & np.isfinite(R[d])
        if ok.sum() < min_n:
            continue
        z, r = Z[d][ok], R[d][ok]
        if np.unique(z).size < min_u or np.unique(r).size < min_u:
            continue
        out[d] = stats.spearmanr(z, r).statistic
    return out


def main():
    t0 = time.time()
    m = L.load_matrices()
    legs = L.build_legs(m, step=1)
    FLY = {h: L.fly_level(m, legs, h) for h in H}
    COST = {a: L.package_cost_bp(m, legs, anchor=a) for a in ("measured", "flat", "sr1170")}
    raw = L.build_signal_matrices(m, fund="TLT")
    D, N = m.T.shape
    dates = m.dates

    def ret(entry, ex, hold=0):
        fe = FLY[ex]
        if hold:
            s = np.full_like(fe, np.nan); s[:-hold] = fe[hold:]; fe = s
        return -(fe - FLY[entry]) * 100.0

    elig = legs.valid & np.isfinite(FLY[15]) & np.isfinite(FLY[16])
    seam = ret(15, 16)

    out_lines = []

    def say(s):
        print(s, flush=True)
        out_lines.append(s)

    # ------------------------------------------------------- cost, stated before P&L
    cm = COST["measured"]
    say("=== COST, stated first ===")
    cost_rows = []
    for y, idx in pd.Series(dates.year, index=range(D)).groupby(lambda i: dates.year[i]):
        pass
    yr = dates.year.to_numpy()
    for y in np.unique(yr):
        v = cm[yr == y]
        cost_rows.append({"year": int(y), "n": int(np.isfinite(v).sum()),
                          "pkg_rt_bp_median": float(np.nanmedian(v)),
                          "pkg_rt_bp_mean": float(np.nanmean(v))})
    cdf = pd.DataFrame(cost_rows)
    cdf.to_csv(DATA / "tsgrid_cost_by_year.csv", index=False)
    say(cdf.round(3).to_string(index=False))
    COST_MED = float(np.nanmedian(cm))
    say(f"measured butterfly round trip: median {COST_MED:.3f} bp, "
        f"mean {np.nanmean(cm):.3f} bp   (daily study's TLT-universe median was 0.535)")
    say(f"flat anchor {np.nanmedian(COST['flat']):.3f} bp   "
        f"sr1170 anchor {np.nanmedian(COST['sr1170']):.2f} bp")

    # =====================================================================  H1
    say("")
    say("=== H1  15:00 cash mark vs 16:00 NAV strike ===")
    ok = elig & np.isfinite(seam)
    say(f"seam sample: {int(ok.sum()):,} bond-dates over "
        f"{int((ok.sum(axis=1) > 0).sum()):,} dates")
    say(f"pooled mean seam move  {np.nanmean(np.where(ok, seam, np.nan)):+.5f} bp   "
        f"mean|move| {np.nanmean(np.abs(np.where(ok, seam, np.nan))):.4f} bp   "
        f"sd {np.nanstd(np.where(ok, seam, np.nan)):.4f} bp")

    # H1a: is there a PER-BOND systematic 15->16 drift?
    rows = []
    for j in range(N):
        v = np.where(ok[:, j], seam[:, j], np.nan)
        v = v[np.isfinite(v)]
        if v.size < 200:
            continue
        rows.append({"cusip": m.cusips[j], "n": v.size, "mean_bp": v.mean(),
                     "sd_bp": v.std(ddof=1), "t_nw": L.newey_west_t(v, 1)})
    h1a = pd.DataFrame(rows)
    h1a.to_csv(DATA / "tsgrid_h1a_per_bond_seam.csv", index=False)
    nsig = int((h1a.t_nw.abs() > 2).sum())
    say(f"H1a per-bond mean seam drift: {len(h1a)} bonds, "
        f"{nsig} with |HAC t| > 2 (5% of {len(h1a)} = {0.05*len(h1a):.1f} expected by chance); "
        f"largest |mean| {h1a.mean_bp.abs().max():.4f} bp, "
        f"median |mean| {h1a.mean_bp.abs().median():.4f} bp")
    say(f"     -> the 15:00 and 16:00 marks of a given bond differ by a mean of "
        f"{h1a.mean_bp.abs().median():.4f} bp, against a "
        f"{COST_MED:.3f} bp round trip = {h1a.mean_bp.abs().median()/COST_MED:.4f}x")

    # H1a level check: does the fitted richness LEVEL shift between the two marks?
    lev = []
    for j in range(N):
        d15 = np.where(elig[:, j], m.RES[15][:, j], np.nan)
        d16 = np.where(elig[:, j], m.RES[16][:, j], np.nan)
        d = d16 - d15
        d = d[np.isfinite(d)]
        if d.size < 200:
            continue
        lev.append({"cusip": m.cusips[j], "n": d.size, "mean_resid_shift_bp": d.mean(),
                    "t_nw": L.newey_west_t(d, 1)})
    h1lev = pd.DataFrame(lev)
    h1lev.to_csv(DATA / "tsgrid_h1a_resid_shift.csv", index=False)
    say(f"H1a richness LEVEL shift 15:00->16:00: median |mean| "
        f"{h1lev.mean_resid_shift_bp.abs().median():.4f} bp, "
        f"{int((h1lev.t_nw.abs()>2).sum())} of {len(h1lev)} bonds with |HAC t| > 2")

    # H1b: is the seam move forecastable from the ladder?
    rows = []
    pf_seam = L.perfect_foresight_per_date(seam, elig, n=3)
    for sig in L.ALL_SIGNALS:
        for lag in (1, 2):
            Z0 = L._xsec_z(L.lag_matrix(raw[sig], lag)) if sig != "resid" else m.RESZ[15]
            for orth in (False, True):
                if orth and sig == "resid":
                    continue
                Z = L.orthogonalize(Z0, m.RESZ[15]) if orth else Z0
                ic = per_date_spearman(Z, seam, elig)
                fin = np.isfinite(ic)
                if fin.sum() < 100:
                    continue
                rows.append({
                    "signal": sig, "orth": orth, "lag": lag, "n_dates": int(fin.sum()),
                    "mean_IC": float(np.nanmean(ic)),
                    "IC_t_nw": L.newey_west_t(ic, 1),
                    "pf_bp": float(np.nanmean(pf_seam[fin])),
                    "implied_gross_bp": float(np.nanmean(ic) * np.nanmean(pf_seam[fin])),
                    "cost_bp": COST_MED,
                })
    h1b = pd.DataFrame(rows).sort_values("mean_IC", key=abs, ascending=False)
    h1b["breakeven_mult"] = h1b["implied_gross_bp"].abs() / h1b["cost_bp"]
    h1b.to_csv(DATA / "tsgrid_h1b_seam_predictability.csv", index=False)
    say("H1b  cross-sectional Spearman IC of each signal against the 15:00->16:00 move:")
    say(h1b.head(12).round(4).to_string(index=False))
    say(f"     IC needed to break even on the seam: "
        f"{COST_MED / np.nanmean(pf_seam[np.isfinite(pf_seam)]):.2f}  "
        f"(cost {COST_MED:.3f} / perfect foresight "
        f"{np.nanmean(pf_seam[np.isfinite(pf_seam)]):.3f})")

    # =====================================================================  H2
    say("")
    say("=== H2  does the hour the signal is READ at matter? ===")
    s2 = pd.read_csv(DATA / "tsgrid_mark_hour_range.csv")
    real_r = s2[~s2.signal.str.startswith("PLACEBO")]
    plac_r = s2[s2.signal.str.startswith("PLACEBO")]
    say(f"mark-hour range of gross bp (entry 16:00, hold 1bd, exit 16:00):")
    say(f"  real signals excl. the richness control: max range "
        f"{real_r[real_r.signal!='resid'].gross_range_bp.max():.4f} bp "
        f"(median {real_r[real_r.signal!='resid'].gross_range_bp.median():.4f})")
    say(f"  label-permuted placebos:                max range "
        f"{plac_r.gross_range_bp.max():.4f} bp "
        f"(median {plac_r.gross_range_bp.median():.4f})")
    say(f"  the richness CONTROL:                   range "
        f"{float(real_r[real_r.signal=='resid'].gross_range_bp.iloc[0]):.4f} bp, "
        f"best at mark hour "
        f"{int(real_r[real_r.signal=='resid'].best_mark_hour.iloc[0])}")
    nbeat = int((real_r[real_r.signal != "resid"].gross_range_bp
                 > plac_r.gross_range_bp.max()).sum())
    say(f"  real signal families whose mark-hour range exceeds the widest placebo range: "
        f"{nbeat} of {len(real_r[real_r.signal!='resid'])}")

    # =====================================================================  H3
    say("")
    say("=== H3  the last business day of the month ===")
    lastbd = m.is_last_bd
    ec = m.early_close
    say(f"last business days in sample: {int(lastbd.sum())}; "
        f"of those on a SIFMA early close: {int((lastbd & ec).sum())}")
    rows = []
    windows = {"10:00->16:00": ret(10, 16), "14:00->15:00": ret(14, 15),
               "15:00->16:00": seam, "16:00->17:00": ret(16, 17)}
    prev_lastbd = np.zeros(D, bool); prev_lastbd[1:] = lastbd[:-1]
    day_sets = {"last business day": lastbd, "first bd of month": prev_lastbd,
                "all other days": ~(lastbd | prev_lastbd)}
    for wname, R in windows.items():
        el = legs.valid & np.isfinite(R)
        for dname, mask in day_sets.items():
            sub = np.where(el & mask[:, None], R, np.nan)
            xsd = np.nanstd(sub, axis=1)
            pf = L.perfect_foresight_per_date(R, el, n=3)
            rows.append({
                "window": wname, "day_set": dname,
                "dates": int(mask.sum()),
                "bond_dates": int(np.isfinite(sub).sum()),
                "mean_abs_move_bp": float(np.nanmean(np.abs(sub))),
                "xsec_sd_bp": float(np.nanmedian(xsd[mask])),
                "pf_bp": float(np.nanmean(pf[mask])),
                "pf_over_cost": float(np.nanmean(pf[mask]) / COST_MED),
            })
    h3 = pd.DataFrame(rows)
    h3.to_csv(DATA / "tsgrid_h3_month_end.csv", index=False)
    say(h3.round(4).to_string(index=False))

    # month-end signal performance, restricted to last-bd entries
    rows = []
    for sig in L.ALL_SIGNALS:
        Z0 = L._xsec_z(L.lag_matrix(raw[sig], 1)) if sig != "resid" else m.RESZ[15]
        for orth in (False, True):
            if orth and sig == "resid":
                continue
            Z = L.orthogonalize(Z0, m.RESZ[15]) if orth else Z0
            ic = per_date_spearman(Z, seam, elig)
            for dname, mask in day_sets.items():
                v = ic[mask & np.isfinite(ic)]
                if v.size < 20:
                    continue
                rows.append({"signal": sig, "orth": orth, "day_set": dname,
                             "n_dates": v.size, "mean_IC": v.mean(),
                             "t_nw": L.newey_west_t(v, 1)})
    h3s = pd.DataFrame(rows)
    h3s.to_csv(DATA / "tsgrid_h3_month_end_signal.csv", index=False)
    lb = h3s[h3s.day_set == "last business day"].reindex(
        h3s[h3s.day_set == "last business day"].mean_IC.abs().sort_values(
            ascending=False).index)
    say("  seam IC on the LAST BUSINESS DAY only (the reconstitution date):")
    say(lb.head(8).round(4).to_string(index=False))

    # =====================================================================  H4
    say("")
    say("=== H4  is any of it staleness? ===")
    stale_seam = m.STALE[16]          # 16:00 yield == 15:00 yield for that bond
    say(f"bond-dates whose 16:00 mark is EXACTLY its 15:00 mark: "
        f"{float(np.nanmean(stale_seam[elig])):.4f} of the eligible seam sample")
    rows = []
    for hh in H:
        st = m.STALE[hh]
        el = legs.valid & np.isfinite(m.Y[hh])
        prev = H[H.index(hh) - 1] if H.index(hh) > 0 else None
        R = ret(prev, hh) if prev else None
        rows.append({
            "clock_hour": hh,
            "stale_frac": float(np.nanmean(st[el])),
            "hour_pf_bp": float(np.nanmean(L.perfect_foresight_per_date(R, legs.valid & np.isfinite(R), n=3))) if R is not None else np.nan,
            "hour_mean_abs_move_bp": float(np.nanmean(np.abs(np.where(legs.valid & np.isfinite(R), R, np.nan)))) if R is not None else np.nan,
        })
    h4a = pd.DataFrame(rows)
    h4a.to_csv(DATA / "tsgrid_h4_staleness_profile.csv", index=False)
    say(h4a.round(4).to_string(index=False))
    sub = h4a.dropna()
    say(f"  corr(hourly staleness, hourly perfect-foresight pond) = "
        f"{np.corrcoef(sub.stale_frac, sub.hour_pf_bp)[0,1]:+.3f} over {len(sub)} hours")

    # signal IC split by whether the BELLY's seam print is stale
    rows = []
    for sig in L.ALL_SIGNALS:
        Z0 = L._xsec_z(L.lag_matrix(raw[sig], 1)) if sig != "resid" else m.RESZ[15]
        for orth in (False, True):
            if orth and sig == "resid":
                continue
            Z = L.orthogonalize(Z0, m.RESZ[15]) if orth else Z0
            for bucket, bmask in (("fresh belly", elig & ~stale_seam),
                                  ("stale belly", elig & stale_seam)):
                ic = per_date_spearman(Z, seam, bmask, min_n=10)
                v = ic[np.isfinite(ic)]
                if v.size < 50:
                    continue
                rows.append({"signal": sig, "orth": orth, "bucket": bucket,
                             "n_dates": v.size, "mean_IC": v.mean(),
                             "t_nw": L.newey_west_t(v, 1)})
    h4b = pd.DataFrame(rows)
    h4b.to_csv(DATA / "tsgrid_h4_signal_by_staleness.csv", index=False)
    piv = h4b.pivot_table(index=["signal", "orth"], columns="bucket",
                          values="mean_IC").round(4)
    say("  seam IC, fresh vs stale belly print:")
    say(piv.to_string())

    (DATA / "tsgrid_hypotheses.txt").write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\n[hyp] done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
