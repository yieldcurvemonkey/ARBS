"""Citi's SOFR convexity **valuation screen**: the two legs the port was missing.

Citi's methodology footnote, verbatim (*Rates Vol Lab -- Forward steepener and
vol divergence*, 12-Jun-2023, Figure 58, close 6/9/2023):

    "Convexity adjustments for 1y SOFR packs are computed as the spread between
     the pack's rate (the average of 4 SOFR rates in the pack) and
     matched-maturity forward 1y CME swap rate. **The model for convexity
     adjustment is the Ho-Lee model calibrated to cap/floor vols.** Implied vol
     is calculated by matching the model to the observed convexity adjustment.
     **Realized vol is 3m realized vol of the corresponding pack.** For each
     valuation metric, we mark three best short convexity trades in bold."

Four claims, and before this module only two of them were built:

==================================  =========================================
claim                               where it lives
==================================  =========================================
CA = pack rate - matched fwd swap   ``strat2_sofr_convexity.ca_snapshot``
implied vol = invert Ho-Lee on CA   ``holee.implied_vol_from_ca_bp``
**model CA from cap/floor vols**    **here** -- :func:`pack_capfloor_vol`,
                                    :func:`model_ca_from_sigma`
**3m realized vol of the pack**     **here** -- :func:`pack_realized_vol`
==================================  =========================================

``strat2_sofr_convexity``'s default ``sigma_model_mode="fit"`` regresses a
smooth variance term structure onto *the same day's own CA curve*. Its own
docstring flags the consequence: ``vs_model`` is then a residual centred on zero
across packs, i.e. a **cross-sectional** dislocation ("which pack is rich versus
the other packs today"). Citi's ``Vs Model`` is a **vol-market** dislocation
("is the CA rich versus what the option market is charging for that vol"), which
is why Citi's column can be systematically signed and ours could not be. This
module supplies the external sigma that closes that gap. Label the output
accordingly: ``vs_model_capfloor_bp`` is a vol-market dislocation. It is not
interchangeable with the fitted ``vs_model_bp`` and the notebook prints both.


WHY A CAPLET NORMAL VOL *IS* THE HO-LEE SIGMA
---------------------------------------------
Ho-Lee is ``dr = theta(t) dt + sigma dW`` with constant absolute sigma and no
mean reversion. Under it **every** forward rate has the same constant normal
volatility sigma -- the term structure of instantaneous forward vol is flat in
both t and T. So the Bachelier (normal) implied vol of a caplet on the 3M
forward rate underlying an SR3 contract maps onto sigma with no adjustment at
all; there is no forward-vol-to-short-rate-vol conversion to get wrong. That is
the whole reason Citi can say "Ho-Lee calibrated to cap/floor vols" in six words
and expect it to be unambiguous.

Two consequences that are *not* free, and are handled explicitly:

* A pack spans four caplets with four different expiries and four different
  normal vols. Ho-Lee wants one sigma. The primary reduction is
  ``STIRCapFloorValue.FLAT_BP_VOL`` -- the single normal vol that reprices the
  whole four-caplet strip -- because that is literally a calibration of a
  one-parameter normal model to the strip, which is what "calibrated to
  cap/floor vols" means. The vega-flat average ``BPVOL`` is carried alongside as
  ``sigma_capfloor_mean_bp``; on the measured sample the two agree to well
  inside a basis point except at the front, where the caplet vols fan out most.
* **Caps and floors are struck; Ho-Lee's sigma is not.** The strike convention
  is therefore a config knob, defaulted to ``atm_per_caplet`` (each caplet at
  its own listed ATM strike), which is the natural reading of "the cap/floor
  vol" and the only one that needs no view on where the strip should be struck.
  :func:`strike_convention_sensitivity` measures what the alternative
  (``flat_swap_rate``, every caplet struck at the pack's own matched forward
  swap rate) does to the model CA, so the reader is never asked to take the
  default on trust.


THE ACCRUAL WINDOW IS THE PACK'S OWN, AND THAT IS A CHOICE WITH CONSEQUENCES
----------------------------------------------------------------------------
The vol used for pack *k* is the vol of the strip of caplets covering **that
pack's own four contracts** -- a forward-starting cap, ``3*(k-1)M`` into
``1Y``, not a spot-starting cap running to the pack's end. That is the reading
the pack-level Ho-Lee formula requires: ``CA_pack = 1/2 sigma^2 mean_i(T1_i^2)``
prices the four contracts' own convexity, so sigma must be the vol *those* four
contracts carry.

It is worth knowing that this is **not** what reproduces Citi's printed ``Model``
column's level. Backing Citi's own sigma out of their published table on
6/9/2023 (``sigma = sqrt(2 * Model / mean(T1^2))``) gives a term structure that
starts materially above the forward-starting strip vol and converges to it by
the back of the strip. :func:`spot_starting_cap_vol` computes the obvious
alternative reading -- a cap from *today* to the pack's end -- so the notebook
can report which reading is closer, as a measurement rather than an assertion.
Neither is silently substituted for the other.


DATA REALITY, MEASURED BEFORE ANY OF THIS WAS WRITTEN
------------------------------------------------------
The cap/floor snapshot is assembled from **listed CME SR3 (SFR) options** via
``STIRFutureOptionMDP``/Barchart. A month-grid probe of pack ranks 2/5/9/13 over
2019-01..2026-08, run entirely under :func:`~listed_cache_guard.cache_only`, is
what set the defaults here. Two structural limits came out of it and both are
permanent features of the data, not bugs to route around:

* **No listed SR3 option history before ~2022.** Essentially every 2019, 2020
  and 2021 cell fails with *"Could not resolve listed ATM option"*, and each
  failure is slow (up to 120s) because a miss on a deferred contract makes the
  MDP walk the whole listed strike ladder. The dense part of the CA panel
  (2019-2023) therefore overlaps the vol data only from 2022 on.
* **The strip runs out around 3.5 years.** Rank 17 (Golds) fails on every date
  tested -- there is no listed ATM SR3 option four years forward. Citi's Golds
  row cannot be reproduced from listed vol at all.

**Cost, measured on five consecutive business days x nine pack ranks:** 19.7s
cold, 18.8s warm, i.e. **2.1s per (date, pack) cell**, firing ~32,000 blocked
outbound requests per date. It does **not** amortise across consecutive dates,
because each date has its own at-the-money strike to locate. A daily build over
2022-2026 is therefore a multi-hour job and
:func:`build_capfloor_vol_panel` is resumable for that reason.

Where a vol is unavailable the sigma is **NaN and the model CA is NaN**. There
is deliberately no fall-back to the CA-fitted sigma anywhere in this module: a
model leg quietly backfilled from the observed CA would make ``vs_model`` zero
by construction and look like a tight fit. :func:`build_capfloor_vol_panel`
returns a ``reason`` column so the NaNs can be counted and attributed.

**Every network-facing call runs inside ``cache_only()`` by default.** Measured
on the probe: a single deferred-contract cell fires up to ~10,000 blocked
outbound requests as the MDP walks the listed strike ladder looking for quotes
that were never cached. Blocked, each costs microseconds; unblocked, that is a
404 storm against a vendor. ``allow_network=True`` exists, is not the default,
and is call-capped by ``max_network_cells``.


THREE UPSTREAM DEFECTS, WORKED AROUND HERE AND REPORTED RATHER THAN PATCHED
---------------------------------------------------------------------------
The first two live in ``MDP/STIRCapFloors/STIRCapFloorMDP.py``, which this work
was not permitted to modify. The notebook's final section carries the full
write-up. **The third has since been fixed at source** -- see below; it is left
in place because the workaround is now a detector.

1. ``_contracts_for_explicit_window`` sizes its candidate ladder as
   ``ceil(window_days/75) + 4`` contracts **from the front of the curve**, so a
   *forward-starting* window comes back short with no error -- rank 9 on
   2023-06-09 returned **one** leg instead of four. Worked around by using the
   ``expiry``/``tail`` request form; see :func:`pack_capfloor_vol`.
2. ``_discount`` falls through to ``handle[ql_date]`` for any curve without a
   ``.discount`` method -- i.e. every **rateslib** curve, including
   ``CITIVELO_EXCEL`` -- and rateslib's ``__getitem__`` compares the key against
   a ``datetime.datetime``, raising ``TypeError: '<' not supported between
   instances of 'Date' and 'datetime.datetime'``. That makes
   ``strike_convention="flat_swap_rate"`` and ``weight_method="duration"``
   unusable on a rateslib curve. Worked around by defaulting to
   ``atm_per_caplet`` (which never reaches ``_discount``) and by running
   :func:`strike_convention_sensitivity` on a QuantLib-backed curve, with a
   control proving the swap does not move the ATM leg.
3. **FIXED AT SOURCE, 2026-08-19.** On an IMM date itself,
   ``packs.quarterly_imm_sequence(include_current=True)`` keeps the contract
   whose IMM date is today while the option MDP's ``_imm_cutoff`` had already
   rolled past it. The two then disagreed about which four contracts a pack
   contains and the leg-identity guard refused the cell -- the right answer, but
   it cost one date per quarter, and all 26 refused cells were IMM dates. Both
   ladders now keep the contract: ``tos._imm_cutoff`` returns IMM + 1 day, so a
   contract survives its own IMM date and rolls the next. The evidence (the
   vendor "continuous ladder" corroboration was circular; the settlement grid
   classifies the starting contract as live on 32/32 IMM dates and the ending
   one as settled on 18/18) is in ``packs``'s module docstring, and
   ``tests/test_sr3_imm_roll_convention.py`` is the cross-site invariant.

   The leg-identity guard in :func:`pack_capfloor_vol` STAYS. It is now a
   detector rather than a workaround: ``reason == "contract_mismatch"`` should
   be empty, and if it ever returns it means the two ladders have drifted apart
   again. Do not weaken it to "probably fine now".
"""

