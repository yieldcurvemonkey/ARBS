"""Run the rule down real (or synthetic) paths and grid over its parameters.

Every number here is reported at three cost multipliers, at both roll-charge
conventions, and deflated by the FULL trial count across all pairs and
families. The top row of a sweep is never the verdict.

**The six binding requirements (Task 15) are enforced here as code paths, not
as report strings.** Task 15 produced a +8.46bp/trade headline that collapsed
to -1.87bp once they were applied, and every one of the four uncontrolled
choices that produced it happened to flatter the conclusion. So each is
implemented as something the engine either DOES or refuses to claim:

1. **Expanding betas** -- :func:`RVUtils.StrikelessVol.factors.expanding_residual`
   is the only supported residual source for a signal, and
   :func:`audit_causal_betas` *verifies* it by shocking the tail of the input
   and confirming the head of the residual does not move. A full-sample fit
   fails that audit by more than a basis point, which is how the checker was
   itself checked against an input whose answer was already known. **The audit
   is tied to the artifact**: :func:`causal_signals` requires the residual it is
   about to use to reproduce the audited baseline and raises otherwise --
   without that link the audit describes a function while the signal comes from
   a series, and a full-sample fit collected a clean certificate.
2. **Hedge frozen at entry vintage** -- :func:`entry_vintage_signals` freezes
   the beta vector on the entry date, re-derives the residual z from THAT vector
   for the whole hold, and stamps how far the frozen z diverged from the live
   one. :func:`run_pair` requires that stamp AND per-episode constancy of
   ``beta_vintage_date``: the label alone is satisfied by any constant column,
   and mutation M8 shows it stays frozen even when the hold is priced on the
   live z.
3. **Rolling-sigma z** -- :func:`audit_rolling_sigma_z` recomputes the z from
   the residual with a trailing 252-day window and rejects any z that does not
   reproduce; :func:`causal_signals` additionally checks the z's OWN causality
   against the shocked run, so the stamp is not a tautology on the path that
   builds the z itself. A full-sample-sigma z fails both legs.
4. **Spread-leg P&L, never residual P&L** -- there is no residual-P&L path in
   this module. ``daily_pnl`` IS ``ledger["total"]`` from
   :func:`replication.simulate`, i.e. the repriced package the book actually
   holds. The residual is a sizing input and never a P&L series.
5. **Distinct episodes** -- :func:`_extract_trades` derives episodes from
   ``sign`` transitions and :func:`_assert_disjoint` raises if any two
   overlap, so an overlapping-window count cannot be reported as a trade
   count.
6. **Random-walk placebo** -- :func:`random_walk_placebo` runs a null with no
   relationship to vol through the identical pipeline; the requirement is met
   only when the real headline beats it at the stated alpha. If the placebo
   clears the criterion, the criterion is the finding.

A row that cannot report all six met is **not eligible for an ALIVE verdict**
(:func:`report.league_table` enforces the downgrade).

Two naming rules, both from measured defects:

* Dollar ledger values are named ``*_usd``. The ``*_bp`` columns divide by the
  **realised** average DV01 of the book on the days it was held, not by the
  design notional -- Task 13 measured the realised book at a mean of $98,813
  with a daily range of $52,672 to $148,915 against a $100,000 target.
* Use ``harvest_flow_ratio`` (gross daily absolute flows -- a book-size
  measure) and ``harvest_pnl_share`` (the signed contribution share). The old
  ``harvest_to_mtm`` is not reintroduced.

Ranking is on vol correlation, ``harvest_pnl_share`` and carry sign. **Never on
Sharpe**: both of Task 13's placebo pairs out-Sharpe every real pair while
running the opposite carry sign, and a DV01-matched zero-convexity twin
(:class:`replication.ZeroConvexityPricer`) beats the real package on skew,
Sharpe and vol correlation on zero gamma. ``report.league_table`` refuses a
Sharpe ranking key outright.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.costs import CostSchedule, charge_usd
from RVUtils.StrikelessVol.factors import (
    WalkForwardFit,
    drift,
    expanding_residual,
    residual_z,
)
from RVUtils.StrikelessVol.replication import (
    TRADED_DV01_COLS,
    ReplicationConfig,
    reconcile,
    simulate,
)
from RVUtils.StrikelessVol.report import distribution_stats
from RVUtils.StrikelessVol.strategy import SignalConfig, build_signals, signal_state

__all__ = [
    "BacktestResult",
    "PlaceboResult",
    "RequirementFlags",
    "REQUIREMENTS",
    "audit_causal_betas",
    "audit_rolling_sigma_z",
    "build_config_grid",
    "causal_signals",
    "entry_vintage_signals",
    "random_walk_like",
    "random_walk_placebo",
    "run_grid",
    "run_pair",
    "with_placebo",
]

#: The six binding requirements, in the order they are reported.
REQUIREMENTS: Tuple[str, ...] = (
    "expanding_betas",
    "entry_vintage_hedge",
    "rolling_sigma_z",
    "spread_leg_pnl",
    "distinct_episodes",
    "random_walk_placebo",
)

PNL_BUCKETS = ("carry", "harvest", "mtm", "cross")
LEDGER_COLS = ("carry", "harvest", "mtm", "cross", "cost")

#: Inputs that reach a trading decision and are **not** covered by any audit in
#: this module. Enumerated rather than discovered: four passes on
#: :func:`causal_signals` each found the certificate attached to something
#: *adjacent* to the object the signal is built from -- the re-derivation
#: instead of the fit, the builder instead of its output, the residual instead
#: of the betas the z is computed from. The check that would have found each
#: earlier is "name every input to the decision, and say what certifies it", so
#: that list is written down here where it can be read next to the certificate.
#:
#: ``signal_state`` consumes five panel columns. Exactly ONE of them is audited:
#:
#: * ``residual_z`` -- **certified** (expanding fit, betas-vs-residual
#:   consistency, head- and tail-shock probes, trailing-sigma reproduction,
#:   entry-vintage freeze).
#: * ``be_over_realized`` -- sets the SIGN. Uncertified: built upstream in
#:   Task 10 and passed through ``causal_signals`` untouched.
#: * ``drift_t`` -- vetoes a flattener. Uncertified (Task 16).
#: * ``spread_vol_bp_day`` -- sets the SIZE by risk parity. Uncertified.
#: * ``iv_z`` -- gates the steepener. Uncertified.
#:
#: plus the regression DRIVERS themselves: :func:`audit_causal_betas` shocks
#: only the dependent variable, so a driver built with future information (a
#: full-sample-standardised or smoothed factor) is invisible to every check
#: here.
#:
#: A certified ``residual_z`` therefore does NOT make the signal causal. It
#: makes one of its five inputs causal. Anything asserting requirement 1 for the
#: rule as a whole has to establish the other four separately.
UNCERTIFIED_SIGNAL_INPUTS: Tuple[str, ...] = (
    "be_over_realized", "drift_t", "spread_vol_bp_day", "iv_z", "drivers",
)

CAUSALITY_TOL: float = 1e-9
ROLLING_Z_TOL: float = 1e-8
#: How closely a caller-supplied ``fit`` must reproduce the audited causal one.
#: The fit is deterministic for identical inputs, so this is float noise, not a
#: modelling tolerance.
FIT_MATCH_TOL: float = 1e-6


@dataclass(frozen=True)
class RequirementFlags:
    """Met / not met for each of the six, with the evidence that decided it.

    Everything defaults to **False**. A caller who supplies no evidence gets no
    credit -- the failure mode this guards against is a result that quietly
    inherits an ALIVE verdict because nobody wired the checks up.
    """

    expanding_betas: bool = False
    entry_vintage_hedge: bool = False
    rolling_sigma_z: bool = False
    spread_leg_pnl: bool = False
    distinct_episodes: bool = False
    random_walk_placebo: bool = False
    evidence: dict = field(default_factory=dict, repr=False)

    @property
    def all_met(self) -> bool:
        return all(bool(getattr(self, name)) for name in REQUIREMENTS)

    @property
    def unmet(self) -> Tuple[str, ...]:
        return tuple(name for name in REQUIREMENTS if not bool(getattr(self, name)))

    def as_columns(self, prefix: str = "req_") -> dict:
        return {f"{prefix}{name}": bool(getattr(self, name)) for name in REQUIREMENTS}


@dataclass(frozen=True)
class BacktestResult:
    pair_name: str
    config: dict
    daily_pnl: pd.Series
    ledger: pd.DataFrame = field(repr=False)
    trades: pd.DataFrame = field(repr=False)
    stats: dict = field(default_factory=dict)
    requirements: RequirementFlags = field(default_factory=RequirementFlags)
    #: What ``daily_pnl`` IS. Requirement 4 exists because the residual and the
    #: spread leg had OPPOSITE signs at the same entries: the residual gained
    #: while the leg the book actually holds lost 2.6-3.7bp.
    pnl_source: str = "spread_leg_ledger"

    def with_requirements(self, flags: RequirementFlags) -> "BacktestResult":
        return replace(self, requirements=flags)


# ------------------------------------------------------------------ turnover


def _turnover_split(scale: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Split each day's change in book size into risk OPENED and risk CLOSED.

    Needed because episodes must be disjoint (requirement 5) while a direct
    sign flip trades both sides on one date: the closing leg belongs to the
    episode ending, the opening leg to the one beginning. Summed, the two
    always equal ``|d scale|``, so no turnover is invented or lost.
    """
    s = pd.Series(scale).astype(float).fillna(0.0).to_numpy()
    prev = np.concatenate([[0.0], s[:-1]])
    same_side = (np.sign(s) * np.sign(prev)) > 0
    a, p = np.abs(s), np.abs(prev)
    opened = np.where(same_side, np.maximum(a - p, 0.0), a)
    closed = np.where(same_side, np.maximum(p - a, 0.0), p)
    return (pd.Series(opened, index=scale.index),
            pd.Series(closed, index=scale.index))


