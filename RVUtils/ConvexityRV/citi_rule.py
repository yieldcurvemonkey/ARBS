r"""Citi's published convexity trade as one pre-specified rule.

Frozen by ``docs/convexityrv/citi-framework-preregistration.md`` BEFORE any
scoring.  The cell list is generated here and counted against that document in
the test suite; a scored cell that is not declared there is a trial-count leak.

What this is, and why it is not block 4 again
---------------------------------------------
Block 4 (``gv_grid``) scored 298 cells of "CA versus a butterfly, z-score in,
z-score out" and found nothing.  **That grid did not test Citi's rule.**  The
note's own framework differs in six specific ways, and every one of them is
implemented here rather than approximated:

1. the hedge weights are the **output** of a 3-rate regression, not a rolling
   univariate beta against a fixed 50/50 fly (:mod:`citi_fv`);
2. the hedge is **re-struck** at each quarterly refit, not frozen at entry;
3. a **screen across the strip** picks which structure to trade
   (:mod:`citi_screen`), rather than one structure per cell;
4. entry is a **conjunction** of five conditions, not ``|z| >= 2``;
5. exit is an explicit **dollar target and stop** (+$600k / -$350k on $200k
   DV01 = +3.0 / -1.75 bp of the spread), not a z-exit;
6. the book is **short only** -- Citi sells rich convexity, and the two-sided
   version of block 4's grid doubled its own opportunity set for free.

The five entry conditions, in the note's own words
--------------------------------------------------
============================ ==================================================
``wide_to_model``            "The Blues pack CA looks especially attractive
                             being roughly 4bp (about two sigmas) wide to the
                             model"
``wide_to_fly``              "The CA is about 3bp (about 2 sigmas) wide to the
                             fly"
``positive_roll``            "short-CA rolldown +1.3bp over 3m" -- the roll
                             must pay the direction being taken
``implied_rich``             "CA implied vol ~30% rich to 3m realized";
                             Figure 20's H0-Z0 row prints Impl/Rlzd 1.3
``positioning_stretched``    "Long dealers' positions in futures reached
                             historically high levels, which should have put
                             pressure on dealers' risk limits and therefore
                             translated into wider CAs"
============================ ==================================================

Conventions that are load-bearing
---------------------------------
**Fills lag decisions by one mark.**  ``exec_lag_bd = 1``.  The CA mark is a
composite of a futures bar and a separately-timed swap curve; a rule that
enters at the mark it was computed from buys mark noise nobody can trade.

**The signal runs on the RAW quoted CA; the P&L runs on the ROLL-SPLICED one.**
These are two different questions and they need two different series, which is
not obvious and was measured rather than assumed:

* the SCREEN asks whether a RANK of the curve is rich against its own history.
  A constant-rank CA is stationary, and it is stationary *because* the quarterly
  roll pays back the decay it accrued (measured here: +0.95 bp/roll on BLUES
  against a quarter-theta of 0.92, ratio 1.024).  That is the object Citi's
  Figure 20 z-scores, so it is the object the conditions are evaluated on;
* the P&L asks what a DATED position earns.  A dated position has no label to
  switch, so it never receives the roll jump -- it just decays.  The spliced
  series is exactly that path.

Using the spliced series for the SIGNAL as well would have been the natural
mistake: it carries the whole undone decay as a ~20 bp downward drift over the
window, so its 252-day rolling z sits at a median of -1.15 to -1.31 instead of
-0.20 to -0.53, and the "wide to model" gate then almost never fires for the
wrong reason.  Measured in ``_p4_conjunction_probe.py``.

The splice is FORWARD (causal).  Its known cost is that a roll date's genuine
market move is discarded along with the contract switch -- about 0.15 bp of
level over 22 rolls, against the +0.95 bp/roll it removes -- and the engine,
which prices real dated instruments, is the authority on the difference.

**The panel is a signal tool; the engine is the number.**  This package
measured a par-rate panel overstating three hedged Sharpes by 1.5-6x and
understating an unhedged book's dollars by 2-3.8x.  Every book reported here is
re-priced through ``QueryDrivenBacktest`` on dated instruments and the engine
number is the one quoted.  Because the engine's triggers are precomputed dates,
the target/stop is evaluated on panel marks and the engine replays those exact
exit dates -- so the fly's own rolldown and the swap leg's accrual are invisible
to the stop, which is stated rather than hidden.

Units: CA, model, fly and spread in **bp**; vol in **bp/yr**; P&L in **USD**;
``beta`` in bp of CA per bp of the quoted fly combination.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import citi_fv as FV
from RVUtils.ConvexityRV import citi_screen as SC

__all__ = [
    "CONDITIONS",
    "COST_MULTS",
    "FUT_RT_BP",
    "HEDGE_SCHEMES",
    "LEG_RT_BP",
    "PRIMARY_UNIVERSE",
    "SECONDARY_UNIVERSE",
    "SELECTIONS",
    "SWAP_RT_BP",
    "CellResult",
    "CellSpec",
    "CitiEpisode",
    "RuleConfig",
    "StructureContext",
    "book_daily",
    "build_contexts",
    "clear_fv_memo",
    "condition_binding",
    "declared_cells",
    "episode_cost_usd",
    "episode_daily_pnl",
    "episodes_from_contexts",
    "null_bars",
    "run_cell",
    "stats_frame",
]

#: Round-trip costs in bp, charged on the relevant DV01 at the unwind.  Block
#: 4's convention, unchanged, so the two blocks' net numbers are comparable:
#: CME's 0.25 bp pack/bundle tick (one package tick regardless of leg count),
#: 0.5 bp on the matched swap, 0.5 bp per swap leg of the fly.
FUT_RT_BP = 0.25
SWAP_RT_BP = 0.5
LEG_RT_BP = 0.5

COST_MULTS: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

#: The five conditions of the note's entry conjunction, in its own order.
CONDITIONS: Tuple[str, ...] = (
    "wide_to_model", "wide_to_fly", "positive_roll", "implied_rich",
    "positioning_stretched",
)

#: How the hedge leg is chosen and maintained.
#:
#: ``fitted_refit``   Citi's method: fly-constrained 3-rate fit, re-struck at
#:                    every quarterly refit that falls inside the hold.
#: ``fitted_frozen``  the same fit, but the parameters in force AT ENTRY are
#:                    held for the life of the trade -- block 4's convention,
#:                    and the direct test of whether the mid-2023 sign reversal
#:                    of ``b`` destroys the book.
#: ``citi_2017``      Citi's published 0.705 / -1 / 0.465 weights held fixed,
#:                    level and scale refit at each roll.  Measured as the
#:                    LOWEST out-of-sample residual sd of any scheme tried.
#: ``unhedged``       no fly leg at all -- the note's own April-2018 variant
#:                    ("outright/unhedged this time"), which still uses the
#:                    fitted fair value for the SIGNAL.
HEDGE_SCHEMES: Tuple[str, ...] = ("fitted_refit", "fitted_frozen", "citi_2017",
                                  "unhedged")

#: How the traded structure is chosen.
SELECTIONS: Tuple[str, ...] = ("screen_best", "blues", "screen_best_all5")

#: The two declared readings of the note's "about two sigmas wide".
#:
#: ``2.0`` is the note's own printed entry ("roughly 4bp (about two sigmas) wide
#: to the model", "about 3bp (about 2 sigmas) wide to the fly"), and the origin
#: note reads 2.5-3 sigmas, so 2.0 is already the loosest of Citi's own numbers.
#:
#: ``1.0`` exists because the five-way conjunction at 2.0 is satisfied on **2 of
#: 1,409 dates** -- measured in ``_p4_conjunction_probe.py`` BEFORE this list was
#: frozen -- and a book with one trade cannot be graded.  It is a widening of the
#: note's own reading, declared as such, and it costs trials.  The intermediate
#: rungs (1.5 -> 2 days, 0.5 -> 30 days) were measured at the same time and are
#: deliberately NOT scored; the ladder this block did not walk is in the
#: pre-registration so the reader can see it.
Z_LEVELS: Tuple[float, ...] = (2.0, 1.0)

#: The primary selection universe.  WHITES and REDS are excluded from it
#: because their daily CA marks sit at or past the -0.5 pure-noise bound
#: (AC1 -0.540 / -0.517), so a "pick the widest" rule over them adversely
#: selects their noise spikes rather than dislocations.  ``screen_best_all5``
#: is the declared secondary cell that measures exactly that.
PRIMARY_UNIVERSE: Tuple[str, ...] = ("GREENS", "BLUES", "GOLDS")
SECONDARY_UNIVERSE: Tuple[str, ...] = SC.SCREEN_STRUCTURES


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleConfig:
    """Every knob, with the note's own printed value beside it."""

    # ---- the entry conjunction ------------------------------------------
    #: "roughly 4bp (about two sigmas) wide to the model"
    z_model_min: float = 2.0
    #: "about 3bp (about 2 sigmas) wide to the fly"
    z_fly_min: float = 2.0
    #: "short-CA rolldown +1.3bp over 3m" -- the roll must pay the short.
    require_positive_roll: bool = True
    #: Figure 20's H0-Z0 row prints Impl/Rlzd 1.3, and the origin note says the
    #: CA implied vol is "about 30% rich to 3m realized".  The threshold is the
    #: note's own printed entry value, not an interpolation of it.
    impl_rlzd_min: float = 1.3
    #: "Long dealers' positions in futures reached historically high levels."
    z_pos_min: float = 1.0
    #: Which condition set is active.  A dropped condition is recorded, not
    #: silently satisfied.
    conditions: Tuple[str, ...] = CONDITIONS

    # ---- windows ---------------------------------------------------------
    #: The z-scores the note quotes as "sigmas" are 1Y.
    z_window_bd: int = 252
    #: The reproduction's declared fair-value refit window.
    fit_window_bd: int = 504

    # ---- the exit --------------------------------------------------------
    #: "+$600k profit" on "$200k DV01" = +3.0 bp of the spread.
    target_bp: float = 3.0
    #: "stop at -$350k loss" on the same DV01 = -1.75 bp.
    stop_bp: float = -1.75
    #: Citi's two published trades ran 82 and 45 business days; the note's own
    #: carry horizon is three months.  126 bd (~2 quarters) is a backstop, not
    #: a signal.
    max_hold_bd: int = 126

    # ---- execution and size ---------------------------------------------
    exec_lag_bd: int = 1
    #: Extra lag on the whole decision frame; the placebo ladder runs this at
    #: 10 / 20 / 40 / 60.
    signal_lag_bd: int = 0
    #: "We sell $200k DV01 of Blues convexity adjustments."
    ca_dv01: float = 200_000.0
    #: Short only: Citi sells rich convexity.
    side: int = -1

    # ---- construction ----------------------------------------------------
    hedge: str = "fitted_refit"
    selection: str = "screen_best"
    #: The SIGNAL runs on the raw constant-rank CA -- the object Citi's screen
    #: z-scores -- and the panel P&L on the roll-spliced one, which is the path
    #: a dated position actually walks.  See the module docstring; both are
    #: swept as declared sensitivities and neither is a free choice.
    splice_signal: bool = False
    splice_pnl: bool = True

    @property
    def target_usd(self) -> float:
        return self.target_bp * self.ca_dv01

    @property
    def stop_usd(self) -> float:
        return self.stop_bp * self.ca_dv01

    def universe(self) -> Tuple[str, ...]:
        if self.selection == "blues":
            return ("BLUES",)
        if self.selection == "screen_best_all5":
            return SECONDARY_UNIVERSE
        return PRIMARY_UNIVERSE