from __future__ import annotations

import datetime
import math
import os
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_ca_bp
from RVUtils.ConvexityRV.listed_cache_guard import cache_only, network_calls_blocked
from RVUtils.ConvexityRV.packs import (
    PACK_COLOURS,
    contract_code,
    matched_swap_dates,
    pack_label,
    pack_t1s,
    quarterly_imm_sequence,
)

__all__ = [
    "CAValuationConfig",
    "CapFloorVol",
    "CITI_CONVENTION",
    "SHORT_CONVEXITY_METRICS",
    "sfr_option_contract",
    "pack_spec_for_rank",
    "pack_capfloor_vol",
    "spot_starting_cap_vol",
    "build_capfloor_vol_panel",
    "sigma_wide",
    "model_ca_from_sigma",
    "bday_reindex",
    "pack_realized_vol",
    "realized_vol_coverage",
    "valuation_screen",
    "short_convexity_flags",
    "top_short_convexity",
    "strike_convention_sensitivity",
    "citi_implied_model_sigma",
    "vol_panel_coverage",
]

#: The convention Citi's published tables use: ``CA = 1/2 sigma^2 mean(T1^2)``.
#: Passed EXPLICITLY at every call site. ``holee.DEFAULT_CONVENTION`` is a
#: module-level default that is not ours to depend on -- it was observed
#: changing under this module during development -- and silently inheriting
#: ``"hull"`` would shift every model CA by ~10-25% with no error raised.
CITI_CONVENTION = "citi"

#: The three valuation metrics of Citi's screen, in the direction that makes a
#: HIGHER number a more attractive SHORT-convexity trade (the market is paying
#: too much for convexity).
SHORT_CONVEXITY_METRICS: Tuple[str, ...] = (
    "vs_model_capfloor_bp",      # observed CA rich to the cap/floor-calibrated model
    "implied_minus_realized_bp",  # CA-implied vol rich to delivered vol
    "implied_over_realized",     # the same, as Citi's printed ratio
)

_REASON_OK = "ok"


