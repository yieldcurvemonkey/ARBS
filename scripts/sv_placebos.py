"""Placebos and confound checks.

Every defect found post-hoc in this repo's research so far has flattered the
hypothesis. So the placebos run BEFORE the winner is believed, not after it is
questioned.

Four legs, and each one is written so that it can come back with the answer
nobody wants:

1. **Short-dated placebo** -- the identical rulebook on
   ``universe.PLACEBO_PAIRS``, where the convexity story should not hold. A
   surviving signal there is a calendar or curve-shape artifact.
2. **Shuffled-vol placebo** -- :func:`block_bootstrap` on the valuation
   column, re-run. The valuation switch must degrade. The bootstrap is
   BLOCKED, not shuffled, and :func:`persistence_check` refuses the run if the
   resample destroyed the series' persistence anyway: a null that is easier
   than the real thing produces a comforting result rather than an
   informative one.
3. **Sign mirror** -- and this is the leg with a rule attached, because
   ``replication.simulate`` is **exactly antisymmetric in sign**. Per-unit
   DV01 is sign-invariant, notionals flip, PV and theta are linear in
   notionals, the trigger reads a sign-independent constant-maturity rate, and
   the cost is a magnitude fee -- so ``P&L_short = -P&L_long_gross + cost``
   identically, for the static book AND for a conditional one. "Both
   directions work" is therefore refuted by arithmetic before any data is
   involved, and a mirror run on a static book is not evidence of anything.
   :func:`run_placebos` refuses to run the mirror unless the signal takes BOTH
   directions at some point -- the Task 17 conditional rule -- and stamps
   ``mirror_is_arithmetic`` on every mirror row it does produce. What the
   mirror can still show is BOTH SIDES LOSING -- the pair
   sitting inside the cost band -- which is a statement about costs, not about
   convexity. Read it as that.
4. **Confound alternatives** for whatever config wins: duration-only
   (:class:`DurationOnlyPricer` -- the long leg outright, DV01-matched to the
   package), PC1-only (the slope's projection on the first principal component
   of the curve) and pure-carry (:func:`carry_sign_signals` -- hold whichever
   sign has positive roll, with no vol input at all). If the winner does not
   beat all three, the vol story is not what is paying.

**The comparison key is named up front and it is not Sharpe**
(:data:`CONFOUND_METRIC`). Both of Task 13's placebo pairs out-Sharpe every
real pair while running the opposite carry sign; ``report.league_table``
refuses a Sharpe ranking key outright and so does this module.

**Confound rows are comparators, never candidates.** They are built from
prebuilt signal frames that carry none of ``causal_signals``' provenance, so
their requirement flags are all False and ``league_table`` would downgrade
them to INELIGIBLE. That is correct: the question they answer is "does
something with no vol content pay as well", not "is this tradeable".
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.backtest import run_grid
from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.replication import ReplicationConfig, simulate
from RVUtils.StrikelessVol.strategy import (
    REQUIRED_COLUMNS,
    SignalConfig,
    build_signals,
)
from RVUtils.StrikelessVol.universe import PLACEBO_PAIRS
from RVUtils.pca_rv import make_pca_rv_builder

__all__ = [
    "CONFOUND_METRIC",
    "PLACEBO_FAMILIES",
    "PLACEBO_PAIR_NAMES",
    "MIRROR_REL_TOL",
    "DurationOnlyPricer",
    "block_bootstrap",
    "carry_sign_signals",
    "mirror_configs",
    "pc1_projection",
    "persistence_check",
    "run_confounds",
    "run_placebos",
    "z_rule_signals",
]

#: The families :func:`run_placebos` can emit, in report order.
PLACEBO_FAMILIES = ("real", "short_dated", "shuffled_vol", "sign_mirror")

#: The short-dated slopes requirement 1 nominates, read from the universe
#: rather than restated here: ``USD 1Y5Y/2Y5Y`` and ``USD 2Y2Y/3Y2Y``. The leg
#: is the identical rulebook run WHERE THE CONVEXITY STORY SHOULD NOT HOLD, so
#: which pairs it runs on is the whole content of it -- run against an
#: arbitrary second pair it is a second real run wearing a placebo label.
#: :func:`run_placebos` refuses anything outside this list unless the caller
#: says ``expect_placebo_pairs=False``.
PLACEBO_PAIR_NAMES: tuple = tuple(p.name for p in PLACEBO_PAIRS)

#: What :func:`run_confounds` ranks on. Stated here, before the run, because
#: the point of a confound table is that the winner was not chosen after
#: looking at it. Net of costs and divided by the REALISED DV01 of the book on
#: the days it was held, then by the number of distinct episodes -- i.e. the
#: study's per-trade unit. **Not Sharpe**, which a zero-convexity twin and both
#: short-dated placebo pairs already beat the real package on.
CONFOUND_METRIC = "net_bp_per_trade"

#: How far ``gross_real + gross_mirror`` may sit from zero and still be called
#: arithmetic. ``simulate`` is antisymmetric to float noise, so this is float
#: noise -- named rather than inlined because the boolean it produces is what
#: the module docstring tells a reader to consult first, and a tolerance nobody
#: can see is a tolerance nobody can test. Measured: loosening it to 1e9 made
#: ``mirror_is_arithmetic`` unfalsifiable and the whole suite still passed.
MIRROR_REL_TOL: float = 1e-9

#: Below this lag-1 autocorrelation there is no persistence to preserve, so
#: :func:`persistence_check` has nothing to verify and says so rather than
#: dividing by a number near zero.
PERSISTENCE_FLOOR: float = 0.2

#: Columns whose presence means a signal frame was already BUILT (as opposed to
#: a raw panel that a config can still sweep). Mirrors ``backtest``'s own set.
_SIGNAL_OUTPUT_COLS = {"sign", "size", "dv01_usd"}

_GROSS_COLS = ("carry_usd", "harvest_usd", "mtm_usd", "cross_usd")

#: The ``SignalConfig`` axes a grid can sweep -- mirrors ``backtest``'s own set.
_SIGNAL_FIELDS = set(SignalConfig.__dataclass_fields__)


# --------------------------------------------------------------- the resample


def block_bootstrap(series: pd.Series, *, block: int = 21, seed: int = 0,
                    min_ratio: float = 0.5) -> pd.Series:
    """Resample in blocks, preserving short-run autocorrelation.

    A plain shuffle destroys the persistence of a vol series and makes the
    placebo trivially easy to beat, which would be a comforting result rather
    than an informative one. Measured on an AR(1) with rho = 0.966: a plain
    permutation takes lag-1 autocorrelation to **-0.009** and inflates the
    increment volatility **5.5x**, while this at ``block=63`` leaves it at
    0.960.

    **What it preserves and what it does not, measured rather than asserted.**
    The moving-block bootstrap is defined for a STATIONARY series. It preserves
    the marginal level distribution (measured level-std ratios 0.98-1.09 across
    rho in 0.90-0.99 and blocks 5-63) and the autocorrelation up to the block
    length. It does NOT preserve increment volatility, because joining
    ``n / block`` independent blocks end to end introduces that many jumps:

    ========  =========  =========  =========  =========
    rho       block 5    block 21   block 63   ac1 out (block 21)
    ========  =========  =========  =========  =========
    0.90          1.66       1.18       1.07   0.864
    0.95          2.16       1.35       1.13   0.905
    0.97          2.66       1.56       1.18   0.920
    0.99          4.26       2.24       1.33   0.936
    ========  =========  =========  =========  =========

    (ratio of resampled to observed ``diff().std()``; 1000 rows.)

    **Do not hand this a non-stationary series.** On a random walk of 1000 rows
    at ``block=21`` the increment-volatility ratio is **4.12**, because the
    boundary jumps are differences of two unrelated LEVELS of a walk rather
    than of two draws from one distribution. That is the input this function's
    first specification was tested on, and the test asserted the ratio was
    within 25% of one. Bootstrap the vol/valuation series, which is stationary;
    if you need a null for an integrated series, resample its increments.

    Three refusals, all fail-closed:

    * ``block < 2`` is a plain shuffle wearing this function's name.
    * ``block >= len(series)`` returned the input UNCHANGED in the first
      specification -- a placebo identical to the real series, certifying by
      construction.
    * a series shorter than 2 rows has nothing to resample.

    And one silent bias fixed: starts are drawn from ``[0, n - block]``
    INCLUSIVE. Drawing from ``[0, n - block)`` (the first specification) means
    the final observation can never appear -- measured, 199 of 200 distinct
    values seen over 400 seeds, with ``values[-1]`` absent from every one.

    The measured properties are stamped on ``out.attrs`` so a caller can read
    what this particular resample did rather than what the class of resamples
    usually does.
    """
    s = pd.Series(series).astype(float)
    n = len(s)
    block = int(block)
    if n < 2:
        raise ValueError(f"nothing to resample: series has {n} row(s)")
    if block < 2:
        raise ValueError(
            f"block={block} is a plain shuffle, not a block bootstrap. A "
            "shuffle destroys the persistence of a vol series and makes the "
            "placebo trivially easy to beat -- a comforting result, not an "
            "informative one."
        )
    if block >= n:
        raise ValueError(
            f"block={block} needs a series longer than {block} rows, got {n}. "
            "A block at or beyond the sample length returns the input "
            "unchanged, i.e. a placebo identical to the real series."
        )
    rng = np.random.default_rng(seed)
    values = s.to_numpy()
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    out = np.concatenate([values[st:st + block] for st in starts])[:n]
    resampled = pd.Series(out, index=s.index, name=s.name)
    # `min_ratio` is threaded through rather than defaulted so the stamp on the
    # series and the verdict that gated the run cannot disagree: a caller
    # reading `out.attrs["persistence_preserved"]` was previously answering a
    # different question from the one `run_placebos` asked.
    resampled.attrs.update(persistence_check(s, resampled, min_ratio=min_ratio))
    resampled.attrs.update({"block": block, "seed": int(seed),
                            "n_blocks": n_blocks})
    return resampled


def persistence_check(
    original: pd.Series,
    resampled: pd.Series,
    *,
    min_ratio: float = 0.5,
    floor: float = PERSISTENCE_FLOOR,
) -> dict:
    """Did the resample keep the persistence its docstring claims to keep?

    The trap this exists for: a null that is EASIER than the real thing. If the
    resample flattened the vol series into noise, the valuation switch degrades
    because there is nothing left to switch on -- which says nothing about
    whether the switch was ever reading vol. So the shuffled-vol leg measures
    the null it built and refuses to report a degradation it manufactured.

    ``preserved`` is ``True`` when the original was not persistent to begin
    with (nothing to destroy, ``ac1_in < floor``) or when the resample kept at
    least ``min_ratio`` of its lag-1 autocorrelation. A plain permutation of a
    rho=0.97 series scores ``ratio ~ -0.01`` and is refused.
    """
    a = pd.Series(original).astype(float)
    b = pd.Series(resampled).astype(float)
    ac_in = float(a.autocorr(1)) if len(a) > 2 else float("nan")
    ac_out = float(b.autocorr(1)) if len(b) > 2 else float("nan")
    sd_in, sd_out = float(a.std(ddof=1)), float(b.std(ddof=1))
    d_in, d_out = float(a.diff().std(ddof=1)), float(b.diff().std(ddof=1))
    trivial = not np.isfinite(ac_in) or ac_in < float(floor)
    ratio = (ac_out / ac_in) if (np.isfinite(ac_in) and ac_in != 0.0) else float("nan")
    preserved = bool(trivial or (np.isfinite(ratio) and ratio >= float(min_ratio)))
    return {
        "autocorr1_in": ac_in,
        "autocorr1_out": ac_out,
        "autocorr1_ratio": ratio,
        "level_std_ratio": (sd_out / sd_in) if sd_in else float("nan"),
        "diff_std_ratio": (d_out / d_in) if d_in else float("nan"),
        "persistence_preserved": preserved,
        "persistence_trivial": bool(trivial),
        "min_ratio": float(min_ratio),
    }


def mirror_configs(grid: Iterable[dict]) -> List[dict]:
    """Every config with its sign reversed. Both sides must not 'work'.

    A config that names no ``sign`` gets ``sign = -1``, which mirrors
    ``ReplicationConfig``'s default of ``FLATTENER = +1``.
    """
    return [{**c, "sign": -int(c.get("sign", 1))} for c in grid]


# ------------------------------------------------------------ the alternatives


class DurationOnlyPricer:
    """The long leg outright, DV01-matched to the package. Confound (a).

    Wraps another pricing context and prices the SHORT leg at zero, leaving
    everything else -- the rate path, the per-leg DV01s, the hedge trigger, the
    roll -- exactly as the real book sees it. So the notional bookkeeping,
    including ``simulate``'s "resize the long leg back to DV01 neutral against
    the short leg as held", is unchanged; only the short leg's contribution to
    PV and theta is removed.

    That is deliberately the crudest possible confound: a book with the same
    DV01, the same trading dates and the same costs, whose P&L is pure
    duration. The real package's entire premise is that it has no directional
    exposure; if this pays as well, the premise is what is wrong.
    """

    def __init__(self, inner):
        self.inner = inner

    def rate(self, date, leg):
        return self.inner.rate(date, leg)

    def dv01(self, date, leg):
        return self.inner.dv01(date, leg)

    def theta(self, date, n_long, n_short):
        return self.inner.theta(date, n_long, 0.0)

    def pv(self, date, n_long, n_short):
        return self.inner.pv(date, n_long, 0.0)


def pc1_projection(
    rates: pd.DataFrame, spread_bp: pd.Series, *, n_factors: int = 3
) -> pd.Series:
    """The slope's projection on the curve's first principal component.

    ``rates`` is a wide curve panel (dates x points); ``spread_bp`` is the
    pair's slope. Returns the fitted values of ``spread ~ a + b * PC1``, i.e.
    the part of the slope that PC1 already explains.

    **This confound is given look-ahead the real rule is denied**, and that is
    on purpose. ``pca_rv.make_pca_rv_builder`` fits on the whole sample, so
    PC1's loadings know the future. A winner that beats a full-sample PC1
    projection has beaten a confound with an advantage; a PC1 projection that
    beats the winner has NOT thereby shown a tradeable PC1 signal, because no
    causal version of it was run. Read the two directions asymmetrically -- the
    stamp ``look_ahead`` on the returned series says so on the object itself.
    """
    df = pd.DataFrame(rates).astype(float).sort_index()
    y = pd.Series(spread_bp).astype(float)
    builder = make_pca_rv_builder(df, on="levels", n_factors=int(n_factors))
    fit = builder[0]
    get_model = builder[-1]
    fit()
    _model, scores = get_model()
    pc1 = pd.Series(scores["PC1"], index=scores.index).astype(float)
    both = pd.concat([y.rename("y"), pc1.rename("x")], axis=1).dropna()
    if len(both) < 3:
        raise ValueError(
            f"only {len(both)} overlapping dates between the spread and the "
            "curve panel -- a PC1 projection needs the two to be aligned"
        )
    slope, intercept = np.polyfit(both["x"].to_numpy(), both["y"].to_numpy(), 1)
    out = pd.Series(intercept + slope * pc1.reindex(y.index), index=y.index,
                    name="pc1_projection")
    out.attrs.update({"look_ahead": "full_sample_pca", "slope": float(slope),
                      "intercept": float(intercept), "n_fit": int(len(both))})
    return out


def z_rule_signals(
    z: pd.Series,
    panel: pd.DataFrame,
    cfg: Optional[SignalConfig] = None,
) -> pd.DataFrame:
    """The study's entry and sizing rule driven by an arbitrary z. Confound (b).

    Same entry threshold, same risk-parity sizing off ``spread_vol_bp_day``,
    same lag-1 discipline as ``strategy.build_signals`` -- so a comparison
    against the real rule isolates WHAT the z is, and not how big the book is
    or when it is allowed to trade. Cheap (``z <= -z_entry``) is the flattener,
    rich is the steepener, matching ``signal_state``'s mapping.

    No valuation switch and no gates: this confound has no vol input, which is
    the whole point of it.
    """
    cfg = cfg or SignalConfig()
    zz = pd.Series(z).astype(float).reindex(panel.index).shift(1)
    sv = pd.Series(panel["spread_vol_bp_day"]).astype(float).reindex(
        panel.index).shift(1)
    rows = []
    for ts in panel.index:
        v, s = float(zz.get(ts, np.nan)), float(sv.get(ts, np.nan))
        if not np.isfinite(v) or abs(v) < cfg.z_entry:
            rows.append({"sign": 0, "size": 0.0, "reason": "flat"})
            continue
        sign = FLATTENER if v <= -cfg.z_entry else STEEPENER
        vol_scale = cfg.target_vol_bp_day / s if np.isfinite(s) and s > 0 else 0.0
        z_scale = min(abs(v), cfg.z_size_cap) / cfg.z_size_cap
        rows.append({"sign": sign,
                     "size": float(min(cfg.size_cap, vol_scale * z_scale)),
                     "reason": f"z={v:+.2f}"})
    out = pd.DataFrame(rows, index=panel.index)
    out["dv01_usd"] = out["sign"] * out["size"] * cfg.base_dv01_usd
    return out


def carry_sign_signals(
    ctx,
    dates: Sequence,
    *,
    rep_cfg: Optional[ReplicationConfig] = None,
    costs: CostSchedule,
    size=1.0,
    base_dv01_usd: float = 100_000.0,
) -> pd.DataFrame:
    """Hold whichever sign has positive roll. Confound (c).

    The carry of the unit package is read from ``simulate`` at
    ``sign = FLATTENER``, lagged one day, and its sign becomes the position.
    Nothing about vol enters. This is the cheapest possible "the carry is what
    is paying" alternative, and the study has already measured that both
    short-dated placebo pairs out-Sharpe every real pair **while running the
    opposite carry sign**, so it is not a straw man.

    ``size`` is a flat 1.0 by default, which is **not** matched to the winner's
    risk-parity sizing. :data:`CONFOUND_METRIC` divides by the realised DV01 of
    the book on the days it was held, so the comparison survives that -- but
    the two books are not the same size, and a caller who wants them to be can
    pass the winner's own ``size`` column as a Series.
    """
    rep = replace(rep_cfg or ReplicationConfig(), sign=FLATTENER)
    unit = simulate(ctx, list(dates), rep, costs)
    carry = unit["carry"].astype(float).shift(1)
    sign = np.sign(carry).fillna(0.0).astype(int)
    if isinstance(size, pd.Series):
        sz = size.astype(float).reindex(unit.index).fillna(0.0).to_numpy()
    else:
        sz = np.full(len(unit.index), float(size))
    out = pd.DataFrame({"sign": sign,
                        "size": np.where(sign != 0, sz, 0.0),
                        "reason": "carry sign"},
                       index=unit.index)
    out["dv01_usd"] = out["sign"] * out["size"] * float(base_dv01_usd)
    return out


# -------------------------------------------------------------------- the runs


def _is_prebuilt(source: pd.DataFrame) -> bool:
    return _SIGNAL_OUTPUT_COLS <= set(source.columns)


def _built_sign(source: pd.DataFrame, *, signal_builder, base_signal_cfg) -> pd.Series:
    """The sign column a pair's signal source produces, prebuilt or not."""
    if _is_prebuilt(source):
        return pd.Series(source["sign"]).astype(float)
    built = (signal_builder or build_signals)(source, base_signal_cfg)
    return pd.Series(built["sign"]).astype(float)


