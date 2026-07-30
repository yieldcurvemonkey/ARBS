"""Figures for the dealer-ladder findings. Style defined ONCE, here.

Design rules this module enforces so the notebook cannot break them:

- **Categorical hues in fixed order, never cycled.** Three slots only (blue,
  orange, aqua), which is the set that validates on ALL pairs rather than just
  adjacent ones — these are scatter/multi-series forms, so all-pairs is the right
  gate. A fourth series folds into "other" or gets its own facet.
- **One axis, ever.** No dual-scale plot appears in this module. Two measures of
  different scale get two panels.
- **Status color never carries meaning alone.** Pass/fail always ships the word as
  well as the colour, because a reader with a colour deficiency, a greyscale
  printout, or forced colours has to get the same answer.
- **Recessive chrome, thin marks, selective direct labels.** Values are labelled on
  the rows a reader will quote (best, median, reference), not on every point.
- Aqua sits at 2.74:1 on the light surface, below the 3:1 bar, so every figure
  using it carries visible direct labels — the documented relief for that.
"""
from __future__ import annotations

import numpy as np

# --- validated palette (light mode, surface #fcfcfb) ----------------------
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")      # blue, orange, aqua
STATUS = {"good": "#0ca30c", "warning": "#fab219",
          "serious": "#ec835a", "critical": "#d03b3b"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"


def use_style():
    """Apply the chart chrome. Call once per notebook."""
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "600",
        "axes.labelsize": 9,
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "text.color": INK,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 2.0,
        "lines.markersize": 5,
        "figure.dpi": 120,
        "savefig.facecolor": SURFACE,
    })


def _finish(ax, title, xlabel=None, ylabel=None, note=None):
    ax.set_title(title, loc="left", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.set_axisbelow(True)
    if note:
        ax.annotate(note, xy=(0, -0.19), xycoords="axes fraction",
                    fontsize=7.5, color=MUTED, va="top")
    return ax


def verdict_strip(verdicts, ax=None):
    """Gate outcomes as a labelled strip — a state readout, not a chart.

    Each gate shows PASS / FAIL / N/A as TEXT beside its swatch, so the state never
    depends on colour. N/A is a real outcome here: a gate can be undecidable for
    want of data, which is different from failing.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(8.2, 0.52 * max(len(verdicts), 1) + 0.9))
    labels, words, colors = [], [], []
    for v in verdicts:
        labels.append(str(v.get("gate", "?")))
        p = v.get("pass")
        word = "N/A" if p is None else ("PASS" if p else "FAIL")
        words.append(word)
        colors.append(STATUS["good"] if p else
                      (MUTED if p is None else STATUS["critical"]))
    y = np.arange(len(labels))[::-1]
    ax.barh(y, [1] * len(labels), height=0.55, color=colors, alpha=0.16,
            edgecolor="none")
    for yy, lab, word, col, v in zip(y, labels, words, colors, verdicts):
        ax.text(0.012, yy, lab, va="center", ha="left", fontsize=9.5,
                color=INK, fontweight="600")
        ax.text(0.115, yy, word, va="center", ha="left", fontsize=9,
                color=col, fontweight="700")
        ax.text(0.20, yy, str(v.get("headline", ""))[:118], va="center",
                ha="left", fontsize=8, color=INK_2)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.7, len(labels) - 0.3)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Gate outcomes (state shown as text, not colour alone)",
                 loc="left", pad=8)
    return ax


def lead_lag_curve(curves_by_bucket, ax=None, max_series=3):
    """HY correlation against lag, one line per bucket (capped at three).

    Zero-lag is marked because the whole question is which SIDE of it the mass sits
    on: positive lags are the ladder leading futures.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(7.4, 3.6))
    items = list(curves_by_bucket.items())[:max_series]
    for i, (name, curve) in enumerate(items):
        lags = sorted(curve)
        vals = [curve[l] for l in lags]
        ax.plot(lags, vals, color=SERIES[i % len(SERIES)], marker="o",
                markersize=4.5, label=str(name))
        # direct label at the right-hand end (relief for the aqua contrast WARN)
        ax.annotate(f" {name}", xy=(lags[-1], vals[-1]), fontsize=8,
                    color=SERIES[i % len(SERIES)], va="center")
    ax.axvline(0.0, color=BASELINE, linewidth=1.2, zorder=0)
    ax.axhline(0.0, color=BASELINE, linewidth=1.0, zorder=0)
    if len(items) >= 2:
        ax.legend(loc="upper left", ncols=min(len(items), 3))
    return _finish(ax, "Hayashi-Yoshida lead-lag: ladder increments vs futures",
                   "lag (minutes) — positive means the ladder LEADS",
                   "HY correlation",
                   note="Sign-blind about direction: read the peak correlation's "
                        "sign alongside this.")