# ===========================================================================
# Config
# ===========================================================================
@dataclass(frozen=True)
class CAValuationConfig:
    """Every knob of the valuation screen, documented inline."""

    # ------------------------------------------------------------ vol source
    curve: str = "USD-SOFR-1D"
    """Discount/forward curve the cap/floor legs are priced against. Matched to
    ``Strat2Config.curve`` so the model leg and the observed CA see one curve."""

    curve_source: str = "CITIVELO_EXCEL"
    """``IRSwapsMDP`` source behind that curve. ``STIRCapFloorMDP``'s own class
    default is ``ERIS_EOD_LIVE-QL_BASIC``; it must be overridden or the model
    leg is calibrated on a different curve from the CA it is compared to."""

    option_source: str = "BARCHART_STIRFO-QL"
    """``STIRFutureOptionMDP`` source for the listed SR3 option quotes."""

    structure: str = "CAP"
    """``"CAP"`` or ``"FLOOR"``. At-the-money the two carry the same normal vol
    up to put/call parity and strike snapping, so this is a diagnostic knob;
    :func:`build_capfloor_vol_panel` can be run both ways to size that noise."""

    strike_convention: str = "atm_per_caplet"
    """``"atm_per_caplet"`` -- each caplet at its own listed ATM strike -- or
    ``"flat_swap_rate"``, every caplet struck at the pack's matched forward swap
    rate and snapped to the listed ladder. The default needs no view; see
    :func:`strike_convention_sensitivity` for what the alternative does."""

    weight_method: str = "equal"
    """Caplet weighting inside the strip. ``"equal"`` matches the pack rate,
    which is the *unweighted* mean of four contract rates. ``"duration"`` would
    annuity-weight, which the pack rate does not."""

    vol_measure: str = "flat"
    """``"flat"`` -> ``FLAT_BP_VOL``, the single normal vol repricing the whole
    strip (a genuine one-parameter calibration). ``"mean"`` -> ``BPVOL``, the
    weighted average of the four caplet vols. Both are always stored; this picks
    which one ``sigma_capfloor_bp`` aliases."""

    # ------------------------------------------------------------ Ho-Lee
    holee_convention: str = CITI_CONVENTION
    """``"citi"`` (``1/2 sigma^2 mean(T1^2)``) reproduces the published tables.
    Never left to the imported module default -- see :data:`CITI_CONVENTION`."""

    ca_floor_bp: float = 0.0
    """Observed CA at or below this is not inverted for an implied vol (a
    negative adjustment is not representable under Ho-Lee). Citi prints n/a."""

    # ------------------------------------------------------------ realized vol
    realized_window_days: int = 63
    """Business days in "3m realized vol of the corresponding pack". 63 = 252/4,
    i.e. one quarter of a 252-business-day year -- the same window
    ``Strat2Config.realized_window_days`` uses, kept identical on purpose so the
    two realized-vol series are comparable."""

    realized_min_obs: int = 42
    """Minimum non-NaN daily changes inside the window before a number is
    emitted. 42 = 2/3 of 63. Below it the cell is NaN. This is the gate that
    stops a sparse panel from printing a "3m realized vol" computed off eleven
    observations spread over five months -- the specific defect the business-day
    reindex in :func:`bday_reindex` exists to expose."""

    realized_annualisation: float = 252.0
    """``sqrt(252)`` scaling of daily close-to-close pack-rate changes in bp.
    252 business days per year is the convention that puts the result in the
    same bp/yr normal units as a cap/floor vol and as the Ho-Lee implied vol,
    which is the entire point of the column."""

    # ------------------------------------------------------------ ranking
    top_n_per_metric: int = 3
    """*"For each valuation metric, we mark three best short convexity trades."*"""

    rank_metrics: Tuple[str, ...] = SHORT_CONVEXITY_METRICS

    # ------------------------------------------------------------ network
    allow_network: bool = False
    """``False`` (default) wraps every MDP call in ``cache_only()``. A miss then
    fails in microseconds instead of crawling the vendor's strike ladder."""

    max_network_cells: int = 0
    """Hard cap on (date, rank) cells allowed to touch the network when
    ``allow_network=True``. 0 means no cell may. Once the cap is hit the panel
    falls back to cache-only for the remainder of the run."""

    progress_every: int = 25
    """Print a progress line every N dates. 0 silences it."""

    def __post_init__(self) -> None:
        if self.vol_measure not in ("flat", "mean"):
            raise ValueError(f"bad vol_measure {self.vol_measure!r}")
        if self.strike_convention not in ("atm_per_caplet", "flat_swap_rate"):
            raise ValueError(f"bad strike_convention {self.strike_convention!r}")
        if self.structure not in ("CAP", "FLOOR"):
            raise ValueError(f"bad structure {self.structure!r}")
        if self.realized_min_obs > self.realized_window_days:
            raise ValueError("realized_min_obs cannot exceed realized_window_days")


# ===========================================================================
# One (date, pack) cap/floor vol
# ===========================================================================
@dataclass(frozen=True)
class CapFloorVol:
    """The cap/floor calibration of one pack on one date.

    ``sigma_flat_bp`` / ``sigma_mean_bp`` are NaN whenever ``reason != "ok"``,
    and ``reason`` is what the coverage tally counts.
    """

    date: datetime.date
    rank: int
    pack: str
    sigma_flat_bp: float
    sigma_mean_bp: float
    reason: str
    n_legs: int = 0
    contracts: Tuple[str, ...] = ()
    caplet_vols_bp: Tuple[float, ...] = ()
    strikes_rate: Tuple[float, ...] = ()
    quote_sources: Tuple[str, ...] = ()
    swap_start: Optional[datetime.date] = None
    swap_end: Optional[datetime.date] = None
    blocked_calls: int = 0
    detail: str = ""

    def as_row(self) -> Dict[str, Any]:
        return {
            "date": pd.Timestamp(self.date),
            "rank": int(self.rank),
            "pack": self.pack,
            "sigma_capfloor_flat_bp": float(self.sigma_flat_bp),
            "sigma_capfloor_mean_bp": float(self.sigma_mean_bp),
            "reason": self.reason,
            "n_legs": int(self.n_legs),
            "contracts": "|".join(self.contracts),
            "caplet_vols_bp": "|".join(f"{v:.2f}" for v in self.caplet_vols_bp),
            "strikes_rate": "|".join(f"{v:.4f}" for v in self.strikes_rate),
            "quote_sources": "|".join(sorted(set(self.quote_sources))),
            "swap_start": self.swap_start,
            "swap_end": self.swap_end,
            "blocked_calls": int(self.blocked_calls),
            "detail": self.detail,
        }


