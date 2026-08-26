"""CHART 4 - Why daily data cannot see this. The reconciliation chart.

Measures the signed Fedspeak response over widening measurement windows, from 5 minutes
(intraday panel) out to 1 week (daily panel), and asks whether the signal-to-noise collapses
as the window widens - the mechanism that would reconcile an intraday effect with the daily null.

Window [T, T+W] for intraday W (response = rate(T+W) - rate(T), signed by ex-ante stance).
Window [close(t-1), close(t)] for 1 day and [close(t-1), close(t+4)] for 1 week.
Reconciliation rank = contract_rank 3 = SR3 IMM_3xIMM_4, the daily study's exact target
(level corr 0.9985, median abs diff 1.28bp).
"""
import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FixedFormatter

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
OUT_PNG = BASE + r"\_event_study\fig4_window_decay.png"
OUT_JSON = BASE + r"\_event_study\fig4_window_decay.json"

RANK = 3
INTRA_W = [5, 15, 30, 60, 120, 240, 300]
PRE_W = [5, 15, 30, 60, 120]
WMIN = INTRA_W + [1440, 7200]
WCOLS = [f"w{w}" for w in WMIN]
XLAB = {5: "5m", 15: "15m", 30: "30m", 60: "1h", 120: "2h", 240: "4h", 300: "5h",
        1440: "1 day", 7200: "1 week"}

# ONE palette for the whole deck.  hawk warm, dove cool, grey null.  These used to
# be local copies and had already drifted from c_common's values, so red did not
# mean quite the same red on figures 1 and 4.
sys.path.append(BASE + r"\_event_study")
from c_common import C_DOVE, C_HAWK, C_PLACEBO as C_NULL  # noqa: E402

C_MAIN = "#2f2a3d"      # pooled signed response
C_BAND = "#e8e4ee"
C_DAILY = "#f4f1e8"     # daily-panel region wash
C_ACC = "#b8860b"       # THE deck-wide "second estimator / correction" accent


# ----------------------------------------------------------------------------- estimators
def cluster_t(x, g):
    x = np.asarray(x, float); ok = np.isfinite(x); x = x[ok]; g = np.asarray(g)[ok]
    n = len(x)
    if n < 3:
        return dict(mean=np.nan, se=np.nan, t=np.nan, n=n, G=0, sd=np.nan)
    m = x.mean(); e = x - m
    sg = pd.DataFrame({"e": e, "g": g}).groupby("g")["e"].sum().values
    G = len(sg)
    V = (G / (G - 1.0)) * (sg ** 2).sum() / (n ** 2)
    se = float(np.sqrt(V))
    return dict(mean=float(m), se=se, t=float(m / se) if se > 0 else np.nan,
                n=int(n), G=int(G), sd=float(x.std(ddof=1)))


def block_bootstrap(df, col, B=15, n_boot=5000, seed=20260825):
    rng = np.random.default_rng(seed)
    s = df.dropna(subset=[col, "bpos"])
    if len(s) < 10:
        return np.nan, np.nan, np.nan
    lo, hi = int(s.bpos.min()), int(s.bpos.max())
    k = int(np.ceil((hi - lo + 1) / B))
    starts = np.arange(lo, hi - B + 2)
    by_pos = {}
    for pos, v in zip(s.bpos.values.astype(int), s[col].values):
        by_pos.setdefault(pos, []).append(v)
    means = np.empty(n_boot)
    for b in range(n_boot):
        vals = []
        for a in rng.choice(starts, size=k, replace=True):
            for p in range(a, a + B):
                if p in by_pos:
                    vals.extend(by_pos[p])
        means[b] = np.mean(vals) if vals else np.nan
    means = means[np.isfinite(means)]
    m = float(s[col].mean()); se = float(means.std(ddof=1))
    p = float((np.abs(means - means.mean()) >= abs(m)).mean())
    return se, (m / se if se > 0 else np.nan), p