def league_dotplot(league, ax=None, top=18, value="mean", lo="lo", hi="hi",
                   label="variant", highlight=()):
    """Horizontal dot plot with CI whiskers, one row per variant.

    A dot plot rather than bars: these are point estimates with uncertainty, and
    bars would imply a magnitude read from zero that the CI already carries. Sorted
    by the estimate so the shape of the FAMILY is visible — which is the point of
    publishing the whole grid rather than the winner.
    """
    import matplotlib.pyplot as plt

    df = league.dropna(subset=[value]).copy()
    df = df.sort_values(value, ascending=True).tail(top)
    if ax is None:
        _, ax = plt.subplots(figsize=(8.6, 0.30 * max(len(df), 1) + 1.4))
    y = np.arange(len(df))
    has_ci = lo in df.columns and hi in df.columns
    if has_ci:
        ax.hlines(y, df[lo], df[hi], color=BASELINE, linewidth=2.0, zorder=1)
    colors = [STATUS["good"] if v > 0 else STATUS["critical"] for v in df[value]]
    ax.scatter(df[value], y, s=42, color=colors, zorder=3, edgecolor=SURFACE,
               linewidth=1.2)
    ax.axvline(0.0, color=INK_2, linewidth=1.0, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels([str(s)[:46] for s in df[label]], fontsize=7.5)
    for yy, v, name in zip(y, df[value], df[label]):
        if name in highlight:
            ax.annotate(f"  {v:+.3f}", xy=(v, yy), fontsize=8, va="center",
                        color=INK, fontweight="700")
    return _finish(ax, "Secondary grid: net bp per trade, day-blocked CI",
                   "net bp per trade (positive = profitable after costs)",
                   note="Whole family shown, winners and losers. Zero line is the "
                        "only thing that matters for a pass.")


def placebo_panel(placebos, ax=None, value="mean", label="placebo"):
    """Reference row against every placebo, on one axis.

    The reference is drawn as a rule across the panel so each placebo is read as a
    distance FROM it rather than as an independent number.
    """
    import matplotlib.pyplot as plt

    df = placebos.dropna(subset=[value]).copy()
    if ax is None:
        _, ax = plt.subplots(figsize=(8.0, 0.42 * max(len(df), 1) + 1.5))
    ref_mask = df[label].astype(str).str.startswith("none")
    ref = float(df.loc[ref_mask, value].iloc[0]) if ref_mask.any() else np.nan
    y = np.arange(len(df))[::-1]
    colors = [SERIES[0] if m else SERIES[1] for m in ref_mask]
    ax.barh(y, df[value], height=0.5, color=colors, edgecolor=SURFACE,
            linewidth=2.0)
    if np.isfinite(ref):
        ax.axvline(ref, color=SERIES[0], linewidth=1.4, linestyle=(0, (4, 3)),
                   zorder=0)
    ax.axvline(0.0, color=INK_2, linewidth=1.0, zorder=1)
    ax.set_yticks(y)
    ax.set_yticklabels([str(s)[:52] for s in df[label]], fontsize=8)
    for yy, v in zip(y, df[value]):
        ax.annotate(f" {v:+.3f}", xy=(v, yy), fontsize=8, va="center",
                    color=INK_2)
    return _finish(ax, "Placebos against the reference (dashed rule)",
                   "net bp per trade",
                   note="A placebo near the reference is a failure of the test, "
                        "not a success of the signal.")


def flip_rate_bars(flip_table, ax=None, group="our_confidence",
                   rate="flip_rate", n="n_compared"):
    """Independent-mid flip rate by stratum, with the comparable count on each bar.

    The denominator is drawn on the bar because a flip rate over a handful of
    covered prints is not the same claim as one over thousands, and a bar alone
    hides that completely.
    """
    import matplotlib.pyplot as plt

    df = flip_table.dropna(subset=[rate]).copy()
    if ax is None:
        _, ax = plt.subplots(figsize=(6.8, 0.5 * max(len(df), 1) + 1.5))
    y = np.arange(len(df))[::-1]
    ax.barh(y, df[rate], height=0.5, color=SERIES[0], edgecolor=SURFACE,
            linewidth=2.0)
    ax.axvline(0.5, color=STATUS["critical"], linewidth=1.2,
               linestyle=(0, (4, 3)), zorder=0)
    ax.annotate("coin flip", xy=(0.5, len(df) - 0.4), fontsize=7.5,
                color=STATUS["critical"], ha="center")
    ax.set_yticks(y)
    ax.set_yticklabels([str(s) for s in df[group]], fontsize=8)
    for yy, v, cnt in zip(y, df[rate], df.get(n, [np.nan] * len(df))):
        ax.annotate(f" {v:.1%}" + (f"  (n={int(cnt)})" if np.isfinite(cnt) else ""),
                    xy=(v, yy), fontsize=8, va="center", color=INK_2)
    ax.set_xlim(0, max(0.6, float(df[rate].max()) * 1.35))
    return _finish(ax, "Independent-mid flip rate by stratum",
                   "share of prints whose direction flips on an independent mid",
                   note="A lower bound on disagreement-driven error, not an "
                        "accuracy: both curves can be wrong together.")


def attenuation_curve(net_bp, accuracies=(0.6, 0.7, 0.8, 0.9, 1.0), ax=None):
    """Net edge after the (2a-1) classification-accuracy haircut."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(6.4, 3.2))
    a = np.asarray(accuracies, dtype=float)
    vals = net_bp * (2.0 * a - 1.0)
    ax.plot(a, vals, color=SERIES[0], marker="o")
    ax.axhline(0.0, color=INK_2, linewidth=1.0, zorder=0)
    for aa, vv in zip(a, vals):
        ax.annotate(f"{vv:+.3f}", xy=(aa, vv), fontsize=7.5, color=INK_2,
                    ha="center", va="bottom")
    ax.set_xlim(min(a) - 0.03, max(a) + 0.03)
    return _finish(ax, "Edge after attenuation for classification accuracy",
                   "assumed sign accuracy a", "net bp per trade",
                   note="Signed exposure scales by (2a-1). Direction is "
                        "UNCERTIFIED, so no single point on this line is 'the' answer.")
