"""The Strategy-2 grid: short pack convexity against a butterfly, every cell.

Citi ran ONE cell of this grid -- Blues CA against a spot 2s5s10s, regression
weights, $100k DV01, held ~4 months. This module runs the whole space:

    pack rank  x  fly (45: 9 shapes x 5 forward starts)  x  weighting (2)
              x  sizing (3)  x  regression window (3)  x  entry rule (4)
              x  holding period  x  cost

and scores every cell on the same ledger. The point is not to find the best
number; it is to see **whether the hedge works for the reason Citi says it
does**. See :mod:`RVUtils.ConvexityRV.strat2_fly_universe` for the hypothesis:
a pack's CA is driven by vol at the pack's own expiry, so a forward-starting
fly matched to that expiry should hedge better than a spot fly, increasingly so
with ``T1``. :func:`effectiveness_matrix` reports exactly that, as
``(pack T1) x (fly forward start)``.

WHY A PANEL SIMULATION AND NOT A QueryDrivenBacktest
====================================================
A QDB run reprices an aged package on a fresh curve every day. That is the right
answer and it costs ~seconds per epoch per cell; at 45 flies x 9 pack ranks x 3
windows x 4 entry rules it is not a slower option, it is an impossible one. So
the ledger here is built from the panels directly.

**THE FIRST-ORDER APPROXIMATION, STATED PLAINLY.** Both legs are struck at
market and held with fixed DV01, so to first order in the daily rate move::

    dP&L_CA   = -s * dCA_bp   * CA_DV01          s = +1 short CA, -1 long CA
    dP&L_fly  = +s * dfly_bp  * belly_DV01       (paid belly)

The CA leg's first-order term is exact in the sense that matters: the futures
leg has a genuinely rate-invariant $25/bp/contract DV01, and the swap leg is
struck DV01-matched to it, so everything except the CA spread itself cancels at
first order. The fly leg's is exact given the measured identity
``PV01_i = w_i * bpv`` (see the universe module) -- the *only* approximation is
that the leg DV01s are held at their entry values rather than re-measured daily.

**WHAT THE APPROXIMATION OMITS IS PRECISELY THE TRADE.** A payer swap is
CONCAVE in rates (``d2NPV/dr2 = 2*A' < 0``, because the annuity shrinks as rates
rise), the futures leg is linear, so long-futures-versus-pay-fixed is SHORT
gamma -- which is the entire economic content of selling a convexity adjustment.
Reporting a P&L that is linear in ``dCA`` and calling the second order zero
would be reporting the trade with its risk deleted. So it is computed::

    dP&L_gamma_CA  = -s * CA_DV01 * D_A * 1e-4 * (d swap_rate_bp)^2      (<= 0 for s=+1)
    dP&L_gamma_fly = -s * belly_DV01 * 1e-4 *
                     ( D_b*db^2 - w_f*D_f*df^2 - w_k*D_k*dk^2 )

with ``D`` the annuity duration from
:func:`RVUtils.ConvexityRV.strat2_fly_universe.annuity_duration` (validated to
2.1% against ``rl.IRS.analytic_delta``; see its docstring). ``NPV(x) = PV01*x -
PV01*D*1e-4*x^2`` -- the one-half cancels against the two in ``2A'``.

``CellResult`` carries the gamma term SEPARATELY from the first-order P&L so the
size of the approximation is always visible, never absorbed. ``cfg.include_gamma``
decides whether the headline total includes it; the diagnostic is reported
either way.

WHAT IS *NOT* MODELLED, so it is not mistaken for modelled
----------------------------------------------------------
* Re-striking drift within an epoch: DV01s are frozen at entry.
* Financing/margin on the futures leg, and CME-vs-LCH clearing basis.
* The CME/non-CME curve basis on the CA level (``Strat2Config.ca_basis_bp``
  defaults to 0, i.e. the raw number; it cancels out of every z-score and every
  daily change, so it does not touch the P&L here at all).
* Bid/offer beyond the single ``cost_bp_roundtrip`` knob.

NO LOOKAHEAD
============
Every regression that sets an epoch's weights is fitted on data ending on or
before the entry date, and the weights are then FROZEN for the life of the
epoch. A fly whose weights move daily is not an instrument; its "P&L" would
include a re-weighting nobody traded. This is structural here -- weights live on
:class:`Epoch`, not on the date axis.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.strat2_fly_universe import (
    DV01_NEUTRAL_WINGS,
    FlyFit,
    FlySpec,
    annuity_duration,
    fly_by_id,
    fly_carry_series,
    fly_rate_series,
    fly_regression,
    fly_universe,
)

__all__ = [
    "Strat2GridConfig",
    "Epoch",
    "CellResult",
    "GridInputs",
    "prepare_inputs",
    "rank_label_series",
    "rank_following_ca",
    "constant_contract_dca",
    "simulate_cell",
    "run_grid",
    "effectiveness_matrix",
    "hypothesis_slope",
    "citi_belly_dv01",
    "COST_MULTIPLIERS",
]

#: The cost-sensitivity ladder every cell is scored on.
COST_MULTIPLIERS: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

#: ``t_mid`` in the CA panel is ``mean(T1_i)`` over the four contracts, whose
#: expiries are ``T1, T1+.25, T1+.5, T1+.75`` -- so the FIRST expiry is
#: ``t_mid - 0.375`` exactly. The matched swap runs ``[T1, T1+1]``.
T_MID_TO_T1 = 0.375


# ===========================================================================
# Config
# ===========================================================================
@dataclass(frozen=True)
class Strat2GridConfig:
    """One grid cell. Every knob documented inline; nothing tuned on its own P&L."""

    # ------------------------------------------------------------- universe
    pack_rank: int = 8
    """1-indexed rolling pack window to trade. Rank 1 = the four front
    contracts (Whites). Reachable range on the offline SR3 store is 1..10, i.e.
    ``T1`` from ~0.15y to ~2.4y. Citi traded Blues (rank 13, ``T1~3.25y``);
    **that depth is not in daily offline reach and is not tested here.**"""

    fly_id: str = "2s5s10s"
    """A ``FlySpec.fly_id`` from
    :func:`~RVUtils.ConvexityRV.strat2_fly_universe.fly_universe`: a bare shape
    for spot (``"2s5s10s"``) or ``shape@NY`` for forward-starting
    (``"2s5s10s@2Y"``). ``"2s5s10s"`` is Citi's published hedge."""

    fly_weighting: str = "regression"
    """``"regression"`` -- wings from ``CA ~ a + b_f r_f + b_b r_b + b_k r_k``,
    Citi's own method (*"we regressed Blues CA on 2y, 5y and 10y swap rates
    ... the fitted value effectively being a 2s5s10s fly with -0.73/1/-0.47 DV01
    weights"*), re-estimated at every entry and never frozen at the published
    2017 numbers -- or ``"dv01_neutral"``: 50/50 wings, a pure curvature trade
    with zero package duration."""

    hedge_sizing: str = "regression_beta"
    """How big the fly is relative to the CA leg.

    ``"regression_beta"``  ``belly_DV01 = CA_DV01 * beta / 100`` -- Citi's rule
        (§5.4), verified against both published notional sets at ratio 0.996 and
        0.997. The fly is deliberately NOT DV01-matched to the CA leg; the belly
        is only ~21% of it, because it is a BETA hedge for the vol exposure.
    ``"dv01_ratio"``       ``belly_DV01 = CA_DV01 * dv01_ratio`` -- a fixed
        ratio, the control that asks whether the rolling beta is worth anything
        over a constant.
    ``"unhedged"``         no fly at all. The baseline every hedge is scored
        against, and the denominator of ``variance_reduction``.
    """

    dv01_ratio: float = 0.214
    """Belly-to-CA DV01 ratio for ``hedge_sizing="dv01_ratio"``. 0.214 is
    Citi's own 13-Jan-2017 ratio ($21.4k belly on $100k CA), used as a constant
    so the comparison isolates *re-estimation*, not *level*."""

    regression_window: int = 252
    """Trailing business days for the weighting/beta regression. 63 / 126 / 252
    are the grid's three settings. Citi re-estimated within three weeks
    (0.73/0.47 on 13-Jan -> 0.705/0.465 on 9-Feb), so a long window is a choice
    to be tested, not an obvious default."""

    regression_basis: str = "levels"
    """``"levels"`` is Citi's, verbatim (*"we regressed Blues CA on 2y, 5y and
    10y swap rates"*, annotated ``10.2 + 21.4*fly``). ``"changes"`` runs the
    same estimator on first differences.

    **Measured here, this is the single biggest knob in the grid.** The level
    fit is a spurious regression on 2019-2023 SOFR: high ``R^2``, and a ``beta``
    whose SIGN flips on a large fraction of re-estimations. Sizing a hedge off
    it makes the P&L variance WORSE than unhedged. See the module report."""

    regression_target: str = "rank"
    """Which CA history the regression is fitted to.

    ``"rank"``   the ROLLING series at ``pack_rank`` -- what Citi means by
        "Blues CA": a colour, re-pointed at a new pack every IMM roll. It has
        years of history, and it carries the roll jumps that come with that.
        **This is Citi's own object and the default.**
    ``"label"``  the CONSTANT-CONTRACT history of the specific pack being
        traded. Cleaner (no roll jumps) but structurally short: a pack label
        only enters a 13-contract strip at window 10 and walks inward, so at
        rank 10 it has ~0 days of own history and at rank 8 about 126. With
        ``regression_window=252`` the deep ranks are starved and the cell
        collapses to a handful of epochs -- which is a fact about the data, not
        a bug, and is why ``"rank"`` is the default."""

    min_abs_beta: float = 1.0
    """Skip the hedge when ``|beta| < this`` (bp of CA per percent of fly). A
    near-zero beta makes ``w = -b/beta`` explode and the sizing meaningless."""

    require_positive_wings: bool = False
    """``IRSwapStructure._build_fly`` forces the wings opposite in sign to the
    belly, so a regression implying a same-signed wing is not expressible as a
    fly. Default False here (unlike the strategy config) because across 45 flies
    a negative fitted wing is a FINDING about that fly, and the grid should
    score it rather than silently drop the cell. ``Epoch.fit.ok`` records
    whether the fitted weights were expressible."""

    # ------------------------------------------------------------- entry
    entry_rule: str = "always"
    """``"always"``      enter on every rebalance date (Citi's revealed
                         behaviour: it rolled Blues -> Greens rather than
                         closing the theme).
    ``"ca_z"``           enter only when the pack's CA z-score >= ``z_entry``
                         (CA wide vs its own history -> sell convexity).
    ``"vs_model_z"``     enter only when the CA-minus-Ho-Lee dislocation
                         z-score >= ``z_entry``. This is the metric Citi's own
                         text leads with: *"almost three sigmas wide to the
                         model"*.
    ``"carry"``          enter only when the CA leg's 3m roll >= ``carry_min_bp``
                         -- the roll IS the short-convexity carry (verified:
                         1.30bp x $100k = the $130k Citi quotes)."""

    z_entry: float = 1.0
    """Threshold for the two z rules. Sign follows the ranking direction: a pack
    is a more attractive SHORT-convexity candidate the HIGHER the z-score is."""

    z_window: str = "z3m"
    """``"z3m"`` or ``"z1y"`` -- which trailing window the z entry rule reads.
    The 1y window needs 252 observations of that LABEL, which the rolling packs
    only accumulate deep into the sample."""

    carry_min_bp: float = 0.0
    """Threshold for ``entry_rule="carry"``, in bp of 3m roll."""

    # ------------------------------------------------------------- execution
    rebalance_days: int = 21
    """Trading days between decision points. One position at a time: a
    rebalance date is only acted on when the book is flat."""

    holding_days: int = 63
    """Trading days held once entered (~3 months). Citi's realised holds were
    ~4 months (Blues) and ~2 months (Greens), and carry is quoted over 3m."""

    ca_dv01: float = 100_000.0
    """Dollars per bp on the CA leg. Citi's flagship was $100k (1000 packs,
    $1bn swap); the executed model-portfolio trade was $200k."""

    direction: str = "short_ca"
    """``"short_ca"`` = buy the pack + pay the matched swap (Citi's trade; you
    profit when the CA narrows) and pay the fly belly. ``"long_ca"`` negates the
    WHOLE package -- both legs and the gamma sign -- so it is the exact mirror,
    including the entry rule's polarity: the z rules still fire on a HIGH
    z-score, they just express the opposite view. That keeps ``long_ca`` a clean
    negative control on the P&L rather than a different strategy."""

    cost_bp_roundtrip: float = 0.0
    """Bid/offer in bp of the traded spread, charged ONCE per epoch against
    ``CA_DV01 + |belly_DV01|``. Citi excludes costs explicitly (*"Calculations
    do not include transaction costs and other fees"*), so 0.0 reproduces their
    convention. Every cell is additionally scored at 0x / 0.5x / 1x / 2x of
    whatever is set here, so the sensitivity is always visible."""

    # ------------------------------------------------------------- second order
    include_gamma: bool = False
    """Whether the headline P&L includes the estimated second-order term. The
    term is ALWAYS computed and reported (``gamma_pnl``, ``gamma_share``);
    this only decides whether it is folded into ``total_pnl``. Default False so
    the headline stays comparable to the first-order convention the note itself
    uses -- but a cell whose ``gamma_share`` is large is a cell whose headline
    should not be believed."""

    # ------------------------------------------------------------- window
    burn_in_days: int = 0
    """Extra trading days to skip at the start of the panel, on top of
    ``regression_window``. Default 0: the regression window is already the
    binding warm-up."""

    def key(self) -> Dict[str, Any]:
        """The identifying knobs, for a grid results row."""
        return {
            "pack_rank": self.pack_rank, "fly_id": self.fly_id,
            "fly_weighting": self.fly_weighting, "hedge_sizing": self.hedge_sizing,
            "regression_window": self.regression_window,
            "regression_basis": self.regression_basis,
            "regression_target": self.regression_target,
            "entry_rule": self.entry_rule,
            "z_entry": self.z_entry, "z_window": self.z_window,
            "carry_min_bp": self.carry_min_bp, "rebalance_days": self.rebalance_days,
            "holding_days": self.holding_days, "direction": self.direction,
            "ca_dv01": self.ca_dv01, "cost_bp_roundtrip": self.cost_bp_roundtrip,
        }

    def __post_init__(self) -> None:
        if self.fly_weighting not in ("regression", "dv01_neutral"):
            raise ValueError(f"bad fly_weighting {self.fly_weighting!r}")
        if self.hedge_sizing not in ("regression_beta", "dv01_ratio", "unhedged"):
            raise ValueError(f"bad hedge_sizing {self.hedge_sizing!r}")
        if self.entry_rule not in ("always", "ca_z", "vs_model_z", "carry"):
            raise ValueError(f"bad entry_rule {self.entry_rule!r}")
        if self.regression_basis not in ("levels", "changes"):
            raise ValueError(f"bad regression_basis {self.regression_basis!r}")
        if self.regression_target not in ("rank", "label"):
            raise ValueError(f"bad regression_target {self.regression_target!r}")
        if self.z_window not in ("z3m", "z1y"):
            raise ValueError(f"bad z_window {self.z_window!r}")
        if self.direction not in ("short_ca", "long_ca"):
            raise ValueError(f"bad direction {self.direction!r}")
        if self.holding_days < 1 or self.rebalance_days < 1:
            raise ValueError("holding_days and rebalance_days must be >= 1")

    @property
    def sign(self) -> float:
        """``+1`` for short CA, ``-1`` for long CA."""
        return 1.0 if self.direction == "short_ca" else -1.0


