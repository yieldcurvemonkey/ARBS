"""Figure 4: the principal-vs-rest cut - the thesis's best surviving lane."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"

split = json.load(open(f"{OUT}/zz_principal_split.json"))
plac = json.load(open(f"{OUT}/zz_principal_placebo.json"))

BLUE, ORANGE, GREY, RED = "#2b6cb0", "#dd6b20", "#a0aec0", "#c53030"
plt.rcParams.update({"font.size": 10, "axes.facecolor": "#fafafa",
                     "figure.facecolor": "white", "axes.edgecolor": "#cbd5e0"})

fig = plt.figure(figsize=(16, 6.4))
gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1], wspace=0.28,
                      left=0.07, right=0.975, top=0.80, bottom=0.16)

fig.suptitle("The last untested cut: do the principals move it, even though the pooled calendar does not?",
             x=0.07, ha="left", fontsize=15, fontweight="bold", y=0.955)
fig.text(0.07, 0.895,
         "Pooling 36 names dilutes a Chair/Governor effect ~4x. Splitting by WHO spoke is the thesis's best remaining lane. "
         "Sample: ex-FOMC/CPI/NFP, ex-IMM-roll, 2019-2026.",
         ha="left", fontsize=10, color="#4a5568")
fig.text(0.07, 0.862,
         "Pre-registered: 4 tiers x 2 statistics x 2 samples = 16 cells, 0.8 expected below p<0.05 by chance. All are shown.",
         ha="left", fontsize=9, color="#718096", style="italic")

# ---------------- Panel A: tiers ----------------
axA = fig.add_subplot(gs[0, 0])
tiers = ["T1_chair_only", "T2_chair_plus_ny", "T3_board_perm_voters", "T4_regional_only"]
labels = ["Chair only\n(Powell)", "Chair + NY Fed\n(+ Williams)",
          "All permanent voters\n(Board + NY)", "Regional presidents\nONLY"]
v = split["rung_c_clean"]["tiers"]
y = np.arange(len(tiers))[::-1]

for i, (t, yy) in enumerate(zip(tiers, y)):
    s = v[t]
    # null band for the mean ratio
    lo = 2 * s["null_median_mean_ratio"] - s["null_p97.5_mean"]
    axA.barh(yy + 0.16, s["null_p97.5_mean"] - lo, left=lo, height=0.20,
             color=GREY, alpha=0.35, zorder=1)
    axA.plot([s["null_median_mean_ratio"]] * 2, [yy + 0.06, yy + 0.26], color="#4a5568", lw=1.4, zorder=3)
    axA.scatter([s["mean_ratio"]], [yy + 0.16], s=105, color=BLUE, zorder=4,
                edgecolor="white", linewidth=1.2)
    axA.text(2.02, yy + 0.16, f"{s['mean_ratio']:.2f}", va="center", fontsize=10,
             fontweight="bold", color=BLUE)
    axA.text(2.30, yy + 0.16, f"p {s['rotation_p_mean']:.2f}", va="center", fontsize=9, color="#718096")

    lo2 = 2 * s["null_median_median_ratio"] - s["null_p97.5_median"]
    axA.barh(yy - 0.16, s["null_p97.5_median"] - lo2, left=lo2, height=0.20,
             color=GREY, alpha=0.35, zorder=1)
    axA.plot([s["null_median_median_ratio"]] * 2, [yy - 0.26, yy - 0.06], color="#4a5568", lw=1.4, zorder=3)
    sig = s["rotation_p_median"] < 0.05
    axA.scatter([s["median_ratio"]], [yy - 0.16], s=105, color=ORANGE, zorder=4,
                edgecolor=(RED if sig else "white"), linewidth=(2.0 if sig else 1.2))
    axA.text(2.02, yy - 0.16, f"{s['median_ratio']:.2f}", va="center", fontsize=10,
             fontweight="bold", color=ORANGE)
    axA.text(2.30, yy - 0.16, f"p {s['rotation_p_median']:.3f}", va="center", fontsize=9,
             color=(RED if sig else "#718096"), fontweight=("bold" if sig else "normal"))
    axA.text(0.715, yy, f"n={s['n']}", va="center", ha="left", fontsize=8, color="#a0aec0")

axA.axvline(1.0, color="#2d3748", ls="--", lw=1.2, zorder=2)
axA.text(1.0, len(tiers) - 0.42, " no effect", fontsize=9, color="#4a5568", ha="left")
axA.set_yticks(y)
axA.set_yticklabels(labels, fontsize=10)
axA.set_xlim(0.70, 2.55)
axA.set_xticks([0.75, 1.0, 1.25, 1.5, 1.75])
axA.set_ylim(-0.75, len(tiers) - 0.25)
axA.set_xlabel("speech-day / no-speech-day ratio of |daily change|", fontsize=10)
axA.set_title("A · By who spoke  —  blue = mean|d| ratio, orange = median|d| ratio",
              fontsize=11.5, fontweight="bold", loc="left", pad=8)
axA.grid(axis="x", alpha=0.25)
for sp in ("top", "right"):
    axA.spines[sp].set_visible(False)
axA.text(0.735, -0.58,
         "grey bar = 95% of the circular-rotation null · dark tick = its median,\n"
         "the true no-effect point (NOT 1.0) · red ring = the one cell of 16 at p<0.05",
         fontsize=8, color="#718096", va="center", ha="left", linespacing=1.5)

# ---------------- Panel B: front-end specificity ----------------
axB = fig.add_subplot(gs[0, 1])
keys = [k for k in plac if isinstance(plac[k], dict) and "median_ratio" in plac[k]]
order = sorted(keys, key=lambda k: (0 if "IMM" in k.upper() else (1 if "2y" in k else 2)))
names = ["3m IMM forward\n(SR3, the target)", "2y SOFR", "5y SOFR"]
exc = [plac[k]["median_ratio"] / plac[k]["null_median_of_median_ratio"] - 1 for k in order]
cols = [ORANGE, GREY, GREY]
x = np.arange(3)
bars = axB.bar(x, [e * 100 for e in exc], color=cols, width=0.58,
               edgecolor="white", linewidth=1.5, zorder=3)
for i, (b, k) in enumerate(zip(bars, order)):
    axB.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.45,
             f"{exc[i]*100:+.1f}%", ha="center", fontsize=11, fontweight="bold",
             color=(ORANGE if i == 0 else "#4a5568"))
    axB.text(b.get_x() + b.get_width() / 2, -1.45, f"p {plac[k]['rotation_p_median']:.3f}",
             ha="center", fontsize=9, color="#718096")
axB.axhline(0, color="#2d3748", lw=1.2)
axB.set_xticks(x)
axB.set_xticklabels(names, fontsize=9.5)
axB.set_ylabel("median|d| tilt in EXCESS of its own rotation null (%)", fontsize=9.5)
axB.set_ylim(-2.2, 18)
axB.set_title("B · Is it front-end specific?  On permanent-voter days",
              fontsize=11.5, fontweight="bold", loc="left", pad=8)
axB.grid(axis="y", alpha=0.25)
for sp in ("top", "right"):
    axB.spines[sp].set_visible(False)
axB.text(0.5, 15.6, "the front end carries ~2x the tilt of the 2y/5y —\nthe one result that IS shaped like the thesis",
         fontsize=8.8, color=ORANGE, style="italic", ha="left")

fig.text(0.07, 0.055,
         "VERDICT  A faint, front-end-specific tilt exists on permanent-voter days — and pooling all 36 speakers was hiding it. But it lives in the MEDIAN, not the mean "
         "(mean 1.09, p 0.35), and p moves 0.027 -> 0.058 between two honest implementations of the same test.",
         fontsize=10.5, fontweight="bold", color="#1a202c", ha="left")
fig.text(0.07, 0.020,
         "A result that straddles 5% on implementation detail is a HINT, not a finding. It is the right thing to test intraday, where the instrument is not diluted by 23 hours of other news — not a number to quote.",
         fontsize=9.2, color="#4a5568", ha="left")

fig.savefig(f"{OUT}/fig_principal_split.png", dpi=200, bbox_inches="tight", facecolor="white")
print("wrote fig_principal_split.png")
