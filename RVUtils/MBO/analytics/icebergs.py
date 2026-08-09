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

Three things worth knowing before reading a number out of here:

* **Synthetic icebergs are detected separately and are a weaker measurement.**
  :func:`detect_synthetic` implements the paper's second rule -- a new limit order
  at the same price and same volume arriving within 0.3 s of the previous
  tranche's execution -- and it rests on assumptions its own authors call very
  strong: constant peak size, a fixed price, and the next tranche arriving faster
  than any other order at that level. Where native detection is a structural fact
  about one order id, synthetic detection is a guess about which of several
  look-alike orders belongs to whom, so the two must never be pooled into one
  count without saying which rule produced each row. Measured on ZNU6 it finds
  **less than chance** -- fewer chains than a surrogate built to contain none --
  which :func:`detect_synthetic` documents in full.
* **Measured caveat: on Databento's normalization, only rule (a) fires.** Across
  2.39 M ZNU6 orders on 2026-07-14, all 668 detections came from a trade
  exceeding the resting volume, and not one came from an order being fully traded
  and returning under the same id -- ``n_refresh`` is zero everywhere. The vendor
  does not appear to re-use the order id across tranches the way the raw feed the
  paper worked from does. Every number here therefore rests on rule (a) alone,
  which detects an iceberg only once it has traded through its displayed size; an
  iceberg cancelled before that is invisible, so the counts are lower bounds.
  That vendor behaviour is precisely why :func:`detect_synthetic` earns its keep:
  a broker-managed iceberg reaches this data as a run of unrelated order ids, and
  the same-id rule cannot see it at all.
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
    "SYNTHETIC_CHAIN_COLUMNS",
    "SYNTHETIC_DT_S",
    "SYNTHETIC_MIN_TRANCHES",
    "detect_synthetic",
    "hidden_volume_share",
    "iceberg_summary",
    "km_size_distribution",
    "synthetic_summary",
]

#: The paper's own window: "for synthetic icebergs, dt was set to 0.3 seconds".
#: It was fitted to one instrument (ESU19) over one training day in 2019, and the
#: authors explicitly decline to claim it transfers -- "an extensive study of the
#: model robustness is required to claim its applicability on other instruments
#: and time spans". Treat it as a starting point to be swept, not a constant.
SYNTHETIC_DT_S = 0.3

#: "Minimum tranches per iceberg is a tunable parameter", default 3. It is the
#: only real defence against the false positives the rule invites, and the paper's
#: headline hidden-volume share moves from 14.3% to 3.3% as it is raised -- so a
#: synthetic volume share quoted without its ``min_tranches`` is meaningless.
SYNTHETIC_MIN_TRANCHES = 3

#: One row per detected chain. Fixed, so an empty result concatenates with a
#: non-empty one without a caller having to care which it got.
SYNTHETIC_CHAIN_COLUMNS = (
    "first_ts", "last_ts", "side", "price", "size", "n_tranches", "total_volume",
    "complete", "status", "span_ns", "n_alt_children", "n_contested",
    "ended_by_contest", "ambiguous", "n_native_tranches",
    "first_order_id", "last_order_id",
)

_CHAIN_DTYPES = {
    "first_ts": "datetime64[ns, UTC]",
    "last_ts": "datetime64[ns, UTC]",
    "side": "object",
    "price": "float64",
    "size": "int64",
    "n_tranches": "int64",
    "total_volume": "int64",
    "complete": "bool",
    "status": "object",
    "span_ns": "int64",
    "n_alt_children": "int64",
    "n_contested": "int64",
    "ended_by_contest": "bool",
    "ambiguous": "bool",
    "n_native_tranches": "int64",
    "first_order_id": "uint64",
    "last_order_id": "uint64",
}

#: What ``detect_synthetic`` needs on the order frame. ``price_idx`` is used in
#: preference to ``price`` for the same-price test when it is present, and is not
#: required.
_SYNTHETIC_REQUIRED = (
    "order_id", "side", "price", "size_initial", "entry_ts", "exit_ts",
    "filled_size", "exit_reason", "iceberg",
)

