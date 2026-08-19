"""Strategy 2 on the Q20 STIR curve -- the deep packs Citi actually traded.

:mod:`RVUtils.ConvexityRV.strat2_sofr_convexity` stops at pack rank 10 (first
expiry <= ~2.4y). Citi's published SOFR screen is ranks **5..17**, and the two
packs it recommended by name are **Blues** (rank 13, T1 ~3.25y) and **Golds**
(rank 17, T1 ~4.25y). So the part of the strategy the research note is actually
about has never been tested in this repo. This module is the extension that
reaches it, and everything in it exists to answer one question honestly: *where
is a curve-derived futures rate allowed to stand in for a settlement mark?*

Nothing here re-implements the screen. The universe, the Ho-Lee model, the
ranking, the hedge regression, the trade construction and the backtest all come
from ``strat2_sofr_convexity`` unchanged; this module supplies a **rate source**
and an **admissibility gate**, and hands both to that engine.


WHY A NEW RATE SOURCE AT ALL, AND WHAT IT DOES *NOT* BUY
=========================================================
``USD-SOFR-1D-Q20STIRT`` (``MDP/IRSwaps/BARCHART_STIRF/rl.py``) is calibrated to
``SFRCM1..SFRCM20`` -- twenty quarterly SR3 futures, ``max_tenor_from_timestamp
_months=60``, versus Q12's thirteen and 39 months. (The task brief said
``SFRCM1..21``; the config carries **20**, measured.)

Because it is calibrated *to the settles*, its IMM x IMM forwards are a smoothed,
arbitrage-consistent restatement of those settles -- **not an independent source
and not new coverage**. It cannot conjure a contract the local store does not
have, and it *inherits* a stale settle rather than laundering it. What it does
buy is threefold and each part is measured, not assumed:

1. **Cross-sectional smoothing.** A single deferred contract's idiosyncratic
   settle error is projected onto a 40-node discount curve fitted to nineteen
   other contracts, so it is damped rather than passed straight into the pack
   mean at full weight.
2. **A gap-tolerant strip.** The curve is calibrated to whatever prefix of
   ``SFRCM1..20`` is locally present (see ``min_instruments``), and then quotes
   *every* quarter inside that span -- including quarters whose own contract had
   no usable print that day.
3. **An explicit resolution diagnostic.** The curve carries its own node grid,
   so ``ca_diagnostics.window_resolution`` can be asked, per pack window per
   day, whether the rate for that window is a market observation or an
   interpolation. That is the test the zero-convexity control cannot perform.

The settle marks themselves remain the traded quantity. See "WHAT MARKS THE
BOOK" below -- the P&L legs are marked off raw SR3 settles, always.


THE TRAP THIS MODULE IS BUILT AROUND
=====================================
A previous investigation tested ``USD-SOFR-1D-Q12STIRT`` forwards as the futures
rate and **rejected them**, with a specific measured mechanism:

* 2019: median ``|futures - Q12 forward|`` = **9.375bp**, ``corr(CA_obs, CA_q12)``
  0.441. On 2019-03-15 the Q12 curve had **12 nodes with the second at
  2021-03-17** -- no front-end degrees of freedom at all -- so it printed a
  constant 2.3147% while the SR3 strip declined 2.4300 -> 2.1450.
* 2021-23 the same curve is fine: ``corr(pack rates) 0.9999``, median
  disagreement **0.881bp**, CA correlation 0.816.
* **And the obvious quality criteria invert.** In 2019 the *degenerate* curve
  scores BETTER on both ``CA >= 0`` (26% vs 41% violations) and
  ``corr(CA, T1^2)`` (+0.83 vs -0.21), because a flattened curve manufactures a
  monotone non-negative adjustment profile out of nothing. **Any gate built on
  those two metrics selects for the failure it is supposed to detect.**

The root cause is now identified exactly, and it is not the curve family. The
node grid of every ``*STIRT`` curve is built by ``_build_stirf_nodes`` from the
**central-bank meeting-date map**, and this machine's
``central_bank_dates/meeting_dates_v1.json`` for ``USD-SOFR-1D`` starts at
**apr21** and runs to **sep27** (56 windows, measured). Before ~2021 there are
no meeting nodes in the near field at all, so the front of the curve is one
enormous log-linear segment.

That has a consequence the earlier work did not draw, and it is the reason this
module exists rather than inheriting the rejection:

    **The 2019 degeneracy is a FRONT-END defect, not a deep-end defect.**

Measured on 2019-03-15 with a 19-instrument Q20 build (settle minus Q20 forward,
bp):

===========  ==========  ===========  ==========
rank          contract    settle       diff (bp)
===========  ==========  ===========  ==========
1             SR3H19      2.4300       **+13.44**
2             SR3M19      2.4050       **+10.94**
17            SR3H23      2.1600       -0.06
18            SR3M23      2.1650       -0.06
19            SR3U23      2.1700       +0.04
===========  ==========  ===========  ==========

The deep windows sit *inside* the 2021+ meeting-node region and are fitted to
four decimal places; the near windows sit inside the single pre-2021 segment and
are wrong by more than the entire signal. So the packs this module targets are
precisely the ones the earlier rejection does **not** cover -- but that is a
claim to be gated per (date, window), never assumed, which is what
:func:`window_gate` does.


THE GATE
========
Three conditions, all per (date, pack window), all recorded on every row so a
reader can re-cut them:

``resolution``
    The window must not sit inside a single node interval of the Q20 curve
    (``ca_diagnostics.window_resolution(...)["spans_window"] == 0``) and must
    carry at least ``gate_min_nodes_inside`` nodes strictly inside it. This is
    the condition the 2019 front end fails and the 2019 deep end passes.

``settle agreement``
    ``max_i |settle_rate_i - q20_forward_i|`` over the window's four contracts
    must be <= ``gate_max_settle_diff_bp``. This is the direct test of the thing
    the user asked to be sure of -- that the rate being used *is* the settlement
    mark -- and it is applied per contract rather than to the pack mean, because
    four errors of opposite sign average to a clean-looking pack.

``instrument coverage``
    All four contracts must be at or inside the calibrated strip depth. The
    curve is never asked to extrapolate past its last instrument; a rank is
    tradeable on a date only if ``rank + 3 <= depth``.

``gate_max_settle_diff_bp`` defaults to 2.0bp. That is not a round number chosen
for looks: it is set by the measured settle-timing noise floor. Barchart's "EOD"
is the 1-minute bar nearest 17:00 New York while SR3 settles at ~15:00 ET, and
the induced CA noise on near packs was measured at 0.89-2.55bp/pack-day (mean
1.82). A per-contract agreement tolerance below that would reject rows for
carrying noise that is present in the settles themselves.


WHAT MARKS THE BOOK
===================
The screen and the CA panel are computed off Q20 forwards. **The backtest's
futures legs are marked off raw SR3 settles**, through the same
``STIRFutureHandler`` path as the near-pack strategy, because a settle is what
you can actually transact at and a curve forward is not. :func:`deep_pack_config`
therefore leaves ``futures_source`` pointing at ``BARCHART_STIRF-RL``.

The consequence is deliberate and is the honest reading of the whole exercise:
if the gate is doing its job the two agree to well inside a basis point, and if
they do not, the gate failed. :func:`rate_source_comparison` computes the screen
both ways so that divergence is visible rather than assumed away.


NETWORK SAFETY -- THE PRODUCTION PATH IS NOT USABLE, AND THIS IS WHY
=====================================================================
``IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":
"USD-SOFR-1D-Q20STIRT", ...})`` **must never be called on this machine.**
Measured: it makes **52-57 outbound HTTP requests per date**. There is no
``offline`` switch on that path -- ``offline=True`` is passed through and
ignored -- and the reason is structural rather than incidental:

* the Q20 curve store is **empty** (``curve_store/raw`` carries Q12STIRT with
  2,061 dates and Q16STIRT with 197; there is no Q20 asset at all), so the
  Tier-0 store fast path always misses and falls through to a live build; and
* ``BARCHART_STIRF_CURVE.__init__`` wires its pricer fetcher to
  ``STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")`` (``rl.py:1039``) -- the
  *intraday* source, whose local cache is 22:xx bars and reaches depth 20 on
  **zero** dates. So even a fully-cached date misses and hits Barchart.

:func:`build_q20_pricer` avoids both by fetching the pricers itself from the
**17:00 EOD** ``BARCHART_STIRF-RL`` source -- which resolves ``SFRCM1..20`` with
zero network on every covered date -- and injecting them straight into
``BARCHART_STIRF_CURVE._build_curve_from_pricers``. That reuses the production
node construction and Levenberg-Marquardt solve verbatim, skips
``_curve_cache_put`` (so no shared store is mutated), and runs in ~0.15s.

Every build is additionally wrapped in
``listed_cache_guard.cache_only()``, which blackholes ``requests`` for the
duration. A date that would need the network raises ``CacheMissOffline`` and is
skipped and counted. That is a hard guarantee, not a convention:
:data:`network_calls_blocked` is asserted to be zero by the test suite and
reported by the build script.


UNIVERSE -- MEASURED, AND SMALLER THAN THE BRIEF ASSUMED
=========================================================
The brief supposed the Q20 curve store had "broad daily coverage". It has none.
The binding constraint is therefore the raw SR3 settle store, scanned directly
out of the 8-shard diskcache (2,072 EOD dates, 2018-05..2026-08). Dates whose
**contiguous** front strip reaches depth *n*:

======  =====  =====  =====  =====  =====  =====  =====  =====  =====  ======
depth    2018   2019   2020   2021   2022   2023   2024   2025   2026   TOTAL
======  =====  =====  =====  =====  =====  =====  =====  =====  =====  ======
>= 13     167    252    253    252    252    198     19      2      1   1,396
>= 16     167    252    253    252    195     51     19      2      1   1,192
>= 17     167    252    253    252    142     51     19      1      0   1,137
>= 20      41     77    253    187     52     51     19      1      0     681
======  =====  =====  =====  =====  =====  =====  =====  =====  =====  ======

So **Blues (rank 13) needs depth 16 -> 1,192 dates** and **Golds (rank 17) needs
depth 20 -> 681 dates**, against 1,396 for the existing rank-10 strategy. The
depth is *variable by date* and this module treats it that way -- a fixed
all-20 rule would throw away ~500 Blues dates for nothing.


THE HOLE THAT ARGUMENT LEFT, AND THE 2026-08-19 REPAIR
=======================================================
The paragraph above is right and the code implementing it was wrong in one
place, which is worth stating plainly because the wrongness was invisible from
inside the design it belongs to.

Depth was treated as variable **per rank** (``gate_covered = spec.rank + 3 <=
depth``) but as fixed **per date**: :func:`strip_depth_by_date` admitted a date
only if ``instrument_count(date, depth) >= min_instruments`` -- the CURVE floor,
then 12 -- so a date holding four perfectly good front settles was discarded for
*every* rank, including the ranks that never look past contract 4. Measured
2026-08-19 on the same shards:

===========  =======================  ======================  ============
year          dates able to quote      dates in the shipped    lost
              rank 1 (depth >= 4)      panel at rank 1
===========  =======================  ======================  ============
2023          258                      222                     36
2024          252                      **19**                  **233**
2025          198                      **2**                   **196**
2026          37                       **3**                   **34**
===========  =======================  ======================  ============

That is the "sparse from ~May-2024" complaint, and none of it is a data
shortage. The repair separates the two floors -- :attr:`Q20Config.min_strip_depth`
(universe, 4 contracts = one pack) from :attr:`Q20Config.min_instruments`
(curve solve, now 4 after measuring depths 4/5/6 solve and agree with settles to
0.37-0.81bp) -- and makes :func:`day_rows` degrade to settle-only rows with
``q20_built=False`` rather than dropping a date whose curve will not build.
Deep-rank sparsity after 2023 is NOT affected by any of this: it is a genuine
absence of deferred settles in the local store, and the only cure is a fetch
(``scripts/warm_sr3_deferred.py``).
"""

