"""Display-quantity (iceberg) orders: how much was hidden, and how big they were.

Detection happens in the lifecycle kernel, because that is where the state lives.
The rule is Zotikov and Antonov's and it is exact -- no time window, no volume
threshold: an order is an iceberg if a trade against it exceeded its resting
volume, or if it was fully traded and then came back with volume. Both are
possible only because CME preserves the order id across an iceberg's whole life,
and because the trade message carries the **total** matched volume including the
concealed part.

What this module adds is the sizing, and the one statistical subtlety that makes
it non-trivial: **a cancelled iceberg is a censored observation of its own size**.
Its total volume is not what it traded; that is only a lower bound. Averaging the
observed totals therefore biases every estimate downward, and the bias is worst
exactly where it matters, in the tail. The Kaplan-Meier estimator is the standard
fix, applied here with **accumulated volume in the role of survival time** rather
than clock time.

Two things this deliberately does not do:

* **Synthetic icebergs are out of scope.** The paper's rule -- a new limit order
  at the same price and same volume arriving within 0.3 s of the previous
  tranche's execution -- rests on assumptions its own authors call very strong:
  constant peak size, a fixed price, and the next tranche arriving faster than any
  other order at that level. When several candidates collide it yields a *tree* of
  possible icebergs rather than an answer. Native detection is unambiguous;
  bolting an ambiguous detector onto it would make the combined output impossible
  to interpret.
* **Measured caveat: on Databento's normalization, only rule (a) fires.** Across
  2.39 M ZNU6 orders on 2026-07-14, all 668 detections came from a trade
  exceeding the resting volume, and not one came from an order being fully traded
  and returning under the same id -- ``n_refresh`` is zero everywhere. The vendor
  does not appear to re-use the order id across tranches the way the raw feed the
  paper worked from does. Every number here therefore rests on rule (a) alone,
  which detects an iceberg only once it has traded through its displayed size; an
  iceberg cancelled before that is invisible, so the counts are lower bounds.
* **The peak-size solver is not implemented.** Recovering the display quantity
  from an iceberg that began mid-trade requires solving a modular-arithmetic
  disambiguation, and it only pays when you want the tranche size rather than the
  total. The total is what a hidden-liquidity study needs.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "hidden_volume_share",
    "iceberg_summary",
    "km_size_distribution",
]


def iceberg_summary(orders: pd.DataFrame) -> dict:
    """Headline counts for one instrument-day's detected icebergs."""
    if orders.empty or "iceberg" not in orders.columns:
        return {"n_orders": 0, "n_icebergs": 0, "iceberg_share": np.nan,
                "n_refreshes": 0, "iceberg_volume": 0, "volume": 0,
                "iceberg_volume_share": np.nan}
    ice = orders[orders["iceberg"]]
    vol = int(orders["filled_size"].sum())
    ivol = int(ice["filled_size"].sum())
    return {
        "n_orders": int(len(orders)),
        "n_icebergs": int(len(ice)),
        "iceberg_share": float(len(ice) / len(orders)) if len(orders) else np.nan,
        "n_refreshes": int(ice["n_refresh"].sum()) if "n_refresh" in ice else 0,
        "iceberg_volume": ivol,
        "volume": vol,
        "iceberg_volume_share": float(ivol / vol) if vol else np.nan,
    }


def hidden_volume_share(orders: pd.DataFrame) -> dict:
    """How much traded volume came from quantity that was never displayed.

    The displayed part of an iceberg is at most its initial size each time it
    joins the queue; everything it traded beyond that was concealed. This is a
    **lower bound** on hidden volume, because an iceberg that was never detected
    contributes nothing and an iceberg cancelled early hid more than it showed.
    """
    if orders.empty or "iceberg" not in orders.columns:
        return {"traded": 0, "hidden_at_least": 0, "share": np.nan, "n": 0}
    ice = orders[orders["iceberg"]]
    if ice.empty:
        return {"traded": int(orders["filled_size"].sum()),
                "hidden_at_least": 0, "share": 0.0, "n": 0}
    shown = ice["size_initial"].to_numpy(dtype=np.int64) * np.maximum(
        1, ice["n_refresh"].to_numpy(dtype=np.int64) + 1
    )
    traded = ice["filled_size"].to_numpy(dtype=np.int64)
    hidden = np.maximum(0, traded - shown)
    total = int(orders["filled_size"].sum())
    return {
        "traded": total,
        "hidden_at_least": int(hidden.sum()),
        "share": float(hidden.sum() / total) if total else np.nan,
        "n": int(len(ice)),
    }


def km_size_distribution(orders: pd.DataFrame) -> pd.DataFrame:
    """Kaplan-Meier survival of total iceberg volume, with cancellation censored.

    Accumulated volume plays the role of survival time. An iceberg that was fully
    executed is an observed event at its total volume; one cancelled part-way is
    **right-censored** -- all we know is that its true size was at least what it
    traded. Treating those as complete observations biases the size distribution
    downward, most severely in the tail, which is the part a hidden-liquidity
    estimate actually depends on.

    With ``u_1 < ... < u_K`` the distinct observed volumes, ``d_j`` the number of
    *complete* icebergs at ``u_j`` and ``n_j`` the number of icebergs (complete or
    cancelled) whose volume is at least ``u_j``::

        S(v) = prod over {j : u_j >= v} of (1 - d_j / n_j)

    Returns one row per distinct volume with the risk set, the event count and the
    survival estimate.
    """
    cols = ["volume", "n_at_risk", "n_events", "hazard", "survival"]
    if orders.empty or "iceberg" not in orders.columns:
        return pd.DataFrame(columns=cols)
    ice = orders[orders["iceberg"] & (orders["filled_size"] > 0)]
    if ice.empty:
        return pd.DataFrame(columns=cols)

    v = ice["filled_size"].to_numpy(dtype=np.int64)
    # Complete = the order left because it was filled out. Cancelled or still
    # open means the size we saw is a lower bound.
    complete = ice["exit_reason"].astype(str).to_numpy() == "FILLED"

    u = np.unique(v)
    rows = []
    surv = 1.0
    # Descending, because a larger total volume means the iceberg "survived"
    # longer: the risk set at u_j is everything of volume u_j or more.
    for uj in u[::-1]:
        at_risk = int(np.count_nonzero(v >= uj))
        events = int(np.count_nonzero((v == uj) & complete))
        hazard = events / at_risk if at_risk else 0.0
        surv *= (1.0 - hazard)
        rows.append({"volume": int(uj), "n_at_risk": at_risk,
                     "n_events": events, "hazard": hazard, "survival": surv})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("volume").reset_index(drop=True)