# ------------------------------------------------------------------ episodes


def _sign_blocks(sign: pd.Series) -> List[tuple]:
    """``[(entry, last_held, sign), ...]`` -- one per continuously held episode.

    ``last_held`` is the LAST date the position was on, not the first flat day,
    so consecutive episodes cannot share a boundary date and a sign flip
    produces two disjoint blocks rather than two that overlap by a day.
    """
    s = pd.Series(sign).fillna(0).astype(int)
    blocks: List[tuple] = []
    start = None
    cur = 0
    prev_ts = None
    for ts, v in s.items():
        if v != cur:
            if cur != 0 and start is not None:
                blocks.append((start, prev_ts, cur))
            start = ts if v != 0 else None
            cur = int(v)
        prev_ts = ts
    if cur != 0 and start is not None:
        blocks.append((start, prev_ts, cur))
    return blocks


def _assert_disjoint(blocks: Sequence[tuple]) -> None:
    """Requirement 5's teeth: overlapping windows are not independent trades.

    Nine years of the study window yielded 9-30 genuinely distinct episodes.
    Counting a rolling 21-day window opened every day as 21x that many trades
    is the single cheapest way to make a DSR penalty disappear, so an
    overlapping episode list is an error here, not a warning.
    """
    ordered = sorted(blocks, key=lambda b: b[0])
    for (e0, x0, _), (e1, _, _) in zip(ordered, ordered[1:]):
        if e1 <= x0:
            raise ValueError(
                f"episodes overlap: [{e0} .. {x0}] and [{e1} .. ] -- overlapping "
                "windows are not independent trades"
            )


def _extract_trades(
    signals: pd.DataFrame,
    ledger: pd.DataFrame,
    *,
    open_fee: pd.Series,
    close_fee: pd.Series,
) -> pd.DataFrame:
    """One row per DISTINCT held episode, so per-trade statistics are defined.

    The exit fee is charged on the first day the position is off, which is the
    day it was actually paid; it is attributed to the episode that closed, and
    on a direct flip the SAME date's opening fee is attributed to the episode
    that opened. Every dollar of turnover therefore lands in exactly one
    episode, which is what makes ``sum(trades.cost_usd)`` reconcile to the
    ledger.

    Column naming (amended after Task 13): the dollar columns say ``_usd``. The
    ``_bp`` columns divide by ``avg_dv01_usd``, the REALISED average DV01 over
    the episode -- not the $100k design notional, which the realised book
    misses by -47% to +49% day to day. Do not compare dollar P&L across roll
    frequencies or trigger widths without that normalisation, and note that a
    regression beta of P&L on the spread is the ``d(spread)**2``-weighted DV01
    rather than the book's size.
    """
    blocks = _sign_blocks(signals["sign"])
    _assert_disjoint(blocks)
    idx = ledger.index
    pos = {ts: i for i, ts in enumerate(idx)}
    rows = []
    for entry, last_held, s in blocks:
        seg = ledger.loc[entry:last_held]
        gross = float(seg[list(PNL_BUCKETS)].sum().sum())
        # fees: everything inside the hold, plus the closing fee on the day after
        fee = float(open_fee.loc[entry:last_held].sum()
                    + close_fee.loc[entry:last_held].sum())
        fee -= float(close_fee.loc[entry])           # that one closed the PREVIOUS episode
        fee += float(seg["cost_carry_usd"].sum())    # hedges and rolls during the hold
        j = pos[last_held] + 1
        if j < len(idx):
            fee += float(close_fee.iloc[j])
        avg_dv01 = float(seg["realised_dv01_usd"].mean())
        net = gross - fee
        denom = avg_dv01 if np.isfinite(avg_dv01) and avg_dv01 != 0.0 else np.nan
        rows.append({
            "entry": entry,
            "exit": last_held,
            "sign": int(s),
            "n_days": int(len(seg)),
            "avg_dv01_usd": avg_dv01,
            "gross_usd": gross,
            "cost_usd": fee,
            "net_usd": net,
            "gross_bp": gross / denom,
            "cost_bp": fee / denom,
            "net_bp": net / denom,
        })
    return pd.DataFrame(rows, columns=[
        "entry", "exit", "sign", "n_days", "avg_dv01_usd",
        "gross_usd", "cost_usd", "net_usd", "gross_bp", "cost_bp", "net_bp",
    ])


# ------------------------------------------------------------------ run_pair


def _entry_vintage_verified(signals: pd.DataFrame) -> Tuple[bool, dict]:
    """Requirement 2, re-derived from the data rather than from a flag.

    Re-hedging with later-known betas is the same look-ahead in a different
    hat: it is what took a +3.80bp gross result to +0.13bp. So the check is
    that the beta vintage each episode was opened on is the ONLY vintage used
    while it was held.
    """
    if "beta_vintage_date" not in signals.columns:
        return False, {"reason": "no beta_vintage_date column"}
    blocks = _sign_blocks(signals["sign"])
    if not blocks:
        return False, {"reason": "no episodes to check"}
    moved = []
    for entry, last_held, _ in blocks:
        vintages = signals.loc[entry:last_held, "beta_vintage_date"].dropna().unique()
        if len(vintages) != 1:
            moved.append((entry, last_held, int(len(vintages))))
    return (not moved), {"episodes": len(blocks), "re_hedged_episodes": moved[:5],
                         "n_re_hedged": len(moved)}