from __future__ import annotations

import datetime
import glob
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked
from RVUtils.ConvexityRV.packs import imm_date, quarterly_imm_sequence
from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    INTRADAY_SOURCE_MARKERS,
    LIVE_SOURCE,
    Strat2Config,
    _tz_readable,
    assert_settle_source,
    ca_snapshot,
    futures_symbol,
    ny_utc_offset,
    pack_windows,
)

__all__ = [
    "Q20_CURVE",
    "Q20_INSTRUMENT_PREFIX",
    "EOD_SOURCE",
    "LIVE_SOURCE",
    "INTRADAY_SOURCE_MARKERS",
    "assert_settle_source",
    "Q20Config",
    "strip_depth_by_date",
    "is_imm_roll_date",
    "instrument_count",
    "max_rank_for_depth",
    "depth_for_rank",
    "Q20Builder",
    "build_q20_pricer",
    "q20_imm_forwards",
    "settle_rates",
    "forwards_to_prices",
    "window_gate",
    "day_rows",
    "deep_pack_config",
    "gate_summary",
    "settle_agreement_summary",
    "rate_source_comparison",
    "apply_gate",
    "CITI_SOFR_20230609",
]

#: The curve. Defined in ``MDP/IRSwaps/BARCHART_STIRF/rl.py``; instruments
#: ``SFRCM1..SFRCM20``, ``max_tenor_from_timestamp_months=66``.
#:
#: The horizon is ``3*20 + 6``, not ``3*20``. Node construction is driven by the
#: horizon ALONE -- ``_build_stirf_nodes`` filters central-bank ends and pricer
#: maturities alike by ``d <= horizon`` and never looks at the instrument count
#: -- and ``SFRCM20`` matures at ``IMM_1 + 60m``, which is always past
#: ``as_of + 60m``. Under the old 60 the terminal instrument was excluded from
#: the grid on every date and priced by extrapolation, which is what held rank
#: 17 at a median 3.7bp against the 2.0bp gate. See
#: ``tests/test_q20_curve_horizon.py``.
Q20_CURVE = "USD-SOFR-1D-Q20STIRT"

#: Continuous-contract instrument prefix. ``SFRCM{k}`` is the k-th quarterly SR3
#: from the front, which is why depth in *contracts* maps 1:1 onto instruments.
Q20_INSTRUMENT_PREFIX = "SFRCM"