@dataclass
class CitiEpisode:
    structure: str
    entry_decision: pd.Timestamp
    entry_fill: pd.Timestamp
    exit_decision: pd.Timestamp
    exit_fill: pd.Timestamp
    side: int
    ca_dv01: float
    beta_entry: float
    w2_entry: float
    w10_entry: float
    exit_reason: str            # "target" | "stop" | "max_hold" | "end_of_sample"
    z_model: float = float("nan")
    z_fly: float = float("nan")
    rich_bp: float = float("nan")
    impl_rlzd: float = float("nan")
    z_pos: float = float("nan")
    n_restrikes: int = 0

    @property
    def hold_bd(self) -> int:
        return int(np.busday_count(self.entry_fill.date(), self.exit_fill.date()))


@dataclass
class StructureContext:
    """Everything one structure contributes to the decision, pre-aligned."""

    label: str
    ca_pnl: pd.Series          # the series P&L is marked on (spliced if declared)
    beta: pd.Series            # bp of CA per bp of the quoted combination
    w2: pd.Series
    w10: pd.Series
    combo: pd.Series           # the fitted-weight combination, bp
    dcombo_held: pd.Series     # change of the combination a HELD position sees
    fitted: pd.Series
    rich_bp: pd.Series
    z_fly: pd.Series
    z_model: pd.Series
    roll_3m: pd.Series
    impl_rlzd: pd.Series
    z_pos: pd.Series
    conds: pd.DataFrame        # one boolean column per declared condition
    all_ok: pd.Series
    rank_metric: pd.Series
    restrike_dates: pd.DatetimeIndex
    #: the three percent par-rate columns the fitted combination is built from,
    #: carried on the context so a frozen-weight combination can be rebuilt
    #: without a module-level cache keyed on object identity
    rates: Tuple[pd.Series, pd.Series, pd.Series] = field(
        default_factory=lambda: (pd.Series(dtype=float),) * 3)