def run_pair(
    ctx,
    signals: pd.DataFrame,
    *,
    rep_cfg: ReplicationConfig,
    costs: CostSchedule,
    pair_name: str,
    book: str = "package",
    placebo: "Optional[PlaceboResult]" = None,
    unit: Optional[pd.DataFrame] = None,
    dv01_unit: Optional[pd.Series] = None,
) -> BacktestResult:
    """Simulate the replication and scale each day by that day's signal.

    The signal is already lag-1 (``strategy.build_signals``). Scaling the
    simulated unit-package P&L is exact for the linear ledgers and correct to
    first order for the harvest; positions are opened and closed at signal
    changes, and the cost of those changes is charged here rather than inside
    ``simulate``, which knows only about hedges and rolls.

    Two things this deliberately does NOT do, both of which were defects in the
    first draft of the specification:

    * It does not charge the entry twice. ``simulate`` books an initiation fee
      on its first row because the static book opens there; a signal-driven
      book opens when the SIGNAL opens, so that fee is dropped and the whole
      entry/exit charge comes from the turnover split. The original scaled the
      simulate fee AND charged a turn on the same date.
    * It does not divide dollars by the design notional to call them basis
      points. ``realised_dv01_usd`` is computed from the notionals actually
      held on each date, and that is the ``_bp`` divisor.

    ``unit``/``dv01_unit`` let :func:`run_grid` reuse one simulation across
    every config that shares a replication config -- 972 signal configs do not
    mean 972 repricings, and on real curves the pricer is nearly all of the
    runtime.
    """
    if not signals.index.is_monotonic_increasing:
        raise ValueError(
            "signals must be sorted by date: the episode extraction slices the "
            "ledger by label, so an unsorted index silently mis-attributes P&L"
        )
    dates = list(signals.index)
    if unit is None:
        unit = simulate(ctx, dates, rep_cfg, costs)
    elif not unit.index.equals(signals.index):
        # a memoised simulation reused against a different date range would
        # align by label and silently drop or invent days
        raise ValueError(
            "supplied `unit` ledger is indexed differently from `signals`; a "
            "reused simulation must cover exactly the same dates"
        )
    if dv01_unit is None:
        dv01_unit = pd.Series(
            [abs(float(ctx.dv01(d, "long"))) for d in unit.index], index=unit.index
        )

    scale = (signals["dv01_usd"].astype(float) / rep_cfg.package_dv01_usd)
    scale = scale.reindex(unit.index).fillna(0.0)
    abs_scale = scale.abs()

    ledger = unit.copy()
    for col in PNL_BUCKETS:
        ledger[col] = unit[col] * scale

    # The realised book: DV01 neutrality is what the rule fixes, not DV01 size.
    ledger["realised_dv01_usd"] = (
        unit["long_notional"].abs() * dv01_unit * abs_scale
    )

    opened, closed = _turnover_split(scale)
    pkg = abs(float(rep_cfg.package_dv01_usd))
    ledger["initiate_dv01_usd"] = (opened + closed) * pkg
    ledger["hedge_dv01_usd"] = unit["hedge_dv01_usd"] * abs_scale
    ledger["roll_dv01_usd"] = unit["roll_dv01_usd"] * abs_scale

    open_fee = charge_usd(pd.DataFrame({"initiate_dv01_usd": opened * pkg},
                                       index=unit.index), costs)
    close_fee = charge_usd(pd.DataFrame({"initiate_dv01_usd": closed * pkg},
                                        index=unit.index), costs)
    carry_fee = charge_usd(ledger[["hedge_dv01_usd", "roll_dv01_usd"]], costs)
    ledger["cost_carry_usd"] = carry_fee
    ledger["cost"] = -(open_fee + close_fee + carry_fee)
    ledger["total"] = ledger[list(LEDGER_COLS)].sum(axis=1)

    trades = _extract_trades(signals, ledger, open_fee=open_fee, close_fee=close_fee)

    held = ledger["realised_dv01_usd"][abs_scale > 0]
    realised_mean = float(held.mean()) if len(held) else float("nan")

    stats = distribution_stats(ledger["total"])
    stats["n_distinct_episodes"] = int(len(trades))
    stats["realised_dv01_mean_usd"] = realised_mean
    stats["total_net_usd"] = float(ledger["total"].sum())
    stats["total_net_bp"] = (
        float(ledger["total"].sum() / realised_mean)
        if np.isfinite(realised_mean) and realised_mean else float("nan")
    )
    stats["reconciliation"] = reconcile(ledger)

    flags = _derive_requirements(signals, trades, placebo)
    return BacktestResult(
        pair_name=pair_name,
        config={"trigger_bp": rep_cfg.trigger_bp, "roll_months": rep_cfg.roll_months,
                "sign": rep_cfg.sign, "cost_multiplier": costs.multiplier,
                "book": book},
        daily_pnl=ledger["total"],
        ledger=ledger,
        trades=trades,
        stats=stats,
        requirements=flags,
        pnl_source="spread_leg_ledger",
    )


def _derive_requirements(signals, trades, placebo) -> RequirementFlags:
    """Requirements 1/3 come from verified provenance, 2/4/5 are re-derived here."""
    attrs = getattr(signals, "attrs", {}) or {}
    causal_diff = attrs.get("causal_max_abs_diff", float("nan"))
    z_diff = attrs.get("rolling_z_max_abs_diff", float("nan"))
    expanding = bool(attrs.get("expanding_betas", False)
                     and np.isfinite(causal_diff) and causal_diff <= CAUSALITY_TOL)
    rolling = bool(attrs.get("rolling_sigma_z", False)
                   and np.isfinite(z_diff) and z_diff <= ROLLING_Z_TOL)
    # Requirement 2 needs the same shape of proof as 1 and 3: a stamp only
    # `entry_vintage_signals` sets, carrying a measured number, PLUS the
    # per-episode label check. The label alone is satisfied by any constant
    # column -- `beta_vintage_date = Timestamp("1999-01-01")` passed it -- which
    # made requirement 2 the one gate a hand-made frame could walk through.
    #
    # The deviation must be strictly POSITIVE, not merely finite: 0.0 is exactly
    # what a freeze that was never applied produces (frozen z == live z on every
    # held day), so accepting it accepts the thing the stamp exists to detect.
    #
    # Scope, stated because it is easy to over-read: this gate proves a frozen
    # vintage was USED and that it made a difference. It does NOT catch the M8
    # shape -- pricing the hold on the live z while leaving the label frozen --
    # because the deviation is measured on a different line from the pricing and
    # stays positive under that mutation. What catches M8 is the formula test,
    # `test_the_hold_is_priced_on_the_entry_vintage_z_not_the_live_z`. Do not
    # cite this gate as the enforcement for that behaviour.
    vintage_deviation = attrs.get("entry_vintage_frozen_z_deviation", float("nan"))
    vintage_ok, vintage_evidence = _entry_vintage_verified(signals)
    vintage_evidence["frozen_z_deviation"] = vintage_deviation
    return RequirementFlags(
        expanding_betas=expanding,
        entry_vintage_hedge=bool(vintage_ok
                                 and attrs.get("entry_vintage_hedge", False)
                                 and np.isfinite(vintage_deviation)
                                 and vintage_deviation > 0.0),
        rolling_sigma_z=rolling,
        # Structural: there is no residual-P&L path in this module at all.
        spread_leg_pnl=True,
        # Structural: _extract_trades raises rather than emit overlaps.
        distinct_episodes=True,
        random_walk_placebo=bool(placebo is not None and placebo.passes),
        evidence={
            "causal_max_abs_diff": causal_diff,
            "rolling_z_max_abs_diff": z_diff,
            "entry_vintage": vintage_evidence,
            "n_episodes": int(len(trades)),
            "placebo_p_value": placebo.p_value if placebo is not None else float("nan"),
        },
    )