#: The **17:00 New York EOD** SR3 source. Not ``BARCHART_TOS_LIVE_STIRF-RL``,
#: which is what the production curve builder reaches for and which has no
#: deferred-contract depth locally. See the module docstring.
EOD_SOURCE = "BARCHART_STIRF-RL"

#: The intraday quote source, and the guard that refuses it. Both live in
#: :mod:`RVUtils.ConvexityRV.strat2_sofr_convexity` -- the base module both
#: configs are defined against -- and are re-exported here because this is the
#: module whose docstring documents the trap. Measured 2026-08-19 over the whole
#: 12,724,720-key local slice: ``BARCHART_TOS_LIVE_STIRF-RL`` reaches contiguous
#: depth 20 on **zero dates in every year** 2018-2026, so it cannot even buy the
#: deep packs it would be reached for.


# ===========================================================================
# Config
# ===========================================================================
@dataclass(frozen=True)
class Q20Config:
    """Every knob of the Q20 rate source and its gate, documented inline.

    This is deliberately *not* a subclass of :class:`Strat2Config`. The two
    describe different things -- this one describes how a futures rate is
    obtained and when it may be believed, that one describes the screen and the
    trade -- and :func:`deep_pack_config` builds the second from the first so
    the pack universe can never drift out of sync with the strip depth.
    """

    # ---------------------------------------------------------------- market
    q20_curve: str = Q20_CURVE
    eod_source: str = EOD_SOURCE
    """SR3 settle source for BOTH the curve's calibration instruments and the
    settle-agreement control. One source, so the gate compares like with like."""

    swap_curve: str = "USD-SOFR-1D"
    swap_source: str = "CITIVELO_EXCEL"
    """The matched-maturity swap leg is unchanged from the near-pack strategy."""

    futures_root: str = "SR3"

    # ---------------------------------------------------------------- strip
    max_instruments: int = 20
    """Cap on calibration instruments. The Q20 config carries exactly 20
    (``SFRCM1..SFRCM20``); asking for more would index past it."""

    min_instruments: int = 4
    """Refuse to build the CURVE below this many calibration instruments.

    **Was 12, and that number was the single largest cause of the sparse
    2024-2026 CA series.** The rationale on record -- "a 20-node curve fitted to
    6 contracts is mostly interpolation, and the resolution gate would reject its
    windows anyway" -- is about the curve, but the floor was applied to
    :func:`strip_depth_by_date`, i.e. to UNIVERSE ADMISSION, so a date holding
    four good settles was dropped for **every** rank rather than for the deep
    ranks it genuinely could not price. Measured cost: 2024 fell from 252 dates
    able to quote rank 1 to 19; 2025 from 198 to 3; 2026 from 37 to 5.

    Both halves of the rationale were then tested rather than assumed
    (2026-08-19, offline, ``network_calls_blocked`` delta 0):

    ==========  ============  ==========  =====================================
    strip depth  date          solver      max |settle - Q20 fwd| over the strip
    ==========  ============  ==========  =====================================
    4            2025-06-20    converged   0.81bp
    5            2025-03-20    converged   0.64bp
    6            2024-12-19    converged   0.37bp
    7            2024-09-19    converged   4.06bp  (IMM roll; gate REJECTS it)
    ==========  ============  ==========  =====================================

    So the curve does resolve at depth 4-6 and agrees with the settles well
    inside the 2.0bp gate, and where it does not the gate catches it on the row
    -- which is the point: a shallow date is now *admitted and judged* rather
    than *discarded unjudged*. Universe admission is governed separately by
    :attr:`min_strip_depth`, so a date whose curve cannot be built is still kept
    and priced off raw settles (see :func:`day_rows`)."""

    min_strip_depth: int = 4
    """Universe admission floor, in CONTRACTS -- decoupled from the curve floor.

    Four contiguous contracts is one pack window (rank 1), so this is the
    smallest strip that can produce any CA at all. Keeping it separate from
    :attr:`min_instruments` is what lets an IMM roll date at depth 4 -- three
    calibration instruments, one pack -- into the panel with a settle-based CA
    and ``q20_built=False`` recorded on the row, instead of vanishing."""

    # ---------------------------------------------------------------- gate
    gate_max_settle_diff_bp: float = 2.0
    """Max per-contract ``|settle - Q20 forward|`` inside a pack window, bp.
    Set at the measured EOD-vs-settle timing noise floor (0.89-2.55bp/pack-day,
    mean 1.82); tighter than that rejects rows for noise the settles carry
    themselves. Applied PER CONTRACT, never to the pack mean -- four errors of
    opposite sign average to a clean-looking pack."""

    gate_min_nodes_inside: int = 1
    """Q20 nodes strictly inside the pack's swap window. Zero means the whole
    window is one log-linear segment and its four forwards are one interpolated
    constant -- the exact 2019 failure, and the one the zero-convexity control
    is structurally blind to."""

    gate_require_resolution: bool = True
    gate_require_settle_agreement: bool = True
    """Both on by default. Off is for measuring what the gate removes."""

    gate_min_control_power_bp: float = 1.0
    """Peak-to-trough spread of the window's four forwards, bp. Below this the
    zero-convexity control has nothing to see and its 0.00bp pass is an absence
    of evidence rather than evidence. Reported on every row; only enforced when
    ``gate_require_resolution`` is on."""

    # ---------------------------------------------------------------- rates
    rate_source: str = "q20"
    """``"q20"`` | ``"settle"``. The screen's futures rate. ``"settle"`` runs the
    identical pipeline off raw SR3 settles and is the control, not a fallback --
    :func:`rate_source_comparison` runs both and reports the divergence."""

    # ---------------------------------------------------------------- window
    start: datetime.date = datetime.date(2018, 1, 1)
    end: datetime.date = datetime.date(2026, 12, 31)
    """Requested window. The EFFECTIVE window is data-driven -- report what the
    panel came back with, never this."""

    block_network: bool = True
    """Wrap every build in ``cache_only()``. Leave this ON. It is the only thing
    standing between a 681-date panel build and 35,000 Barchart requests."""

    def __post_init__(self) -> None:
        if self.rate_source not in ("q20", "settle"):
            raise ValueError(f"bad rate_source {self.rate_source!r}")
        if not 1 <= self.min_instruments <= self.max_instruments <= 20:
            raise ValueError(
                f"need 1 <= min_instruments ({self.min_instruments}) <= "
                f"max_instruments ({self.max_instruments}) <= 20")
        if self.min_strip_depth < 4:
            raise ValueError(
                f"min_strip_depth={self.min_strip_depth} cannot quote any pack; "
                "a pack window is four consecutive contracts")
        assert_settle_source(self.eod_source, field="eod_source")


# ===========================================================================
# Strip depth -- the universe, read straight off the diskcache
# ===========================================================================
#: Barchart STIR diskcache key: ``f"{iso_timestamp}-{ticker}-{source}"``.
_STIR_CACHE_KEY = re.compile(
    r"^(?P<d>\d{4}-\d{2}-\d{2})T(?P<t>\d{2}:\d{2}:\d{2})(?P<tz>[+\-]\d{2}:\d{2})?"
    r"-(?P<sym>SR3[FGHJKMNQUVXZ]\d{2})-(?P<src>[A-Z0-9_\-]+)$")