def sfr_option_contract(year: int, month: int) -> str:
    """``(2024, 6) -> 'SFRM24'`` -- the option MDP's contract token.

    The futures side of this codebase speaks ``SR3M24``; ``STIRCapFloorMDP``
    resolves options off root ``SFR``. Same contract, different root, and the
    leg-identity assert in :func:`pack_capfloor_vol` compares in this space.
    """
    return f"SFR{contract_code(year, month)[0]}{year % 100:02d}"


def pack_spec_for_rank(
    as_of: datetime.date, rank: int,
) -> Tuple[str, Tuple[Tuple[int, int], ...], datetime.date, datetime.date, List[float]]:
    """``(label, contracts, swap_start, swap_end, t1s)`` for pack window *rank*.

    Rank is 1-indexed on the first contract, exactly as
    ``strat2_sofr_convexity.pack_windows`` numbers them, so a label produced here
    joins straight onto that panel.
    """
    if rank < 1:
        raise ValueError(f"rank must be >= 1, got {rank}")
    seq = quarterly_imm_sequence(as_of, rank + 3)
    cts = tuple(seq[rank - 1:rank + 3])
    if len(cts) != 4:
        raise ValueError(f"could not resolve 4 contracts for rank {rank} on {as_of}")
    start, end = matched_swap_dates(cts)
    return pack_label(cts[0], cts[-1]), cts, start, end, pack_t1s(as_of, cts)


def _capfloor_mdp(cfg: CAValuationConfig) -> Any:
    from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMDP

    return STIRCapFloorMDP(curve_source=cfg.curve_source, option_source=cfg.option_source)


def _strip_vols(ctx: Any) -> Tuple[float, float]:
    """``(FLAT_BP_VOL, BPVOL)`` in bp/yr from a built cap/floor context.

    Units: ``_strip_price_with_flat_sigma`` prices in futures **price points**,
    so the bisection's sigma is in price points per sqrt-year and the ``* 100``
    inside ``FLAT_BP_VOL`` converts to bp of rate. ``iv_normal_bps`` is
    ``iv_normal * 100`` from the same price space. The two are therefore in the
    same units, which is what makes them comparable and what makes either of
    them a Ho-Lee sigma in bp/yr.
    """
    from Query.STIRCapFloors.STIRCapFloorValue import (
        STIRCapFloorValue,
        STIRCapFloorValueFunctionMap,
    )

    legs = list(ctx.legs)
    package = [leg.build_pricable() for leg in legs]
    vmap = STIRCapFloorValueFunctionMap(
        context=ctx, package=package, risk_weights=[1.0] * len(package))
    flat = float(vmap.apply(value=STIRCapFloorValue.FLAT_BP_VOL))
    mean = float(vmap.apply(value=STIRCapFloorValue.BPVOL))
    return flat, mean


def _fail(as_of, rank, pack, reason, detail, blocked) -> CapFloorVol:
    return CapFloorVol(date=as_of, rank=rank, pack=pack, sigma_flat_bp=float("nan"),
                       sigma_mean_bp=float("nan"), reason=reason,
                       blocked_calls=blocked, detail=str(detail)[:200])


def pack_capfloor_vol(
    as_of: datetime.date,
    rank: int,
    cfg: CAValuationConfig,
    *,
    mdp: Any = None,
    expiry_months: Optional[int] = None,
    tail_months: int = 12,
    verify_contracts: bool = True,
) -> CapFloorVol:
    """Normal vol of the caplet strip covering pack *rank*'s own accrual window.

    **The expiry/tail request form is used, not the explicit swap_start/swap_end
    form, and that is load-bearing.** ``STIRCapFloorMDP._contracts_for_explicit_
    window`` sizes its candidate ladder as ``ceil(window_days/75)+4`` contracts
    *from the front of the curve*, which for a forward-starting window is far
    too short: measured on 2023-06-09, rank 9 came back with **one** leg instead
    of four, and the resulting "pack vol" was a single caplet. The
    ``expiry``/``tail`` path calls ``resolve_quarterly_contracts(as_of,
    start_index=expiry//3, count=tail//3)`` and returns exactly four. See the
    module docstring of the notebook for the follow-up this needs upstream.

    Every failure mode returns a ``CapFloorVol`` with a NaN sigma and a
    ``reason``, never an exception and never a substituted value:

    ``no_option``      the listed ATM SR3 option does not exist / is not cached
    ``no_curve``       the swap curve is unavailable for that date
    ``leg_count``      the MDP returned other than four legs
    ``contract_mismatch``  the legs are not the pack's own four contracts
    ``window_mismatch``    the strip's accrual window is not the pack's
    ``bad_vol``        the calibration returned a non-finite or non-positive vol
    ``other``          anything else, with the exception text in ``detail``
    """
    mdp = mdp if mdp is not None else _capfloor_mdp(cfg)
    pack, cts, start, end, _ = pack_spec_for_rank(as_of, rank)
    want = [sfr_option_contract(y, m) for y, m in cts]
    exp_m = 3 * (rank - 1) if expiry_months is None else int(expiry_months)
    b0 = network_calls_blocked()

    req = {
        "endpoint": "synthetic_capfloor_snapshot",
        "structure": cfg.structure,
        "curve_name": cfg.curve,
        "timestamp": as_of,
        "expiry": f"{exp_m}M",
        "tail": f"{int(tail_months)}M",
        "weight_method": cfg.weight_method,
        "strike_convention": cfg.strike_convention,
        "contracts": 1.0,
    }
    try:
        with cache_only(block=not cfg.allow_network):
            ctx = mdp.get_data(req)
    except Exception as exc:                                    # noqa: BLE001
        msg = str(exc)
        blocked = network_calls_blocked() - b0
        if "Could not resolve listed" in msg or "No quarterly SFR contracts" in msg:
            return _fail(as_of, rank, pack, "no_option", msg, blocked)
        if "curve" in msg.lower() or "timestamp" in msg.lower():
            return _fail(as_of, rank, pack, "no_curve", msg, blocked)
        return _fail(as_of, rank, pack, "other", f"{type(exc).__name__}: {msg}", blocked)

    blocked = network_calls_blocked() - b0
    legs = list(ctx.legs)
    got = [str(leg.underlying_contract) for leg in legs]
    if len(legs) != 4 and verify_contracts:
        return _fail(as_of, rank, pack, "leg_count",
                     f"got {len(legs)} legs {got}", blocked)
    if verify_contracts and got != want:
        return _fail(as_of, rank, pack, "contract_mismatch",
                     f"want {want} got {got}", blocked)
    if verify_contracts and (ctx.swap_start != start or ctx.swap_end != end):
        return _fail(as_of, rank, pack, "window_mismatch",
                     f"want {start}..{end} got {ctx.swap_start}..{ctx.swap_end}", blocked)

    try:
        flat, mean = _strip_vols(ctx)
    except Exception as exc:                                    # noqa: BLE001
        return _fail(as_of, rank, pack, "other",
                     f"{type(exc).__name__}: {exc}", network_calls_blocked() - b0)

    if not (np.isfinite(flat) and flat > 0) or not (np.isfinite(mean) and mean > 0):
        return _fail(as_of, rank, pack, "bad_vol", f"flat={flat} mean={mean}", blocked)

    return CapFloorVol(
        date=as_of, rank=rank, pack=pack, sigma_flat_bp=float(flat),
        sigma_mean_bp=float(mean), reason=_REASON_OK, n_legs=len(legs),
        contracts=tuple(got),
        caplet_vols_bp=tuple(float(leg.pricer.iv_normal_bps()) for leg in legs),
        strikes_rate=tuple(float(leg.strike_rate) for leg in legs),
        quote_sources=tuple(str(leg.quote_source) for leg in legs),
        swap_start=ctx.swap_start, swap_end=ctx.swap_end,
        blocked_calls=blocked,
    )