# ===========================================================================
# Inputs
# ===========================================================================
@dataclass
class GridInputs:
    """Everything a cell needs, prepared ONCE and shared across the whole grid.

    Recomputing z-scores or pivoting the CA panel per cell would dominate the
    runtime and, worse, would make it possible for two cells to disagree about
    the same market. One preparation, many cells.
    """

    panel: pd.DataFrame                   # long CA panel (date, rank, pack, ...)
    ca: pd.DataFrame                      # wide date x pack, bp
    swap_rate: pd.DataFrame               # wide date x pack, percent
    t_mid: pd.DataFrame                   # wide date x pack, years
    ca_z3m: pd.DataFrame
    ca_z1y: pd.DataFrame
    vs_model_z3m: pd.DataFrame
    vs_model_z1y: pd.DataFrame
    roll_3m: pd.DataFrame                 # wide date x pack, bp
    legs: pd.DataFrame                    # wide date x tenor, percent
    carry: Optional[pd.DataFrame]         # wide date x tenor, bp (3M horizon)
    dates: pd.DatetimeIndex
    specs: Dict[str, FlySpec] = field(default_factory=dict)

    def rank_labels(self, rank: int) -> pd.Series:
        """``date -> pack label`` for one rank, over the common date axis."""
        return rank_label_series(self.panel, rank).reindex(self.dates)