def _default_cache_root() -> str:
    try:
        from Caching.DiskCacheMixin import DiskCacheMixin  # noqa: PLC0415

        return str(DiskCacheMixin.default_cache_path("STIRFuturePricer_Cache"))
    except Exception:                                          # noqa: BLE001
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "ARBS", "Cache",
                            "diskcache", "dump", "STIRFuturePricer_Cache")


def strip_depth_by_date(
    cfg: Q20Config,
    *,
    cache_root: Optional[str] = None,
    session_time: str = "17:00:00",
    min_depth: Optional[int] = None,
    require_readable_offset: bool = True,
) -> Dict[datetime.date, int]:
    """``date -> length of the CONTIGUOUS front SR3 strip already on this machine``.

    The single most important function in the module, because it makes the
    universe an observable instead of an assumption. The SR3 store is
    demand-driven, not an archive: a miss goes to Barchart at roughly a minute
    per cold contract, so enumerating what is local *first* is what turns an
    overnight crawl into a two-minute scan that never opens a socket.

    Contiguity is required rather than mere presence. A pack is four consecutive
    contracts and the curve is calibrated to ``SFRCM1..k``, an unbroken prefix by
    construction; a strip with a hole at rank 7 cannot supply either, so counting
    "17 of the first 20 present" would overstate what is buildable.

    Reads the diskcache's sqlite shards read-only. Probing the MDP instead is
    precisely the expensive thing being avoided.

    **Admission is PER DATE and the returned depth is used PER RANK.** A date is
    admitted when its contiguous strip reaches ``cfg.min_strip_depth`` (four
    contracts = one pack), NOT when it reaches the depth the deepest requested
    pack needs. The caller then asks ``max_rank_for_depth(depth)`` what that date
    can quote. This is the difference between the shipped 1,434-date universe and
    the 1,922-date one: 488 dates were being dropped for want of contracts no
    front pack ever reads. See :attr:`Q20Config.min_instruments` for the measured
    per-year cost of the old rule.

    ``require_readable_offset`` (default True) drops 17:00 keys whose UTC offset
    is not New York's for that date. They match the key regex but the EOD fetcher
    asks for the New-York-stamped alias and misses -- see
    :func:`strat2_sofr_convexity._tz_readable`. Set it False ONLY to measure the
    defect; a panel build that turns it off manufactures dates that then reach
    for the vendor.

    ``min_depth`` overrides ``cfg.min_strip_depth`` for callers that need a
    DIFFERENT lens on the same scan. There is exactly one: a **warm** wants to
    see the dates that hold one or two contracts, because those are precisely the
    dates it exists to fill, and a config floored at 4 (the smallest depth that
    can quote a pack) cannot see them. Panel builders should never pass this.
    """
    root = cache_root or _default_cache_root()
    floor = int(cfg.min_strip_depth if min_depth is None else min_depth)
    have: Dict[str, set] = defaultdict(set)
    for db in sorted(glob.glob(os.path.join(root, "*", "cache.db"))):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for (key,) in con.execute("SELECT key FROM Cache"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "ignore")
                m = _STIR_CACHE_KEY.match(key)
                if not m:
                    continue
                if m.group("t") != session_time or m.group("src") != cfg.eod_source:
                    continue
                # A key stamped in the wrong UTC offset matches this regex but is
                # NOT what the EOD fetcher asks for -- see `_tz_readable`. Counting
                # it inflates the universe with dates that then miss and reach for
                # the vendor. Measured: 51 such dates, 2026-07-09 among them at a
                # scanned depth of 12 against a resolvable depth of 0.
                if require_readable_offset and not _tz_readable(
                        m.group("d"), m.group("tz"),
                        session_hour=int(session_time[:2])):
                    continue
                have[m.group("d")].add(m.group("sym"))
        finally:
            con.close()

    out: Dict[datetime.date, int] = {}
    for d, syms in have.items():
        dd = datetime.date.fromisoformat(d)
        if not (cfg.start <= dd <= cfg.end):
            continue
        seq = quarterly_imm_sequence(dd, cfg.max_instruments)
        depth = 0
        for y, m in seq:
            if futures_symbol(y, m, cfg.futures_root) in syms:
                depth += 1
            else:
                break
        if depth >= floor:
            out[dd] = depth
    return dict(sorted(out.items()))


def is_imm_roll_date(as_of: datetime.date) -> bool:
    """Is *as_of* itself the IMM date of the front quarterly contract?

    Matters because the two ladders disagree on exactly these ~4 days a year.
    ``packs.quarterly_imm_sequence(..., include_current=True)`` -- what the pack
    universe and the settle fetch use -- **keeps** a contract whose IMM date is
    today, while Barchart's continuous ``SFRCM`` ladder has already rolled past
    it, so ``SFRCM1`` is the *second* entry of that sequence.

    Left unhandled this is not a rounding error, it is a request for a contract
    one quarter beyond the cached strip, which misses and goes to the vendor.
    Measured before the fix: 8 of the 10 dates that reached for the network in a
    full 1,433-date build were IMM roll dates (2018-06-20, 2018-09-19,
    2018-12-19, 2019-03-20, 2019-06-19, 2019-09-18, 2021-09-15, 2021-12-15) and
    every one of them resolved cleanly at ``SFRCM1..depth-1``.
    """
    y, m = quarterly_imm_sequence(as_of, 1)[0]
    return imm_date(y, m) == as_of


def instrument_count(as_of: datetime.date, depth: int) -> int:
    """Calibration instruments available from a strip of *depth* contracts.

    ``depth`` counts contracts from :func:`packs.quarterly_imm_sequence` with
    ``include_current=True``. On an IMM roll date the ``SFRCM`` ladder starts one
    contract later, so one fewer instrument is reachable. See
    :func:`is_imm_roll_date`.
    """
    return int(depth) - 1 if is_imm_roll_date(as_of) else int(depth)


def max_rank_for_depth(depth: int) -> int:
    """Deepest pack window fully inside a strip of *depth* contracts.

    A pack starting at rank ``r`` uses contracts ``r..r+3``, so ``r <= depth-3``.
    Blues is rank 13 (needs 16), Golds is rank 17 (needs 20).
    """
    return int(depth) - 3


def depth_for_rank(rank: int) -> int:
    """Contracts needed to quote the pack window starting at *rank*."""
    return int(rank) + 3