def spot_starting_cap_vol(
    as_of: datetime.date, rank: int, cfg: CAValuationConfig, *, mdp: Any = None,
) -> CapFloorVol:
    """The **alternative** reading: a cap from today to the pack's END.

    Provided as a separate, clearly named quantity because it is *not* the vol
    of the pack's own four contracts -- it is a spot-starting strip of
    ``rank + 3`` caplets that happens to terminate where the pack does. Citi's
    footnote does not say which of the two it means, and the two differ most in
    exactly the regime where the front of the curve is volatile. Reported, never
    substituted; the leg-identity check is switched off because the strip is
    deliberately longer than the pack.
    """
    return pack_capfloor_vol(as_of, rank, cfg, mdp=mdp, expiry_months=0,
                             tail_months=3 * (rank + 3), verify_contracts=False)


# ===========================================================================
# The vol panel
# ===========================================================================
def build_capfloor_vol_panel(
    dates: Sequence[Any],
    ranks: Sequence[int],
    cfg: CAValuationConfig,
    *,
    mdp: Any = None,
    resume_path: Optional[str] = None,
    progress: bool = True,
) -> pd.DataFrame:
    """Long panel of ``(date, rank)`` cap/floor calibrations.

    Resumable: if ``resume_path`` names an existing parquet its ``(date, rank)``
    cells are loaded and not recomputed, and the merged frame is written back
    after every date. A run interrupted halfway costs nothing to restart, which
    matters because the first touch of a contract-month is the expensive one and
    later dates in the same month ride its cached window.
    """
    mdp = mdp if mdp is not None else _capfloor_mdp(cfg)
    ranks = [int(r) for r in ranks]

    done: Dict[Tuple[pd.Timestamp, int], Dict[str, Any]] = {}
    if resume_path and os.path.exists(resume_path):
        prev = pd.read_parquet(resume_path)
        for row in prev.to_dict("records"):
            done[(pd.Timestamp(row["date"]), int(row["rank"]))] = row
        if progress:
            print(f"  resume: {len(done)} cells already on disk", flush=True)

    net_used = 0
    rows: List[Dict[str, Any]] = list(done.values())
    n = len(dates)
    for i, d in enumerate(dates):
        d = pd.Timestamp(d).date() if not isinstance(d, datetime.date) else d
        d = d.date() if isinstance(d, datetime.datetime) else d
        for r in ranks:
            key = (pd.Timestamp(d), r)
            if key in done:
                continue
            local = cfg
            if cfg.allow_network and net_used >= cfg.max_network_cells:
                local = replace(cfg, allow_network=False)
            res = pack_capfloor_vol(d, r, local, mdp=mdp)
            if local.allow_network:
                net_used += 1
            row = res.as_row()
            rows.append(row)
            done[key] = row
        if resume_path and rows:
            pd.DataFrame(rows).to_parquet(resume_path, index=False)
        if progress and cfg.progress_every and (i + 1) % cfg.progress_every == 0:
            ok = sum(1 for v in done.values() if v["reason"] == _REASON_OK)
            print(f"  vol panel {i + 1}/{n} ({d})  ok={ok}/{len(done)}", flush=True)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values(["date", "rank"]).reset_index(drop=True)


def vol_panel_coverage(vol_panel: pd.DataFrame, *, by: str = "rank") -> pd.DataFrame:
    """Cells with a real vol vs each NaN reason, cross-tabulated by year x *by*."""
    if vol_panel.empty:
        return pd.DataFrame()
    df = vol_panel.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    tab = pd.crosstab([df["year"], df[by]], df["reason"])
    tab["total"] = tab.sum(axis=1)
    if _REASON_OK in tab.columns:
        tab["pct_ok"] = (100.0 * tab[_REASON_OK] / tab["total"]).round(1)
    return tab


def sigma_wide(
    vol_panel: pd.DataFrame, cfg: CAValuationConfig, *, measure: Optional[str] = None,
) -> pd.DataFrame:
    """Long vol panel -> wide ``date x pack-label`` sigma frame, bp/yr.

    Keyed by pack **label**, not rank, so it joins onto the CA panel the same
    constant-contract way every other series in the strategy does, and so it can
    be handed straight to ``strat2_sofr_convexity.model_timeseries`` as
    ``external_sigma``.
    """
    if vol_panel.empty:
        return pd.DataFrame()
    measure = measure or cfg.vol_measure
    col = "sigma_capfloor_flat_bp" if measure == "flat" else "sigma_capfloor_mean_bp"
    ok = vol_panel[vol_panel["reason"] == _REASON_OK]
    if ok.empty:
        return pd.DataFrame()
    return ok.pivot_table(index="date", columns="pack", values=col,
                          aggfunc="last").sort_index()


