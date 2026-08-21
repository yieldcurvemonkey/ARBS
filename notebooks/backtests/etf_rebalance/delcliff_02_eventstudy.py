"""Step 2 (+ discriminators): richness-residual event study around the 20y deletion
crossing, the 10y placebo, and the AUM/ownership-scaling identification check.

Verification finding from step 1 (see delcliff_01 output / holdings_verification.csv):
TLT's par in a crossing CUSIP does NOT collapse at the nominal crossing month-end. It
declines gradually over roughly 3-6 months starting near (up to ~1 month after) the
nominal crossing, in what looks like two tranches (~1 month and ~3 months out) rather
than a single cliff. The event window here is therefore run wide: -60 to +120 business
days, not a symmetric +/-60. The +/-60 numbers are reported too, as the protocol
window, so the difference is visible rather than silently substituted.
"""
from __future__ import annotations

import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import bond_panel as BP
from RVUtils.ETFRebalance import curve as CV

OUT = BP.panel_dir()
OFFSETS = list(range(-60, 121, 1))
BASELINE_WINDOW = (-60, -45)   # business days, used as each event's own zero point


def fit_band(panel: pd.DataFrame, lo: float, hi: float) -> pd.DataFrame:
    sub = panel[panel["ttm"].between(lo, hi)].copy()
    return CV.fit_residuals(sub, x_axis="ttm", include_coupon=True, robust=True, deg=3)


def event_paths(resid: pd.DataFrame, cal: pd.DataFrame, panel_dates: np.ndarray) -> pd.DataFrame:
    """Per (cusip, event_date, offset): resid_bp at panel_dates[idx0+offset]."""
    piv = resid.pivot_table(index="date", columns="cusip", values="resid_bp")
    piv = piv.reindex(panel_dates)
    idx_of = {d: i for i, d in enumerate(panel_dates)}

    rows = []
    for r in cal.itertuples():
        ed = r.event_date
        if ed not in idx_of:
            # nearest panel date at/after
            later = panel_dates[panel_dates >= np.datetime64(ed)]
            if len(later) == 0:
                continue
            ed_eff = later[0]
        else:
            ed_eff = ed
        i0 = idx_of[ed_eff]
        if r.cusip not in piv.columns:
            continue
        col = piv[r.cusip].to_numpy()
        for off in OFFSETS:
            j = i0 + off
            if j < 0 or j >= len(panel_dates):
                continue
            rows.append({"cusip": r.cusip, "event_date": ed, "off": off,
                         "resid_bp": col[j]})
    return pd.DataFrame(rows)


def baseline_and_excess(paths: pd.DataFrame) -> pd.DataFrame:
    base = (paths[paths["off"].between(*BASELINE_WINDOW)]
            .groupby(["cusip", "event_date"])["resid_bp"].mean()
            .rename("baseline"))
    p = paths.merge(base, on=["cusip", "event_date"], how="left")
    p["excess_resid_bp"] = p["resid_bp"] - p["baseline"]
    return p


def control_path(resid: pd.DataFrame, cal: pd.DataFrame, panel_dates: np.ndarray,
                 *, lo: float, hi: float, ttm_tol: float = 2.0,
                 exclude_near_days: int = 180) -> pd.DataFrame:
    """For every event, the SAME offsets' average excess residual across bonds that are
    in the fit band, close in ttm to the event bond AT ENTRY, and not within
    ``exclude_near_days`` business days of their OWN crossing (so the control doesn't
    carry the same event). This nets out the level of the local curve fit / any
    curve-wide move on the same dates, leaving the event bond's IDIOSYNCRATIC excess.
    """
    piv = resid.pivot_table(index="date", columns="cusip", values="resid_bp")
    piv = piv.reindex(panel_dates)
    idx_of = {d: i for i, d in enumerate(panel_dates)}
    all_event_dates = {(row.cusip, row.event_date) for row in cal.itertuples()}
    # per-cusip set of all its own crossing offsets (for exclusion)
    own_events = cal.groupby("cusip")["event_date"].apply(list).to_dict()

    ttm_piv = resid.pivot_table(index="date", columns="cusip", values="ttm").reindex(panel_dates)

    rows = []
    for r in cal.itertuples():
        ed = r.event_date
        later = panel_dates[panel_dates >= np.datetime64(ed)]
        if len(later) == 0:
            continue
        ed_eff = later[0]
        i0 = idx_of[ed_eff]
        if r.cusip not in ttm_piv.columns or i0 >= len(ttm_piv):
            continue
        entry_ttm = ttm_piv.iloc[i0][r.cusip]
        if not np.isfinite(entry_ttm):
            continue
        cands = ttm_piv.columns[(ttm_piv.iloc[i0] - entry_ttm).abs() <= ttm_tol]
        cands = [c for c in cands if c != r.cusip]
        # drop candidates near their OWN crossing
        good = []
        for c in cands:
            evs = own_events.get(c, [])
            near = any(abs((ed - e).days) <= exclude_near_days * 1.45 for e in evs)
            if not near:
                good.append(c)
        if not good:
            continue
        for off in OFFSETS:
            j = i0 + off
            if j < 0 or j >= len(panel_dates):
                continue
            vals = piv.iloc[j][good].to_numpy(dtype=float)
            vals = vals[np.isfinite(vals)]
            if len(vals) == 0:
                continue
            rows.append({"cusip": r.cusip, "event_date": ed, "off": off,
                         "ctrl_resid_bp": float(np.median(vals)), "n_ctrl": len(vals)})
    return pd.DataFrame(rows)


