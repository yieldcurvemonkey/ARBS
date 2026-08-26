"""
CHART 2 -- response across the SR3 strip.

Estimators, all on signed_d_bp (>0 = rate moved the way the ex-ante stance predicted):

  pooled_real[r]  = mean over all signed events (77% hawk / 23% dove)
  pooled_plac[r]  = same on the time-of-day + calendar-proximity matched placebo book
  pooled_excess   = pooled_real - pooled_plac
  hawk_excess[r]  = mean_hawk(real) - mean_hawk(placebo)
  dove_excess[r]  = mean_dove(real) - mean_dove(placebo)
  DiD[r]          = 0.5*(hawk_excess + dove_excess)      <- arm-balanced difference-in-differences
  delta[r]        = 0.5*(hawk_excess - dove_excess)      <- UNSIGNED drift gap, speech day minus quiet day

  Identity: pooled_excess = w_h*hawk_excess + w_d*dove_excess = DiD + (w_h - w_d)*delta,
  so with w_h ~ 0.77 the pooled number carries +0.54*delta of pure drift-gap contamination.
  DiD cancels any level drift that hits both arms; it is the shape-decisive estimator.

Bootstrap: ONE shared resample of distinct calendar DATES per book (multinomial weights),
reused across every rank, offset, estimator and contrast, so rank contrasts pair tightly.
Real and placebo date universes are disjoint by construction (placebo days have no Fed
calendar entry), so the two books are resampled independently.
"""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
RANKS = [1, 2, 3, 4, 5]
OFFSETS = [30, 240]
REPS = 10000
SEED = 20260825

sys.path.append(BASE)
# ONE palette for the whole deck.  Three local copies had already drifted into
# three hawk-reds, three dove-blues and three greys; these now come from c_common
# so red always means hawk and blue always means dove on every figure.
from c_common import C_DOVE, C_HAWK, C_PLACEBO as C_PLAC  # noqa: E402

C_REAL = "#7b1f1f"      # pooled REAL line - a darker shade of the hawk family
C_DID = "#1a1a1a"       # the drift-immune estimator - ink, not a stance colour
C_DELTA = "#7d6608"     # the unsigned drift gap
C_ACC = "#b8860b"       # THE deck-wide "second estimator / correction" accent
C_CLEAN = "#0f7b6c"     # release-free subset

# the corrected numbers, computed once in c5_fixes.py
FIX = json.load(open(BASE + r"\c5_fixes.json"))

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 100)


# ----------------------------------------------------------------------------- data
def load(cutname):
    ev = pd.read_parquet(BASE + r"\event_paths.parquet")
    pl = pd.read_parquet(BASE + r"\placebo_paths.parquet")
    out = {}
    for book, df in (("real", ev), ("plac", pl)):
        d = df[df["offset_min"].isin(OFFSETS)
               & df["signed_d_bp"].notna()
               & (df["stance_sign"] != 0)].copy()
        if cutname == "clean" and book == "real":
            d = d[~d["is_overlapping"]]
        if cutname == "bucket":
            d = d[d["bucket"].abs() >= 1]
        if cutname == "nomacro":
            d = d[~d["is_cpi_day"] & ~d["is_nfp_day"]]
        if cutname == "notariff":
            # 2025-04-09 is the 90-day tariff-pause announcement (~13:18 ET). It carries the single
            # largest signed move in the panel (+29.5bp at +240) and NO calendar column flags it, so
            # it survives every other cut. Drop the whole day from both books.
            d = d[d["date"].astype(str) != "2025-04-09"]
        out[book] = d[["date", "event_id", "stance_sign", "contract_rank",
                       "offset_min", "signed_d_bp", "d_rate_bp_from_baseline"]]
    return out


