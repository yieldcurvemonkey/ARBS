"""Strategy 1, THREE WAYS -- the curve, the swaption and the exchange in one unit.

The same long-gamma exposure is available from three places, and all three
reduce to a normal volatility in **bp/day**:

===========  =========================================================
source       the number
===========  =========================================================
CURVE        the flattener's **breakeven vol** -- how much daily normal
             vol you must realise for the convexity to pay for the
             carry (``strat1_curve_gamma.breakeven_vol``).
SWAPTION     **ATMF normal vol** from the Citi Velocity cube, at the
             sector-matched node (1Yx2Y, not JPM's 1Yx30Y -- see below).
LISTED       **ATM normal vol** of SFR (3M SOFR) futures options, at the
             horizon-matched listed expiry (``listed_vol``).
===========  =========================================================

Cheapest wins. But a single winner is the least interesting thing this
comparison produces, and this module is built around the three questions that
are actually informative:

(a) **How often does the ranking change, and do the two curve-vs-vol signals
    ever disagree?** ``signal_swaption`` and ``signal_listed`` are the same
    curve breakeven measured against two different benchmarks. If they never
    disagree, the listed leg adds nothing over the swaption leg and this module
    should say so plainly -- :func:`agreement_table` and
    :func:`threeway_verdict` are written so that outcome is reportable rather
    than embarrassing.
(b) **The swaption-minus-listed basis as its own series.** That is a real
    traded spread (buy listed gamma, sell OTC gamma, or the reverse), and its
    level and percentile are what condition whether gamma should be sourced
    listed or OTC. :func:`basis_frame`.
(c) **Does conditioning on "cheap vs BOTH" beat "cheap vs the swaption
    alone"?** This is the only honest test of whether the third leg carries
    information, and :func:`all_gate_books` answers it on *identical* cohorts.


The window is the intersection, and it is short
------------------------------------------------
The three series have very different coverage:

* curve breakeven -- 2019-01-02 onward (the swap curve store)
* swaption ATMF -- 2015-10 onward
* **listed SFR -- 2024-07-01 .. 2026-07-28 only**

so the three-way comparison exists ONLY on the intersection. Measured on the
strategy-1-listed panel: 540 listed dates, of which **517** carry a finite
swaption ATMF *and* a horizon-matched listed ATM. Every three-way statistic in
this module is computed on that intersection and nowhere else;
:func:`intersection_report` prints the three coverages side by side so a longer
number can never be quoted by accident.

Two years with a one-year holding period is roughly **two** non-overlapping
observations per structure. That cannot support a Sharpe ratio, and none is
claimed. The headline outputs are :func:`rank_table`, :func:`agreement_table`
and :func:`basis_frame` -- statements about pricing, which survive a short
sample -- while the gate-mode P&L is explicitly an illustration.
:func:`effective_independent_n` and :func:`expected_max_sharpe_under_null` are
provided so the sample-size caveat is a number rather than a sentence.


Sector matching is mandatory
-----------------------------
An SFR option prices a 3-month rate; a 30-year forward flattener does not. The
universe here is ``strat1_listed.SFR_STRUCTURES`` -- five SFR-sector forward
flatteners -- and the swaption node is **1Yx2Y**, chosen to match the curve
legs' tenor and the listed option's sector. JPM's own 1Yx30Y node is carried
only as a labelled, deliberately non-sector-matched reference, because the long
end is exactly where the listed benchmark is missing (there is no offline UST
futures-option history; see ``listed_vol.load_ust_panel``).


Gate modes -- and the identity between two of them
---------------------------------------------------
Five gates are implemented. All are the same curve breakeven read against a
different rule:

``swaption_only``
    the curve must beat the swaption. This is strategy 1's own signal.
``listed_only``
    the curve must beat the exchange. This is strategy 1-listed's signal.
``both``
    the curve must beat BOTH. Mixed verdicts stand aside.
``cheapest``
    the curve must be the cheapest of the three (and is sold when it is the
    richest of the three).
``either``
    the curve need only beat ONE. Deliberately asymmetric -- it is long
    whenever at least one market says cheap and short only when both say rich
    -- and it is here as the permissive bound on the other gates, not as a
    recommendation.

**``both`` and ``cheapest`` are the same signal -- always, not just at the
default configuration.** That is arithmetic, and it is worth stating plainly
because the two read like different ideas. For any threshold ``t``:

    both = +1  <=>  curve < swaption - t AND curve < listed - t
               <=>  curve < min(swaption, listed) - t  =  cheapest = +1
    both = -1  <=>  curve > swaption + t AND curve > listed + t
               <=>  curve > max(swaption, listed) + t  =  cheapest = -1
    both =  0  <=>  neither                            =  cheapest =  0

"the curve beats both benchmarks" and "the curve is the cheapest of the three"
are the same proposition, so **no knob separates them** -- not the no-trade
band, not ``trade_when_rich``, not the missing-data handling. The sentinels
respect it too (``always_cheap`` carries breakeven 0, below any positive
benchmark; ``never_cheap`` carries ``+inf``, above any finite one).

Both names are implemented anyway, by deliberately different expressions -- an
AND over the two signals versus a comparison against the min/max -- so that
:func:`assert_both_equals_cheapest` is a genuine measurement of two independent
code paths rather than a tautology about one. The spec for this study asked for
four gate modes; two of them are provably one mode, which is why
:data:`DISTINCT_GATE_MODES` has four entries rather than five and why the
multiple-testing correction counts four trials.


Why no engine run happens here
-------------------------------
Scoring five gate modes on five structures the obvious way is twenty
``QueryDrivenBacktest`` passes. It is also unnecessary and slightly wrong.

Swap NPV is **linear in ``bpv``**, and ``strat1_curve_gamma.build_backtest``
opens each cohort with ``front_bpv = +dv01*s``, ``back_bpv = -dv01*s``. Flipping
``s`` therefore negates the package exactly, and the unwind fee
(``2 * cost_bp_one_way * package_dv01``) does not depend on ``s`` at all. So a
cohort's P&L under ANY gate is recoverable from ONE stored run::

    unit_gross_bp = stored_direction * stored_gross_bp     # pure flattener
    gate_gross_bp = gate_direction  * unit_gross_bp
    gate_net_bp   = gate_gross_bp - 2 * cost_bp_one_way    # when traded

This is not merely cheaper -- it is the cleaner experiment, because every gate
mode is then scored on *bit-identical cohort P&L* and the only thing that
differs between modes is the gate. A per-mode engine run would re-introduce
run-to-run differences that have nothing to do with the question.

The linearity claim is load-bearing, so it is **verified, not assumed**:
``notebooks/backtests/convexity_rv/_strat1_threeway_build.py verify`` re-runs one
structure as a pure flattener and ties out cohort-by-cohort against the stored
mixed-direction run. :func:`apply_gate` additionally has a known-answer property
that the test suite pins: replaying the STORED direction through it must
reproduce the stored ``net_pnl_bp`` exactly.


=============================================================================
THE LONG-END MODE -- same three questions, the sector strategy 1 actually trades
=============================================================================

Everything above describes the SFR (short-end) study, and every word of it still
holds: :data:`Strat1ThreeWayConfig`'s defaults, :data:`GATE_MODES` and every
function's behaviour on an SFR panel are unchanged. The long-end mode is
*additional*, reached through :func:`longend_config` and
:func:`select_longend_benchmark`, and it exists because the constant-maturity UST
vol harvest removed the two limits that made the short-end study weak:

=================  ==============================  ==============================
                   SFR / short-end study           UST / long-end study
=================  ==============================  ==============================
window             517 dates (2024-07..2026-07)    **1,854 dates** (2019-01..2026-08)
structures         SFR-sector 2-3Y-tail forwards   strategy 1's OWN long-end four
swaption node      1Yx2Y (sector-matched proxy)    **1Yx30Y** (the note's node)
listed benchmark   SFR 3M SOFR option              UST futures option ABPV
n_eff / structure  2.05                            **7.50**
=================  ==============================  ==============================

The intersection is ~7.5 years rather than ~2, and the structures are the ones
the note recommends rather than short-end stand-ins chosen to match the data.


Why the long-end panel needs an adapter and not a new pipeline
---------------------------------------------------------------
``strat1_listed.build_longend_listed_panel`` emits one row per
**(date, structure, listed_symbol)** -- twelve (root, constant-maturity)
benchmarks, so the primary, the alt and a deliberately-wrong control are all
visible side by side. Its three vol columns are already named
``breakeven_vol_bp_day`` / ``otc_atmf_bp_day`` / ``listed_atm_bp_day``, which are
exactly :class:`Strat1ThreeWayConfig`'s defaults.

So the only thing standing between that panel and every function above is the
duplicated ``(date, structure)`` key. :func:`select_longend_benchmark` collapses
it by picking ONE benchmark, after which :func:`threeway_frame`,
:func:`rank_table`, :func:`agreement_table`, :func:`all_gate_books` and the rest
run unmodified. That is the whole extension, and it is deliberate: a second
implementation of the ranking or the gates would make a long-end/short-end
divergence un-diagnosable.

**The headline benchmark is pre-specified**: ``role="primary"``, ``cm_days=30``.
Pre-specified in the sense that matters -- the primary root per structure comes
from ``listed_vol.UST_SECTOR_MAP``, which was fixed by the *measured* CTD
maturity of each contract before any three-way statistic was computed, and 30
days is the shortest (most liquid, best-populated) constant maturity. The other
eleven benchmarks are reported by :func:`benchmark_sweep_table` as **robustness,
not as extra trials**: they are the same gate against a different benchmark, and
counting them in the multiple-testing correction would be double-counting the
same four gate modes twelve times.


The basis is PER BENCHMARK, and :func:`basis_frame` must not be used
--------------------------------------------------------------------
On the SFR panel the two benchmark columns were identical across structures on a
given date, so ``basis_frame``'s ``drop_duplicates(subset=["date"])`` was safe.
**On the long end it is not**, because the primary root differs by structure (UL
for 30Y/50Y and 20Yx5Y/25Yx5Y, US for 10Yx10Y/20Yx10Y and 5Y/30Y): dropping
duplicates by date would silently keep whichever structure sorted first and label
one root's basis "the basis". :func:`longend_basis_frame` therefore keys on
``(date, listed_symbol)`` and every downstream statistic
(:func:`basis_persistence`, :func:`basis_regime_table`) is computed per symbol.
Calling :func:`basis_frame` on a long-end panel raises.


The retest that motivated the whole study
------------------------------------------
The short-end conclusion was "listed adds essentially no information over the
sector-matched swaption", and it rested on a ratio: the median |OTC-listed basis|
was **0.271 bp/day** against a **2.721 bp/day** threshold to flip a quarter of
days -- a factor of **10.0**, so the two benchmarks *arithmetically could not*
often disagree. The long end is a different market (swaption vol there is set by
structured-product and mortgage-convexity hedging, listed bond-option vol by
macro and dealer gamma), so the brief was to re-measure that ratio like for like.
:func:`flip_threshold_table` computes it with the identical formula, and the
answer is **not** the same number:

=======================  =======  ==========  ========  =========  ========  =========
structure (benchmark)    n        med basis   flip p25  **ratio**  disagree  saturated
=======================  =======  ==========  ========  =========  ========  =========
5Y/30Y  (US_30)            1,854       0.556     1.917  **3.45**     3.34%      0.514
10Yx10Y/20Yx10Y (US_30)    1,854       0.556     2.936      5.28     0.00%      1.000
20Yx5Y/25Yx5Y (UL_30)      1,614       0.424     4.177      9.84     0.00%      1.000
30Y/50Y (UL_30)            1,614       0.424     4.243     10.00     0.00%      1.000
SFR short end (prior)      2,585       0.271     2.721     10.02     1.59%        n/a
=======================  =======  ==========  ========  =========  ========  =========

"med basis" is the median ABSOLUTE basis and "flip p25" the 25th percentile of
the absolute curve-vs-swaption gap -- the same two quantities, by the same
expression, that the short-end ratio was built from. In particular the
percentile INCLUDES ``never_cheap`` days, whose gap is ``+inf``, exactly as the
short-end computation did; the finite-only variant is carried alongside
(``shortfall_multiple_p25_finite``) and reads 2.40 on 5Y/30Y, but a retest run
on a different formula is not a retest.

Read that table with the saturation caveat attached, because without it the
middle three rows say the opposite of what they mean. On those three the
flattener is cheap gamma against BOTH benchmarks on **100.0%** of days
(``frac_verdict_saturated`` = 1.000): the breakeven is the ``always_cheap``
sentinel ``0.0`` on 34-85% of days, ``|curve - swaption|`` degenerates to the
swaption level itself (~4-5 bp/day), and their flip threshold is large **because
the verdict is saturated**, not because the two markets agree. Their 0.00%
disagreement is arithmetic of the most trivial kind.

**5Y/30Y is the only structure on which the comparison binds** -- its verdict is
cheap on 51.4% of days and rich on the rest -- and there the ratio falls from
10.02 to **3.45**: the basis roughly doubles (0.271 -> 0.556 bp/day) while the
threshold falls by a third (2.721 -> 1.917), a **2.9-fold** compression. The
disagreement rate rises correspondingly, from 1.59% to **3.34%** at the
pre-specified benchmark, and ranges 3.24%-5.34% across the twelve. That is a
real difference in kind between the two sectors, and :func:`longend_verdict`
states it without inflating it: 3.34% is still a small number, it is below the
5% materiality bar the short-end study used, and three of the four structures
remain at exactly zero.

One trap worth naming, because it is the obvious wrong selector: **the binding
structure must be picked on ``frac_verdict_saturated``, not on the share of days
at a breakeven sentinel.** Measured, those two rank the universe differently --
10Yx10Y/20Yx10Y has FEWER sentinel days than 5Y/30Y (0.342 vs 0.578) and yet its
verdict is unanimous. Selecting on sentinels nominates a structure whose
disagreement rate is exactly zero as the one where the benchmark matters.


Sample size: 7.50 per structure, ~9.7 pooled -- both measured
--------------------------------------------------------------
The cohorts are monthly one-year holds over 2019-02-01..2026-08-03, so each
structure contains ``2740 / 365.25 = 7.50`` non-overlapping observations, not 88.
Pooling the four does **not** give 30: their measured pairwise unit-cohort P&L
correlation is **0.698 on average** (0.489 for 5Y/30Y vs 20Yx5Y/25Yx5Y, up to
0.862 for 30Y/50Y vs 10Yx10Y/20Yx10Y), so
``k_eff = k / (1 + (k-1) * rbar) = 4 / (1 + 3*0.698) = 1.29`` independent
structures and the pooled effective count is ``7.50 * 1.29 = 9.7``.
:func:`cohort_pnl_correlation` measures the correlation and
:func:`effective_independent_n_pooled` applies it, so neither number is asserted.
Every Sharpe in this mode is quoted against
:func:`expected_max_sharpe_under_null` evaluated at that count and at
``len(DISTINCT_GATE_MODES) == 4`` trials.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.strat1_listed import LONG_END_STRUCTURES, SFR_STRUCTURES

__all__ = [
    "Strat1ThreeWayConfig",
    "GATE_MODES",
    "SOURCES",
    "threeway_frame",
    "intersection_report",
    "rank_table",
    "transition_table",
    "agreement_table",
    "basis_frame",
    "basis_summary",
    "gate_direction",
    "gate_columns",
    "assert_both_equals_cheapest",
    "unit_cohort_table",
    "apply_gate",
    "all_gate_books",
    "gate_summary",
    "conditional_basis_table",
    "effective_independent_n",
    "expected_max_sharpe_under_null",
    "deflated_sharpe_ratio",
    "threeway_verdict",
    # ------------------------------------------------------- UST long-end mode
    "LONGEND_STRUCTURES",
    "LONGEND_ROLES",
    "LONGEND_CM_DAYS",
    "HEADLINE_ROLE",
    "HEADLINE_CM_DAYS",
    "SHORT_END_REFERENCE",
    "longend_config",
    "select_longend_benchmark",
    "longend_threeway_frames",
    "longend_intersection_report",
    "longend_basis_frame",
    "basis_persistence",
    "basis_regime_table",
    "flip_threshold_table",
    "benchmark_sweep_table",
    "gate_distinctness_table",
    "cohort_pnl_correlation",
    "effective_independent_n_pooled",
    "longend_verdict",
]


#: The three sources of the same exposure, in the order they are ranked.
SOURCES: Tuple[str, str, str] = ("curve", "swaption", "listed")

#: Every gate mode. ``both`` and ``cheapest`` coincide at the default config --
#: see the module docstring and :func:`assert_both_equals_cheapest`.
GATE_MODES: Tuple[str, ...] = (
    "swaption_only", "listed_only", "both", "cheapest", "either",
)

#: Gate modes that are DISTINCT at the default configuration. ``cheapest`` is
#: dropped because it is identical to ``both``; using this tuple as the trial
#: count for :func:`expected_max_sharpe_under_null` is what keeps the multiple-
#: testing correction honest -- counting an identical curve twice would deflate
#: the threshold rather than raise it.
DISTINCT_GATE_MODES: Tuple[str, ...] = (
    "swaption_only", "listed_only", "both", "either",
)


@dataclass(frozen=True)
class Strat1ThreeWayConfig:
    """Every knob of the three-way study. Nothing here is tuned on the P&L."""

    # ---------------------------------------------------------------- universe
    #: (label, front_tenor, back_tenor). Defaults to the SFR-sector flatteners
    #: ``strat1_listed`` built, because sector matching is mandatory: the listed
    #: benchmark is a 3M SOFR option and a 30-year flattener is not the same
    #: risk. The long-end structures have NO listed benchmark at all.
    structures: Tuple[Tuple[str, str, str], ...] = SFR_STRUCTURES

    # --------------------------------------------------- where the vols live
    #: Column carrying the CURVE's breakeven vol in bp/day. ``always_cheap``
    #: days carry 0.0 and ``never_cheap`` days carry ``+inf``; both are
    #: meaningful and are ranked as such, so this column is filtered on
    #: ``isnan``, never on ``isfinite``.
    curve_col: str = "breakeven_vol_bp_day"
    #: Column carrying the SWAPTION ATMF vol in bp/day (sector-matched node).
    swaption_col: str = "otc_atmf_bp_day"
    #: Column carrying the LISTED ATM vol in bp/day (horizon-matched expiry).
    listed_col: str = "listed_atm_bp_day"

    # ------------------------------------------------------------------ signal
    #: The curve is CHEAP against a benchmark when
    #: ``curve_bp_day < benchmark_bp_day - entry_threshold_bp_per_day`` and RICH
    #: when above by the same margin. 0.0 is JPM's own rule: any divergence
    #: trades. A positive value opens a no-trade band around each benchmark; it
    #: does NOT separate ``both`` from ``cheapest``, which are identical at every
    #: threshold (see the module docstring).
    entry_threshold_bp_per_day: float = 0.0
    #: When False the rich side stands aside instead of putting on a steepener.
    #: The note trades both sides: "when it is negative, we do the opposite."
    trade_when_rich: bool = True
    #: Require all three vols present before ANY gate fires. True by default and
    #: it matters: with it False, ``swaption_only`` would trade on dates
    #: ``listed_only`` cannot, and the gate comparison would be measuring
    #: coverage rather than information.
    require_all_three: bool = True
    #: The gate that drives ``direction`` when a single one is asked for.
    gate_mode: str = "both"

    # ------------------------------------------------------------------- units
    #: Business days per year for the annual-vol <-> daily-vol bridge. Applied
    #: identically to all three sources, which is what makes bp/day common.
    business_days_per_year: float = 252.0
    #: Curve horizon in years. Also the cohort holding period, and the target the
    #: listed expiry was matched to.
    horizon_years: float = 1.0

    # -------------------------------------------------------------- basis knobs
    #: Rolling window, business days, for the basis percentile. 63 ~ one quarter.
    #: Descriptive only -- nothing trades off it in this module.
    basis_window: int = 63
    #: Number of buckets for the conditional basis table.
    basis_quantiles: int = 5

    # ---------------------------------------------------------------- backtest
    #: One-way cost per leg-pair, bp of package DV01. Charged twice at the
    #: unwind, matching the engine's only cost hook and the stored runs.
    cost_bp_one_way: float = 0.5
    #: Package risk the stored cohort P&L is quoted against.
    package_dv01: float = 100_000.0
    #: Days the gate is lagged before a cohort acts on it. The stored runs used
    #: 1 (signal off day t's close, fill at t+1) and the gate books must use the
    #: same lag or they are not comparable to them.
    signal_lag_days: int = 1

    # ------------------------------------------------------------------ window
    #: The listed panel's own span -- the binding constraint. The curve runs from
    #: 2019 and the swaption cube from 2015, so neither binds.
    start: datetime.date = datetime.date(2024, 7, 1)
    end: datetime.date = datetime.date(2026, 7, 28)

    def labels(self) -> Tuple[str, ...]:
        return tuple(s[0] for s in self.structures)

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------- the three vols


def _sig(curve: np.ndarray, bench: np.ndarray, *, threshold: float,
         trade_when_rich: bool) -> np.ndarray:
    """+1 cheap / -1 rich / 0 stand aside, elementwise.

    Deliberately a pure numeric comparison rather than a re-implementation of
    ``strat1_curve_gamma.signal_from_breakeven``'s status switch, because the
    sentinels already encode themselves: ``always_cheap`` stores 0.0, which is
    below any positive benchmark, and ``never_cheap`` stores ``+inf``, which is
    above any finite one. ``undefined`` stores NaN and both comparisons fail, so
    it lands on 0. At ``threshold == 0`` this reproduces that function row for
    row, which the test suite pins against the stored panel.
    """
    c = np.asarray(curve, dtype=float)
    b = np.asarray(bench, dtype=float)
    t = abs(float(threshold))
    ok = np.isfinite(b) & ~np.isnan(c)          # +inf curve is MEANINGFUL, keep it
    out = np.zeros(c.shape, dtype=float)
    out[ok & (c < b - t)] = 1.0
    if trade_when_rich:
        out[ok & (c > b + t)] = -1.0
    return out


def threeway_frame(panel: pd.DataFrame, cfg: Optional[Strat1ThreeWayConfig] = None
                   ) -> pd.DataFrame:
    """Align the three vol series and everything derived from them.

    ``panel`` is the strategy-1-listed signal panel (or anything carrying
    ``date``, ``structure`` and the three configured vol columns). Returns a
    ``(date, structure)``-indexed frame with:

    * the three vols in bp/day, under the neutral names ``curve_bp_day`` /
      ``swaption_bp_day`` / ``listed_bp_day``;
    * ``basis_bp_day`` = swaption - listed, positive when the OTC market prices
      more vol than the exchange;
    * the rank of each source (1 = cheapest) and ``cheapest_source`` /
      ``richest_source`` as labels;
    * the two curve-vs-vol signals and every gate in :data:`GATE_MODES`;
    * ``usable``, True only where all three vols are present -- the three-way
      intersection, and the only rows any three-way statistic may use.

    Rows outside ``cfg.structures`` are dropped, so a panel that also carries
    long-end structures cannot leak a sector-mismatched comparison into the
    tables.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    df = panel.copy()
    if not isinstance(df.index, pd.RangeIndex) and "date" not in df.columns:
        df = df.reset_index()
    if "date" not in df.columns or "structure" not in df.columns:
        raise KeyError("panel must carry 'date' and 'structure' columns "
                       f"(found {list(df.columns)[:10]})")
    for c in (cfg.curve_col, cfg.swaption_col, cfg.listed_col):
        if c not in df.columns:
            raise KeyError(f"panel is missing the vol column {c!r}")

    df["date"] = pd.to_datetime(df["date"])
    keep = set(cfg.labels())
    df = df[df["structure"].isin(keep)]
    df = df[(df["date"] >= pd.Timestamp(cfg.start)) & (df["date"] <= pd.Timestamp(cfg.end))]
    if df.empty:
        raise ValueError("no rows left after restricting to cfg.structures / window")

    out = pd.DataFrame({
        "date": df["date"].to_numpy(),
        "structure": df["structure"].to_numpy(),
        "curve_bp_day": df[cfg.curve_col].to_numpy(dtype=float),
        "swaption_bp_day": df[cfg.swaption_col].to_numpy(dtype=float),
        "listed_bp_day": df[cfg.listed_col].to_numpy(dtype=float),
    })
    for extra in ("breakeven_status", "carry_roll_bp", "convex", "listed_symbol",
                  "listed_gap_days", "listed_tte", "signal_listed", "signal_otc"):
        if extra in df.columns:
            out[f"src_{extra}"] = df[extra].to_numpy()

    c = out["curve_bp_day"].to_numpy(float)
    s = out["swaption_bp_day"].to_numpy(float)
    l = out["listed_bp_day"].to_numpy(float)

    out["basis_bp_day"] = s - l
    out["cheapness_vs_swaption_bp_day"] = s - c
    out["cheapness_vs_listed_bp_day"] = l - c
    #: All three present. The curve may legitimately be +inf (never_cheap), so
    #: this is an isnan test on the curve and an isfinite test on the two
    #: benchmarks -- a benchmark of +inf would be a data error, not a state.
    usable = (~np.isnan(c)) & np.isfinite(s) & np.isfinite(l)
    out["usable"] = usable

    # ------------------------------------------------------------- the ranking
    stack = np.vstack([c, s, l])
    # NaN sorts last, so an unusable row cannot claim to be cheapest. This fill
    # is defensive only and is provably UNREACHABLE in the output: a NaN can only
    # appear where ``usable`` is False, and every rank / label below is masked to
    # NaN / None there. Mutating ``inf`` to ``-inf`` therefore changes nothing,
    # which the mutation log in tests/test_convexity_rv_threeway.py records as a
    # semantically inert mutation rather than an escaped bug. It is kept because
    # relaxing ``usable`` would make it live again, and sorting NaN to the front
    # would then silently crown a missing benchmark the cheapest gamma source.
    filled = np.where(np.isnan(stack), np.inf, stack)
    order = np.argsort(filled, axis=0, kind="stable")
    ranks = np.empty_like(order)
    np.put_along_axis(ranks, order, np.arange(3)[:, None] + 1, axis=0)
    for i, name in enumerate(SOURCES):
        r = ranks[i].astype(float)
        r[~usable] = np.nan
        out[f"rank_{name}"] = r
    cheapest = np.array(SOURCES, dtype=object)[np.argmin(filled, axis=0)]
    richest = np.array(SOURCES, dtype=object)[np.argmax(filled, axis=0)]
    out["cheapest_source"] = np.where(usable, cheapest, None)
    out["richest_source"] = np.where(usable, richest, None)
    out["min_market_bp_day"] = np.minimum(s, l)
    out["max_market_bp_day"] = np.maximum(s, l)

    # ------------------------------------------------------------- the signals
    t, twr = cfg.entry_threshold_bp_per_day, cfg.trade_when_rich
    sig_s = _sig(c, s, threshold=t, trade_when_rich=twr)
    sig_l = _sig(c, l, threshold=t, trade_when_rich=twr)
    if cfg.require_all_three:
        sig_s = np.where(usable, sig_s, 0.0)
        sig_l = np.where(usable, sig_l, 0.0)
    out["signal_swaption"] = sig_s
    out["signal_listed"] = sig_l
    out["signals_agree"] = np.where(usable, sig_s == sig_l, False)

    for mode in GATE_MODES:
        out[f"gate_{mode}"] = gate_direction(sig_s, sig_l, c, s, l, mode=mode,
                                             cfg=cfg, usable=usable)
    out["gate"] = out[f"gate_{cfg.gate_mode}"]
    return out.set_index(["date", "structure"]).sort_index()