# ===========================================================================
# The model leg
# ===========================================================================
def model_ca_from_sigma(
    panel: pd.DataFrame,
    sigma: pd.DataFrame,
    cfg: CAValuationConfig,
) -> pd.DataFrame:
    """Attach the cap/floor-calibrated model CA and the vol-market dislocation.

    Takes the CA panel (long: ``date``, ``rank``, ``pack``, ``ca_bp``,
    ``time_weight``) and the wide sigma frame, and returns the panel plus:

    ``sigma_capfloor_bp``       the pack's own cap/floor normal vol, bp/yr
    ``ca_model_capfloor_bp``    ``1/2 sigma^2 mean(T1^2)`` in bp
    ``vs_model_capfloor_bp``    ``observed CA - model CA``, **a vol-market
                                dislocation**, positive = market pays too much
                                for convexity = short-convexity attractive
    ``implied_vol_bp``          the Ho-Lee vol implied by the OBSERVED CA
    ``implied_minus_capfloor_bp``  implied vol - cap/floor vol, the same
                                dislocation expressed in vol rather than price

    ``time_weight`` is the panel's own stored ``M = mean(T1^2)``; a single
    pseudo-``T1`` of ``sqrt(M)`` reproduces it exactly through
    ``holee.pack_time_weight``, which is the identity the locked
    ``_sigma_for_day`` relies on too. Using the stored ``M`` rather than
    re-deriving the four IMM dates guarantees the model leg and the implied-vol
    inversion share one time weight, so their ratio is exactly
    ``(sigma_impl/sigma_model)^2`` with no as-of drift between them.

    Cells with no cap/floor vol come back NaN. There is no fallback.
    """
    out = panel.copy()
    if out.empty:
        for c in ("sigma_capfloor_bp", "ca_model_capfloor_bp", "vs_model_capfloor_bp",
                  "implied_vol_bp", "implied_minus_capfloor_bp"):
            out[c] = pd.Series(dtype=float)
        return out

    out["date"] = pd.to_datetime(out["date"])
    if sigma is None or sigma.empty:
        sig = pd.Series(np.nan, index=out.index, dtype=float)
    else:
        s = sigma.copy()
        s.index = pd.to_datetime(s.index)
        try:                                   # pandas >= 2.1 keeps the NaNs
            stacked = s.stack(future_stack=True)
        except TypeError:                      # pragma: no cover - older pandas
            stacked = s.stack(dropna=False)
        stacked.index.names = ["date", "pack"]
        lut = stacked.rename("sigma_capfloor_bp")
        sig = out.set_index(["date", "pack"]).index.map(lut)
        sig = pd.Series(np.asarray(sig, dtype=float), index=out.index)
    out["sigma_capfloor_bp"] = sig.astype(float)

    conv = cfg.holee_convention
    out["ca_model_capfloor_bp"] = [
        pack_ca_bp(s, [math.sqrt(w)], convention=conv)
        if (np.isfinite(s) and np.isfinite(w) and w > 0) else np.nan
        for s, w in zip(out["sigma_capfloor_bp"], out["time_weight"])]
    out["vs_model_capfloor_bp"] = out["ca_bp"] - out["ca_model_capfloor_bp"]
    out["implied_vol_bp"] = [
        implied_vol_from_ca_bp(c, [math.sqrt(w)], convention=conv)
        if (np.isfinite(c) and c > cfg.ca_floor_bp and np.isfinite(w) and w > 0) else np.nan
        for c, w in zip(out["ca_bp"], out["time_weight"])]
    out["implied_minus_capfloor_bp"] = out["implied_vol_bp"] - out["sigma_capfloor_bp"]
    return out


def citi_implied_model_sigma(
    published: Mapping[str, Mapping[str, float]],
    time_weights: Mapping[str, float],
    *,
    convention: str = CITI_CONVENTION,
) -> pd.DataFrame:
    """Back Citi's OWN cap/floor sigma out of their printed ``Model`` column.

    ``sigma = sqrt(2 * Model_bp / mean(T1^2))``, the same inversion Citi applies
    to the observed CA to print ``Implied Vol``. Applying it to the *model*
    column instead recovers the vol Citi's cap/floor calibration must have fed
    in -- which is the only way to compare our calibration to theirs, since they
    publish the model CA and not the sigma. This is an inversion of published
    numbers, not a fit: there are no free parameters.
    """
    rows = []
    for lab, rec in published.items():
        w = float(time_weights.get(lab, np.nan))
        rows.append({
            "pack": lab,
            "rank": int(rec.get("rank", -1)),
            "citi_ca_bp": float(rec["ca_bp"]),
            "citi_model_bp": float(rec["model_bp"]),
            "citi_implied_vol_bp": float(rec["implied_vol_bp"]),
            "citi_realized_vol_bp": float(rec["realized_vol_bp"]),
            "time_weight": w,
            "citi_model_sigma_bp": implied_vol_from_ca_bp(
                float(rec["model_bp"]), [math.sqrt(w)], convention=convention)
            if (np.isfinite(w) and w > 0) else np.nan,
        })
    return pd.DataFrame(rows).sort_values("rank").set_index("pack")


# ===========================================================================
# 3m realized vol of the pack
# ===========================================================================
def bday_reindex(wide: pd.DataFrame, *, freq: str = "B") -> pd.DataFrame:
    """Reindex a wide date-indexed frame onto a **complete** business-day grid.

    Two jobs, both necessary and both about not lying:

    * ``.diff()`` on a sparse index silently computes a 200-day change and calls
      it a daily change. On the current CA panel -- 249 dates in 2022 but 19 in
      2024 -- that would inflate the 2024 realized vol by a factor of ~5. On the
      reindexed grid the missing days are NaN, so the change across a hole is
      NaN and simply does not enter the rolling window.
    * Plotly's ``connectgaps=False`` needs the gap to *exist* in the series. A
      sparse series has no gap to skip: it draws a straight line from the last
      point to the next one, 200 days later, and the chart bridges the hole. The
      whole defect this module was asked to fix.
    """
    if wide is None or wide.empty:
        return wide
    idx = pd.to_datetime(wide.index)
    grid = pd.bdate_range(idx.min(), idx.max(), freq=freq)
    return wide.reindex(grid).sort_index()