# ---------------------------------------------------------------------------
# 1. Building the decision inputs
# ---------------------------------------------------------------------------
def _spliced(s: pd.Series, roll_dates: Sequence) -> pd.Series:
    from RVUtils.ConvexityRV.gv_sizing import roll_spliced
    return roll_spliced(s, roll_dates)


#: Memo for the quarterly refit.  The fair value depends only on the CA series,
#: the fit kind, the window and the regressors -- NOT on any threshold -- so the
#: 23 declared cells and the whole control battery re-derive the same handful of
#: paths dozens of times.  The key is a CONTENT fingerprint, not an object id:
#: an id is reused after garbage collection and would serve one structure's fit
#: under another's name.
_FV_MEMO: Dict[tuple, Tuple[pd.DataFrame, pd.Series]] = {}


def clear_fv_memo() -> None:
    """Drop the refit memo.  Only needed if a panel is mutated in place."""
    _FV_MEMO.clear()


def _fv_key(ca: pd.Series, panel: pd.DataFrame, kind: str, window_bd: int,
            cols: Sequence[str], rolls) -> tuple:
    idx = ca.index
    return (kind, int(window_bd), tuple(cols), len(idx),
            idx[0].value, idx[-1].value, len(rolls),
            float(np.nansum(ca.to_numpy())),
            float(np.nansum(ca.to_numpy() ** 2)),
            float(np.nansum(ca.to_numpy() * np.arange(len(idx)))),
            tuple(float(np.nansum(panel[c].to_numpy())) for c in cols),
            tuple(float(np.nansum(panel[c].to_numpy() ** 2)) for c in cols),
            tuple(float(np.nansum(panel[c].to_numpy() * np.arange(len(idx))))
                  for c in cols))