def summarize_amplitude(excess: pd.DataFrame, *, off_lo: int, off_hi: int,
                        label: str) -> pd.DataFrame:
    """Cumulative excess-residual change from the baseline window to [off_lo, off_hi]
    (mean over that window), per event. Positive = cheapened relative to its own
    pre-event level.
    """
    e = excess[excess["off"].between(off_lo, off_hi)]
    amp = e.groupby(["cusip", "event_date"])["excess_resid_bp"].mean().rename("amp_bp").reset_index()
    amp["window"] = label
    return amp


def t_stat(x: pd.Series) -> float:
    x = x.dropna()
    if len(x) < 2:
        return np.nan
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def main():
    panel = BP.load()
    panel = panel[~panel["yield_gate_fail"]]
    panel_dates = np.array(sorted(panel["date"].unique()))

    del20 = pd.read_csv(OUT / "delcliff_deletion_calendar_20y.csv", parse_dates=["event_date"])
    del20 = del20[del20["usable_window"]]
    del10 = pd.read_csv(OUT / "delcliff_placebo_calendar_10y.csv", parse_dates=["event_date"])
    del10 = del10[del10["usable_window"]]

    print(f"20y deletion events (usable): {len(del20)}", flush=True)
    print(f"10y placebo events (usable): {len(del10)}", flush=True)

    # ---------------------------------------------------------------- 20y band fit
    print("\nfitting local curve, ttm band 15-31 ...", flush=True)
    resid20 = fit_band(panel, 15.0, 31.0)
    q = CV.residual_quality(resid20)
    print(f"residual quality (15-31y band): median autocorr1={q['autocorr_1'].median():.3f}, "
          f"median sd={q['sd_bp'].median():.2f}bp, n cusips={len(q)}", flush=True)

    paths20 = event_paths(resid20, del20, panel_dates)
    ex20 = baseline_and_excess(paths20)
    ctrl20 = control_path(resid20, del20, panel_dates, lo=15.0, hi=31.0)
    ex20 = ex20.merge(ctrl20[["cusip", "event_date", "off", "ctrl_resid_bp"]],
                       on=["cusip", "event_date", "off"], how="left")
    cbase = (ex20[ex20["off"].between(*BASELINE_WINDOW)]
             .groupby(["cusip", "event_date"])["ctrl_resid_bp"].mean().rename("ctrl_baseline"))
    ex20 = ex20.merge(cbase, on=["cusip", "event_date"], how="left")
    ex20["excess_vs_ctrl_bp"] = (ex20["resid_bp"] - ex20["baseline"]) - \
                                (ex20["ctrl_resid_bp"] - ex20["ctrl_baseline"])
    ex20.to_csv(OUT / "delcliff_event_paths_20y.csv", index=False)

    agg = ex20.groupby("off").agg(
        mean_excess=("excess_resid_bp", "mean"), median_excess=("excess_resid_bp", "median"),
        mean_vs_ctrl=("excess_vs_ctrl_bp", "mean"), median_vs_ctrl=("excess_vs_ctrl_bp", "median"),
        n=("excess_resid_bp", "count"),
    ).reset_index()
    agg.to_csv(OUT / "delcliff_event_path_agg_20y.csv", index=False)
    print("\naggregate excess residual path (20y), selected offsets (bd):", flush=True)
    print(agg[agg["off"].isin([-60, -30, -10, 0, 10, 20, 30, 45, 60, 90, 120])]
          .to_string(index=False), flush=True)

    for lo, hi, lbl in [(-1, 60, "protocol_+/-60bd"), (60, 120, "extended_+60..+120bd"),
                        (90, 120, "tail_+90..+120bd")]:
        amp = summarize_amplitude(ex20, off_lo=lo, off_hi=hi, label=lbl)
        vs = summarize_amplitude(ex20.assign(excess_resid_bp=ex20["excess_vs_ctrl_bp"]),
                                 off_lo=lo, off_hi=hi, label=lbl)
        n = amp["amp_bp"].notna().sum()
        print(f"\n[{lbl}]  raw excess: mean={amp['amp_bp'].mean():.3f}bp "
              f"median={amp['amp_bp'].median():.3f}bp t={t_stat(amp['amp_bp']):.2f} n={n}  "
              f"sign+ = {(amp['amp_bp']>0).mean()*100:.0f}%", flush=True)
        print(f"[{lbl}]  vs local-curve control: mean={vs['amp_bp'].mean():.3f}bp "
              f"median={vs['amp_bp'].median():.3f}bp t={t_stat(vs['amp_bp']):.2f} n={vs['amp_bp'].notna().sum()}  "
              f"sign+ = {(vs['amp_bp']>0).mean()*100:.0f}%", flush=True)

    amp_full = summarize_amplitude(ex20, off_lo=90, off_hi=120, label="tail")
    amp_full["year"] = amp_full["event_date"].dt.year
    print("\nper-year median amplitude (+90..+120bd raw excess, bp):", flush=True)
    print(amp_full.groupby("year")["amp_bp"].agg(["median", "count"]).to_string(), flush=True)
    amp_full.to_csv(OUT / "delcliff_amplitude_by_year_20y.csv", index=False)

    # ---------------------------------------------------------------- AUM/ownership scaling
    print("\n=== identification check: does amplitude scale with TLT ownership share? ===",
          flush=True)
    verify = pd.read_csv(OUT / "delcliff_holdings_verification.csv", parse_dates=["event_date"])
    verify["own_share"] = verify["tlt_par_pre"] / verify["free_float"]
    join = amp_full.merge(verify[["cusip", "event_date", "own_share", "tlt_par_pre"]],
                          on=["cusip", "event_date"], how="inner").dropna(subset=["own_share", "amp_bp"])
    print(f"n events with both ownership share and amplitude: {len(join)}", flush=True)
    if len(join) >= 5:
        x, y = join["own_share"].to_numpy(float), join["amp_bp"].to_numpy(float)
        corr = np.corrcoef(x, y)[0, 1]
        print(f"corr(own_share, amplitude_bp) = {corr:.3f}", flush=True)
        join["own_tercile"] = pd.qcut(join["own_share"], 3, labels=["low", "mid", "high"],
                                      duplicates="drop")
        print(join.groupby("own_tercile", observed=True)[["own_share", "amp_bp"]]
              .agg(["mean", "median", "count"]).to_string(), flush=True)
    join.to_csv(OUT / "delcliff_ownership_scaling.csv", index=False)

    # ---------------------------------------------------------------- 10y placebo
    print("\n=== 10y placebo: TLH(seller,small) -> IEF(buyer,large); flow story predicts "
          "OPPOSITE amplitude/sign vs the 20y case ===", flush=True)
    resid10 = fit_band(panel, 7.0, 13.0)
    q10 = CV.residual_quality(resid10)
    print(f"residual quality (7-13y band): median autocorr1={q10['autocorr_1'].median():.3f}, "
          f"median sd={q10['sd_bp'].median():.2f}bp, n cusips={len(q10)}", flush=True)
    paths10 = event_paths(resid10, del10, panel_dates)
    ex10 = baseline_and_excess(paths10)
    ex10.to_csv(OUT / "delcliff_event_paths_10y.csv", index=False)
    for lo, hi, lbl in [(-1, 60, "protocol_+/-60bd"), (90, 120, "tail_+90..+120bd")]:
        amp10 = summarize_amplitude(ex10, off_lo=lo, off_hi=hi, label=lbl)
        n = amp10["amp_bp"].notna().sum()
        print(f"[10y placebo {lbl}] mean={amp10['amp_bp'].mean():.3f}bp "
              f"median={amp10['amp_bp'].median():.3f}bp t={t_stat(amp10['amp_bp']):.2f} n={n}  "
              f"sign+={(amp10['amp_bp']>0).mean()*100:.0f}%", flush=True)

    print("\nwrote CSVs to", OUT)


if __name__ == "__main__":
    main()
