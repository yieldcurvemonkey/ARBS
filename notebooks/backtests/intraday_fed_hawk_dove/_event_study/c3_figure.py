"""fig3_speaker_scatter.png -- speaker ex-ante stance vs RAW SR3 move at +240 min."""
import sys, pickle, textwrap
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy import stats as sps
import c3_stats as CS

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
res = pickle.load(open(D + r"\c3_results.pkl", "rb"))
tab, F = res["tab"], res["F"]

HAWK, HAWK_F = "#C0392B", "#E9B8B2"
DOVE, DOVE_F = "#1F5C8B", "#B2CADD"
GREY, INK, FIT = "#8C8C8C", "#22252A", "#111417"
SHADE_H, SHADE_D = "#F8EAE7", "#E6EEF5"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": "#4A4A4A", "axes.linewidth": 0.9,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})

FIGW, FIGH = 15.6, 11.3
fig = plt.figure(figsize=(FIGW, FIGH), dpi=220)
gs = GridSpec(1, 2, width_ratios=[2.45, 1.0], wspace=0.38,
              left=0.052, right=0.985, top=0.872, bottom=0.335)
ax = fig.add_subplot(gs[0, 0])
axf = fig.add_subplot(gs[0, 1])

x = tab["mean_stance"].values
y = tab["mean_move"].values
se = tab["se_move"].values
n = tab["n"].values
names = list(tab.index)

xlo, xhi = x.min() - 4.5, x.max() + 5.0
ylo, yhi = -2.75, 2.75
ax.set_xlim(xlo, xhi); ax.set_ylim(ylo, yhi)

# ---------------- correctly-signed half-planes ----------------
ax.add_patch(plt.Rectangle((0, 0), xhi, yhi, color=SHADE_H, zorder=0))
ax.add_patch(plt.Rectangle((xlo, ylo), -xlo, -ylo, color=SHADE_D, zorder=0))
ax.text(xhi - 0.7, yhi - 0.10, "hawk  \u2192  rate rose", ha="right", va="top",
        fontsize=10, color=HAWK, style="italic", alpha=0.9, zorder=1)
ax.text(xhi - 0.7, yhi - 0.40, "correctly signed", ha="right", va="top",
        fontsize=8.4, color=HAWK, alpha=0.62, zorder=1)
ax.text(xlo + 0.7, ylo + 0.40, "dove  \u2192  rate fell", ha="left", va="bottom",
        fontsize=10, color=DOVE, style="italic", alpha=0.9, zorder=1)
ax.text(xlo + 0.7, ylo + 0.14, "correctly signed", ha="left", va="bottom",
        fontsize=8.4, color=DOVE, alpha=0.62, zorder=1)

ax.axhline(0, color="#5A5A5A", lw=0.9, zorder=2)
ax.axvline(0, color="#5A5A5A", lw=0.9, zorder=2)
ax.grid(True, alpha=0.16, lw=0.6, color="#9AA0A6", zorder=1)

# ---------------- fit + 95% CI band ----------------
tcrit = sps.t.ppf(0.975, F["dof"])
mde = (tcrit + sps.t.ppf(0.80, F["dof"])) * F["se_slope"]
xg = np.linspace(xlo, xhi, 200)
Xd = np.column_stack([np.ones(len(x)), x])
XtX_inv = np.linalg.pinv(Xd.T @ Xd)
Xg = np.column_stack([np.ones_like(xg), xg])
sig2 = ((y - (F["intercept"] + F["slope"] * x)) ** 2).sum() / F["dof"]
seg = np.sqrt(sig2 * np.einsum("ij,jk,ik->i", Xg, XtX_inv, Xg))
yhat_g = F["intercept"] + F["slope"] * xg
ax.fill_between(xg, yhat_g - tcrit * seg, yhat_g + tcrit * seg,
                color="#9AA0A6", alpha=0.30, lw=0, zorder=4)