#: A chain ends when its last tranche is cancelled rather than traded out.
_CANCELLED_REASONS = ("CANCELLED", "PARTIAL_FILL_CANCELLED")


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


def km_size_distribution(orders: pd.DataFrame,
                         complete: Optional[pd.Series] = None) -> pd.DataFrame:
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

    **On natively-detected icebergs the censoring is currently uninformative, and
    that is a property of the detector rather than of this function.**  Rule (a)
    fires precisely when a trade exceeds an order's resting size, so a detected
    iceberg has ``filled_size > size_initial`` by construction and the lifecycle
    kernel labels any such order ``FILLED`` -- including one whose owner pulled it
    with hidden quantity still behind.  The default mask therefore marks nearly
    every native iceberg as an event, the censoring machinery buys nothing, and
    the estimate collapses to the empirical tail.  Pass ``complete`` explicitly
    where a better completion signal exists; the synthetic chains carry one.
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
    if complete is None:
        done = ice["exit_reason"].astype(str).to_numpy() == "FILLED"
    else:
        done = np.asarray(
            complete.reindex(ice.index) if hasattr(complete, "reindex") else complete,
            dtype=bool,
        )

    u = np.unique(v)
    rows = []
    surv = 1.0
    # **Ascending**, and the direction is the whole estimator.  An earlier version
    # accumulated the product downward from the largest volume, which puts the
    # terminal (1 - 1/1) = 0 factor into every row and returns a column of zeros.
    # It shipped, and its four tests could not tell: one asserted only that the
    # result was monotone non-increasing, which all-zeros satisfies.  Known
    # answer: three uncensored icebergs of 10, 20 and 30 give 0.667, 0.333, 0.
    for uj in u:
        at_risk = int(np.count_nonzero(v >= uj))
        events = int(np.count_nonzero((v == uj) & done))
        hazard = events / at_risk if at_risk else 0.0
        surv *= (1.0 - hazard)
        rows.append({"volume": int(uj), "n_at_risk": at_risk,
                     "n_events": events, "hazard": hazard, "survival": surv})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("volume").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# synthetic (broker-managed) icebergs -- arXiv:1909.09495 section 3.2
# --------------------------------------------------------------------------- #

def _empty_chains() -> pd.DataFrame:
    """The chain frame with no rows but every column and dtype in place."""
    return pd.DataFrame(
        {c: pd.Series([], dtype=_CHAIN_DTYPES[c]) for c in SYNTHETIC_CHAIN_COLUMNS}
    )


