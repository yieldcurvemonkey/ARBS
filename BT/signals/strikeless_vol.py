"""Today's strikeless-vol state, one row per pair -- with what that state is worth.

Composes the package: forward greeks panel -> vol metrics -> walk-forward factor
residual and drift -> ``backtest.causal_signals`` -> the conditional rule. Every
row carries the reason the rule reached its sign, the sample behind it, and --
because this study measured what it measured -- the verdict, the DSR and the
trial count beside the sign.

Public surface:
  - ``REQUIRED_OUTPUT_COLUMNS``   : every column a row must carry
  - ``MEASURED_VERDICT`` / ``market_verdict``  : the study's own measured result
  - ``SignalWindows``             : the windows, in one place
  - ``build_pair_inputs``         : the five ``signal_state`` columns, built causally
  - ``certified_signals``         : ``causal_signals`` with both certifiable sources wired
  - ``state_row`` / ``pair_state``: one output row
  - ``greeks_with_cache``         : the incremental per-pair greeks cache
  - ``today_state``               : the runner

**READ THIS BEFORE READING A ROW.**

**Nothing here is a validated edge.** Every measured result in this study is
DEAD. The four markets run end to end in Task 21 print DSR ``9.7e-127`` (USD),
``1.5e-40`` (EUR), ``1.5e-48`` (JPY) and ``1.8e-95`` (GBP) on a declared 3888
trials, all four lose at 1x costs, and **three of the four have a NEGATIVE
break-even cost multiplier** -- gross is already negative, so no cost assumption
rescues them. Only EUR's is positive, at ``+0.23x``: EUR needs the true cost to
be under a quarter of the assumed schedule merely to reach zero. Those numbers
travel on every row (``verdict``, ``dsr_prob``, ``n_trials``,
``breakeven_cost_mult``) so that a reader of a single day's output cannot
mistake it for something it is not.

**A row is a statement about the rule, not a recommendation.** If the rule emits
a sign today, what that means is "the published rulebook, run on today's data,
is in this state". ``strategy.build_signals`` is STATELESS -- it recomputes the
sign from scratch each day with no position memory and no exit hysteresis -- so
the ``dv01_usd`` on a row is a TARGET for that date, not an instruction to hold.
A target that changes is turnover, and turnover is what the cost schedule bites
on: costs are 41% of gross at 1x and 83% at 2x on the static long.

**Requirement 6 is not evidenceable here, and it was measured NOT MET anyway.**
Of the six binding requirements, a live runner can evidence five: requirements 1
and 3 come from ``causal_signals``' stamped audit numbers, requirement 2 from
``entry_vintage_signals``' frozen-z deviation, and 4 and 5 are structural
properties of the engine. Requirement 6 -- the random-walk placebo -- is a
statement about a completed backtest and there is no such object on a daily
runner, so ``req_random_walk_placebo`` is ``False`` and ``requirements_met`` is
``False`` on every row. That is not a formality being skipped: Task 19 measured
requirement 6 through the genuine ``causal_signals -> run_pair`` composition and
found it **NOT MET** (20/20 nulls traded, 19 beat the headline, p = 0.952).

**The SIGN is uncertified.** ``causal_signals`` certifies ``residual_z`` end to
end and can certify ``drift_t`` and ``iv_z`` when handed their sources -- both
are wired below. It cannot certify ``be_over_realized``, which is the column
that SETS the sign and the largest lever of the five; its own docstring says "no
argument to this function can certify it today". So the row names it, in
``uncertified_signal_inputs``, in ``sign_input_certified`` and again in
``note``. Read the stamp on the row in hand, never the module-level default.

**Two places a number here would otherwise describe something adjacent to what
it is read as**, both of which cost a real defect elsewhere in this study:

1. *The diagnostics belong to the information date.* A lag-1 sign for date ``t``
   is decided on the panel row for ``t-1``, so the ``spread_bp`` / ``BE/RV`` /
   ``drift_t`` printed beside a sign must be ``t-1``'s.
   ``scripts/sv_cross_market._fmt_signal_state`` prints ``signals.iloc[-1]``
   next to ``panel.iloc[-1]``, which are one day apart. Every diagnostic on a
   row here is read at ``information_date``, and ``information_date`` is
   emitted next to ``signal_date`` so the gap is visible rather than assumed.
2. *``be_over_realized``'s denominator is a RATE vol, not a slope vol.*
   ``breakeven_h25`` is ``sqrt(2|roll|/gamma)`` with gamma measured by a
   parallel LEVEL bump, so it is a breakeven rate move per day, and
   ``vol_metrics`` says in as many words that it is compared to "the longer
   leg's forward par rate" while ``spread_vol_bp_day`` is "the sizing base --
   they are different numbers". This runner uses the long leg's rate vol, per
   that contract and per the Task 10 brief's own motivating case (``be 1.3 / rv
   3.0 -> 0.43``, deeply cheap). ``scripts/sv_cross_market`` divides by the
   SPREAD's vol instead, which is roughly 4x smaller and turns the same
   breakeven into a ratio of 1.75-4.17, i.e. "rich" on 72-98% of days. Both are
   emitted -- ``be_over_realized`` (rate vol, the sign's input) and
   ``be_over_spread_vol`` (slope vol, the Task 21 variant) -- so the difference
   is visible on the row. ``verdict_pair`` names the structure the stored
   verdict was measured on, and ``verdict_basis`` names the denominator it used.

A third of the same shape, closed rather than flagged: on a day the rule is
already holding, ``entry_vintage_signals`` prices the row on the z FROZEN at
entry, which is a different number from the live trailing z -- on this module's
own test frame, ``-2.49`` against ``-2.06``. Reporting only the live one would
put it next to a ``reason`` string quoting the other. So the row carries both:
``residual_z`` (live, at the information date) and ``decision_z`` (the number
that actually decided the row), with ``residual_z_is_decision_input`` saying
when they are the same object and ``held_days`` saying why not.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.backtest import (
    UNCERTIFIED_SIGNAL_INPUTS,
    causal_signals,
    _derive_requirements,
)
from RVUtils.StrikelessVol.conventions import bp_day_to_annual_normals
from RVUtils.StrikelessVol.factors import (
    WalkForwardFit,
    drift,
    expanding_changes_residual,
    expanding_residual,
    residual_z,
)
from RVUtils.StrikelessVol.greeks import greeks_panel
from RVUtils.StrikelessVol.panels import PANEL_DIR, vol_panel
from RVUtils.StrikelessVol.strategy import SignalConfig
from RVUtils.StrikelessVol.universe import (
    ALL_PAIRS,
    MARKET_CURVES,
    ForwardPair,
    supported_pairs,
)
from RVUtils.StrikelessVol.vol_metrics import (
    be_over_implied,
    be_over_realized,
    realized_vol_bp_day,
    spread_vol_bp_day,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_DIR",
    "MEASURED_VERDICT",
    "MarketVerdict",
    "PairInputs",
    "REQUIRED_OUTPUT_COLUMNS",
    "SIGNAL_COLUMNS",
    "HONESTY_COLUMNS",
    "SignalWindows",
    "STUDY_N_TRIALS",
    "VOL_CURVE_BY_MARKET",
    "VOL_STRUCTURE",
    "build_pair_inputs",
    "certified_signals",
    "greeks_with_cache",
    "market_verdict",
    "pair_state",
    "state_row",
    "today_state",
]

#: The swaption-vol curve key per market. ``MARKET_CURVES`` names the RATE
#: curve; these name the vol surface, and for USD the two differ (OIS vs SOFR).
VOL_CURVE_BY_MARKET: Dict[str, str] = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "JPY": "JPY-TONAR",
    "GBP": "GBP-SONIA",
}

#: The driver and the short-side gate, in ``definitions.IRSwaptions.ASSET_IDS_MAP``
#: form. The one structure every market publishes.
VOL_STRUCTURE = "2y 10y"

CACHE_DIR = PANEL_DIR / "daily_runner"

#: Task 18's per-pair sweep (972 configs) times the four markets Task 21 ran.
#: A LOWER BOUND on the study's search: it ignores the pairs and families run in
#: earlier tasks entirely. Recorded as a constant so the deflation count cannot
#: silently shrink if someone narrows an axis default.
STUDY_N_TRIALS: int = 3888

#: Task 19's measured p-value for requirement 6, through the genuine
#: ``causal_signals -> run_pair`` composition: 20 of 20 nulls traded and 19 beat
#: the headline. Quoted on the row so "requirement 6 unmet" reads as a
#: measurement rather than as paperwork this runner skipped.
PLACEBO_P_VALUE: float = 0.952


# ------------------------------------------------------- the measured verdict


@dataclass(frozen=True)
class MarketVerdict:
    """One market's measured result, as the Task 21 run printed it.

    Every field is a number that run produced. ``verdict`` and
    ``breakeven_cost_mult`` are DERIVED from those numbers here rather than
    transcribed, so a stored label cannot drift away from the figures beside it
    -- ``verdict`` through ``RVUtils.SFRRVLab.stats.verdict``, the repo-wide
    taxonomy this study does not get its own version of.
    """

    market: str
    pair_name: str
    n_trades: int
    gross_bp: float
    net_1x_bp: float
    net_2x_bp: float
    dsr_prob: float
    sample_start: dt.date
    sample_end: dt.date
    n_trials: int = STUDY_N_TRIALS
    #: What ``be_over_realized``'s denominator was in the run that produced
    #: these numbers. Not this runner's default -- see the module docstring.
    basis: str = "spread_vol_bp_day denominator (scripts/sv_cross_market)"

    @property
    def cost_1x_bp(self) -> float:
        return self.gross_bp - self.net_1x_bp

    @property
    def maker_bp(self) -> float:
        """Gross less HALF the 1x charge -- the maker leg of the taxonomy."""
        return self.gross_bp - 0.5 * self.cost_1x_bp

    @property
    def breakeven_cost_mult(self) -> float:
        """The cost multiplier at which net P&L reaches zero.

        Cost is linear in the multiplier, so this is ``gross / cost_at_1x``.
        Negative means gross is already negative and **no** cost schedule makes
        the market profitable.
        """
        c = self.cost_1x_bp
        return self.gross_bp / c if c else float("nan")

    @property
    def verdict(self) -> str:
        """Recomputed through ``RVUtils.SFRRVLab.stats.verdict``, never stored.

        The repo-wide taxonomy is the authority and this study does not get its
        own; deriving here means the label on a row cannot drift away from the
        numbers printed beside it. ``median_net_bp`` is the "is the edge one
        lucky corner" leg and is the median 1x net across the markets scored,
        which is what ``report.league_table`` hands it.
        """
        from RVUtils.SFRRVLab.stats import verdict as _verdict

        return _verdict(
            net_bp_at_taker=self.net_2x_bp,
            net_bp_at_maker=self.maker_bp,
            dsr_prob=self.dsr_prob,
            median_net_bp=MEDIAN_NET_1X_BP,
            n_trades=self.n_trades,
        )


def _measured() -> Dict[str, MarketVerdict]:
    """The Task 21 league table, verbatim.

    Source: ``.superpowers/sdd/2026-08-04-strikeless-vol/task-21-cross-market-run.txt``
    (the run's own stdout), section "league table (one config per market, DSR on
    the multiplied count)". One config per market: ``SignalConfig()`` defaults,
    the ``10Y10Y/20Y10Y`` structure, implied vol as the only driver, one
    ``CostSchedule`` at multiplier 1.
    """
    rows = [
        # market, n_trades, gross_bp, net_1x_bp, net_2x_bp, dsr_prob, start, end
        ("USD", 116, -4.349373, -191.370916, -378.392458, 9.730617e-127,
         dt.date(2017, 1, 3), dt.date(2026, 8, 3)),
        ("EUR", 58, 21.239336, -72.739479, -166.718293, 1.508078e-40,
         dt.date(2019, 10, 2), dt.date(2026, 8, 3)),
        ("JPY", 61, -36.895482, -165.815749, -294.736017, 1.471768e-48,
         dt.date(2017, 1, 4), dt.date(2026, 8, 3)),
        ("GBP", 93, -25.644988, -215.519128, -405.393268, 1.794651e-95,
         dt.date(2017, 1, 3), dt.date(2026, 8, 3)),
    ]
    return {
        market: MarketVerdict(
            market=market, pair_name=f"{market} 10Y10Y/20Y10Y", n_trades=n,
            gross_bp=gross, net_1x_bp=net1, net_2x_bp=net2, dsr_prob=dsr,
            sample_start=start, sample_end=end,
        )
        for market, n, gross, net1, net2, dsr, start, end in rows
    }


MEASURED_VERDICT: Dict[str, MarketVerdict] = _measured()

#: The median 1x net across the markets scored, which is what
#: ``report.league_table`` hands ``verdict`` as ``median_net_bp`` (the "is the
#: edge one lucky corner" leg). Computed from the stored numbers rather than
#: transcribed.
MEDIAN_NET_1X_BP: float = float(
    np.median([mv.net_1x_bp for mv in MEASURED_VERDICT.values()]))


def market_verdict(market: str) -> MarketVerdict:
    """The stored measured result for ``market``. Raises for anything else.

    A market the study never scored has no verdict, and returning a default --
    or the study-wide DEAD without its numbers -- would put a verdict on a row
    that nothing measured. Refuse instead.
    """
    try:
        return MEASURED_VERDICT[str(market)]
    except KeyError:
        raise KeyError(
            f"no measured verdict for market {market!r}; this study scored "
            f"{sorted(MEASURED_VERDICT)} and nothing else. A row cannot carry a "
            "verdict that was never measured for it."
        ) from None


# ------------------------------------------------------------------- columns

#: The signal itself, exactly as Task 22's brief specifies it.
SIGNAL_COLUMNS = (
    "pair", "spread_bp", "breakeven_h25", "realized_vol_bp_day", "implied_bp_day",
    "be_over_realized", "be_over_implied", "drift_t", "residual_z",
    "sign", "size", "dv01_usd", "reason", "sample_start",
)

#: What the row must say about itself beside the sign. Not optional: a row that
#: carries a sign without these is a row a reader can mistake for a validated
#: edge, which no result in this study is.
HONESTY_COLUMNS = (
    "market", "asof", "signal_date", "information_date",
    "sample_end", "n_obs", "held_days", "decision_z", "residual_z_is_decision_input",
    "spread_vol_bp_day", "be_over_spread_vol", "iv_z", "beta_vintage_date",
    "verdict", "verdict_pair", "verdict_is_for_this_pair", "verdict_basis",
    "dsr_prob", "n_trials", "gross_bp", "net_1x_bp", "net_2x_bp",
    "breakeven_cost_mult", "placebo_p_value",
    "requirements_met", "unmet_requirements",
    "req_expanding_betas", "req_entry_vintage_hedge", "req_rolling_sigma_z",
    "req_spread_leg_pnl", "req_distinct_episodes", "req_random_walk_placebo",
    "certified_signal_inputs", "uncertified_signal_inputs",
    "sign_input_certified", "note",
)

REQUIRED_OUTPUT_COLUMNS = SIGNAL_COLUMNS + HONESTY_COLUMNS


# ------------------------------------------------------------------- windows


@dataclass(frozen=True)
class SignalWindows:
    """Every window the rule uses, in one place.

    Defaults are the study's: a trailing 63-day realized vol, a 63-day drift
    window, a 252-day minimum for the walk-forward fit and a 252/126 trailing z.
    Warm-up is therefore ``fit_min_periods + z_min_periods`` = **378 business
    days of NaN** before any signal at all, and ``signal_state`` fails CLOSED on
    a NaN -- so a lookback that does not comfortably clear 378 rows produces a
    runner that reports "no valuation" forever and looks like a quiet market.
    """

    realized: int = 63
    drift: int = 63
    fit_min_periods: int = 252
    refit_every: int = 1
    z_window: int = 252
    z_min_periods: int = 126
    iv_z_window: int = 252
    iv_z_min_periods: int = 126

    @property
    def warmup_rows(self) -> int:
        return int(self.fit_min_periods) + int(self.z_min_periods)


# -------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class PairInputs:
    """Everything ``causal_signals`` needs for one pair, built causally."""

    pair: ForwardPair
    panel: pd.DataFrame = field(repr=False)
    spread_bp: pd.Series = field(repr=False)
    drivers: Dict[str, pd.Series] = field(repr=False)
    changes_resid: pd.Series = field(repr=False)
    iv_bp_day: pd.Series = field(repr=False)
    fit: WalkForwardFit = field(repr=False)
    residual_z: pd.Series = field(repr=False)
    windows: SignalWindows = SignalWindows()


def build_pair_inputs(
    pair: ForwardPair,
    greeks: pd.DataFrame,
    iv_bp_day: pd.Series,
    *,
    umep: Optional[pd.Series] = None,
    windows: SignalWindows = SignalWindows(),
) -> PairInputs:
    """The five columns ``strategy.signal_state`` reads, and where each is from.

    * ``be_over_realized`` -- ``greeks["breakeven_h25"]`` over the trailing
      ``windows.realized``-day realized vol of **the longer leg's forward par
      rate**. That is ``vol_metrics``' stated contract ("the rate the rebalance
      trigger watches, and the one the breakeven is compared to"), and it is the
      right comparator because ``breakeven_h25`` is a breakeven LEVEL move --
      gamma is measured by a parallel bump. The spread-vol variant is computed
      too, as ``be_over_spread_vol``, because that is what
      ``scripts/sv_cross_market`` divides by; see the module docstring.
    * ``drift_t`` -- a trailing ``windows.drift``-day Newey-West t of
      :func:`factors.expanding_changes_residual`. **Not**
      ``factors.changes_regression``, which fits one set of betas on the whole
      sample and moves this veto column 6.1 t-units in the head of a sample
      whose tail alone was shocked, against a gate of 2.0.
    * ``residual_z`` -- a placeholder here; ``causal_signals`` overwrites it
      from the audited walk-forward levels fit and whatever is put here is
      ignored. The fit is built here anyway so the certified z can be REPORTED
      (``PairInputs.residual_z``) and so ``causal_signals`` can verify the
      artifact rather than rebuild it.
    * ``spread_vol_bp_day`` -- the trailing realized vol of the package SPREAD,
      which is the risk-parity sizing base.
    * ``iv_z`` -- a trailing ``windows.iv_z_window``-day z of the market's own
      2y10y ATM implied normal, in bp/day exactly as GS publishes it.

    ``drivers`` is implied vol alone by default, which is the model Task 21
    measured in all four markets and therefore the model the stored verdict
    describes. ``umep`` is USD-only (``panels.umep_panel`` needs a Treasury
    curve) and is off by default; USD run both ways over 2021-2026 agreed on
    92.6% of dates and the driver was worth ~3.2bp over 5.5 years -- it changed
    no sign and no verdict.
    """
    if greeks.empty:
        raise ValueError(f"{pair.name}: empty greeks panel, nothing to build")
    idx = greeks.index
    iv = pd.Series(iv_bp_day).astype(float).reindex(idx)

    spread = greeks["spread_bp"].astype(float)
    long_rate = greeks["long_rate"].astype(float)
    be = greeks["breakeven_h25"].astype(float)

    rate_vol = realized_vol_bp_day(long_rate, window=int(windows.realized))
    slope_vol = spread_vol_bp_day(spread, window=int(windows.realized))

    drivers: Dict[str, pd.Series] = {
        "vol": pd.Series(bp_day_to_annual_normals(iv), index=idx, name="vol")
    }
    if umep is not None:
        if pair.market != "USD":
            raise ValueError(
                f"umep is USD-only (panels.umep_panel needs a Treasury curve, "
                f"and no equivalent ASW infrastructure exists for "
                f"{pair.market} in this repo); asked for {pair.market}"
            )
        drivers["umep"] = pd.Series(umep).astype(float).reindex(idx)

    changes_resid = expanding_changes_residual(
        spread, drivers, min_periods=int(windows.fit_min_periods),
        refit_every=int(windows.refit_every)).residual
    fit = expanding_residual(
        spread, drivers, min_periods=int(windows.fit_min_periods),
        refit_every=int(windows.refit_every))
    z = residual_z(fit.residual, window=int(windows.z_window),
                   min_periods=int(windows.z_min_periods))

    panel = pd.DataFrame({
        # the five the rule reads
        "be_over_realized": be_over_realized(be, rate_vol),
        "drift_t": drift(changes_resid, window=int(windows.drift))["t_stat"],
        "residual_z": pd.Series(np.nan, index=idx),
        "spread_vol_bp_day": slope_vol,
        "iv_z": residual_z(iv, window=int(windows.iv_z_window),
                           min_periods=int(windows.iv_z_min_periods)),
        # everything the row reports beside them
        "spread_bp": spread,
        "breakeven_h25": be,
        "realized_vol_bp_day": rate_vol,
        "implied_bp_day": iv,
        "be_over_implied": be_over_implied(be, iv),
        "be_over_spread_vol": be_over_realized(be, slope_vol),
        "gamma_h25": greeks["gamma_h25"].astype(float),
        "daily_roll_usd": greeks["daily_roll_usd"].astype(float),
    }, index=idx)

    return PairInputs(pair=pair, panel=panel, spread_bp=spread, drivers=drivers,
                      changes_resid=changes_resid, iv_bp_day=iv, fit=fit,
                      residual_z=z, windows=windows)


def certified_signals(inputs: PairInputs, cfg: SignalConfig) -> pd.DataFrame:
    """``causal_signals`` with everything this engine can certify wired up.

    ``fit=`` hands over the walk-forward levels fit built in
    :func:`build_pair_inputs`; ``causal_signals`` verifies it reproduces the fit
    its own audit ran on and RAISES if it does not, so passing it certifies the
    artifact rather than saving a rebuild.

    ``changes_resid_fn=`` puts the drift source itself through
    ``audit_causal_betas``; supplying only ``changes_resid=`` would certify the
    transform and leave the certificate reading ``drift_t(source uncertified)``.

    ``iv_bp_day=`` is passed WITHOUT ``iv_bp_day_fn=``: the series IS the raw GS
    observable, no shock probe can certify a raw observable, and the engine
    refuses a pointwise builder by name. ``iv_z(source uncertified)`` is the
    honest certificate this call earns.

    ``be_over_realized`` -- the SIGN -- has no analogous argument.
    """
    w = inputs.windows
    return causal_signals(
        inputs.panel, cfg,
        spread_bp=inputs.spread_bp, drivers=inputs.drivers,
        fit=inputs.fit,
        min_periods=int(w.fit_min_periods), refit_every=int(w.refit_every),
        window=int(w.z_window), z_min_periods=int(w.z_min_periods),
        changes_resid=inputs.changes_resid,
        changes_resid_fn=lambda y, x: expanding_changes_residual(
            y, x, min_periods=int(w.fit_min_periods),
            refit_every=int(w.refit_every)).residual,
        drift_window=int(w.drift),
        iv_bp_day=inputs.iv_bp_day,
        iv_z_window=int(w.iv_z_window), iv_z_min_periods=int(w.iv_z_min_periods),
    )


# ---------------------------------------------------------------- the row


def _held_days(sign: pd.Series) -> int:
    """How many days the CURRENT sign has already been on, ending yesterday.

    Zero when today is flat or is a fresh entry. The distinction is not
    cosmetic: ``entry_vintage_signals`` prices a continuing hold on the z FROZEN
    at entry, so on a held day the live ``residual_z`` this row reports is not
    the number that priced the decision.
    """
    s = pd.Series(sign).fillna(0).astype(int)
    if len(s) < 2 or int(s.iloc[-1]) == 0:
        return 0
    today = int(s.iloc[-1])
    run = 0
    for v in reversed(s.iloc[:-1].tolist()):
        if int(v) != today:
            break
        run += 1
    return run


def _frozen_z_at(inputs: PairInputs, entry_ts, ts) -> float:
    """The entry-vintage z at ``ts`` for an episode opened at ``entry_ts``.

    ``entry_vintage_signals`` prices a continuing hold on a residual re-derived
    from the beta vector FROZEN at entry, not from the latest expanding fit, and
    z-scores that residual with the same trailing window before lagging it one
    day. This reproduces that computation from ``fit.betas`` so the row can
    report the number that actually decided it (``decision_z``) beside the live
    one (``residual_z``), instead of reporting the live one next to a ``reason``
    string quoting a different figure. The reproduction is pinned against the
    engine's own ``reason`` by
    ``test_decision_z_is_the_number_the_engines_reason_quotes``.
    """
    idx = inputs.panel.index
    betas = inputs.fit.betas
    if entry_ts not in betas.index:
        return float("nan")
    driver_cols = [c for c in betas.columns if c not in ("const", "vintage_date")]
    b = betas.loc[entry_ts]
    coef = b[["const"] + driver_cols].astype(float)
    if not np.isfinite(coef.to_numpy()).all():
        return float("nan")
    y = pd.Series(inputs.spread_bp).astype(float).reindex(idx)
    X = pd.DataFrame({k: pd.Series(v).astype(float)
                      for k, v in inputs.drivers.items()}).reindex(idx)
    pred = float(coef["const"]) + sum(float(coef[c]) * X[c] for c in driver_cols)
    frozen = residual_z(y - pred, window=int(inputs.windows.z_window),
                        min_periods=int(inputs.windows.z_min_periods)).shift(1)
    return float(frozen.get(ts, float("nan")))


def _note(mv: MarketVerdict, flags, uncertified, *, verdict: str) -> str:
    return (
        f"{verdict}: DSR {mv.dsr_prob:.2e} on {mv.n_trials} declared trials, "
        f"net {mv.net_1x_bp:+.1f}bp at 1x costs, break-even cost multiplier "
        f"{mv.breakeven_cost_mult:+.2f}x (measured on {mv.pair_name}, "
        f"{mv.sample_start}..{mv.sample_end}). "
        f"Binding requirements met: {6 - len(flags.unmet)} of 6"
        + (f"; unmet: {', '.join(flags.unmet)}" if flags.unmet else "")
        + f" (requirement 6 was measured NOT MET in Task 19, p = {PLACEBO_P_VALUE}, "
        "and a daily runner has no completed backtest to re-run it on). "
        f"Uncertified signal inputs: {', '.join(uncertified)} -- "
        "be_over_realized SETS THE SIGN and no argument to causal_signals can "
        "certify it. "
        "This row is a TARGET implied by the published rulebook on this date, "
        "not a recommendation: the rule is stateless, so the target changes "
        "whenever the signal does, and that turnover is what the cost schedule "
        "bites on (costs are 41% of gross at 1x, 83% at 2x)."
    )


def state_row(
    inputs: PairInputs,
    signals: pd.DataFrame,
    cfg: SignalConfig,
    *,
    asof: Optional[dt.date] = None,
) -> dict:
    """One output row: the last signal, the panel that decided it, and the verdict.

    **Every diagnostic is read at the INFORMATION date**, ``panel.index[-2]``,
    because ``build_signals`` decides date ``t`` from the panel row for ``t-1``.
    Reading them at ``signal_date`` would put yesterday's reason next to today's
    numbers -- see the module docstring.
    """
    panel = inputs.panel
    if len(panel) < 2 or len(signals) < 2:
        raise ValueError(
            f"{inputs.pair.name}: a lag-1 signal needs at least two rows "
            f"(panel {len(panel)}, signals {len(signals)}). The signal for a "
            "date is decided on the previous date's panel row, so a single-row "
            "panel has no information date to report."
        )
    signal_date = signals.index[-1]
    info_date = panel.index[-2]
    p = panel.loc[info_date]
    sig = signals.iloc[-1]

    attrs = dict(getattr(signals, "attrs", {}) or {})
    flags = _derive_requirements(signals, (), None, None)
    certified = tuple(attrs.get("certified_signal_inputs", ()))
    uncertified = tuple(attrs.get("uncertified_signal_inputs",
                                  UNCERTIFIED_SIGNAL_INPUTS))

    mv = market_verdict(inputs.pair.market)
    v = mv.verdict
    held = _held_days(signals["sign"])
    live_z = float(inputs.residual_z.loc[info_date])
    # On a fresh entry (or a flat day) the live z IS the decision input; on a
    # continuing hold the engine priced the row on the entry-vintage z, which
    # is a different number and is what `reason` quotes.
    decision_z = (live_z if held == 0
                  else _frozen_z_at(inputs, signals.index[len(signals) - 1 - held],
                                    signal_date))

    row = {
        "pair": inputs.pair.name,
        "market": inputs.pair.market,
        "asof": pd.Timestamp(asof) if asof is not None else signal_date,
        "signal_date": signal_date,
        "information_date": info_date,
        "spread_bp": float(p["spread_bp"]),
        "breakeven_h25": float(p["breakeven_h25"]),
        "realized_vol_bp_day": float(p["realized_vol_bp_day"]),
        "spread_vol_bp_day": float(p["spread_vol_bp_day"]),
        "implied_bp_day": float(p["implied_bp_day"]),
        "be_over_realized": float(p["be_over_realized"]),
        "be_over_implied": float(p["be_over_implied"]),
        "be_over_spread_vol": float(p["be_over_spread_vol"]),
        "drift_t": float(p["drift_t"]),
        "iv_z": float(p["iv_z"]),
        "residual_z": live_z,
        "decision_z": decision_z,
        "residual_z_is_decision_input": bool(held == 0),
        "held_days": int(held),
        "beta_vintage_date": sig.get("beta_vintage_date", pd.NaT),
        "sign": int(sig["sign"]),
        "size": float(sig["size"]),
        "dv01_usd": float(sig["sign"]) * float(sig["size"]) * cfg.base_dv01_usd,
        "reason": str(sig["reason"]),
        "sample_start": panel.index.min(),
        "sample_end": panel.index.max(),
        "n_obs": int(len(panel)),
        "verdict": v,
        "verdict_pair": mv.pair_name,
        "verdict_is_for_this_pair": bool(mv.pair_name == inputs.pair.name),
        "verdict_basis": mv.basis,
        "dsr_prob": float(mv.dsr_prob),
        "n_trials": int(mv.n_trials),
        "gross_bp": float(mv.gross_bp),
        "net_1x_bp": float(mv.net_1x_bp),
        "net_2x_bp": float(mv.net_2x_bp),
        "breakeven_cost_mult": float(mv.breakeven_cost_mult),
        "placebo_p_value": float(PLACEBO_P_VALUE),
        "requirements_met": bool(flags.all_met),
        "unmet_requirements": tuple(flags.unmet),
        "certified_signal_inputs": certified,
        "uncertified_signal_inputs": uncertified,
        "sign_input_certified": bool("be_over_realized" in certified),
        "note": _note(mv, flags, uncertified, verdict=v),
    }
    row.update(flags.as_columns("req_"))
    missing = [c for c in REQUIRED_OUTPUT_COLUMNS if c not in row]
    if missing:
        raise AssertionError(f"state_row omitted required columns: {missing}")
    return row


def pair_state(
    pair: ForwardPair,
    greeks: pd.DataFrame,
    iv_bp_day: pd.Series,
    *,
    cfg: Optional[SignalConfig] = None,
    umep: Optional[pd.Series] = None,
    windows: SignalWindows = SignalWindows(),
    asof: Optional[dt.date] = None,
) -> dict:
    """``build_pair_inputs`` -> ``certified_signals`` -> ``state_row``."""
    cfg = cfg or SignalConfig()
    inputs = build_pair_inputs(pair, greeks, iv_bp_day, umep=umep, windows=windows)
    return state_row(inputs, certified_signals(inputs, cfg), cfg, asof=asof)


# --------------------------------------------------------------- the caches


def _greeks_cache_path(pair: ForwardPair, cache_dir) -> Path:
    """One file per pair, fingerprinted by the pair's own identity.

    Same house pattern as ``panels._cache_path_for_legs``: a hex digest of the
    identifying string, truncated, so one file only ever holds one schema.
    """
    key = f"{pair.market}|{pair.curve_name}|{pair.short.label}|{pair.long.label}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:8]
    stem = f"greeks__{pair.market}_{pair.short.label}_{pair.long.label}__{digest}"
    return Path(cache_dir) / f"{stem}.parquet"


def greeks_with_cache(
    pair: ForwardPair,
    dates: Sequence,
    *,
    fetch_curves: Callable[[Sequence[dt.date]], dict],
    cache_dir=CACHE_DIR,
    panel_fn: Callable[[dict, ForwardPair], pd.DataFrame] = greeks_panel,
) -> pd.DataFrame:
    """``greeks_panel`` for ``dates``, computing only the dates not already cached.

    ``greeks_panel`` reprices the package nine times per date, which is the
    expensive part of a daily run; a runner re-invoked every morning should pay
    it once per date ever. The cache is per pair and additive: a run asks
    ``fetch_curves`` only for the dates it does not already hold, merges, and
    returns exactly the requested dates.

    **A date the provider cannot serve is re-requested on every run.** Market
    holidays inside a ``bdate_range`` never enter the cache (they have no
    curve), so they stay in the missing set forever. That is deliberate: a
    permanently-negative cache would also swallow a transient provider failure,
    and the re-request is cheap -- a curve the MDP has no data for costs no
    repricing.
    """
    path = _greeks_cache_path(pair, cache_dir)
    cached: Optional[pd.DataFrame] = None
    if path.exists():
        cached = pd.read_parquet(path)
        cached.index = pd.to_datetime(cached.index)

    wanted = pd.DatetimeIndex(sorted({pd.Timestamp(d) for d in dates}))
    have = cached.index if cached is not None else pd.DatetimeIndex([])
    missing = wanted.difference(have)

    if len(missing):
        curves = fetch_curves([ts.date() for ts in missing])
        curves = {pd.Timestamp(k): v for k, v in curves.items()
                  if v is not None and k != "live"}
        if curves:
            fresh = panel_fn(curves, pair)
            if not fresh.empty:
                fresh.index = pd.to_datetime(fresh.index)
                cached = fresh if cached is None else fresh.combine_first(cached)
                path.parent.mkdir(parents=True, exist_ok=True)
                cached.sort_index().to_parquet(path)

    if cached is None:
        return pd.DataFrame()
    return cached.loc[cached.index.isin(wanted)].sort_index()


# ---------------------------------------------------------------- the runner


def _market_curve_fetcher(market: str, *, mdp, n_jobs: int):
    """Fetch curves a year at a time, isolating a failing chunk.

    One stale cache entry once took a whole market down: GBP-SONIA's 2026-07-31
    payload had been serialized by an older rateslib and ``from_json`` raised
    ``JSONDecodeError`` on its ``convention`` field, failing the bulk request
    for 199 dates over one of them. A market that returns nothing looks exactly
    like a market with no data.
    """
    curve_name = MARKET_CURVES[market]

    def fetch(dates: Sequence[dt.date]) -> dict:
        out: dict = {}
        by_year: Dict[int, list] = {}
        for d in dates:
            by_year.setdefault(d.year, []).append(d)
        for year in sorted(by_year):
            try:
                cm = mdp.bulk_get_data({"curve_name": curve_name,
                                        "timestamps": by_year[year],
                                        "n_jobs": n_jobs})
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s %s: curve chunk failed -- %s: %s",
                               market, year, type(exc).__name__, exc)
                continue
            for k, v in cm.items():
                if v is None or k == "live":
                    continue
                out[pd.Timestamp(k)] = v
        return out

    return fetch


def today_state(
    asof: Optional[dt.date] = None,
    *,
    markets: Sequence[str] = ("USD", "EUR", "JPY", "GBP"),
    lookback_days: int = 750,
    cfg: Optional[SignalConfig] = None,
    windows: SignalWindows = SignalWindows(),
    with_umep: bool = False,
    mdp=None,
    cache_dir=CACHE_DIR,
    n_jobs: int = 4,
) -> pd.DataFrame:
    """One row per supported pair: today's state, and what the study measured.

    ``lookback_days`` is in BUSINESS days of usable panel; the calendar window
    requested is ``1.5x`` that, which is roughly the business/calendar ratio.
    The default 750 leaves ~800 rows against ``windows.warmup_rows`` of 378, so
    the rule has ~420 usable dates and the causality audit's 75% cut is far from
    the warm-up. A shorter lookback silently produces "no valuation" rows,
    because ``signal_state`` fails CLOSED on a NaN.

    Curves are fetched once per market and shared across that market's pairs;
    the per-pair greeks panel is cached incrementally (:func:`greeks_with_cache`)
    so a daily re-run prices only the new day.

    ``with_umep`` is off by default: Task 21 ran implied vol alone in all four
    markets, so that is the model the stored verdict describes.
    """
    cfg = cfg or SignalConfig()
    asof = asof or dt.date.today()
    start = asof - dt.timedelta(days=int(lookback_days * 1.5))
    if mdp is None:
        os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source="GSQUANT-RL")

    rows = []
    for market in markets:
        pairs = supported_pairs([p for p in ALL_PAIRS if p.market == market])
        if not pairs:
            continue
        # Today itself is dropped: the MDP resolves a request for today to the
        # "live" snapshot, which comes back under the key "live" and cannot be
        # placed on a DatetimeIndex (the same trap `panels.forward_rate_panel`
        # raises on). `asof` and `signal_date` are emitted separately so the
        # resulting one-day gap is visible rather than inferred.
        today = dt.date.today()
        dates = [d for d in pd.bdate_range(start, asof).date.tolist() if d != today]
        fetch = _market_curve_fetcher(market, mdp=mdp, n_jobs=n_jobs)
        try:
            iv = vol_panel(VOL_CURVE_BY_MARKET[market], [VOL_STRUCTURE],
                           start, asof,
                           cache_path=Path(cache_dir) / "vol.parquet")
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: no swaption vols (%s: %s) -- skipping the "
                           "market; the driver, the gate and the valuation all "
                           "rest on them", market, type(exc).__name__, exc)
            continue
        iv_col = VOL_STRUCTURE.replace(" ", "")
        if iv_col not in iv.columns:
            logger.warning("%s: vol panel has no %s column", market, iv_col)
            continue
        iv_bp_day = iv[iv_col].astype(float)

        umep = None
        if with_umep and market == "USD":
            from RVUtils.StrikelessVol.panels import umep_panel

            umep_df = umep_panel(start, asof)
            if not umep_df.empty:
                umep = umep_df["umep_bp_per_year"].astype(float)

        for pair in pairs:
            greeks = greeks_with_cache(pair, dates, fetch_curves=fetch,
                                       cache_dir=cache_dir)
            if greeks.empty or len(greeks) < 2:
                logger.warning("%s: %d greeks rows -- skipped", pair.name,
                               len(greeks))
                continue
            try:
                rows.append(pair_state(pair, greeks, iv_bp_day, cfg=cfg,
                                       umep=umep, windows=windows, asof=asof))
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: no state (%s: %s)", pair.name,
                               type(exc).__name__, exc, exc_info=True)

    if not rows:
        return pd.DataFrame(columns=list(REQUIRED_OUTPUT_COLUMNS))
    return pd.DataFrame(rows)[list(REQUIRED_OUTPUT_COLUMNS)]


def format_state(out: pd.DataFrame) -> str:
    """A human-readable block per row, verdict first. For notebooks and logs."""
    lines = []
    for _, r in out.iterrows():
        lines.append(
            f"{r['pair']:24s} signal {r['signal_date'].date()} "
            f"(decided on {r['information_date'].date()})  "
            f"sign {int(r['sign']):+d} size {float(r['size']):.3f} "
            f"target dv01 ${float(r['dv01_usd']):>12,.0f}\n"
            f"    reason        : {r['reason']}\n"
            f"    BE/RV {r['be_over_realized']:.3f} (rate vol) | "
            f"{r['be_over_spread_vol']:.3f} (spread vol)  "
            f"BE {r['breakeven_h25']:.3f}bp/d  RV {r['realized_vol_bp_day']:.3f}bp/d  "
            f"IV {r['implied_bp_day']:.3f}bp/d\n"
            f"    z live {r['residual_z']:+.2f}  z that decided this row "
            f"{r['decision_z']:+.2f} "
            f"({'live -- fresh entry or flat' if r['residual_z_is_decision_input'] else 'FROZEN at entry -- the hold is priced on this, not on the live z'})  "
            f"drift_t {r['drift_t']:+.2f}  iv_z {r['iv_z']:+.2f}  "
            f"held {int(r['held_days'])}d\n"
            f"    VERDICT       : {r['note']}\n"
            f"    certified     : {r['certified_signal_inputs']}\n"
            f"    uncertified   : {r['uncertified_signal_inputs']}"
        )
    return "\n\n".join(lines)