# single MDE reference line: what a detectable effect would look like
xc, yc = x.mean(), y.mean()
ax.plot(xg, yc + mde * (xg - xc), color="#5F6368", lw=1.4, ls=(0, (1.5, 2.6)),
        alpha=0.95, zorder=5)
_xa = -15.0
ax.annotate(f"an effect big enough for this design to detect\n"
            f"would tilt this steeply  (slope {mde:.3f}, 80% power)",
            xy=(_xa, yc + mde * (_xa - xc)),
            xytext=(xlo + 1.0, -1.62),
            ha="left", va="center", fontsize=8.6, color="#4F5358", linespacing=1.45,
            arrowprops=dict(arrowstyle="-", color="#7A7F85", lw=0.9,
                            shrinkA=3, shrinkB=3), zorder=11,
            bbox=dict(boxstyle="round,pad=0.34", fc="white", ec="#C3C7CC",
                      lw=0.7, alpha=0.90))

ax.plot(xg, PFy := (res["PF"]["intercept"] + res["PF"]["slope"] * xg),
        color=GREY, lw=1.9, ls="--", alpha=0.95, zorder=5)
ax.plot(xg, yhat_g, color=FIT, lw=2.7, zorder=6)

# ---------------- error bars + points ----------------
colors = [HAWK if xi > 0 else DOVE for xi in x]
faces = [HAWK_F if xi > 0 else DOVE_F for xi in x]
for i in range(len(x)):
    ax.errorbar(x[i], y[i], yerr=se[i], fmt="none", ecolor=colors[i], elinewidth=1.5,
                capsize=3.2, capthick=1.5, alpha=0.70, zorder=7)
sizes = 26 + 5.0 * n
# semi-transparent fills with a thin edge: in the +5..+15 hawk cluster six markers
# overlap, and an opaque fill hides whichever is drawn underneath.
ax.scatter(x, y, s=sizes, c=faces, edgecolors=colors, linewidths=1.25, zorder=8, alpha=0.58)

# ---------------- iterative label declutter with leader lines ----------------
fig.canvas.draw()
def d2a(dx, dy):
    """data-length -> axes-fraction-ish scaling helpers in data units."""
    return dx, dy

xr_, yr_ = (xhi - xlo), (yhi - ylo)
ax_w_in = ax.get_position().width * FIGW
ax_h_in = ax.get_position().height * FIGH
FS = 9.0
# label half-size in DATA units
lab_w = np.array([len(nm) * FS * 0.60 / 72.0 / ax_w_in * xr_ / 2 for nm in names])
lab_h = np.full(len(names), FS * 1.30 / 72.0 / ax_h_in * yr_ / 2)

lx = x.astype(float).copy()
# place the label on the side that keeps it near its own point: above for points
# at/above the fit line, below for points beneath it. A tall error bar (Jefferson,
# SE ~1bp) would otherwise fling the label right across the crowded middle.
y_fit = F["intercept"] + F["slope"] * x
side = np.where(y >= y_fit, 1.0, -1.0)
ly = y + side * (se + lab_h * 1.55 + np.sqrt(sizes) / 2 / 72.0 / ax_h_in * yr_)

# obstacles the labels must also dodge: the markers themselves
mk_w = np.sqrt(sizes) / 2 / 72.0 / ax_w_in * xr_
mk_h = np.sqrt(sizes) / 2 / 72.0 / ax_h_in * yr_