def _ns(frame: pd.DataFrame, col: str) -> np.ndarray:
    """Nanoseconds since epoch, refusing anything that is not a real timestamp.

    A null timestamp cast through ``int64`` becomes the most negative integer
    there is, which lands inside somebody's ``dt`` window and produces a link out
    of nothing. Raising is the only safe response.
    """
    s = frame[col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        raise TypeError(
            f"{col!r} must be a datetime64 column, got {s.dtype}; "
            "pass the frame from replay_lifecycle, or convert with pd.to_datetime"
        )
    if s.isna().any():
        raise ValueError(
            f"{int(s.isna().sum())} rows have a null {col}; a tranche with no "
            "arrival or removal time cannot be windowed -- drop those rows before "
            "calling, so the exclusion is yours and not a silent one here"
        )
    return s.astype("int64").to_numpy()


def detect_synthetic(orders: pd.DataFrame,
                     dt_s: float = SYNTHETIC_DT_S,
                     min_tranches: int = SYNTHETIC_MIN_TRANCHES) -> pd.DataFrame:
    """Chains of look-alike orders that behave like one broker-managed iceberg.

    A synthetic (ISV-managed) iceberg is refilled by the *broker*, not the
    exchange, so every tranche reaches the feed as a **new order id**. The
    same-order-id rule that makes native detection exact therefore cannot see one
    at all, and Zotikov and Antonov fall back to a timing rule: a new limit order
    at the **same price and same volume** as the previous tranche, arriving within
    ``dt`` of that tranche being traded out and removed, is treated as its
    refill. Their ``dt`` was 0.3 s and their minimum chain length 3.

    This is a far weaker instrument than the native rule, and the docstring is
    longer than the code because every one of the following is a way to be wrong.

    **The rule produces a tree, not an answer, and this function resolves it.**
    The paper's own words: "our very strong assumption is that the next tranche
    arrives faster than any other new limit order, so for each tranche there is
    only one child", and where that fails, "every path from all leaves to the root
    (a chain) is a possible iceberg". Two resolutions were available. The paper's
    is to keep every path and weight it ``1/h``. This function does not, for three
    reasons: those chains **overlap**, so the returned ``total_volume`` column
    would double count and any hidden-volume share summed from it would be wrong
    unless every caller re-applied the weights exactly right; the path count is
    exponential in a dense cluster, which is precisely the regime where the rule
    is least trustworthy; and a deterministic answer plus an honest ambiguity
    count lets a caller do something **stronger** than weighting -- throw the
    ambiguous chains away entirely and see whether the conclusion survives. The
    paper's weighted treatment remains available on the subset where it is
    vacuous: filter to ``~ambiguous`` and every weight is 1 by construction.

    The deterministic rule, stated so it can be argued with:

    * each tranche takes the **earliest-arriving** eligible successor, which is
      the paper's assumption read literally;
    * when two tranches claim the same successor, it goes to the one that was
      removed **latest** (the nearest predecessor), ties broken by later arrival
      and then by larger order id;
    * the tranche that loses that contest gets no successor at all, and its chain
      ends there. ``ended_by_contest`` marks it, and this matters more than it
      looks: such a chain's last tranche was traded out with a refill following
      inside ``dt``, so it is reported ``complete`` **only because the refill was
      awarded elsewhere**. Read ``complete`` on a contested chain as an artefact
      of the resolution, not as a fact about the market.

    ``n_alt_children`` counts eligible successors the chain declined, summed over
    its tranches; ``n_contested`` counts its tranches that more than one
    predecessor claimed; ``ambiguous`` is true when any of the three fired.

    **What is deliberately excluded, and why**, because each would manufacture
    links:

    * orders that arrived in the session **snapshot** -- their ``entry_ts`` is the
      snapshot's, not an arrival, so a whole book's worth of them would sit inside
      one ``dt`` window;
    * orders that **moved price** while resting -- the frame records where they
      ended, not where they joined, so the same-price test would be asked about
      the wrong level;
    * a predecessor that was not **fully traded**. The paper's rule is trade *and*
      removal; an order cancelled after a partial fill is a cancellation, and
      under the paper's completion rule it ends the iceberg rather than continuing
      it.

    Ordering is by ``(entry_ts, entry_seq, order_id)`` and a successor must be
    strictly later in it than its predecessor, so a chain cannot revisit a tranche
    even when a whole packet shares one nanosecond.

    **The paper's stated blind spots, which are not implementation gaps and cannot
    be closed by tuning:**

    * "We only detect orders that have constant peak size." An iceberg whose
      tranches vary in size, or which walks its price, is undetectable here.
    * "If the iceberg is not a multiple of the display quantity, the last tranche
      will be smaller than all the previous tranches in volume, hence its
      detection using the current approach does not seem to be possible." The
      final, smaller tranche is not merely missed -- it cannot be seen at all.
    * Consequently **every count and every volume this returns is a lower bound**,
      and the bound is loosest exactly where the hidden size is largest.

    And one blind spot in the other direction, which the paper's assumption
    implies but does not spell out: at a busy level with a common size -- size 1
    on a front Treasury contract, say -- independent traders replacing the same
    quantity within 0.3 s are **indistinguishable** from tranches of one iceberg.
    There is no fix inside the rule. ``min_tranches``, the ambiguity columns and a
    sweep over ``dt_s`` are the only defences, and a share that moves a lot with
    ``dt_s`` is measuring the level's arrival rate rather than an iceberg.

    **Measured, and it is the reason not to quote the headline on its own.** On
    ZNU6, 2026-07-14, 2.39 M orders: at ``min_tranches=3`` this returns 4,191
    chains over 14,114 tranches and 2.3% of traded volume -- **below** the paper's
    3.3% to 14.3% band, not inside it -- with 96% of chains flagged ``ambiguous``
    and 60% of them
    of size one. Then run the same rule against a surrogate that keeps every
    timestamp, every price level and every level's size composition and permutes
    only **which order held which size**, so that no real iceberg can survive it:
    the surrogate returns *more*, a mean of 5,118 chains and 82 k lots over eight
    seeds (range 5,024 to 5,193) against the real 4,191 and 57 k. Restricting to
    chains of size above one is the only cut where the real data leads at all, by
    13% at ``min_tranches=3`` and by 7% at 4, the latter inside the surrogate's
    own spread. **On that instrument-day the output is not evidence of hidden
    liquidity**, and a share quoted from it would have been a measurement of how
    often ZN replaces the same size at the same price. The rule is implemented
    faithfully; what the numbers mean is the caller's problem, and this is the
    null that settles it::

        idx = orders.groupby(["side", "price_idx"], observed=True).ngroup()
        # permute size_initial within each idx group, then re-run and compare

    Nothing here is evidence about SR3 or about any other session. The authors
    validated the rule on one instrument over two days and declined to generalise.

    Returns one row per chain, sorted by first arrival, with
    :data:`SYNTHETIC_CHAIN_COLUMNS`. Chains are **disjoint**: a tranche belongs to
    at most one, so volumes add.
    """
    dt_s = float(dt_s)
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError(
            f"dt_s must be a positive number of seconds, got {dt_s!r}; the "
            "paper's value is 0.3"
        )
    min_tranches = int(min_tranches)
    if min_tranches < 2:
        raise ValueError(
            f"min_tranches must be at least 2, got {min_tranches}; one order is "
            "not a chain, and the paper's default is 3"
        )
    if orders is None or len(orders) == 0:
        return _empty_chains()

    missing = [c for c in _SYNTHETIC_REQUIRED if c not in orders.columns]
    if missing:
        raise KeyError(
            f"detect_synthetic needs {missing} on the order frame; pass "
            "RVUtils.MBO.lifecycle.replay_lifecycle(...).orders, which carries them"
        )
    for col in ("symbol", "instrument_id"):
        if col in orders.columns:
            n_distinct = int(orders[col].nunique(dropna=False))
            if n_distinct > 1:
                raise ValueError(
                    f"detect_synthetic was handed {n_distinct} distinct {col} "
                    "values; order ids and price ladders are per instrument, so "
                    "pooling them invents chains out of coincidences -- group by "
                    f"{col} and call this once per instrument-day"
                )

    # -- eligibility -------------------------------------------------------- #
    keep = orders["size_initial"].to_numpy(dtype=np.int64) > 0
    if "from_snapshot" in orders.columns:
        keep &= ~orders["from_snapshot"].to_numpy(dtype=bool)
    if "n_price_move" in orders.columns:
        keep &= orders["n_price_move"].to_numpy(dtype=np.int64) == 0
    sub = orders.loc[keep]
    n = len(sub)
    if n == 0:
        return _empty_chains()

    entry = _ns(sub, "entry_ts")
    exit_ = _ns(sub, "exit_ts")
    if np.any(exit_ < entry):
        raise ValueError(
            f"{int(np.count_nonzero(exit_ < entry))} orders exit before they "
            "enter; the dt window is measured forward from removal and would run "
            "backwards on those rows -- this frame is not a lifecycle replay"
        )

    side = sub["side"].to_numpy()
    price = sub["price"].to_numpy(dtype=np.float64)
    size = sub["size_initial"].to_numpy(dtype=np.int64)
    filled = sub["filled_size"].to_numpy(dtype=np.int64)
    oid = sub["order_id"].to_numpy(dtype=np.uint64)
    reason = sub["exit_reason"].astype(str).to_numpy()
    native = sub["iceberg"].to_numpy(dtype=bool).astype(np.int64)

    # The same-price test runs on the tick index where one is available: SR3's
    # 0.005 tick is not representable in binary floating point, so on prices it
    # would be an equality test that is only nearly true.
    level = (sub["price_idx"].to_numpy(dtype=np.int64) if "price_idx" in sub.columns
             else pd.factorize(price)[0].astype(np.int64))

    c_side = pd.factorize(side)[0].astype(np.int64)
    c_level = pd.factorize(level)[0].astype(np.int64)
    c_size = pd.factorize(size)[0].astype(np.int64)
    combo = (c_side * (c_level.max() + 1) + c_level) * (c_size.max() + 1) + c_size
    grp = pd.factorize(combo)[0].astype(np.int64)

    # Arrival order, total and strict. entry_seq is the feed's own tie-break
    # inside a packet; order id is the last resort so that the answer does not
    # depend on row order.
    if "entry_seq" in sub.columns:
        seq = sub["entry_seq"].to_numpy(dtype=np.int64)
    else:
        seq = np.zeros(n, dtype=np.int64)
    # oid stays unsigned: a CME order id above 2**63 cast to int64 would sort as
    # a negative, and the tie-break inside a packet would silently reverse.
    arrival = np.lexsort((oid, seq, entry))
    rank = np.empty(n, dtype=np.int64)
    rank[arrival] = np.arange(n, dtype=np.int64)

    # -- one array, grouped and then in arrival order inside each group ------ #
    sidx = np.lexsort((rank, grp))
    s_grp, s_entry, s_exit = grp[sidx], entry[sidx], exit_[sidx]
    s_size, s_filled, s_native = size[sidx], filled[sidx], native[sidx]
    s_reason, s_side, s_price, s_oid = reason[sidx], side[sidx], price[sidx], oid[sidx]

    if n > 1:
        same = s_grp[1:] == s_grp[:-1]
        if np.any(s_grp[1:] < s_grp[:-1]) or np.any(same & (s_entry[1:] < s_entry[:-1])):
            raise RuntimeError(
                "internal invariant broken: the candidate array is not sorted by "
                "(group, arrival), and searchsorted on it would return silently "
                "wrong windows"
            )

    key = np.empty(n, dtype=[("g", "i8"), ("t", "i8")])
    key["g"] = s_grp
    key["t"] = s_entry

    dt_ns = int(round(dt_s * 1e9))
    n_cand = np.zeros(n, dtype=np.int64)
    chosen = np.full(n, -1, dtype=np.int64)

    parents = np.flatnonzero(s_reason == "FILLED")
    if parents.size:
        q_lo = np.empty(parents.size, dtype=key.dtype)
        q_lo["g"] = s_grp[parents]
        q_lo["t"] = s_exit[parents]
        q_hi = np.empty(parents.size, dtype=key.dtype)
        q_hi["g"] = s_grp[parents]
        q_hi["t"] = s_exit[parents] + dt_ns
        # [lo, hi) is exactly {same group, entry in [exit, exit + dt]}, and the
        # clamp to parents+1 is what makes a successor strictly later in arrival
        # order -- it excludes the tranche itself and forbids a cycle among orders
        # that share a nanosecond.
        lo = np.maximum(np.searchsorted(key, q_lo, side="left"), parents + 1)
        hi = np.searchsorted(key, q_hi, side="right")
        cnt = np.maximum(hi - lo, 0)
        n_cand[parents] = cnt
        got = cnt > 0
        chosen[parents[got]] = lo[got]

    # -- resolve the tree into disjoint chains ------------------------------- #
    child_of = np.full(n, -1, dtype=np.int64)
    parent_of = np.full(n, -1, dtype=np.int64)
    lost_contest = np.zeros(n, dtype=bool)
    contested_in = np.zeros(n, dtype=bool)

    sel = np.flatnonzero(chosen >= 0)
    if sel.size == 0:
        return _empty_chains()
    c_sel = chosen[sel]
    # primary key the claimed successor, then removal time, then arrival: the
    # last row of each successor's block is the nearest predecessor, and it wins.
    ordr = np.lexsort((sel, s_exit[sel], c_sel))
    sel_s, c_s = sel[ordr], c_sel[ordr]
    last = np.ones(sel_s.size, dtype=bool)
    last[:-1] = c_s[:-1] != c_s[1:]
    child_of[sel_s[last]] = c_s[last]
    parent_of[c_s[last]] = sel_s[last]
    lost_contest[sel_s[~last]] = True
    contested_in[np.flatnonzero(np.bincount(c_sel, minlength=n) > 1)] = True

    roots = np.flatnonzero((child_of >= 0) & (parent_of < 0))
    if roots.size == 0:
        return _empty_chains()

    # Walk every chain at once: one pass per tranche position, not per chain.
    cur = roots.copy()
    n_tr = np.ones(roots.size, dtype=np.int64)
    vol = s_filled[roots].copy()
    cand_sum = n_cand[roots].copy()
    n_cont = np.zeros(roots.size, dtype=np.int64)
    n_nat = s_native[roots].copy()
    for _ in range(n + 1):
        nxt = child_of[cur]
        live = np.flatnonzero(nxt >= 0)
        if live.size == 0:
            break
        c = nxt[live]
        cur[live] = c
        n_tr[live] += 1
        vol[live] += s_filled[c]
        cand_sum[live] += n_cand[c]
        n_cont[live] += contested_in[c]
        n_nat[live] += s_native[c]
    else:  # pragma: no cover -- arrival order strictly increases along a chain
        raise RuntimeError(
            "chain walk did not terminate; successor links must strictly advance "
            "in arrival order and evidently do not"
        )

    take = n_tr >= min_tranches
    if not take.any():
        return _empty_chains()
    roots, cur = roots[take], cur[take]
    n_tr, vol = n_tr[take], vol[take]
    cand_sum, n_cont, n_nat = cand_sum[take], n_cont[take], n_nat[take]

    end_reason = s_reason[cur]
    status = np.where(
        end_reason == "FILLED", "COMPLETE",
        np.where(np.isin(end_reason, _CANCELLED_REASONS), "CANCELLED", "TRUNCATED"),
    )
    ended_by_contest = lost_contest[cur]
    n_alt = cand_sum - (n_tr - 1)

    out = pd.DataFrame({
        "first_ts": pd.to_datetime(s_entry[roots], utc=True),
        "last_ts": pd.to_datetime(s_exit[cur], utc=True),
        "side": s_side[roots],
        "price": s_price[roots],
        "size": s_size[roots],
        "n_tranches": n_tr,
        # What the chain actually traded. The remainder deleted with a cancelled
        # final tranche is NOT added: this column has to be comparable with the
        # traded-volume denominator the paper divides by, and that denominator
        # counts fills only.
        "total_volume": vol,
        "complete": status == "COMPLETE",
        "status": status,
        "span_ns": s_exit[cur] - s_entry[roots],
        "n_alt_children": n_alt,
        "n_contested": n_cont,
        "ended_by_contest": ended_by_contest,
        # The third term is provably implied by the first: a chain that ended by
        # losing a contest has a last tranche with a candidate it did not take,
        # so n_alt >= 1 already. It is written out because the reader should not
        # have to reconstruct that proof, and it was checked on 30,802 real ZNU6
        # chains with no counterexample. A mutation dropping it therefore cannot
        # be killed by any test, which is a property of the expression rather
        # than a gap in the suite.
        "ambiguous": (n_alt > 0) | (n_cont > 0) | ended_by_contest,
        "n_native_tranches": n_nat,
        "first_order_id": s_oid[roots],
        "last_order_id": s_oid[cur],
    })
    out = out.astype({c: _CHAIN_DTYPES[c] for c in ("size", "n_tranches",
                                                    "total_volume", "span_ns",
                                                    "n_alt_children", "n_contested",
                                                    "n_native_tranches")})
    return (out.sort_values(["first_ts", "first_order_id"], kind="stable")
               .reset_index(drop=True)[list(SYNTHETIC_CHAIN_COLUMNS)])


def synthetic_summary(chains: pd.DataFrame, orders: pd.DataFrame) -> dict:
    """Headline figures for one instrument-day's synthetic chains.

    ``volume_share`` uses the paper's denominator and it is not the obvious one:
    "we divide the total volume of all iceberg orders by the total traded volume
    of all orders... and not the total daily limit order volume". Dividing by
    posted volume instead would make the share look tiny, because most posted
    volume never trades.

    Everything here is a **lower bound** for the reasons set out in
    :func:`detect_synthetic`: an iceberg with varying tranche sizes, a walking
    price, or a smaller final tranche is invisible to the rule that produced these
    chains.

    ``ambiguous_share`` and ``ambiguous_volume_share`` are the numbers to read
    first. They say how much of the headline rests on the arbitrary tie-breaks the
    detector had to make; a volume share carried mostly by ambiguous chains is a
    statement about the level's arrival rate, not about hidden liquidity.
    """
    missing = [c for c in SYNTHETIC_CHAIN_COLUMNS if c not in chains.columns]
    if missing:
        raise KeyError(
            f"synthetic_summary needs {missing} on the chain frame; pass the "
            "output of detect_synthetic unmodified"
        )
    if "filled_size" not in orders.columns:
        raise KeyError(
            "synthetic_summary needs 'filled_size' on the order frame to form the "
            "traded-volume denominator the share is defined against"
        )

    n_orders = int(len(orders))
    traded = int(orders["filled_size"].sum()) if n_orders else 0
    n_chains = int(len(chains))
    if n_chains == 0:
        return {
            "n_chains": 0, "n_tranches": 0, "tranche_share": np.nan,
            "n_complete": 0, "n_cancelled": 0, "n_truncated": 0,
            "complete_share": np.nan,
            "synthetic_volume": 0, "traded_volume": traded, "volume_share": np.nan,
            "median_volume": np.nan, "mean_tranches": np.nan, "max_tranches": 0,
            "n_ambiguous": 0, "ambiguous_share": np.nan,
            "ambiguous_volume_share": np.nan, "n_ended_by_contest": 0,
            "n_with_native_tranche": 0, "n_orders": n_orders,
        }

    status = chains["status"].astype(str).to_numpy()
    vol = chains["total_volume"].to_numpy(dtype=np.int64)
    amb = chains["ambiguous"].to_numpy(dtype=bool)
    n_tranches = int(chains["n_tranches"].sum())
    syn_vol = int(vol.sum())
    return {
        "n_chains": n_chains,
        "n_tranches": n_tranches,
        "tranche_share": float(n_tranches / n_orders) if n_orders else np.nan,
        "n_complete": int(np.count_nonzero(status == "COMPLETE")),
        "n_cancelled": int(np.count_nonzero(status == "CANCELLED")),
        "n_truncated": int(np.count_nonzero(status == "TRUNCATED")),
        "complete_share": float(np.count_nonzero(status == "COMPLETE") / n_chains),
        "synthetic_volume": syn_vol,
        "traded_volume": traded,
        "volume_share": float(syn_vol / traded) if traded else np.nan,
        "median_volume": float(np.median(vol)),
        "mean_tranches": float(chains["n_tranches"].mean()),
        "max_tranches": int(chains["n_tranches"].max()),
        "n_ambiguous": int(amb.sum()),
        "ambiguous_share": float(amb.sum() / n_chains),
        "ambiguous_volume_share": float(vol[amb].sum() / syn_vol) if syn_vol else np.nan,
        "n_ended_by_contest": int(chains["ended_by_contest"].sum()),
        "n_with_native_tranche": int((chains["n_native_tranches"] > 0).sum()),
        "n_orders": n_orders,
    }