def with_placebo(result: BacktestResult, placebo: "PlaceboResult") -> BacktestResult:
    """Attach a placebo run to an existing result. Returns a NEW result."""
    flags = replace(
        result.requirements,
        random_walk_placebo=bool(placebo.passes),
        evidence={**result.requirements.evidence,
                  "placebo_p_value": placebo.p_value,
                  "placebo_n_sims": placebo.n_sims},
    )
    return replace(result, requirements=flags)


# ---------------------------------------------------------------------- grid


def build_config_grid(
    *,
    trigger_bp: Sequence[float] = (10.0, 15.0, 20.0, 25.0, 30.0, 40.0),
    be_cheap: Sequence[float] = (0.6, 0.8, 0.9),
    be_rich: Sequence[float] = (1.1, 1.2, 1.5),
    z_entry: Sequence[float] = (1.0, 1.5, 2.0),
    drift_t_gate: Sequence[float] = (1.5, 2.0, float("inf")),
    short_side_enabled: Sequence[bool] = (True, False),
) -> List[dict]:
    """972 configs per pair, before markets. This is the DSR's trial count.

    ``deflated_for_grid`` must receive the FULL count across all pairs and all
    families, not this per-pair number -- see :func:`report.league_table`,
    which refuses a grid that only covers some of the pairs it is ranking.
    """
    axes = {
        "trigger_bp": trigger_bp, "be_cheap": be_cheap, "be_rich": be_rich,
        "z_entry": z_entry, "drift_t_gate": drift_t_gate,
        "short_side_enabled": short_side_enabled,
    }
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*axes.values())]


_REP_FIELDS = set(ReplicationConfig.__dataclass_fields__)
_SIGNAL_FIELDS = set(SignalConfig.__dataclass_fields__)
_SIGNAL_OUTPUT_COLS = {"sign", "size", "dv01_usd"}


def _check_grid_keys(grid: Sequence[dict], *, prebuilt: bool, pair_name: str) -> None:
    """Refuse a grid whose axes this pair's source cannot actually sweep.

    Two silent no-ops, both measured:

    * **A prebuilt signal frame disables every signal axis.** ``run_grid`` reuses
      such a frame for every config, so six configs sweeping ``z_entry`` and
      ``be_cheap`` produced ONE distinct ``total_net_usd`` -- with the swept
      values faithfully printed in the columns. ``causal_signals``' output has
      exactly the columns that trigger the prebuilt path, and the parameter name
      ``signal_panel_by_pair`` invites passing it, so this is the likely
      accident, not an exotic one.
    * **An unknown or misspelled key is dropped.** ``{"zz_entry": 1.0}`` vs
      ``{"zz_entry": 9.9}`` gave two rows, one distinct result, and a tidy
      ``zz_entry`` column to read the difference off.

    A grid that cannot sweep what it says it sweeps is worse than no grid: it
    produces a full league table of identical results wearing different labels.
    """
    keys = {k for cfg in grid for k in cfg}
    unknown = sorted(keys - _REP_FIELDS - _SIGNAL_FIELDS)
    if unknown:
        raise ValueError(
            f"grid has key(s) {unknown} belonging to neither ReplicationConfig "
            f"{sorted(_REP_FIELDS)} nor SignalConfig. They would be swept in the "
            "output columns and ignored by the engine."
        )
    if prebuilt:
        blocked = sorted(keys & _SIGNAL_FIELDS)
        if blocked:
            raise ValueError(
                f"{pair_name}: the signal source is a PREBUILT signal frame "
                f"(it carries {sorted(_SIGNAL_OUTPUT_COLS)}), so it is reused "
                f"unchanged for every config -- but the grid sweeps {blocked}, "
                "which only a raw signal panel can vary. Every row would be the "
                "same run with different labels. Pass the raw panel (with "
                "strategy.REQUIRED_COLUMNS) plus a signal_builder, or drop the "
                "signal axes from the grid."
            )


def run_grid(
    ctx_by_pair: Dict[str, object],
    signal_panel_by_pair: Dict[str, pd.DataFrame],
    grid: Sequence[dict],
    *,
    costs: CostSchedule,
    base_signal_cfg: Optional[SignalConfig] = None,
    base_rep_cfg: Optional[ReplicationConfig] = None,
    comparator_ctx_by_pair: Optional[Dict[str, object]] = None,
    placebo_by_pair: Optional[dict] = None,
    signal_builder: Optional[Callable[[pd.DataFrame, SignalConfig], pd.DataFrame]] = None,
    keep_results: bool = False,
) -> pd.DataFrame:
    """One row per (pair, book, config). Nothing is dropped silently.

    ``signal_panel_by_pair`` accepts either a **built signal frame** (with
    ``sign``/``size``/``dv01_usd``, used as-is for every config) or a **raw
    signal panel** (with ``strategy.REQUIRED_COLUMNS``), in which case the
    signal is rebuilt per config so the grid actually sweeps the signal axes.

    The simulation is memoised on the replication config: 972 signal configs
    over 6 trigger widths is 6 simulations per pair, not 972. ``build_signals``
    runs a row-wise Python loop and is the remaining per-config cost -- 162
    distinct signal configs per pair, reused across the 6 triggers.

    ``signal_builder`` replaces ``strategy.build_signals`` for the raw-panel
    path. **The study's real grid passes a partial of :func:`causal_signals`
    here**, because ``build_signals`` alone satisfies none of requirements 1-3:
    it reads whatever ``residual_z`` the panel happens to carry. Whatever the
    builder stamps on ``attrs`` wins over the panel's own.

    ``comparator_ctx_by_pair`` runs the identical configs on a second pricing
    context and tags them ``book="zero_convexity"``. That row is not decoration:
    a DV01-matched zero-convexity twin cleared skew, Sharpe AND vol correlation
    with better numbers than the real package, on $0 of harvest, because ~95.6%
    of daily variance is unhedged first-order slope exposure.
    """
    base_signal_cfg = base_signal_cfg or SignalConfig()
    base_rep_cfg = base_rep_cfg or ReplicationConfig()
    books = [("package", ctx_by_pair)]
    if comparator_ctx_by_pair:
        books.append(("zero_convexity", comparator_ctx_by_pair))

    rows: List[dict] = []
    results: List[BacktestResult] = []
    for book, ctx_map in books:
        for pair_name, ctx in ctx_map.items():
            source = signal_panel_by_pair[pair_name]
            prebuilt = _SIGNAL_OUTPUT_COLS <= set(source.columns)
            _check_grid_keys(grid, prebuilt=prebuilt, pair_name=pair_name)
            sim_cache: dict = {}
            sig_cache: dict = {}
            for cfg in grid:
                rep = replace(base_rep_cfg, **{k: v for k, v in cfg.items()
                                               if k in _REP_FIELDS})
                key = (rep.trigger_bp, rep.roll_months, rep.sign,
                       rep.package_dv01_usd, rep.hedge_instrument)
                if key not in sim_cache:
                    dates = list(source.index)
                    unit = simulate(ctx, dates, rep, costs)
                    dv01 = pd.Series([abs(float(ctx.dv01(d, "long"))) for d in unit.index],
                                     index=unit.index)
                    sim_cache[key] = (unit, dv01)
                unit, dv01 = sim_cache[key]

                if prebuilt:
                    signals = source
                else:
                    scfg = replace(base_signal_cfg, **{k: v for k, v in cfg.items()
                                                       if k in _SIGNAL_FIELDS})
                    if scfg not in sig_cache:
                        built = (signal_builder or build_signals)(source, scfg)
                        # the builder's own provenance wins over the panel's
                        merged = {**(getattr(source, "attrs", {}) or {}),
                                  **(getattr(built, "attrs", {}) or {})}
                        built.attrs.clear()
                        built.attrs.update(merged)
                        sig_cache[scfg] = built
                    signals = sig_cache[scfg]

                placebo = (placebo_by_pair or {}).get(pair_name)
                res = run_pair(ctx, signals, rep_cfg=rep, costs=costs,
                               pair_name=pair_name, book=book, placebo=placebo,
                               unit=unit, dv01_unit=dv01)
                if keep_results:
                    results.append(res)
                row = {"pair": pair_name, "book": book, **cfg}
                row.update({k: v for k, v in res.stats.items() if k != "reconciliation"})
                row["sharpe"] = res.stats.get("sharpe_annualised")
                row["n_trades"] = int(len(res.trades))
                for bucket in LEDGER_COLS:
                    row[f"{bucket}_usd"] = float(res.ledger[bucket].sum())
                row.update(res.requirements.as_columns())
                row["requirements_met"] = bool(res.requirements.all_met)
                rows.append(row)
    out = pd.DataFrame(rows)
    if keep_results:
        out.attrs["results"] = results
    return out