def gate_direction(sig_swaption: np.ndarray, sig_listed: np.ndarray,
                   curve: np.ndarray, swaption: np.ndarray, listed: np.ndarray,
                   *, mode: str, cfg: Optional[Strat1ThreeWayConfig] = None,
                   usable: Optional[np.ndarray] = None) -> np.ndarray:
    """One gate's {+1, 0, -1} direction, elementwise.

    ``both`` is a two-sided AND over the two signals; ``cheapest`` is a
    comparison of the curve against the min/max of the two markets. They are the
    same function at the default config (see the module docstring), and are
    written out separately anyway so the identity is a *measured* result of
    :func:`assert_both_equals_cheapest` rather than an artefact of sharing code.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    m = str(mode)
    if m not in GATE_MODES:
        raise ValueError(f"gate mode must be one of {GATE_MODES}, got {mode!r}")
    a = np.asarray(sig_swaption, dtype=float)
    b = np.asarray(sig_listed, dtype=float)
    c = np.asarray(curve, dtype=float)
    s = np.asarray(swaption, dtype=float)
    l = np.asarray(listed, dtype=float)
    t, twr = cfg.entry_threshold_bp_per_day, cfg.trade_when_rich

    if m == "swaption_only":
        g = a.copy()
    elif m == "listed_only":
        g = b.copy()
    elif m == "both":
        g = np.where(a == b, a, 0.0)
    elif m == "cheapest":
        g = _sig(c, np.minimum(s, l), threshold=t, trade_when_rich=False)
        if twr:
            rich = _sig(c, np.maximum(s, l), threshold=t, trade_when_rich=True)
            g = np.where(rich < 0, -1.0, g)
    else:  # "either": long if EITHER market says cheap, short only if BOTH say rich
        g = np.where((a > 0) | (b > 0), 1.0, 0.0)
        if twr:
            g = np.where((a < 0) & (b < 0), -1.0, g)

    if usable is not None and cfg.require_all_three:
        g = np.where(np.asarray(usable, dtype=bool), g, 0.0)
    return g


def gate_columns(three: pd.DataFrame) -> List[str]:
    return [c for c in three.columns if c.startswith("gate_")]


def assert_both_equals_cheapest(three: pd.DataFrame) -> Dict[str, Any]:
    """Prove (or disprove) the ``both`` == ``cheapest`` identity on real rows.

    The two gates are computed by different expressions -- ``both`` is an AND
    over the two per-benchmark signals, ``cheapest`` compares the curve against
    the min and max of the two markets -- so this compares two independent code
    paths rather than restating one. The module docstring argues the identity
    from the inequalities; this measures it, which is the version worth
    printing.

    Returns the count of rows where they differ, which should be zero for every
    configuration. A non-zero count means one of the two paths has a bug.
    """
    a = three["gate_both"].to_numpy(float)
    b = three["gate_cheapest"].to_numpy(float)
    diff = a != b
    return {
        "n_rows": int(len(a)),
        "n_differ": int(diff.sum()),
        "identical": bool(not diff.any()),
        "first_difference": (three.index[np.argmax(diff)] if diff.any() else None),
    }


# ---------------------------------------------------------------- coverage


def intersection_report(three: pd.DataFrame) -> Dict[str, Any]:
    """The three coverages side by side, and the intersection they share.

    Printed first in every report. The point is that the curve runs from 2019
    and the swaption cube from 2015 while the listed panel is two years long, so
    a three-way statistic quoted off anything but the intersection is wrong by
    construction.
    """
    df = three.reset_index()
    c = np.isnan(df["curve_bp_day"].to_numpy(float))
    s = np.isfinite(df["swaption_bp_day"].to_numpy(float))
    l = np.isfinite(df["listed_bp_day"].to_numpy(float))
    u = df["usable"].to_numpy(bool)
    d = df["date"]
    return {
        "n_rows": int(len(df)),
        "n_dates": int(d.nunique()),
        "window": (str(d.min().date()), str(d.max().date())),
        "n_structures": int(df["structure"].nunique()),
        "rows_curve_ok": int((~c).sum()),
        "rows_swaption_ok": int(s.sum()),
        "rows_listed_ok": int(l.sum()),
        "rows_all_three": int(u.sum()),
        "dates_all_three": int(d[u].nunique()),
        "intersection_window": (str(d[u].min().date()), str(d[u].max().date())),
        "frac_rows_usable": float(u.mean()) if len(u) else float("nan"),
    }


# ----------------------------------------------------------------- ranking


def rank_table(three: pd.DataFrame) -> pd.DataFrame:
    """How often each source is the cheapest gamma, per structure and pooled.

    This is the direct answer to "cheapest wins" -- and the reason a single
    winner is uninteresting is visible in the spread of these fractions across
    structures.
    """
    df = three.reset_index()
    df = df[df["usable"].to_numpy(bool)]
    rows: List[Dict[str, Any]] = []

    def _one(label: str, g: pd.DataFrame) -> Dict[str, Any]:
        n = int(len(g))
        r: Dict[str, Any] = {"structure": label, "n_days": n}
        for name in SOURCES:
            r[f"frac_cheapest_{name}"] = float((g["cheapest_source"] == name).mean()) if n else np.nan
            r[f"frac_richest_{name}"] = float((g["richest_source"] == name).mean()) if n else np.nan
        for name, col in zip(SOURCES, ("curve_bp_day", "swaption_bp_day", "listed_bp_day")):
            v = g[col].to_numpy(float)
            r[f"median_{name}_bp_day"] = float(np.nanmedian(v[np.isfinite(v)])) if np.isfinite(v).any() else np.nan
        r["frac_curve_inf"] = float(np.isposinf(g["curve_bp_day"].to_numpy(float)).mean()) if n else np.nan
        r["frac_curve_zero"] = float((g["curve_bp_day"].to_numpy(float) == 0.0).mean()) if n else np.nan
        return r

    for label, g in df.groupby("structure", sort=True):
        rows.append(_one(label, g))
    rows.append(_one("POOLED", df))
    return pd.DataFrame(rows)


def transition_table(three: pd.DataFrame) -> pd.DataFrame:
    """How often the cheapest source CHANGES from one day to the next.

    A ranking that never moves is a ranking with no information in it; one that
    moves every day is noise. Per structure: the fraction of consecutive
    observed days on which ``cheapest_source`` differs, and the mean run length
    of a single regime.
    """
    df = three.reset_index()
    df = df[df["usable"].to_numpy(bool)].sort_values(["structure", "date"])
    rows: List[Dict[str, Any]] = []
    for label, g in df.groupby("structure", sort=True):
        v = g["cheapest_source"].to_numpy(object)
        if len(v) < 2:
            rows.append({"structure": label, "n_days": int(len(v)),
                         "frac_days_ranking_changes": np.nan, "n_regimes": np.nan,
                         "mean_regime_len_days": np.nan})
            continue
        chg = v[1:] != v[:-1]
        n_reg = int(chg.sum()) + 1
        rows.append({
            "structure": label,
            "n_days": int(len(v)),
            "frac_days_ranking_changes": float(chg.mean()),
            "n_regimes": n_reg,
            "mean_regime_len_days": float(len(v) / n_reg),
        })
    return pd.DataFrame(rows)


def agreement_table(three: pd.DataFrame) -> pd.DataFrame:
    """Do the curve-vs-swaption and curve-vs-listed signals ever DISAGREE?

    The whole "is this a relabelling of strategy 1" question, as a number. One
    row per structure plus a pooled row, with the 2x2 confusion counts of
    ``(signal_swaption, signal_listed)`` and the fraction of rows on which the
    two benchmarks give a different verdict.

    ``frac_gate_differs_from_swaption`` is the operational version: how often the
    ``both`` gate would have done something different from ``swaption_only``.
    That is the number that decides whether the listed leg is worth carrying.
    """
    df = three.reset_index()
    df = df[df["usable"].to_numpy(bool)]
    rows: List[Dict[str, Any]] = []

    def _one(label: str, g: pd.DataFrame) -> Dict[str, Any]:
        n = int(len(g))
        a = g["signal_swaption"].to_numpy(float)
        b = g["signal_listed"].to_numpy(float)
        gb = g["gate_both"].to_numpy(float)
        basis = g["basis_bp_day"].to_numpy(float)
        return {
            "structure": label,
            "n_days": n,
            "frac_disagree": float((a != b).mean()) if n else np.nan,
            "n_disagree": int((a != b).sum()),
            "frac_both_cheap": float(((a > 0) & (b > 0)).mean()) if n else np.nan,
            "frac_both_rich": float(((a < 0) & (b < 0)).mean()) if n else np.nan,
            "frac_swaption_cheap_listed_rich": float(((a > 0) & (b < 0)).mean()) if n else np.nan,
            "frac_swaption_rich_listed_cheap": float(((a < 0) & (b > 0)).mean()) if n else np.nan,
            "frac_gate_differs_from_swaption": float((gb != a).mean()) if n else np.nan,
            "frac_gate_differs_from_listed": float((gb != b).mean()) if n else np.nan,
            "median_basis_bp_day": float(np.nanmedian(basis)) if n else np.nan,
            #: How big the basis would have to be to flip a quarter of days: the
            #: 75th percentile of |curve - swaption|. If the observed basis is
            #: far below this, the two benchmarks CANNOT often disagree, and the
            #: low disagreement rate is arithmetic rather than evidence that the
            #: two markets agree about vol.
            "basis_needed_to_flip_25pct_bp_day": float(np.nanpercentile(
                np.abs(g["cheapness_vs_swaption_bp_day"].to_numpy(float)), 25)) if n else np.nan,
        }

    for label, g in df.groupby("structure", sort=True):
        rows.append(_one(label, g))
    rows.append(_one("POOLED", df))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- the basis


def basis_frame(panel: pd.DataFrame, cfg: Optional[Strat1ThreeWayConfig] = None
                ) -> pd.DataFrame:
    """The swaption-minus-listed ATM vol basis as its own daily series.

    This is a **real traded spread** -- sell OTC gamma, buy listed gamma -- and
    it is the only part of this study that does not depend on the curve at all.
    The benchmark columns are identical across structures on a given date, so
    the panel collapses to one row per date.

    Adds, all descriptive and none of it traded on here:

    ``basis_pct_of_listed``
        the basis as a fraction of the listed level, which is the unit a vol
        trader would actually quote it in.
    ``basis_pctile_roll``
        rolling percentile over ``cfg.basis_window`` business days -- the
        "is this wide or tight" reading.
    ``basis_pctile_full`` / ``basis_z_full``
        full-sample percentile and z-score. Full-sample, so **look-ahead by
        construction**: fine for describing the distribution, useless as a
        signal, and named so that cannot be forgotten.
    ``basis_bucket``
        ``cfg.basis_quantiles`` full-sample quantile buckets, used by
        :func:`conditional_basis_table`.

    **Raises on a long-end panel.** The collapse to one row per date is only
    valid when the benchmark columns do not depend on the structure -- true of
    the SFR panel (one horizon-matched contract per date, shared by all five
    structures) and false of the UST one, where the primary root is UL for
    30Y/50Y and US for 5Y/30Y. Silently keeping whichever structure sorted first
    and calling it "the basis" is the exact error this guard exists to prevent;
    use :func:`longend_basis_frame` instead.

    The guard tests that precondition directly -- "does any single date carry two
    different listed vols?" -- rather than sniffing a column name, because
    ``listed_symbol`` legitimately varies ACROSS dates in the SFR panel as the
    matched contract rolls, and a test on its cardinality would reject the panel
    this function was written for.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    df = panel.copy()
    if "date" not in df.columns:
        df = df.reset_index()
    if cfg.listed_col in df.columns:
        per_date = df.groupby("date")[cfg.listed_col].nunique(dropna=True)
        if (per_date > 1).any():
            bad = per_date[per_date > 1]
            raise ValueError(
                f"basis_frame() collapses to one row per date, but {len(bad)} dates "
                f"carry more than one {cfg.listed_col!r} (e.g. {bad.index[0].date()} "
                f"has {int(bad.iloc[0])}). That means the benchmark depends on the "
                "structure -- a long-end panel. Use longend_basis_frame(), which "
                "keys on (date, listed_symbol).")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(cfg.start)) & (df["date"] <= pd.Timestamp(cfg.end))]

    cols = {cfg.swaption_col: "swaption_bp_day", cfg.listed_col: "listed_bp_day"}
    keep = ["date"] + [c for c in cols if c in df.columns]
    extra = [c for c in ("listed_symbol", "listed_expiry", "listed_tte", "listed_gap_days",
                         "listed_atm_bp_yr", "otc_atmf_bp_yr") if c in df.columns]
    out = (df[keep + extra].drop_duplicates(subset=["date"])
             .rename(columns=cols).set_index("date").sort_index())

    s = out["swaption_bp_day"].to_numpy(float)
    l = out["listed_bp_day"].to_numpy(float)
    out["basis_bp_day"] = s - l
    with np.errstate(invalid="ignore", divide="ignore"):
        out["basis_pct_of_listed"] = np.where(l > 0, (s - l) / l, np.nan)
    b = out["basis_bp_day"]
    out["basis_pctile_roll"] = b.rolling(cfg.basis_window, min_periods=max(10, cfg.basis_window // 3)) \
                                .rank(pct=True)
    ok = np.isfinite(b.to_numpy(float))
    out["basis_pctile_full"] = b.rank(pct=True)
    mu, sd = np.nanmean(b.to_numpy(float)), np.nanstd(b.to_numpy(float), ddof=1)
    out["basis_z_full"] = (b - mu) / sd if sd > 0 else np.nan
    try:
        out["basis_bucket"] = pd.qcut(b.where(pd.Series(ok, index=b.index)),
                                      cfg.basis_quantiles, labels=False, duplicates="drop")
    except ValueError:                                    # too few distinct values
        out["basis_bucket"] = np.nan
    return out


def basis_summary(basis: pd.DataFrame) -> pd.DataFrame:
    """Distribution of the basis, overall and by calendar quarter.

    Quarterly because the measured series is not stationary over the sample --
    it is wide early and closes later -- and a single median would hide that.
    """
    b = basis["basis_bp_day"]
    rows: List[Dict[str, Any]] = []

    def _one(label: str, x: pd.Series, lv: pd.Series) -> Dict[str, Any]:
        v = x.to_numpy(float)
        v = v[np.isfinite(v)]
        lvv = lv.to_numpy(float)
        lvv = lvv[np.isfinite(lvv)]
        if not len(v):
            return {"period": label, "n": 0}
        return {
            "period": label, "n": int(len(v)),
            "mean_bp_day": float(v.mean()), "median_bp_day": float(np.median(v)),
            "std_bp_day": float(v.std(ddof=1)) if len(v) > 1 else np.nan,
            "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
            "min": float(v.min()), "max": float(v.max()),
            "frac_positive": float((v > 0).mean()),
            "median_pct_of_listed": (float(np.median(v) / np.median(lvv))
                                     if len(lvv) and np.median(lvv) else np.nan),
        }

    rows.append(_one("FULL", b, basis["listed_bp_day"]))
    q = basis.index.to_period("Q")
    for p in sorted(set(q)):
        m = q == p
        rows.append(_one(str(p), b[m], basis["listed_bp_day"][m]))
    return pd.DataFrame(rows)


# ------------------------------------------------------------- gate -> cohorts


def unit_cohort_table(cohorts: pd.DataFrame, *,
                      cfg: Optional[Strat1ThreeWayConfig] = None) -> pd.DataFrame:
    """Convert a STORED cohort table into pure-flattener ("unit") P&L.

    The stored runs traded a mixed book. Because swap NPV is linear in ``bpv``
    and the two legs are opened at ``+dv01*s`` / ``-dv01*s``, the same cohort
    held as a flattener has P&L ``direction * gross_pnl_bp`` exactly. That claim
    is verified against a fresh engine run by
    ``_strat1_threeway_build.py verify``; it is not assumed here.

    Returns the cohort table with ``unit_gross_bp`` added. Live cohorts keep
    NaN P&L and are carried, not dropped -- on a two-year sample with a one-year
    hold they are about half the book, which is a fact about the sample that
    deleting them would hide.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    t = cohorts.copy()
    for c in ("entry", "direction", "gross_pnl_bp", "closed"):
        if c not in t.columns:
            raise KeyError(f"cohort table is missing {c!r}")
    t["entry"] = pd.to_datetime(t["entry"])
    if "exit" in t.columns:
        t["exit"] = pd.to_datetime(t["exit"])
    d = t["direction"].to_numpy(float)
    bad = np.isfinite(d) & (np.abs(np.abs(d) - 1.0) > 1e-12)
    if bad.any():
        raise ValueError("stored cohort directions must be +/-1 for the linearity "
                         f"identity to apply; found {sorted(set(d[bad]))[:5]}")
    t["unit_gross_bp"] = d * t["gross_pnl_bp"].to_numpy(float)
    return t


def apply_gate(cohorts: pd.DataFrame, direction: pd.Series, *,
               cfg: Optional[Strat1ThreeWayConfig] = None,
               lag_days: Optional[int] = None) -> pd.DataFrame:
    """Score a stored cohort table under a different gate.

    ``direction``
        a date-indexed series of {+1, 0, -1} for ONE structure, on the daily
        panel grid and **not yet lagged** -- the lag is applied here so every
        gate mode gets the identical treatment the stored runs got
        (``shift(1)``: signal off day t's close, cohort fills at t+1).

    Cohorts whose gated direction is 0 are marked ``traded = False`` and carry
    zero P&L and zero cost -- standing aside is free, and charging it would
    flatter the gates that trade less.

    **Known answer**: passing the stored run's own direction back in must
    reproduce the stored ``net_pnl_bp`` exactly. The test suite and the notebook
    both pin that, and it is the single check that makes every gate-mode number
    in this study trustworthy.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    lag = cfg.signal_lag_days if lag_days is None else int(lag_days)
    t = unit_cohort_table(cohorts, cfg=cfg)

    sig = pd.Series(direction).copy()
    sig.index = pd.to_datetime(sig.index)
    sig = sig.sort_index()
    if lag:
        sig = sig.shift(lag)
    sig = sig.fillna(0.0)

    g = sig.reindex(t["entry"]).to_numpy(float)
    g = np.where(np.isfinite(g), g, 0.0)
    t["gate_direction"] = g
    t["traded"] = g != 0.0

    unit = t["unit_gross_bp"].to_numpy(float)
    gross = g * unit
    cost = np.where(t["traded"].to_numpy(bool), 2.0 * float(cfg.cost_bp_one_way), 0.0)
    closed = t["closed"].to_numpy(bool) & t["traded"].to_numpy(bool)
    t["gate_gross_bp"] = np.where(t["traded"].to_numpy(bool), gross, 0.0)
    t["gate_cost_bp"] = cost
    t["gate_net_bp"] = np.where(closed, t["gate_gross_bp"].to_numpy(float) - cost, np.nan)
    t["gate_closed"] = closed
    return t


def all_gate_books(three: pd.DataFrame, cohorts: Mapping[str, pd.DataFrame],
                   cfg: Optional[Strat1ThreeWayConfig] = None,
                   modes: Sequence[str] = GATE_MODES) -> pd.DataFrame:
    """Every gate mode x every structure, scored on identical cohort P&L.

    The point of doing it this way rather than with one engine run per mode: the
    cohorts, their entries, their exits and their unit P&L are *bit-identical*
    across modes, so any difference between two gate curves is the gate and
    nothing else.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    frames: List[pd.DataFrame] = []
    for label in cfg.labels():
        if label not in cohorts:
            continue
        sub = three.xs(label, level="structure")
        for mode in modes:
            col = f"gate_{mode}"
            if col not in sub.columns:
                raise KeyError(f"three-way frame has no {col!r}")
            b = apply_gate(cohorts[label], sub[col], cfg=cfg)
            b["gate_mode"] = mode
            b["structure"] = label
            frames.append(b)
    if not frames:
        raise ValueError("no cohort tables matched cfg.structures")
    return pd.concat(frames, ignore_index=True)


def gate_summary(books: pd.DataFrame, cfg: Optional[Strat1ThreeWayConfig] = None,
                 *, by_structure: bool = False) -> pd.DataFrame:
    """Per-gate-mode P&L summary. **Illustration, not evidence** -- see below.

    Every row carries ``n_eff_independent`` next to ``n_closed`` for exactly one
    reason: the cohorts are weekly-opened one-year holds, so ~50 "trades" are
    about **two** independent observations. The t-statistic is computed on the
    nominal count and is therefore an UPPER bound on the evidence; the
    overlap-adjusted t divides it by ``sqrt(n_closed / n_eff)``.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    keys = ["gate_mode"] + (["structure"] if by_structure else [])
    rows: List[Dict[str, Any]] = []
    for k, g in books.groupby(keys, sort=True):
        c = g[g["gate_closed"].to_numpy(bool)]
        p = c["gate_net_bp"].to_numpy(float)
        p = p[np.isfinite(p)]
        n = len(p)
        sd = float(p.std(ddof=1)) if n > 1 else np.nan
        sr = float(p.mean() / sd) if n > 1 and sd > 0 else np.nan
        n_eff = effective_independent_n(c["entry"], c["exit"], cfg.horizon_years)
        tstat = float(p.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else np.nan
        row: Dict[str, Any] = dict(zip(keys, k if isinstance(k, tuple) else (k,)))
        row.update({
            "n_cohorts": int(len(g)),
            "n_traded": int(g["traded"].sum()),
            "frac_traded": float(g["traded"].mean()) if len(g) else np.nan,
            "frac_flattener": (float((g.loc[g["traded"], "gate_direction"] > 0).mean())
                               if g["traded"].any() else np.nan),
            "n_closed": n,
            "n_eff_independent": n_eff,
            "net_bp_total": float(p.sum()) if n else np.nan,
            "net_bp_mean": float(p.mean()) if n else np.nan,
            "net_bp_median": float(np.median(p)) if n else np.nan,
            "net_bp_std": sd,
            "hit_rate": float((p > 0).mean()) if n else np.nan,
            "sharpe_per_trade": sr,
            "t_stat_nominal": tstat,
            "t_stat_overlap_adj": (tstat / math.sqrt(n / n_eff)
                                   if np.isfinite(tstat) and n_eff and n_eff > 0 else np.nan),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def conditional_basis_table(books: pd.DataFrame, basis: pd.DataFrame,
                            cfg: Optional[Strat1ThreeWayConfig] = None,
                            *, mode: str = "both") -> pd.DataFrame:
    """Cohort outcomes bucketed by the OTC-minus-listed basis at ENTRY.

    Question (b)'s operational half: does the level of the basis condition
    whether sourcing gamma from the curve worked? At this sample size the answer
    is a description of ~50 overlapping cohorts spread across five buckets, i.e.
    ~10 highly-correlated observations each, and the table is labelled that way.
    It is here because the question deserves a measurement rather than a shrug,
    not because the measurement is conclusive.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    b = books[(books["gate_mode"] == mode) & books["gate_closed"].to_numpy(bool)].copy()
    if b.empty:
        return pd.DataFrame()
    bs = basis.copy()
    bs.index = pd.to_datetime(bs.index)
    b["entry"] = pd.to_datetime(b["entry"])
    b["basis_at_entry"] = bs["basis_bp_day"].reindex(b["entry"]).to_numpy(float)
    b["basis_bucket"] = bs["basis_bucket"].reindex(b["entry"]).to_numpy(float)

    rows: List[Dict[str, Any]] = []
    for bucket, g in b.groupby("basis_bucket", sort=True, dropna=True):
        p = g["gate_net_bp"].to_numpy(float)
        p = p[np.isfinite(p)]
        rows.append({
            "basis_bucket": int(bucket),
            "n_cohorts": int(len(p)),
            "basis_lo_bp_day": float(np.nanmin(g["basis_at_entry"])),
            "basis_hi_bp_day": float(np.nanmax(g["basis_at_entry"])),
            "basis_median_bp_day": float(np.nanmedian(g["basis_at_entry"])),
            "net_bp_mean": float(p.mean()) if len(p) else np.nan,
            "net_bp_median": float(np.median(p)) if len(p) else np.nan,
            "hit_rate": float((p > 0).mean()) if len(p) else np.nan,
            "frac_flattener": float((g["gate_direction"] > 0).mean()),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------- sample-size arithmetic


def effective_independent_n(entries: Sequence[Any], exits: Sequence[Any],
                            horizon_years: float = 1.0) -> float:
    """Non-overlapping observations a set of overlapping cohorts really contains.

    Weekly cohorts held one year share ~98% of their holding windows. The count
    of cohorts is therefore not the count of observations, and every statistic
    that divides by ``sqrt(n)`` is inflated by ``sqrt(n / n_eff)``.

    Measured as calendar span covered divided by the holding period -- the
    number of independent one-year windows the sample physically contains.

    Applied to a POOLED set (several structures at once) this deliberately
    credits **no** cross-sectional diversification, and that is the right call
    here rather than laziness: the five SFR flatteners are overlapping segments
    of the same front-end curve and their measured pairwise cohort-P&L
    correlation is **0.70 on average, up to 0.996** (2Yx2Y/3Yx2Y against
    2Yx3Y/3Yx3Y). Five structures at that correlation are worth ~1.4
    independent ones, so pooling 270 cohort-rows still buys ~2-3 observations,
    not 270.
    """
    e = pd.to_datetime(pd.Series(list(entries)).dropna())
    x = pd.to_datetime(pd.Series(list(exits)).dropna())
    if e.empty or x.empty or horizon_years <= 0:
        return float("nan")
    span_days = (x.max() - e.min()).days
    if span_days <= 0:
        return float("nan")
    return max(1.0, float(span_days / 365.25 / float(horizon_years)))


def expected_max_sharpe_under_null(n_trials: int, n_obs: Optional[int] = None,
                                   *, sr_std: Optional[float] = None) -> float:
    """E[max Sharpe] across ``n_trials`` strategies that all have zero edge.

    Bailey & Lopez de Prado's expected maximum of ``N`` independent draws::

        E[max] ~= sigma * [ (1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e)) ]

    with ``g`` the Euler-Mascheroni constant. ``sigma`` defaults to the standard
    error of a per-observation Sharpe under the null, ``1/sqrt(n_obs)``.

    This is the number a comparison of several gate modes has to clear before
    "the best one" means anything -- and with ``n_obs`` set to the *effective*
    independent count rather than the cohort count, it is usually larger than
    any of the Sharpes on offer.
    """
    N = int(n_trials)
    if N < 1:
        return float("nan")
    if sr_std is None:
        if not n_obs or n_obs <= 0:
            return float("nan")
        sr_std = 1.0 / math.sqrt(float(n_obs))
    if N == 1:
        return 0.0
    from scipy.stats import norm

    g = 0.5772156649015329
    z1 = float(norm.ppf(1.0 - 1.0 / N))
    z2 = float(norm.ppf(1.0 - 1.0 / (N * math.e)))
    return float(sr_std * ((1.0 - g) * z1 + g * z2))


def deflated_sharpe_ratio(sr: float, n_obs: int, *, sr_benchmark: float = 0.0,
                          skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """Probability the observed Sharpe beats ``sr_benchmark`` given the sample.

    Bailey & Lopez de Prado (2014). ``sr`` and ``sr_benchmark`` are
    PER-OBSERVATION Sharpes, not annualised -- mixing the two units is the usual
    way this statistic gets misreported by an order of magnitude.

    Pair it with :func:`expected_max_sharpe_under_null` as the benchmark: that
    is what turns "the best of five gates has Sharpe 0.3" into a probability.
    """
    n = int(n_obs)
    if n < 2 or not np.isfinite(sr):
        return float("nan")
    from scipy.stats import norm

    denom = 1.0 - float(skew) * float(sr) + (float(kurtosis) - 1.0) / 4.0 * float(sr) ** 2
    if denom <= 0:
        return float("nan")
    z = (float(sr) - float(sr_benchmark)) * math.sqrt(n - 1) / math.sqrt(denom)
    return float(norm.cdf(z))


# ------------------------------------------------------------------- verdict


def threeway_verdict(three: pd.DataFrame, basis: pd.DataFrame,
                     books: Optional[pd.DataFrame] = None,
                     cfg: Optional[Strat1ThreeWayConfig] = None) -> Dict[str, Any]:
    """Everything the report has to state, as one JSON-able dict.

    Deliberately leads with coverage and the signal statistics, and puts the
    P&L last and labelled -- in that order because that is the order of
    evidential weight in a two-year sample.
    """
    cfg = cfg or Strat1ThreeWayConfig()
    cov = intersection_report(three)
    ranks = rank_table(three)
    agree = agreement_table(three)
    bsum = basis_summary(basis)
    pooled_agree = agree[agree["structure"] == "POOLED"].iloc[0].to_dict()
    pooled_rank = ranks[ranks["structure"] == "POOLED"].iloc[0].to_dict()
    full = bsum[bsum["period"] == "FULL"].iloc[0].to_dict()

    out: Dict[str, Any] = {
        "coverage": cov,
        "identity_both_equals_cheapest": assert_both_equals_cheapest(three),
        "pooled_ranking": {k: v for k, v in pooled_rank.items()
                           if k.startswith(("frac_", "median_", "n_"))},
        "pooled_agreement": {k: v for k, v in pooled_agree.items()
                             if k.startswith(("frac_", "n_", "median_", "basis_"))},
        "basis_full_sample": full,
        "transitions": transition_table(three).to_dict("records"),
        "n_distinct_gate_modes": len(DISTINCT_GATE_MODES),
    }

    # ------------------------------------------------------------------------
    # "Does the listed benchmark add information over the swaption?" -- reported
    # as THREE fields, not one boolean, because the one-boolean version is
    # actively misleading here. The two signals DO disagree sometimes
    # (frac_disagree > 0), so a bare "adds_information: true" would be literally
    # true and substantively the opposite of the finding: the disagreement rate
    # is 1.6% and the basis is an order of magnitude too small to move it.
    # A consumer reading only the JSON must get the same headline as a reader of
    # the notebook, so the material question is answered separately from the
    # existence question, with the supporting numbers alongside.
    disagree = float(pooled_agree["frac_disagree"])
    need = float(pooled_agree["basis_needed_to_flip_25pct_bp_day"])
    obs = float(np.nanmedian(np.abs(basis["basis_bp_day"].to_numpy(float))))
    out["listed_information"] = {
        "signals_ever_disagree": bool(disagree > 0.0),
        "frac_rows_disagree": disagree,
        "n_rows_disagree": int(pooled_agree["n_disagree"]),
        "median_abs_basis_bp_day": obs,
        "basis_needed_to_flip_25pct_bp_day": need,
        "basis_shortfall_multiple": (need / obs) if obs > 0 else float("nan"),
        #: The headline. True only if the listed benchmark changes the verdict
        #: often enough to matter, which is the question anyone actually has.
        "listed_materially_changes_verdict": bool(disagree >= 0.05),
        "verdict": (
            f"On this sample and in this sector the listed benchmark adds "
            f"essentially NO information over the sector-matched swaption: the "
            f"two signals disagree on {disagree:.2%} of rows "
            f"({int(pooled_agree['n_disagree'])} of {int(pooled_agree['n_days'])}). "
            f"That is arithmetic rather than agreement between the two markets -- "
            f"the median |OTC-listed basis| is {obs:.3f} bp/day while flipping a "
            f"quarter of days would need {need:.3f} bp/day, a factor of "
            f"{(need / obs) if obs > 0 else float('nan'):.0f}."
        ),
    }

    if books is not None and len(books):
        gs = gate_summary(books, cfg)
        out["gate_summary"] = gs.to_dict("records")
        n_eff = float(np.nanmax(gs["n_eff_independent"].to_numpy(float)))
        out["expected_max_sharpe_under_null_nominal"] = expected_max_sharpe_under_null(
            len(DISTINCT_GATE_MODES), int(np.nanmax(gs["n_closed"].to_numpy(float))))
        out["expected_max_sharpe_under_null_effective"] = expected_max_sharpe_under_null(
            len(DISTINCT_GATE_MODES), max(2, int(round(n_eff))))
        best = gs.iloc[int(np.nanargmax(gs["sharpe_per_trade"].to_numpy(float)))]
        out["best_gate_mode"] = str(best["gate_mode"])
        out["best_gate_sharpe_per_trade"] = float(best["sharpe_per_trade"])
        out["best_gate_beats_null"] = bool(
            float(best["sharpe_per_trade"]) > out["expected_max_sharpe_under_null_effective"])
        out["best_gate_deflated_sharpe"] = deflated_sharpe_ratio(
            float(best["sharpe_per_trade"]), max(2, int(round(n_eff))),
            sr_benchmark=out["expected_max_sharpe_under_null_effective"])

        # The operational half of "does listed add information": what did adding
        # the listed veto to the swaption signal actually do to the outcome?
        g = gs.set_index("gate_mode")
        if {"both", "swaption_only"} <= set(g.index):
            d = float(g.loc["both", "net_bp_mean"]) - float(g.loc["swaption_only", "net_bp_mean"])
            stood_aside = int(g.loc["swaption_only", "n_traded"]) - int(g.loc["both", "n_traded"])
            out["listed_information"].update({
                "gate_both_minus_swaption_only_bp_per_cohort": d,
                "cohorts_the_listed_veto_stood_aside_on": stood_aside,
                "cohorts_total": int(g.loc["swaption_only", "n_cohorts"]),
            })
            out["listed_information"]["verdict"] += (
                f" Operationally the listed veto stood aside on {stood_aside} of "
                f"{int(g.loc['swaption_only', 'n_cohorts'])} cohorts and moved the "
                f"mean outcome by {d:+.3f} bp per cohort."
            )
    return out


# =============================================================================
#  UST LONG-END MODE
#
#  Everything below is additive. No function above changes behaviour, and the
#  SFR study's defaults, gates and outputs are untouched -- the long-end mode is
#  reached by passing a different config and a benchmark-selected panel into the
#  SAME machinery.
# =============================================================================

#: Strategy 1's own long-end universe, imported rather than restated so a change
#: to the universe cannot leave the two modules disagreeing about what "30Y/50Y"
#: means.
LONGEND_STRUCTURES: Tuple[Tuple[str, str, str], ...] = LONG_END_STRUCTURES

#: Benchmark roles present in the long-end panel. ``control`` is a deliberately
#: WRONG-sector root (TY, CTD 6.8 years) and is carried on every structure so a
#: comparison that fails to discriminate by sector is visible rather than
#: assumed away.
LONGEND_ROLES: Tuple[str, ...] = ("primary", "alt", "control")

#: Constant maturities, calendar days. 180 exists in the harvest plan and is
#: empty for every root, so it is not offered.
LONGEND_CM_DAYS: Tuple[int, ...] = (30, 60, 90)

#: The PRE-SPECIFIED headline benchmark. ``primary`` is fixed per structure by
#: ``listed_vol.UST_SECTOR_MAP``, which was set from the measured CTD maturity of
#: each contract before any three-way statistic existed; 30 days is the shortest
#: and best-populated constant maturity. Fixing these two here, in the module
#: rather than in a notebook cell, is what stops the headline being the best of
#: twelve after the fact.
HEADLINE_ROLE: str = "primary"
HEADLINE_CM_DAYS: int = 30

#: The SFR study's published result, carried so the long-end retest is
#: like-for-like and the comparison cannot drift. Every field is copied from
#: ``notebooks/data/convexity_rv/strat1_threeway_verdict.json``, not recomputed.
SHORT_END_REFERENCE: Dict[str, Any] = {
    "study": "SFR / short end, strat1_threeway_backtest.ipynb",
    "n_dates_intersection": 517,
    "n_rows_usable": 2585,
    "window": ("2024-07-01", "2026-07-28"),
    "median_abs_basis_bp_day": 0.2714825093089992,
    "basis_needed_to_flip_25pct_bp_day": 2.7206168562235313,
    "basis_shortfall_multiple": 10.021333835274623,
    "frac_rows_disagree": 0.01586073500967118,
    "n_eff_per_structure": 2.053388,
    "mean_pairwise_cohort_r": 0.70,
    "verdict": "listed adds essentially no information over the sector-matched swaption",
}


def longend_config(**overrides: Any) -> Strat1ThreeWayConfig:
    """The :class:`Strat1ThreeWayConfig` for the UST long-end study.

    Differs from the SFR default in exactly two respects, and in nothing else:

    * ``structures`` -- strategy 1's own long-end four rather than the SFR
      stand-ins;
    * ``start`` / ``end`` -- the full 2019-01-01..2026-08-14 window, because
      neither the curve, the swaption cube nor the constant-maturity listed panel
      truncates it. The SFR mode's 2024-07 start was the listed panel's own span
      and does not apply here.

    ``horizon_years``, ``cost_bp_one_way``, ``package_dv01`` and
    ``signal_lag_days`` are restated at their default values rather than left
    implicit, to make explicit that the long-end cohorts are the SAME one-year
    monthly holds, the same 0.5 bp round-trip and the same one-day signal lag
    strategy 1 ran -- the gate books are derived from strategy 1's own stored
    cohort tables and would be incomparable to them otherwise.

    The three vol COLUMN names are left at their defaults on purpose:
    ``build_longend_listed_panel`` already emits ``breakeven_vol_bp_day``,
    ``otc_atmf_bp_day`` and ``listed_atm_bp_day``, so a benchmark-selected
    long-end panel is accepted by :func:`threeway_frame` with no remapping.
    ``**overrides`` is for diagnostics (a threshold sweep, a single structure);
    the headline run passes none.
    """
    base: Dict[str, Any] = dict(
        structures=LONGEND_STRUCTURES,
        start=datetime.date(2019, 1, 1),
        end=datetime.date(2026, 8, 14),
        horizon_years=1.0,
        cost_bp_one_way=0.5,
        package_dv01=100_000.0,
        signal_lag_days=1,
    )
    base.update(overrides)
    return Strat1ThreeWayConfig(**base)


def select_longend_benchmark(panel: pd.DataFrame, *, role: Optional[str] = HEADLINE_ROLE,
                             root: Optional[str] = None,
                             cm_days: int = HEADLINE_CM_DAYS) -> pd.DataFrame:
    """Collapse the (date, structure, benchmark) long-end panel to ONE benchmark.

    This is the entire adapter between ``strat1_listed``'s long-end panel and
    every function in this module. After it the frame has a unique
    ``(date, structure)`` key and column names that already match
    :class:`Strat1ThreeWayConfig`'s defaults, so :func:`threeway_frame` and
    everything downstream run unmodified.

    ``role``
        ``"primary"`` / ``"alt"`` / ``"control"``. **Selecting by role is
        per-structure**, which is the point: the panel stamps each row with the
        role ``listed_vol.UST_SECTOR_MAP`` assigned it, so ``role="primary"``
        picks UL for 30Y/50Y and US for 5Y/30Y in one call.
    ``root``
        mutually exclusive with ``role``; pins a SINGLE contract across every
        structure. Right for a robustness sweep, wrong for the headline, because
        one root cannot be the sector-matched benchmark for all four structures.
        Any alias (``"ZB"``, ``"WN"``, ...) is folded onto the panel's globex key.
    ``cm_days``
        which constant maturity: 30 / 60 / 90.

    Raises if the selection is empty or fails to produce a unique
    ``(date, structure)`` key. That check is not defensive decoration: a
    duplicated key makes :func:`threeway_frame` rank the same date twice and
    silently double-weight it in every pooled statistic, and nothing downstream
    would notice.
    """
    from RVUtils.ConvexityRV import listed_vol as lv

    if (role is None) == (root is None):
        raise ValueError("pass exactly one of role= or root= "
                         f"(got role={role!r}, root={root!r})")
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    for c in ("date", "structure", "listed_symbol", "listed_role",
              "listed_root", "listed_cm_days"):
        if c not in df.columns:
            raise KeyError(
                f"long-end panel is missing {c!r}; expected the frame written by "
                "strat1_listed.build_longend_listed_panel "
                f"(found {sorted(df.columns)[:8]}...)")
    df["date"] = pd.to_datetime(df["date"])

    if role is not None:
        if str(role) not in LONGEND_ROLES:
            raise ValueError(f"role must be one of {LONGEND_ROLES}, got {role!r}")
        sel = df[df["listed_role"] == str(role)]
        what = f"role={role!r}"
    else:
        r = lv.UST_ROOT_ALIAS.get(str(root).upper(), str(root).upper())
        sel = df[df["listed_root"] == r]
        what = f"root={r!r}"
    sel = sel[sel["listed_cm_days"] == int(cm_days)]
    if sel.empty:
        raise ValueError(f"no long-end rows for {what}, cm_days={cm_days}")

    dup = sel.duplicated(subset=["date", "structure"])
    if dup.any():
        d = sel.loc[dup, ["date", "structure"]].iloc[0]
        n = int((sel["date"].eq(d["date"]) & sel["structure"].eq(d["structure"])).sum())
        raise ValueError(
            f"{what} at cm_days={cm_days} does not give a unique (date, structure) "
            f"key -- e.g. {d['date'].date()} / {d['structure']} appears {n} times. "
            "threeway_frame would rank that date twice.")
    return sel.sort_values(["date", "structure"]).reset_index(drop=True)


def longend_threeway_frames(panel: pd.DataFrame,
                            cfg: Optional[Strat1ThreeWayConfig] = None,
                            *, roles: Sequence[str] = LONGEND_ROLES,
                            cm_days: Sequence[int] = LONGEND_CM_DAYS
                            ) -> Dict[str, pd.DataFrame]:
    """One :func:`threeway_frame` per (role, constant maturity). Robustness, not trials.

    Keyed ``"{role}@{cm}"``. The headline is ``"primary@30"``; the other eleven
    exist so a reader can see whether the answer depends on the contract or on
    the tenor, and :func:`benchmark_sweep_table` summarises them into one table.

    They are **not** additional trials for the multiple-testing correction: all
    twelve score the same four gate modes against a different benchmark, and
    counting them would inflate the trial count twelvefold for no new degree of
    freedom.
    """
    cfg = cfg or longend_config()
    out: Dict[str, pd.DataFrame] = {}
    for role in roles:
        for cm in cm_days:
            try:
                sel = select_longend_benchmark(panel, role=role, cm_days=int(cm))
            except ValueError:
                continue                       # role absent for every structure
            out[f"{role}@{int(cm)}"] = threeway_frame(sel, cfg)
    if not out:
        raise ValueError("no (role, cm_days) combination produced any rows")
    return out


def longend_intersection_report(three: pd.DataFrame) -> Dict[str, Any]:
    """The three-way intersection PER STRUCTURE, plus the common one. Print first.

    :func:`intersection_report` pools, which on the long end hides something that
    matters: the primary root is not the same contract for every structure, and
    the roots have different histories. US and TY run 2019-01-02..2026-08-14, UL
    starts later and has gaps, TN is a 2023 contract. So the intersection is
    **1,854 days for the US-benchmarked structures and 1,614 for the
    UL-benchmarked ones**, and a table that differences a UL row against a US row
    is differencing two different samples.

    ``common_dates`` is the strictest reading -- dates on which ALL structures are
    simultaneously usable. Every per-structure statistic in this module is
    computed on that structure's OWN intersection (which is the right choice: it
    uses all the data each structure has), so ``common_dates`` is reported as the
    floor a cross-structure claim would have to be re-measured on, not as the
    window the tables use. ``pooled`` is what :func:`intersection_report` returns,
    repeated here so all three readings sit together.
    """
    df = three.reset_index()
    u = df["usable"].to_numpy(bool)
    per: List[Dict[str, Any]] = []
    sets: List[set] = []
    for label, g in df.groupby("structure", sort=True):
        m = g["usable"].to_numpy(bool)
        d = g.loc[m, "date"]
        sets.append(set(d))
        per.append({
            "structure": label,
            "n_rows": int(len(g)),
            "n_usable": int(m.sum()),
            "frac_usable": float(m.mean()) if len(g) else float("nan"),
            "first": str(d.min().date()) if len(d) else None,
            "last": str(d.max().date()) if len(d) else None,
            "n_curve_ok": int((~np.isnan(g["curve_bp_day"].to_numpy(float))).sum()),
            "n_swaption_ok": int(np.isfinite(g["swaption_bp_day"].to_numpy(float)).sum()),
            "n_listed_ok": int(np.isfinite(g["listed_bp_day"].to_numpy(float)).sum()),
        })
    common = set.intersection(*sets) if sets else set()
    return {
        "pooled": intersection_report(three),
        "per_structure": per,
        "n_common_dates": int(len(common)),
        "common_window": ((str(min(common).date()), str(max(common).date()))
                          if common else None),
        "note": ("per-structure statistics use each structure's OWN intersection; "
                 "n_common_dates is the floor any cross-structure claim must be "
                 "re-measured on."),
    }


# --------------------------------------------------------- the long-end basis


def longend_basis_frame(panel: pd.DataFrame,
                        cfg: Optional[Strat1ThreeWayConfig] = None) -> pd.DataFrame:
    """The 1Yx30Y-minus-listed vol basis, one series per (root, constant maturity).

    The long-end analogue of :func:`basis_frame`, keyed on
    ``(date, listed_symbol)`` rather than on ``date`` alone -- see the module
    docstring for why collapsing to date here would mislabel one root's basis as
    "the" basis.

    Positive means the OTC 1Yx30Y swaption prices MORE vol than the exchange
    contract. **Measured, it is negative almost everywhere on the long end**
    (median -0.195 bp/day for UL_30, -0.545 for US_30, -0.802 for TY_30), the
    opposite sign to the short end's +0.251 -- and it is the finding this frame
    exists to expose, because it means substituting the exchange benchmark makes
    the curve look CHEAPER still rather than correcting an expensive comparison.

    Percentile and z-score columns are computed WITHIN each symbol, so a symbol
    with a shorter window (TN starts 2023-05) is never ranked against another
    symbol's distribution. All of them are full-sample and therefore look-ahead
    by construction: descriptive only, named so that cannot be forgotten, and
    nothing in this module trades off them.
    """
    cfg = cfg or longend_config()
    df = panel.reset_index() if "date" not in panel.columns else panel.copy()
    need = {"date", "listed_symbol", "otc_atmf_bp_day", "listed_atm_bp_day"}
    missing = need - set(df.columns)
    if missing:
        raise KeyError(f"long-end panel is missing {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(cfg.start)) & (df["date"] <= pd.Timestamp(cfg.end))]

    keep = [c for c in ["date", "listed_symbol", "listed_root", "listed_cm_days",
                        "otc_atmf_bp_day", "listed_atm_bp_day", "listed_swap_point"]
            if c in df.columns]
    # A contract's vol is a property of the CONTRACT, so a (date, listed_symbol)
    # pair must carry one level however many structures reference it. Verified
    # before de-duplicating rather than after: drop_duplicates keeps whichever row
    # happened to sort first, so a panel that violated this would collapse to a
    # plausible-looking series built from an arbitrary structure's rows.
    for col in ("listed_atm_bp_day", "otc_atmf_bp_day"):
        n = df.groupby(["date", "listed_symbol"])[col].nunique(dropna=True)
        if (n > 1).any():
            k = n[n > 1].index[0]
            raise ValueError(
                f"{col} is not unique within (date, listed_symbol): "
                f"{k[1]} on {pd.Timestamp(k[0]).date()} carries {int(n.loc[k])} "
                "distinct values. A contract has one vol per date whatever "
                "references it, so this panel is malformed.")
    out = (df[keep].drop_duplicates(subset=["date", "listed_symbol"])
             .sort_values(["listed_symbol", "date"]).reset_index(drop=True))
    s = out["otc_atmf_bp_day"].to_numpy(float)
    l = out["listed_atm_bp_day"].to_numpy(float)
    out["basis_bp_day"] = s - l
    with np.errstate(invalid="ignore", divide="ignore"):
        out["basis_pct_of_listed"] = np.where(l > 0, (s - l) / l, np.nan)

    g = out.groupby("listed_symbol", sort=False)["basis_bp_day"]
    out["basis_pctile_roll"] = g.transform(
        lambda x: x.rolling(cfg.basis_window,
                            min_periods=max(10, cfg.basis_window // 3)).rank(pct=True))
    out["basis_pctile_full"] = g.transform(lambda x: x.rank(pct=True))
    out["basis_z_full"] = g.transform(
        lambda x: (x - x.mean()) / x.std(ddof=1) if x.std(ddof=1) > 0 else x * np.nan)
    out["basis_bucket"] = g.transform(
        lambda x: pd.qcut(x, cfg.basis_quantiles, labels=False, duplicates="drop"))
    return out


def basis_persistence(basis: pd.DataFrame, *,
                      lags: Sequence[int] = (1, 5, 21, 63, 126)) -> pd.DataFrame:
    """Is the long-end basis a persistent spread, or day-to-day noise?

    One row per ``listed_symbol`` with the level distribution, the
    autocorrelation at each lag, an AR(1) half-life and the SIGN-run statistics.
    Persistence is what decides whether the basis is tradeable at all: a spread
    that mean-reverts in a day is a bid/offer, one that holds for a quarter is a
    position.

    Two persistence readings are reported and they disagree, which is itself the
    information and is why both are here:

    * the **AR(1) half-life** is short -- US_30 9.5 business days, UL_30 9.3,
      TY_30 24.9 -- i.e. a shock decays quickly;
    * the **long-lag autocorrelation** is not zero -- US_30 ``rho_63`` = 0.318,
      TY_30 0.628 -- i.e. there is a slow component an AR(1) cannot see.

    Read with :func:`basis_regime_table`, which shows what the slow component is:
    the basis sits near zero through 2019-2021, collapses to -1.573 bp/day
    (US_30) in the 2022-23 rate-vol shock, and recovers toward zero by 2026.

    ``mean_sign_run_days`` is the average length of a run of one sign, computed
    on the OBSERVED sequence, so a gap in the series joins two runs. The long-end
    series are near-daily (US 1,854 of ~1,900 curve dates), so the distortion is
    small, and ``n`` is carried so it can be judged rather than trusted.
    """
    rows: List[Dict[str, Any]] = []
    for sym, g in basis.groupby("listed_symbol", sort=True):
        b = (g.sort_values("date").set_index("date")["basis_bp_day"]).dropna()
        n = int(len(b))
        rec: Dict[str, Any] = {
            "listed_symbol": sym,
            "listed_root": (g["listed_root"].iloc[0] if "listed_root" in g else None),
            "listed_cm_days": (int(g["listed_cm_days"].iloc[0])
                               if "listed_cm_days" in g else None),
            "n": n,
        }
        if n < 3:
            rows.append(rec)
            continue
        v = b.to_numpy(float)
        a1 = float(b.autocorr(1))
        rec.update({
            "first": str(b.index.min().date()),
            "last": str(b.index.max().date()),
            "mean_bp_day": float(v.mean()),
            "median_bp_day": float(np.median(v)),
            "std_bp_day": float(v.std(ddof=1)),
            "p05": float(np.percentile(v, 5)),
            "p25": float(np.percentile(v, 25)),
            "p75": float(np.percentile(v, 75)),
            "p95": float(np.percentile(v, 95)),
            "min": float(v.min()), "max": float(v.max()),
            "frac_positive": float((v > 0).mean()),
            "median_abs_bp_day": float(np.median(np.abs(v))),
        })
        for k in lags:
            rec[f"rho_{int(k)}"] = (float(b.autocorr(int(k)))
                                    if n > int(k) + 2 else float("nan"))
        rec["ar1_half_life_days"] = (float(math.log(0.5) / math.log(a1))
                                     if 0.0 < a1 < 1.0 else float("nan"))
        sgn = np.sign(v)
        n_runs = int(1 + np.sum(sgn[1:] != sgn[:-1]))
        rec["n_sign_runs"] = n_runs
        rec["mean_sign_run_days"] = float(n / n_runs)
        rows.append(rec)
    return pd.DataFrame(rows)


def basis_regime_table(basis: pd.DataFrame, *, by: str = "year",
                       symbols: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """The basis bucketed by calendar regime -- the slow component, made visible.

    ``by`` is ``"year"`` or ``"quarter"``. One row per (symbol, period) with the
    count, median, mean, dispersion and the fraction of days the OTC side priced
    the richer vol.

    This is where the long-end basis stops looking like a constant. Measured on
    US_30: medians of -0.055 / -0.150 / -0.257 bp/day through 2019-2021, then
    **-1.573 (2022)** and **-1.416 (2023)** through the rate-vol shock, then
    -0.700 / -0.439 / -0.107 as it recovers. UL_30 does the same and its SIGN
    flips with the regime: +0.024 (2019), -1.131 (2022), +0.163 (2024), +0.376
    (2026). A single full-sample median would hide all of that, which is why the
    verdict quotes this table next to it.
    """
    df = basis.copy()
    if symbols is not None:
        df = df[df["listed_symbol"].isin(list(symbols))]
    df["date"] = pd.to_datetime(df["date"])
    if by == "year":
        df["period"] = df["date"].dt.year.astype(str)
    elif by == "quarter":
        df["period"] = df["date"].dt.to_period("Q").astype(str)
    else:
        raise ValueError(f"by must be 'year' or 'quarter', got {by!r}")

    rows: List[Dict[str, Any]] = []
    for (sym, per), g in df.groupby(["listed_symbol", "period"], sort=True):
        v = g["basis_bp_day"].to_numpy(float)
        v = v[np.isfinite(v)]
        if not len(v):
            continue
        rows.append({
            "listed_symbol": sym, "period": per, "n": int(len(v)),
            "median_bp_day": float(np.median(v)),
            "mean_bp_day": float(v.mean()),
            "std_bp_day": float(v.std(ddof=1)) if len(v) > 1 else float("nan"),
            "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
            "frac_positive": float((v > 0).mean()),
            "median_listed_bp_day": float(np.nanmedian(
                g["listed_atm_bp_day"].to_numpy(float))),
            "median_otc_bp_day": float(np.nanmedian(
                g["otc_atmf_bp_day"].to_numpy(float))),
        })
    return pd.DataFrame(rows)


def flip_threshold_table(three: pd.DataFrame, *,
                         quantiles: Sequence[int] = (10, 25, 50),
                         include_reference: bool = True) -> pd.DataFrame:
    """**The factor-of-10 retest.** How big would the basis have to be to matter?

    The short-end study concluded that listed added nothing, and the load-bearing
    number was not the disagreement rate itself but the RATIO behind it: the
    median |OTC-listed basis| was 0.271 bp/day while flipping a quarter of days
    would have needed 2.721 -- a factor of 10, so the two benchmarks
    *arithmetically could not* often disagree whatever the two markets believed.
    This recomputes that ratio with the identical formula, so the long end is
    like-for-like rather than merely adjacent.

    Per structure and pooled:

    ``median_abs_basis_bp_day``
        the observed |swaption - listed|.
    ``flip_p{q}_bp_day``
        the q-th percentile of ``|curve - swaption|``: the basis needed to flip
        q% of days. ``flip_p25`` is the short-end study's own statistic, computed
        **by the identical expression** -- ``np.nanpercentile`` over the raw
        absolute gap, with ``never_cheap`` days (gap ``+inf``) INCLUDED. That
        detail is worth a sentence because it changes the answer: 21.8% of
        5Y/30Y days are ``never_cheap``, and dropping them moves the ratio from
        3.45 to 2.40. The ``_finite`` columns report the dropped version beside
        it, but the headline comparison uses the inclusive one, because a retest
        run on a different formula is not a retest.
    ``shortfall_multiple_p{q}``
        ``flip_pq / median_abs_basis``. Large means the basis is arithmetically
        too small to change the verdict; near 1 means it binds.
    ``frac_verdict_saturated``
        the share of days on the MAJORITY verdict -- ``max(frac_cheap,
        frac_rich, frac_flat)`` of the curve-vs-swaption signal. **This is the
        column that says whether a row's ratio means anything**, and it is the
        selector :func:`longend_verdict` uses to pick the binding structure.
        1.0000 on 30Y/50Y, 20Yx5Y/25Yx5Y and 10Yx10Y/20Yx10Y -- the flattener is
        cheap gamma on every single day, so the benchmark cannot change the
        verdict and their large ratios are saturation, not agreement. **0.5140 on
        5Y/30Y**, the only structure where the comparison binds.
    ``frac_curve_at_sentinel``
        diagnostic for WHY a saturated row's threshold is inflated: the share of
        days the breakeven is ``0.0`` (``always_cheap``) or ``+inf``
        (``never_cheap``). With breakeven pinned at 0.0, ``|curve - swaption|``
        degenerates to the swaption level itself (~4-5 bp/day). It is **not** a
        saturation selector and must not be used as one -- measured, it is 0.342
        on 10Yx10Y/20Yx10Y against 0.578 on 5Y/30Y, i.e. it ranks the fully
        saturated structure as the *less* saturated of the two.

    Measured at the headline benchmark, the retest this table exists for:

    =====================  =====  =========  ========  ========  ==========
    structure              n      med basis  flip p25  ratio     saturated
    =====================  =====  =========  ========  ========  ==========
    5Y/30Y                 1,854      0.556     1.917  **3.45**      0.514
    10Yx10Y/20Yx10Y        1,854      0.556     2.936      5.28      1.000
    20Yx5Y/25Yx5Y          1,614      0.424     4.177      9.84      1.000
    30Y/50Y                1,614      0.424     4.243     10.00      1.000
    SFR short end (prior)  2,585      0.271     2.721     10.02      n/a
    =====================  =====  =========  ========  ========  ==========

    Every statistic is on ``usable`` rows only -- the three-way intersection.
    ``include_reference`` appends the stored SFR row so the comparison sits on
    one screen and cannot be made against a half-remembered number.
    """
    df = three.reset_index()
    df = df[df["usable"].to_numpy(bool)]
    rows: List[Dict[str, Any]] = []

    def _one(label: str, g: pd.DataFrame) -> Dict[str, Any]:
        c = g["curve_bp_day"].to_numpy(float)
        basis = np.abs(g["basis_bp_day"].to_numpy(float))
        basis = basis[np.isfinite(basis)]
        # NOT filtered to finite -- see the docstring. This is the short-end
        # study's own expression, and matching it is the whole point.
        gap = np.abs(g["cheapness_vs_swaption_bp_day"].to_numpy(float))
        gap_fin = gap[np.isfinite(gap)]
        mb = float(np.median(basis)) if basis.size else float("nan")
        sig = g["signal_swaption"].to_numpy(float)
        sat = (max(float((sig > 0).mean()), float((sig < 0).mean()),
                   float((sig == 0).mean())) if len(sig) else float("nan"))
        rec: Dict[str, Any] = {
            "structure": label,
            "n_days": int(len(g)),
            "median_abs_basis_bp_day": mb,
            "median_basis_bp_day": float(np.nanmedian(g["basis_bp_day"].to_numpy(float))),
            "n_gap_finite": int(gap_fin.size),
            "frac_gap_infinite": (float((~np.isfinite(gap)).mean())
                                  if gap.size else float("nan")),
            "frac_verdict_saturated": sat,
            "frac_curve_at_sentinel": (float(((c == 0.0) | np.isposinf(c)).mean())
                                       if len(c) else float("nan")),
            "frac_disagree": (float((g["signal_swaption"].to_numpy(float)
                                     != g["signal_listed"].to_numpy(float)).mean())
                              if len(g) else float("nan")),
        }
        for q in quantiles:
            f = float(np.nanpercentile(gap, int(q))) if gap.size else float("nan")
            ff = float(np.percentile(gap_fin, int(q))) if gap_fin.size else float("nan")
            rec[f"flip_p{int(q)}_bp_day"] = f
            rec[f"shortfall_multiple_p{int(q)}"] = ((f / mb) if (mb and mb > 0)
                                                    else float("nan"))
            rec[f"flip_p{int(q)}_finite_bp_day"] = ff
            rec[f"shortfall_multiple_p{int(q)}_finite"] = ((ff / mb) if (mb and mb > 0)
                                                           else float("nan"))
        return rec

    for label, g in df.groupby("structure", sort=True):
        rows.append(_one(label, g))
    rows.append(_one("POOLED", df))
    out = pd.DataFrame(rows)
    if not include_reference:
        return out
    ref = {
        "structure": "[SFR short end, prior study]",
        "n_days": SHORT_END_REFERENCE["n_rows_usable"],
        "median_abs_basis_bp_day": SHORT_END_REFERENCE["median_abs_basis_bp_day"],
        "flip_p25_bp_day": SHORT_END_REFERENCE["basis_needed_to_flip_25pct_bp_day"],
        "shortfall_multiple_p25": SHORT_END_REFERENCE["basis_shortfall_multiple"],
        "frac_disagree": SHORT_END_REFERENCE["frac_rows_disagree"],
    }
    return pd.concat([out, pd.DataFrame([ref])], ignore_index=True)


def benchmark_sweep_table(panel: pd.DataFrame,
                          cfg: Optional[Strat1ThreeWayConfig] = None,
                          *, roles: Sequence[str] = LONGEND_ROLES,
                          cm_days: Sequence[int] = LONGEND_CM_DAYS) -> pd.DataFrame:
    """Every (structure, root, constant maturity) on one page. Robustness.

    One row per (benchmark, structure) with the intersection length and window,
    the ranking, the disagreement rate, the basis and the flip ratio -- so
    "does the answer depend on which contract, or on which tenor?" is answered by
    reading a column rather than by re-running the study.

    ``is_headline`` marks the pre-specified ``primary`` @ 30-day rows. The other
    rows are robustness and are NOT counted as trials in the multiple-testing
    correction: every one of them scores the same four gate modes.

    ``n_days`` differs by root -- US and TY run 2019-01..2026-08, UL starts later
    and TN is a 2023 contract -- so every row carries its own window and no two
    rows may be differenced without checking them first.
    """
    cfg = cfg or longend_config()
    frames = longend_threeway_frames(panel, cfg, roles=roles, cm_days=cm_days)
    meta = panel.reset_index() if "date" not in panel.columns else panel
    rows: List[Dict[str, Any]] = []
    for key, three in frames.items():
        role, cm = key.split("@")
        agree = agreement_table(three).set_index("structure")
        ranks = rank_table(three).set_index("structure")
        flips = flip_threshold_table(three, include_reference=False).set_index("structure")
        trans = transition_table(three).set_index("structure")
        df = three.reset_index()
        df = df[df["usable"].to_numpy(bool)]
        for label, g in df.groupby("structure", sort=True):
            m = meta[(meta["structure"] == label) & (meta["listed_role"] == role)
                     & (meta["listed_cm_days"] == int(cm))]
            rows.append({
                "benchmark": key,
                "listed_role": role,
                "listed_cm_days": int(cm),
                "listed_root": (str(m["listed_root"].iloc[0]) if len(m) else None),
                "listed_symbol": (str(m["listed_symbol"].iloc[0]) if len(m) else None),
                "structure": label,
                "is_headline": bool(role == HEADLINE_ROLE and int(cm) == HEADLINE_CM_DAYS),
                "n_days": int(len(g)),
                "first": str(g["date"].min().date()),
                "last": str(g["date"].max().date()),
                "frac_cheapest_curve": float(ranks.loc[label, "frac_cheapest_curve"]),
                "frac_cheapest_swaption": float(ranks.loc[label, "frac_cheapest_swaption"]),
                "frac_cheapest_listed": float(ranks.loc[label, "frac_cheapest_listed"]),
                "frac_days_ranking_changes": float(trans.loc[label, "frac_days_ranking_changes"]),
                "median_curve_bp_day": float(ranks.loc[label, "median_curve_bp_day"]),
                "median_swaption_bp_day": float(ranks.loc[label, "median_swaption_bp_day"]),
                "median_listed_bp_day": float(ranks.loc[label, "median_listed_bp_day"]),
                "frac_disagree": float(agree.loc[label, "frac_disagree"]),
                "median_basis_bp_day": float(flips.loc[label, "median_basis_bp_day"]),
                "median_abs_basis_bp_day": float(flips.loc[label, "median_abs_basis_bp_day"]),
                "flip_p25_bp_day": float(flips.loc[label, "flip_p25_bp_day"]),
                "shortfall_multiple_p25": float(flips.loc[label, "shortfall_multiple_p25"]),
                "frac_curve_at_sentinel": float(flips.loc[label, "frac_curve_at_sentinel"]),
            })
    return pd.DataFrame(rows).sort_values(
        ["structure", "listed_role", "listed_cm_days"]).reset_index(drop=True)


def gate_distinctness_table(three: pd.DataFrame,
                            books: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Which gate modes are actually different -- daily, and at cohort entries.

    The multiple-testing correction counts trials, so "how many gates are there
    really?" has to be measured rather than counted off :data:`GATE_MODES`. Two
    quite different things can make two gates coincide, and conflating them is
    how a trial count goes wrong in both directions:

    ``both`` vs ``cheapest`` -- **an identity.** Provable for every threshold and
        every configuration (see the module docstring), and re-measured here:
        **0 differences in 7,098 long-end daily rows** and 0 across the 352
        cohort entries. This is why :data:`DISTINCT_GATE_MODES` has four entries,
        not five.

    ``listed_only`` vs ``either`` -- **a coincidence of this cohort grid.** They
        differ on **12 of 7,098 daily rows**, so they are genuinely different
        gates; but none of those 12 days is one of the 88 monthly cohort entry
        dates, so they produce **0 differences across the 352 cohort rows** and
        their books are identical. That makes the realised book count 3 while
        the ex-ante gate count stays 4.

    The correction must use the **ex-ante** count -- four -- because the choice
    among the four was available before the cohort grid was known. Using the
    three realised books instead would lower the null threshold on the strength
    of an accident of the calendar. The distinction is reported rather than
    resolved silently, which is what this table is for.

    Returns one row per unordered pair with ``n_differ_daily``,
    ``n_differ_at_entries`` (when ``books`` is supplied) and ``relation``, one of
    ``identity`` / ``coincides_on_cohort_grid`` / ``distinct``.
    """
    import itertools

    piv = None
    if books is not None and len(books):
        piv = books.pivot_table(index=["structure", "entry"], columns="gate_mode",
                                values="gate_direction")
    rows: List[Dict[str, Any]] = []
    for a, b in itertools.combinations(GATE_MODES, 2):
        ca, cb = f"gate_{a}", f"gate_{b}"
        if ca not in three.columns or cb not in three.columns:
            continue
        nd = int((three[ca].to_numpy(float) != three[cb].to_numpy(float)).sum())
        ne: Optional[int] = None
        if piv is not None and a in piv.columns and b in piv.columns:
            ne = int((piv[a].to_numpy(float) != piv[b].to_numpy(float)).sum())
        if nd == 0:
            rel = "identity"
        elif ne == 0:
            rel = "coincides_on_cohort_grid"
        else:
            rel = "distinct"
        rows.append({
            "mode_a": a, "mode_b": b,
            "n_rows_daily": int(len(three)),
            "n_differ_daily": nd,
            "frac_differ_daily": nd / len(three) if len(three) else np.nan,
            "n_cohort_rows": (int(len(piv)) if piv is not None else None),
            "n_differ_at_entries": ne,
            "relation": rel,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------- sample size, measured not assumed


def cohort_pnl_correlation(cohorts: Mapping[str, pd.DataFrame],
                           cfg: Optional[Strat1ThreeWayConfig] = None
                           ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Measured pairwise correlation of the structures' UNIT cohort P&L.

    Returns ``(corr_matrix, summary)``. The correlation is computed on
    ``unit_gross_bp`` -- the pure-flattener P&L of :func:`unit_cohort_table` --
    aligned on cohort ``entry`` date and restricted to cohorts closed in every
    structure, so it measures the co-movement of the EXPOSURE rather than the
    co-movement of whatever direction each structure happened to be traded in.
    (Correlating the stored, direction-signed P&L instead would report a
    correlation that changes when a gate changes, which is not a property of the
    structures at all.)

    This is the input to :func:`effective_independent_n_pooled`, and the reason
    the pooled sample size is a measurement rather than a convention. Measured on
    the four long-end structures, 76 commonly-closed monthly cohorts: mean
    pairwise **r = 0.698**, ranging 0.489 (5Y/30Y vs 20Yx5Y/25Yx5Y) to 0.862
    (30Y/50Y vs 10Yx10Y/20Yx10Y). The three saturated forward structures alone
    average 0.818 -- they are very nearly one bet.
    """
    cfg = cfg or longend_config()
    series: Dict[str, pd.Series] = {}
    for label in cfg.labels():
        if label not in cohorts:
            continue
        t = unit_cohort_table(cohorts[label], cfg=cfg)
        t = t[t["closed"].to_numpy(bool)]
        s = pd.Series(t["unit_gross_bp"].to_numpy(float),
                      index=pd.to_datetime(t["entry"]))
        series[label] = s[~s.index.duplicated(keep="first")]
    if len(series) < 2:
        raise ValueError(f"need >= 2 structures with stored cohorts, got {list(series)}")

    M = pd.DataFrame(series).dropna()
    corr = M.corr()
    labels = list(corr.columns)
    off = [float(corr.iloc[i, j]) for i in range(len(labels))
           for j in range(i + 1, len(labels))]
    pairs = [(labels[i], labels[j], float(corr.iloc[i, j]))
             for i in range(len(labels)) for j in range(i + 1, len(labels))]
    lo = min(pairs, key=lambda p: p[2])
    hi = max(pairs, key=lambda p: p[2])
    summary = {
        "n_structures": len(labels),
        "n_common_closed_cohorts": int(len(M)),
        "mean_pairwise_r": float(np.mean(off)) if off else float("nan"),
        "min_pairwise_r": lo[2], "min_pair": f"{lo[0]} vs {lo[1]}",
        "max_pairwise_r": hi[2], "max_pair": f"{hi[0]} vs {hi[1]}",
    }
    return corr, summary


def effective_independent_n_pooled(cohorts: Mapping[str, pd.DataFrame],
                                   cfg: Optional[Strat1ThreeWayConfig] = None
                                   ) -> Dict[str, Any]:
    """Pooled effective sample size, with the cross-structure haircut MEASURED.

    Two independent haircuts, applied in sequence, because the nominal cohort
    count overstates the evidence twice over:

    **Overlap in time.** Monthly cohorts held one year share ~92% of their
    holding window, so a structure's 88 cohorts are
    ``span_days / 365.25 / horizon_years`` non-overlapping observations, not 88.
    Measured on 2019-02-01..2026-08-03: **7.50** per structure.

    **Overlap across structures.** The four long-end flatteners are overlapping
    segments of the same curve. With ``k`` structures at mean pairwise P&L
    correlation ``rbar``, the equal-weight portfolio's variance ratio gives

        ``k_eff = k / (1 + (k - 1) * rbar)``

    which at the measured ``rbar = 0.698`` is **1.29**, not 4. Pooled effective
    count ``= 7.50 * 1.29 = 9.7``.

    ``rbar`` is measured by :func:`cohort_pnl_correlation`, never assumed -- and
    the formula is monotone DECREASING in ``rbar``, which the test suite pins,
    because getting that direction backwards would credit correlated structures
    with more independence rather than less.

    The comparison worth carrying: the SFR study's per-structure ``n_eff`` was
    **2.05**. The long end has 3.7x more independent information per structure,
    which is the entire reason a gate-mode Sharpe is quoted here at all -- and it
    is still ten observations, not a thousand.
    """
    cfg = cfg or longend_config()
    per: Dict[str, float] = {}
    for label in cfg.labels():
        if label not in cohorts:
            continue
        t = cohorts[label]
        per[label] = effective_independent_n(t["entry"], t["exit"], cfg.horizon_years)
    if not per:
        raise ValueError("no stored cohort tables matched cfg.structures")

    corr, summ = cohort_pnl_correlation(cohorts, cfg)
    k = int(summ["n_structures"])
    rbar = float(summ["mean_pairwise_r"])
    k_eff = float(k / (1.0 + (k - 1) * rbar)) if (1.0 + (k - 1) * rbar) > 0 else float(k)
    n_per = float(np.nanmean(list(per.values())))
    return {
        "n_eff_per_structure": per,
        "n_eff_per_structure_mean": n_per,
        "n_structures": k,
        "mean_pairwise_r": rbar,
        "min_pairwise_r": summ["min_pairwise_r"], "min_pair": summ["min_pair"],
        "max_pairwise_r": summ["max_pairwise_r"], "max_pair": summ["max_pair"],
        "n_common_closed_cohorts": summ["n_common_closed_cohorts"],
        "k_eff_structures": k_eff,
        "n_eff_pooled": float(n_per * k_eff),
        "n_nominal_pooled": int(sum(len(cohorts[l]) for l in per)),
        "shortend_n_eff_per_structure": SHORT_END_REFERENCE["n_eff_per_structure"],
        "formula": "k_eff = k / (1 + (k-1)*rbar);  n_eff_pooled = mean(span/horizon) * k_eff",
    }


# --------------------------------------------------------------- the verdict


def longend_verdict(three: pd.DataFrame, basis: pd.DataFrame,
                    sweep: Optional[pd.DataFrame] = None,
                    books: Optional[pd.DataFrame] = None,
                    cohorts: Optional[Mapping[str, pd.DataFrame]] = None,
                    cfg: Optional[Strat1ThreeWayConfig] = None) -> Dict[str, Any]:
    """Everything the long-end report has to state, as one JSON-able dict.

    Leads with coverage, then the ranking and agreement statistics, then the
    basis and the flip retest, and puts the P&L last and labelled -- that being
    the order of evidential weight even at 7.5 effective observations per
    structure.

    The headline booleans are computed at the PRE-SPECIFIED benchmark only
    (``primary`` @ 30 days), with the twelve-benchmark range reported beside
    them as robustness. That ordering matters here more than it did in the short
    end: the disagreement rate on 5Y/30Y runs 3.24%-5.34% across the twelve, so
    picking the widest would push it across the 5% materiality line and picking
    the narrowest would push it comfortably under. The pre-specified one is
    3.34%, and that is the number the verdict states.
    """
    cfg = cfg or longend_config()
    cov = intersection_report(three)
    ranks = rank_table(three)
    agree = agreement_table(three)
    trans = transition_table(three)
    flips = flip_threshold_table(three)
    persist = basis_persistence(basis)

    pooled_agree = agree[agree["structure"] == "POOLED"].iloc[0].to_dict()
    pooled_rank = ranks[ranks["structure"] == "POOLED"].iloc[0].to_dict()

    out: Dict[str, Any] = {
        "mode": "UST long end",
        "headline_benchmark": {"role": HEADLINE_ROLE, "cm_days": HEADLINE_CM_DAYS,
                               "pre_specified": True,
                               "source": "listed_vol.UST_SECTOR_MAP (measured CTD maturity)"},
        "coverage": cov,
        "identity_both_equals_cheapest": assert_both_equals_cheapest(three),
        "pooled_ranking": {k: v for k, v in pooled_rank.items()
                           if k.startswith(("frac_", "median_", "n_"))},
        "pooled_agreement": {k: v for k, v in pooled_agree.items()
                             if k.startswith(("frac_", "n_", "median_", "basis_"))},
        "per_structure_ranking": ranks.to_dict("records"),
        "per_structure_agreement": agree.to_dict("records"),
        "transitions": trans.to_dict("records"),
        "flip_threshold": flips.to_dict("records"),
        "basis_persistence": persist.to_dict("records"),
        "n_distinct_gate_modes": len(DISTINCT_GATE_MODES),
        "short_end_reference": SHORT_END_REFERENCE,
    }

    # ---------------------------------------------------------------- the retest
    # The UNSATURATED structure is the one that carries the answer, and it is
    # picked by measurement rather than by name so that a future rebuild which
    # unsaturates a different structure reports that one instead of silently
    # continuing to quote 5Y/30Y.
    #
    # The selector is ``frac_verdict_saturated`` -- the share of days on the
    # majority verdict -- NOT ``frac_curve_at_sentinel``. Measured, the two
    # disagree and the sentinel column gets it backwards: 10Yx10Y/20Yx10Y sits at
    # 0.342 sentinel days against 5Y/30Y's 0.578, yet its verdict is cheap on
    # 100.0% of days and 5Y/30Y's on 51.4%. Selecting on sentinels would nominate
    # a structure whose disagreement rate is exactly zero as "the binding one".
    per = flips[~flips["structure"].isin(["POOLED", "[SFR short end, prior study]"])]
    binding = per.sort_values("frac_verdict_saturated").iloc[0]
    ref_ratio = float(SHORT_END_REFERENCE["basis_shortfall_multiple"])
    ratio = float(binding["shortfall_multiple_p25"])
    dis = float(binding["frac_disagree"])
    out["flip_retest"] = {
        "binding_structure": str(binding["structure"]),
        "why_binding": ("lowest frac_verdict_saturated, i.e. the structure whose "
                        "cheap/rich verdict is furthest from unanimous and "
                        "therefore the only one where the choice of benchmark can "
                        "move the answer"),
        "frac_verdict_saturated": float(binding["frac_verdict_saturated"]),
        "frac_verdict_saturated_others": {
            str(r["structure"]): float(r["frac_verdict_saturated"])
            for _, r in per.iterrows() if r["structure"] != binding["structure"]},
        "frac_curve_at_sentinel": float(binding["frac_curve_at_sentinel"]),
        "formula_note": ("flip_p25 is np.nanpercentile(|curve - swaption|, 25) "
                         "with never_cheap (+inf) days INCLUDED -- the short-end "
                         "study's own expression. The finite-only variant is "
                         "carried as shortfall_multiple_p25_finite."),
        "shortfall_multiple_p25_finite": float(binding["shortfall_multiple_p25_finite"]),
        "n_days": int(binding["n_days"]),
        "median_abs_basis_bp_day": float(binding["median_abs_basis_bp_day"]),
        "flip_p25_bp_day": float(binding["flip_p25_bp_day"]),
        "shortfall_multiple_p25": ratio,
        "shortend_shortfall_multiple_p25": ref_ratio,
        "compression_vs_short_end": (ref_ratio / ratio) if ratio > 0 else float("nan"),
        "frac_disagree": dis,
        "shortend_frac_disagree": float(SHORT_END_REFERENCE["frac_rows_disagree"]),
        "disagreement_ratio_vs_short_end": (
            dis / float(SHORT_END_REFERENCE["frac_rows_disagree"])
            if SHORT_END_REFERENCE["frac_rows_disagree"] else float("nan")),
    }

    obs = float(np.nanmedian(np.abs(basis["basis_bp_day"].to_numpy(float))))
    need = float(pooled_agree["basis_needed_to_flip_25pct_bp_day"])
    pooled_dis = float(pooled_agree["frac_disagree"])
    out["listed_information"] = {
        "signals_ever_disagree": bool(pooled_dis > 0.0),
        "frac_rows_disagree_pooled": pooled_dis,
        "n_rows_disagree_pooled": int(pooled_agree["n_disagree"]),
        "frac_rows_disagree_binding_structure": dis,
        "median_abs_basis_bp_day_pooled": obs,
        "basis_needed_to_flip_25pct_bp_day_pooled": need,
        "basis_shortfall_multiple_pooled": (need / obs) if obs > 0 else float("nan"),
        #: Pre-specified: the binding structure at the pre-specified benchmark,
        #: against the same 5% bar the short-end study used.
        "listed_materially_changes_verdict": bool(dis >= 0.05),
        "listed_matters_more_than_short_end": bool(ratio < ref_ratio),
    }
    if sweep is not None and len(sweep):
        b = sweep[sweep["structure"] == str(binding["structure"])]
        if len(b):
            out["listed_information"]["binding_structure_disagree_range_over_12_benchmarks"] = [
                float(b["frac_disagree"].min()), float(b["frac_disagree"].max())]
            out["listed_information"]["binding_structure_ratio_range_over_12_benchmarks"] = [
                float(b["shortfall_multiple_p25"].min()),
                float(b["shortfall_multiple_p25"].max())]

    out["listed_information"]["verdict"] = (
        f"On the long end the listed benchmark is measurably CLOSER to mattering "
        f"than it was in the short end, and still does not decide anything on its "
        f"own. The two curve-vs-vol signals disagree on {pooled_dis:.2%} of pooled "
        f"rows; on {binding['structure']} -- the only structure whose verdict is "
        f"not saturated ({float(binding['frac_verdict_saturated']):.1%} of days on "
        f"the majority verdict, against 100.0% for the other three) -- they "
        f"disagree on {dis:.2%} against "
        f"{float(SHORT_END_REFERENCE['frac_rows_disagree']):.2%} in the short end. "
        f"The reason is arithmetic and it moved in both directions at once: the "
        f"median |OTC-listed basis| roughly DOUBLED "
        f"({SHORT_END_REFERENCE['median_abs_basis_bp_day']:.3f} -> "
        f"{float(binding['median_abs_basis_bp_day']):.3f} bp/day, "
        f"x{float(binding['median_abs_basis_bp_day']) / float(SHORT_END_REFERENCE['median_abs_basis_bp_day']):.2f}) "
        f"while the basis needed to flip a quarter of days fell by about a THIRD "
        f"({SHORT_END_REFERENCE['basis_needed_to_flip_25pct_bp_day']:.3f} -> "
        f"{float(binding['flip_p25_bp_day']):.3f}, "
        f"x{float(binding['flip_p25_bp_day']) / float(SHORT_END_REFERENCE['basis_needed_to_flip_25pct_bp_day']):.2f}), "
        f"so the shortfall multiple falls from {ref_ratio:.1f}x to {ratio:.1f}x -- a "
        f"{(ref_ratio / ratio) if ratio > 0 else float('nan'):.1f}-fold compression. "
        f"On the other three structures the flattener is cheap gamma against every "
        f"benchmark on 100% of days and the disagreement rate is exactly zero, so "
        f"the listed leg adds literally nothing there."
    )

    # ----------------------------------------------------------- sample size
    if cohorts is not None:
        out["sample_size"] = effective_independent_n_pooled(cohorts, cfg)
        n_eff = out["sample_size"]["n_eff_pooled"]
    else:
        n_eff = float("nan")

    if books is not None and len(books):
        gs = gate_summary(books, cfg)
        out["gate_summary"] = gs.to_dict("records")
        gd = gate_distinctness_table(three, books)
        out["gate_distinctness"] = gd.to_dict("records")
        out["n_trials_used_for_correction"] = len(DISTINCT_GATE_MODES)
        out["trial_count_note"] = (
            "the correction uses the EX-ANTE distinct gate count (4: both == "
            "cheapest is an identity at every configuration). listed_only and "
            "either coincide on this cohort grid but differ on 12 of 7,098 daily "
            "rows, so they are two gates whose books happened to match, not one "
            "gate -- counting the realised books instead would lower the null "
            "threshold on an accident of the calendar.")
        if not np.isfinite(n_eff):
            n_eff = float(np.nanmax(gs["n_eff_independent"].to_numpy(float)))
        n_eff_int = max(2, int(round(n_eff)))
        out["expected_max_sharpe_under_null_nominal"] = expected_max_sharpe_under_null(
            len(DISTINCT_GATE_MODES), int(np.nanmax(gs["n_closed"].to_numpy(float))))
        out["expected_max_sharpe_under_null_effective"] = expected_max_sharpe_under_null(
            len(DISTINCT_GATE_MODES), n_eff_int)
        out["n_eff_used_for_null"] = n_eff_int
        sr = gs["sharpe_per_trade"].to_numpy(float)
        if np.isfinite(sr).any():
            best = gs.iloc[int(np.nanargmax(sr))]
            out["best_gate_mode"] = str(best["gate_mode"])
            out["best_gate_sharpe_per_trade"] = float(best["sharpe_per_trade"])
            out["best_gate_beats_null"] = bool(
                float(best["sharpe_per_trade"])
                > out["expected_max_sharpe_under_null_effective"])
            out["best_gate_deflated_sharpe"] = deflated_sharpe_ratio(
                float(best["sharpe_per_trade"]), n_eff_int,
                sr_benchmark=out["expected_max_sharpe_under_null_effective"])

        g = gs.set_index("gate_mode")
        if {"both", "swaption_only"} <= set(g.index):
            d = (float(g.loc["both", "net_bp_mean"])
                 - float(g.loc["swaption_only", "net_bp_mean"]))
            stood_aside = (int(g.loc["swaption_only", "n_traded"])
                           - int(g.loc["both", "n_traded"]))
            out["listed_information"].update({
                "gate_both_minus_swaption_only_bp_per_cohort": d,
                "cohorts_the_listed_veto_stood_aside_on": stood_aside,
                "cohorts_total": int(g.loc["swaption_only", "n_cohorts"]),
            })
            out["listed_information"]["verdict"] += (
                f" Operationally the listed veto stood aside on {stood_aside} of "
                f"{int(g.loc['swaption_only', 'n_cohorts'])} cohorts and moved the "
                f"mean outcome by {d:+.3f} bp per cohort."
            )
    return out


# =============================================================================
#  REAL LISTED CONTRACT mode -- re-exported from ``strat1_real_contracts``
#
#  Nothing above changes. The real-contract run reaches this module's machinery
#  the same way the constant-maturity long-end run does -- by handing
#  :func:`threeway_frame` a panel with a unique ``(date, structure)`` key and the
#  three vol columns already named ``breakeven_vol_bp_day`` /
#  ``otc_atmf_bp_day`` / ``listed_atm_bp_day``. ``build_longend_contract_panel``
#  was written to that contract, so the ranking, the gates, the flip retest, the
#  basis persistence and the sample-size arithmetic are reused unmodified rather
#  than reimplemented. A second implementation of any of them would make a
#  real-vs-CM divergence un-diagnosable, which is the one thing that study exists
#  to measure.
#
#  Lazy, via PEP 562's module ``__getattr__``, because this module is imported BY
#  ``strat1_real_contracts``: an eager import here would close the cycle and all
#  three modules would fail to import.
# =============================================================================

#: Names ``strat1_threeway`` re-exports from ``strat1_real_contracts``. Listed
#: explicitly rather than deferring to that module's ``__all__`` so that adding a
#: helper there cannot silently widen this module's surface.
_REAL_CONTRACT_EXPORTS: Tuple[str, ...] = (
    "real_threeway_config",
    "real_threeway_frames",
    "cm_vs_real_gate_table",
    "real_contract_verdict",
    "REAL_ROOTS",
    "REAL_HEADLINE_ROOT",
    "REAL_HEADLINE_TARGET",
)

#: ``HEADLINE_ROOT`` / ``HEADLINE_TARGET`` are re-exported under PREFIXED names.
#: This module already defines ``HEADLINE_ROLE`` and ``HEADLINE_CM_DAYS`` for the
#: constant-maturity study, and a bare ``HEADLINE_ROOT`` sitting beside them
#: would read as part of that same set while meaning something else entirely.
_REAL_ALIASES: Dict[str, str] = {
    "REAL_HEADLINE_ROOT": "HEADLINE_ROOT",
    "REAL_HEADLINE_TARGET": "HEADLINE_TARGET",
}

__all__ += list(_REAL_CONTRACT_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve the real-contract names on first access. See the block above."""
    if name in _REAL_CONTRACT_EXPORTS:
        from RVUtils.ConvexityRV import strat1_real_contracts as _rc

        return getattr(_rc, _REAL_ALIASES.get(name, name))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Keep tab-completion and ``dir()`` honest about the lazy names."""
    return sorted(set(globals()) | set(_REAL_CONTRACT_EXPORTS))
