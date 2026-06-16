"""SFR butterfly 'fade-the-kink' backtest — naive vs implied-distribution.

Reads two panels:
  butterfly_curve_panel.parquet   — full year: bf_bps, rates, FOMC (forward-return
                                     target + naive signal). Master table.
  butterfly_rv_backfill.parquet   — options signals (adj_signal etc.), joined on
                                     (date, fly_id). May be partial; coverage printed.

Core question: does the options-implied variance signal predict subsequent
butterfly normalization BETTER than naively fading by fly magnitude — net of the
fly level itself (additive?) and net of costs? We TEST the sign, not assume it.

Methodology notes:
 * Forward Δfly built on the curve panel via a global business-day ordinal, so
   Δfly at t+h is the SAME fixed-contract fly h biz days later (NaN if rolled off).
 * Cross-gap scale differs ~20x (12mo flies vs 3mo), so the primary analyses are
   WITHIN-GAP: rank/standardize inside each maturity bucket, then pool. This is the
   fair RV question ("which fly in this bucket is rich?").
 * "Fade" position = -sign(signal)*Δfly: high signal => expected to FALL (sell).
"""
import sys, math
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DIR = r"C:\Users\chris\clee\ARBS\notebooks\backtests\SFR_screeners"
CURVE_PANEL = DIR + r"\butterfly_curve_panel.parquet"
OPT_PANEL = DIR + r"\butterfly_rv_backfill.parquet"
HORIZONS = [5, 21, 63]
GAPS = ["3mo", "6mo", "9mo", "12mo"]


# ──────────────────────────────────────────────────────────────────────────────
def load_panels(verbose=True):
    curve = pd.read_parquet(CURVE_PANEL)
    curve["date"] = pd.to_datetime(curve["date"])
    dates = sorted(curve["date"].unique())
    ordmap = {d: i for i, d in enumerate(dates)}
    curve["bd"] = curve["date"].map(ordmap)

    for h in HORIZONS:
        fwd = curve[["fly_id", "bd", "bf_bps"]].rename(
            columns={"bd": "bd_f", "bf_bps": f"bf_fwd_{h}"})
        curve["bd_t"] = curve["bd"] + h
        curve = curve.merge(fwd, left_on=["fly_id", "bd_t"],
                            right_on=["fly_id", "bd_f"], how="left")
        curve[f"dfly_{h}"] = curve[f"bf_fwd_{h}"] - curve["bf_bps"]
        curve = curve.drop(columns=["bd_t", "bd_f"])

    panel = curve
    try:
        opt = pd.read_parquet(OPT_PANEL)
        opt["date"] = pd.to_datetime(opt["date"])
        keep = ["date", "fly_id", "std_excess", "std_excess_adj", "var_signal",
                "var_signal_adj", "kink_width_ratio", "fragility", "near_dead",
                "near_expiry_distorted", "tte_imbalanced", "std_near", "std_mid",
                "std_far", "mid_std_bps", "skew_near", "skew_mid", "skew_far"]
        opt = opt[[c for c in keep if c in opt.columns]].drop_duplicates(["date", "fly_id"])
        panel = curve.merge(opt, on=["date", "fly_id"], how="left")
        # higher-moment "curvature of skew" signal: mid skew vs wing interpolation
        if {"skew_near", "skew_mid", "skew_far"}.issubset(panel.columns):
            panel["skew_excess"] = panel["skew_mid"] - 0.5 * (panel["skew_near"] + panel["skew_far"])
    except FileNotFoundError:
        pass

    has_opt = "var_signal_adj" in panel.columns and panel["var_signal_adj"].notna().any()
    if verbose:
        print(f"Panel: {panel.shape[0]} rows, {panel['date'].nunique()} dates "
              f"({dates[0].date()}..{dates[-1].date()}), {panel['fly_id'].nunique()} flies")
        if has_opt:
            sig = panel["var_signal_adj"].notna()
            print(f"Options coverage: {sig.sum()} rows / {panel['date'][sig].nunique()} dates "
                  f"({panel['date'][sig].min().date()}..{panel['date'][sig].max().date()})")
        else:
            print("Options coverage: none yet (naive-only)")
    return panel, dates, has_opt