# ===========================================================================
# The curve -- built offline, from EOD settles, with the production solver
# ===========================================================================
class Q20Builder:
    """Offline Q20 curve construction from locally cached 17:00 EOD settles.

    Holds the three heavyweight objects -- the STIRF curve builder, the EOD
    futures MDP, and the swaps MDP used only for its timestamp normaliser -- so
    a multiprocess panel build constructs them once per worker rather than once
    per date. That is the whole reason the class exists; it carries no other
    state and every method is a thin bound wrapper over the module functions,
    which stay independently callable and independently testable.

    **Never** call ``IRSwapsMDP.get_pricer`` for a ``*STIRT`` curve on this
    machine -- see the module docstring for the two structural reasons it
    guarantees a Barchart crawl.
    """

    def __init__(self, cfg: Optional[Q20Config] = None) -> None:
        from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

        self.cfg = cfg or Q20Config()
        self.builder = BARCHART_STIRF_CURVE()
        self.base_cfg = dict(self.builder._STIRF_CURVE_CONFIGS[self.cfg.q20_curve])
        self.eod = STIRFutureMDP(source=self.cfg.eod_source)
        self.irs = IRSwapsMDP(source=self.cfg.eod_source)

    def pricer(self, as_of: datetime.date, depth: int) -> Any:
        """The Q20 pricer for one date at one strip depth."""
        return build_q20_pricer(as_of, depth, cfg=self.cfg, builder=self.builder,
                                base_cfg=self.base_cfg, eod_mdp=self.eod,
                                irs_mdp=self.irs)

    def settles(self, as_of: datetime.date, depth: int) -> Dict[Tuple[int, int], float]:
        """``(year, month) -> 100 - settle`` for the first *depth* contracts."""
        return settle_rates(as_of, depth, cfg=self.cfg, eod_mdp=self.eod)


def build_q20_pricer(
    as_of: datetime.date,
    depth: int,
    *,
    cfg: Optional[Q20Config] = None,
    builder: Any = None,
    base_cfg: Optional[Dict[str, Any]] = None,
    eod_mdp: Any = None,
    irs_mdp: Any = None,
) -> Any:
    """A Q20 pricer for *as_of*, calibrated to the first *depth* SR3 contracts.

    Reuses the production pipeline at the only seam that matters -- pricers in,
    curve out -- so the node construction (``_build_stirf_nodes``, central-bank
    meeting dates then contract maturities) and the Levenberg-Marquardt solve
    are the shipped ones, not a reimplementation that could drift from them::

        pricers = STIRFutureMDP("BARCHART_STIRF-RL").get_data(SFRCM1..depth)
        curve   = BARCHART_STIRF_CURVE._build_curve_from_pricers(...)
        pricer  = IRSwapsMDP._build_barchart_stirf_rl_curve(...)

    ``depth`` is passed by *rewriting the config's instrument list*, which is
    what makes a variable-depth build legitimate rather than a hack: the curve
    is told it has ``k`` instruments and sizes its own node grid accordingly.

    ``depth`` is the **strip depth** (contracts from
    ``quarterly_imm_sequence(..., include_current=True)``). The instrument count
    is derived from it by :func:`instrument_count`, which is one lower on IMM
    roll dates because the ``SFRCM`` ladder has already rolled. Asking for the
    strip depth on those ~4 days a year requests a contract past the cached
    strip and goes to the vendor.

    The whole call sits inside ``cache_only()`` when ``cfg.block_network``, so a
    date needing the network raises ``CacheMissOffline`` in microseconds instead
    of crawling Barchart. Measured cost on a covered date: ~0.15s, 0 requests.

    Returns an ``_IRSwapGenericCurve`` -- the same object type
    ``IRSwapsMDP.get_pricer`` returns -- so ``curve_ops.matched_forward_swap_rate``
    and ``ca_diagnostics.curve_nodes`` work on it unchanged.
    """
    cfg = cfg or Q20Config()
    depth = int(depth)
    if depth > cfg.max_instruments:
        raise ValueError(f"depth {depth} > max_instruments {cfg.max_instruments}")
    n_inst = instrument_count(as_of, depth)
    if n_inst < cfg.min_instruments:
        raise ValueError(
            f"{as_of}: {n_inst} instruments (strip depth {depth}) "
            f"< min_instruments {cfg.min_instruments}")

    if builder is None or base_cfg is None:
        from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

        builder = builder or BARCHART_STIRF_CURVE()
        base_cfg = dict(builder._STIRF_CURVE_CONFIGS[cfg.q20_curve])
    if eod_mdp is None:
        from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

        eod_mdp = STIRFutureMDP(source=cfg.eod_source)
    if irs_mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        irs_mdp = IRSwapsMDP(source=cfg.eod_source)

    curve_cfg = dict(base_cfg)
    curve_cfg["instruments"] = [f"{Q20_INSTRUMENT_PREFIX}{i}" for i in range(1, n_inst + 1)]
    ts = irs_mdp._to_barchart_stirf_timestamp(as_of)

    with cache_only(block=cfg.block_network):
        pricers = eod_mdp.get_data({"symbols": curve_cfg["instruments"], "timestamp": ts})
        present = {k: v for k, v in pricers.items() if v}
        if len(present) < n_inst:
            raise LookupError(
                f"{as_of}: only {len(present)}/{n_inst} SFRCM instruments resolved")
        curve, _solver = builder._build_curve_from_pricers(
            curve_name=cfg.q20_curve, timestamp=ts, cfg=curve_cfg, pricers=present)
        curve = builder._attach_curve_context(
            curve, curve_name=cfg.q20_curve, timestamp=ts, cfg=curve_cfg)
        return irs_mdp._build_barchart_stirf_rl_curve(
            requested_curve_name=cfg.q20_curve, resolved_curve_name=cfg.q20_curve,
            request_timestamp=ts, rl_curve_handle=curve, builder=builder)


# ===========================================================================
# Rates
# ===========================================================================
def q20_imm_forwards(
    pricer: Any, contracts: Sequence[Tuple[int, int]]
) -> Dict[Tuple[int, int], float]:
    """``(year, month) -> IMM x IMM quarterly forward`` in PERCENT, off *pricer*.

    The futures-equivalent rate: contract ``(y, m)`` references the quarter from
    its own IMM date to the next quarterly IMM date, and for SR3 those quarters
    tile the pack's matched swap exactly. Quarterly/quarterly, via
    ``curve_ops.matched_forward_swap_rate``, for the same reason the swap leg is
    -- the annual spec default biases the rate by ``0.375 * r^2``, up to 12bp.

    Priced once per date over the whole strip rather than once per pack: ten
    overlapping windows share thirteen quarters, so a per-pack loop does 40 curve
    calls where 13 suffice.
    """
    from RVUtils.ConvexityRV.ca_diagnostics import next_quarterly
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

    out: Dict[Tuple[int, int], float] = {}
    for y, m in contracts:
        if (y, m) in out:
            continue
        out[(y, m)] = matched_forward_swap_rate(
            pricer, imm_date(y, m), imm_date(*next_quarterly(y, m)))
    return out


def settle_rates(
    as_of: datetime.date,
    depth: int,
    *,
    cfg: Optional[Q20Config] = None,
    eod_mdp: Any = None,
) -> Dict[Tuple[int, int], float]:
    """``(year, month) -> 100 - SR3 settle`` in PERCENT, from the 17:00 EOD store.

    The observable. Used three ways: as the gate's reference, as the ``"settle"``
    rate source, and as what the backtest's futures legs actually mark against.
    """
    cfg = cfg or Q20Config()
    if eod_mdp is None:
        from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

        eod_mdp = STIRFutureMDP(source=cfg.eod_source)
    seq = quarterly_imm_sequence(as_of, int(depth))
    syms = [futures_symbol(y, m, cfg.futures_root) for y, m in seq]
    with cache_only(block=cfg.block_network):
        snap = eod_mdp.get_data({"symbols": syms, "timestamp": as_of})
    out: Dict[Tuple[int, int], float] = {}
    for (y, m), s in zip(seq, syms):
        v = snap.get(s)
        if not v:
            continue
        try:
            p = float(v[0].price())
        except Exception:                                      # noqa: BLE001
            continue
        if np.isfinite(p):
            out[(y, m)] = 100.0 - p
    return out


