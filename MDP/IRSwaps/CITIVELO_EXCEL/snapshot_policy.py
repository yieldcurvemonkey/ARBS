r"""Which stored snapshot answers a minute-resolution request, and on what terms.

Why this is a module and not three keyword arguments
----------------------------------------------------
Two code paths read the ``<curve>-CITIVELOEXCELMIN`` store - the single-point
loader and ``bulk_get_data``'s prepared-window branch - and they are required to
serve the identical snapshot for the identical request. They previously agreed
because both spelled ``(stamps - wanted).abs().values.argmin()`` inline, which is
agreement by coincidence: the next edit to either one silently ends it. The
selection lives here once, and both call it.

What the default is, and why it is not "safe"
----------------------------------------------
``SnapshotPolicy.legacy()`` is **bit-identical to the behaviour this module
replaced**: nearest in either direction, no bound, a soft miss. That is
deliberate. Changing which snapshot a valuation caller is served would move
numbers in work that has nothing to do with this change, and a miss on the
default path degrades to building from live Excel - which needs a signed-in
Excel session over COM, so turning a served curve into a miss is not a
conservative choice, it is a louder failure in someone else's process.

So the *behaviour* change is opt-in. What is **not** opt-in is the diagnosis:
every served snapshot now reports its signed lag, whether it came from the
future, and whether it came from the requested calendar day, and the first time
either pathology occurs for an asset it is logged at WARNING. A caller who does
nothing gets the same curve it always got, and can now tell when that curve is
wrong.

Nearest-in-either-direction, measured
-------------------------------------
Over every eligible leg on the ``_v3`` SDR tape (2024-03-01 .. 2026-08-07,
1,961,419 SOFR legs), measured 2026-08-09:

* the median and p90 request is served the **exact** minute asked for;
* **1.09%** of legs are served a snapshot from *after* the execution they are
  meant to be classified against, by up to 3 hours;
* **0.33%** are served a snapshot from a *different calendar day*;
* repricing those cases against the true nearest-preceding snapshot moves the
  par rate by a mean of ~1.0-1.2 bp and up to 5.2 bp - against prints that land
  within a basis point or two of mid.

For direction inference a post-trade curve is not a rounding choice: it can
already contain the market impact of the print being classified, which biases the
call toward whatever the trade actually was. Hence ``method="asof"``.

See ``docs/2026-08-09-citivelo-minute-curve-fidelity.md`` for the full
measurement and for how the tolerance was chosen.
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import threading
from typing import Any, Dict, Literal, Optional, Tuple

import numpy as np

__all__ = [
    "SnapshotPolicy",
    "SnapshotMiss",
    "Selection",
    "select_snapshot",
    "policy_from_kwargs",
    "warn_once",
]

_logger = logging.getLogger(__name__)

Method = Literal["nearest", "asof"]
OnMiss = Literal["none", "raise"]


class SnapshotMiss(LookupError):
    """No stored snapshot satisfies the request under the caller's policy.

    A distinct type, not a bare ``LookupError``, because the read paths wrap
    their store access in ``except Exception: return None`` so that a cold or
    damaged partition degrades to the live build. A strict caller's miss must
    travel *through* that handler rather than be converted into the silent
    fallback it was raised to prevent, so every such handler re-raises this one
    type by name.
    """


@dataclasses.dataclass(frozen=True)
class SnapshotPolicy:
    """How to choose a snapshot, and what to do when none qualifies.

    Attributes
    ----------
    method
        ``"nearest"`` - closest in either direction (the historical rule).
        ``"asof"`` - the latest snapshot **at or before** the request, which is
        the only setting that can guarantee the curve predates the trade.
    max_lag
        Upper bound on ``requested - served``. ``None`` means unbounded. This is
        a *tolerance in minutes*, not the twelve-hour feed-death guard
        ``IRSwapsMDP._max_snapshot_staleness`` provides: a request at 14:32
        served from 02:32 passes that one.
    allow_future
        Whether a snapshot stamped after the request is acceptable. Independent
        of ``max_lag`` because the existing freshness guard computes
        ``requested - snapshot`` and only raises when it *exceeds* the limit -
        it is structurally blind to negative lag, and no size of tolerance fixes
        that.
    on_miss
        ``"none"`` returns ``None`` and lets the caller fall through to the live
        build; ``"raise"`` raises :class:`SnapshotMiss`. Research callers want
        ``"raise"``: a determinism requirement is not served by quietly getting a
        different curve.
    """

    method: Method = "nearest"
    max_lag: Optional[datetime.timedelta] = None
    allow_future: bool = True
    on_miss: OnMiss = "none"

    @classmethod
    def legacy(cls) -> "SnapshotPolicy":
        """Exactly what this path did before the policy existed."""
        return cls()

    @classmethod
    def strict(
        cls,
        *,
        minutes: float = 1.0,
        allow_future: bool = False,
        on_miss: OnMiss = "raise",
    ) -> "SnapshotPolicy":
        """Backward-only, bounded, loud - what dealer-direction inference needs.

        **Why one minute.** Loosening it buys almost nothing and admits a lot.
        Measured over the SDR tape span (2024-03-01 .. 2026-08-07), backward-only
        selection prices this share of SOFR legs:

        ===========  ====================  ==========================
        tolerance    share of legs priced  5Y drift admitted (p90/p99)
        ===========  ====================  ==========================
        60 s         **97.58 %**           0.21 / 0.44 bp
        5 min        97.78 %               0.43 / 0.86 bp
        30 min       98.18 %               1.07 / 3.07 bp
        60 min       98.60 %               1.77 / 5.32 bp
        ===========  ====================  ==========================

        Going from 60 s to 60 min recovers **one percent** more legs and admits
        eight times the drift. Inside the 01:00-16:59 ET session - 94.7 % of the
        tape - 60 s prices **99.84 %** of legs, so the tolerance is not what
        constrains coverage; the hours the feed does not publish are.

        The drift column is the measured movement of the curve itself over that
        elapsed time, not a model: see ``drift`` in
        ``scripts/citivelo_minute_lag_audit.py``. It is nearly identical on
        USD-FEDFUNDS-1D (5Y p90 0.22 bp at one minute), so this is not a
        SOFR-specific number.

        Compare what it replaces: the shipped nearest-either-direction rule
        introduces a **mean 1.0-1.3 bp** error on the requests where the two
        rules differ. One minute of drift is an order of magnitude below that,
        and below the one-to-two basis points from mid at which prints land -
        which is the quantity the direction call is reading.

        A caller with a different edge should pass a different number rather
        than inherit this one by accident.
        """
        return cls(
            method="asof",
            max_lag=datetime.timedelta(minutes=float(minutes)),
            allow_future=bool(allow_future),
            on_miss=on_miss,
        )

    @property
    def is_legacy(self) -> bool:
        return (
            self.method == "nearest"
            and self.max_lag is None
            and self.allow_future
            and self.on_miss == "none"
        )

    def fingerprint(self) -> Tuple[Any, ...]:
        """Hashable identity, for callers that memoise curves per policy."""
        return (
            self.method,
            None if self.max_lag is None else self.max_lag.total_seconds(),
            self.allow_future,
            self.on_miss,
        )

    def describe(self) -> str:
        lag = "unbounded" if self.max_lag is None else f"{self.max_lag.total_seconds():.0f}s"
        return (
            f"method={self.method} max_lag={lag} "
            f"allow_future={self.allow_future} on_miss={self.on_miss}"
        )


@dataclasses.dataclass(frozen=True)
class Selection:
    """The chosen row and everything the caller needs to judge it.

    ``position`` is a **positional** index into the window, never a label. The
    window is the concatenation of up to three day frames without
    ``ignore_index``, so its index is neither unique nor monotonic; and two rows
    in it can carry the same stamp when partitions overlap after a re-warm.
    ``idxmax``/``idxmin`` on such a frame silently returns the wrong row.
    """

    position: int
    served_ns: int
    lag_seconds: float          # requested - served; negative = served the future
    from_future: bool
    within_tolerance: bool


def select_snapshot(
    stamps_ns: np.ndarray,
    wanted_ns: int,
    policy: SnapshotPolicy,
) -> Optional[Selection]:
    """The snapshot ``policy`` chooses out of ``stamps_ns``, or ``None``.

    ``stamps_ns`` is int64 nanoseconds-since-epoch in UTC, in the window's own
    order - deliberately **unsorted**. The day order ``(D, D-1, D+1)`` decides
    ties, and this repo documents that order as part of the contract, so the
    search must not sort and must break ties positionally-first exactly as
    ``numpy.argmin`` and ``pandas.Series.values.argmin()`` do.
    """
    if stamps_ns.size == 0:
        return None

    delta = stamps_ns - wanted_ns          # served - wanted, in ns
    if policy.method == "asof":
        eligible = delta <= 0
        if not eligible.any():
            return None
        # Largest (least negative) offset = latest stamp at or before the
        # request. First positional occurrence on a tie, which with the
        # (D, D-1, D+1) window order prefers the requested day's own copy of a
        # duplicated stamp over a neighbouring partition's.
        masked = np.where(eligible, delta, np.iinfo(np.int64).min)
        pos = int(masked.argmax())
    else:
        pos = int(np.abs(delta).argmin())

    served = int(stamps_ns[pos])
    lag_s = (wanted_ns - served) / 1e9
    from_future = served > wanted_ns
    within = True
    if policy.max_lag is not None and lag_s > policy.max_lag.total_seconds():
        within = False
    if from_future and not policy.allow_future:
        within = False
    if not within:
        return None
    return Selection(
        position=pos,
        served_ns=served,
        lag_seconds=lag_s,
        from_future=from_future,
        within_tolerance=True,
    )


def policy_from_kwargs(kwargs: Optional[Dict[str, Any]]) -> SnapshotPolicy:
    """Read a ``snapshot_policy`` out of a ``get_data`` request dict.

    One spelling only. Accepting both an object and a scatter of scalar keys
    would give two ways to say the same thing, and the failure mode is a caller
    setting the one this code does not read and believing it is protected.
    """
    if not kwargs:
        return SnapshotPolicy.legacy()
    policy = kwargs.get("snapshot_policy")
    if policy is None:
        return SnapshotPolicy.legacy()
    if not isinstance(policy, SnapshotPolicy):
        raise TypeError(
            "snapshot_policy must be a "
            "MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy.SnapshotPolicy; got "
            f"{type(policy).__name__}. Build one with SnapshotPolicy.strict(minutes=...)."
        )
    return policy


# --------------------------------------------------------------------------- #
#                        one warning per pathology per asset                  #
# --------------------------------------------------------------------------- #

_WARNED: set = set()
_WARN_LOCK = threading.RLock()


def warn_once(key: Tuple[Any, ...], message: str) -> None:
    """Log ``message`` at WARNING the first time ``key`` occurs in this process.

    A backfill makes millions of these requests and roughly one percent of them
    trip a pathology, so an unconditional warning is 21,000 lines nobody reads -
    which is the same as silence, only more expensive. One line per asset per
    kind, saying that the rest are suppressed and how to count them properly, is
    the version that gets acted on.
    """
    with _WARN_LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    _logger.warning("%s (further occurrences of this kind are not logged)", message)


def reset_warnings() -> None:
    """For tests: forget which warnings have already been emitted."""
    with _WARN_LOCK:
        _WARNED.clear()
