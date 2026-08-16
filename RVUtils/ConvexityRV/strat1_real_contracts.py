"""Strategy 1 on REAL LISTED CONTRACTS -- ``USM26``, not ``US_30``.

``strat1_listed.build_longend_listed_panel`` benchmarks the long-end flatteners
against QuikStrike's **constant-maturity** UST vol (``US_30``, ``TY_90``). That
series is an interpolation ACROSS the expiry ladder. It is not a tradeable
instrument, it has no strike dimension and it has no expiry, so it cannot
support two of the three things JPM's note actually does:

* **size a funding straddle** so its premium intake equals the flattener's
  carry -- that needs a contract with a real expiry and a real premium;
* **carry an expected-payoff signal** -- that needs OTM quotes.

``scripts/harvest_listed_contract_vol.py`` removed the limitation by harvesting
the contracts themselves (196,560 rows, 228 contracts, 2019-01-02..2026-08-14),
and ``listed_contracts`` loads them. This module is the strategy-1 half: it
selects a contract per date, benchmarks the curve against it, and reports what
changes relative to the constant-maturity control.

**The constant-maturity panel is kept as an explicit CONTROL, not deleted.**
Every table here is produced twice -- once against the real contract, once
against ``US_30``/``TY_30`` on the identical curve rows -- because the
difference between them is itself the finding. It measures what constant-
maturity interpolation was doing to the answer, which is the direct answer to
"why bother with real contracts". :func:`cm_vs_real_table` is that comparison.


Written as a separate module, and why
--------------------------------------
``strat1_listed`` and ``strat1_threeway`` are untouched by this file; both
re-export its public names lazily (a module-level ``__getattr__``, because
``strat1_threeway`` already imports ``strat1_listed`` and an eager re-export
would close an import cycle). Every existing caller of either module keeps
working unchanged, and the constant-maturity path keeps running, because it is
the control.


What a real contract can and cannot reach on the long end
----------------------------------------------------------
The single most important measured fact about this panel, stated before any
result that depends on it:

=====================  =======  =======  ================================
quantity               US       TY       what it means
=====================  =======  =======  ================================
dates covered            1,917    1,917  every curve date -- no truncation
contracts alive/date     4 (max 6) 5 (max 6)
time to expiry, median      66 d     71 d
time to expiry, **max**    241 d    241 d  **0.66 years**
=====================  =======  =======  ================================

The curve breakeven is a **one-year**-horizon number. The longest-dated listed
UST option in the whole sample expires in **241 days**, so even the best
possible expiry match is **124 days short** of the horizon and the median match
is 232 days short. That is a large improvement on constant maturity -- ``US_30``
is 335 days short by construction, every day -- and it is still not a match.
:func:`contract_selection_report` reports the achieved distribution rather than
asserting the improvement, and the honest one-line version is: *real contracts
halve the horizon mismatch; they do not remove it.*

A consequence worth naming because it is not obvious: at a 365-day target the
"nearest expiry" rule always resolves to the **back** contract on the ladder,
since 365 days is beyond every listed expiry. The selection is well defined and
it is what the brief asks for, but it is degenerate in that specific sense, and
:func:`contract_selection_report` carries ``frac_selected_is_longest`` so the
degeneracy is visible instead of implied.


Sector matching is IMPERFECT here, and by how much is measured
---------------------------------------------------------------
``listed_vol.UST_SECTOR_MAP`` assigns the sector-matched primary benchmark by
measured CTD maturity. For two of the four long-end structures (30Y/50Y and
20Yx5Y/25Yx5Y) that primary is **UL (Ultra Bond, CTD 25.6 years)**, and for
10Yx10Y/20Yx10Y the alt is **TN**. Neither is reachable as a real listed
contract:

    ``ULM26`` / ``TNM26`` -> "Invalid UST option contract token"

They exist only as constant maturity. So the real-contract study runs on **US
(the best available real long-end root) and TY (the deliberately wrong-sector
control)**, and on two of the four structures the best available real benchmark
is the sector map's *alt*, not its primary.

That is a real limitation and it is quantified rather than apologised for:
measured over the 1,662 common dates, the constant-maturity ``UL_30`` prices
**-0.345 bp/day** LESS vol than ``US_30`` (mean -0.414, p05 -1.217, p95
+0.271). Substituting US for the unavailable UL therefore RAISES the listed
benchmark by about a third of a bp/day, which makes the curve look *cheaper*,
not richer -- i.e. the missing contract biases the headline in the direction of
the conclusion already reached, and the size of that bias is a third of a
bp/day. :func:`unavailable_root_penalty` recomputes it from the data;
:data:`UNAVAILABLE_REAL_ROOTS` records why the token fails.


Units -- inherited, not re-derived
-----------------------------------
``ABPV`` is annualised normal (Bachelier) **bp/yr yield vol**, the same unit as
the constant-maturity panel and as a swaption normal vol; the harvest verified
it three independent ways (vs the CM control at matched TTE, ratio 0.999-1.000;
vs the swaption cube, the same 4-15% listed-over-OTC basis the CM panel showed;
and cross-vendor against ``sfr_rv_lab``'s own Bachelier inversion, ratio median
0.9998). So ``ABPV / sqrt(252)`` is bp/day and is directly comparable to the
curve breakeven, exactly as in the CM mode.

``ATM`` is NOT bp/yr and is never used as a vol here -- for UST it is a
lognormal PRICE vol whose ratio to ABPV is the CTD's ``1e4/ModDur``. It is used
only through ``listed_contracts.smile_in_bp_yr``, which uses the panel's own
per-row ``ABPV/ATM`` scale to put the 25-delta quotes into bp/yr without any
external DV01. ``25D_BF`` is never read: the harvest measured it against an
at-the-money anchor this panel does not carry, so the fly is rebuilt from
``25D_CALL``/``25D_PUT``/``ABPV`` instead (:func:`real_smile_frame`).
"""

from __future__ import annotations

import dataclasses
import datetime
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import listed_contracts as lc
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_threeway as tw
from RVUtils.ConvexityRV.payoff import expected_payoff
from RVUtils.ConvexityRV.strat1_curve_gamma import (
    atmf_straddle_premium_bp,
    straddle_dv01_for_carry,
)
from RVUtils.ConvexityRV.strat1_listed import (
    LONG_END_STRUCTURES,
    Strat1ListedConfig,
    _as_curve_panel,
    _be_result,
    _med,
    signal_from_breakeven,
)

__all__ = [
    # --- constants / provenance
    "REAL_ROOTS",
    "REAL_ROOT_ROLE",
    "UNAVAILABLE_REAL_ROOTS",
    "TARGETS",
    "HEADLINE_TARGET",
    "HEADLINE_ROOT",
    "CONTRACT_SIZE_USD_PER_POINT",
    "real_sector_note",
    "unavailable_root_penalty",
    # --- the panel
    "RealContractConfig",
    "real_contract_atm_series",
    "build_longend_contract_panel",
    # --- what a real contract buys (the three exploitations)
    "contract_selection_report",
    "contract_roll_report",
    "funded_straddle_frame",
    "funded_straddle_summary",
    "real_smile_frame",
    "smile_strike_offsets",
    "three_point_smile",
    "real_shift_density",
    "real_expected_payoff_frame",
    # --- CM control vs real
    "cm_vs_real_table",
    "ageing_table",
    # --- three-way
    "real_threeway_config",
    "real_threeway_frames",
    "cm_vs_real_gate_table",
    "real_contract_verdict",
]


# =============================================================================
#  Provenance constants
# =============================================================================

#: The UST roots that EXIST as real listed option contracts in this panel.
#: Measured, not chosen: ``USM26`` and ``TYM26`` return data from
#: ``qs_timeseries``; ``ULM26`` and ``TNM26`` raise "Invalid UST option contract
#: token". See :data:`UNAVAILABLE_REAL_ROOTS`.
REAL_ROOTS: Tuple[str, ...] = ("US", "TY")

#: Role each real root plays in the comparison. ``US`` (CTD ~15.9 years) is the
#: longest-dated Treasury yield reachable as a real contract and is therefore the
#: best available long-end benchmark; ``TY`` (CTD ~6.8 years) is the deliberately
#: WRONG-sector control, carried on every structure so a comparison that fails to
#: discriminate by sector is visible rather than assumed away.
#:
#: The role names match ``strat1_threeway.LONGEND_ROLES`` so
#: ``select_longend_benchmark(role=...)`` accepts this panel unchanged. The
#: honesty lives in ``listed_sector_primary`` / ``listed_sector_matched``, two
#: columns every row carries: on 30Y/50Y and 20Yx5Y/25Yx5Y the sector map's own
#: primary is UL, so ``US`` is stamped ``primary`` here while
#: ``listed_sector_matched`` is False.
REAL_ROOT_ROLE: Dict[str, str] = {"US": "primary", "TY": "control"}

#: Roots the sector map wants but that are NOT reachable as listed contracts,
#: with the measured failure. Recorded here rather than in a comment because the
#: verdict quotes it: a reader has to be able to see that the long-end sector
#: match is imperfect for a data reason, not a modelling choice.
UNAVAILABLE_REAL_ROOTS: Dict[str, Dict[str, Any]] = {
    "UL": {
        "name": "Ultra Bond",
        "ctd_ttm_yrs": 25.59,
        "sector_primary_for": ("30Y/50Y", "20Yx5Y/25Yx5Y"),
        "failure": "qs_timeseries('ULM26', 'ABPV') -> Invalid UST option contract token",
        "available_as": "constant maturity only (UL_30 / UL_60 / UL_90)",
    },
    "TN": {
        "name": "Ultra 10-Year",
        "ctd_ttm_yrs": 9.61,
        "sector_primary_for": (),
        "sector_alt_for": ("10Yx10Y/20Yx10Y",),
        "failure": "qs_timeseries('TNM26', 'ABPV') -> Invalid UST option contract token",
        "available_as": "constant maturity only (TN_30 / TN_60 / TN_90)",
    },
}