# ── IC machinery ──────────────────────────────────────────────────────────────
def xs_ic(panel, sig, h, mask=None, min_names=5, within_gap=False):
    """Mean per-date cross-sectional Spearman IC of `sig` vs forward Δfly.
    within_gap: compute inside each (date,gap) cell and n-weight-average per date."""
    df = panel if mask is None else panel[mask]
    df = df.dropna(subset=[sig, f"dfly_{h}"])
    ics = []
    for d, g in df.groupby("date"):
        if within_gap:
            cell_ics, cell_ns = [], []
            for gap, gg in g.groupby("gap"):
                if len(gg) < 3 or gg[sig].nunique() < 3:
                    continue
                ic = spearmanr(gg[sig], gg[f"dfly_{h}"]).correlation
                if np.isfinite(ic):
                    cell_ics.append(ic); cell_ns.append(len(gg))
            if cell_ics:
                ics.append(np.average(cell_ics, weights=cell_ns))
        else:
            if len(g) < min_names or g[sig].nunique() < 3:
                continue
            ic = spearmanr(g[sig], g[f"dfly_{h}"]).correlation
            if np.isfinite(ic):
                ics.append(ic)
    ics = np.array(ics)
    if len(ics) < 2:
        return dict(mean=np.nan, t=np.nan, n=len(ics), hit=np.nan)
    return dict(mean=ics.mean(), t=ics.mean() / (ics.std(ddof=1) + 1e-12) * math.sqrt(len(ics)),
                n=len(ics), hit=(ics > 0).mean())


def pooled_ic(panel, sig, h, mask=None):
    df = panel if mask is None else panel[mask]
    df = df.dropna(subset=[sig, f"dfly_{h}"])
    if len(df) < 20 or df[sig].nunique() < 5:
        return dict(rho=np.nan, n=len(df))
    return dict(rho=spearmanr(df[sig], df[f"dfly_{h}"]).correlation, n=len(df))


def zwithin(df, col, by):
    g = df.groupby(by)[col]
    return (df[col] - g.transform("mean")) / (g.transform("std") + 1e-12)


def nw_t(x, lag):
    """Newey-West t-stat of the mean of series x (lag for overlapping h-day returns)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return np.nan
    e = x - x.mean()
    var = (e @ e) / n
    for l in range(1, min(lag, n - 1) + 1):
        w = 1 - l / (lag + 1)
        var += 2 * w * (e[l:] @ e[:-l]) / n
    return x.mean() / (math.sqrt(var / n) + 1e-12)


def fama_macbeth(panel, h, extra_sig="var_signal_adj", mask=None):
    """Per-date cross-sectional regression dfly_z ~ bf_z + extra_z (standardized
    WITHIN gap on that date), collect the extra-signal coefficient each date, then
    t-stat across dates with Newey-West(lag=h) to honour overlapping forward returns.
    This is the rigorous 'does options add beyond level?' test (n = #dates dof)."""
    need = ["bf_bps", extra_sig, f"dfly_{h}", "gap", "date"]
    df = panel if mask is None else panel[mask]
    df = df.dropna(subset=need).copy()
    b_ex, b_bf = [], []
    for d, g in df.groupby("date"):
        g = g.copy()
        g["y"] = zwithin(g, f"dfly_{h}", "gap")
        g["xb"] = zwithin(g, "bf_bps", "gap")
        g["xe"] = zwithin(g, extra_sig, "gap")
        g = g[np.isfinite(g["y"]) & np.isfinite(g["xb"]) & np.isfinite(g["xe"])]
        if len(g) < 6 or g["xe"].std() < 1e-9:
            continue
        X = np.column_stack([np.ones(len(g)), g["xb"].values, g["xe"].values])
        try:
            beta, *_ = np.linalg.lstsq(X, g["y"].values, rcond=None)
        except Exception:
            continue
        b_bf.append(beta[1]); b_ex.append(beta[2])
    if len(b_ex) < 5:
        return None
    return dict(n=len(b_ex), b_ex=np.mean(b_ex), t_ex=nw_t(b_ex, h),
                b_bf=np.mean(b_bf), t_bf=nw_t(b_bf, h))


def marginal_reg(panel, h, extra_sig="var_signal_adj", demean_date_gap=False, mask=None):
    """Pooled OLS dfly_z ~ bf_z + extra_z, standardized within gap (+optional
    within date×gap demeaning = pure cross-sectional). Returns betas + t-stats."""
    need = ["bf_bps", extra_sig, f"dfly_{h}", "gap", "date"]
    df = panel if mask is None else panel[mask]
    df = df.dropna(subset=need).copy()
    if len(df) < 40:
        return None
    by = ["date", "gap"] if demean_date_gap else "gap"
    df["y"] = zwithin(df, f"dfly_{h}", by)
    df["x_bf"] = zwithin(df, "bf_bps", by)
    df["x_ex"] = zwithin(df, extra_sig, by)
    df = df.dropna(subset=["y", "x_bf", "x_ex"])
    df = df[np.isfinite(df["x_ex"]) & np.isfinite(df["x_bf"]) & np.isfinite(df["y"])]
    if len(df) < 40:
        return None
    X = np.column_stack([np.ones(len(df)), df["x_bf"].values, df["x_ex"].values])
    y = df["y"].values
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(df) - 3, 1)
    se = np.sqrt(np.diag((resid @ resid) / dof * np.linalg.inv(X.T @ X)))
    return dict(n=len(df), b_bf=beta[1], t_bf=beta[1] / se[1],
                b_ex=beta[2], t_ex=beta[2] / se[2],
                r2=1 - (resid @ resid) / (((y - y.mean()) ** 2).sum() + 1e-12))


