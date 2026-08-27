"""The two-book split: label each kink-screen row harvest / dislocation / none.

Implements docs/convexityrv/kink_ledger.md section 4 rule 6 ("the two books")
with the frozen reference gates of docs/cvxsuite/DESIGN.md section 6. Pure
pandas over named columns — no market data, no kernels.

Why these gates exist (the measured deaths they encode, DESIGN.md section 0):

* F3 xsec liquid-tenor fade is dead — median 63d reversion +0.81..+1.14 bp vs
  >= 1.0 bp round trip ("pond equals boat") — so a dislocation entry must
  clear an EXPLICIT expected-net-edge line, not a bare z threshold.
* W4 rac harvest is dead — gross 0.397 < null 0.446, duration in disguise —
  so the harvest book charges the harvest holder's own risk-adjusted carry
  (``-rac_net`` — the receive-belly side of the level-long-signed column,
  NET of reversion drag at the FPT horizon), not raw carry.
* Flow-mark fades are pre-dead program-wide (L-0085/L-0088), so the
  dislocation book additionally requires the ``clean`` tag: meeting-zone and
  convexity-zone points are never faded (the convexity zone is harvest-only,
  kink_ledger section 2.4/4.4).

Expected columns (EXACT names — the kink_screen composition layer must match)
-----------------------------------------------------------------------------
``be_over_rv``  float, unitless: sigma_BE / sigma_rlzd, both bp/day (rent line
                over ex-roll realized vol). Harvest gate INCLUSIVE:
                ``be_over_rv >= harvest_min_be_over_rv``. Default 1.17 is
                Citi's published curve-pair anchor (1.17–1.38) — a curve-pair
                anchor, not validated on micro-flies (DESIGN.md section 4).
``zs``          float: trailing z-score of the COMPOSED MICRO-FLY level
                (``2*belly - front - back`` on convexity-adjusted legs, 756d
                window per DESIGN.md section 6 — sum-zero weights, so the z
                is duration-free by construction). POLARITY (rate space,
                kink_ledger section 0): positive = fly level above its own
                mean (belly CHEAP — an upward kink; reversion downward
                expected); negative = belly RICH. Harvest gate (RECEIVE-belly
                side — DESIGN section 6a item 5): "not rich" for the
                SHORT-the-level holder is an INCLUSIVE LOWER bound,
                ``zs >= -harvest_max_z`` ("do not harvest what has already
                run" means do not SHORT a level already deep BELOW its mean).
                Dislocation gate two-sided INCLUSIVE:
                ``|zs| >= disl_min_abs_z`` (symmetric — either side of an
                extreme fades toward the mean).
``rac_net``     float: rac_net@FPT — risk-adjusted carry net of reversion drag
                at the measured half-life horizon (kink_ledger section 6 row),
                SIGNED FOR THE LONG-THE-FLY-LEVEL (pay-belly) HOLDER. The
                column semantics are deliberately UNCHANGED by the 6a-item-5
                re-signing: the screen table, the panel builders and this
                gate all keep the one long-signed convention, and it is the
                GATE that reads the other side. The harvest holder
                (receive-belly) earns exactly ``-rac_net``, so the harvest
                gate is STRICT on that side:
                ``-rac_net > harvest_min_rac_net`` (the DESIGN section 5
                rule "rac_net@FPT > 0" read on the harvest holder's own
                book; the field says "min" but the floor is exclusive).
``sign_agree``  {+1, -1, 0} from ``residuals.sign_agreement``: +1 both methods
                say cheap, -1 both say rich, 0 disagree/too small. Dislocation
                requires membership in {+1, -1} — implemented ``isin((1, -1))``
                because ``!= 0`` evaluates True on NaN and would let a missing
                agreement through.
``tag``         str from ``grids.classify_point``: "meeting" | "convexity" |
                "clean". Dislocation requires EXACTLY ``"clean"``
                (DESIGN section 6: ``tags == "clean"``).
``edge_bp``     float, bp of the belly=+2 fly level L, on the BOOK'S OWN
                CLOCK (DESIGN section 6a item 2): ``e_rev * p_hit_h -
                |carry_bp_day| * min(e_fpt, h) - cost_rt_bp`` with
                h = max_hold_bd = 63 (the frozen dislocation exit) and
                ``p_hit_h`` the probability of reversion WITHIN h (screen:
                fraction of MC paths with hit <= h; panel: the analytic
                ``1 - exp(-h/e_fpt)``), ALREADY NET OF 1x COST (DESIGN
                section 6: "after 1x cost"; 3-leg package RT band 2.0–2.6 bp
                on the belly=+2 L). Dislocation gate STRICT:
                ``edge_bp > disl_min_edge_bp``.

The harvest side (DESIGN section 6a item 5 — read before touching a sign)
-------------------------------------------------------------------------
On a FLY, harvest = selling local convexity = RECEIVING the belly = SHORT
the level ``L = 2b - f - k``. The pair-shape harvest gate (cvx_kink_harvest,
where the level-LONG steepener IS the short-convexity side) was transplanted
here verbatim and gated the WRONG side: ``(rac_net > 0) & (zs <= +max_z)``
selects rows where the LONG-the-level holder earns and the receive-belly
harvest holder bleeds (rev_4 finding 1: the planted ``{zs=-3, rac_net=+5}``
row classified harvest — shorting a level 3 sigma BELOW its mean with
receive-side carry -5). The re-signed gates read the SAME long-signed
columns for the receive side: harvest carry is ``-rac_net`` and "not rich"
for a short is a LOWER bound on ``zs``. Screen label only — no QDB backtest
ever traded the pre-fix label.

Classification rules
--------------------
* harvest      = ``be_over_rv >= harvest_min_be_over_rv``
                 AND ``zs >= -harvest_max_z``
                 AND ``-rac_net > harvest_min_rac_net``.
                 (RECEIVE-belly side throughout — see "The harvest side"
                 above. No tag condition: the convexity zone is
                 harvest-eligible — it is only fades that are excluded
                 there.)
* dislocation  = ``|zs| >= disl_min_abs_z`` AND ``sign_agree in {+1, -1}``
                 AND ``tag == "clean"`` AND ``edge_bp > disl_min_edge_bp``.
* none         = everything else.

PRECEDENCE: a row passing both books is labelled ``"dislocation"``. The
dislocation conditions are the stricter, more specific set (extreme |z|,
dual-method sign agreement, clean tag, positive expected net edge) and its
exit discipline (zero-cross / +2SD / max-hold, DESIGN section 5) must govern a
live extreme; harvest membership is a standing monthly-reform decision the
composition layer re-evaluates anyway.

NaN handling: any NaN gate input fails that book's gates and the row falls to
``"none"`` — a conservative refusal to enter, matching citi_rule's
NaN-refuse conjunction semantics (``_at_least``, mutation-tested there).
Missing COLUMNS, by contrast, raise ``KeyError`` loudly.

What this is NOT
----------------
* NOT an entry engine. The QDB reference strategies re-derive their entries
  from the same columns at t-1 with lag-1 fills (DESIGN section 5); this
  function labels screen rows for the ledger print.
* NOT a registered fade family (L-0088 stands): the dislocation book is
  machinery awaiting non-flow state data (supply/LDI/index calendars —
  DESIGN section 7). A "dislocation" label here is a screen classification,
  not an aliveness claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

__all__ = [
    "BookGates",
    "classify_books",
    "REQUIRED_COLUMNS",
    "BOOK_HARVEST",
    "BOOK_DISLOCATION",
    "BOOK_NONE",
    "TAG_CLEAN",
]

BOOK_HARVEST = "harvest"
BOOK_DISLOCATION = "dislocation"
BOOK_NONE = "none"

#: The only tag the dislocation book fades (grids.classify_point vocabulary).
TAG_CLEAN = "clean"

#: Exact column names ``classify_books`` reads — the composition contract.
REQUIRED_COLUMNS: Tuple[str, ...] = (
    "be_over_rv",
    "zs",
    "rac_net",
    "sign_agree",
    "tag",
    "edge_bp",
)


@dataclass(frozen=True)
class BookGates:
    """Frozen reference gate config. Defaults = DESIGN.md section 6, verbatim
    (section 6a item 5 re-signed the harvest gate ORIENTATION, not the
    values).

    Field order is contractual (DESIGN.md section 3) — callers may construct
    positionally. Inequality per gate is documented in the module docstring:
    ``harvest_min_be_over_rv`` and ``disl_min_abs_z`` are inclusive,
    ``harvest_max_z`` is the MAGNITUDE of an inclusive LOWER bound (the gate
    reads ``zs >= -harvest_max_z`` — the receive-belly "not rich" side),
    ``harvest_min_rac_net`` is an EXCLUSIVE floor on the RECEIVE side's
    carry ``-rac_net``, and ``disl_min_edge_bp`` is an EXCLUSIVE floor.
    """

    harvest_min_be_over_rv: float = 1.17
    harvest_max_z: float = 0.5
    harvest_min_rac_net: float = 0.0
    disl_min_abs_z: float = 2.0
    disl_min_edge_bp: float = 1.0


def classify_books(df: pd.DataFrame, gates: BookGates) -> pd.Series:
    """Label each kink-screen row ``harvest`` / ``dislocation`` / ``none``.

    See the module docstring for the exact column contract, gate inequalities,
    NaN refusal, and the dislocation-over-harvest precedence. Returns an
    object-dtype Series named ``"book"`` on ``df``'s own index.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"classify_books: missing required column(s) {missing}; "
            f"expected exactly {list(REQUIRED_COLUMNS)}"
        )

    be = df["be_over_rv"]
    zs = df["zs"]
    rac = df["rac_net"]
    agree = df["sign_agree"]
    tag = df["tag"]
    edge = df["edge_bp"]

    # NaN in any numeric gate input compares False -> that book's gate fails
    # (a NaN rac_net negates to NaN and still compares False).
    # HARVEST IS THE RECEIVE-BELLY SIDE (DESIGN 6a item 5): the gate reads
    # the level-long-signed columns for the SHORT-the-level holder — its
    # carry is -rac_net, and "not rich" for a short is a LOWER bound on zs.
    # The rac_net COLUMN itself is never re-signed anywhere.
    harvest = (
        (be >= gates.harvest_min_be_over_rv)
        & (zs >= -gates.harvest_max_z)
        & (-rac > gates.harvest_min_rac_net)
    )
    dislocation = (
        (zs.abs() >= gates.disl_min_abs_z)
        # isin, NOT `!= 0`: NaN != 0 is True and would pass a missing agreement.
        & agree.isin((1, -1))
        & tag.eq(TAG_CLEAN)
        & (edge > gates.disl_min_edge_bp)
    )

    labels = np.select(
        [dislocation.to_numpy(dtype=bool), harvest.to_numpy(dtype=bool)],
        [BOOK_DISLOCATION, BOOK_HARVEST],
        default=BOOK_NONE,
    )
    return pd.Series(labels, index=df.index, name="book", dtype=object)
