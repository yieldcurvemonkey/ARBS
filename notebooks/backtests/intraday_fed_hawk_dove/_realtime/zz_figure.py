"""The real-time verdict in one figure: the signal is real and it is worth its costs."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_realtime"
S = pd.read_csv(f"{OUT}/scoreboard.csv")

PIT, PROV, HIND = "#1d6f6f", "#8a6d1f", "#a8342c"
GREY, INK = "#a8b0ba", "#1a202c"
KIND_C = {"PIT": PIT, "provenance": PROV, "hindsight": HIND}
plt.rcParams.update({"font.size": 10, "axes.facecolor": "#fafafa", "figure.facecolor": "white",
                     "axes.edgecolor": "#cbd5e0"})

fig = plt.figure(figsize=(17, 7.6))
gs = fig.add_gridspec(1, 2, width_ratios=[1.42, 1], wspace=0.30,
                      left=0.20, right=0.975, top=0.795, bottom=0.135)

fig.suptitle("The committee-standing signal is real — and it is worth almost exactly its transaction costs",
             x=0.035, ha="left", fontsize=15.5, fontweight="bold", y=0.955)
fig.text(0.035, 0.895,
         "SR3 3rd contract, \u221260\u2192+240 min, voters only, 2022\u20132026.  Trade = sign(stance) \u00d7 rate move.  "
         "t is day-clustered.  A round trip crosses roughly one 0.5 bp tick.",
         ha="left", fontsize=10, color="#4a5568")
fig.text(0.035, 0.858,
         "PIT = structurally point-in-time (a corruption test confirms no construction reads its own quarter).  "
         "provenance = filtered by cited evidence dates.  hindsight = labels assigned in 2026.",
         ha="left", fontsize=9, color="#718096", style="italic")

# ---------- Panel A: gross vs net ----------
axA = fig.add_subplot(gs[0, 0])
d = S.dropna(subset=["gross_bp"]).copy()
d = d.iloc[::-1].reset_index(drop=True)
y = np.arange(len(d))

for i, r in d.iterrows():
    c = KIND_C.get(r["kind"], GREY)
    axA.plot([r["net_050"], r["gross_bp"]], [y[i], y[i]], color=c, lw=2.0, alpha=0.30,
             solid_capstyle="round", zorder=2)
    axA.scatter([r["gross_bp"]], [y[i]], s=95, color=c, zorder=4, edgecolor="white", lw=1.2)
    net = r["net_050"]
    axA.scatter([net], [y[i]], s=95, color=c, zorder=4, marker="D",
                edgecolor=("white" if net > 0 else INK), lw=(1.2 if net > 0 else 1.6))
    axA.text(2.02, y[i], f"{r['gross_bp']:+.2f}", va="center", ha="right", fontsize=9.5,
             color=c, fontweight="bold")
    axA.text(2.52, y[i], f"{net:+.2f}", va="center", ha="right", fontsize=9.5,
             color=(c if net > 0 else "#9aa4b0"),
             fontweight=("bold" if net > 0 else "normal"))
    axA.text(2.90, y[i], f"{r['t']:.2f}", va="center", ha="right", fontsize=9, color="#718096")
    axA.text(-1.28, y[i], f"n={int(r['n'])}", va="center", ha="left", fontsize=8, color="#a0aec0")

axA.axvline(0, color=INK, ls="-", lw=1.1, zorder=1)
axA.axvspan(-1.35, 0, color="#c53030", alpha=0.05, zorder=0)
axA.set_yticks(y)
axA.set_yticklabels(d["construction"], fontsize=9.6)
axA.set_xlim(-1.35, 2.95)
axA.set_xticks([-1.0, -0.5, 0, 0.5, 1.0, 1.5])
axA.set_ylim(-0.95, len(d) - 0.35)
axA.set_xlabel("bp per trade", fontsize=10)
axA.set_title("A \u00b7 Circle = gross.  Diamond = net of a 0.5 bp round trip.",
              fontsize=11.5, fontweight="bold", loc="left", pad=8)
axA.grid(axis="x", alpha=0.25)
for sp in ("top", "right"):
    axA.spines[sp].set_visible(False)
axA.text(2.02, len(d) - 0.55, "gross", ha="right", fontsize=8.5, color="#718096", fontweight="bold")
axA.text(2.52, len(d) - 0.55, "net", ha="right", fontsize=8.5, color="#718096", fontweight="bold")
axA.text(2.90, len(d) - 0.55, "t", ha="right", fontsize=8.5, color="#718096", fontweight="bold")

fl = float(S.loc[S.construction.str.contains("ROLE"), "gross_bp"].iloc[0])
_fy = list(d.construction).index("L4 ROLE ONLY (floor)")
axA.annotate("the floor", xy=(fl, _fy), xytext=(-0.92, _fy + 0.80),
             fontsize=8.8, color="#4a5568",
             arrowprops=dict(arrowstyle="->", color="#a0aec0", lw=1.0))

# ---------- Panel B: the two claims ----------
axB = fig.add_subplot(gs[0, 1])
best = S[S.kind == "PIT"].sort_values("gross_bp", ascending=False).iloc[0]
conv = {"name": "conviction |2|\nstability\u22652q", "gross": 0.802, "net": 0.302, "t": 2.57, "n": 167}
bars = [
    ("role alone\n(floor)", fl, 0.45, GREY),
    ("best PIT\n(prev quarter)", float(best["gross_bp"]), float(best["t"]), PIT),
    ("hindsight\n(upper bound)", float(S.loc[S.kind == "hindsight", "gross_bp"].max()), 4.13, HIND),
    (conv["name"], conv["gross"], conv["t"], PIT),
]
x = np.arange(len(bars))
axB.bar(x, [b[1] for b in bars], color=[b[3] for b in bars], width=0.6,
        edgecolor="white", lw=1.5, zorder=3)
axB.axhline(0.5, color="#c53030", ls="--", lw=1.6, zorder=4)
axB.text(3.42, 0.53, "0.5 bp round trip", ha="right", fontsize=9, color="#c53030", fontweight="bold")
axB.axhline(0, color=INK, lw=1.1)
for i, (nm, g, t, c) in enumerate(bars):
    axB.text(i, g + 0.035, f"{g:+.2f}", ha="center", fontsize=11, fontweight="bold", color=c)
    axB.text(i, -0.085, f"t {t:.2f}", ha="center", fontsize=8.5, color="#718096")
axB.set_xticks(x)
axB.set_xticklabels([b[0] for b in bars], fontsize=9.2)
axB.set_ylim(-0.16, 1.15)
axB.set_ylabel("gross bp per trade", fontsize=10)
axB.set_title("B \u00b7 Only the conviction cut clears the cost line",
              fontsize=11.5, fontweight="bold", loc="left", pad=8)
axB.grid(axis="y", alpha=0.25)
for sp in ("top", "right"):
    axB.spines[sp].set_visible(False)

fig.text(0.035, 0.062,
         "THE RESEARCH FINDING HOLDS.  Standing carries information that tone does not, and it is not merely who is speaking: role alone pays +0.07 bp (t 0.45) while a structurally point-in-time",
         fontsize=10, color=INK, ha="left")
fig.text(0.035, 0.036,
         "stance label pays +0.49 to +0.51 (t 2.4\u20133.0).  Hindsight is worth ~20% of the edge, not all of it, and the mechanical own-history label is dead (+0.11, t 0.68) \u2014 so this is the committee read, not momentum.",
         fontsize=10, color=INK, ha="left")
fig.text(0.035, 0.008,
         "THE BUSINESS CLAIM DOES NOT.  At a 0.5 bp round trip the best point-in-time book nets \u22120.01 to +0.01 bp \u2014 zero. Only the conviction |2| cut survives, at +0.30 bp net on 167 trades; the last four quarters pay +0.06 net on 51.",
         fontsize=10, color="#a8342c", ha="left", fontweight="bold")

fig.savefig(f"{OUT}/fig_realtime_verdict.png", dpi=200, bbox_inches="tight", facecolor="white")
print("wrote fig_realtime_verdict.png")