# ── Long-short fade ───────────────────────────────────────────────────────────
def ls_fade(panel, sig, h, mask=None, frac=0.33, within_gap=True, frag_weight=False,
            min_names=6, cost_bps=0.0, min_fly_bps=0.0):
    """Daily cross-sectional fade: short top-frac signal (rich), long bottom (cheap).
    within_gap=True ranks inside each maturity bucket then sums (gap-neutral).
    Returns per-date P&L (bps of fly) + annualized stats (252 biz days)."""
    df = panel if mask is None else panel[mask]
    df = df.dropna(subset=[sig, f"dfly_{h}"]).copy()
    if min_fly_bps > 0:
        df = df[df["bf_bps"].abs() >= min_fly_bps]

    def one_book(g):
        if len(g) < 3 or g[sig].nunique() < 3:
            return None
        k = max(1, int(len(g) * frac))
        order = g[sig].rank(method="first")
        longs = g[order <= k]; shorts = g[order > len(g) - k]
        wl = np.ones(len(longs)); ws = np.ones(len(shorts))
        if frag_weight and "fragility" in g.columns:
            wl = 1.0 / (1.0 + longs["fragility"].fillna(0.3).values)
            ws = 1.0 / (1.0 + shorts["fragility"].fillna(0.3).values)
        wl, ws = wl / wl.sum(), ws / ws.sum()
        return (wl * longs[f"dfly_{h}"].values).sum() - (ws * shorts[f"dfly_{h}"].values).sum()

    recs = []
    for d, g in df.groupby("date"):
        if within_gap:
            books = [one_book(gg) for _, gg in g.groupby("gap")]
            books = [b for b in books if b is not None]
            if not books:
                continue
            pnl = float(np.mean(books))
        else:
            if len(g) < min_names:
                continue
            pnl = one_book(g)
            if pnl is None:
                continue
        recs.append(dict(date=d, pnl=pnl - cost_bps * 2.0))
    if len(recs) < 3:
        return None
    s = pd.DataFrame(recs).set_index("date").sort_index()
    ppy = 252.0 / h
    nonover = s.iloc[::h]
    mean = s["pnl"].mean()
    sd = nonover["pnl"].std(ddof=1) if len(nonover) > 2 else s["pnl"].std(ddof=1)
    cum = s["pnl"].cumsum()
    return dict(series=s, n=len(s), mean=mean, ir=mean * ppy / (sd * math.sqrt(ppy) + 1e-12),
                hit=(s["pnl"] > 0).mean(), maxdd=(cum - cum.cummax()).min(),
                nonover=(nonover["pnl"].mean() / (nonover["pnl"].std(ddof=1) + 1e-12) * math.sqrt(ppy)) if len(nonover) > 2 else np.nan)