def forwards_to_prices(
    rates: Mapping[Tuple[int, int], float], root: str = "SR3"
) -> Dict[str, float]:
    """``{(y, m): rate_pct} -> {"SR3M26": 100 - rate}``.

    The adapter that lets the whole existing screen run off a curve. ``ca_snapshot``
    takes a ``symbol -> price`` mapping and does not care where the prices came
    from, so a Q20 panel is the near-pack panel with one substituted argument --
    which is the point: the two are then genuinely comparable, because every line
    of arithmetic after this one is shared.
    """
    return {futures_symbol(y, m, root): 100.0 - r for (y, m), r in rates.items()}


# ===========================================================================
# The gate
# ===========================================================================
def window_gate(
    spec: Any,
    *,
    q20_nodes: Sequence[datetime.date],
    q20_fwds: Mapping[Tuple[int, int], float],
    settles: Mapping[Tuple[int, int], float],
    depth: int,
    cfg: Q20Config,
) -> Dict[str, Any]:
    """Admissibility of one pack window on one date, with every input recorded.

    Returns the three gate conditions AND the measurements they were derived
    from, so a reader can re-cut the thresholds without rebuilding the panel.
    The conditions are deliberately independent -- resolution can pass while
    settle agreement fails and vice versa, and which one fails is the diagnosis.

    ``max_settle_diff_bp`` is a max over the four contracts, not a mean. Four
    errors of opposite sign average to zero and would let a badly fitted window
    through looking clean.
    """
    from RVUtils.ConvexityRV.ca_diagnostics import control_power_bp, window_resolution

    cts = list(spec.contracts)
    res = window_resolution(q20_nodes, spec.swap_start, spec.swap_end)

    diffs = []
    for k in cts:
        f, s = q20_fwds.get(k), settles.get(k)
        diffs.append((s - f) * 100.0 if (f is not None and s is not None
                                         and np.isfinite(f) and np.isfinite(s))
                     else np.nan)
    ad = np.abs(np.asarray(diffs, dtype=float))
    max_diff = float(np.nanmax(ad)) if np.isfinite(ad).any() else float("nan")
    mean_diff = float(np.nanmean(ad)) if np.isfinite(ad).any() else float("nan")

    fwds = [q20_fwds.get(k, np.nan) for k in cts]
    power = control_power_bp(fwds)

    covered = bool(spec.rank + 3 <= int(depth))
    resolved = bool(res["spans_window"] == 0.0
                    and res["n_nodes_inside"] >= cfg.gate_min_nodes_inside
                    and (not np.isfinite(power) or power >= cfg.gate_min_control_power_bp))
    agrees = bool(np.isfinite(max_diff) and max_diff <= cfg.gate_max_settle_diff_bp)

    ok = covered
    if cfg.gate_require_resolution:
        ok = ok and resolved
    if cfg.gate_require_settle_agreement:
        ok = ok and agrees

    return {
        "gate_covered": covered,
        "gate_resolved": resolved,
        "gate_settle_agrees": agrees,
        "gate_ok": bool(ok),
        "q20_n_nodes": res["n_nodes"],
        "q20_n_nodes_inside": res["n_nodes_inside"],
        "q20_segment_days": res["segment_days"],
        "q20_spans_window": res["spans_window"],
        "max_settle_diff_bp": max_diff,
        "mean_settle_diff_bp": mean_diff,
        "fwd_spread_bp": power,
        "strip_depth": int(depth),
    }


def apply_gate(panel: pd.DataFrame, *, require: Sequence[str] = ("gate_ok",)) -> pd.DataFrame:
    """Keep only rows passing every named gate column. Pure filter, no re-derivation."""
    out = panel
    for c in require:
        if c in out.columns:
            out = out[out[c].astype(bool)]
    return out.copy()