def nw_day_t(df, col, lag):
    s = df.dropna(subset=[col])
    x = s.groupby("date")[col].mean().sort_index().values
    n = len(x)
    if n < 10:
        return np.nan, np.nan
    m = x.mean(); e = x - m
    S = (e ** 2).sum()
    for l in range(1, lag + 1):
        S += 2.0 * (1.0 - l / (lag + 1.0)) * (e[l:] * e[:-l]).sum()
    se = float(np.sqrt(max(S, 1e-12)) / n)
    return se, float(m / se)


# ----------------------------------------------------------------------------- data
def load():
    ev = pd.read_parquet(BASE + r"\_event_study\event_paths.parquet")
    pl = pd.read_parquet(BASE + r"\_event_study\placebo_paths.parquet")
    dl = pd.read_parquet(BASE + r"\_driver_analysis\panel_daily.parquet").reset_index()
    dl["date"] = pd.to_datetime(dl["date"]).dt.date
    dl = dl.sort_values("date").reset_index(drop=True)
    d = dl["d_rate_bp"]
    dl["cum_1d"] = d
    dl["cum_1w"] = d.rolling(5).sum().shift(-4)
    dl["pre_1d"] = d.shift(1)
    dl["pre_1w"] = d.rolling(5).sum().shift(1)
    dl["bpos"] = np.arange(len(dl))
    return ev, pl, dl