# ------------------------------------------------------- causality machinery


def audit_causal_betas(
    fit_fn: Callable[[pd.Series, Dict[str, pd.Series]], pd.Series],
    spread_bp,
    drivers: Dict[str, pd.Series],
    *,
    shock_frac: float = 0.25,
    shock: float = 250.0,
    tol: float = CAUSALITY_TOL,
) -> dict:
    """Requirement 1, MEASURED: shock the future and see whether the past moves.

    A causal fit at date ``t`` cannot see data after ``t``, so adding a large
    constant to the last ``shock_frac`` of the dependent variable must leave
    every residual before that point bit-identical.
    :func:`factors.expanding_residual` passes at float zero;
    :func:`factors.levels_regression` fails by basis points, which is the
    control that shows this checker actually bites (a checking tool that is
    itself wrong reports success and hides the thing it was built to find).

    **Scope: only the DEPENDENT variable is shocked.** Look-ahead entering
    through a *driver* -- a regressor that is itself built with future
    information, e.g. a full-sample-standardised or smoothed factor -- is
    invisible to this audit. The drivers' own causality is the caller's
    responsibility.

    Returns ``baseline`` and ``shocked`` (the two residual series) alongside the
    verdict, so a caller can **certify the artifact it actually uses** against
    the causal one this function computed, rather than trusting that the two are
    the same object. :func:`causal_signals` does exactly that; without it, the
    audit is a statement about a function while the signal is built from a
    series, and nothing connects them.

    **The probe must have reached the code (``probe_reached``).** An unmoved
    head is only evidence of causality if the shock moved ANYTHING; otherwise it
    is evidence the shock never got in. A ``fit_fn`` that ignores its ``y``
    argument -- a closure over a precomputed fit, or a memoised builder, both
    natural responses to this function being called three times per invocation
    -- returns the identical series for the shocked and unshocked calls, so the
    head cannot move and a naive audit certifies it. That reopened C1 on the
    ``fit_fn`` seam exactly as ``fit=`` had: a full-sample residual carrying
    ~8.5bp/trade of look-ahead, stamped ``expanding_betas=True,
    causal_max_abs_diff=0.0``.

    ``tail_max_abs_diff`` (the movement AFTER the cut) separates that case from
    both legitimate ones, and the separation is not marginal:

    ====================================  =========  =========
    builder                               head diff  tail diff
    ====================================  =========  =========
    genuine expanding fit                 0          250.000
    honest full-sample levels_regression  148        186.055
    constant / memoised builder           0            0.000
    ====================================  =========  =========

    So ``causal`` requires a still head AND a moved tail. Note the middle row:
    the requirement does not weaken the audit's verdict on an honest non-causal
    fit, which still fails on the head.

    **And the fit must depend on its own history (``responds_to_history``).** A
    builder whose coefficients are baked in before it is called -- ``resid = y -
    (C + B*x)`` with ``C``/``B`` fitted on the whole sample elsewhere -- is a
    pure pointwise transform of ``y``. Its head is still under a tail shock and
    its tail moves, so it passes both checks above, yet its residual is
    bit-identical to a full-sample ``levels_regression`` residual. It is a
    plausible accident ("I already have the betas, just apply them"), not an
    adversarial construction. Shocking the HEAD and requiring the TAIL to
    respond separates it: a genuinely refitting builder must change its later
    coefficients, a frozen-coefficient one cannot.

    =====================================  ==========================
    builder                                tail response to head shock
    =====================================  ==========================
    genuine expanding fit                  216.008
    frozen-coefficient leaky builder         0.000
    honest full-sample levels_regression   160.485
    =====================================  ==========================

    **Scope limit of the method, stated where the certificate is read.** A
    single cut at ``1 - shock_frac`` certifies only that the last
    ``shock_frac`` of the sample does not leak into the first part. Leakage
    *within* the tail region -- a fit at date ``t`` late in the sample seeing
    ``t+1`` -- is invisible to this probe **by construction**, because both the
    shocked and unshocked runs contain that leak identically. Two or three cuts
    would narrow the blind spot. This is a property of the one-cut method, not a
    defect of this implementation, and it means a passing ``causal`` is evidence
    about a boundary rather than a proof of causality everywhere.

    Cost note: ``fit_fn`` is called **three** times (baseline, tail-shocked,
    head-shocked). See :func:`causal_signals` for why the answer to that cost is
    ``fit=``, not a memoising builder.
    """
    y = pd.Series(spread_bp).astype(float)
    base = pd.Series(fit_fn(y, drivers)).astype(float)
    cut = int(len(y) * (1.0 - float(shock_frac)))
    y2 = y.copy()
    y2.iloc[cut:] = y2.iloc[cut:] + float(shock)
    shocked = pd.Series(fit_fn(y2, drivers)).astype(float)

    tail = y.index[cut:]
    head = y.index[:cut]

    def _gap(u, v, where):
        pair = pd.concat([u.reindex(where).rename("a"),
                          v.reindex(where).rename("b")], axis=1).dropna()
        if pair.empty:
            return float("nan"), 0
        return float((pair["a"] - pair["b"]).abs().max()), int(len(pair))

    # 1. Did the shock reach the code at all?
    tail_diff, n_tail = _gap(base, shocked, tail)
    probe_reached = bool(np.isfinite(tail_diff) and tail_diff > 0.0)

    # 2. Does the fit depend on its own history, or are its coefficients frozen?
    y3 = y.copy()
    y3.iloc[:cut] = y3.iloc[:cut] + float(shock)
    head_shocked = pd.Series(fit_fn(y3, drivers)).astype(float)
    history_diff, n_history = _gap(base, head_shocked, tail)
    responds_to_history = bool(np.isfinite(history_diff) and history_diff > 0.0)

    # 3. The actual causality question: did the future move the past?
    diff, n_head = _gap(base, shocked, head)

    out = {"shock": float(shock), "cut": cut, "baseline": base, "shocked": shocked,
           "tail_max_abs_diff": tail_diff, "probe_reached": probe_reached,
           "n_tail_compared": n_tail,
           "head_shock_tail_response": history_diff,
           "responds_to_history": responds_to_history,
           "max_abs_diff": diff, "n_compared": n_head}
    out["causal"] = bool(probe_reached and responds_to_history
                         and np.isfinite(diff) and diff <= tol)
    return out


def audit_rolling_sigma_z(
    z, resid, *, window: int = 252, min_periods: int = 126, tol: float = ROLLING_Z_TOL,
) -> dict:
    """Requirement 3: the z must reproduce from a TRAILING 252-day sigma.

    Pricing on a full-sample sigma overstated expectancy by 20-45% (measured
    rolling/full ratios 0.604 / 0.799 / 0.556). This recomputes the z the rule
    is entitled to and refuses any series that does not match it.
    """
    expected = residual_z(resid, window=int(window), min_periods=int(min_periods))
    both = pd.concat([pd.Series(z).astype(float).rename("got"),
                      expected.rename("want")], axis=1).dropna()
    if both.empty:
        return {"rolling": False, "max_abs_diff": float("nan"), "n_compared": 0}
    diff = float((both["got"] - both["want"]).abs().max())
    return {"rolling": bool(diff <= tol), "max_abs_diff": diff,
            "n_compared": int(len(both))}