# ── Report ────────────────────────────────────────────────────────────────────
def report(panel, has_opt):
    print("\n" + "=" * 88)
    print("1. IS THE FLY MEAN-REVERTING?  within-gap xs-IC( bf_level , Δfly )  (want NEG)")
    print("=" * 88)
    for h in HORIZONS:
        ic = xs_ic(panel, "bf_bps", h, within_gap=True)
        print(f"  h={h:>2}d: IC={ic['mean']:+.3f} (t={ic['t']:+.2f}, n_dates={ic['n']}, "
              f"hit={ic['hit']:.0%})")

    if not has_opt:
        print("\n[options panel thin — running naive-only sections]")
    print("\n" + "=" * 88)
    print("2. NAIVE LONG-SHORT FADE (rank bf within gap, gap-neutral)  — the baseline")
    print("=" * 88)
    for h in HORIZONS:
        r = ls_fade(panel, "bf_bps", h, within_gap=True)
        if r:
            print(f"  h={h:>2}d: IR={r['ir']:+.2f} (nonover Sh={r['nonover']:+.2f}) "
                  f"mean={r['mean']:+.2f}bps hit={r['hit']:.0%} maxDD={r['maxdd']:+.1f} n={r['n']}")
    if not has_opt:
        return

    print("\n" + "=" * 88)
    print("3. OPTIONS SIGNALS — within-gap xs-IC vs Δfly  (fade wants NEG; sign as-is)")
    print("=" * 88)
    sigs = {"adj_signal (var_signal_adj)": "var_signal_adj",
            "adj_excess  (std_excess_adj)": "std_excess_adj",
            "raw var_signal": "var_signal",
            "skew_excess (mid-wings)": "skew_excess",
            "skew_mid": "skew_mid"}
    for name, col in sigs.items():
        if col not in panel.columns:
            continue
        row = f"  {name:<30}: "
        for h in HORIZONS:
            ic = xs_ic(panel, col, h, within_gap=True)
            row += f"h{h}={ic['mean']:+.3f}(t{ic['t']:+.1f}) " if np.isfinite(ic['mean']) else f"h{h}=n/a "
        print(row)

    print("\n" + "=" * 88)
    print("4. ★ ADDITIVITY — does options info beat the fly LEVEL?  (Fama-MacBeth, honest)")
    print("   per-date xs regression dfly_z ~ bf_z + signal_z (within gap); t = NW(lag=h)")
    print("   across dates. options adds iff t_signal stays large with right (NEG) sign.")
    print("=" * 88)
    for ex_name, ex in [("adj_signal", "var_signal_adj"), ("adj_excess", "std_excess_adj"),
                        ("raw var_signal", "var_signal"), ("skew_excess", "skew_excess")]:
        if ex not in panel.columns:
            continue
        row = f"  {ex_name:<16}: "
        for h in HORIZONS:
            fm = fama_macbeth(panel, h, extra_sig=ex)
            row += (f"h{h}: β={fm['b_ex']:+.3f} t={fm['t_ex']:+.1f} (bf t={fm['t_bf']:+.1f}) | "
                    if fm else f"h{h}: n/a | ")
        print(row)
    print("  GAP-FLIES ONLY (6/9/12mo — where the convexity link lives; 3mo excluded):")
    gapmask = panel["gap"].isin(["6mo", "9mo", "12mo"])
    for ex_name, ex in [("adj_signal", "var_signal_adj"), ("adj_excess", "std_excess_adj")]:
        if ex not in panel.columns:
            continue
        row = f"    {ex_name:<14}: "
        for h in HORIZONS:
            fm = fama_macbeth(panel, h, extra_sig=ex, mask=gapmask)
            row += (f"h{h}: β={fm['b_ex']:+.3f} t={fm['t_ex']:+.1f} | " if fm else f"h{h}: n/a | ")
        print(row)
    print("  (reference — pooled OLS, t inflated by pseudo-replication, for contrast:)")
    for ex_name, ex in [("adj_signal", "var_signal_adj")]:
        for h in HORIZONS:
            r = marginal_reg(panel, h, extra_sig=ex)
            if r:
                print(f"    pooled h={h:>2}d: β_adj={r['b_ex']:+.3f} (t={r['t_ex']:+.1f}, "
                      f"inflated)  β_bf={r['b_bf']:+.3f}")

    # entanglement: how correlated is adj_signal with the fly level/magnitude?
    sub = panel.dropna(subset=["var_signal_adj", "bf_bps"])
    if len(sub) > 50:
        c_signed = spearmanr(sub["var_signal_adj"], sub["bf_bps"]).correlation
        c_mag = spearmanr(sub["var_signal_adj"], sub["bf_bps"].abs()).correlation
        print(f"\n  entanglement: ρ(adj_signal, bf)={c_signed:+.2f}, "
              f"ρ(adj_signal, |bf|)={c_mag:+.2f}  (adj_signal = std_excess_adj/|bf|)")

    print("\n" + "=" * 88)
    print("5. BUCKETED predictive power of adj_signal  (pooled-ρ; fade wants NEG)")
    print("=" * 88)
    print("  by GAP:")
    for gap in GAPS:
        m = panel["gap"] == gap
        row = f"    {gap:>4}: "
        for h in HORIZONS:
            p = pooled_ic(panel, "var_signal_adj", h, mask=m)
            row += f"h{h}={p['rho']:+.3f}(n{p['n']}) " if np.isfinite(p['rho']) else f"h{h}=n/a "
        print(row)
    print("  by FOMC gap-window symmetry:")
    for lab, m in [("symmetric", panel["fomc_asym"] == 0), ("asymmetric", panel["fomc_asym"] >= 1)]:
        row = f"    {lab:>10}: "
        for h in HORIZONS:
            p = pooled_ic(panel, "var_signal_adj", h, mask=m)
            row += f"h{h}={p['rho']:+.3f}(n{p['n']}) " if np.isfinite(p['rho']) else f"h{h}=n/a "
        print(row)

    print("\n" + "=" * 88)
    print("6. OPTIONS LONG-SHORT FADE (adj_signal, within gap)  vs naive  + gate ablation")
    print("=" * 88)
    for name, col in [("naive_bf", "bf_bps"), ("adj_signal", "var_signal_adj")]:
        for h in HORIZONS:
            r = ls_fade(panel, col, h, within_gap=True)
            if r:
                print(f"  {name:<10} h={h:>2}d: IR={r['ir']:+.2f} (nonover {r['nonover']:+.2f}) "
                      f"mean={r['mean']:+.2f}bps hit={r['hit']:.0%} n={r['n']}")
    print("\n  Gate ablation (adj_signal, h=21, within gap):")
    for lab, kw in [("raw", {}), ("+frag_weight", dict(frag_weight=True)),
                    ("+excl_near_dead", dict(mask=~panel["near_dead"].fillna(False).astype(bool))),
                    ("+min_fly_1bp", dict(min_fly_bps=1.0)),
                    ("+symmetric_FOMC", dict(mask=panel["fomc_asym"] == 0)),
                    ("+cost_0.75bp", dict(cost_bps=0.75))]:
        r = ls_fade(panel, "var_signal_adj", 21, within_gap=True, **kw)
        print(f"    {lab:>16}: IR={r['ir']:+.2f} mean={r['mean']:+.2f}bps hit={r['hit']:.0%} n={r['n']}"
              if r else f"    {lab:>16}: insufficient")