def _signal_key(cfg: dict) -> tuple:
    """The signal-axis part of a grid config, as a hashable key."""
    return tuple(sorted((k, v) for k, v in cfg.items() if k in _SIGNAL_FIELDS))


def _takes_both_directions(sign: pd.Series) -> bool:
    return (set(int(v) for v in sign.dropna().unique()) - {0}) == {FLATTENER,
                                                                  STEEPENER}


def _direction_coverage(source: pd.DataFrame, grid: Sequence[dict], *,
                        signal_builder, base_signal_cfg) -> Dict[tuple, bool]:
    """``{signal-config key: does that config take BOTH directions}``.

    The mirror is vacuous on a one-directional book, and whether a book is
    one-directional is a property of the CONFIG, not of the pair: the study's
    own ``build_config_grid`` sweeps ``short_side_enabled``, and every config
    with it False holds the flattener alone. Reading only the base config
    answers for a run nobody made.
    """
    if _is_prebuilt(source):
        return {(): _takes_both_directions(pd.Series(source["sign"]))}
    out: Dict[tuple, bool] = {}
    for cfg in grid:
        key = _signal_key(cfg)
        if key in out:
            continue
        scfg = replace(base_signal_cfg,
                       **{k: v for k, v in cfg.items() if k in _SIGNAL_FIELDS})
        built = (signal_builder or build_signals)(source, scfg)
        out[key] = _takes_both_directions(pd.Series(built["sign"]))
    return out