def pack_realized_vol(
    panel: pd.DataFrame,
    cfg: CAValuationConfig,
    *,
    rate_col: str = "pack_rate",
) -> pd.DataFrame:
    """*"Realized vol is 3m realized vol of the corresponding pack."*

    The pack rate is the arithmetic mean of its four contract rates, in
    **percent**; it is keyed by pack LABEL, so its four contracts never change
    and the series carries no IMM-roll jump. The calculation, every step of it
    stated because every step is a convention:

    1. pivot to wide ``date x pack`` and **reindex onto the business-day grid**
       (:func:`bday_reindex`) -- so a missing date is a NaN and not a silently
       compressed axis;
    2. ``diff() * 100`` -> **daily close-to-close change in bp**. Across a gap
       this is NaN by construction, never a multi-day change relabelled daily;
    3. ``rolling(63, min_periods=42).std(ddof=1)`` -> the sample standard
       deviation of those daily bp changes over a **63-business-day** window
       (= 252/4, one quarter), emitted only where at least **42** of the 63
       possible daily changes actually exist;
    4. ``* sqrt(252)`` -> annualised, giving a **normal vol in bp/yr**, the same
       units as the cap/floor vol and the Ho-Lee implied vol. 252 is the
       business-day count implied by using a business-day window in step 3;
       mixing a 63-*business*-day window with a 365 annualisation would
       overstate the vol by 24%.

    No demeaning beyond what ``std`` does and no EWMA: Citi says "3m realized
    vol" and the simplest reading of that is a 3m sample standard deviation.
    """
    if panel is None or panel.empty:
        return pd.DataFrame()
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])
    wide = p.pivot_table(index="date", columns="pack", values=rate_col,
                         aggfunc="last").sort_index()
    grid = bday_reindex(wide)
    d_bp = grid.diff() * 100.0
    rv = (d_bp.rolling(cfg.realized_window_days, min_periods=cfg.realized_min_obs)
          .std(ddof=1) * math.sqrt(cfg.realized_annualisation))
    return rv


def realized_vol_coverage(rv: pd.DataFrame, *, by_year: bool = True) -> pd.DataFrame:
    """How much of the realized-vol grid is actually computable, by year.

    ``computable`` counts cells with a finite number; ``grid`` counts cells on
    the business-day grid the pack label is alive for (first to last date the
    label appears anywhere in the frame's columns). The ratio is the honest
    answer to "how much of 2024-2026 can we compute", and it is a data-coverage
    statement, not a modelling one.
    """
    if rv is None or rv.empty:
        return pd.DataFrame()
    rows = []
    idx = pd.to_datetime(rv.index)
    for y, sub in rv.groupby(idx.year):
        finite = int(np.isfinite(sub.to_numpy(dtype=float)).sum())
        cells = int(sub.size)
        rows.append({"year": int(y), "bdays": int(len(sub)),
                     "labels": int(sub.shape[1]), "grid_cells": cells,
                     "computable": finite,
                     "pct": round(100.0 * finite / cells, 1) if cells else np.nan})
    out = pd.DataFrame(rows).set_index("year")
    return out if by_year else out.sum().to_frame().T


# ===========================================================================
# The screen
# ===========================================================================
def valuation_screen(
    as_of: Any,
    valued: pd.DataFrame,
    rv: pd.DataFrame,
    cfg: CAValuationConfig,
    *,
    ranks: Optional[Sequence[int]] = None,
) -> pd.DataFrame:
    """Citi's valuation table for one date: three metrics per pack.

    ``valued`` is the output of :func:`model_ca_from_sigma`; ``rv`` the wide
    frame from :func:`pack_realized_vol`. Columns, grouped as Citi groups them::

        observed CA  | model CA (cap/floor)  | vs model
        implied vol  | realized vol          | implied - realized | impl/rlzd
        cap/floor vol| capvol/realized

    Every cell that depends on a missing cap/floor vol or an under-populated
    realized-vol window is NaN and votes in no ranking.
    """
    d = pd.Timestamp(as_of)
    day = valued[pd.to_datetime(valued["date"]) == d]
    if ranks is not None:
        day = day[day["rank"].isin(list(ranks))]
    # The emptiness check has to come AFTER the rank filter, not before it. The
    # vol panel is built from pack geometry and the CA panel from what settled,
    # so a date can carry a cap/floor vol for rank 5 and no rank-5 row at all --
    # which is exactly what a partially repaired panel looks like. Checking
    # first left an empty frame to `set_index("pack")` and raised
    # ``KeyError: None of ['pack'] are in the columns`` mid-notebook.
    if day.empty:
        return pd.DataFrame(columns=["rank", "pack", "colour", "ca_bp"])
    day = day.sort_values("rank")

    def _rv(pack: str) -> float:
        if rv is None or rv.empty or d not in rv.index or pack not in rv.columns:
            return float("nan")
        return float(rv.at[d, pack])

    rows = []
    for _, r in day.iterrows():
        pack = str(r["pack"])
        iv = float(r.get("implied_vol_bp", np.nan))
        realized = _rv(pack)
        sig = float(r.get("sigma_capfloor_bp", np.nan))
        ir = iv / realized if (np.isfinite(iv) and np.isfinite(realized) and realized > 0) else np.nan
        cr = sig / realized if (np.isfinite(sig) and np.isfinite(realized) and realized > 0) else np.nan
        rows.append({
            "rank": int(r["rank"]),
            "pack": pack,
            "colour": PACK_COLOURS.get(int(r["rank"])),
            "ca_bp": float(r["ca_bp"]),
            "ca_model_capfloor_bp": float(r.get("ca_model_capfloor_bp", np.nan)),
            "vs_model_capfloor_bp": float(r.get("vs_model_capfloor_bp", np.nan)),
            "implied_vol_bp": iv,
            "realized_vol_bp": realized,
            "implied_minus_realized_bp": iv - realized
            if (np.isfinite(iv) and np.isfinite(realized)) else np.nan,
            "implied_over_realized": ir,
            "sigma_capfloor_bp": sig,
            "implied_minus_capfloor_bp": float(r.get("implied_minus_capfloor_bp", np.nan)),
            "capvol_over_realized": cr,
        })
    return pd.DataFrame(rows).set_index("pack", drop=False)