def _refit_memoised(ca: pd.Series, panel: pd.DataFrame, kind: str,
                    window_bd: int, cols: Sequence[str], rolls
                    ) -> Tuple[pd.DataFrame, pd.Series]:
    key = _fv_key(ca, panel, kind, window_bd, cols, rolls)
    hit = _FV_MEMO.get(key)
    if hit is None:
        hit = FV.imm_refit(ca, panel, kind, window_bd, cols,
                           roll_dates=list(rolls))
        _FV_MEMO[key] = hit
    frame, fitted = hit
    return frame.copy(), fitted.copy()


def _fit_kind_for(hedge: str) -> str:
    return "citi" if hedge == "citi_2017" else "fly"


def build_contexts(panel: pd.DataFrame, screen: Mapping[str, pd.DataFrame],
                   cfg: RuleConfig, *,
                   structures: Optional[Sequence[str]] = None,
                   fv_cols: Sequence[str] = FV.SPOT_COLS,
                   roll_col: str = "is_ca_roll",
                   pos_col: str = "dealer_net",
                   ) -> Dict[str, StructureContext]:
    """One :class:`StructureContext` per structure, all series causal.

    The fair value is refit at every CA roll on a trailing window ending
    strictly before the roll (:func:`citi_fv.imm_refit`), so the parameters in
    force on date ``t`` never saw ``t``.  ``dcombo_held`` is the change a
    position HELD INTO ``t`` experiences: on a re-strike date that is the change
    of the OLD combination, because the new weights only come into force after
    the old leg has been closed.
    """
    structures = [s.upper() for s in (structures or cfg.universe())]
    idx = panel.index
    rolls = pd.DatetimeIndex(idx[panel[roll_col].astype(bool)]) if roll_col in \
        panel.columns else pd.DatetimeIndex([])
    kind = _fit_kind_for(cfg.hedge)

    pos = panel[pos_col].astype(float) if pos_col in panel.columns else None
    z_pos = (SC.rolling_z(pos, cfg.z_window_bd) if pos is not None
             else pd.Series(np.nan, index=idx))

    out: Dict[str, StructureContext] = {}
    for lab in structures:
        ca_raw = panel[f"{lab.lower()}_ca_bp"].astype(float)
        ca_sig = _spliced(ca_raw, rolls) if cfg.splice_signal else ca_raw
        ca_pnl = _spliced(ca_raw, rolls) if cfg.splice_pnl else ca_raw

        frame, fitted = _refit_memoised(ca_sig, panel, kind,
                                        cfg.fit_window_bd, fv_cols, rolls)
        # the parameters in force on each date, forward-filled from the roll
        par = pd.DataFrame(index=idx, columns=["a", "b", "w2", "w10"],
                           dtype=float)
        for _, row in frame.iterrows():
            m = (idx >= row["in_force_from"]) & (idx <= row["in_force_to"])
            par.loc[m, "a"] = row["a"]
            par.loc[m, "b"] = row["b"]
            par.loc[m, "w2"] = row["w2"]
            par.loc[m, "w10"] = row["w10"]

        beta = (par["b"] / 100.0).rename("beta")
        if cfg.hedge == "unhedged":
            beta = pd.Series(0.0, index=idx, name="beta")

        # the combination at TODAY's weights, and the change a HELD position
        # sees (yesterday's weights on both marks)
        c0, c1, c2 = fv_cols
        r0, r1, r2 = (panel[c].astype(float) for c in (c0, c1, c2))
        combo = ((-par["w2"] * r0 + r1 - par["w10"] * r2) * 100.0).rename("combo_bp")
        w2p, w10p = par["w2"].shift(1), par["w10"].shift(1)
        held_now = (-w2p * r0 + r1 - w10p * r2) * 100.0
        held_prev = (-w2p * r0.shift(1) + r1.shift(1) - w10p * r2.shift(1)) * 100.0
        dcombo_held = (held_now - held_prev).rename("dcombo_held_bp")

        rich = (ca_sig - fitted).rename("rich_bp")
        z_fly = SC.rolling_z(rich, cfg.z_window_bd)
        # the model dislocation, spliced on the same clock as the CA -- the
        # Ho-Lee level jumps at the roll for the same reason the CA does
        vs_model_raw = screen["vs_model"][lab]
        vs_model = (_spliced(vs_model_raw, rolls) if cfg.splice_signal
                    else vs_model_raw)
        z_model = SC.rolling_z(vs_model, cfg.z_window_bd)
        roll3 = screen["roll_3m"][lab]
        ir = screen["impl_rlzd"][lab]

        raw = {
            "wide_to_model": z_model >= cfg.z_model_min,
            "wide_to_fly": z_fly >= cfg.z_fly_min,
            "positive_roll": (roll3 > 0.0) if cfg.require_positive_roll
            else pd.Series(True, index=idx),
            "implied_rich": ir >= cfg.impl_rlzd_min,
            "positioning_stretched": z_pos >= cfg.z_pos_min,
        }
        # A NaN input cannot CONFIRM a condition.  Every gate is evaluated on
        # the underlying being finite, so a missing mark refuses rather than
        # inheriting pandas' "NaN >= x is False" by accident -- same answer,
        # but the refusal is counted by cause in `condition_binding`.
        conds = pd.DataFrame({k: v.fillna(False).astype(bool)
                              for k, v in raw.items()}, index=idx)
        active = [c for c in cfg.conditions]
        all_ok = conds[active].all(axis=1) if active else pd.Series(True, index=idx)
        # never open on a date whose own hedge parameters do not exist
        # Every cell -- including the unhedged one -- may only open once the
        # fair value exists, so all fifteen share one tradeable window and their
        # Sharpes are graded against one span.
        all_ok &= np.isfinite(beta) & np.isfinite(rich) & np.isfinite(ca_sig)

        if cfg.signal_lag_bd:
            sh = int(cfg.signal_lag_bd)
            # ``fill_value`` rather than ``.fillna``: shifting a bool frame
            # upcasts to object first, and the downcast back is deprecated.
            conds = conds.shift(sh, fill_value=False).astype(bool)
            all_ok = all_ok.shift(sh, fill_value=False).astype(bool)
            z_model, z_fly = z_model.shift(sh), z_fly.shift(sh)

        out[lab] = StructureContext(
            label=lab, ca_pnl=ca_pnl, beta=beta, w2=par["w2"], w10=par["w10"],
            combo=combo, dcombo_held=dcombo_held, fitted=fitted, rich_bp=rich,
            z_fly=z_fly, z_model=z_model, roll_3m=roll3, impl_rlzd=ir,
            z_pos=z_pos, conds=conds, all_ok=all_ok,
            rank_metric=z_model.rename("rank_metric"),
            restrike_dates=pd.DatetimeIndex(frame["in_force_from"])
            if not frame.empty else pd.DatetimeIndex([]),
            rates=(r0, r1, r2))
    return out