def _tag(frame: pd.DataFrame, family: str, sim: int = -1) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "family", family)
    out.insert(1, "sim", int(sim))
    return out


def _gross_usd(frame: pd.DataFrame) -> pd.Series:
    return frame[list(_GROSS_COLS)].sum(axis=1)


def run_placebos(
    ctx_by_pair: Dict[str, object],
    panel_by_pair: Dict[str, pd.DataFrame],
    grid: Sequence[dict],
    *,
    costs: CostSchedule,
    signal_builder: Optional[Callable[[pd.DataFrame, SignalConfig], pd.DataFrame]] = None,
    base_signal_cfg: Optional[SignalConfig] = None,
    base_rep_cfg: Optional[ReplicationConfig] = None,
    placebo_ctx_by_pair: Optional[Dict[str, object]] = None,
    placebo_panel_by_pair: Optional[Dict[str, pd.DataFrame]] = None,
    vol_col: str = "be_over_realized",
    block: int = 21,
    n_shuffles: int = 5,
    seed: int = 0,
    min_autocorr_ratio: float = 0.5,
    sign_mirror: bool = True,
    expect_placebo_pairs: bool = True,
) -> pd.DataFrame:
    """The three placebo legs plus the real run, one frame, one ``family`` column.

    Everything goes through :func:`backtest.run_grid`, so every leg inherits
    its refusals -- an unsweepable grid axis, a prebuilt frame reused for every
    config, an unknown key -- rather than reimplementing them here.

    ``attrs["legs_run"]`` and ``attrs["legs_skipped"]`` say what this frame
    actually contains. **Read them.** A placebo suite missing a leg is not a
    placebo suite, and a caller who passed no ``placebo_ctx_by_pair`` gets the
    real run plus two legs rather than an error, because the legs are useful
    separately during development. The verdict is not.

    ``vol_col`` is the column the shuffled-vol leg block-bootstraps. It
    defaults to ``be_over_realized`` -- the valuation switch, the largest lever
    of ``signal_state``'s five inputs and the one the vol story lives in.

    The sign mirror is refused outright unless the signal takes BOTH directions
    at some point: see the module docstring, and do not report a
    one-directional book's mirror as evidence.
    """
    base_signal_cfg = base_signal_cfg or SignalConfig()
    if (placebo_ctx_by_pair is None) != (placebo_panel_by_pair is None):
        raise ValueError(
            "the short-dated placebo needs BOTH placebo_ctx_by_pair and "
            "placebo_panel_by_pair: a context with no panel cannot be run and "
            "a panel with no context would silently reuse the real pair's "
            "pricing"
        )
    common = dict(costs=costs, signal_builder=signal_builder,
                  base_signal_cfg=base_signal_cfg, base_rep_cfg=base_rep_cfg)

    frames: List[pd.DataFrame] = []
    ran: List[str] = []
    skipped: List[str] = []

    real = run_grid(ctx_by_pair, panel_by_pair, grid, **common)
    frames.append(_tag(real, "real"))
    ran.append("real")

    # 1. the identical rulebook where the story should not hold
    if placebo_ctx_by_pair is not None:
        if expect_placebo_pairs:
            unknown = sorted(set(placebo_ctx_by_pair) - set(PLACEBO_PAIR_NAMES))
            if unknown or not placebo_ctx_by_pair:
                raise ValueError(
                    f"short-dated placebo pairs {unknown or 'none'} are not in "
                    f"universe.PLACEBO_PAIRS {list(PLACEBO_PAIR_NAMES)}. This "
                    "leg is requirement 1 -- the identical rulebook on the "
                    "SHORT-DATED slopes, where the convexity story should not "
                    "hold -- and it means nothing run against an arbitrary "
                    "second pair. Pass `expect_placebo_pairs=False` only when "
                    "deliberately probing a pair the study did not nominate."
                )
        short = _tag(run_grid(placebo_ctx_by_pair, placebo_panel_by_pair,
                              grid, **common), "short_dated")
        # The leg must have run on the PLACEBO contexts. Measured: replacing
        # this call with `_tag(real, "short_dated")` -- the real run's own rows
        # wearing the placebo label -- left the whole suite passing. A placebo
        # leg that reproduces the real number is a leg that ran nothing.
        got, want = set(short["pair"]), set(placebo_ctx_by_pair)
        if got != want:
            raise ValueError(
                f"the short-dated leg produced rows for {sorted(got)}, not for "
                f"the placebo pairs {sorted(want)} -- it did not run on the "
                "contexts it was given"
            )
        frames.append(short)
        ran.append("short_dated")
    else:
        skipped.append("short_dated")

    # 2. the block-bootstrapped valuation column
    shuffle_evidence: List[dict] = []
    if int(n_shuffles) > 0:
        for pair, source in panel_by_pair.items():
            if _is_prebuilt(source):
                raise ValueError(
                    f"{pair}: the shuffled-vol placebo needs a RAW signal panel "
                    f"(with {sorted(REQUIRED_COLUMNS)}); this one is already a "
                    f"built signal frame ({sorted(_SIGNAL_OUTPUT_COLS)}), so "
                    "bootstrapping a vol column would change nothing that "
                    "reaches a trading decision and the leg would report a "
                    "degradation of exactly zero."
                )
            if vol_col not in source.columns:
                raise ValueError(
                    f"{pair}: no {vol_col!r} column to bootstrap; the panel has "
                    f"{sorted(source.columns)}"
                )
        drawn: Dict[str, Dict[bytes, int]] = {p: {} for p in panel_by_pair}
        for sim in range(1, int(n_shuffles) + 1):
            shuffled = {}
            for pair, source in panel_by_pair.items():
                null = block_bootstrap(source[vol_col], block=block,
                                       seed=int(seed) * 10_000 + sim,
                                       min_ratio=min_autocorr_ratio)
                # `n_shuffles` must not be decorative. Measured: changing the
                # per-sim seed to a constant makes every simulation draw the
                # SAME null and the whole suite still passed -- a placebo
                # reporting n independent draws while holding one, i.e. an
                # under-dispersed null presented with n times its real sample
                # size. This is the same shape as the random-walk placebo's
                # own per-sim seeding, one function across.
                fingerprint = null.to_numpy().tobytes()
                if fingerprint in drawn[pair]:
                    raise ValueError(
                        f"{pair} sim {sim}: this null is identical to sim "
                        f"{drawn[pair][fingerprint]}. The shuffled-vol leg "
                        f"would report {n_shuffles} independent draws while "
                        "holding fewer, so its spread understates the null's. "
                        "Check that the per-sim seed actually varies."
                    )
                drawn[pair][fingerprint] = sim
                # The draw's OWN stamp, not a re-computation of it. Recomputing
                # is what let the two verdicts disagree (the series said one
                # thing at the default ratio, the gate said another at the
                # caller's), and it made the `min_ratio=` above dead code --
                # measured: removing it changed nothing observable.
                ev = dict(null.attrs)
                if not ev["persistence_preserved"]:
                    raise ValueError(
                        f"{pair} sim {sim}: the block bootstrap destroyed the "
                        f"persistence it exists to keep (lag-1 autocorrelation "
                        f"{ev['autocorr1_in']:.3f} -> {ev['autocorr1_out']:.3f}, "
                        f"ratio {ev['autocorr1_ratio']:.3f} against a floor of "
                        f"{min_autocorr_ratio}). A null with no persistence is "
                        "EASIER than the real series, so the valuation switch "
                        "would degrade for a reason that has nothing to do with "
                        "whether it reads vol. Raise `block`."
                    )
                ev.update({"pair": pair, "sim": sim})
                shuffle_evidence.append(ev)
                shuffled[pair] = source.assign(**{vol_col: null})
            frames.append(_tag(run_grid(ctx_by_pair, shuffled, grid, **common),
                               "shuffled_vol", sim=sim))
        ran.append("shuffled_vol")
    else:
        skipped.append("shuffled_vol")

    # 3. the sign mirror -- scoped, because the engine is antisymmetric
    scope_by_pair: Dict[str, dict] = {}
    if sign_mirror:
        for pair, source in panel_by_pair.items():
            # Per CONFIG, not just the base one. `build_config_grid` sweeps
            # `short_side_enabled`, and a config with it False is
            # one-directional however the base config behaves, so a guard that
            # only reads the base config passes it on the base's behalf.
            coverage = _direction_coverage(
                source, grid, signal_builder=signal_builder,
                base_signal_cfg=base_signal_cfg)
            scope_by_pair[pair] = coverage
            if not any(coverage.values()):
                held = _built_sign(source, signal_builder=signal_builder,
                                   base_signal_cfg=base_signal_cfg)
                held = sorted(set(int(v) for v in held.dropna().unique()) - {0})
                raise ValueError(
                    f"{pair}: NO config in this grid takes both directions "
                    f"(the base config holds {held or 'nothing'}), so the sign "
                    "mirror is arithmetically vacuous on all of them. "
                    "`simulate` is exactly antisymmetric in `sign` -- per-unit "
                    "DV01 is sign-invariant, notionals flip, PV and theta are "
                    "linear in notionals, the trigger reads a sign-independent "
                    "rate and the cost is a magnitude fee -- so the mirror of a "
                    "one-directional book is -gross + cost by construction and "
                    "reports nothing at all. Run it on the Task 17 conditional "
                    "rule, which takes BOTH directions and whose timing, not "
                    "the engine, decides which."
                )
        mirror = _tag(run_grid(ctx_by_pair, panel_by_pair, mirror_configs(grid),
                               **common), "sign_mirror")
        frames.append(_annotate_mirror(real, mirror, grid,
                                       scope_by_pair=scope_by_pair))
        ran.append("sign_mirror")
    else:
        skipped.append("sign_mirror")

    unknown = [f for f in ran + skipped if f not in PLACEBO_FAMILIES]
    if unknown:  # pragma: no cover -- keeps the exported constant truthful
        raise AssertionError(f"undeclared placebo family/families {unknown}")
    out = pd.concat(frames, ignore_index=True, sort=False)
    out.attrs.update({
        "legs_run": tuple(ran),
        "legs_skipped": tuple(skipped),
        "vol_col": vol_col,
        "block": int(block),
        "shuffle_evidence": shuffle_evidence,
        "sign_mirror_is_arithmetic": (
            bool(out.loc[out["family"] == "sign_mirror",
                         "mirror_is_arithmetic"].all())
            if "mirror_is_arithmetic" in out.columns
            and (out["family"] == "sign_mirror").any() else None),
    })
    return out