def short_convexity_flags(screen: pd.DataFrame, cfg: CAValuationConfig) -> pd.DataFrame:
    """*"we mark three best short convexity trades in bold."*

    Short convexity is attractive where the market **pays too much** for
    convexity: the observed CA rich to the cap/floor-calibrated model, and the
    CA-implied vol rich to what the pack has actually delivered. Both metrics
    are therefore signed so that HIGHER is a better short, and the rule is one
    ``nlargest(3)`` per metric over the finite values only. A metric with no
    finite value casts no vote rather than voting for whatever is at the top of
    the index.
    """
    metrics = [m for m in cfg.rank_metrics if m in screen.columns]
    flags = pd.DataFrame(False, index=screen.index, columns=metrics)
    for m in metrics:
        s = screen[m].dropna()
        if s.empty:
            continue
        for p in s.nlargest(min(cfg.top_n_per_metric, len(s))).index:
            flags.at[p, m] = True
    flags["n_flags"] = flags[metrics].sum(axis=1) if metrics else 0
    return flags


def top_short_convexity(screen: pd.DataFrame, cfg: CAValuationConfig) -> pd.DataFrame:
    """The flagged table Citi prints, ordered by how many metrics agree.

    Carries Citi's own caveat, which is part of the deliverable and not a
    disclaimer bolted on: these are *"the most attractive on the chart"*, not
    recommendations. Nothing here accounts for carry, financing, the CA's own
    measurement error (1.7-2.7bp at ranks 1-8 per ``strat2_ca_diagnostics``), or
    whether the pack is tradeable in size.
    """
    if screen.empty:
        return pd.DataFrame()
    flags = short_convexity_flags(screen, cfg)
    out = screen.join(flags[[c for c in flags.columns if c not in screen.columns]])
    metrics = [m for m in cfg.rank_metrics if m in screen.columns]
    pct = pd.DataFrame({m: screen[m].rank(pct=True) for m in metrics}, index=screen.index)
    out["mean_pct"] = pct.mean(axis=1)
    return out.sort_values(["n_flags", "mean_pct"], ascending=False)


# ===========================================================================
# Strike-convention sensitivity
# ===========================================================================
def strike_convention_sensitivity(
    dates: Sequence[Any],
    ranks: Sequence[int],
    panel: pd.DataFrame,
    cfg: CAValuationConfig,
    *,
    curve_source: Optional[str] = None,
    mdp_atm: Any = None,
    mdp_flat: Any = None,
) -> pd.DataFrame:
    """Model CA under ``atm_per_caplet`` vs ``flat_swap_rate``, side by side.

    Caps and floors are struck and Ho-Lee's sigma is not, so the strike is a
    genuine degree of freedom in "calibrated to cap/floor vols" and the reader
    is entitled to see what it is worth. ``flat_swap_rate`` strikes every caplet
    at the pack's own matched forward swap rate and snaps to the listed ladder;
    where the snapped strike has no listed quote the MDP falls back to a SABR
    smile, which is the per-strike crawl the cache guard exists for -- so this
    is deliberately a small-sample diagnostic and the ``quote_source`` of every
    leg is reported alongside the number.

    ``curve_source`` overrides ``cfg.curve_source`` for **both** legs, and it
    has to exist. ``flat_swap_rate`` is the only convention that calls
    ``STIRCapFloorMDP._contract_forward_price``, which reaches
    ``_discount(curve, ql_date)``; on a **rateslib**-backed curve (which
    ``CITIVELO_EXCEL`` is) that indexes the curve with a QuantLib ``Date`` and
    dies with ``TypeError: '<' not supported between instances of 'Date' and
    'datetime.datetime'``. So the sensitivity is measured on a QuantLib-backed
    curve instead. That substitution is safe **and it is checked, not assumed**:
    the ``atm_per_caplet`` sigma is identical under both curve sources
    (128.288bp on the 2023-06-09 Blues pack either way), because the ATM path
    takes its strike from the listed option rather than from the curve. See the
    notebook's follow-up section.

    Returns one row per (date, rank) with both sigmas, both model CAs and their
    difference in bp.
    """
    base = cfg if curve_source is None else replace(cfg, curve_source=curve_source)
    cfg_atm = replace(base, strike_convention="atm_per_caplet")
    cfg_flat = replace(base, strike_convention="flat_swap_rate")
    mdp_atm = mdp_atm if mdp_atm is not None else _capfloor_mdp(cfg_atm)
    mdp_flat = mdp_flat if mdp_flat is not None else _capfloor_mdp(cfg_flat)

    weights: Dict[Tuple[pd.Timestamp, int], float] = {}
    if panel is not None and not panel.empty:
        p = panel.copy()
        p["date"] = pd.to_datetime(p["date"])
        for row in p[["date", "rank", "time_weight"]].to_dict("records"):
            weights[(row["date"], int(row["rank"]))] = float(row["time_weight"])

    rows = []
    for d in dates:
        d = pd.Timestamp(d).date()
        for r in ranks:
            a = pack_capfloor_vol(d, int(r), cfg_atm, mdp=mdp_atm)
            f = pack_capfloor_vol(d, int(r), cfg_flat, mdp=mdp_flat)
            w = weights.get((pd.Timestamp(d), int(r)), np.nan)
            conv = cfg.holee_convention

            def _ca(sig: float) -> float:
                if not (np.isfinite(sig) and np.isfinite(w) and w > 0):
                    return np.nan
                return pack_ca_bp(sig, [math.sqrt(w)], convention=conv)

            rows.append({
                "date": pd.Timestamp(d), "rank": int(r), "pack": a.pack,
                "sigma_atm_bp": a.sigma_flat_bp, "sigma_flatswap_bp": f.sigma_flat_bp,
                "reason_atm": a.reason, "reason_flatswap": f.reason,
                "quote_sources_flatswap": "|".join(sorted(set(f.quote_sources))),
                "time_weight": w,
                "ca_model_atm_bp": _ca(a.sigma_flat_bp),
                "ca_model_flatswap_bp": _ca(f.sigma_flat_bp),
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["d_sigma_bp"] = out["sigma_flatswap_bp"] - out["sigma_atm_bp"]
    out["d_ca_model_bp"] = out["ca_model_flatswap_bp"] - out["ca_model_atm_bp"]
    return out