def _wide(panel: pd.DataFrame, col: str) -> pd.DataFrame:
    return panel.pivot_table(index="date", columns="pack", values=col,
                             aggfunc="last").sort_index()


def prepare_inputs(
    panel: pd.DataFrame,
    legs: pd.DataFrame,
    *,
    carry: Optional[pd.DataFrame] = None,
    strat2_cfg: Optional[Any] = None,
    specs: Optional[Sequence[FlySpec]] = None,
) -> GridInputs:
    """Pivot the CA panel, derive the z-scores and the roll, align to the legs.

    ``ts``/``model`` come from
    :func:`~RVUtils.ConvexityRV.strat2_sofr_convexity.panel_timeseries` and
    ``model_timeseries`` -- reused rather than re-derived, so the grid's
    z-scores are literally the screen's z-scores.

    The **3m roll** is Citi's ``Roll(p) = CA(p) - CA(p one contract nearer)``,
    which needs the panel's rank axis (the nearer window), so it is rebuilt here
    on the wide label axis: for each date, the roll of the label at rank ``k``
    is its CA minus the CA of the label at rank ``k-1`` on the same date.
    """
    from RVUtils.ConvexityRV.strat2_sofr_convexity import (
        Strat2Config,
        model_timeseries,
        panel_timeseries,
    )

    cfg = strat2_cfg if strat2_cfg is not None else Strat2Config()
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    ts = panel_timeseries(panel, cfg)
    model = model_timeseries(panel, cfg)

    ca = ts["ca"]
    # roll: CA(rank k) - CA(rank k-1), mapped back onto the k label
    roll = pd.DataFrame(np.nan, index=ca.index, columns=ca.columns)
    by = panel.pivot_table(index="date", columns="rank", values="ca_bp", aggfunc="last")
    lab = panel.pivot_table(index="date", columns="rank", values="pack", aggfunc="last")
    for k in by.columns:
        if (k - 1) not in by.columns:
            continue
        diff = by[k] - by[k - 1]
        for d, v in diff.dropna().items():
            p = lab.at[d, k]
            if isinstance(p, str) and p in roll.columns:
                roll.at[d, p] = v

    common = ca.index.intersection(legs.index)
    idx = pd.DatetimeIndex(sorted(common))
    return GridInputs(
        panel=panel,
        ca=ca.reindex(idx),
        swap_rate=_wide(panel, "swap_rate").reindex(idx),
        t_mid=_wide(panel, "t_mid").reindex(idx),
        ca_z3m=ts["ca_z3m"].reindex(idx),
        ca_z1y=ts["ca_z1y"].reindex(idx),
        vs_model_z3m=model["vs_model_z3m"].reindex(idx),
        vs_model_z1y=model["vs_model_z1y"].reindex(idx),
        roll_3m=roll.reindex(idx),
        legs=legs.reindex(idx),
        carry=carry.reindex(idx) if carry is not None else None,
        dates=idx,
        specs={s.fly_id: s for s in (specs if specs is not None else fly_universe())},
    )