#: ``(label, target_tte_days, max_gap_days)`` -- the expiry-selection rules.
#:
#: ``H365`` is the HEADLINE and is what the brief asks for: pick the contract
#: whose time to expiry is closest to the curve's own one-year horizon. Its
#: ``max_gap_days`` is deliberately unbounded, because the honest answer is that
#: nothing on this ladder gets within 124 days and a finite cap would silently
#: return no rows at all rather than reporting that. (``select_by_tte``'s own
#: default of 20 days returns ``None`` on every single date at this target --
#: which is a correct refusal, and useless as a study.)
#:
#: ``D30`` / ``D60`` / ``D90`` exist for ONE reason: they match the constant
#: maturities the CM control is quoted at, so :func:`cm_vs_real_table` compares
#: like with like. Their caps are tight because at those targets the ladder is
#: dense and a wide cap would quietly substitute a far contract.
TARGETS: Tuple[Tuple[str, float, float], ...] = (
    ("H365", 365.0, float("inf")),
    ("D30", 30.0, 20.0),
    ("D60", 60.0, 25.0),
    ("D90", 90.0, 30.0),
)

#: Pre-specified headline: the horizon-matched contract on US. Fixed here, in the
#: module, rather than chosen in a notebook after seeing four answers.
HEADLINE_TARGET: str = "H365"
HEADLINE_ROOT: str = "US"

#: USD per full price point, per contract. Both ZB (US) and ZN (TY) are $100,000
#: face quoted in points of par, so one point is $1,000. Used only to turn a
#: straddle DV01 into a CONTRACT COUNT -- the thing a constant-maturity series
#: can never produce. Ties out against the market: ``fv01_points_per_bp`` medians
#: of 0.1388 (US) and 0.0657 (TY) give $138.8 and $65.7 of DV01 per contract.
CONTRACT_SIZE_USD_PER_POINT: float = 1000.0

#: ``|K - F|`` for a 25-delta option in a normal (Bachelier) model, in units of
#: ``sigma * sqrt(T)``. A Bachelier delta is ``Phi((F - K) / (sigma sqrt T))``,
#: so delta 0.25 puts the strike at ``Phi^-1(0.75) = 0.674490`` standard
#: deviations away from the forward. Written out because it is the one place the
#: smile geometry is asserted rather than quoted by the vendor.
DELTA25_SIGMAS: float = 0.6744897501960817


def real_sector_note(structure: str) -> Dict[str, Any]:
    """What the sector map wanted, and what a real contract can actually deliver.

    Returns the map's own ``primary`` / ``alt`` / ``control`` for the structure
    alongside ``best_available_real`` and ``sector_matched`` -- the latter False
    exactly when the sector primary has no listed contract. Every row of
    :func:`build_longend_contract_panel` carries these, so a reader of the panel
    cannot see the benchmark without also seeing whether it was the right one.
    """
    b = lv.ust_benchmarks_for(structure)
    primary = str(b["primary"])
    matched = primary in REAL_ROOTS
    return {
        "structure": str(structure),
        "sector_primary": primary,
        "sector_alt": str(b["alt"]),
        "sector_control": str(b["control"]),
        "sector_matched": bool(matched),
        "best_available_real": HEADLINE_ROOT,
        "why": str(b["why"]),
        "limitation": ("" if matched else
                       f"sector primary {primary} ({UNAVAILABLE_REAL_ROOTS.get(primary, {}).get('name', '?')}) "
                       f"is not reachable as a listed contract "
                       f"({UNAVAILABLE_REAL_ROOTS.get(primary, {}).get('failure', 'unavailable')}); "
                       f"the best available real benchmark is {HEADLINE_ROOT}, which is the "
                       f"sector map's ALT for this structure"),
    }


def unavailable_root_penalty(cm_panel: pd.DataFrame, *, root: str = "UL",
                             against: str = HEADLINE_ROOT, cm_days: int = 30,
                             business_days_per_year: float = 252.0) -> Dict[str, Any]:
    """How much the missing real root would have moved the benchmark, in bp/day.

    Both roots exist in the CONSTANT-MATURITY panel, so the substitution's size
    is measurable even though one of them has no listed contract. Positive means
    the unavailable root prices MORE vol than the substitute, i.e. using the
    substitute makes the curve look richer; negative means the substitute makes
    the curve look cheaper and the missing contract therefore biases the headline
    towards the conclusion.

    This is the number the verdict has to quote for 30Y/50Y and
    20Yx5Y/25Yx5Y. Computed from the control panel, never asserted.
    """
    a = lv.ust_cm_series(cm_panel, root, cm_days)
    b = lv.ust_cm_series(cm_panel, against, cm_days)
    idx = a.index.intersection(b.index)
    if len(idx) < 5:
        return {"root": root, "against": against, "n": int(len(idx)),
                "note": "insufficient overlap"}
    d = (a.loc[idx] - b.loc[idx]) / math.sqrt(business_days_per_year)
    return {
        "root": root, "against": against, "cm_days": int(cm_days), "n": int(len(idx)),
        "first": str(idx.min().date()), "last": str(idx.max().date()),
        "median_bp_day": float(d.median()),
        "mean_bp_day": float(d.mean()),
        "p05_bp_day": float(d.quantile(0.05)),
        "p95_bp_day": float(d.quantile(0.95)),
        "frac_positive": float((d > 0).mean()),
        "direction": ("substitute makes the curve look CHEAPER (missing root priced LESS vol)"
                      if d.median() < 0 else
                      "substitute makes the curve look RICHER (missing root priced MORE vol)"),
    }


# =============================================================================
#  Config
# =============================================================================


@dataclass(frozen=True)
class RealContractConfig:
    """Every knob of the real-contract study. Nothing here is tuned on the P&L.

    Deliberately a thin object beside :class:`Strat1ListedConfig` rather than a
    subclass of it: the curve side is not re-derived here at all (it is read
    from strategy 1's own stored panel, exactly as the constant-maturity mode
    does), so the only knobs that belong here are the ones that pick a contract
    and price a straddle against it.
    """

    #: Structures. Strategy 1's own long-end four, imported so a change to the
    #: universe cannot leave the two modules disagreeing about what "30Y/50Y" is.
    structures: Tuple[Tuple[str, str, str], ...] = LONG_END_STRUCTURES
    #: Real roots to build. Both by default: dropping the TY control is exactly
    #: how a sector comparison stops being checkable.
    roots: Tuple[str, ...] = REAL_ROOTS
    #: Expiry-selection rules; see :data:`TARGETS`.
    targets: Tuple[Tuple[str, float, float], ...] = TARGETS
    #: Contracts closer to expiry than this are dropped -- a normal vol backed out
    #: of a nearly-intrinsic premium is numerically unstable. 0.02 years is ~5
    #: business days and is the same guard the SFR mode applies.
    min_tte_years: float = 0.02
    #: Contract kinds to select from. Both by default. The serial (monthly)
    #: contracts are 64 of the 97 per root and they are what makes the near end of
    #: the ladder dense; restricting to quarterlies is a diagnostic, not a default.
    kinds: Optional[Tuple[str, ...]] = None
    #: Business days per year for the annual-vol <-> daily-vol bridge, applied
    #: identically to curve, swaption and listed. This is what makes bp/day the
    #: common unit and it must equal the CM mode's or the two are incomparable.
    business_days_per_year: float = 252.0
    #: The curve horizon, in years. Also the cohort holding period AND the target
    #: the ``H365`` rule matches the expiry to.
    horizon_years: float = 1.0
    #: The swaption node the stored strategy-1 panel was built against.
    otc_expiry: str = "1Y"
    otc_tenor: str = "30Y"
    #: Entry rule. 0.0 is the note's own (any divergence trades).
    entry_threshold_bp_per_day: float = 0.0
    #: The note trades both sides: "when it is negative, we do the opposite."
    trade_when_rich: bool = True
    #: Package risk the stored curve panel is quoted against.
    package_dv01: float = 100_000.0
    #: Window. The real-contract panel and the swap curve both run
    #: 2019-01-02..2026-08-14, so nothing is truncated -- unlike the SFR mode,
    #: where the listed panel was the binding constraint.
    start: datetime.date = datetime.date(2019, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 14)

    def labels(self) -> Tuple[str, ...]:
        return tuple(s[0] for s in self.structures)

    def target_days(self, label: str) -> float:
        for name, days, _gap in self.targets:
            if name == label:
                return float(days)
        raise KeyError(f"unknown target {label!r}; known {[t[0] for t in self.targets]}")

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def listed_config(self) -> Strat1ListedConfig:
        """The equivalent :class:`Strat1ListedConfig`, so the CM control run uses
        the identical curve window, threshold, horizon and day-count."""
        return Strat1ListedConfig(
            longend_structures=self.structures,
            business_days_per_year=self.business_days_per_year,
            horizon_years=self.horizon_years,
            longend_otc_expiry=self.otc_expiry,
            longend_otc_tenor=self.otc_tenor,
            entry_threshold_bp_per_day=self.entry_threshold_bp_per_day,
            trade_when_rich=self.trade_when_rich,
            package_dv01=self.package_dv01,
            longend_start=self.start,
            longend_end=self.end,
        )