# ===========================================================================
# One day
# ===========================================================================
def day_rows(
    as_of: datetime.date,
    depth: int,
    *,
    cfg: Q20Config,
    s2cfg: Strat2Config,
    builder: Optional[Q20Builder] = None,
    swap_pricer: Any = None,
    swaps_mdp: Any = None,
) -> List[Dict[str, Any]]:
    """Every pack window on one date, both rate sources, gate columns attached.

    The row set is the union of what either source can quote, so the comparison
    in :func:`rate_source_comparison` is paired by construction. Rows carry both
    ``ca_bp_q20`` and ``ca_bp_settle``; which one is named ``ca_bp`` is decided
    by ``cfg.rate_source``, because that is the column the shared screen reads.

    The swap leg is ``USD-SOFR-1D`` at quarterly/quarterly and is **identical**
    between the two, so any difference between the two CA columns is entirely
    the futures leg -- which is what makes the comparison a measurement of the
    rate source rather than of two whole pipelines.

    Every row also carries the **zero-convexity control** and the two things it
    has to be read against:

    ``ca_synthetic_bp``
        The identical arithmetic with the four futures rates replaced by the
        *swap curve's own* IMM x IMM forwards. Those contain no convexity by
        construction -- they come off the very discount curve the swap leg is
        priced on -- so this must be ~0. Whatever it returns instead is our own
        convention error, measured with no external reference.
    ``swap_fwd_spread_bp`` / ``swap_n_nodes_inside``
        How much curvature the control was allowed to see, and whether the swap
        curve has any node inside the window. A 0.00bp control on a window whose
        four forwards are identical says nothing at all; reported together or
        the control is unfalsifiable. This matters more at deep ranks than near
        ones, because ``USD-SOFR-1D`` thins to annual nodes past ~2y.
    ``annual_qq_gap_bp``
        The matched swap at the ``usd_irs`` spec default (annual fixed) minus the
        quarterly/quarterly rate Citi specifies. A prediction, not a fudge:
        ``0.375 * r^2`` with no free parameter.

    **Degradation is per rate source, and it is recorded as data, never as
    absence.** If the Q20 curve cannot be built for this date -- too few
    calibration instruments (an IMM roll date at strip depth 4 has three), or a
    solver failure -- the date is NOT dropped. The settle rows are still emitted
    with ``q20_built=False``, every ``q20_*`` / ``*_q20`` column ``NaN``, and
    ``gate_resolved`` / ``gate_settle_agrees`` ``False``, so the row can never be
    mistaken for a resolved one. This is the difference between a sparse series
    and a series that is honest about being sparse: previously the whole date
    vanished and the chart drew a straight line through it.

    Row-level availability columns, all written on every row:

    ``strip_depth``     contiguous contracts available on this date
    ``n_instruments``   calibration instruments (one lower on IMM roll dates)
    ``q20_built``       did the Q20 curve solve
    ``q20_error``       the exception type if it did not, else ``""``
    ``max_rank_available`` deepest pack this date's strip can quote (``depth-3``)
    ``ca_source_ok``    is the column named ``ca_bp`` finite on this row
    """
    from RVUtils.ConvexityRV.ca_diagnostics import (
        annuity_weight_residual_bp,
        control_power_bp,
        curve_nodes,
        imm_forward_map,
        window_resolution,
    )
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

    builder = builder or Q20Builder(cfg)
    if swap_pricer is None:
        if swaps_mdp is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

            swaps_mdp = IRSwapsMDP(source=cfg.swap_source)
        swap_pricer = swaps_mdp.get_pricer(
            {"curve_name": cfg.swap_curve, "timestamp": as_of, "offline": True})
    ref = swap_pricer.reference_date()
    ref = ref.date() if hasattr(ref, "date") else ref
    if ref != as_of:
        # The store serves the previous close on a holiday. Marking a stale swap
        # curve against live settles manufactures a CA move out of nothing.
        raise LookupError(f"{as_of}: swap curve reference date is {ref}")

    seq = quarterly_imm_sequence(as_of, depth)
    setl = builder.settles(as_of, depth)

    # The Q20 curve is an ENHANCEMENT of the settle panel, not a precondition for
    # it. A build failure costs this date its q20 columns and nothing else.
    pricer = None
    q20_error = ""
    try:
        pricer = builder.pricer(as_of, depth)
    except Exception as exc:                                   # noqa: BLE001
        q20_error = type(exc).__name__
    nodes = curve_nodes(pricer) if pricer is not None else []
    fwds = q20_imm_forwards(pricer, seq) if pricer is not None else {}

    px_q20 = forwards_to_prices(fwds, cfg.futures_root)
    px_set = forwards_to_prices(setl, cfg.futures_root)

    snap_q20 = (ca_snapshot(as_of, s2cfg, futures_prices=px_q20, swap_pricer=swap_pricer)
                if pricer is not None else pd.DataFrame())
    snap_set = ca_snapshot(as_of, s2cfg, futures_prices=px_set, swap_pricer=swap_pricer)
    ca_set = dict(zip(snap_set["pack"], snap_set["ca_bp"])) if len(snap_set) else {}
    pr_set = dict(zip(snap_set["pack"], snap_set["pack_rate"])) if len(snap_set) else {}

    # The row set is the UNION of what either source can quote, keyed by pack
    # label, with the Q20 row preferred as the base when both exist. The two
    # snapshots share their swap leg exactly, so the non-futures columns
    # (swap_rate, time_weight, t_mid, the window dates) are identical either way
    # and the choice of base cannot move them.
    base: Dict[str, Any] = {}
    if len(snap_set):
        base.update({r["pack"]: r for _, r in snap_set.iterrows()})
    if len(snap_q20):
        base.update({r["pack"]: r for _, r in snap_q20.iterrows()})
    q20_packs = set(snap_q20["pack"]) if len(snap_q20) else set()

    # --- zero-convexity control, off the SWAP curve's own IMM forwards
    swap_nodes = curve_nodes(swap_pricer)
    swap_fwds = imm_forward_map(swap_pricer, seq)

    specs = {s.label: s for s in pack_windows(as_of, s2cfg)}
    n_inst = instrument_count(as_of, depth)
    rows: List[Dict[str, Any]] = []
    for label in sorted(base, key=lambda p: specs[p].rank if p in specs else 10**6):
        r = base[label]
        spec = specs.get(label)
        if spec is None:
            continue
        g = window_gate(spec, q20_nodes=nodes, q20_fwds=fwds, settles=setl,
                        depth=depth, cfg=cfg)
        syn = [swap_fwds[k] for k in spec.contracts]
        swap_res = window_resolution(swap_nodes, spec.swap_start, spec.swap_end)
        s_an = matched_forward_swap_rate(swap_pricer, spec.swap_start, spec.swap_end,
                                         frequency=None, leg2_frequency=None)
        g["pack_rate_synthetic"] = float(np.mean(syn))
        g["ca_synthetic_bp"] = (float(np.mean(syn)) - float(r["swap_rate"])) * 100.0
        g["ca_synthetic_pred_bp"] = annuity_weight_residual_bp(syn, float(r["swap_rate"]))
        g["swap_fwd_spread_bp"] = control_power_bp(syn)
        g["swap_n_nodes"] = swap_res["n_nodes"]
        g["swap_n_nodes_inside"] = swap_res["n_nodes_inside"]
        g["swap_spans_window"] = swap_res["spans_window"]
        g["annual_qq_gap_bp"] = (s_an - float(r["swap_rate"])) * 100.0
        row: Dict[str, Any] = dict(r)
        row.update(g)
        has_q20 = label in q20_packs
        row["pack_rate_q20"] = float(r["pack_rate"]) if has_q20 else float("nan")
        row["ca_bp_q20"] = float(r["ca_bp"]) if has_q20 else float("nan")
        row["pack_rate_settle"] = float(pr_set.get(label, np.nan))
        row["ca_bp_settle"] = float(ca_set.get(label, np.nan))
        row["ca_diff_bp"] = row["ca_bp_q20"] - row["ca_bp_settle"]
        row["t1_first"] = float(spec.t1s[0])
        row["colour"] = spec.colour
        # --- availability, recorded as data so sparsity is visible downstream
        row["strip_depth"] = int(depth)
        row["n_instruments"] = int(n_inst)
        row["max_rank_available"] = int(max_rank_for_depth(depth))
        row["q20_built"] = bool(pricer is not None)
        row["q20_error"] = q20_error
        # `ca_bp` is whatever `cfg.rate_source` names, ALWAYS -- never a silent
        # fallback to the other source. A missing q20 curve gives NaN under
        # rate_source="q20", which is the honest answer.
        src = "settle" if cfg.rate_source == "settle" else "q20"
        row["pack_rate"] = row[f"pack_rate_{src}"]
        row["ca_bp"] = row[f"ca_bp_{src}"]
        row["ca_source_ok"] = bool(np.isfinite(row["ca_bp"]))
        rows.append(row)
    return rows


# ===========================================================================
# Universe -> Strat2Config
# ===========================================================================
def deep_pack_config(
    *,
    rank_start: int = 5,
    n_packs: int = 13,
    base: Optional[Strat2Config] = None,
    **overrides: Any,
) -> Strat2Config:
    """The ``Strat2Config`` for a deep-pack run, with ``n_contracts`` implied.

    ``rank_start=5, n_packs=13`` is **exactly Citi's published SOFR screen**:
    windows 5..17, Reds M4-H5 through Golds M7-H8, and it needs
    ``n_contracts = 17 + 3 = 20``. Deriving ``n_contracts`` here rather than
    letting a caller pass it is what stops the universe and the strip depth
    drifting apart -- ``Strat2Config.__post_init__`` would raise, but only after
    a panel had been built against the wrong strip.

    Note ``futures_source`` is left at ``BARCHART_STIRF-RL``: the screen may be
    computed off Q20 forwards, but the **book is marked off settles**.
    """
    base = base or Strat2Config()
    n_contracts = rank_start + n_packs - 1 + 3
    return replace(base, rank_start=int(rank_start), n_packs=int(n_packs),
                   n_contracts=int(n_contracts), **overrides)


