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
"""

from __future__ import annotations

import dataclasses
import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.strat1_listed import SFR_STRUCTURES

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
    """
    cfg = cfg or Strat1ThreeWayConfig()
    df = panel.copy()
    if "date" not in df.columns:
        df = df.reset_index()
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