def condition_binding(ctx: Mapping[str, StructureContext], cfg: RuleConfig
                      ) -> pd.DataFrame:
    """How often each condition refuses, per structure.

    With a five-way conjunction the interesting number is not "how many days
    pass" but "which condition is the binding one", and that has to be reported
    or the rule's failure mode is invisible.
    """
    rows = []
    for lab, c in ctx.items():
        n = len(c.conds)
        row = {"structure": lab, "n_dates": n}
        for k in CONDITIONS:
            row[f"pass_{k}"] = float(c.conds[k].mean()) if k in c.conds else np.nan
        active = [k for k in cfg.conditions if k in c.conds]
        row["pass_all"] = float(c.conds[active].all(axis=1).mean()) if active else 1.0
        # the marginal cost of each condition: what fraction of days that pass
        # everything ELSE are refused by this one alone
        for k in active:
            others = [o for o in active if o != k]
            base = c.conds[others].all(axis=1) if others else pd.Series(
                True, index=c.conds.index)
            row[f"binds_alone_{k}"] = float((base & ~c.conds[k]).mean())
        rows.append(row)
    return pd.DataFrame(rows).set_index("structure")


# ---------------------------------------------------------------------------
# 2. The state machine
# ---------------------------------------------------------------------------
def _fill(idx: pd.DatetimeIndex, t: pd.Timestamp, lag: int
          ) -> Optional[pd.Timestamp]:
    i = int(idx.get_loc(t)) + int(lag)
    return idx[i] if 0 <= i < len(idx) else None


def _unit_pnl(ctx: StructureContext, cfg: RuleConfig, beta_series: pd.Series,
              dcombo: pd.Series) -> pd.Series:
    """Daily USD P&L per open position: ``side*(dCA - beta*dcombo)*ca_dv01``."""
    d = ctx.ca_pnl.diff()
    if cfg.hedge == "unhedged":
        return (cfg.side * d * cfg.ca_dv01).astype(float)
    return (cfg.side * (d - beta_series * dcombo) * cfg.ca_dv01).astype(float)


def episode_daily_pnl(ep: CitiEpisode, ctx: StructureContext, cfg: RuleConfig
                      ) -> pd.Series:
    """Daily USD P&L of one episode, accrued on ``(entry_fill, exit_fill]``."""
    idx = ctx.ca_pnl.index
    if ep.exit_fill <= ep.entry_fill:
        return pd.Series(dtype=float)
    if cfg.hedge == "fitted_frozen":
        # weights frozen at entry: rebuild the combination at those weights
        # from the same rates the refit path uses
        beta = pd.Series(ep.beta_entry, index=idx)
        frozen = _frozen_combo(ctx, ep)
        dcombo = frozen.diff()
    else:
        beta = ctx.beta.shift(1)
        dcombo = ctx.dcombo_held
    p = _unit_pnl(ctx, cfg, beta, dcombo)
    seg = p.loc[ep.entry_fill:ep.exit_fill]
    return seg.iloc[1:].astype(float)


