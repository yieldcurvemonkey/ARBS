"""The two-book split: label each kink-screen row harvest / dislocation / none.

Implements docs/convexityrv/kink_ledger.md section 4 rule 6 ("the two books")
with the frozen reference gates of docs/cvxsuite/DESIGN.md section 6. Pure
pandas over named columns — no market data, no kernels.

Why these gates exist (the measured deaths they encode, DESIGN.md section 0):

* F3 xsec liquid-tenor fade is dead — median 63d reversion +0.81..+1.14 bp vs
  >= 1.0 bp round trip ("pond equals boat") — so a dislocation entry must
  clear an EXPLICIT expected-net-edge line, not a bare z threshold.
* W4 rac harvest is dead — gross 0.397 < null 0.446, duration in disguise —
  so the harvest book charges ``rac_net`` (risk-adjusted carry NET of
  reversion drag at the FPT horizon), not raw carry.
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
``zs``          float: trailing z-score of the convexity-adjusted structure
                level (756d window per DESIGN.md section 6). POLARITY:
                positive = RICH vs its own trailing window. Harvest gate
                INCLUSIVE upper bound ("z not rich"): ``zs <= harvest_max_z``.
                Dislocation gate two-sided INCLUSIVE: ``|zs| >= disl_min_abs_z``.
``rac_net``     float: rac_net@FPT — risk-adjusted carry net of reversion drag
                at the measured half-life horizon (kink_ledger section 6 row).
                Harvest gate STRICT: ``rac_net > harvest_min_rac_net`` (the
                DESIGN section 5 rule is "rac_net@FPT > 0"; the field says
                "min" but the floor is exclusive).
``sign_agree``  {+1, -1, 0} from ``residuals.sign_agreement``: +1 both methods
                say cheap, -1 both say rich, 0 disagree/too small. Dislocation
                requires membership in {+1, -1} — implemented ``isin((1, -1))``
                because ``!= 0`` evaluates True on NaN and would let a missing
                agreement through.
``tag``         str from ``grids.classify_point``: "meeting" | "convexity" |
                "clean". Dislocation requires EXACTLY ``"clean"``
                (DESIGN section 6: ``tags == "clean"``).
``edge_bp``     float, bp: ``E[reversion]*P(hit) - |carry|*E[FPT]/252 - cost``,
                ALREADY NET OF 1x COST (DESIGN section 6: "after 1x cost";
                3-leg package RT band 2.0–2.6 bp). Dislocation gate STRICT:
                ``edge_bp > disl_min_edge_bp``.

Classification rules
--------------------
* harvest      = ``be_over_rv >= harvest_min_be_over_rv``
                 AND ``zs <= harvest_max_z``
                 AND ``rac_net > harvest_min_rac_net``.
                 (No tag condition: the convexity zone is harvest-eligible —
                 it is only fades that are excluded there.)
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
    """Frozen reference gate config. Defaults = DESIGN.md section 6, verbatim.

    Field order is contractual (DESIGN.md section 3) — callers may construct
    positionally. Inequality per gate is documented in the module docstring:
    ``harvest_min_be_over_rv`` and ``disl_min_abs_z`` are inclusive,
    ``harvest_max_z`` is an inclusive upper bound, ``harvest_min_rac_net`` and
    ``disl_min_edge_bp`` are EXCLUSIVE floors.
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

    # NaN in any numeric gate input compares False -> that book's gate fails.
    harvest = (
        (be >= gates.harvest_min_be_over_rv)
        & (zs <= gates.harvest_max_z)
        & (rac > gates.harvest_min_rac_net)
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