# =============================================================================
#  The benchmark series
# =============================================================================


def real_contract_atm_series(
    contract_panel: pd.DataFrame,
    root: str,
    target_label: str = HEADLINE_TARGET,
    *,
    cfg: Optional[RealContractConfig] = None,
    dates: Optional[Sequence[Any]] = None,
) -> pd.DataFrame:
    """The REAL-CONTRACT benchmark in the shape ``ust_listed_atm_series`` returns.

    This is the adapter that lets every existing long-end function consume real
    contracts with no change: same index (``date``), same column names
    (``listed_symbol``, ``listed_root``, ``listed_cm_days``, ``listed_expiry``,
    ``listed_tte``, ``listed_gap_days``, ``listed_atm_bp_yr``,
    ``listed_atm_bp_day``, ``listed_swap_point``). Four columns are ADDED and
    three change meaning; both differences are load-bearing.

    Added:

    ``listed_contract_code``
        the deliverable -- ``USM26``. This is the column that makes the panel
        tradeable and it is the one a constant-maturity series cannot have.
    ``listed_contract_kind``
        ``quarterly`` or ``serial``.
    ``listed_sector_primary`` / ``listed_sector_matched``
        what ``UST_SECTOR_MAP`` wanted for this root's structures and whether
        this root is it. False on the two structures whose primary is UL.

    Changed in MEANING:

    ``listed_symbol``
        ``"US@H365"`` -- the BENCHMARK's identity, not the contract's. It has to
        be stable across dates because ``longend_basis_frame`` and
        ``basis_persistence`` group by it to build a time series; keying them on
        the contract code would shatter one 1,917-day basis series into 47
        forty-day fragments and report a "half-life" of the roll schedule.
    ``listed_expiry`` / ``listed_tte``
        a REAL deliverable expiry and the real time to it, not ``cm_days/365``.
    ``listed_gap_days``
        the SIGNED distance from that real expiry to the curve horizon. For the
        CM series this is a constant by construction (-335 days at 30-day CM).
        Here it moves every day and is the thing :func:`contract_selection_report`
        exists to describe.

    ``listed_cm_days`` is set to the TARGET in days (365 / 30 / 60 / 90), not to
    the achieved time to expiry, so ``select_longend_benchmark(cm_days=...)``
    keeps working and so two roots at the same target are comparable. The
    achieved value is ``listed_tte * 365``.
    """
    cfg = cfg or RealContractConfig()
    r = lv.UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
    target_days = cfg.target_days(target_label)
    max_gap = next(g for n, _d, g in cfg.targets if n == target_label)

    sub = contract_panel[(contract_panel["root"] == r)
                         & (contract_panel["value_type"] == "ABPV")]
    if sub.empty:
        raise ValueError(f"no ABPV rows for root {r!r} in the real-contract panel")

    ms = lc.tte_matched_series(
        sub, target_days, root=r, value_type="ABPV",
        max_gap_days=float(max_gap), min_tte_years=float(cfg.min_tte_years),
        kinds=list(cfg.kinds) if cfg.kinds else None,
        dates=dates,
    )
    if ms.empty:
        raise ValueError(
            f"no contract for {r!r} at target {target_label} ({target_days:g} days, "
            f"max_gap={max_gap}). The longest listed UST option expiry in this panel is "
            "241 days, so a finite cap at a 365-day target matches nothing.")

    out = pd.DataFrame(index=ms.index)
    out.index.name = "date"
    out["listed_symbol"] = f"{r}@{target_label}"
    out["listed_root"] = r
    out["listed_cm_days"] = int(round(target_days))
    out["listed_target"] = target_label
    out["listed_contract_code"] = ms["contract_code"].to_numpy()
    out["listed_contract_kind"] = ms["contract_kind"].to_numpy()
    out["listed_expiry"] = ms["expiry_date"].to_numpy()
    out["listed_tte"] = ms["tte_years"].to_numpy(dtype=float)
    #: SIGNED distance from the real expiry to the curve horizon, in days.
    #: Negative = the option expires BEFORE the horizon, which on this ladder is
    #: every single date.
    out["listed_gap_days"] = (ms["tte_years"].to_numpy(dtype=float) * 365.0
                              - 365.0 * float(cfg.horizon_years))
    out["listed_gap_to_target_days"] = ms["gap_days"].to_numpy(dtype=float)
    out["listed_atm_bp_yr"] = ms["value"].to_numpy(dtype=float)
    out["listed_atm_bp_day"] = (ms["value"].to_numpy(dtype=float)
                                / math.sqrt(cfg.business_days_per_year))
    out["listed_swap_point"] = lv.UST_CTD_PROFILE.get(r, {}).get("swap_point")
    return out.sort_index()