def build_cells(d):
    """S[arm][offset] and N[arm][offset]: (n_days, 5) sums and counts of signed_d_bp."""
    days = np.array(sorted(d["date"].unique()))
    dix = {v: i for i, v in enumerate(days)}
    S, N = {}, {}
    for arm, sgn in (("h", 1), ("d", -1)):
        for off in OFFSETS:
            s = np.zeros((len(days), 5))
            n = np.zeros((len(days), 5))
            sub = d[(d["stance_sign"] == sgn) & (d["offset_min"] == off)]
            di = sub["date"].map(dix).to_numpy()
            ri = sub["contract_rank"].to_numpy() - 1
            np.add.at(s, (di, ri), sub["signed_d_bp"].to_numpy())
            np.add.at(n, (di, ri), 1.0)
            S[(arm, off)] = s
            N[(arm, off)] = n
    return days, S, N


def stats_from_weights(W, S, N):
    """W: (reps, n_days) weights (or (1,n_days) of ones for the point estimate).
    Returns dict[(kind, arm/'pool', off)] -> (reps, 5) means."""
    out = {}
    for off in OFFSETS:
        sh, nh = W @ S[("h", off)], W @ N[("h", off)]
        sd, nd = W @ S[("d", off)], W @ N[("d", off)]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[("h", off)] = np.where(nh > 0, sh / np.maximum(nh, 1e-12), np.nan)
            out[("d", off)] = np.where(nd > 0, sd / np.maximum(nd, 1e-12), np.nan)
            tot = nh + nd
            out[("pool", off)] = np.where(tot > 0, (sh + sd) / np.maximum(tot, 1e-12), np.nan)
        out[("nh", off)] = nh
        out[("nd", off)] = nd
    return out


def run(cutname, reps=REPS, seed=SEED, verbose=True):
    books = load(cutname)
    days_r, Sr, Nr = build_cells(books["real"])
    days_p, Sp, Np = build_cells(books["plac"])
    assert len(set(days_r) & set(days_p)) == 0, "real and placebo date universes overlap"

    rng = np.random.default_rng(seed)
    Wr = rng.multinomial(len(days_r), np.full(len(days_r), 1.0 / len(days_r)), size=reps).astype(np.float64)
    Wp = rng.multinomial(len(days_p), np.full(len(days_p), 1.0 / len(days_p)), size=reps).astype(np.float64)
    W1r = np.ones((1, len(days_r)))
    W1p = np.ones((1, len(days_p)))

    pt_r = stats_from_weights(W1r, Sr, Nr)
    pt_p = stats_from_weights(W1p, Sp, Np)
    bs_r = stats_from_weights(Wr, Sr, Nr)
    bs_p = stats_from_weights(Wp, Sp, Np)

    def derive(R, P):
        d = {}
        for off in OFFSETS:
            hx = R[("h", off)] - P[("h", off)]
            dx = R[("d", off)] - P[("d", off)]
            d[("real_pool", off)] = R[("pool", off)]
            d[("plac_pool", off)] = P[("pool", off)]
            d[("pooled_excess", off)] = R[("pool", off)] - P[("pool", off)]
            d[("hawk_excess", off)] = hx
            d[("dove_excess", off)] = dx
            d[("DiD", off)] = 0.5 * (hx + dx)
            d[("delta", off)] = 0.5 * (hx - dx)
            d[("real_hawk", off)] = R[("h", off)]
            d[("real_dove", off)] = P[("h", off)] * 0 + R[("d", off)]
            d[("plac_hawk", off)] = P[("h", off)]
            d[("plac_dove", off)] = P[("d", off)]
        return d

    pt = derive(pt_r, pt_p)
    bs = derive(bs_r, bs_p)

    bad = np.isnan(bs[("DiD", 240)]).any(axis=1).sum()
    if verbose:
        print(f"[{cutname}] real days={len(days_r)} placebo days={len(days_p)} reps={reps} "
              f"bootstrap draws with an empty arm: {bad}")

    res = {}
    for key, arr in pt.items():
        name, off = key
        b = bs[key]
        lo = np.nanpercentile(b, 2.5, axis=0)
        hi = np.nanpercentile(b, 97.5, axis=0)
        res[key] = dict(pt=arr[0], lo=lo, hi=hi,
                        p2=2 * min((b <= 0).mean(), (b >= 0).mean()) if False else None)
    # two-sided bootstrap p per rank for the excess-style quantities
    for key in list(bs.keys()):
        b = bs[key]
        pv = 2.0 * np.minimum(np.nanmean(b <= 0, axis=0), np.nanmean(b >= 0, axis=0))
        res[key]["p"] = np.clip(pv, 1.0 / reps, 1.0)

    # ---- shape contrasts, paired across ranks within the same resample
    contrasts = {}
    for off in OFFSETS:
        for nm in ("pooled_excess", "DiD", "real_pool"):
            b = bs[(nm, off)]
            p = pt[(nm, off)][0]
            for cname, f in (
                ("front_minus_back_r1_r5", lambda x: x[..., 0] - x[..., 4]),
                ("hump_r3_vs_mid_r1r5", lambda x: x[..., 2] - 0.5 * (x[..., 0] + x[..., 4])),
                ("r3_minus_r1", lambda x: x[..., 2] - x[..., 0]),
            ):
                bb = f(b)
                contrasts[(nm, off, cname)] = dict(
                    pt=float(f(p)),
                    lo=float(np.nanpercentile(bb, 2.5)),
                    hi=float(np.nanpercentile(bb, 97.5)),
                    p=float(np.clip(2.0 * min(np.nanmean(bb <= 0), np.nanmean(bb >= 0)), 1.0 / reps, 1.0)),
                )
    counts = {}
    for off in OFFSETS:
        counts[("real", off)] = (pt_r[("nh", off)][0], pt_r[("nd", off)][0])
        counts[("plac", off)] = (pt_p[("nh", off)][0], pt_p[("nd", off)][0])
    return res, contrasts, counts, len(days_r), len(days_p), books