def _annotate_mirror(real: pd.DataFrame, mirror: pd.DataFrame,
                     grid: Sequence[dict], *, rel_tol: float = MIRROR_REL_TOL,
                     scope_by_pair: Optional[Dict[str, dict]] = None) -> pd.DataFrame:
    """Measure, on the run itself, whether the mirror was pure arithmetic.

    Joins each mirror row to its real counterpart on everything except the sign
    and records ``gross_real + gross_mirror``. The engine's antisymmetry says
    that sum is zero; the column exists so a reader does not have to take the
    module docstring's word for it, and so that a future change to ``simulate``
    that breaks the antisymmetry shows up as a number rather than as a
    silently more interesting mirror.

    ``mirror_scope_ok`` says whether THAT config's own signal takes both
    directions. A config that does not (``short_side_enabled=False``, say) has
    a vacuous mirror even when its neighbours in the grid do not.
    """
    keys = [k for k in {k for cfg in grid for k in cfg} if k != "sign"]
    on = ["pair", "book"] + sorted(keys)
    left = mirror.copy()
    right = real.copy()
    right["_gross_real"] = _gross_usd(right)
    if "sign" in right.columns and "sign" in left.columns:
        # the mirror row carrying sign s came from the real row carrying -s.
        # Without this the join is ambiguous whenever the grid itself sweeps
        # `sign`: both real rows match every mirror row on the remaining keys.
        right["sign"] = -right["sign"].astype(int)
        on = on + ["sign"]
    merged = left.merge(right[on + ["_gross_real"]], on=on, how="left",
                        validate="m:1")
    gross_mirror = _gross_usd(merged)
    total = merged["_gross_real"] + gross_mirror
    scale = pd.concat([merged["_gross_real"].abs(), gross_mirror.abs()],
                      axis=1).max(axis=1).clip(lower=1.0)
    left = left.reset_index(drop=True)
    left["mirror_gross_sum_usd"] = total.to_numpy()
    left["mirror_is_arithmetic"] = (total.abs() <= rel_tol * scale).to_numpy()
    if scope_by_pair is not None:
        left["mirror_scope_ok"] = [
            bool(scope_by_pair.get(row["pair"], {}).get(
                _signal_key({k: row[k] for k in row.index
                             if k in _SIGNAL_FIELDS}), False))
            for _, row in left.iterrows()
        ]
    return left