def audit_trailing_statistic(
    got, source, *, recompute: Callable[[pd.Series], pd.Series], label: str,
    tol: float = ROLLING_Z_TOL,
) -> dict:
    """Certify that a panel column IS a trailing statistic of a named source.

    The same shape as :func:`audit_rolling_sigma_z`, generalised, and it exists
    for the same reason the betas check does: ``causal_signals`` certified
    ``residual_z`` and nothing else, while ``signal_state`` consumes **five**
    panel columns. A certified ``residual_z`` makes one of five inputs causal,
    not the signal.

    Of the other four, three are trailing by construction where they are built
    -- ``spread_vol_bp_day`` and ``realized_vol_bp_day`` are
    ``.diff().rolling(window).std()``, and ``be_over_realized`` is a pointwise
    ratio of a contemporaneous breakeven to one of them. The two that are NOT
    safe by construction are the ones whose own input can leak:

    * ``drift_t`` -- :func:`factors.drift` takes a trailing rolling mean and
      Newey-West t of ``changes_resid``, so its WINDOW is causal but its INPUT
      is a regression residual, exactly the object that leaked through four
      passes of this module.
    * ``iv_z`` -- a z-score, and a z is only causal if its sigma is trailing.
      A full-sample sigma overstated expectancy by 20-45% where it was measured.

    Supply the source and this certifies the column against a recomputation,
    raising in :func:`causal_signals` on mismatch rather than scoring it lower.
    """
    want = recompute(pd.Series(source).astype(float))
    both = pd.concat([pd.Series(got).astype(float).rename("got"),
                      pd.Series(want).astype(float).rename("want")], axis=1)
    aligned = both.dropna()
    n_got = int(both["got"].notna().sum())
    if aligned.empty:
        return {"matched": False, "max_abs_diff": float("nan"), "n_compared": 0,
                "n_defined": n_got, "label": label}
    diff = float((aligned["got"] - aligned["want"]).abs().max())
    # A column defined on dates the recomputation is not is not "matching on the
    # overlap" -- it is a different series that happens to agree where both
    # exist, which is how an endpoint-only check passes a gapped file.
    complete = bool(len(aligned) == n_got)
    return {"matched": bool(complete and np.isfinite(diff) and diff <= tol),
            "max_abs_diff": diff, "n_compared": int(len(aligned)),
            "n_defined": n_got, "label": label}


def entry_vintage_signals(
    panel: pd.DataFrame,
    cfg: SignalConfig,
    *,
    spread_bp,
    drivers: Dict[str, pd.Series],
    betas: pd.DataFrame,
    window: int = 252,
    min_periods: int = 126,
) -> pd.DataFrame:
    """Requirement 2: open on the entry date's betas and hold THAT vector.

    While a position is on, the residual (and therefore the z that sizes and
    exits it) is re-derived from the beta vector frozen at entry, not from the
    latest expanding fit. Re-estimating during the hold is look-ahead wearing a
    different hat: measured, it took a +3.80bp gross result to +0.13bp.

    The returned frame carries ``beta_vintage_date`` so :func:`run_pair` can
    re-verify the freeze from the data instead of trusting a flag.

    ``panel["residual_z"]`` is **overwritten**, not read. The entry-side z is
    re-derived here from ``betas`` (the per-date expanding vintage) so that a
    caller cannot accidentally leave a placeholder -- or worse, a full-sample z
    -- in the panel and have entries silently decided on it. Everything else in
    the panel is used as supplied.
    """
    idx = panel.index
    y = pd.Series(spread_bp).astype(float).reindex(idx)
    X = pd.DataFrame({k: pd.Series(v).astype(float) for k, v in drivers.items()})
    X = X.reindex(idx)
    driver_cols = [c for c in betas.columns if c not in ("const", "vintage_date")]

    b = betas.reindex(idx)
    pred_live = b["const"].astype(float).copy()
    for c in driver_cols:
        pred_live = pred_live + b[c].astype(float) * X[c]
    panel = panel.copy()
    panel["residual_z"] = residual_z(y - pred_live, window=window,
                                     min_periods=min_periods)
    base = build_signals(panel, cfg)
    lagged = panel.shift(1)

    live_z_lagged = panel["residual_z"].shift(1)
    records = []
    held_z_deviation = 0.0     # max |z_frozen - z_live| on days actually held
    n_episodes = 0
    open_sign = 0
    frozen_z = None
    vintage = pd.NaT
    for ts in idx:
        if open_sign == 0:
            st = {"sign": int(base.at[ts, "sign"]), "size": float(base.at[ts, "size"]),
                  "reason": str(base.at[ts, "reason"])}
            if st["sign"] != 0:
                b = betas.loc[ts] if ts in betas.index else None
                coef = None if b is None else b[["const"] + driver_cols].astype(float)
                if coef is None or not np.isfinite(coef.to_numpy()).all():
                    st = {"sign": 0, "size": 0.0,
                          "reason": "no beta vintage at entry -- fail closed"}
                else:
                    pred = float(coef["const"]) + sum(
                        float(coef[c]) * X[c] for c in driver_cols)
                    frozen_z = residual_z(y - pred, window=window,
                                          min_periods=min_periods).shift(1)
                    open_sign = int(st["sign"])
                    vintage = b.get("vintage_date", ts)
                    n_episodes += 1
            records.append({**st, "beta_vintage_date": vintage if st["sign"] else pd.NaT})
            continue

        row = lagged.loc[ts].copy()
        z_frozen = frozen_z.get(ts, np.nan) if frozen_z is not None else np.nan
        row["residual_z"] = z_frozen
        z_live = live_z_lagged.get(ts, np.nan)
        if np.isfinite(z_frozen) and np.isfinite(z_live):
            held_z_deviation = max(held_z_deviation, abs(float(z_frozen) - float(z_live)))
        st = signal_state(row, cfg) if not row.isna().all() else {
            "sign": 0, "size": 0.0, "reason": "warmup"}
        if int(st["sign"]) != open_sign:
            st = {"sign": 0, "size": 0.0,
                  "reason": "exit -- entry-vintage signal closed"}
            open_sign, frozen_z, vintage = 0, None, pd.NaT
        records.append({**st, "beta_vintage_date": vintage if st["sign"] else pd.NaT})

    out = pd.DataFrame(records, index=idx)
    out["dv01_usd"] = out["sign"] * out["size"] * cfg.base_dv01_usd
    # Evidence, not just a claim (I4). ``run_pair`` requires this stamp AND the
    # per-episode constancy of ``beta_vintage_date``: the label alone is
    # satisfied by any constant column, including a hand-written one, and
    # mutation M8 showed the label stays frozen even when the hold is priced on
    # the live z. ``entry_vintage_frozen_z_deviation`` is how far the frozen z
    # actually diverged from the live one on days the book was on -- the
    # quantity that is identically zero if the freeze was never applied.
    out.attrs.update({
        "entry_vintage_hedge": True,
        "entry_vintage_frozen_z_deviation": float(held_z_deviation),
        "entry_vintage_episodes": int(n_episodes),
    })
    return out