# ----------------------------------------------------------------------------- report
def fmt(res, key):
    r = res[key]
    return " ".join(f"{r['pt'][i]:+.3f}[{r['lo'][i]:+.3f},{r['hi'][i]:+.3f}]" for i in range(5))


def table(res, off, cutname):
    rows = []
    for i, rk in enumerate(RANKS):
        row = {"rank": rk}
        for nm in ("real_pool", "plac_pool", "pooled_excess", "hawk_excess", "dove_excess", "DiD", "delta"):
            r = res[(nm, off)]
            row[nm] = r["pt"][i]
            row[nm + "_lo"] = r["lo"][i]
            row[nm + "_hi"] = r["hi"][i]
            row[nm + "_p"] = r["p"][i]
        rows.append(row)
    return pd.DataFrame(rows).set_index("rank")


def main():
    lines = []
    def P(*a):
        s = " ".join(str(x) for x in a)
        print(s)
        lines.append(s)

    allres = {}
    for cutname in ("main", "nomacro", "bucket", "clean", "notariff"):
        res, contr, counts, nd_r, nd_p, books = run(cutname)
        allres[cutname] = dict(res=res, contr=contr, counts=counts, nd_r=nd_r, nd_p=nd_p)

    for cutname in ("main", "nomacro", "bucket", "clean", "notariff"):
        A = allres[cutname]
        P("=" * 132)
        P(f"CUT = {cutname}    real days={A['nd_r']}  placebo days={A['nd_p']}")
        P("=" * 132)
        for off in OFFSETS:
            nh, ndv = A["counts"][("real", off)]
            ph, pdv = A["counts"][("plac", off)]
            P(f"\n  offset +{off}   real n per rank hawk={nh.astype(int).tolist()} dove={ndv.astype(int).tolist()}")
            P(f"                 placebo n per rank hawk={ph.astype(int).tolist()} dove={pdv.astype(int).tolist()}")
            t = table(A["res"], off, cutname)
            show = t[["real_pool", "real_pool_lo", "real_pool_hi", "plac_pool",
                      "pooled_excess", "pooled_excess_lo", "pooled_excess_hi", "pooled_excess_p",
                      "DiD", "DiD_lo", "DiD_hi", "DiD_p", "delta", "delta_lo", "delta_hi"]]
            P(show.round(4).to_string())
            P("  contrasts (bp):")
            for nm in ("real_pool", "pooled_excess", "DiD"):
                for cname in ("front_minus_back_r1_r5", "hump_r3_vs_mid_r1r5", "r3_minus_r1"):
                    c = A["contr"][(nm, off, cname)]
                    P(f"    {nm:14s} {cname:24s} {c['pt']:+.4f}  95% CI [{c['lo']:+.4f}, {c['hi']:+.4f}]  p={c['p']:.4f}")

    # signal-to-noise: excess per unit of that rank's own placebo SD
    ev = pd.read_parquet(BASE + r"\event_paths.parquet")
    pl = pd.read_parquet(BASE + r"\placebo_paths.parquet")
    P("\n" + "=" * 132)
    P("SIGNAL-TO-NOISE: excess in units of that rank's OWN placebo SD of signed_d_bp (dimensionless)")
    P("=" * 132)
    sn = {}
    for off in OFFSETS:
        p = pl[(pl.offset_min == off) & pl.signed_d_bp.notna() & (pl.stance_sign != 0)]
        sd = p.groupby("contract_rank")["signed_d_bp"].std().reindex(RANKS).to_numpy()
        res = allres["main"]["res"]
        sn[off] = dict(
            placebo_sd=sd,
            pooled_excess_over_sd=res[("pooled_excess", off)]["pt"] / sd,
            DiD_over_sd=res[("DiD", off)]["pt"] / sd,
            real_pool_over_sd=res[("real_pool", off)]["pt"] / sd,
        )
        P(f"\n  offset +{off}")
        P(pd.DataFrame(sn[off], index=RANKS).rename_axis("rank").round(4).to_string())

    with open(BASE + r"\fig2_numbers.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # ------------------------------------------------------------------- figure
    make_fig(allres, sn)

    # machine-readable dump
    out = {}
    for cutname, A in allres.items():
        out[cutname] = {"real_days": A["nd_r"], "placebo_days": A["nd_p"], "offsets": {}}
        for off in OFFSETS:
            t = table(A["res"], off, cutname)
            out[cutname]["offsets"][str(off)] = json.loads(t.to_json(orient="index"))
            out[cutname]["offsets"][str(off)]["contrasts"] = {
                f"{nm}|{cn}": A["contr"][(nm, off, cn)]
                for nm in ("real_pool", "pooled_excess", "DiD")
                for cn in ("front_minus_back_r1_r5", "hump_r3_vs_mid_r1r5", "r3_minus_r1")}
    out["signal_to_noise"] = {str(o): {k: list(map(float, v)) for k, v in d.items()} for o, d in sn.items()}
    with open(BASE + r"\fig2_numbers.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("\nwrote fig2_numbers.txt / fig2_numbers.json / fig2_strip_response.png")


def make_fig(allres, sn):
    res = allres["main"]["res"]
    contr = allres["main"]["contr"]
    x = np.arange(1, 6)

    fig = plt.figure(figsize=(16.4, 10.6), dpi=220, facecolor="white")
    gs = GridSpec(2, 2, width_ratios=[1.30, 1.0], height_ratios=[1, 1],
                  wspace=0.23, hspace=0.50, left=0.058, right=0.988, top=0.800, bottom=0.235)
    axA = fig.add_subplot(gs[:, 0])
    axB = fig.add_subplot(gs[0, 1])
    axC = fig.add_subplot(gs[1, 1])
    for ax in (axA, axB, axC):
        ax.set_facecolor("white")
        ax.grid(True, axis="y", color="#e3e3e3", lw=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color("#666666")
        ax.spines["bottom"].set_color("#666666")

    # ---------- Panel A: the spec'd chart, +240, pooled real vs placebo
    off = 240
    rp = res[("real_pool", off)]
    pp = res[("plac_pool", off)]
    ex = res[("pooled_excess", off)]

    axA.axhline(0, color="#444444", lw=1.0)
    axA.fill_between(x, pp["lo"], pp["hi"], color=C_PLAC, alpha=0.28, lw=0,
                     label="placebo 95% band (no-speech days, time-of-day matched)", zorder=1)
    axA.plot(x, pp["pt"], color="#5c5c5c", lw=2.0, ls="--", marker="s", ms=6,
             label="placebo mean", zorder=3)
    axA.errorbar(x, rp["pt"], yerr=[rp["pt"] - rp["lo"], rp["hi"] - rp["pt"]],
                 color=C_REAL, lw=2.6, marker="o", ms=9, capsize=5, capthick=2.0, elinewidth=2.0,
                 label="Fed speeches, all signed events (95% CI, day bootstrap)", zorder=5)
    axA.plot(x, res[("real_hawk", off)]["pt"], color=C_HAWK, lw=0, marker="^", ms=8, alpha=0.95,
             label="hawk arm (real)", zorder=6)
    axA.plot(x, res[("real_dove", off)]["pt"], color=C_DOVE, lw=0, marker="v", ms=8, alpha=0.95,
             label="dove arm (real)", zorder=6)

    ymax = max(rp["hi"].max(), pp["hi"].max(), res[("real_dove", off)]["pt"].max())
    ymin = min(rp["lo"].min(), pp["lo"].min(), res[("real_hawk", off)]["pt"].min())
    pad = 0.13 * (ymax - ymin)
    axA.set_ylim(ymin - pad, ymax + 2.1 * pad)
    for i in range(5):
        star = ex["p"][i] < 0.05
        axA.annotate("clears" if star else "n.s.",
                     (x[i], rp["hi"][i]), textcoords="offset points", xytext=(0, 8),
                     ha="center", fontsize=8.5, color=C_REAL if star else "#909090",
                     fontweight="bold" if star else "normal")
    axA.set_xticks(x)
    axA.set_xticklabels([f"{r}Q\n{3*(r-1)}–{3*(r-1)+6}m" for r in RANKS])
    axA.set_xlabel("SR3 contract rank  (the forward window the contract covers)", fontsize=9.5, labelpad=6)
    axA.set_ylabel("mean signed rate move, speech −60min → +240min  (bp)\n"
                   "positive = rate moved the way the ex-ante stance predicted", fontsize=9.5)
    axA.set_title("A.  Raw profile at +240 min: only 1Q clears the placebo — but the placebo\n"
                  "     itself rises with rank, so this is not the shape test",
                  fontsize=10.5, loc="left", color="#222222", pad=8)
    axA.legend(loc="lower left", fontsize=8.3, frameon=False, ncol=1, handlelength=2.2,
               borderaxespad=0.6)

    # ---------- Panel B: arm-balanced DiD at +30 and +240, AND the release-free cut
    # The three cells whose CIs excluded zero (1Q/2Q/3Q) do not survive removing
    # windows that contain a scheduled US macro release from BOTH books: the
    # excess turns NEGATIVE at every rank.  That series is drawn here so the
    # panel cannot be read as evidence of a response.
    axB.axhline(0, color="#444444", lw=1.0)
    for off_, col, ls, lab in ((240, C_DID, "-", "+240 min (all windows)"),
                               (30, C_ACC, "--", "+30 min (all windows)")):
        d = res[("DiD", off_)]
        axB.fill_between(x, d["lo"], d["hi"], color=col, alpha=0.15, lw=0)
        axB.plot(x, d["pt"], color=col, lw=2.4, ls=ls, marker="o", ms=7, label=lab)
    clean_pt = np.array([FIX["fig2_strip_release_clean"][str(r)]["excess_clean"]["coef"]
                         for r in RANKS])
    clean_t = np.array([FIX["fig2_strip_release_clean"][str(r)]["excess_clean"]["t"] for r in RANKS])
    axB.plot(x, clean_pt, color=C_CLEAN, lw=2.4, ls="-", marker="s", ms=7,
             label="+240 min, RELEASE-FREE windows only", zorder=7)
    c = contr[("DiD", 240, "hump_r3_vs_mid_r1r5")]
    d240 = res[("DiD", 240)]
    for i in range(5):
        if d240["p"][i] < 0.05:
            axB.plot([x[i]], [d240["pt"][i]], marker="o", ms=11, mfc="none", mec=C_DID, mew=1.6, zorder=6)
    axB.set_xticks(x)
    axB.set_xticklabels([f"{r}Q" for r in RANKS])
    axB.set_ylabel("arm-balanced excess over placebo (bp)", fontsize=9)
    axB.set_xlabel("SR3 contract rank   (ringed = clears zero on ALL windows only)", fontsize=9)
    axB.set_title("B.  The three cells that cleared zero are release windows: strip out\n"
                  "     scheduled US macro and the excess goes NEGATIVE at every rank",
                  fontsize=10.5, loc="left", color="#222222", pad=8)
    rb = []
    n_clear = 0
    for cutname, lab in (("main", "all signed"), ("nomacro", "ex CPI/NFP"),
                         ("bucket", "|bucket|≥1"), ("clean", "non-overlap"),
                         ("notariff", "ex 2025-04-09 tariff")):
        cc = allres[cutname]["contr"][("DiD", 240, "hump_r3_vs_mid_r1r5")]
        rb.append(f"{lab} {cc['pt']:+.2f} (p={cc['p']:.2f})")
        n_clear += cc["p"] < 0.05
    # room below the lines for the legend, and above them for the box
    blo = min(clean_pt.min(), res[("DiD", 240)]["lo"].min())
    bhi = max(res[("DiD", 240)]["hi"].max(), res[("DiD", 30)]["hi"].max())
    axB.set_ylim(blo - 0.72 * (bhi - blo), bhi + 0.16 * (bhi - blo))
    axB.legend(fontsize=8.0, frameon=False, loc="lower left", ncol=1, borderaxespad=0.7)
    axB.text(0.015, 0.975,
             "RELEASE-FREE excess, +240 min:  "
             + " · ".join(f"{r}Q {clean_pt[i]:+.2f} (t {clean_t[i]:+.2f})"
                          for i, r in enumerate(RANKS[:3]))
             + "\n   " + " · ".join(f"{r}Q {clean_pt[i + 3]:+.2f} (t {clean_t[i + 3]:+.2f})"
                                    for i, r in enumerate(RANKS[3:])),
             transform=axB.transAxes, fontsize=7.6, va="top", ha="left", color="#444444",
             linespacing=1.5,
             bbox=dict(boxstyle="round,pad=0.36", fc="white", ec="#cccccc", lw=0.7, alpha=0.94))
    HUMP_CUTS = (f"3Q tilt across 5 cuts — stable in size, clears zero in {n_clear} of {len(rb)}, and it is "
                 "1 of ~90 contrasts computed here: " + " · ".join(rb) + ".")

    # ---------- Panel C: delta, the unsigned drift gap
    axC.axhline(0, color="#444444", lw=1.0)
    d = res[("delta", 240)]
    axC.fill_between(x, d["lo"], d["hi"], color=C_DELTA, alpha=0.18, lw=0)
    axC.plot(x, d["pt"], color=C_DELTA, lw=2.4, marker="D", ms=7, label="+240 min")
    d30 = res[("delta", 30)]
    axC.plot(x, d30["pt"], color=C_DELTA, lw=1.6, ls=":", marker="d", ms=6, alpha=0.8, label="+30 min")
    axC.set_xticks(x)
    axC.set_xticklabels([f"{r}Q" for r in RANKS])
    axC.set_ylabel("δ = speech-day − quiet-day\nunsigned drift (bp)", fontsize=9)
    axC.set_xlabel("SR3 contract rank", fontsize=9)
    axC.set_title("C.  Why panel A misleads: quiet days drift up more than speech\n"
                  "     days, and the gap grows with rank",
                  fontsize=10.5, loc="left", color="#222222", pad=8)
    axC.legend(fontsize=8.5, frameon=False, loc="lower left", ncol=2)

    fb = contr[("DiD", 240, "front_minus_back_r1_r5")]
    fig.text(0.058, 0.988,
             "No shape — and on release-free windows, no level either:",
             fontsize=15.0, fontweight="bold", ha="left", va="top", color="#111111")
    fig.text(0.058, 0.960,
             "the SR3 strip response is flat across 1Q–5Q, and dies once scheduled macro leaves the window",
             fontsize=15.0, fontweight="bold", ha="left", va="top", color="#111111")
    fig.text(0.058, 0.929,
             "Mean signed reaction by contract rank against a time-of-day- and calendar-proximity-matched placebo book. "
             "Positive = the rate moved the way the speaker's ex-ante hawk/dove score predicted.\nTHE SHAPE: the two ends "
             f"are dead equal — 1Q−5Q is {fb['pt']:+.2f} bp (CI [{fb['lo']:+.2f}, {fb['hi']:+.2f}]) — and the 3Q tilt is "
             f"{c['pt']:+.3f} bp (CI [{c['lo']:+.3f}, {c['hi']:+.3f}]), about 1/30th of per-event noise and 1 of ~90 "
             "contrasts computed here; it fails in 3 of 5 cuts.\nRead the strip as FLAT — the belly hump a structural "
             "story needs is not in the data. THE LEVEL: the 0.21–0.35 bp arm-balanced excess in panel B is carried by "
             "the 28% of windows containing a scheduled US macro\nrelease. Remove those from both books and the excess is "
             "−0.02 to −0.18 bp at every rank. This figure does not show Fedspeak moving the strip; it shows why the raw "
             "profile looked as if it did.",
             fontsize=9.2, ha="left", va="top", color="#444444", linespacing=1.55)

    nh, nd = allres["main"]["counts"][("real", 240)]
    ph, pd_ = allres["main"]["counts"][("plac", 240)]
    import textwrap
    note = (
        f"Sample: SR3 1-min bars, ex-ante point-in-time hawk/dove scores. Signed events priced at +240 min: "
        f"{int(nh[2])} hawk / {int(nd[2])} dove at 3Q (n varies {int((nh+nd).min())}–{int((nh+nd).max())} by rank) over "
        f"{allres['main']['nd_r']} distinct speech days, 2023-01 to 2026-08 — 2022 carries NO signed events (no ex-ante "
        f"score exists that early). Placebo: {int(ph[2])} hawk / {int(pd_[2])} dove pseudo-events on "
        f"{allres['main']['nd_p']} no-speech days, stance inherited from the matched parent. Pooled arms are 77% hawk / "
        f"23% dove, so panel A is hawk-dominated; the arm-balanced estimator in B weights the arms equally and cancels "
        f"any drift common to both. 95% CIs from 10,000 bootstrap resamples of distinct calendar DAYS, one shared draw "
        f"across all ranks so rank contrasts are paired. The rank ladder rolls on the IMM date, so even 1Q is a "
        f"fully-forward 3m rate — no contract in the ladder is accruing. Baseline −60 min; price(T) = close of the last "
        f"bar labelled strictly before T, NaN if >15 min stale. RELEASE-FREE = no scheduled high/medium-impact US macro "
        f"release anywhere in −60→+240, rebuilt at MINUTE resolution from the timestamped ForexFactory calendar (28.1% of "
        f"windows are contaminated; the panel's own is_cpi_day/is_nfp_day are DAY flags catching only 4–5%); events after "
        f"the calendar ends 2026-08-07 are dropped from BOTH books, never defaulted to clean. Caveats: the −60→+240 window "
        f"is FIVE hours, of which FOUR are after the speech, and non-scheduled macro (tariff headlines, geopolitics, "
        f"ECB/BoE spillover) is still unflagged — read far offsets as \"what happened after a speech\", not \"what the "
        f"speech did\". 48% of placebo days sit within 10 days of an FOMC decision against 2% of real speech days, so the "
        f"null is drawn from quieter days and every excess number here is biased UPWARD. A days_to_fomc gradient runs "
        f"backwards from any information story (far-from-FOMC tercile +0.76 bp t=2.53 vs near tercile −0.01) and is not "
        f"release-driven. 2022 and the SVB week (2023-03-06–17) carry zero signed events. " + HUMP_CUTS
    )
    fig.text(0.058, 0.012, textwrap.fill(note, width=250),
             fontsize=7.5, ha="left", va="bottom", color="#606060", linespacing=1.6)

    out = BASE + r"\fig2_strip_response.png"
    fig.savefig(out, dpi=220, facecolor="white", bbox_inches=None)
    plt.close(fig)
    print("saved", out)


if __name__ == "__main__":
    main()