def rank_label_series(panel: pd.DataFrame, rank: int) -> pd.Series:
    """``date -> pack label`` at a fixed rolling rank."""
    sub = panel[panel["rank"] == int(rank)]
    return sub.set_index("date")["pack"].sort_index()


def rank_following_ca(inp: "GridInputs", rank: int) -> pd.Series:
    """Citi's *"Blues CA"*: the CA at a fixed rolling RANK, as a level series.

    A colour is a position on the strip, not a pack: it is re-pointed at a new
    set of four contracts every IMM roll. So this series has genuine roll steps
    in it -- and it is nonetheless the object Citi regresses, because it is the
    only one with years of history. The constant-contract alternative
    (``inp.ca[label]``) has no roll steps but only exists from the moment the
    label enters the visible strip, which for rank 10 of a 13-contract strip is
    essentially never. Both are offered; the difference is a config knob and
    the trade-off is stated rather than hidden.
    """
    labels = inp.rank_labels(rank)
    vals = [inp.ca.at[d, p] if isinstance(p, str) and p in inp.ca.columns else np.nan
            for d, p in labels.items()]
    return pd.Series(vals, index=labels.index, name=f"rank{rank}")


def constant_contract_dca(ca: pd.DataFrame, labels: pd.Series) -> pd.Series:
    """Daily ``dCA`` of the pack at a fixed RANK, computed CONSTANT-CONTRACT.

    The naive ``ca_at_rank.diff()`` is wrong: on an IMM roll the rank points at
    a different pack and the "change" is the width of the CA term structure, not
    a market move -- a jump of several bp that no position ever earned. Here the
    difference is taken within the label that the rank pointed at *today*, so a
    roll date simply produces NaN (there is no yesterday for that label at that
    rank) instead of a fabricated return.
    """
    labels = labels.reindex(ca.index)
    prev = ca.index.to_series().shift(1)
    out = pd.Series(np.nan, index=ca.index, dtype=float)
    for d in ca.index:
        p = labels.get(d)
        d0 = prev.get(d)
        if not isinstance(p, str) or pd.isna(d0) or p not in ca.columns:
            continue
        a, b = ca.at[d, p], ca.at[d0, p]
        if np.isfinite(a) and np.isfinite(b):
            out.at[d] = a - b
    return out