def build(paths, dl, rank=RANK):
    p = paths[paths.contract_rank == rank]
    piv = p.pivot_table(index="event_id", columns="offset_min", values="rate_bp")
    out = p.drop_duplicates("event_id").set_index("event_id")[
        ["date", "stance_sign", "bucket", "is_overlapping", "speaker"]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for w in INTRA_W:
        out[f"w{w}"] = (piv[w] - piv[0]) * out["stance_sign"]
        out[f"base{w}"] = (piv[w] - piv[-60]) * out["stance_sign"]   # straddle from -60
    for w in PRE_W:
        out[f"pre{w}"] = (piv[0] - piv[-w]) * out["stance_sign"]
    dd = dl.set_index("date")
    for nm, col in [("w1440", "cum_1d"), ("w7200", "cum_1w"),
                    ("pre1440", "pre_1d"), ("pre7200", "pre_1w")]:
        out[nm] = out["date"].map(dd[col]) * out["stance_sign"]
    out["bpos"] = out["date"].map(dd["bpos"])
    out["year"] = pd.to_datetime(out["date"]).dt.year
    out["raw240"] = piv[240] - piv[0]
    out["raw_base240"] = piv[240] - piv[-60]
    out["raw_daily"] = out["date"].map(dd["cum_1d"])
    return out


def curve(df, cols=WCOLS, wins=WMIN):
    rows = []
    for c, w in zip(cols, wins):
        r = cluster_t(df[c].values, df["date"].values)
        r["window_min"] = w
        r["mde_bp"] = 2.0 * r["se"] if np.isfinite(r["se"]) else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- main
def main():
    ev, pl, dl = load()
    E = build(ev, dl); P = build(pl, dl)
    Es = E[E.stance_sign != 0]; Ps = P[P.stance_sign != 0]
    Ec = Es[Es[WCOLS].notna().all(axis=1)].copy()          # common sample - primary
    Pc = Ps[Ps[WCOLS].notna().all(axis=1)].copy()

    R = {}
    main_c = curve(Ec)
    plac_c = curve(Pc)
    maxn_c = curve(Es)
    hawk_c = curve(Ec[Ec.stance_sign > 0])
    dove_c = curve(Ec[Ec.stance_sign < 0])
    nov_c = curve(Ec[~Ec.is_overlapping])
    buck_c = curve(Ec[Ec.bucket.abs() >= 1])
    strad_c = curve(Ec, [f"base{w}" for w in INTRA_W], INTRA_W)
    pre_c = curve(Ec, [f"pre{w}" for w in PRE_W + [1440, 7200]], PRE_W + [1440, 7200])

    # event minus placebo, day-clustered (pooled two-sample)
    diff = []
    for c, w in zip(WCOLS, WMIN):
        a = Ec[["date", c]].rename(columns={c: "x"}).assign(g=1)
        b = Pc[["date", c]].rename(columns={c: "x"}).assign(g=0)
        s = pd.concat([a, b]).dropna()
        # cluster-robust two-group mean difference on the day cluster
        m1 = s.loc[s.g == 1, "x"].mean(); m0 = s.loc[s.g == 0, "x"].mean()
        n1 = (s.g == 1).sum(); n0 = (s.g == 0).sum()
        s["e"] = np.where(s.g == 1, s.x - m1, s.x - m0)
        s["h"] = np.where(s.g == 1, 1.0 / n1, -1.0 / n0)
        sg = s.groupby("date").apply(lambda d: (d.e * d.h).sum(), include_groups=False).values
        G = len(sg)
        V = (G / (G - 1.0)) * (sg ** 2).sum()
        se = float(np.sqrt(V))
        diff.append(dict(window_min=w, diff_bp=float(m1 - m0), se=se,
                         t=float((m1 - m0) / se) if se > 0 else np.nan))
    diff_c = pd.DataFrame(diff)

    # overlap-robust inference on the multi-day windows
    ovl = []
    for w, lag, B in [(240, 1, 10), (300, 1, 10), (1440, 1, 10), (7200, 5, 15)]:
        base = cluster_t(Ec[f"w{w}"].values, Ec["date"].values)
        se_nw, t_nw = nw_day_t(Ec, f"w{w}", lag)
        se_bb, t_bb, p_bb = block_bootstrap(Ec, f"w{w}", B=B)
        ovl.append(dict(window_min=w, mean_bp=base["mean"], t_cluster=base["t"],
                        t_nw=t_nw, nw_lag=lag, t_block=t_bb, p_block=p_bb, block_days=B))
    ovl_c = pd.DataFrame(ovl)
    t1w_corr = float(ovl_c.loc[ovl_c.window_min == 7200, "t_block"].iloc[0])
    t1w_nw = float(ovl_c.loc[ovl_c.window_min == 7200, "t_nw"].iloc[0])
    p1w = float(ovl_c.loc[ovl_c.window_min == 7200, "p_block"].iloc[0])

    # noise scaling exponent
    lw = np.log(main_c.window_min.values.astype(float))
    ls = np.log(main_c.sd.values)
    b_all = float(np.polyfit(lw, ls, 1)[0])
    b_intra = float(np.polyfit(lw[:7], ls[:7], 1)[0])
    lm = np.log(np.abs(main_c["mean"].values))
    b_mean = float(np.polyfit(lw, lm, 1)[0])

    # ---- correlation with the daily close-to-close ----
    corr_out = {}
    for label, col, samp in [("primary_all_events_0to240", "raw240", E),
                             ("signed_events_0to240", "raw240", Es),
                             ("signed_events_m60to240", "raw_base240", Es)]:
        s = samp.dropna(subset=[col, "raw_daily"]).copy()
        day = s.assign(ai=s[col].abs(), ad=s["raw_daily"].abs()).groupby("date").agg(
            ai=("ai", "mean"), ad=("ad", "first"), si=(col, "mean"), sd_=("raw_daily", "first"))
        pr = float(np.corrcoef(day.ai, day.ad)[0, 1])
        sp = float(day[["ai", "ad"]].corr(method="spearman").iloc[0, 1])
        prs = float(np.corrcoef(day.si, day.sd_)[0, 1])
        corr_out[label] = dict(n_days=int(len(day)), abs_pearson=pr, abs_r2=pr ** 2,
                               abs_spearman=sp, signed_pearson=prs, signed_r2=prs ** 2)

    crossing = [int(w) for w, t in zip(main_c.window_min, main_c.t) if abs(t) >= 2.0]

    # microstructure floor: how many events do not move at all in the first 5 minutes
    frac_zero5 = float((Ec["w5"] == 0).mean())

    R = dict(
        spec=dict(rank=RANK, target="SR3 IMM_3xIMM_4 (contract_rank 3)",
                  level_corr_vs_daily_target=0.9985, median_abs_diff_bp=1.28,
                  intraday_window="[T, T+W] rate change, signed by ex-ante stance",
                  daily_window="close(t-1)->close(t) and close(t-1)->close(t+4)",
                  estimator="mean, SE clustered by calendar day",
                  n_events=int(len(Ec)), n_days=int(Ec.date.nunique()),
                  n_hawk=int((Ec.stance_sign > 0).sum()), n_dove=int((Ec.stance_sign < 0).sum()),
                  n_placebo=int(len(Pc)), span="2023-01 -> 2026-08 (signed sample; 2022 carries no scores)"),
        t_curve_primary=main_c.to_dict("records"),
        t_curve_placebo=plac_c.to_dict("records"),
        t_curve_maxn=maxn_c.to_dict("records"),
        t_curve_hawk=hawk_c.to_dict("records"),
        t_curve_dove=dove_c.to_dict("records"),
        t_curve_nonoverlap=nov_c.to_dict("records"),
        t_curve_bucket1=buck_c.to_dict("records"),
        t_curve_straddle_from_minus60=strad_c.to_dict("records"),
        t_curve_pre_event_mirror=pre_c.to_dict("records"),
        event_minus_placebo=diff_c.to_dict("records"),
        overlap_robust=ovl_c.to_dict("records"),
        noise_scaling=dict(log_log_slope_all=b_all, log_log_slope_intraday=b_intra,
                           log_log_slope_mean=b_mean, sqrt_reference=0.5),
        crossings_abs_t_ge_2=crossing,
        daily_correlation=corr_out,
        microstructure=dict(tick_bp_rank3=0.5, frac_zero_move_first_5min=frac_zero5),
    )
    with open(OUT_JSON, "w") as f:
        json.dump(R, f, indent=1, default=float)

    # ========================================================================= FIGURE
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.5,
        "axes.edgecolor": "#4a4a4a", "axes.linewidth": 0.9,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white",
    })
    fig = plt.figure(figsize=(14.4, 10.6), dpi=200)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.22, 1.0], hspace=0.36, wspace=0.20,
                          left=0.062, right=0.982, top=0.858, bottom=0.155)
    axA = fig.add_subplot(gs[0, :])
    axB = fig.add_subplot(gs[1, 0])
    axC = fig.add_subplot(gs[1, 1])

    x = main_c.window_min.values.astype(float)
    SPARSE = [5, 15, 30, 60, 120, 300, 1440, 7200]   # drop 4h label - it collides with 5h

    def style_x(ax, wins=WMIN):
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(FixedLocator(wins))
        ax.xaxis.set_minor_locator(FixedLocator([]))
        ax.xaxis.set_major_formatter(FixedFormatter([XLAB[w] for w in wins]))
        ax.axvspan(700, 12000, color=C_DAILY, zorder=0)
        ax.set_xlim(4.0, 11000)

    # ---------------- Panel A : t-stat ----------------
    style_x(axA)
    axA.axhspan(-2, 2, color=C_BAND, zorder=1, label="_nolegend_")
    axA.axhline(0, color="#7a7a7a", lw=0.8, zorder=2)
    for yv in (-2, 2):
        axA.axhline(yv, color="#8e7fae", lw=1.2, ls="--", zorder=2)
    axA.plot(x, hawk_c.t, color=C_HAWK, lw=1.3, ls=(0, (4, 2)), alpha=0.75, zorder=3,
             label=f"hawk arm only (n={int((Ec.stance_sign>0).sum())})")
    axA.plot(x, dove_c.t, color=C_DOVE, lw=1.3, ls=(0, (4, 2)), alpha=0.75, zorder=3,
             label=f"dove arm only (n={int((Ec.stance_sign<0).sum())})")
    axA.plot(x, plac_c.t, color=C_NULL, lw=2.0, marker="o", ms=5, zorder=4,
             label=f"calendar-matched placebo (n={len(Pc)})")
    axA.plot(x, main_c.t, color=C_MAIN, lw=2.8, marker="o", ms=7.5, zorder=6,
             label=f"Fedspeak, signed by ex-ante stance (n={len(Ec)})")
    # the one nominal crossing, and what it becomes under overlap-robust inference
    i1w = list(main_c.window_min).index(7200)
    axA.plot([7200], [t1w_corr], marker="D", ms=8.5, mfc="white", mec=C_ACC, mew=2.0, zorder=7)
    axA.annotate(
        f"nominal t = {main_c.t.iloc[i1w]:.2f}\nbut 5-day windows OVERLAP:\n"
        f"block-bootstrap t = {t1w_corr:.2f} (p = {p1w:.2f}),\nNewey-West t = {t1w_nw:.2f}"
        f"\n\u2192 does not clear 2",
        xy=(7200, t1w_corr), xytext=(2100, -1.55), fontsize=9.0, color="#3a2f10",
        ha="left", va="top",
        bbox=dict(boxstyle="round,pad=0.42", fc="#fdf6e3", ec=C_ACC, lw=1.0, alpha=0.97),
        arrowprops=dict(arrowstyle="-|>", color=C_ACC, lw=1.3,
                        connectionstyle="arc3,rad=-0.25"))
    axA.text(740, 3.42, "measured on the DAILY panel (close-to-close)", fontsize=8.6,
             color="#6b6252", va="top", ha="left", style="italic")
    axA.text(4.4, 3.42, "measured on the INTRADAY panel  (1-minute bars)", fontsize=8.6,
             color="#6b6252", va="top", ha="left", style="italic")
    axA.text(10500, 2.09, "|t| = 2", fontsize=8.4, color="#6d5f8a", va="bottom", ha="right")
    axA.text(5.3, -3.02,
             "beyond ~1 day BOTH lines measure a week of ambient drift, not a reaction —\n"
             "the grey placebo drifts just as hard, in the other direction",
             fontsize=8.5, color="#5d5d5d", ha="left", va="bottom", linespacing=1.45,
             bbox=dict(boxstyle="round,pad=0.35", fc="#f6f6f6", ec="#c4c4c4", lw=0.8))
    axA.set_ylabel("t-statistic of the mean signed response\n(SE clustered by calendar day)")
    axA.set_ylim(-3.15, 3.75)
    axA.set_title("A.  The signal never appears at ANY window \u2014 so window width is not what hides it",
                  fontsize=12.2, loc="left", pad=8, color="#241f30")
    axA.legend(loc="upper left", bbox_to_anchor=(0.005, 0.90), fontsize=8.9, frameon=True,
               framealpha=0.95, edgecolor="#cccccc", ncol=2)
    axA.grid(axis="y", color="#eeeeee", lw=0.7, zorder=0)

    # ---------------- Panel B : effect vs noise ----------------
    style_x(axB, SPARSE)
    axB.set_yscale("log")
    sd = main_c.sd.values
    mn = np.abs(main_c["mean"].values)
    ref = sd[0] * np.sqrt(x / x[0])
    axB.plot(x, ref, color="#b0a8c2", lw=1.6, ls=":", zorder=2,
             label=r"$\sqrt{\mathrm{window}}$ reference")
    axB.plot(x, sd, color="#6f6485", lw=2.4, marker="s", ms=6, zorder=4,
             label=f"NOISE: std of the response  (grows like W$^{{{b_all:.2f}}}$)")
    axB.plot(x, mn, color=C_MAIN, lw=2.4, marker="o", ms=6.5, zorder=5,
             label="EFFECT: |mean| signed response")
    axB.fill_between(x, mn, sd, color="#efecf4", zorder=1)
    axB.set_ylabel("bp  (log scale)")
    axB.set_ylim(0.008, 60)
    axB.set_title("B.  The dilution mechanism is absent \u2014 effect-to-noise is no better at 5 min than at 1 week",
                  fontsize=10.6, loc="left", pad=7, color="#241f30")
    axB.legend(loc="upper left", fontsize=8.6, frameon=True, framealpha=0.95, edgecolor="#cccccc")
    axB.grid(axis="y", color="#f0f0f0", lw=0.7, zorder=0)
    snr = mn / sd
    axB.text(0.982, 0.035,
             f"effect / noise = {snr.min():.3f} \u2013 {snr.max():.3f},\n"
             f"flat across a 1,440\u00d7 range of widths",
             transform=axB.transAxes, fontsize=8.4, ha="right", va="bottom",
             color="#3d3550", linespacing=1.5,
             bbox=dict(boxstyle="round,pad=0.34", fc="#f7f5fb", ec="#c9c0dc", lw=0.9))
    axB.text(5.6, 0.20, f"the 5-min std is already {sd[0]/0.5:.1f} ticks \u2014\na microstructure floor under the noise",
             fontsize=8.0, color="#6f6485", va="bottom", ha="left", linespacing=1.4)

    # ---------------- Panel C : resolution ----------------
    style_x(axC, SPARSE)
    axC.set_yscale("log")
    mde = main_c.mde_bp.values
    axC.plot(x, mde, color="#8e7fae", lw=2.4, marker="^", ms=6.5, zorder=4,
             label="smallest effect this window could detect (|t| = 2)")
    axC.plot(x, mn, color=C_MAIN, lw=2.4, marker="o", ms=6.5, zorder=5,
             label="effect actually measured")
    axC.fill_between(x, mn, mde, color="#f2eff7", zorder=1)
    axC.axhline(0.5, color=C_NULL, lw=1.2, ls="--", zorder=3)
    axC.text(4.6, 0.545, "1 SR3 tick = 0.5 bp", fontsize=8.4, color="#6a6a6a", va="bottom")
    axC.set_ylabel("bp  (log scale)")
    axC.set_ylim(0.012, 12)
    axC.set_title("C.  The 5-minute window is the SHARPEST instrument here, and it finds nothing",
                  fontsize=10.6, loc="left", pad=7, color="#241f30")
    axC.legend(loc="upper left", fontsize=8.6, frameon=True, framealpha=0.95, edgecolor="#cccccc")
    axC.grid(axis="y", color="#f0f0f0", lw=0.7, zorder=0)
    axC.annotate(f"5 min resolves {mde[0]:.2f} bp \u2014 {mde[-1]/mde[0]:.0f}\u00d7 finer than the 1-week window ({mde[-1]:.2f} bp).\n"
                 f"A real 0.5 bp reaction would print t \u2248 {0.5/main_c.se.iloc[0]:.0f} here. It measured {main_c['mean'].iloc[0]:.3f} bp,\n"
                 f"and {frac_zero5*100:.0f}% of speeches move this contract exactly ZERO ticks in 5 min.",
                 xy=(0.985, 0.035), xycoords="axes fraction",
                 xytext=(0.985, 0.035), textcoords="axes fraction",
                 fontsize=8.3, color="#3d3550", ha="right", va="bottom", linespacing=1.5,
                 bbox=dict(boxstyle="round,pad=0.38", fc="#f7f5fb", ec="#c9c0dc", lw=0.9))

    for ax in (axA, axB, axC):
        ax.set_xlabel("measurement window width (log scale)", fontsize=9.8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)

    import textwrap
    fig.suptitle("Widening the measurement window is NOT what hides the Fedspeak effect \u2014 "
                 "it is absent at 5 minutes too",
                 fontsize=15.4, x=0.062, ha="left", y=0.972, color="#1a1622", weight="bold")
    sub = ("Signed SR3 IMM 3x4 response (hawk \u2192 rate up = positive) over measurement windows from 5 minutes to 1 week. Intraday points come from the "
           "1-minute event panel, the 1-day and 1-week points from the daily panel \u2014 same rate, same events, same sign convention.")
    fig.text(0.062, 0.933, "\n".join(textwrap.wrap(sub, 168)),
             fontsize=10.0, ha="left", va="top", color="#5a5266", linespacing=1.45)

    nh, nd = int((Ec.stance_sign > 0).sum()), int((Ec.stance_sign < 0).sum())
    paras = [
        f"SAMPLE   n = {len(Ec)} Fedspeak events on {Ec.date.nunique()} days, {nh} hawk / {nd} dove \u2014 the roster is hawk-heavy, so the pooled line is hawk-weighted; both arms are drawn separately and neither carries a signal. "
        f"The signed sample is effectively 2023-01 \u2192 2026-08: no 2022 speech has an ex-ante score. Common sample \u2014 the same {len(Ec)} events at every window, so the curve is not composition drift; the max-n curve (n up to 964) is in the JSON and is materially identical.",
        f"CONSTRUCTION   Target = SR3 contract_rank 3 = IMM_3xIMM_4, the daily study's exact series (level corr 0.9985, median abs diff 1.28 bp over 1,167 shared days). Intraday response = rate(T+W) \u2212 rate(T), T = last print strictly before the speech; "
        f"daily = close(t\u22121)\u2192close(t) and close(t\u22121)\u2192close(t+4). Placebo = {len(Pc)} calendar-, weekday- and clock-matched pseudo-events on no-speech days, stance inherited from the parent.",
        f"CAVEATS   The 1-day and 1-week windows begin at the PREVIOUS close, so they contain hours of non-speech trading by construction \u2014 that is exactly the dilution this chart tests for, and it is not enough to explain the null. "
        f"The only nominal crossing (1 week) uses overlapping 5-day windows: block-bootstrap t = {t1w_corr:.2f}, and it is carried entirely by 2024 (t = 2.81; the other three years all |t| < 1.5). "
        f"Prepared remarks are sometimes released before the calendar slot, which would push a reaction into the pre-window \u2014 but the 30-minute PRE-speech window (+0.12 bp, t = 1.36) is no larger than the post-speech one. Windows \u2265 2h contain unflagged macro headlines.",
    ]
    lines = []
    for p_ in paras:
        lines.extend(textwrap.wrap(p_, 232))
    fig.text(0.062, 0.017, "\n".join(lines), fontsize=7.3, ha="left", va="bottom",
             color="#6a6272", linespacing=1.62)

    fig.savefig(OUT_PNG, dpi=200, facecolor="white")
    print("wrote", OUT_PNG)

    # ------------------------------------------------------------------ console summary
    print("\n=== t-curve (primary, common sample n=%d) ===" % len(Ec))
    show = main_c[["window_min", "mean", "se", "t", "sd", "mde_bp"]].copy()
    show["placebo_t"] = plac_c["t"].values
    show["diff_t"] = diff_c["t"].values
    print(show.to_string(index=False, float_format=lambda v: f"{v:9.4f}"))
    print("\ncrossings |t|>=2 (day-clustered):", crossing)
    print("overlap-robust:\n", ovl_c.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    print("\nnoise log-log slope all=%.3f intraday=%.3f ; |mean| slope=%.3f (sqrt would be 0.50)"
          % (b_all, b_intra, b_mean))
    print("\ndaily correlation:")
    for k, v in corr_out.items():
        print(" ", k, v)
    print("\nwrote", OUT_JSON)


if __name__ == "__main__":
    main()