def make_charts(panel):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 2, figsize=(15, 10))

    # (1) cumulative P&L: naive vs adj_signal at h=21 (within-gap, gap-neutral)
    # restrict BOTH to the common options-covered window for a fair head-to-head.
    h = 21
    osig = panel["var_signal_adj"].notna()
    d0, d1 = panel["date"][osig].min(), panel["date"][osig].max()
    common = (panel["date"] >= d0) & (panel["date"] <= d1)
    nai = ls_fade(panel, "bf_bps", h, within_gap=True, mask=common)
    adj = ls_fade(panel, "var_signal_adj", h, within_gap=True)
    a = ax[0, 0]
    if nai:
        a.plot(nai["series"].index, nai["series"]["pnl"].cumsum(), label=f"naive bf  IR={nai['ir']:+.2f}", lw=1.8)
    if adj:
        a.plot(adj["series"].index, adj["series"]["pnl"].cumsum(), label=f"adj_signal  IR={adj['ir']:+.2f}", lw=1.8)
    a.set_title(f"Cumulative fade P&L (h={h}d, within-gap L/S tercile, common window)\noverlapping; bps of fly")
    a.legend(); a.grid(alpha=0.3); a.axhline(0, color="k", lw=0.6)

    # (2) bucketed pooled-rho of adj_signal by gap x horizon
    a = ax[0, 1]
    x = np.arange(len(GAPS)); w = 0.25
    for j, hh in enumerate(HORIZONS):
        vals = [pooled_ic(panel, "var_signal_adj", hh, mask=panel["gap"] == g)["rho"] for g in GAPS]
        a.bar(x + (j - 1) * w, vals, w, label=f"h={hh}d")
    a.set_xticks(x); a.set_xticklabels(GAPS); a.axhline(0, color="k", lw=0.6)
    a.set_title("adj_signal predictive ρ vs Δfly by GAP\n(neg = fade works; theory: stronger in long gaps)")
    a.legend(); a.grid(alpha=0.3, axis="y")

    # (3) honest FM t vs inflated pooled t (adj_signal)
    a = ax[1, 0]
    fm_t = [(fama_macbeth(panel, hh, "var_signal_adj") or {}).get("t_ex", np.nan) for hh in HORIZONS]
    pl_t = [(marginal_reg(panel, hh, "var_signal_adj") or {}).get("t_ex", np.nan) for hh in HORIZONS]
    x = np.arange(len(HORIZONS))
    a.bar(x - 0.2, pl_t, 0.4, label="pooled OLS t (inflated)", color="lightcoral")
    a.bar(x + 0.2, fm_t, 0.4, label="Fama-MacBeth NW t (honest)", color="steelblue")
    for s in (1.96, -1.96):
        a.axhline(s, color="gray", ls="--", lw=0.8)
    a.set_xticks(x); a.set_xticklabels([f"h={hh}d" for hh in HORIZONS]); a.axhline(0, color="k", lw=0.6)
    a.set_title("Additivity t-stat of adj_signal beyond fly level\nhonest (blue) vs pseudo-replication-inflated (red)")
    a.legend(); a.grid(alpha=0.3, axis="y")

    # (4) mean reversion: within-gap z(bf) vs z(dfly_21)
    a = ax[1, 1]
    df = panel.dropna(subset=["bf_bps", "dfly_21"]).copy()
    df["zbf"] = zwithin(df, "bf_bps", "gap"); df["zdf"] = zwithin(df, "dfly_21", "gap")
    df = df[np.isfinite(df["zbf"]) & np.isfinite(df["zdf"])]
    a.scatter(df["zbf"], df["zdf"], s=4, alpha=0.15, color="navy")
    b1, b0 = np.polyfit(df["zbf"], df["zdf"], 1)
    xs = np.linspace(df["zbf"].quantile(0.01), df["zbf"].quantile(0.99), 50)
    a.plot(xs, b0 + b1 * xs, color="red", lw=2, label=f"slope={b1:+.2f}")
    a.set_xlabel("z(fly level) within gap"); a.set_ylabel("z(forward Δfly, 21d)")
    a.set_title("Fly mean reversion (the dominant effect)\nnegative slope = high fly falls")
    a.legend(); a.grid(alpha=0.3)

    fig.suptitle(f"SFR kink-fade backtest — naive vs implied-distribution  "
                 f"({panel['date'][panel['var_signal_adj'].notna()].nunique()} options dates)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = DIR + r"\kink_fade_framework_results.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"  saved {out}")


if __name__ == "__main__":
    import sys as _sys
    panel, dates, has_opt = load_panels()
    if "--charts" in _sys.argv:
        make_charts(panel)
    else:
        report(panel, has_opt)
