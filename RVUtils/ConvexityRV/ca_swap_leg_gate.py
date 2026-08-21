r"""The convexity panel's gate tests the futures leg. Nothing tests the swap leg.

``gate_ok`` is ``gate_covered & gate_resolved & gate_settle_agrees``, and all
three are statements about the **futures** side: is the strip deep enough, do the
keys resolve, and does the Q20 curve's own IMM×IMM forward agree with the raw SR3
settle. Every one of them can pass while the other half of
``CA = pack_rate − swap_rate`` is unusable.

It is not hypothetical. Measured on the shipped panel, Golds (rank 17, a 4–5 year
forward window):

======  =====  ==========  ==============  ===============  ===============
era     n      frac CA<0   median CA (bp)  median swap (%)  median pack (%)
======  =====  ==========  ==============  ===============  ===============
2019    75     0.760       −2.57           —                —
2020    251    **0.928**   **−19.93**      **0.581**        **0.286**
2022-26 1,135  **0.000**   +14.66          3.520            3.641
======  =====  ==========  ==============  ===============  ===============

A convexity adjustment is bounded below by zero in any arbitrage-free model, so
a median of −19.93 bp is not a price. And the futures leg is **not** the problem:
in that same era the two independent futures sources agree to a median of
0.029 bp (``|ca_bp_q20 − ca_bp_settle|``) and ``max_settle_diff_bp`` runs 0.310,
*better* than the 1.383 of 2026. The swap leg is carrying it — the curve says
0.581 % for a forward the futures price at 0.286 %.

The reason is the era, not the code. USD swaps in 2019–2020 were LIBOR-based;
SOFR discounting only switched in October 2020, and a SOFR swap market at four-
to five-year forward starts barely existed before then. ``USD-SOFR-1D`` built
from Citi Velocity quotes in that window is thin where this panel needs it most.

**Consequence.** 1,629 of 29,643 gated rows (5.50 %) carry ``ca_bp < −5 bp``, and
**385 of them are Blues and Golds in 2019–2020**. Anyone filtering on ``gate_ok``
alone and reading the panel from 2018 gets those. Nothing published from this
branch does — W2b, W3 and the screeners all start 2021-01-01 — but the panel
ships the whole history and the gate does not warn.

This module adds the missing test. It deliberately does **not** change
``gate_ok``: that column has a published meaning and quietly widening it would
silently move numbers other work has already quoted.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "SWAP_LEG_MIN_DATE",
    "add_swap_leg_gate",
    "swap_leg_report",
]

#: The USD SOFR swap curve is not trustworthy at multi-year forward starts before
#: this. SOFR discounting switched in October 2020 and the market took months
#: more to populate the long forwards; 2021-01-01 is the first date at which every
#: colour in this panel behaves (Golds goes 0.928 negative in 2020 and 0.033 in
#: 2021). A date floor, not a quality score, because the failure is an era.
SWAP_LEG_MIN_DATE = pd.Timestamp("2021-01-01")


def add_swap_leg_gate(panel: pd.DataFrame, *,
                      min_date: pd.Timestamp = SWAP_LEG_MIN_DATE,
                      max_negative_bp: float = -5.0) -> pd.DataFrame:
    """Attach ``gate_swap_sane`` and ``gate_ok_full``. Does not modify ``gate_ok``.

    ``gate_swap_sane`` is False when either:

    * the observation predates :data:`SWAP_LEG_MIN_DATE`, or
    * ``ca_bp`` is below ``max_negative_bp``.

    The second is a **backstop, not a filter on the sign**. Small negative
    readings are expected wherever the true adjustment is near zero — the front
    colours in a low-vol regime sit at a median of 0.098 bp (Whites), and
    symmetric quote noise flips that sign often. Dropping every negative reading
    would be fitting the theory rather than measuring the market. What is
    excluded is only the magnitude that no arbitrage-free model can produce.

    ``gate_ok_full = gate_ok & gate_swap_sane`` is the column a consumer reading
    the full history should use.
    """
    out = panel.copy()
    d = pd.to_datetime(out["date"])
    sane = (d >= pd.Timestamp(min_date))
    if "ca_bp" in out.columns:
        sane &= ~(out["ca_bp"] < float(max_negative_bp))
    out["gate_swap_sane"] = sane.to_numpy()
    if "gate_ok" in out.columns:
        out["gate_ok_full"] = (out["gate_ok"].to_numpy() & out["gate_swap_sane"].to_numpy())
    return out


def swap_leg_report(panel: pd.DataFrame) -> pd.DataFrame:
    """Per (year, colour): how many gated rows the swap-leg test would remove.

    Reported rather than applied silently, because a filter nobody can see the
    effect of is indistinguishable from a filter nobody applied.
    """
    g = add_swap_leg_gate(panel)
    g = g[g.get("gate_ok", True)]
    g = g.assign(year=pd.to_datetime(g["date"]).dt.year)
    rep = (g.groupby(["year", "colour"])
             .agg(n=("ca_bp", "size"),
                  dropped=("gate_swap_sane", lambda s: int((~s).sum())),
                  frac_neg=("ca_bp", lambda s: float((s < 0).mean())),
                  ca_median=("ca_bp", "median"))
             .reset_index())
    rep["frac_dropped"] = rep["dropped"] / rep["n"]
    return rep