def run_confounds(
    ctx_by_pair: Dict[str, object],
    signals_by_pair: Dict[str, pd.DataFrame],
    config: dict,
    *,
    costs: CostSchedule,
    base_rep_cfg: Optional[ReplicationConfig] = None,
    rates_by_pair: Optional[Dict[str, pd.DataFrame]] = None,
    spread_by_pair: Optional[Dict[str, pd.Series]] = None,
    panel_by_pair: Optional[Dict[str, pd.DataFrame]] = None,
    signal_cfg: Optional[SignalConfig] = None,
    z_window: int = 252,
    z_min_periods: int = 126,
) -> pd.DataFrame:
    """The winner against duration-only, PC1-only and pure-carry.

    ``signals_by_pair`` are the winner's BUILT signal frames and ``config`` is
    its single replication config -- confounds are run against one winner, not
    against a grid, because the question is "what else pays this much" and a
    grid of alternatives would just re-open the multiple-testing problem the
    league table's DSR closes. Since the signals are prebuilt, ``config`` may
    name only ``ReplicationConfig`` fields; ``run_grid`` refuses a signal axis
    here, because a prebuilt frame cannot sweep one and every row would be the
    same run wearing a different label.

    The PC1 leg needs ``rates_by_pair`` (a wide curve panel) and
    ``spread_by_pair`` (the slope), plus ``panel_by_pair`` for the sizing
    column; without them it is skipped and named in ``attrs["skipped"]``.

    ``beats_winner`` and ``attrs["winner_beats_all"]`` fail closed on a
    confound that never traded: a comparator with no episodes did not lose the
    comparison, it never entered it. Same shape as the placebo's
    ``probe_reached``. They also fail closed on a WINNER that never traded --
    its metric is ``nan``, ``>= nan`` is False for every confound, and an empty
    book would otherwise read as a clean sweep of all three. That leg is
    currently redundant with the confound one, because ``duration_only`` runs
    the winner's own signals and is untraded whenever the winner is; it is kept
    because that redundancy is an implementation detail of one confound, and
    ``attrs["winner_informative"]`` reports it either way.
    """
    signal_cfg = signal_cfg or SignalConfig()
    grid = [dict(config)]
    frames: List[pd.DataFrame] = []
    skipped: List[str] = []
    common = dict(costs=costs, base_rep_cfg=base_rep_cfg)

    frames.append(_tag(run_grid(ctx_by_pair, signals_by_pair, grid, **common),
                       "winner"))

    duration = {p: DurationOnlyPricer(c) for p, c in ctx_by_pair.items()}
    frames.append(_tag(run_grid(duration, signals_by_pair, grid, **common),
                       "duration_only"))

    if rates_by_pair and spread_by_pair and panel_by_pair:
        pc1_signals = {}
        for pair, panel in panel_by_pair.items():
            proj = pc1_projection(rates_by_pair[pair], spread_by_pair[pair])
            roll = proj.rolling(int(z_window), min_periods=int(z_min_periods))
            z = (proj - roll.mean()) / roll.std(ddof=1)
            pc1_signals[pair] = z_rule_signals(z, panel, signal_cfg)
        frames.append(_tag(run_grid(ctx_by_pair, pc1_signals, grid, **common),
                           "pc1_only"))
    else:
        skipped.append("pc1_only")

    rep = replace(base_rep_cfg or ReplicationConfig(),
                  **{k: v for k, v in config.items()
                     if k in ReplicationConfig.__dataclass_fields__})
    carry_signals = {
        pair: carry_sign_signals(ctx, list(signals_by_pair[pair].index),
                                 rep_cfg=rep, costs=costs,
                                 base_dv01_usd=signal_cfg.base_dv01_usd)
        for pair, ctx in ctx_by_pair.items()
    }
    frames.append(_tag(run_grid(ctx_by_pair, carry_signals, grid, **common),
                       "pure_carry"))

    out = pd.concat(frames, ignore_index=True, sort=False)
    out[CONFOUND_METRIC] = np.where(
        out["n_trades"] > 0, out["total_net_bp"] / out["n_trades"].replace(0, np.nan),
        np.nan)
    out["informative"] = out["n_trades"] > 0

    win = out[out["family"] == "winner"].set_index("pair")[CONFOUND_METRIC]
    winner_metric = out["pair"].map(win)
    out["winner_metric"] = winner_metric.to_numpy()
    out["beats_winner"] = (out["informative"].to_numpy()
                           & (out[CONFOUND_METRIC] >= winner_metric).to_numpy()
                           & (out["family"] != "winner").to_numpy())
    alt = out[out["family"] != "winner"]
    won = out[out["family"] == "winner"]
    # A winner that never traded has a NaN metric, and `>= nan` is False for
    # every confound -- so without this leg an empty book "beats" all three.
    # The hole is the same shape as the confound one, one row across.
    winner_ok = bool(len(won) > 0 and bool(won["informative"].all())
                     and bool(np.isfinite(won[CONFOUND_METRIC].to_numpy()).all()))
    out.attrs.update({
        "metric": CONFOUND_METRIC,
        "skipped": tuple(skipped),
        "families": tuple(dict.fromkeys(out["family"])),
        "winner_informative": winner_ok,
        # fail closed: an uninformative confound has not been beaten
        "winner_beats_all": bool(winner_ok
                                 and len(alt) > 0
                                 and bool(alt["informative"].all())
                                 and not bool(alt["beats_winner"].any())
                                 and not skipped),
    })
    return out