rng = np.random.default_rng(3)
for it in range(2000):
    moved = False
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            # a little horizontal slack on top of the glyph width, so adjacent
            # labels read as separate words rather than one run of text
            ox = (lab_w[i] + lab_w[j]) * 1.10 - abs(lx[i] - lx[j])
            oy = (lab_h[i] + lab_h[j]) * 1.45 - abs(ly[i] - ly[j])
            if ox > 0 and oy > 0:
                moved = True
                d = ly[i] - ly[j]
                if abs(d) < 1e-9:
                    d = rng.normal() * 1e-3
                push = oy * 0.5 * np.sign(d)
                ly[i] += push * 0.60
                ly[j] -= push * 0.60
                dx_ = lx[i] - lx[j]
                if abs(dx_) < 1e-9:
                    dx_ = rng.normal() * 1e-3
                lx[i] += ox * 0.22 * np.sign(dx_)
                lx[j] -= ox * 0.22 * np.sign(dx_)
    # keep labels off the markers
    for i in range(len(names)):
        for j in range(len(names)):
            ox = (lab_w[i] + mk_w[j]) - abs(lx[i] - x[j])
            oy = (lab_h[i] + mk_h[j]) - abs(ly[i] - y[j])
            if ox > 0 and oy > 0:
                moved = True
                d = ly[i] - y[j]
                if abs(d) < 1e-9:
                    d = 1e-3
                ly[i] += oy * 0.55 * np.sign(d)
    lx = np.clip(lx, xlo + lab_w + 0.25, xhi - lab_w - 0.25)
    ly = np.clip(ly, ylo + lab_h + 0.12, yhi - lab_h - 0.12)
    if not moved:
        break

for i, nm in enumerate(names):
    # leader line if the label drifted away from its point
    dist = np.hypot((lx[i] - x[i]) / xr_, (ly[i] - y[i]) / yr_)
    if dist > 0.035:
        ax.plot([x[i], lx[i]], [y[i] + np.sign(ly[i] - y[i]) * (se[i] + mk_h[i] * 0.5), ly[i]],
                color=colors[i], lw=0.7, alpha=0.45, zorder=8.5,
                solid_capstyle="round")
    ax.text(lx[i], ly[i], nm, ha="center", va="center", fontsize=FS,
            color=colors[i], fontweight="semibold", zorder=10)

ax.set_xlabel("Speaker's mean ex-ante hawk/dove score   (point-in-time JPM FED "
              "trailing-5 average;  + = hawkish)", fontsize=10.8, labelpad=8)
ax.set_ylabel("Mean RAW change in SR3 implied rate,  t\u221260 \u2192 +240 min   (bp)\n"
              "positive = rate rose", fontsize=10.8, labelpad=8)

stat = (f"cross-speaker OLS    slope = {F['slope']:+.4f} bp per score point\n"
        f"t = {F['t_slope']:+.2f}     p = {F['p_slope']:.2f}     "
        f"R\u00b2 = {F['r2']:.4f}     n = {F['n']} speakers\n"
        f"placebo slope = {res['PF']['slope']:+.4f} (t = {res['PF']['t_slope']:+.2f})  "
        f"\u2014 dashed grey\n"
        f"hawk\u2212dove spread end to end: {F['slope']*(x.max()-x.min()):+.2f} bp,  "
        f"95% CI [{(F['slope']-tcrit*F['se_slope'])*(x.max()-x.min()):+.2f}, "
        f"{(F['slope']+tcrit*F['se_slope'])*(x.max()-x.min()):+.2f}]")
ax.text(0.014, 0.984, stat, transform=ax.transAxes, ha="left", va="top", fontsize=9.3,
        color=INK, zorder=13, linespacing=1.55,
        bbox=dict(boxstyle="round,pad=0.55", fc="white", ec="#9AA0A6", lw=0.9, alpha=0.96))