# ===========================================================================
# Epochs
# ===========================================================================
@dataclass(frozen=True)
class Epoch:
    """One held position. Weights and DV01s are FIXED here, at entry, forever."""

    entry: pd.Timestamp
    exit: pd.Timestamp
    pack: str
    rank: int
    w_front: float
    w_back: float
    belly_dv01: float
    ca_dv01: float
    fit: Optional[FlyFit]
    ca_entry_bp: float
    fly_entry_bp: float


def citi_belly_dv01(ca_dv01: float, beta: float) -> float:
    """``belly_DV01 = CA_DV01 * beta / 100`` -- Citi's §5.4 rule, verbatim.

    *"fly_belly_DV01 = CA_DV01 * beta / 100 [beta from §5.3; /100 converts % ->
    bp]"*. Verified against both published notional sets: $100k CA DV01 at
    beta 21.4 needs $21,400/bp and Citi published -$44.4mn of 5y, which is
    $21,312/bp at the era's $480/mn -- **ratio 1.004** on the required-to-
    published comparison. $200k at beta 20.6 -> $41,200 vs $41,088 -- **1.003**.
    """
    return float(ca_dv01) * float(beta) / 100.0


def _entry_ok(inp: GridInputs, cfg: Strat2GridConfig, d: pd.Timestamp,
              pack: str) -> bool:
    if cfg.entry_rule == "always":
        return True
    if cfg.entry_rule == "carry":
        v = inp.roll_3m.at[d, pack] if pack in inp.roll_3m.columns else np.nan
        return bool(np.isfinite(v) and v >= cfg.carry_min_bp)
    frame = {"ca_z": {"z3m": inp.ca_z3m, "z1y": inp.ca_z1y},
             "vs_model_z": {"z3m": inp.vs_model_z3m,
                            "z1y": inp.vs_model_z1y}}[cfg.entry_rule][cfg.z_window]
    v = frame.at[d, pack] if pack in frame.columns else np.nan
    return bool(np.isfinite(v) and v >= cfg.z_entry)


def plan_epochs(inp: GridInputs, cfg: Strat2GridConfig,
                spec: FlySpec) -> List[Epoch]:
    """Walk the rebalance calendar; fit, size and freeze one epoch at a time.

    The regression slice is ``ca.loc[:entry]`` -- inclusive of the entry date's
    own close and nothing after it. That is the information a desk striking the
    trade on that close actually has.
    """
    dates = inp.dates
    labels = inp.rank_labels(cfg.pack_rank)
    start_i = max(cfg.regression_window + cfg.burn_in_days, 1)
    if start_i >= len(dates):
        return []
    out: List[Epoch] = []
    i = start_i
    while i < len(dates):
        d = dates[i]
        pack = labels.get(d)
        if not isinstance(pack, str) or pack not in inp.ca.columns:
            i += cfg.rebalance_days
            continue
        if not _entry_ok(inp, cfg, d, pack):
            i += cfg.rebalance_days
            continue

        if cfg.regression_target == "rank":
            ca_hist = rank_following_ca(inp, cfg.pack_rank).loc[:d].dropna()
        else:
            ca_hist = inp.ca[pack].loc[:d].dropna()
        fit = fly_regression(ca_hist, inp.legs.loc[:d], spec,
                             window_days=cfg.regression_window,
                             require_positive_wings=cfg.require_positive_wings,
                             min_abs_beta=cfg.min_abs_beta,
                             basis=cfg.regression_basis)
        if cfg.fly_weighting == "regression":
            if not np.isfinite(fit.w_front) or not np.isfinite(fit.w_back):
                i += cfg.rebalance_days
                continue
            wf, wk = float(fit.w_front), float(fit.w_back)
        else:
            wf, wk = DV01_NEUTRAL_WINGS

        if cfg.hedge_sizing == "unhedged":
            belly = 0.0
        elif cfg.hedge_sizing == "dv01_ratio":
            belly = float(cfg.ca_dv01) * float(cfg.dv01_ratio)
        else:
            if not np.isfinite(fit.beta):
                i += cfg.rebalance_days
                continue
            belly = citi_belly_dv01(cfg.ca_dv01, fit.beta)

        j = min(i + cfg.holding_days, len(dates) - 1)
        if j <= i:
            break
        legs_e = inp.legs.loc[d]
        if any(not np.isfinite(legs_e.get(t, np.nan)) for t in spec.tenors):
            i += cfg.rebalance_days
            continue
        out.append(Epoch(
            entry=d, exit=dates[j], pack=pack, rank=cfg.pack_rank,
            w_front=wf, w_back=wk, belly_dv01=belly, ca_dv01=float(cfg.ca_dv01),
            fit=fit, ca_entry_bp=float(inp.ca.at[d, pack]),
            fly_entry_bp=100.0 * (-abs(wf) * legs_e[spec.front] + legs_e[spec.belly]
                                  - abs(wk) * legs_e[spec.back]),
        ))
        i = j if j > i else i + cfg.rebalance_days
        # next decision point is on/after the exit, on the rebalance grid
        while i < len(dates) and (i - start_i) % cfg.rebalance_days != 0:
            i += 1
    return out


# ===========================================================================
# The ledger
# ===========================================================================
def _ann_sharpe(x: pd.Series) -> float:
    x = x.dropna()
    if len(x) < 2:
        return float("nan")
    sd = float(x.std(ddof=1))
    return float("nan") if sd == 0 else float(x.mean() / sd * math.sqrt(252.0))


