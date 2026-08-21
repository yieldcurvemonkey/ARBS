"""One visual language for the ETF-rebalance figure pack.

Why a shared module rather than per-figure styling
---------------------------------------------------
This pack exists to let a reader tell, at a glance, which panels show something real and
which show a null doing the same job. That only works if **colour follows the entity and
never the rank**: the richness control must be the same green in every figure it appears
in, and a placebo must never borrow the thesis's blue because it happened to be plotted
first. Cycling a default colour list defeats the entire point of the pack.

The palette is Okabe-Ito, which is colour-vision-deficiency safe by construction, with
fixed role assignments below.

Rules this module enforces, and why each one matters here
----------------------------------------------------------
* **Never a dual axis.** Two y-scales let any two series be made to look related. Use
  :func:`panels` and give each measure its own axes, or index both to a common base.
* **Signed quantities get a diverging map with a NEUTRAL midpoint** (``coolwarm``,
  centred at zero). An IC that is positive at one horizon and negative at another must
  show that at a glance; a sequential or rainbow map hides the sign change.
* **Magnitudes get one hue, light to dark** (``Blues``). Counts and sample sizes are
  magnitudes.
* **Text wears ink, not the series colour.** A coloured mark beside a label carries the
  identity; a coloured label just lowers contrast.
* **Every effect panel carries its null.** :func:`annotate_null` exists so that showing
  the control alongside the thesis is the path of least resistance rather than an extra
  step someone skips.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

import matplotlib as mpl
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- palette

#: Okabe-Ito. CVD-safe by construction; do not substitute ad hoc hues.
OKABE_ITO = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "sky": "#56B4E9",
    "yellow": "#F0E442",
    "black": "#000000",
}

#: Role -> colour. FIXED across the whole pack. A role is an entity, not a position in a
#: plotting order, so a figure that drops a series must not repaint the survivors.
ROLE = {
    # the hypothesis: anything read out of an ETF holdings file
    "thesis": OKABE_ITO["blue"],
    # the control: the bond's own richness against its local curve. Reads no ETF data.
    "control": OKABE_ITO["green"],
    # the calendar-only null: deletion / addition / month-end. Reads no ETF data either.
    "null": OKABE_ITO["orange"],
    # matched placebos - boundaries where nothing happens
    "placebo": "#8C8C8C",
    # the cost line, which is what usually kills these
    "cost": OKABE_ITO["vermillion"],
    # a flow that was VERIFIED in the holdings (e.g. TLT shedding a deleted bond)
    "verified": OKABE_ITO["purple"],
    # a second thesis variant when one is needed
    "thesis_alt": OKABE_ITO["sky"],
}

INK = {"primary": "#1A1A1A", "secondary": "#4D4D4D", "muted": "#7A7A7A", "grid": "#D8D8D8"}

#: Signed quantities (IC, active weight, P&L). Two hues through a neutral midpoint.
DIVERGING = "coolwarm"
#: Magnitudes (counts, n, |size|). One hue, light to dark.
SEQUENTIAL = "Blues"


def use() -> None:
    """Install the pack's rcParams. Call once at the top of a figure script."""
    mpl.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": INK["secondary"],
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": INK["grid"],
        "grid.linewidth": 0.6,
        "grid.alpha": 0.9,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.labelsize": 9.5,
        "axes.labelcolor": INK["secondary"],
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "xtick.color": INK["secondary"],
        "ytick.color": INK["secondary"],
        "text.color": INK["primary"],
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "lines.linewidth": 2.0,
        "lines.markersize": 5.0,
        "font.size": 9.5,
        # A default cycle exists only as a backstop. Address ROLE[...] explicitly.
        "axes.prop_cycle": mpl.cycler(color=[ROLE["thesis"], ROLE["control"], ROLE["null"],
                                             ROLE["placebo"], ROLE["cost"], ROLE["verified"]]),
    })


def panels(nrows: int = 1, ncols: int = 1, *, w: float = 6.2, h: float = 3.8, **kw):
    """A figure sized per panel. Never returns a twinned axis -- see the module docstring."""
    fig, axes = plt.subplots(nrows, ncols, figsize=(w * ncols, h * nrows), **kw)
    return fig, axes


def zero_line(ax, **kw) -> None:
    ax.axhline(0, color=INK["secondary"], lw=0.9, zorder=1, **kw)


def cost_band(ax, cost_bp: float, *, label: str = "measured round trip") -> None:
    """Draw the cost hurdle. Almost every honest chart in this pack needs it.

    A gross-P&L panel without the cost line invites the reader to a conclusion the number
    does not support, which is the single most common way a research figure misleads.
    """
    ax.axhline(cost_bp, color=ROLE["cost"], ls="--", lw=1.6, label=f"{label} ({cost_bp:.2f}bp)")
    ax.axhline(-cost_bp, color=ROLE["cost"], ls="--", lw=1.6)


def annotate_null(ax, text: str, *, loc: str = "lower right") -> None:
    """Stamp the panel with what the null did. Keeps the honest comparison visible."""
    xy = {"lower right": (0.98, 0.03, "right", "bottom"),
          "lower left": (0.02, 0.03, "left", "bottom"),
          "upper right": (0.98, 0.97, "right", "top"),
          "upper left": (0.02, 0.97, "left", "top")}[loc]
    ax.text(xy[0], xy[1], text, transform=ax.transAxes, ha=xy[2], va=xy[3],
            fontsize=8, color=INK["muted"])


def finish(fig, path, *, caption: Optional[str] = None) -> str:
    """Save, and record the caption beside it so the pack can be assembled from disk."""
    import pathlib

    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p)
    if caption:
        p.with_suffix(".caption.txt").write_text(caption.strip() + "\n", encoding="utf-8")
    plt.close(fig)
    return str(p)