ax.text(0.986, 0.022, "marker area \u221d number of speeches\nbars = \u00b11 SE of the speaker mean",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color="#5F6368",
        zorder=13, linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.42", fc="white", ec="#C3C7CC", lw=0.7, alpha=0.94))
ax.set_title("One dot per official \u2014 21 FOMC speakers, 827 scored speeches",
             fontsize=11.6, color="#42464C", pad=10, loc="left")
for s_ in ("top", "right"):
    ax.spines[s_].set_visible(False)

# =================== right panel: robustness forest ===================
# Red and blue mean HAWK and DOVE everywhere else in this deck, so the forest
# rows must not reuse them for voter status - a red "Voters only" row against a
# blue "Non-voters only" row reads at a glance as a stance split.  Two neutral
# slates carry the voter contrast instead.
SLATE_D, SLATE_L = "#3F4A57", "#818C9B"
rows = [
    ("Headline \u00b7 all signed speeches", F, INK, True),
    ("Drop %s (top lever)" % res["lever"], res["F_loo"], INK, False),
    ("Non-overlapping only", res["CF"], INK, False),
    ("Conviction  |bucket| \u2265 1", res["BF"], INK, False),
    ("Voters only \u2020", res["VF"], SLATE_D, False),
    ("Non-voters only \u2020", res["NF"], SLATE_L, False),
    ("PLACEBO \u00b7 quiet days", res["PF"], GREY, False),
]
ypos = np.arange(len(rows))[::-1]
axf.axvspan(-mde, mde, color=GREY, alpha=0.15, lw=0, zorder=0)
_los, _his = [], []
for lbl, f_, col, bold in rows:
    tc = sps.t.ppf(0.975, f_["dof"])
    _los.append(f_["slope"] - tc * f_["se_slope"])
    _his.append(f_["slope"] + tc * f_["se_slope"])
fxlo = min(min(_los), -mde) - 0.012
fxhi = max(max(_his), mde) + 0.078          # right margin reserved for the t labels
axf.set_xlim(fxlo, fxhi)
t_x = fxhi - 0.004

for k, (lbl, f_, col, bold) in enumerate(rows):
    yy = ypos[k]
    lo, hi = _los[k], _his[k]
    axf.plot([lo, hi], [yy, yy], color=col, lw=2.1, alpha=0.9, solid_capstyle="round", zorder=4)
    for e in (lo, hi):
        axf.plot([e, e], [yy - 0.13, yy + 0.13], color=col, lw=1.5, zorder=4)
    axf.scatter([f_["slope"]], [yy], s=78 if bold else 52, color=col, zorder=5,
                edgecolors="white", linewidths=1.2)
    # t label on the SAME row, in the reserved right margin
    axf.text(t_x, yy, f"t = {f_['t_slope']:+.2f}", ha="right", va="center",
             fontsize=8.4, color="#6E6E6E", zorder=6)

axf.axvline(0, color="#3A3A3A", lw=1.2, zorder=2)
axf.set_ylim(-0.75, len(rows) - 0.25)
axf.set_yticks(ypos)
axf.set_yticklabels([r[0] for r in rows], fontsize=9.3)
for tk, (lbl, f_, col, bold) in zip(axf.get_yticklabels(), rows):
    tk.set_color(col if col != INK else INK)
    if bold:
        tk.set_fontweight("bold")
axf.tick_params(axis="y", length=0, pad=6)
axf.set_xlabel("Cross-speaker slope   (bp per score point)", fontsize=10.2, labelpad=8)
axf.grid(True, axis="x", alpha=0.18, lw=0.6, color="#9AA0A6")
axf.set_axisbelow(True)
axf.set_title("Every cut straddles zero", fontsize=11.6, color="#42464C", pad=10, loc="left")
axf.text(0.5, -0.62, "grey band = \u00b1 the slope this design could detect at 80% power",
         transform=axf.get_yaxis_transform(), ha="center", va="center",
         fontsize=8.3, color="#6E6E6E")
for s_ in ("top", "right", "left"):
    axf.spines[s_].set_visible(False)

# =================== headline + footnote ===================
fig.suptitle("A Fed speaker's known hawkishness does not predict which way SR3 moves "
             "after they speak",
             fontsize=16.6, fontweight="bold", color=INK, x=0.052, ha="left", y=0.975)
fig.text(0.052, 0.936,
         "Cross-speaker slope is +0.0005 bp per score point (t = 0.05, R\u00b2 = 0.0001) \u2014 "
         "and stays flat in all 21 leave-one-out refits, both voter cuts and the placebo.",
         fontsize=11.4, color="#4A4E54", ha="left", va="top")

loo = res["loo"]
paras = [
    f"SR3 contract rank 3 (~9\u201315 months forward), 4 hours after the speech. y is the RAW "
    f"directional rate change from the \u221260-min baseline \u2014 NOT sign-flipped by stance, which "
    f"would make the fit circular. Sample: {res['n_events']} Fed speeches, {res['span'][0]} to "
    f"{res['span'][1]}, each carrying a point-in-time score published BEFORE the speech. 2022 has "
    f"zero scored events, so this is effectively a 2023\u20132026 sample. Speakers with <8 priced "
    f"speeches excluded (Paulson only, n=3).",

    f"CAVEAT 1 \u2014 the roster is lopsided: {int((x>0).sum())} of {len(x)} speakers have a hawkish "
    f"mean score, so the dove half-plane rests almost entirely on Barr. His x-position alone supplies "
    f"44% of the regression's x-variance, and as Vice Chair for Supervision his score partly reads "
    f"regulatory rather than monetary speeches. Barr has high leverage (h = 0.49) but near-zero "
    f"Cook's D \u2014 he anchors the axis without tilting the line.",

    f"CAVEAT 2 \u2014 the biggest actual lever is {res['lever']}; dropping him leaves the slope at "
    f"{res['F_loo']['slope']:+.4f} (t = {res['F_loo']['t_slope']:+.2f}). Across all 21 leave-one-out "
    f"refits the slope stays inside [{loo.slope.min():+.4f}, {loo.slope.max():+.4f}] and not one "
    f"reaches p < 0.05, so this null is not any single name's result.",

    f"CAVEAT 3 \u2014 sign agreement is {res['sign_k']}/{res['sign_n']} = "
    f"{res['sign_k']/res['sign_n']:.0%} of speakers (binomial p = {res['sign_p']:.2f}), but the "
    f"calendar-matched placebo scores {res['pk']}/{res['pn']} = {res['pk']/res['pn']:.0%} on days "
    f"nobody spoke, so the agreement rate carries no information.",

    f"CAVEAT 4 \u2014 \u2020 THE VOTER / NON-VOTER ROWS ARE NOT COMPARABLE and must not be read as evidence "
    f"for a voter effect. All three dove-mean speakers (Barr, Miran, Waller) are Governors, i.e. permanent "
    f"voters, so the non-voter slope is fitted on positive-only x (+5.4 to +22.6) while the voter slope "
    f"spans \u221224.9 to +24.9. \u201cVoters show a steeper slope\u201d is inseparable from \u201cthe doves all vote\u201d. "
    f"The within-rotator specification is the only one that dodges this and it is insignificant (p = 0.13).",

    f"CAVEAT 5 \u2014 the measurement window is \u221260 \u2192 +240 min: FIVE hours, of which FOUR are after the "
    f"speech starts. 28.1% of these windows contain a scheduled high/medium-impact US macro release "
    f"(window-level flag rebuilt at minute resolution; the panel's own is_cpi_day / is_nfp_day are DAY "
    f"flags catching only 4\u20135%). Non-scheduled macro \u2014 tariff headlines, geopolitics, ECB/BoE spillover "
    f"\u2014 is still unflagged. Read this as \u201cwhat happened in the hours after a speech\u201d, not \u201cwhat the "
    f"speech did\u201d. The speaker-level null here is unaffected either way: it is a null, and removing "
    f"contaminated windows can only shrink an effect that is already zero.",
]
WRAP = 213
lines = []
for p in paras:
    lines.extend(textwrap.wrap(p, WRAP))
fig.text(0.052, 0.268, "\n".join(lines), fontsize=8.2, color="#54585E",
         ha="left", va="top", linespacing=1.62)

out = D + r"\fig3_speaker_scatter.png"
fig.savefig(out, dpi=220, facecolor="white")
print("[written]", out)
print(f"footnote lines: {len(lines)}   MDE {mde:.5f}   slope {F['slope']:+.5f}  t {F['t_slope']:+.3f}")