def _max_drawdown(cum: pd.Series) -> float:
    if cum.empty:
        return float("nan")
    return float((cum - cum.cummax()).min())


def _r2(y: pd.Series, x: pd.Series) -> float:
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(j) < 10:
        return float("nan")
    xv = np.column_stack([np.ones(len(j)), j["x"].to_numpy(float)])
    yv = j["y"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(xv, yv, rcond=None)
    resid = yv - xv @ coef
    sst = float(((yv - yv.mean()) ** 2).sum())
    return float("nan") if sst <= 0 else 1.0 - float((resid ** 2).sum()) / sst


@dataclass
class CellResult:
    """One grid cell: the ledger plus every score the grid is read on."""

    cfg: Strat2GridConfig
    spec: FlySpec
    epochs: List[Epoch]
    daily: pd.DataFrame          # date -> ca_pnl, fly_pnl, gamma_pnl, pnl, in_position
    metrics: Dict[str, Any]

    def to_row(self) -> Dict[str, Any]:
        row = dict(self.cfg.key())
        row["shape"] = self.spec.shape
        row["forward_start_y"] = self.spec.forward_start_y
        row.update(self.metrics)
        return row


def simulate_cell(inp: GridInputs, cfg: Strat2GridConfig) -> CellResult:
    """Run one cell end to end and score it.

    The ledger is a daily currency P&L over the FULL common date axis, zero when
    flat -- so the Sharpe reported is a portfolio Sharpe including the time the
    strategy sits out, which is the honest number when entry rules are being
    compared. ``sharpe_active`` (in-position days only) is reported alongside.
    """
    spec = inp.specs.get(cfg.fly_id) or fly_by_id(cfg.fly_id)
    epochs = plan_epochs(inp, cfg, spec)
    s = cfg.sign
    idx = inp.dates
    ca_pnl = pd.Series(0.0, index=idx)
    fly_pnl = pd.Series(0.0, index=idx)
    gam_pnl = pd.Series(0.0, index=idx)
    unh_pnl = pd.Series(0.0, index=idx)
    in_pos = pd.Series(False, index=idx)
    cost = pd.Series(0.0, index=idx)
    epoch_pnl: List[float] = []
    carry_bp: List[float] = []
    d_ca_all: List[pd.Series] = []
    d_fly_all: List[pd.Series] = []

    for ep in epochs:
        win = idx[(idx > ep.entry) & (idx <= ep.exit)]
        if len(win) == 0:
            continue
        hold = idx[(idx >= ep.entry) & (idx <= ep.exit)]
        ca_h = inp.ca[ep.pack].reindex(hold)
        d_ca = ca_h.diff().reindex(win)
        legs_h = inp.legs.reindex(hold)
        fly_h = fly_rate_series(legs_h, spec, ep.w_front, ep.w_back)
        d_fly = fly_h.diff().reindex(win)

        ca_leg = (-s * d_ca * ep.ca_dv01).fillna(0.0)
        fly_leg = (s * d_fly * ep.belly_dv01).fillna(0.0)

        # ---- second order -------------------------------------------------
        t1 = float(np.nanmean(inp.t_mid[ep.pack].reindex(hold))) - T_MID_TO_T1
        sw = inp.swap_rate[ep.pack].reindex(hold)
        d_sw_bp = (sw.diff() * 100.0).reindex(win)
        d_a = annuity_duration(max(t1, 0.0), 1.0, float(np.nanmean(sw)))
        g_ca = (-s * ep.ca_dv01 * d_a * 1e-4 * d_sw_bp ** 2).fillna(0.0)
        g_fly = pd.Series(0.0, index=win)
        if ep.belly_dv01 != 0.0:
            r_e = inp.legs.loc[ep.entry]
            dd = {t: (legs_h[t].diff() * 100.0).reindex(win) for t in spec.tenors}
            df = annuity_duration(spec.forward_start_y, spec.front_y, float(r_e[spec.front]))
            db = annuity_duration(spec.forward_start_y, spec.belly_y, float(r_e[spec.belly]))
            dk = annuity_duration(spec.forward_start_y, spec.back_y, float(r_e[spec.back]))
            g_fly = (-s * ep.belly_dv01 * 1e-4 *
                     (db * dd[spec.belly] ** 2
                      - abs(ep.w_front) * df * dd[spec.front] ** 2
                      - abs(ep.w_back) * dk * dd[spec.back] ** 2)).fillna(0.0)

        ca_pnl.loc[win] += ca_leg
        fly_pnl.loc[win] += fly_leg
        gam_pnl.loc[win] += g_ca + g_fly
        unh_pnl.loc[win] += ca_leg
        in_pos.loc[win] = True
        ep_cost = cfg.cost_bp_roundtrip * (ep.ca_dv01 + abs(ep.belly_dv01))
        cost.loc[ep.entry] += ep_cost      # the whole round trip, charged at entry
        tot = float((ca_leg + fly_leg).sum())
        if cfg.include_gamma:
            tot += float((g_ca + g_fly).sum())
        epoch_pnl.append(tot - ep_cost)
        if inp.carry is not None:
            try:
                c = fly_carry_series(inp.carry.loc[[ep.entry]], spec, ep.w_front, ep.w_back)
                carry_bp.append(float(c.iloc[0]))
            except Exception:                                 # noqa: BLE001
                pass
        d_ca_all.append(d_ca)
        d_fly_all.append(d_fly)

    pnl = ca_pnl + fly_pnl + (gam_pnl if cfg.include_gamma else 0.0)
    unh = unh_pnl + (gam_pnl if cfg.include_gamma else 0.0)
    net = pnl - cost
    daily = pd.DataFrame({"ca_pnl": ca_pnl, "fly_pnl": fly_pnl, "gamma_pnl": gam_pnl,
                          "cost": cost, "pnl": pnl, "pnl_net": net,
                          "unhedged_pnl": unh, "in_position": in_pos})

    d_ca_c = pd.concat(d_ca_all) if d_ca_all else pd.Series(dtype=float)
    d_fly_c = pd.concat(d_fly_all) if d_fly_all else pd.Series(dtype=float)
    hedged_var = float(pnl[in_pos].var(ddof=1)) if in_pos.any() else float("nan")
    unh_var = float(unh[in_pos].var(ddof=1)) if in_pos.any() else float("nan")

    n_days = int(in_pos.sum())
    cost_total = float(cost.sum())
    total = float(net.sum())
    metrics: Dict[str, Any] = {
        "n_epochs": len(epochs),
        "n_days_in_position": n_days,
        "first_entry": epochs[0].entry.date() if epochs else None,
        "last_exit": epochs[-1].exit.date() if epochs else None,
        "total_pnl": total,
        "ca_leg_pnl": float(ca_pnl.sum()),
        "fly_leg_pnl": float(fly_pnl.sum()),
        "gamma_pnl": float(gam_pnl.sum()),
        "gamma_share": (float(gam_pnl.sum()) / abs(float(pnl.sum()))
                        if float(pnl.sum()) != 0 else float("nan")),
        "cost_paid": cost_total,
        "sharpe": _ann_sharpe(net),
        "sharpe_active": _ann_sharpe(net[in_pos]),
        "max_drawdown": _max_drawdown(net.cumsum()),
        "hit_rate": (float(np.mean([p > 0 for p in epoch_pnl]))
                     if epoch_pnl else float("nan")),
        "hedge_r2": _r2(d_ca_c, d_fly_c),
        "variance_reduction": (1.0 - hedged_var / unh_var
                               if np.isfinite(hedged_var) and unh_var > 0 else float("nan")),
        "corr_dca_dfly": (float(pd.concat([d_ca_c.rename("a"), d_fly_c.rename("b")],
                                          axis=1).dropna().corr().iloc[0, 1])
                          if len(d_ca_c) > 10 else float("nan")),
        "fly_carry_3m_bp": float(np.nanmean(carry_bp)) if carry_bp else float("nan"),
        "mean_beta": float(np.nanmean([e.fit.beta for e in epochs if e.fit])) if epochs else np.nan,
        "mean_w_front": float(np.nanmean([e.w_front for e in epochs])) if epochs else np.nan,
        "mean_w_back": float(np.nanmean([e.w_back for e in epochs])) if epochs else np.nan,
        "mean_belly_dv01": float(np.nanmean([e.belly_dv01 for e in epochs])) if epochs else np.nan,
        "mean_fit_r2": float(np.nanmean([e.fit.r2 for e in epochs if e.fit])) if epochs else np.nan,
        "frac_fit_expressible": (float(np.mean([bool(e.fit and e.fit.ok) for e in epochs]))
                                 if epochs else float("nan")),
    }
    gross = float(pnl.sum())
    unit_cost = sum(cfg.cost_bp_roundtrip * (e.ca_dv01 + abs(e.belly_dv01)) for e in epochs)
    for m in COST_MULTIPLIERS:
        metrics[f"pnl_cost_{m:g}x"] = gross - m * unit_cost
    return CellResult(cfg=cfg, spec=spec, epochs=epochs, daily=daily, metrics=metrics)


# ===========================================================================
# The grid
# ===========================================================================
def run_grid(
    inp: GridInputs,
    base: Optional[Strat2GridConfig] = None,
    *,
    axes: Optional[Dict[str, Sequence[Any]]] = None,
    progress: bool = True,
    keep_ledgers: bool = False,
) -> Tuple[pd.DataFrame, Dict[Tuple, CellResult]]:
    """Cartesian product over ``axes`` on top of ``base``. Returns ``(rows, cells)``.

    ``axes`` maps a ``Strat2GridConfig`` field name to the values it takes, e.g.
    ``{"fly_id": [...], "pack_rank": [5, 8], "regression_window": [63, 252]}``.
    A cell that produces no epochs is still emitted, with ``n_epochs=0`` -- a
    silently dropped cell is indistinguishable from a cell that lost money.
    """
    base = base or Strat2GridConfig()
    axes = axes or {}
    names = list(axes)
    combos = list(itertools.product(*[list(axes[n]) for n in names])) if names else [()]
    rows: List[Dict[str, Any]] = []
    cells: Dict[Tuple, CellResult] = {}
    for i, combo in enumerate(combos):
        cfg = replace(base, **dict(zip(names, combo)))
        try:
            res = simulate_cell(inp, cfg)
        except Exception as exc:                              # noqa: BLE001
            rows.append({**cfg.key(), "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(res.to_row())
        if keep_ledgers:
            cells[combo] = res
        if progress and (i + 1) % 25 == 0:
            print(f"  grid {i + 1}/{len(combos)}", flush=True)
    return pd.DataFrame(rows), cells


# ===========================================================================
# THE HYPOTHESIS TABLE
# ===========================================================================
def effectiveness_matrix(
    inp: GridInputs,
    *,
    shape: str = "2s5s10s",
    ranks: Sequence[int] = (2, 3, 4, 5, 6, 7, 8, 9, 10),
    forward_starts: Sequence[float] = (0.0, 1.0, 2.0, 3.0, 5.0),
    weighting: str = "dv01_neutral",
    window: int = 252,
    metric: str = "r2",
) -> pd.DataFrame:
    """``(pack T1) x (fly forward start)`` hedge effectiveness. **The deliverable.**

    For every pack rank and every forward start of one shape, regress the pack's
    **constant-contract daily dCA** on the fly's daily change and report ``R^2``
    (or ``beta``/``corr``). Constant-contract matters: the naive rank-following
    diff jumps on every IMM roll, and those jumps would show up as unexplained
    CA variance, biasing every ``R^2`` down by a different amount per rank.

    ``weighting="dv01_neutral"`` fixes the fly's wings at 50/50 so the columns
    are comparable across forward starts -- with regression weights each cell
    would be fitted to its own target and the ``R^2`` would be a statement about
    the fit, not about the instrument. ``weighting="regression"`` is available
    and uses a single full-sample fit per cell (an in-sample upper bound,
    labelled as such).

    Read it as: **does R^2 rise as the fly's forward start approaches the pack's
    T1?** The index carries the mean ``T1`` of each rank so the diagonal is
    visible.
    """
    specs = {s.forward_start_y: s for s in fly_universe()
             if s.shape == shape and s.forward_start_y in tuple(forward_starts)}
    if not specs:
        raise KeyError(f"no flies for shape {shape!r} at forward starts {forward_starts}")
    rows: List[Dict[str, Any]] = []
    for rank in ranks:
        labels = inp.rank_labels(rank)
        d_ca = constant_contract_dca(inp.ca, labels)
        t1 = float(np.nanmean(
            [inp.t_mid.at[d, p] for d, p in labels.dropna().items()
             if isinstance(p, str) and p in inp.t_mid.columns
             and np.isfinite(inp.t_mid.at[d, p])])) - T_MID_TO_T1
        row: Dict[str, Any] = {"rank": rank, "T1_years": t1,
                               "n_obs": int(d_ca.notna().sum())}
        for fs in forward_starts:
            spec = specs.get(fs)
            if spec is None:
                row[f"fs_{fs:g}Y"] = np.nan
                continue
            if weighting == "regression":
                ca_lvl = pd.Series(
                    [inp.ca.at[d, p] if isinstance(p, str) and p in inp.ca.columns
                     else np.nan for d, p in labels.items()], index=labels.index)
                fit = fly_regression(ca_lvl.dropna(), inp.legs, spec,
                                     window_days=max(window, int(ca_lvl.notna().sum())))
                wf, wk = (fit.w_front, fit.w_back) if np.isfinite(fit.w_front) \
                    else DV01_NEUTRAL_WINGS
            else:
                wf, wk = DV01_NEUTRAL_WINGS
            d_fly = fly_rate_series(inp.legs, spec, wf, wk).diff()
            if metric == "r2":
                row[f"fs_{fs:g}Y"] = _r2(d_ca, d_fly)
            elif metric == "corr":
                j = pd.concat([d_ca.rename("a"), d_fly.rename("b")], axis=1).dropna()
                row[f"fs_{fs:g}Y"] = float(j.corr().iloc[0, 1]) if len(j) > 10 else np.nan
            else:                                             # "beta"
                j = pd.concat([d_ca.rename("a"), d_fly.rename("b")], axis=1).dropna()
                if len(j) < 10:
                    row[f"fs_{fs:g}Y"] = np.nan
                else:
                    x = np.column_stack([np.ones(len(j)), j["b"]])
                    row[f"fs_{fs:g}Y"] = float(
                        np.linalg.lstsq(x, j["a"].to_numpy(float), rcond=None)[0][1])
        rows.append(row)
    return pd.DataFrame(rows).set_index("rank")


def hypothesis_slope(matrices: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Reduce a set of :func:`effectiveness_matrix` results to ONE falsifiable number.

    The hypothesis is *"a fly starting ``F`` years forward hedges the pack whose
    expiry ``T1`` is near ``F``"*. Its sharp prediction is that, for each fly,
    the pack ``T1`` at which that fly is MOST effective should track its forward
    start one-for-one::

        argmax_T1 R^2(F)  =  a + b*F      with  b ~ +1.0

    So: for every (shape, forward start) cell, find the rank whose ``R^2`` is
    highest, take that rank's mean ``T1``, and regress those ``T1`` values on the
    forward start across all cells. ``b`` near 0 means the fly's forward start
    tells you nothing about which pack it hedges.

    Returns ``slope``, ``corr``, ``n``, and ``peak_r2_by_start`` (the mean best
    ``R^2`` at each forward start, which is the second half of the story: even
    where a forward fly wins, does it win at a useful level?).
    """
    fs_cols: Optional[List[str]] = None
    rows: List[Tuple[float, float, float]] = []
    peaks: Dict[float, List[float]] = {}
    for shape, m in matrices.items():
        if fs_cols is None:
            fs_cols = [c for c in m.columns if c.startswith("fs_")]
        for c in fs_cols:
            f = float(c[3:-1])
            v = m[c].to_numpy(float)
            if not np.isfinite(v).any():
                continue
            i = int(np.nanargmax(v))
            rows.append((f, float(m["T1_years"].to_numpy()[i]), float(v[i])))
            peaks.setdefault(f, []).append(float(v[i]))
    if len(rows) < 3:
        return {"slope": float("nan"), "corr": float("nan"), "n": len(rows),
                "peak_r2_by_start": {}}
    a = np.array(rows, dtype=float)
    slope = float(np.polyfit(a[:, 0], a[:, 1], 1)[0])
    corr = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]) if a[:, 0].std() > 0 else float("nan")
    return {"slope": slope, "corr": corr, "n": len(rows),
            "peak_r2_by_start": {k: float(np.mean(v)) for k, v in sorted(peaks.items())}}