def _frozen_combo(ctx: StructureContext, ep: CitiEpisode) -> pd.Series:
    """The fitted combination at the weights frozen AT ENTRY, in bp."""
    r0, r1, r2 = ctx.rates
    if len(r0) == 0:
        raise RuntimeError(
            "this context carries no rate columns, so a frozen-weight "
            "combination cannot be rebuilt; build it with build_contexts()")
    return (-float(ep.w2_entry) * r0 + r1 - float(ep.w10_entry) * r2) * 100.0


def episodes_from_contexts(ctx: Mapping[str, StructureContext], cfg: RuleConfig,
                           *, panel: pd.DataFrame,
                           fv_cols: Sequence[str] = FV.SPOT_COLS,
                           ) -> List[CitiEpisode]:
    """The rule, run forward one date at a time, one position at a time.

    Citi ran one convexity trade idea at a time -- the Blues ticket closed on
    6-Jun-2017 and the Greens ticket opened the same day -- so the book holds at
    most one position and the screen decides which structure gets it.
    """
    labs = [l for l in cfg.universe() if l in ctx]
    if not labs:
        return []
    idx = ctx[labs[0]].ca_pnl.index
    _ = (panel, fv_cols)     # the rate columns travel on the contexts themselves

    # per-structure daily unit P&L, so the target/stop can be evaluated without
    # re-deriving it inside the loop
    unit: Dict[str, pd.Series] = {}
    for lab in labs:
        c = ctx[lab]
        unit[lab] = _unit_pnl(c, cfg, c.beta.shift(1), c.dcombo_held)

    out: List[CitiEpisode] = []
    open_ep: Optional[CitiEpisode] = None
    cum = 0.0
    frozen_unit: Optional[pd.Series] = None
    entry_i = -1
    for i, t in enumerate(idx):
        if open_ep is None:
            cands = [l for l in labs if bool(ctx[l].all_ok.get(t, False))]
            if not cands:
                continue
            best = max(cands, key=lambda l: float(ctx[l].rank_metric.get(t, -np.inf)))
            fill = _fill(idx, t, cfg.exec_lag_bd)
            if fill is None:
                continue
            c = ctx[best]
            open_ep = CitiEpisode(
                structure=best, entry_decision=t, entry_fill=fill,
                exit_decision=t, exit_fill=fill, side=cfg.side,
                ca_dv01=cfg.ca_dv01, beta_entry=float(c.beta.get(t, np.nan)),
                w2_entry=float(c.w2.get(t, np.nan)),
                w10_entry=float(c.w10.get(t, np.nan)),
                exit_reason="", z_model=float(c.z_model.get(t, np.nan)),
                z_fly=float(c.z_fly.get(t, np.nan)),
                rich_bp=float(c.rich_bp.get(t, np.nan)),
                impl_rlzd=float(c.impl_rlzd.get(t, np.nan)),
                z_pos=float(c.z_pos.get(t, np.nan)))
            cum = 0.0
            entry_i = int(idx.get_loc(fill))
            frozen_unit = None
            if cfg.hedge == "fitted_frozen":
                fc = _frozen_combo(c, open_ep)
                frozen_unit = _unit_pnl(
                    c, cfg, pd.Series(open_ep.beta_entry, index=idx), fc.diff())
            continue

        if i <= entry_i:
            continue
        u = (frozen_unit if frozen_unit is not None else unit[open_ep.structure])
        step = float(u.get(t, 0.0))
        cum += 0.0 if not np.isfinite(step) else step
        held = i - entry_i
        reason = ""
        if cum >= cfg.target_usd:
            reason = "target"
        elif cum <= cfg.stop_usd:
            reason = "stop"
        elif held >= cfg.max_hold_bd:
            reason = "max_hold"
        elif i == len(idx) - 1:
            reason = "end_of_sample"
        if reason:
            fill = _fill(idx, t, cfg.exec_lag_bd) or idx[-1]
            open_ep.exit_decision = t
            open_ep.exit_fill = fill
            open_ep.exit_reason = reason
            rs = ctx[open_ep.structure].restrike_dates
            open_ep.n_restrikes = (
                0 if cfg.hedge in ("fitted_frozen", "unhedged")
                else int(((rs > open_ep.entry_fill) & (rs <= fill)).sum()))
            out.append(open_ep)
            open_ep = None
            frozen_unit = None
    return out


# ---------------------------------------------------------------------------
# 3. Costs and the book
# ---------------------------------------------------------------------------
def episode_cost_usd(ep: CitiEpisode, cfg: RuleConfig, *, mult: float = 1.0
                     ) -> float:
    """Round-trip cost of one episode, per leg, on that leg's own DV01.

    The futures package pays ONE tick regardless of leg count; the matched swap
    pays its own; the fly pays ``0.5 bp`` on each of its three legs, whose DV01s
    are ``(w2, 1, w10) * |beta| * CA_DV01``.  A re-strike is a further round
    trip of the fly and only the fly, so it is charged separately -- this is the
    term that grows when the hedge is maintained rather than frozen, and
    hiding it would flatter exactly the scheme the note recommends.
    """
    if mult == 0.0:
        return 0.0
    ca = float(ep.ca_dv01)
    total = (FUT_RT_BP + SWAP_RT_BP) * ca
    if cfg.hedge != "unhedged" and np.isfinite(ep.beta_entry) and ep.beta_entry:
        belly = abs(ep.beta_entry) * ca
        legs = belly * (1.0 + float(ep.w2_entry) + float(ep.w10_entry))
        total += LEG_RT_BP * legs * (1 + int(ep.n_restrikes))
    return float(mult * total)