def causal_signals(
    panel: pd.DataFrame,
    cfg: SignalConfig,
    *,
    spread_bp,
    drivers: Dict[str, pd.Series],
    fit: Optional[WalkForwardFit] = None,
    fit_fn: Optional[Callable[[pd.Series, Dict[str, pd.Series]], WalkForwardFit]] = None,
    min_periods: int = 252,
    refit_every: int = 1,
    window: int = 252,
    z_min_periods: int = 126,
    changes_resid: Optional[pd.Series] = None,
    drift_window: int = 63,
    iv_bp_day: Optional[pd.Series] = None,
    iv_z_window: int = 252,
    iv_z_min_periods: int = 126,
) -> pd.DataFrame:
    """The only supported way to build a signal for this study.

    Runs the walk-forward fit, AUDITS its causality, derives a trailing-252-day
    z from **the audited residual**, audits that the z is causal too, and then
    freezes the beta vintage at entry. The audits' own numbers are stamped on
    ``attrs`` so ``run_pair`` requires evidence rather than a claim: a forged
    ``expanding_betas=True`` with no finite ``causal_max_abs_diff`` does not
    open the gate.

    **The audit certifies the artifact, not a re-derivation of it.** An earlier
    version audited a local closure over :func:`factors.expanding_residual` and
    then built the signal from the caller's ``fit``, never comparing the two --
    so both audits were constants on that path. Handing it a ``WalkForwardFit``
    carrying :func:`factors.levels_regression`'s FULL-SAMPLE residual produced
    ``expanding_betas=True, causal_max_abs_diff=0.0, rolling_sigma_z=True``,
    i.e. requirements 1, 2 and 3 all granted on a signal built with ~8.5bp/trade
    of look-ahead, wearing this engine's own certificate. That is the precise
    failure Task 15 exists to prevent.

    So ``fit`` is now **verified against the audited baseline** and a mismatch
    RAISES rather than failing quietly -- passing a precomputed fit is a
    performance shortcut (it is the natural response to the builder's cost in a
    162-config sweep), and a fit that does not reproduce the causal one means
    the caller passed the wrong object or mismatched parameters, not that the
    result should be scored a little lower.

    ``fit_fn`` supplies a different causal builder (e.g. a rolling rather than
    expanding window). It is audited in place of the default, and its own output
    is then certified the same way, so the shortcut cannot be used to smuggle a
    non-causal fit past the gate either.

    **What this function does and does not certify.** It certifies
    ``residual_z``, end to end: the fit is causal (head still under a future
    shock, tail responsive to a past one), the artifact is the audited one, the
    BETAS reproduce that residual, and the z is a trailing-sigma z of it, frozen
    at the entry vintage. It certifies **nothing else**. The other four panel
    columns that reach a trading decision -- ``be_over_realized`` (the sign),
    ``drift_t`` (the veto), ``spread_vol_bp_day`` (the size), ``iv_z`` (the
    short-side gate) -- are passed through untouched, as are the regression
    drivers. See :data:`UNCERTIFIED_SIGNAL_INPUTS`.
    """
    if fit_fn is None:
        def fit_fn(y, x):
            return expanding_residual(y, x, min_periods=min_periods,
                                      refit_every=refit_every)

    causal = audit_causal_betas(lambda y, x: fit_fn(y, x).residual,
                                spread_bp, drivers)
    if not causal["probe_reached"]:
        raise ValueError(
            "the builder returned the same residual for shocked and unshocked "
            f"inputs (tail movement {causal['tail_max_abs_diff']!r}), so the "
            "causality probe never reached it. A `fit_fn` that ignores its `y` "
            "argument -- a closure over a precomputed fit, or a memoised "
            "builder -- cannot be audited: its head is unmoved because nothing "
            "moved, not because the fit is causal, and certifying it would "
            "stamp a full-sample residual as expanding. Pass a builder that "
            "genuinely re-fits on the `y` it is given; if the cost is the "
            "concern, use `fit=` with a matching precomputed fit, which is "
            "certified against the audit instead."
        )
    baseline = pd.Series(causal["baseline"]).astype(float)

    if fit is None:
        fit = fit_fn(spread_bp, drivers)
    else:
        # Certify the artifact: the residual about to become the signal must BE
        # the one the audit just ran on.
        both = pd.concat([pd.Series(fit.residual).astype(float).rename("got"),
                          baseline.rename("want")], axis=1)
        # NB `fit_gap`, not `drift` -- `drift` is the imported factor function,
        # and shadowing it here broke the drift_t certification below.
        fit_gap = float((both["got"] - both["want"]).abs().max())
        disagree_on_nan = bool(
            (both["got"].isna() != both["want"].isna()).any())
        if disagree_on_nan or not np.isfinite(fit_gap) or fit_gap > FIT_MATCH_TOL:
            raise ValueError(
                "the supplied `fit` does not reproduce the audited causal fit "
                f"(max abs deviation {fit_gap:.6g}"
                + (", and the two disagree on which dates are defined"
                   if disagree_on_nan else "")
                + "). causal_signals certifies the residual it USES, so a fit "
                "built with different parameters -- or by a non-causal "
                "regression -- cannot be certified as causal. Either drop "
                "`fit=` and let this function build it, align `min_periods`/"
                "`refit_every` with how `fit` was built, or pass the builder "
                "itself as `fit_fn=` so it is the thing audited."
            )

    # Certify the BETAS against the certified residual. This is the object the
    # signal is ACTUALLY built from: `entry_vintage_signals` rebuilds the entry
    # z and the whole frozen hold from `betas`, not from the residual audited
    # above. Nothing tied the two together, and on the honest path they agree,
    # which is exactly why it stayed invisible through three fixes. A fit
    # carrying the genuine causal residual next to centred-window betas (fitted
    # on [t-126, t+126]) was granted requirements 1, 2 AND 3, with the "hedge
    # frozen at entry vintage" frozen at a vintage that saw 126 days of the
    # future -- and, being time-varying, it defeated the deviation gate too.
    #
    #   fit                                     consistency gap
    #   honest expanding                                      0
    #   causal residual + centred betas                    15.3
    #   causal residual + full-sample betas                6.94
    y_series = pd.Series(spread_bp).astype(float)
    X_frame = pd.DataFrame({k: pd.Series(v).astype(float)
                            for k, v in drivers.items()}).reindex(y_series.index)
    beta_cols = [c for c in fit.betas.columns if c not in ("const", "vintage_date")]
    missing_drivers = [c for c in beta_cols if c not in X_frame.columns]
    if missing_drivers:
        raise ValueError(
            f"`fit.betas` carries coefficients for {missing_drivers}, which are "
            "not among `drivers`; the betas cannot be checked against the "
            "residual they are supposed to explain."
        )
    b_frame = fit.betas.reindex(y_series.index)
    implied_pred = b_frame["const"].astype(float)
    for c in beta_cols:
        implied_pred = implied_pred + b_frame[c].astype(float) * X_frame[c]
    beta_pair = pd.concat([(y_series - implied_pred).rename("implied"),
                           pd.Series(fit.residual).astype(float).rename("certified")],
                          axis=1)
    aligned = beta_pair.dropna()
    n_certified = int(beta_pair["certified"].notna().sum())
    beta_gap = (float((aligned["implied"] - aligned["certified"]).abs().max())
                if len(aligned) else float("nan"))
    if (len(aligned) != n_certified or not np.isfinite(beta_gap)
            or beta_gap > FIT_MATCH_TOL):
        raise ValueError(
            "`fit.betas` does not reproduce `fit.residual` "
            f"(max abs deviation {beta_gap:.6g} over {len(aligned)} of "
            f"{n_certified} dated residuals). The betas -- not the residual --"
            " are what `entry_vintage_signals` rebuilds the entry z and the "
            "frozen hold from, so certifying only the residual leaves the "
            "object that actually drives the signal unchecked. A fit whose two "
            "faces disagree is not a fit: pass betas and residual from the same "
            "regression."
        )

    # The z is derived from the AUDITED residual, and its own causality is
    # checked against the shocked run the audit already computed -- free, and it
    # is what a full-sample sigma would fail. Comparing the z only against a
    # recomputation of itself is a tautology.
    z = residual_z(fit.residual, window=window, min_periods=z_min_periods)
    rolling = audit_rolling_sigma_z(z, fit.residual, window=window,
                                    min_periods=z_min_periods)
    z_shocked = residual_z(pd.Series(causal["shocked"]).astype(float),
                           window=window, min_periods=z_min_periods)
    head = pd.Series(spread_bp).index[:int(causal["cut"])]
    z_both = pd.concat([z.reindex(head).rename("a"),
                        z_shocked.reindex(head).rename("b")], axis=1).dropna()
    z_causal_diff = (float((z_both["a"] - z_both["b"]).abs().max())
                     if len(z_both) else float("nan"))
    # Requirement 3's substance is "a trailing-252d z OF A CAUSAL RESIDUAL", so
    # it inherits requirement 1's verdict. Without this, a frozen-coefficient
    # builder (doorway A) was stamped rolling_sigma_z=True: its z really is a
    # trailing-sigma z, and really is unmoved by a future shock -- of a residual
    # that leaks the whole sample. Both statements were true and the conjunction
    # was still misleading.
    z_ok = bool(causal["causal"] and rolling["rolling"]
                and np.isfinite(z_causal_diff) and z_causal_diff <= ROLLING_Z_TOL)

    # Optional certification of the OTHER signal inputs. `residual_z` is one of
    # five columns `signal_state` reads; certifying it makes one input causal,
    # not the signal. Supplying the sources closes the two that can actually
    # leak -- see :func:`audit_trailing_statistic` for why these two and not the
    # other three. Omit them and behaviour is unchanged, but the certificate
    # then says so rather than staying silent.
    certified = ["residual_z"]
    uncertified = list(UNCERTIFIED_SIGNAL_INPUTS)
    input_audits: Dict[str, float] = {}

    if changes_resid is not None and "drift_t" in panel.columns:
        audit = audit_trailing_statistic(
            panel["drift_t"], changes_resid, label="drift_t",
            recompute=lambda s: drift(s, window=int(drift_window))["t_stat"])
        input_audits["drift_t_max_abs_diff"] = audit["max_abs_diff"]
        if not audit["matched"]:
            raise ValueError(
                f"`drift_t` does not reproduce as a trailing {drift_window}-day "
                "Newey-West t of the supplied `changes_resid` (max abs deviation "
                f"{audit['max_abs_diff']:.6g} over {audit['n_compared']} of "
                f"{audit['n_defined']} dated values). drift_t VETOES a flattener, "
                "so a drift built from a full-sample residual vetoes trades using "
                "information the trade date did not have. Pass the changes "
                "residual this column was built from, or drop `changes_resid=` "
                "and accept it as uncertified."
            )
        certified.append("drift_t")
        uncertified.remove("drift_t")

    if iv_bp_day is not None and "iv_z" in panel.columns:
        audit = audit_trailing_statistic(
            panel["iv_z"], iv_bp_day, label="iv_z",
            recompute=lambda s: residual_z(s, window=int(iv_z_window),
                                           min_periods=int(iv_z_min_periods)))
        input_audits["iv_z_max_abs_diff"] = audit["max_abs_diff"]
        if not audit["matched"]:
            raise ValueError(
                f"`iv_z` does not reproduce as a trailing {iv_z_window}-day z of "
                f"the supplied `iv_bp_day` (max abs deviation "
                f"{audit['max_abs_diff']:.6g} over {audit['n_compared']} of "
                f"{audit['n_defined']} dated values). iv_z GATES the steepener, "
                "and a z on a full-sample sigma is exactly the look-ahead "
                "requirement 3 exists to refuse -- the same error, one column "
                "across. Pass the implied-vol series it was built from, or drop "
                "`iv_bp_day=` and accept it as uncertified."
            )
        certified.append("iv_z")
        uncertified.remove("iv_z")

    p = panel.copy()
    p["residual_z"] = z.reindex(p.index)
    out = entry_vintage_signals(p, cfg, spread_bp=spread_bp, drivers=drivers,
                                betas=fit.betas, window=window,
                                min_periods=z_min_periods)
    # Stamp EVERY leg's number, not just the head-shock one. `causal` is a
    # conjunction of three measurements, and only one of them was being
    # recorded -- so a fit that failed on a different leg still carried
    # `causal_max_abs_diff: 0.0` on its certificate, which reads as a clean
    # pass. Measured on the frozen-coefficient builder (doorway A):
    # `expanding_betas=False` with `causal_max_abs_diff=0.0`, because its head
    # genuinely does not move under a future shock -- it fails because its tail
    # does not respond to its own history, and that number was nowhere. The
    # flag governs the gate either way, so no gate was wrong; but this study
    # trusts stamped evidence over flags, and evidence that omits the failing
    # leg invites the reader to trust the flag instead.
    out.attrs.update({
        "expanding_betas": bool(causal["causal"]),
        "causal_max_abs_diff": float(causal["max_abs_diff"]),
        "causal_probe_reached": bool(causal["probe_reached"]),
        "causal_tail_max_abs_diff": float(causal["tail_max_abs_diff"]),
        "causal_responds_to_history": bool(causal["responds_to_history"]),
        "causal_head_shock_tail_response": float(causal["head_shock_tail_response"]),
        "betas_reproduce_residual_max_abs_diff": float(beta_gap),
        "rolling_sigma_z": z_ok,
        "rolling_z_max_abs_diff": max(float(rolling["max_abs_diff"]),
                                      z_causal_diff),
        "beta_vintage": fit.kind,
        "certified_signal_inputs": tuple(certified),
        "uncertified_signal_inputs": tuple(uncertified),
        **input_audits,
    })
    return out