def build_longend_contract_panel(
    strat1_panel: pd.DataFrame,
    contract_panel: pd.DataFrame,
    cfg: Optional[RealContractConfig] = None,
    *,
    structures: Optional[Sequence[str]] = None,
    roots: Optional[Sequence[str]] = None,
    targets: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """The (date x structure x benchmark) panel on REAL CONTRACTS.

    Deliberately the same shape, the same column names and the same three
    comparisons as ``strat1_listed.build_longend_listed_panel``::

        cheapness_vs_listed_bp_day  = listed  - breakeven
        cheapness_vs_otc_bp_day     = 1Yx30Y  - breakeven
        otc_minus_listed_bp_day     = 1Yx30Y  - listed

    so the real-contract panel and the constant-maturity control are consumed by
    the identical downstream functions and any difference between the two runs is
    the benchmark and nothing else.

    ``strat1_panel``
        strategy 1's OWN stored signal panel. The curve side is **reused, not
        recomputed** -- the same choice the CM mode makes, and for the same
        reason: the two studies' breakeven must be the same number, and the whole
        point of this exercise is a controlled substitution of the right-hand
        side of one comparison.
    ``contract_panel``
        ``listed_contracts.load_listed_contract_panel()`` output.

    One row per (date, structure, benchmark) where a benchmark is a
    (real root, expiry-selection target) pair. With the defaults that is 2 roots
    x 4 targets = 8 benchmarks per structure, of which ``US@H365`` is the
    pre-specified headline.
    """
    cfg = cfg or RealContractConfig()
    cur = _as_curve_panel(strat1_panel)
    cur = cur[(cur["date"] >= pd.Timestamp(cfg.start)) & (cur["date"] <= pd.Timestamp(cfg.end))]
    labels = ([str(s) for s in structures] if structures is not None else list(cfg.labels()))
    cur = cur[cur["structure"].isin(labels)]
    if cur.empty:
        raise ValueError(f"no stored strat1 rows for structures={labels} in "
                         f"{cfg.start}..{cfg.end}")

    use_roots = [str(r) for r in (roots if roots is not None else cfg.roots)]
    use_targets = [str(t) for t in (targets if targets is not None
                                    else [t[0] for t in cfg.targets])]

    # Build each (root, target) series ONCE -- it does not depend on the
    # structure -- and join it to every structure's curve rows.
    series: Dict[Tuple[str, str], pd.DataFrame] = {}
    for r in use_roots:
        for t in use_targets:
            try:
                series[(r, t)] = real_contract_atm_series(contract_panel, r, t, cfg=cfg)
            except ValueError:
                continue
    if not series:
        raise RuntimeError("no (root, target) benchmark could be built from the panel")

    notes = {lab: real_sector_note(lab) for lab in labels}
    frames: List[pd.DataFrame] = []
    for label in labels:
        g = cur[cur["structure"] == label].set_index("date").sort_index()
        note = notes[label]
        for (r, t), ls in series.items():
            j = g.join(ls, how="inner")
            if j.empty:
                continue
            j = j.reset_index()
            j["listed_role"] = REAL_ROOT_ROLE.get(r, "alt")
            j["listed_sector_primary"] = note["sector_primary"]
            j["listed_sector_matched"] = bool(note["sector_primary"] == r)
            j["listed_why"] = note["why"]
            j["listed_limitation"] = note["limitation"]
            frames.append(j)
    if not frames:
        raise RuntimeError("real-contract long-end panel is empty -- no (date, root) overlap")

    out = pd.concat(frames, ignore_index=True)

    be = out["breakeven_vol_bp_day"].to_numpy(dtype=float)
    listed = out["listed_atm_bp_day"].to_numpy(dtype=float)
    otc = out["atmf_vol_bp_day"].to_numpy(dtype=float)

    out["otc_atmf_bp_day"] = otc
    out["otc_node"] = f"{cfg.otc_expiry}x{cfg.otc_tenor}"
    out["cheapness_vs_listed_bp_day"] = listed - be
    out["cheapness_vs_otc_bp_day"] = otc - be
    out["otc_minus_listed_bp_day"] = otc - listed
    status = out["breakeven_status"].to_numpy()
    out["signal_listed"] = [
        signal_from_breakeven(_be_result(b, s), l,
                              threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
                              trade_when_rich=cfg.trade_when_rich)
        for b, s, l in zip(be, status, listed)
    ]
    out["signal_otc"] = [
        signal_from_breakeven(_be_result(b, s), o,
                              threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
                              trade_when_rich=cfg.trade_when_rich)
        for b, s, o in zip(be, status, otc)
    ]
    return out.set_index(["date", "structure", "listed_symbol"]).sort_index()


# =============================================================================
#  (1) EXPIRY MATCHING -- what the real ladder can actually reach
# =============================================================================


def contract_selection_report(panel: pd.DataFrame,
                              contract_panel: Optional[pd.DataFrame] = None, *,
                              horizon_years: float = 1.0,
                              cm_control_days: int = 30) -> pd.DataFrame:
    """The achieved time-to-expiry distribution, per benchmark. **Item 1.**

    Constant maturity answers "what is 30-day vol" by interpolating; a real
    contract answers "which tradeable thing is closest to my horizon" and then
    has to admit how close that was. This table is the admission.

    Columns worth reading in order:

    ``median_tte_days`` / ``max_tte_days``
        what the ladder actually reached. The maximum over the whole sample is
        241 days against a 365-day horizon.
    ``median_gap_days`` / ``best_gap_days``
        signed distance from the selected expiry to the curve horizon. Negative
        everywhere -- the option always expires first. ``best_gap_days`` is the
        closest the ladder EVER got.
    ``cm_gap_days``
        the CONTROL's gap -- ``cm_control_days - 365`` -- a constant, because a
        constant-maturity quote has no expiry to move. It is deliberately the gap
        of the constant maturity the study actually compares against
        (``US_30``, so -335 days), **not** ``target_days - 365``. The naive
        version silently reports 0.0 on the ``H365`` row, which reads as "the
        control matched the horizon perfectly" when in fact **there is no
        365-day constant-maturity series at all** -- the panel is quoted at 30,
        60 and 90 days only. Comparing this column to ``median_gap_days`` is the
        whole of item 1, so it has to name a series that exists.
    ``frac_selected_is_longest``
        how often the rule picked the back contract on the ladder. **Measured
        against the full ladder**, not asserted: pass ``contract_panel`` (the
        loader's output) and each date's selected time to expiry is compared to
        the maximum any contract of that root reached that day. At the 365-day
        target it should come back 1.00 by arithmetic -- the target is beyond
        every listed expiry, so "nearest" is "longest" -- and measuring it rather
        than stating it is what turns that arithmetic into a check on the
        selection code. NaN when ``contract_panel`` is not supplied.
    ``n_contracts`` / ``median_hold_days``
        how many distinct deliverables the benchmark used and for how long each.
    """
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    ladder_max: Dict[str, pd.Series] = {}
    if contract_panel is not None:
        a = contract_panel[contract_panel["value_type"] == "ABPV"]
        for r, g in a.groupby("root"):
            ladder_max[str(r)] = (g.groupby("date")["tte_years"].max() * 365.0)
    rows: List[Dict[str, Any]] = []
    for sym, g in df.groupby("listed_symbol", sort=True):
        one = (g.drop_duplicates(subset=["date"]).sort_values("date")
                .set_index("date"))
        tte = one["listed_tte"].to_numpy(dtype=float) * 365.0
        gap = one["listed_gap_days"].to_numpy(dtype=float)
        codes = one["listed_contract_code"].to_numpy(object)
        chg = codes[1:] != codes[:-1] if len(codes) > 1 else np.array([], dtype=bool)
        n_seg = int(chg.sum()) + 1
        target = float(one["listed_cm_days"].iloc[0])
        rows.append({
            "listed_symbol": sym,
            "listed_root": str(one["listed_root"].iloc[0]),
            "target_days": target,
            "n_days": int(len(one)),
            "first": str(one.index.min().date()), "last": str(one.index.max().date()),
            "median_tte_days": float(np.median(tte)),
            "p05_tte_days": float(np.percentile(tte, 5)),
            "p95_tte_days": float(np.percentile(tte, 95)),
            "max_tte_days": float(tte.max()),
            "median_gap_days": float(np.median(gap)),
            "best_gap_days": float(gap[np.argmin(np.abs(gap))]),
            "worst_gap_days": float(gap[np.argmax(np.abs(gap))]),
            "median_abs_gap_days": float(np.median(np.abs(gap))),
            #: The CONTROL's gap -- see the docstring for why this is the control's
            #: constant maturity and not the target.
            "cm_control_days": int(cm_control_days),
            "cm_gap_days": float(cm_control_days) - 365.0 * float(horizon_years),
            "gap_improvement_days": float(
                abs(float(cm_control_days) - 365.0 * float(horizon_years))
                - np.median(np.abs(gap))),
            "frac_selected_is_longest": _frac_longest(one, ladder_max),
            "n_contracts": int(one["listed_contract_code"].nunique()),
            "n_roll_events": int(chg.sum()),
            "median_hold_days": float(len(one) / n_seg),
            "frac_quarterly": float((one["listed_contract_kind"] == "quarterly").mean()),
        })
    return pd.DataFrame(rows)


def _frac_longest(one: pd.DataFrame, ladder_max: Mapping[str, pd.Series]) -> float:
    """Fraction of dates on which the selected contract WAS the ladder's longest.

    ``ladder_max`` is per-root ``date -> max(tte_days)`` over EVERY contract the
    vendor quoted that day, not only the selected ones, so this is a real
    measurement against the full ladder rather than a restatement of the
    selection rule. The half-day tolerance absorbs the float round-trip through
    ``tte_years * 365``; it is far tighter than the ladder's own spacing (the
    nearest two expiries are ~28 days apart), so it cannot make a
    second-longest contract look longest.
    """
    root = str(one["listed_root"].iloc[0])
    lm = ladder_max.get(root)
    if lm is None:
        return float("nan")
    sel = one["listed_tte"].to_numpy(dtype=float) * 365.0
    top = lm.reindex(one.index).to_numpy(dtype=float)
    ok = np.isfinite(sel) & np.isfinite(top)
    return float(np.mean(np.abs(sel[ok] - top[ok]) < 0.5)) if ok.any() else float("nan")


def ageing_table(panel: pd.DataFrame, cm_panel: pd.DataFrame, *,
                 root: str = HEADLINE_ROOT, cm_days: int = 30,
                 buckets: Sequence[Tuple[float, float]] = (
                     (25, 35), (50, 75), (105, 150), (150, 250))) -> pd.DataFrame:
    """Real ABPV against the same-day CM quote, bucketed by time to expiry.

    The term structure constant maturity smoothed away, as a table. At ~30 days
    a real contract and ``<root>_30`` are the same number; as the contract ages
    past the CM window they diverge, and the size of that divergence is the
    quantity a 30-day CM benchmark was silently substituting for a one-year one.

    Takes the FULL real-contract panel (all contracts, not a selection) so every
    (date, contract) observation lands in its own bucket.
    """
    r = lv.UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
    real = panel[(panel["root"] == r) & (panel["value_type"] == "ABPV")].copy()
    cm = lv.ust_cm_series(cm_panel, r, cm_days)
    real["tte_days"] = real["tte_years"].to_numpy(dtype=float) * 365.0
    real["cm"] = cm.reindex(pd.DatetimeIndex(real["date"])).to_numpy(dtype=float)
    real = real[np.isfinite(real["cm"].to_numpy(dtype=float))]

    rows: List[Dict[str, Any]] = []
    for lo, hi in buckets:
        g = real[(real["tte_days"] >= lo) & (real["tte_days"] < hi)]
        if g.empty:
            continue
        a = g["cm"].to_numpy(dtype=float)
        b = g["value"].to_numpy(dtype=float)
        rows.append({
            "tte_bucket": f"{int(lo)}-{int(hi)}d",
            "n": int(len(g)),
            "cm_median_bp_yr": float(np.median(a)),
            "real_median_bp_yr": float(np.median(b)),
            "ratio_median": float(np.median(b / a)),
            "median_abs_diff_bp_yr": float(np.median(np.abs(b - a))),
            "median_abs_diff_bp_day": float(np.median(np.abs(b - a)) / math.sqrt(252.0)),
        })
    return pd.DataFrame(rows)


# =============================================================================
#  (3) ROLL EFFECTS
# =============================================================================


def contract_roll_report(panel: pd.DataFrame) -> pd.DataFrame:
    """How often the selected contract changes, and what that does to the signal.

    **Item 3.** A constant-maturity series never rolls; a real one does, and the
    roll is the one thing a tradeable benchmark introduces that an interpolation
    cannot. Three questions, each a column:

    ``n_rolls`` / ``median_hold_days``
        how often, and how long a deliverable is held.
    ``median_abs_vol_jump_bp_day`` vs ``median_abs_daily_move_bp_day``
        the benchmark's jump ON roll days against its ordinary daily move. Their
        RATIO (``roll_jump_multiple``) is the number: 1.0 means the roll is
        invisible in the series, and a large value means the benchmark
        discontinuity is bigger than the market's own daily variation and the
        signal partly measures the roll schedule.
    ``n_signal_flips_on_roll`` / ``frac_rolls_that_flip_signal``
        how often the cheap/rich verdict changed on a roll day. This is the
        operational cost of using a tradeable benchmark, and it is zero on a
        structure whose verdict is saturated.
    """
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    rows: List[Dict[str, Any]] = []
    for (sym, label), g in df.groupby(["listed_symbol", "structure"], sort=True):
        one = g.drop_duplicates(subset=["date"]).sort_values("date")
        codes = one["listed_contract_code"].to_numpy(object)
        v = one["listed_atm_bp_day"].to_numpy(dtype=float)
        s = one["signal_listed"].to_numpy(dtype=float)
        if len(one) < 3:
            continue
        roll = codes[1:] != codes[:-1]
        dv = np.abs(np.diff(v))
        ds = s[1:] != s[:-1]
        n_roll = int(roll.sum())
        rows.append({
            "listed_symbol": sym,
            "structure": label,
            "n_days": int(len(one)),
            "n_rolls": n_roll,
            "roll_rate_per_day": float(roll.mean()),
            "median_hold_days": float(len(one) / (n_roll + 1)),
            "median_abs_vol_jump_bp_day": (float(np.median(dv[roll])) if n_roll else float("nan")),
            "median_abs_daily_move_bp_day": (float(np.median(dv[~roll]))
                                             if (~roll).any() else float("nan")),
            "roll_jump_multiple": (float(np.median(dv[roll]) / np.median(dv[~roll]))
                                   if n_roll and (~roll).any() and np.median(dv[~roll]) > 0
                                   else float("nan")),
            "n_signal_flips_total": int(ds.sum()),
            "n_signal_flips_on_roll": int((ds & roll).sum()),
            "frac_rolls_that_flip_signal": (float((ds & roll).sum() / n_roll)
                                            if n_roll else float("nan")),
            "frac_flips_that_are_rolls": (float((ds & roll).sum() / ds.sum())
                                          if ds.sum() else float("nan")),
        })
    return pd.DataFrame(rows)


# =============================================================================
#  (2) THE FUNDED STRADDLE -- JPM's own sizing, on a contract that exists
# =============================================================================


def funded_straddle_frame(
    panel: pd.DataFrame,
    fv01: Optional[pd.DataFrame] = None,
    cfg: Optional[RealContractConfig] = None,
) -> pd.DataFrame:
    """JPM's funding straddle sized against a REAL contract. **Item 2.**

        "we initiate a flattener and sell 1Yx30Y ATMF swaption straddles to fund
         the carry on the position (i.e., sized such that the initiate premium
         intake is equal to the carry over the same 1-year horizon)"

    ``strat1_curve_gamma`` already implements the sizing
    (:func:`atmf_straddle_premium_bp`, :func:`straddle_dv01_for_carry`); this
    function supplies it with a listed contract instead of a swaption node, and
    then does the thing only a real contract permits -- converts the required
    DV01 into a **number of deliverable contracts**.

    Two approximations, both deliberate and both named on the frame:

    ``carry_scaled_bp``
        the option expires before the horizon (median 133 days against 365), so
        the carry it must fund is **pro-rated linearly** to the option's own time
        to expiry: ``carry_roll_bp * tte_years / horizon_years``. Carry-and-roll
        is not exactly linear in horizon -- rolldown accelerates as the swap
        shortens -- so this is a first-order statement, and funding a 1-year
        carry with a 133-day option is in any case a *rolled* programme rather
        than a single trade. The unscaled version is carried beside it as
        ``straddle_dv01_full_carry`` so the size of the approximation is visible.
    ``premium_bp``
        Bachelier at the forward, ``sqrt(2/pi) * sigma * sqrt(T)``, with sigma the
        contract's own ABPV and T its own time to expiry. This is a premium in
        **bp of yield per unit of DV01**, which is why no futures price is needed
        to size the straddle -- only to count the contracts.

    ``fv01``
        optional ``ust_ctd_fv01.parquet`` frame (``root``, ``date``,
        ``fv01_points_per_bp``, ``futures_price``, ``ctd_mod_duration``). When
        supplied, matched backwards-in-time per root (its sampling is 1-7 days,
        so an as-of merge is the honest join) and used for ``n_contracts`` and
        ``premium_usd_per_contract``. Without it those columns are NaN and every
        other column is unchanged.
    """
    cfg = cfg or RealContractConfig()
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    need = {"carry_roll_bp", "listed_atm_bp_yr", "listed_tte", "listed_root"}
    missing = need - set(df.columns)
    if missing:
        raise KeyError(f"panel is missing {sorted(missing)}")

    tte = df["listed_tte"].to_numpy(dtype=float)
    vol = df["listed_atm_bp_yr"].to_numpy(dtype=float)
    carry_bp = df["carry_roll_bp"].to_numpy(dtype=float)

    out = df[["date", "structure", "listed_symbol", "listed_root",
              "listed_contract_code", "listed_expiry", "listed_tte",
              "listed_atm_bp_yr", "carry_roll_bp"]].copy()
    out["horizon_years"] = float(cfg.horizon_years)
    out["carry_scaled_bp"] = carry_bp * tte / float(cfg.horizon_years)
    out["carry_scaled_usd"] = out["carry_scaled_bp"] * float(cfg.package_dv01)
    out["carry_full_usd"] = carry_bp * float(cfg.package_dv01)

    out["premium_bp"] = [atmf_straddle_premium_bp(v, t) for v, t in zip(vol, tte)]
    out["straddle_dv01"] = [
        straddle_dv01_for_carry(c, v, tte_years=t)
        for c, v, t in zip(out["carry_scaled_usd"].to_numpy(dtype=float), vol, tte)]
    out["straddle_dv01_full_carry"] = [
        straddle_dv01_for_carry(c, v, tte_years=t)
        for c, v, t in zip(out["carry_full_usd"].to_numpy(dtype=float), vol, tte)]
    #: The straddle's DV01 as a multiple of the flattener package's. >1 means the
    #: funding leg carries more rate risk than the thing it funds, which is the
    #: sizing check the note's own footnote implies and never states.
    out["straddle_dv01_ratio"] = (out["straddle_dv01"].to_numpy(dtype=float)
                                  / float(cfg.package_dv01))
    #: Sign of the carry. The note's programme only makes sense when carry is
    #: NEGATIVE (the flattener bleeds and the straddle funds it). Where carry is
    #: positive there is nothing to fund, and a size computed off |carry| would
    #: silently describe a trade nobody would do -- so it is flagged, not hidden.
    out["carry_negative"] = carry_bp < 0.0

    #: Placeholders so the frame's schema does not depend on whether ``fv01`` was
    #: supplied. They are DROPPED before the as-of merge -- leaving them in makes
    #: pandas suffix the merged columns ``_x``/``_y`` and the contract count
    #: silently disappears.
    out["n_contracts"] = np.nan
    out["premium_usd_per_contract"] = np.nan
    out["fv01_points_per_bp"] = np.nan
    out["dv01_usd_per_contract"] = np.nan
    if fv01 is not None and len(fv01):
        f = fv01.copy()
        f["date"] = pd.to_datetime(f["date"])
        f = (f[f["root"].isin(sorted(set(out["listed_root"])))]
             .sort_values(["date"])[["date", "root", "fv01_points_per_bp",
                                     "futures_price", "ctd_mod_duration"]])
        left = (out.drop(columns=["n_contracts", "premium_usd_per_contract",
                                  "fv01_points_per_bp", "dv01_usd_per_contract"])
                   .sort_values("date").copy())
        merged = pd.merge_asof(left, f, left_on="date", right_on="date",
                               left_by="listed_root", right_by="root",
                               direction="backward", tolerance=pd.Timedelta("21D"))
        pts = merged["fv01_points_per_bp"].to_numpy(dtype=float)
        dv01_per_contract = pts * CONTRACT_SIZE_USD_PER_POINT
        merged["fv01_points_per_bp"] = pts
        merged["premium_usd_per_contract"] = (merged["premium_bp"].to_numpy(dtype=float)
                                              * dv01_per_contract)
        with np.errstate(invalid="ignore", divide="ignore"):
            merged["n_contracts"] = np.where(
                dv01_per_contract > 0,
                merged["straddle_dv01"].to_numpy(dtype=float) / dv01_per_contract, np.nan)
        merged["dv01_usd_per_contract"] = dv01_per_contract
        out = merged.drop(columns=[c for c in ("root",) if c in merged.columns])
    return out.reset_index(drop=True)


def funded_straddle_summary(straddle: pd.DataFrame) -> pd.DataFrame:
    """One row per (structure, benchmark): the sizing, as distributions.

    Restricted to rows where the carry is negative, because those are the only
    ones on which "sell a straddle to fund the carry" describes a trade. The
    fraction excluded is reported, since on three of the four long-end structures
    the flattener carries POSITIVELY most of the time and the note's funding leg
    is therefore not applicable at all -- a finding, not a gap.
    """
    rows: List[Dict[str, Any]] = []
    for (label, sym), g in straddle.groupby(["structure", "listed_symbol"], sort=True):
        neg = g[g["carry_negative"].to_numpy(bool)]
        rec: Dict[str, Any] = {
            "structure": label, "listed_symbol": sym,
            "n_days": int(len(g)),
            "frac_carry_negative": float(g["carry_negative"].to_numpy(bool).mean()),
            "n_fundable": int(len(neg)),
            "median_tte_days": float(np.median(g["listed_tte"].to_numpy(dtype=float)) * 365.0),
            "median_premium_bp": _med(g["premium_bp"].to_numpy(dtype=float)),
        }
        if len(neg):
            rec.update({
                "median_carry_scaled_bp": _med(neg["carry_scaled_bp"].to_numpy(dtype=float)),
                "median_straddle_dv01": _med(neg["straddle_dv01"].to_numpy(dtype=float)),
                "median_straddle_dv01_ratio": _med(neg["straddle_dv01_ratio"].to_numpy(dtype=float)),
                "median_n_contracts": _med(neg["n_contracts"].to_numpy(dtype=float))
                if "n_contracts" in neg else float("nan"),
                "p95_n_contracts": (float(np.nanpercentile(neg["n_contracts"].to_numpy(dtype=float), 95))
                                    if "n_contracts" in neg
                                    and np.isfinite(neg["n_contracts"].to_numpy(dtype=float)).any()
                                    else float("nan")),
                "median_premium_usd_per_contract": _med(
                    neg["premium_usd_per_contract"].to_numpy(dtype=float))
                if "premium_usd_per_contract" in neg else float("nan"),
            })
        rows.append(rec)
    return pd.DataFrame(rows)


# =============================================================================
#  THE SMILE -- the other thing constant maturity could not carry
# =============================================================================


def real_smile_frame(contract_panel: pd.DataFrame, *,
                     roots: Sequence[str] = REAL_ROOTS) -> pd.DataFrame:
    """The 25-delta smile of every (date, contract), converted to bp/yr.

    Conversion is the panel's own: ``listed_contracts.smile_in_bp_yr`` scales
    each quote by that row's measured ``ABPV / ATM``, which for UST is the CTD's
    ``1e4 / ModDur``. No external DV01, no duration table, no assumption that the
    scale is constant -- it is not, because the CTD changes.

    Emits, all in bp/yr:

    ``atm_bp_yr``            the ABPV (the same number the benchmark uses)
    ``call25_bp_yr`` / ``put25_bp_yr``   the 25-delta vols
    ``rr25_bp_yr``           ``call - put``. The harvest verified this identity
                             holds to 1.4e-17 against the vendor's own ``25D_RR``,
                             which is what pins the smile into a known unit.
    ``bf25_bp_yr``           ``mean(call, put) - atm``, **rebuilt from the three
                             quoted vols**. The vendor's ``25D_BF`` column is
                             deliberately NOT used: the harvest measured it as a
                             fly against an at-the-money anchor this panel does
                             not carry (residual 51% of BF's own size on US), so
                             reading it would import an error of half the
                             quantity's magnitude.

    Measured on this panel: US 25-delta put vol runs above call vol (median RR
    **-3.08 bp/yr** on 8,433 rows, negative on 70% of days) and the fly is
    positive (**+1.39 bp/yr**, 1.5% of ATM, positive on 88% of days) -- a bid for
    protection against higher yields, which is the sign a Treasury option smile
    should have.
    """
    want = ["ABPV", "ATM", "25D_CALL", "25D_PUT"]
    sub = contract_panel[contract_panel["root"].isin(list(roots))]
    sm = lc.smile_in_bp_yr(sub[sub["value_type"].isin(want + ["25D_RR", "25D_BF"])])
    w = (sm[sm["value_type"].isin(want)]
         .pivot_table(index=["date", "root", "contract_code", "contract_kind",
                             "expiry_date", "tte_years"],
                      columns="value_type", values="value_bp_yr", aggfunc="last")
         .reset_index())
    # ``value_bp_yr`` is NaN for ATM by construction (it is a level in the
    # asset's own units, not a bp/yr vol); ABPV is already bp/yr.
    for c in ("ABPV", "25D_CALL", "25D_PUT"):
        if c not in w.columns:
            raise ValueError(f"smile frame is missing {c!r} after the pivot")
    out = w.rename(columns={"ABPV": "atm_bp_yr", "25D_CALL": "call25_bp_yr",
                            "25D_PUT": "put25_bp_yr"})
    out = out.dropna(subset=["atm_bp_yr", "call25_bp_yr", "put25_bp_yr"])
    out["rr25_bp_yr"] = out["call25_bp_yr"] - out["put25_bp_yr"]
    out["bf25_bp_yr"] = 0.5 * (out["call25_bp_yr"] + out["put25_bp_yr"]) - out["atm_bp_yr"]
    out["bf25_pct_of_atm"] = out["bf25_bp_yr"] / out["atm_bp_yr"]
    return out.sort_values(["date", "root", "expiry_date"]).reset_index(drop=True)


def smile_strike_offsets(atm_bp_yr: float, call25_bp_yr: float, put25_bp_yr: float,
                         tte_years: float) -> Tuple[float, float]:
    """Yield-space strike offsets of the two 25-delta quotes, in bp.

    A Bachelier delta is ``Phi((F - K) / (sigma sqrt T))``, so a 25-delta option
    sits ``Phi^-1(0.75) = 0.6745`` standard deviations from the forward. Each
    quote is placed at its OWN vol's standard deviation, which is the convention
    that makes the three points mutually consistent (placing both at the ATM vol
    would put the wings at the wrong strikes by the size of the smile itself).

    **Sign.** The quotes are options on the FUTURES PRICE and the panel is in
    YIELD vol. A call on the price is a call on ``-yield``, so the 25-delta CALL
    sits BELOW the forward yield and the 25-delta PUT above it. Returns
    ``(offset_call_bp, offset_put_bp)`` = ``(-0.6745 sigma_c sqrt(T),
    +0.6745 sigma_p sqrt(T))``, i.e. always ``(negative, positive)``.

    Getting this backwards would mirror the skew and turn a put-bid smile into a
    call-bid one, so ``test_convexity_rv_real_contracts`` pins the sign.
    """
    t = float(tte_years)
    if not (np.isfinite(t) and t > 0):
        return (float("nan"), float("nan"))
    k = DELTA25_SIGMAS * math.sqrt(t)
    return (-k * float(call25_bp_yr), k * float(put25_bp_yr))


def three_point_smile(atm_bp_yr: float, call25_bp_yr: float, put25_bp_yr: float,
                      tte_years: float, *, n_points: int = 81) -> Optional[pd.DataFrame]:
    """The three quoted vols as a smooth ``(offset_bp, vol_bp)`` curve.

    A listed UST option gives exactly three points -- 25-delta call, at the money,
    25-delta put -- against a swaption cube's dozen. Handing three points straight
    to ``swaption_cube.implied_shift_density`` would work numerically and be
    wrong: that kernel interpolates the vol smile LINEARLY in strike, so three
    points make two straight segments meeting at a kink, and the second derivative
    of the call price picks the kink up as a spike in the density.

    So the three points are first fitted with the unique **quadratic** through
    them and evaluated on ``n_points`` inside the quoted range. This is
    interpolation, not extrapolation: nothing is generated outside
    ``[offset_call, offset_put]``, and the density kernel's own flat
    extrapolation handles the wings, which is the conservative choice (a linear
    extrapolation of a normal-vol smile turns negative and produces a negative
    density).

    Returns ``None`` when the inputs are not usable -- a non-finite vol, a
    non-positive tte, or a fitted curve that dips to a non-positive vol inside the
    quoted range. ``None`` rather than a silently-repaired curve, because the
    caller's correct response is to fall back to the ATM-only breakeven signal.
    """
    vals = (float(atm_bp_yr), float(call25_bp_yr), float(put25_bp_yr))
    if not all(np.isfinite(v) and v > 0 for v in vals):
        return None
    kc, kp = smile_strike_offsets(atm_bp_yr, call25_bp_yr, put25_bp_yr, tte_years)
    if not (np.isfinite(kc) and np.isfinite(kp)) or not (kc < 0 < kp):
        return None
    x = np.array([kc, 0.0, kp], dtype=float)
    y = np.array([float(call25_bp_yr), float(atm_bp_yr), float(put25_bp_yr)], dtype=float)
    try:
        coef = np.polyfit(x, y, 2)
    except Exception:
        return None
    grid = np.linspace(kc, kp, int(n_points))
    vol = np.polyval(coef, grid)
    if not np.isfinite(vol).all() or vol.min() <= 0:
        return None
    return pd.DataFrame({"offset_bp": grid, "vol_bp": vol})


def real_shift_density(smile: Optional[pd.DataFrame], shifts_bp: Sequence[float], *,
                       tte_years: float) -> Optional[np.ndarray]:
    """Breeden-Litzenberger density on ``shifts_bp`` from a listed 3-point smile.

    Delegates to ``swaption_cube.implied_shift_density`` -- the same kernel
    strategy 1 and the SFR mode use -- so the listed and swaption densities are
    built by identical code and a difference between them is the market.

    Returns ``None`` rather than a guess when the smile is unusable or the
    resulting density is degenerate. Two things it checks that the kernel does
    not: that the weights are finite and sum to 1, and that the density is not
    concentrated in a single grid cell (which is what a numerically failed second
    derivative looks like, and which would make ``E[payoff]`` the payoff at one
    shift).
    """
    from RVUtils.ConvexityRV.swaption_cube import implied_shift_density

    if smile is None or len(smile) < 5:
        return None
    if not np.isfinite(tte_years) or float(tte_years) <= 0:
        return None
    try:
        w = implied_shift_density(smile, shifts_bp, tte_years=float(tte_years),
                                  min_points=5)
    except Exception:
        return None
    w = np.asarray(w, dtype=float)
    if not np.isfinite(w).all() or w.sum() <= 0:
        return None
    if float(w.max()) > 0.99:
        return None
    return w


def real_expected_payoff_frame(
    panel: pd.DataFrame,
    smile: pd.DataFrame,
    *,
    shifts_bp: Optional[Sequence[float]] = None,
    cfg: Optional[RealContractConfig] = None,
) -> pd.DataFrame:
    """The note's SECOND signal, which constant maturity could not support.

        "Both measures can be interpreted as a relative value signal for curve
         convexity trades versus swaptions."

    For each (date, structure, benchmark) row of the real-contract panel, builds
    the selected contract's implied density of terminal rate shifts and
    integrates the STORED payoff profile against it. The payoff columns
    (``payoff_bp_-250`` ... ``payoff_bp_+250``) come from strategy 1's own panel
    and are reused, not recomputed, so this signal and the breakeven signal are
    computed off the same profile.

    **Two mismatches are carried on the frame rather than argued away**, because
    they bound how much weight this signal can take:

    ``ep_tte_years``
        the density is the distribution at the OPTION's expiry (median 133 days),
        while the payoff profile is a one-year terminal shift. They are not the
        same horizon. The SFR mode makes the identical choice
        (``listed_signal_row`` integrates over ``listed_tte``) and it is the only
        available one -- a listed density simply does not exist at one year.
    ``ep_quoted_halfwidth_bp``
        how far the QUOTED strikes reach, ``0.6745 * sigma * sqrt(T)`` -- about
        38 bp on US at a 133-day expiry. The shift grid runs to +/-250 bp, so
        everything beyond ~38 bp is the density kernel's flat-vol extrapolation.
        Reporting this next to the signal is what stops a +/-250 bp expected
        payoff from being read as if the wings were observed.

    ``ep_status`` is ``ok`` / ``no_smile`` / ``bad_density``, and the fraction of
    each is the honest measure of how often this signal exists at all.
    """
    cfg = cfg or RealContractConfig()
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    pay_cols = sorted([c for c in df.columns if c.startswith("payoff_bp_")],
                      key=lambda c: float(c.split("_")[-1]))
    if not pay_cols:
        raise KeyError("panel carries no payoff_bp_* columns; the stored strat1 "
                       "panel supplies them and they are required for E[payoff]")
    grid = (np.asarray(list(shifts_bp), dtype=float) if shifts_bp is not None
            else np.array([float(c.split("_")[-1]) for c in pay_cols], dtype=float))
    if len(grid) != len(pay_cols):
        raise ValueError(f"shift grid has {len(grid)} points, panel has {len(pay_cols)}")

    sk = smile.copy()
    sk["date"] = pd.to_datetime(sk["date"])
    key = sk.set_index(["date", "contract_code"])[
        ["atm_bp_yr", "call25_bp_yr", "put25_bp_yr", "tte_years"]]
    key = key[~key.index.duplicated(keep="last")]

    # One density per (date, contract) -- it does not depend on the structure, and
    # the same contract benchmarks all four.
    cache: Dict[Tuple[Any, str], Tuple[Optional[np.ndarray], str, float, float]] = {}
    ep, status, halfw, tte_used = [], [], [], []
    for d, code in zip(pd.to_datetime(df["date"]), df["listed_contract_code"].astype(str)):
        ck = (d, code)
        if ck not in cache:
            if ck not in key.index:
                cache[ck] = (None, "no_smile", float("nan"), float("nan"))
            else:
                q = key.loc[ck]
                t = float(q["tte_years"])
                sm = three_point_smile(float(q["atm_bp_yr"]), float(q["call25_bp_yr"]),
                                       float(q["put25_bp_yr"]), t)
                w = real_shift_density(sm, grid, tte_years=t)
                hw = (DELTA25_SIGMAS * float(q["atm_bp_yr"]) * math.sqrt(t)
                      if t > 0 else float("nan"))
                cache[ck] = ((w, "ok", hw, t) if w is not None
                             else (None, "bad_density", hw, t))
        w, st, hw, t = cache[ck]
        ep.append(w)
        status.append(st)
        halfw.append(hw)
        tte_used.append(t)

    pay = df[pay_cols].to_numpy(dtype=float)
    vals = np.full(len(df), np.nan, dtype=float)
    for i, w in enumerate(ep):
        if w is None:
            continue
        vals[i] = expected_payoff(grid, pay[i] * float(cfg.package_dv01), w)

    out = df[["date", "structure", "listed_symbol", "listed_contract_code",
              "listed_tte", "carry_roll_bp", "breakeven_vol_bp_day",
              "listed_atm_bp_day", "otc_atmf_bp_day", "signal_listed"]].copy()
    out["ep_status"] = status
    out["ep_tte_years"] = tte_used
    out["ep_quoted_halfwidth_bp"] = halfw
    out["expected_payoff_ccy"] = vals
    out["expected_payoff_bp"] = vals / float(cfg.package_dv01)
    #: +1 cheap / -1 rich / 0 stand aside, on the note's own rule: the curve is
    #: cheap gamma when its payoff has POSITIVE expectation under the market's own
    #: implied distribution.
    out["signal_ep_listed"] = np.where(
        ~np.isfinite(vals), 0.0,
        np.where(vals > 0.0, 1.0, np.where(cfg.trade_when_rich, -1.0, 0.0)))
    return out.reset_index(drop=True)


# =============================================================================
#  CM CONTROL vs REAL -- question (b)
# =============================================================================


def cm_vs_real_table(real_panel: pd.DataFrame, cm_panel: pd.DataFrame, *,
                     real_symbol: str = f"{HEADLINE_ROOT}@{HEADLINE_TARGET}",
                     cm_symbol: str = f"{HEADLINE_ROOT}_30") -> pd.DataFrame:
    """**Does constant maturity change any verdict?** Side by side, same curve rows.

    The direct answer to "why not real contracts". Both panels carry the identical
    curve breakeven and the identical 1Yx30Y swaption on the same dates -- only the
    listed benchmark differs -- so every difference in this table is the
    substitution and nothing else.

    Restricted to the intersection of the two benchmarks' dates, per structure.
    The columns that decide it:

    ``cheap_share_cm`` / ``cheap_share_real``  and ``cheap_share_diff``
        the headline verdict under each benchmark.
    ``frac_signal_differs``
        the fraction of days the cheap/rich verdict is NOT the same. This is the
        number that says whether CM was an adequate proxy: near zero means it was.
    ``median_listed_diff_bp_day``
        real minus CM, i.e. how much higher the real benchmark prices vol. It
        should be positive at the 365-day target, because the selected contract
        sits at a median 133 days where the ABPV term structure is above the
        30-day point.
    ``median_basis_diff_bp_day``
        what that does to the traded OTC-minus-listed basis, which is the input to
        question (c).
    """
    a = _benchmark_slice(cm_panel, cm_symbol)
    b = _benchmark_slice(real_panel, real_symbol)
    rows: List[Dict[str, Any]] = []

    def _one(label: str, ga: pd.DataFrame, gb: pd.DataFrame) -> Dict[str, Any]:
        #: Joined on (date, STRUCTURE), never on date alone. The per-structure
        #: slices have a unique date so either would work there, but the POOLED
        #: row concatenates four structures and a date-only join would cross them
        #: 4x4 -- turning 7,416 aligned rows into 30,416 and reporting a
        #: "disagreement rate" of 17% that is entirely the cross product. Caught
        #: by the pooled row disagreeing with every structure it pools.
        j = ga.merge(gb, on=["date", "structure"], suffixes=("_cm", "_real"))
        n = int(len(j))
        if not n:
            return {"structure": label, "n_days": 0}
        sa = j["signal_listed_cm"].to_numpy(dtype=float)
        sb = j["signal_listed_real"].to_numpy(dtype=float)
        la = j["listed_atm_bp_day_cm"].to_numpy(dtype=float)
        lb = j["listed_atm_bp_day_real"].to_numpy(dtype=float)
        return {
            "structure": label,
            "cm_symbol": cm_symbol, "real_symbol": real_symbol,
            "n_days": n,
            "first": str(j["date"].min().date()), "last": str(j["date"].max().date()),
            "cheap_share_cm": float((sa > 0).mean()),
            "cheap_share_real": float((sb > 0).mean()),
            "cheap_share_diff": float((sb > 0).mean() - (sa > 0).mean()),
            "rich_share_cm": float((sa < 0).mean()),
            "rich_share_real": float((sb < 0).mean()),
            "frac_signal_differs": float((sa != sb).mean()),
            "n_signal_differs": int((sa != sb).sum()),
            "median_listed_cm_bp_day": float(np.median(la)),
            "median_listed_real_bp_day": float(np.median(lb)),
            "median_listed_diff_bp_day": float(np.median(lb - la)),
            "p95_abs_listed_diff_bp_day": float(np.percentile(np.abs(lb - la), 95)),
            "corr_level": float(pd.Series(la).corr(pd.Series(lb))),
            "corr_change": float(pd.Series(la).diff().corr(pd.Series(lb).diff())),
            "median_basis_cm_bp_day": float(np.nanmedian(
                j["otc_minus_listed_bp_day_cm"].to_numpy(dtype=float))),
            "median_basis_real_bp_day": float(np.nanmedian(
                j["otc_minus_listed_bp_day_real"].to_numpy(dtype=float))),
            "median_basis_diff_bp_day": float(np.nanmedian(
                j["otc_minus_listed_bp_day_real"].to_numpy(dtype=float)
                - j["otc_minus_listed_bp_day_cm"].to_numpy(dtype=float))),
            "median_tte_days_real": float(np.median(
                j["listed_tte_real"].to_numpy(dtype=float)) * 365.0),
        }

    labels = sorted(set(a["structure"]) & set(b["structure"]))
    pool_a, pool_b = [], []
    for label in labels:
        ga = a[a["structure"] == label]
        gb = b[b["structure"] == label]
        rows.append(_one(label, ga, gb))
        pool_a.append(ga)
        pool_b.append(gb)
    if pool_a:
        rows.append(_one("POOLED", pd.concat(pool_a, ignore_index=True),
                         pd.concat(pool_b, ignore_index=True)))
    return pd.DataFrame(rows)


def _benchmark_slice(panel: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """One benchmark's rows, flat, with the columns the CM/real comparison needs."""
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    sel = df[df["listed_symbol"].astype(str) == str(symbol)]
    if sel.empty:
        raise ValueError(f"no rows for listed_symbol={symbol!r}; present: "
                         f"{sorted(set(df['listed_symbol'].astype(str)))[:8]}")
    keep = ["date", "structure", "signal_listed", "listed_atm_bp_day",
            "otc_minus_listed_bp_day", "otc_atmf_bp_day", "breakeven_vol_bp_day"]
    if "listed_tte" in sel.columns:
        keep.append("listed_tte")
    out = sel[keep].copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.drop_duplicates(subset=["date", "structure"]).sort_values(["structure", "date"])


# =============================================================================
#  Three-way -- reuse strat1_threeway wholesale
# =============================================================================


def real_threeway_config(**overrides: Any) -> "tw.Strat1ThreeWayConfig":
    """The three-way config for the real-contract study.

    Identical to ``strat1_threeway.longend_config()`` -- same structures, same
    window, same cost, same one-day signal lag, same one-year horizon -- because
    the gate books are derived from strategy 1's own stored cohort tables and
    would be incomparable to the constant-maturity run otherwise. The ONLY thing
    that differs between the CM run and this one is which column
    ``listed_atm_bp_day`` was filled from, which is exactly the experiment.
    """
    return tw.longend_config(**overrides)


def real_threeway_frames(panel: pd.DataFrame,
                         cfg: Optional["tw.Strat1ThreeWayConfig"] = None,
                         *, roots: Sequence[str] = REAL_ROOTS,
                         targets: Sequence[str] = tuple(t[0] for t in TARGETS),
                         ) -> Dict[str, pd.DataFrame]:
    """One ``threeway_frame`` per (root, expiry target). Robustness, not trials.

    Keyed ``"{root}@{target}"``, matching ``listed_symbol``. The headline is
    ``"US@H365"``. The other seven are the same four gate modes against a
    different benchmark and are NOT counted as trials in the multiple-testing
    correction, for the same reason the CM study's eleven robustness benchmarks
    are not.

    Selection goes through ``strat1_threeway.select_longend_benchmark(root=...)``
    unchanged -- the real-contract panel was built to that function's contract,
    so nothing about the ranking, the gates or the statistics is reimplemented
    here.
    """
    cfg = cfg or real_threeway_config()
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    out: Dict[str, pd.DataFrame] = {}
    for r in roots:
        for t in targets:
            sym = f"{r}@{t}"
            sel = df[df["listed_symbol"].astype(str) == sym]
            if sel.empty:
                continue
            dup = sel.duplicated(subset=["date", "structure"])
            if dup.any():
                raise ValueError(f"{sym} does not give a unique (date, structure) key")
            out[sym] = tw.threeway_frame(sel, cfg)
    if not out:
        raise ValueError("no (root, target) benchmark produced any rows")
    return out


def cm_vs_real_gate_table(three_cm: pd.DataFrame, three_real: pd.DataFrame,
                          ) -> pd.DataFrame:
    """Gate-by-gate: does swapping CM for a real contract change what trades?

    The operational half of question (b). Both frames carry the identical curve
    and swaption columns on the same ``(date, structure)`` key, so the comparison
    is restricted to their intersection and every difference is the listed leg.

    ``frac_gate_differs`` per mode is the number: ``swaption_only`` must be
    exactly 0.0 (it does not touch the listed benchmark, so a non-zero value
    means the two frames are not aligned and every other row is suspect), while
    ``listed_only`` and ``both`` carry the real answer.
    """
    a = three_cm.reset_index()
    b = three_real.reset_index()
    key = ["date", "structure"]
    a["date"] = pd.to_datetime(a["date"])
    b["date"] = pd.to_datetime(b["date"])
    modes = [c for c in a.columns if c.startswith("gate_")]
    j = a.merge(b, on=key, suffixes=("_cm", "_real"))
    j = j[j["usable_cm"].to_numpy(bool) & j["usable_real"].to_numpy(bool)]
    rows: List[Dict[str, Any]] = []

    def _one(label: str, g: pd.DataFrame) -> Dict[str, Any]:
        rec: Dict[str, Any] = {"structure": label, "n_days": int(len(g))}
        for m in modes:
            x = g[f"{m}_cm"].to_numpy(dtype=float)
            y = g[f"{m}_real"].to_numpy(dtype=float)
            rec[f"frac_differs_{m[5:]}"] = float((x != y).mean()) if len(g) else float("nan")
            rec[f"n_differs_{m[5:]}"] = int((x != y).sum())
        rec["frac_cheapest_changes"] = (
            float((g["cheapest_source_cm"].to_numpy(object)
                   != g["cheapest_source_real"].to_numpy(object)).mean()) if len(g) else float("nan"))
        rec["median_listed_diff_bp_day"] = (
            float(np.nanmedian(g["listed_bp_day_real"].to_numpy(dtype=float)
                               - g["listed_bp_day_cm"].to_numpy(dtype=float))) if len(g) else float("nan"))
        return rec

    for label, g in j.groupby("structure", sort=True):
        rows.append(_one(label, g))
    rows.append(_one("POOLED", j))
    return pd.DataFrame(rows)


# =============================================================================
#  The verdict
# =============================================================================


def real_contract_verdict(
    three_real: pd.DataFrame,
    basis_real: pd.DataFrame,
    *,
    three_cm: Optional[pd.DataFrame] = None,
    cm_vs_real: Optional[pd.DataFrame] = None,
    selection: Optional[pd.DataFrame] = None,
    rolls: Optional[pd.DataFrame] = None,
    straddle: Optional[pd.DataFrame] = None,
    ep: Optional[pd.DataFrame] = None,
    ul_penalty: Optional[Mapping[str, Any]] = None,
    books: Optional[pd.DataFrame] = None,
    cohorts: Optional[Mapping[str, pd.DataFrame]] = None,
    cfg: Optional["tw.Strat1ThreeWayConfig"] = None,
) -> Dict[str, Any]:
    """Everything the real-contract report has to state, as one JSON-able dict.

    Built on ``strat1_threeway.longend_verdict`` -- the coverage, ranking,
    agreement, flip-threshold, persistence and sample-size machinery is the CM
    study's, unmodified, so the two verdicts are directly comparable -- and adds
    the four things only a real contract can answer:

    ``expiry_match``      how close the ladder got to the horizon (item 1)
    ``roll``              what the roll does to the benchmark and the signal (item 3)
    ``funded_straddle``   the note's own sizing, in contracts (item 2)
    ``cm_control``        whether constant maturity was an adequate proxy (question b)

    Leads with coverage and puts the P&L last and labelled, which is the order of
    evidential weight at ~7.5 effective observations per structure.
    """
    cfg = cfg or real_threeway_config()
    out = tw.longend_verdict(three_real, basis_real, books=books, cohorts=cohorts, cfg=cfg)
    out["mode"] = "UST long end, REAL LISTED CONTRACTS"
    out["headline_benchmark"] = {
        "listed_symbol": f"{HEADLINE_ROOT}@{HEADLINE_TARGET}",
        "root": HEADLINE_ROOT,
        "target": HEADLINE_TARGET,
        "rule": "the listed contract whose time to expiry is closest to the curve horizon",
        "pre_specified": True,
    }
    out["sector_limitation"] = {
        "real_roots_available": list(REAL_ROOTS),
        "unavailable": UNAVAILABLE_REAL_ROOTS,
        "per_structure": [real_sector_note(s) for s in sorted(
            set(three_real.reset_index()["structure"].astype(str)))],
        "substitution_penalty": dict(ul_penalty) if ul_penalty else None,
    }
    if selection is not None and len(selection):
        h = selection[selection["listed_symbol"] == f"{HEADLINE_ROOT}@{HEADLINE_TARGET}"]
        out["expiry_match"] = {
            "headline": (h.iloc[0].to_dict() if len(h) else None),
            "all_benchmarks": selection.to_dict("records"),
        }
    if rolls is not None and len(rolls):
        h = rolls[rolls["listed_symbol"] == f"{HEADLINE_ROOT}@{HEADLINE_TARGET}"]
        out["roll"] = {"headline": h.to_dict("records"),
                       "all_benchmarks": rolls.to_dict("records")}
    if straddle is not None and len(straddle):
        out["funded_straddle"] = straddle.to_dict("records")
    if ep is not None and len(ep):
        st = ep["ep_status"].value_counts(normalize=True).to_dict()
        h = ep[ep["listed_symbol"] == f"{HEADLINE_ROOT}@{HEADLINE_TARGET}"]
        ok = h[h["ep_status"] == "ok"]
        out["expected_payoff"] = {
            "status_shares": {str(k): float(v) for k, v in st.items()},
            "n_rows": int(len(ep)),
            "headline_n_ok": int(len(ok)),
            "headline_median_ep_bp": (float(np.nanmedian(ok["expected_payoff_bp"]))
                                      if len(ok) else float("nan")),
            "headline_frac_positive": (float((ok["expected_payoff_bp"] > 0).mean())
                                       if len(ok) else float("nan")),
            "median_quoted_halfwidth_bp": float(np.nanmedian(
                ep["ep_quoted_halfwidth_bp"].to_numpy(dtype=float))),
            "caveat": ("the density is at the OPTION's expiry (median ~133 days), not at "
                       "the payoff profile's 1-year horizon, and only +/-~38 bp of strike "
                       "is quoted -- beyond that the wings are a flat-vol extrapolation. "
                       "The breakeven-vol signal remains the headline."),
        }
    if cm_vs_real is not None and len(cm_vs_real):
        p = cm_vs_real[cm_vs_real["structure"] == "POOLED"]
        out["cm_control"] = {
            "per_structure": cm_vs_real.to_dict("records"),
            "pooled": (p.iloc[0].to_dict() if len(p) else None),
        }
    if three_cm is not None and len(three_cm):
        out["cm_control"] = out.get("cm_control", {})
        out["cm_control"]["gate_table"] = cm_vs_real_gate_table(
            three_cm, three_real).to_dict("records")
    return out