def book_daily(eps: Sequence[CitiEpisode], ctx: Mapping[str, StructureContext],
               cfg: RuleConfig, *, index: pd.DatetimeIndex,
               cost_mult: float = 0.0) -> pd.Series:
    """Daily USD P&L of a whole cell (not cumulative); cost charged at exit."""
    daily = pd.Series(0.0, index=index)
    for ep in eps:
        p = episode_daily_pnl(ep, ctx[ep.structure], cfg)
        daily = daily.add(p.reindex(index).fillna(0.0), fill_value=0.0)
        c = episode_cost_usd(ep, cfg, mult=cost_mult)
        if c:
            daily.loc[ep.exit_fill] = daily.get(ep.exit_fill, 0.0) - c
    return daily


# ---------------------------------------------------------------------------
# 4. The declared cell list
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CellSpec:
    cell_id: str
    tier: str                  # "primary" | "secondary" | "diagnostic"
    hedge: str
    selection: str
    z_min: float = 2.0
    conditions: Tuple[str, ...] = CONDITIONS
    headline: bool = False
    note: str = ""

    def config(self, base: RuleConfig = RuleConfig()) -> RuleConfig:
        return RuleConfig(
            z_model_min=self.z_min, z_fly_min=self.z_min,
            require_positive_roll=base.require_positive_roll,
            impl_rlzd_min=base.impl_rlzd_min, z_pos_min=base.z_pos_min,
            conditions=self.conditions, z_window_bd=base.z_window_bd,
            fit_window_bd=base.fit_window_bd, target_bp=base.target_bp,
            stop_bp=base.stop_bp, max_hold_bd=base.max_hold_bd,
            exec_lag_bd=base.exec_lag_bd, signal_lag_bd=base.signal_lag_bd,
            ca_dv01=base.ca_dv01, side=base.side, hedge=self.hedge,
            selection=self.selection, splice_signal=base.splice_signal,
            splice_pnl=base.splice_pnl)


#: The z level the non-faithful tiers run at -- the one measured to give the
#: rule enough entry-eligible days to be scoreable at all.
LADDER_Z = 1.0


def declared_cells() -> List[CellSpec]:
    """Exactly the pre-registered list, in a deterministic order.

    **16 primary** = 2 threshold readings x 4 hedge schemes x 2 selection rules.
    The headline is the faithful rule: the note's own two-sigma reading, the
    screen-selected structure, the fly-constrained fit re-struck at each roll,
    the five-way conjunction, the dollar target and stop, short only.

    **2 secondary**: the same rule with WHITES and REDS back in the selection
    universe, at the two hedge schemes worth the comparison.  Their marks are
    the least trustworthy on the board (AC1 of the daily change -0.540 /
    -0.517, at or past the pure-noise bound) and every number they produce
    carries that caveat.

    **5 diagnostics**: the rule with one condition of the conjunction dropped,
    so "which condition is load-bearing" is answered by a scored cell rather
    than by inspection.  They are declared here, and counted, because a
    drop-one variant that beat the headline would otherwise be a trial nobody
    paid for.
    """
    cells: List[CellSpec] = []
    for z in Z_LEVELS:
        for sel in ("screen_best", "blues"):
            for h in HEDGE_SCHEMES:
                head = (z == 2.0 and sel == "screen_best"
                        and h == "fitted_refit")
                cells.append(CellSpec(
                    f"P|z{z:.1f}|{sel}|{h}", "primary", h, sel, z, CONDITIONS,
                    head, "the note's own trade, at its own thresholds"
                    if head else ""))
    for h in ("fitted_refit", "citi_2017"):
        cells.append(CellSpec(
            f"S|z{LADDER_Z:.1f}|screen_best_all5|{h}", "secondary", h,
            "screen_best_all5", LADDER_Z, CONDITIONS, False,
            "does the noise-dominated front of the strip adversely select "
            "into the screen"))
    for drop in CONDITIONS:
        rest = tuple(c for c in CONDITIONS if c != drop)
        cells.append(CellSpec(
            f"D|z{LADDER_Z:.1f}|drop_{drop}", "diagnostic", "fitted_refit",
            "screen_best", LADDER_Z, rest, False,
            f"the rule without {drop}"))
    ids = [c.cell_id for c in cells]
    assert len(set(ids)) == len(ids), "duplicate cell id"
    return cells