# -------------------------------------------------------------------- placebo


def random_walk_like(series, rng: np.random.Generator) -> pd.Series:
    """A random walk on the same index, matched to the LEVEL dispersion.

    Deliberately carries no relationship to vol whatsoever -- that is the point.
    Task 15's version of this opened the gate in 20.6% of 500 sims (four times
    nominal) and beat the reported headline in 100% of those.
    """
    s = pd.Series(series).astype(float)
    steps = rng.normal(0.0, 1.0, len(s))
    w = np.cumsum(steps)
    w = w - w.mean()
    sd = float(np.std(w, ddof=1)) if len(w) > 1 else 0.0
    target = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    if sd:
        w = w / sd * target
    return pd.Series(w + float(s.mean()), index=s.index)


@dataclass(frozen=True)
class PlaceboResult:
    """How often a null with no relationship to vol matched the real headline."""

    headline: float
    placebo_headlines: Tuple[float, ...]
    seed: int
    alpha: float = 0.05

    @property
    def n_sims(self) -> int:
        return len(self.placebo_headlines)

    @property
    def p_value(self) -> float:
        """Share of nulls that matched or beat the headline (+1 smoothing)."""
        if not self.placebo_headlines:
            return float("nan")
        a = np.asarray(self.placebo_headlines, dtype=float)
        beat = int(np.sum(a >= self.headline))
        return float((1 + beat) / (1 + len(a)))

    @property
    def passes(self) -> bool:
        p = self.p_value
        return bool(np.isfinite(p) and p <= self.alpha)


def random_walk_placebo(
    headline: float,
    run_one: Callable[[np.random.Generator], float],
    *,
    n_sims: int = 200,
    seed: int = 0,
    alpha: float = 0.05,
) -> PlaceboResult:
    """Run ``run_one`` on ``n_sims`` random-walk nulls through the SAME pipeline.

    ``run_one`` must take an RNG and return the same headline statistic the
    real run produced, computed by the same code -- a placebo through a
    different pipeline tests the pipeline, not the signal.
    """
    rng = np.random.default_rng(seed)
    vals = tuple(float(run_one(rng)) for _ in range(int(n_sims)))
    return PlaceboResult(headline=float(headline), placebo_headlines=vals,
                         seed=int(seed), alpha=float(alpha))