# ===========================================================================
# Reporting
# ===========================================================================
def settle_agreement_summary(
    panel: pd.DataFrame, *, by: Sequence[str] = ("year", "rank")
) -> pd.DataFrame:
    """``|settle - Q20 forward|`` per group: median, p95, max, and the CA impact.

    The number that decides whether the rate source is admissible. Grouped by
    year AND rank because the failure is jointly determined -- 2019 fails at the
    front and passes at the back, which a marginal table in either variable
    alone would average away into a uniform mediocrity.
    """
    df = panel.copy()
    if "year" in by and "year" not in df.columns:
        df["year"] = pd.to_datetime(df["date"]).dt.year
    g = df.groupby(list(by))
    out = pd.DataFrame({
        "n": g.size(),
        "diff_median_bp": g["max_settle_diff_bp"].median(),
        "diff_p95_bp": g["max_settle_diff_bp"].quantile(0.95),
        "diff_max_bp": g["max_settle_diff_bp"].max(),
        "ca_diff_median_bp": g["ca_diff_bp"].median() if "ca_diff_bp" in df else np.nan,
        "ca_diff_sd_bp": g["ca_diff_bp"].std() if "ca_diff_bp" in df else np.nan,
        "nodes_inside_median": g["q20_n_nodes_inside"].median(),
        "pass_rate": g["gate_ok"].mean(),
    })
    return out


def gate_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Incidence of each gate condition by year -- what the gate removes and why."""
    df = panel.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    cols = ["gate_covered", "gate_resolved", "gate_settle_agrees", "gate_ok"]
    g = df.groupby("year")
    out = g[cols].mean()
    out["n_rows"] = g.size()
    out["n_dates"] = g["date"].nunique()
    return out


def rate_source_comparison(panel: pd.DataFrame) -> pd.DataFrame:
    """Q20-forward CA against settle CA, per year and rank.

    The control demanded by the whole design: if the gate is doing its job these
    two agree to well inside a basis point, and a material divergence means the
    gate failed rather than that the curve is adding information. Correlation is
    reported alongside the level difference because a constant offset and a
    decorrelated series are different diseases.
    """
    df = panel.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    rows = []
    for (y, r), g in df.groupby(["year", "rank"]):
        a = g["ca_bp_q20"].to_numpy(float)
        b = g["ca_bp_settle"].to_numpy(float)
        ok = np.isfinite(a) & np.isfinite(b)
        corr = (float(np.corrcoef(a[ok], b[ok])[0, 1])
                if ok.sum() >= 3 and np.std(a[ok]) > 0 and np.std(b[ok]) > 0 else np.nan)
        rows.append({
            "year": int(y), "rank": int(r), "n": int(ok.sum()),
            "ca_q20_median": float(np.nanmedian(a[ok])) if ok.any() else np.nan,
            "ca_settle_median": float(np.nanmedian(b[ok])) if ok.any() else np.nan,
            "diff_median_bp": float(np.nanmedian(a[ok] - b[ok])) if ok.any() else np.nan,
            "abs_diff_median_bp": float(np.nanmedian(np.abs(a[ok] - b[ok]))) if ok.any() else np.nan,
            "corr": corr,
        })
    return pd.DataFrame(rows).set_index(["year", "rank"])


# ===========================================================================
# The known-answer tie-out
# ===========================================================================
#: Citi Research, *Rates Vol Lab*, 12-Jun-2023, Figure 58 -- close **6/9/2023**.
#: "Convexity adjustments for 1y SOFR futures packs (vs CME swaps)", 13 rows,
#: windows 5..17. Reproduced verbatim from
#: ``docs/convexityrv/research/01-citi-stir-convexity-vs-butterfly.md`` sec 7.8.
#: Columns: pack -> (CA bp, Model bp, VsModel bp, 3m Roll, Implied Vol, Realized
#: Vol). **Blues M6-H7 at 15.40 and Golds M7-H8 at 22.29 are the two rows the
#: rank-2..10 strategy can never reach**, and reaching them is the point of this
#: module.
CITI_SOFR_20230609: Dict[str, Dict[str, float]] = {
    "M4-H5": {"rank": 5,  "ca_bp": 4.03,  "model_bp": 2.94,  "vs_model_bp": 1.09,
              "roll_3m_bp": 0.88, "implied_vol_bp": 199.5, "realized_vol_bp": 229.7},
    "U4-M5": {"rank": 6,  "ca_bp": 4.41,  "model_bp": 3.79,  "vs_model_bp": 0.62,
              "roll_3m_bp": 0.38, "implied_vol_bp": 178.1, "realized_vol_bp": 201.4},
    "Z4-U5": {"rank": 7,  "ca_bp": 5.16,  "model_bp": 4.66,  "vs_model_bp": 0.49,
              "roll_3m_bp": 0.74, "implied_vol_bp": 167.7, "realized_vol_bp": 180.3},
    "H5-Z5": {"rank": 8,  "ca_bp": 6.10,  "model_bp": 5.53,  "vs_model_bp": 0.58,
              "roll_3m_bp": 0.95, "implied_vol_bp": 161.6, "realized_vol_bp": 166.3},
    "M5-H6": {"rank": 9,  "ca_bp": 8.24,  "model_bp": 6.36,  "vs_model_bp": 1.88,
              "roll_3m_bp": 2.14, "implied_vol_bp": 168.5, "realized_vol_bp": 156.4},
    "U5-M6": {"rank": 10, "ca_bp": 9.77,  "model_bp": 7.16,  "vs_model_bp": 2.60,
              "roll_3m_bp": 1.52, "implied_vol_bp": 166.3, "realized_vol_bp": 148.8},
    "Z5-U6": {"rank": 11, "ca_bp": 11.70, "model_bp": 8.02,  "vs_model_bp": 3.67,
              "roll_3m_bp": 1.93, "implied_vol_bp": 166.5, "realized_vol_bp": 142.2},
    "H6-Z6": {"rank": 12, "ca_bp": 13.70, "model_bp": 8.96,  "vs_model_bp": 4.74,
              "roll_3m_bp": 2.00, "implied_vol_bp": 166.0, "realized_vol_bp": 136.1},
    "M6-H7": {"rank": 13, "ca_bp": 15.40, "model_bp": 9.98,  "vs_model_bp": 5.42,
              "roll_3m_bp": 1.70, "implied_vol_bp": 163.1, "realized_vol_bp": 130.9},
    "U6-M7": {"rank": 14, "ca_bp": 16.84, "model_bp": 11.10, "vs_model_bp": 5.74,
              "roll_3m_bp": 1.44, "implied_vol_bp": 159.0, "realized_vol_bp": 126.2},
    "Z6-U7": {"rank": 15, "ca_bp": 18.27, "model_bp": 12.23, "vs_model_bp": 6.04,
              "roll_3m_bp": 1.43, "implied_vol_bp": 155.1, "realized_vol_bp": 121.9},
    "H7-Z7": {"rank": 16, "ca_bp": 20.08, "model_bp": 13.37, "vs_model_bp": 6.71,
              "roll_3m_bp": 1.81, "implied_vol_bp": 152.8, "realized_vol_bp": 118.0},
    "M7-H8": {"rank": 17, "ca_bp": 22.29, "model_bp": 14.50, "vs_model_bp": 7.79,
              "roll_3m_bp": 2.21, "implied_vol_bp": 151.9, "realized_vol_bp": 113.8},
}