@dataclass
class CellResult:
    spec: CellSpec
    cfg: RuleConfig
    episodes: List[CitiEpisode]
    daily_by_mult: Dict[float, pd.Series]
    per_episode_usd: List[float]
    carry_usd: float = 0.0
    n_dates: int = 0
    binding: Optional[pd.DataFrame] = None

    @property
    def n_episodes(self) -> int:
        return len(self.episodes)


def run_cell(spec: CellSpec, panel: pd.DataFrame,
             screen: Mapping[str, pd.DataFrame], *,
             base: RuleConfig = RuleConfig(),
             cost_mults: Sequence[float] = COST_MULTS,
             theta_bp_per_bd: Optional[Mapping[str, pd.Series]] = None,
             ) -> CellResult:
    """One declared cell, end to end, on precomputed panels."""
    cfg = spec.config(base)
    ctx = build_contexts(panel, screen, cfg)
    eps = episodes_from_contexts(ctx, cfg, panel=panel)
    idx = panel.index
    daily = {m: book_daily(eps, ctx, cfg, index=idx, cost_mult=m)
             for m in cost_mults}
    per_ep, carry = [], 0.0
    for e in eps:
        p = episode_daily_pnl(e, ctx[e.structure], cfg)
        per_ep.append(float(p.sum()))
        if theta_bp_per_bd is not None and e.structure in theta_bp_per_bd:
            th = theta_bp_per_bd[e.structure].reindex(p.index)
            carry += float(cfg.side) * float(th.sum()) * float(e.ca_dv01)
    return CellResult(spec, cfg, eps, daily, per_ep, carry, len(idx),
                      condition_binding(ctx, cfg))


# ---------------------------------------------------------------------------
# 5. Statistics
# ---------------------------------------------------------------------------
ANN = 252.0


def _sharpe(daily: pd.Series) -> float:
    d = pd.Series(daily).astype(float)
    if len(d[d != 0.0]) < 5 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(ANN))


def stats_frame(results: Sequence[CellResult], *, span_years: float
                ) -> pd.DataFrame:
    rows = []
    for r in results:
        s, cfg = r.spec, r.cfg
        holds = [e.hold_bd for e in r.episodes]
        mean_hold = float(np.mean(holds)) if holds else float("nan")
        n_eff_hold = ((span_years * ANN / mean_hold)
                      if mean_hold and mean_hold > 0 else float("nan"))
        # the SMALLER clock is the honest count: a book with 9 episodes over
        # 5 years has made 9 bets, not 48
        n_eff = (float(min(n_eff_hold, len(r.episodes)))
                 if r.episodes and np.isfinite(n_eff_hold) else float("nan"))
        pe = np.asarray(r.per_episode_usd, dtype=float)
        gross = 0.0
        for e in r.episodes:
            gross += 2.0 * e.ca_dv01
            if cfg.hedge != "unhedged" and np.isfinite(e.beta_entry):
                gross += (abs(e.beta_entry) * e.ca_dv01
                          * (1.0 + e.w2_entry + e.w10_entry)
                          * (1 + e.n_restrikes))
        row = {
            "cell_id": s.cell_id, "tier": s.tier, "headline": s.headline,
            "hedge": s.hedge, "selection": s.selection,
            "n_conditions": len(s.conditions),
            "n_episodes": r.n_episodes, "mean_hold_bd": mean_hold,
            "n_eff": n_eff, "n_eff_hold_clock": n_eff_hold,
            "hit_rate": float((pe > 0).mean()) if len(pe) else float("nan"),
            "mean_abs_beta": float(np.mean([abs(e.beta_entry)
                                            for e in r.episodes]))
            if r.episodes else float("nan"),
            "n_restrikes": int(sum(e.n_restrikes for e in r.episodes)),
            "gross_dv01_traded": gross,
            "carry_usd": r.carry_usd,
        }
        for reason in ("target", "stop", "max_hold", "end_of_sample"):
            row[f"exit_{reason}"] = sum(1 for e in r.episodes
                                        if e.exit_reason == reason)
        for m in sorted(r.daily_by_mult):
            d = r.daily_by_mult[m]
            row[f"net_{m}"] = float(d.sum())
            row[f"sharpe_{m}"] = _sharpe(d)
        g = row.get("net_0.0", np.nan)
        row["breakeven_bp"] = (g / gross) if gross else np.nan
        row["residual_usd"] = g - r.carry_usd
        row["carry_share"] = (r.carry_usd / g) if g else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def null_bars(n_trials: int, *, n_eff: float, span_years: float
              ) -> Dict[str, float]:
    """``E[max SR | null]`` on both clocks -- the house discipline, verbatim.

    A per-hold Sharpe has null SE ``1/sqrt(n_eff)``; an ANNUALISED Sharpe has
    ``1/sqrt(span_years)``.  ``span_years`` is the TRADEABLE span, not the panel
    span: a book that cannot open until its fair value and its z-scores exist
    has not been running for the whole panel.
    """
    from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe
    return {
        "emax_perhold": expected_max_sharpe(n_trials, 1.0 / max(n_eff, 1e-9)),
        "emax_annualised": expected_max_sharpe(n_trials,
                                               1.0 / max(span_years, 1e-9)),
    }
