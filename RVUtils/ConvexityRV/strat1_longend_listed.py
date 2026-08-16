"""Strategy 1, long end, LISTED benchmark -- the backtest the signal work implied.

The signal side of this question is finished elsewhere. ``strat1_real_contracts``
built the real dated UST futures-option benchmark (``US@H365`` -- the contract
whose expiry is nearest one year out, rolled), ``strat1_threeway`` ranked the
curve against it and against the 1Yx30Y swaption, and both concluded that the
listed leg changes the *verdict* on ~2.4% of ``5Y/30Y`` days and on exactly 0% of
the other three structures' days.

What neither did is run a backtest. ``grep -c QueryDrivenBacktest`` over
``strat1_real_contracts.py`` and both of its notebooks returns **0**, and no P&L
claim appears in either. This module closes that gap: it drives
``strat1_curve_gamma.build_backtest`` -- the proven engine path, unmodified --
and turns one engine run per structure into a daily mark-to-market equity curve
for every gate mode.


The four gates, and what separates them
----------------------------------------
=================  =========================================================
gate               enters a cohort when
=================  =========================================================
``always``         always. No vol benchmark is consulted at all. This is the
                   CONTROL: an always-on long-end flattener. Every gated book
                   has to be read against it, because "the signal made money"
                   and "being long the flattener made money" are different
                   claims and only one of them is usually true here.
``swaption_only``  curve breakeven < 1Yx30Y ATMF. Strategy 1's committed
                   signal.
``listed_only``    curve breakeven < the REAL listed contract's ATM vol.
``both``           cheap (or rich) against both benchmarks; mixed stands
                   aside.
=================  =========================================================

The constant-maturity control (``US_30``) is run through ``listed_only`` as
well, so the real-contract-versus-interpolated-surface difference shows up in
P&L and not only in the signal counts ``cm_vs_real_table`` already reports.
It is **robustness, not a fifth trial** -- it is the same gate against a
differently-constructed version of the same benchmark -- and the multiple-testing
correction therefore counts four trials, not five.


ONE engine run per structure, and why that is the cleaner experiment
---------------------------------------------------------------------
Four structures x five books is twenty ``QueryDrivenBacktest`` passes at ~25-90
minutes each. It is also the *worse* design, for the reason ``strat1_threeway``
already sets out: swap NPV is linear in ``bpv``, ``build_backtest`` opens each
cohort at ``front_bpv = +dv01*s`` / ``back_bpv = -dv01*s``, and the unwind fee
does not depend on ``s``. So every gate's P&L is recoverable from one run in
which every cohort is opened as a pure flattener, and scoring the gates that way
puts them on **bit-identical cohort P&L** -- the only thing that differs between
two gate curves is the gate.

``strat1_threeway.apply_gate`` already does this at the COHORT level and the test
suite pins its known-answer property. What is new here is the same identity at
the DAILY level, which the equity curve needs and which nothing had verified:

    mtm(t) == sum_c [ value_c(t)  if cohort c is open at t
                      net_c       if it has closed by t ]

The engine's mark is ``realized_pnl + sum(open position values)``, each cohort's
two legs carry its own tag, and no cash is realised mid-hold on these packages,
so the identity is exact. :func:`cohort_contributions` performs the split and
``_strat1_longend_listed_build.py`` asserts it on every mark of every run --
measured max relative error **7e-16 to 8e-16** across the four long-end
structures, i.e. floating-point noise and nothing else.

That last clause is worth one more sentence, because "no cash is realised
mid-hold" is an assumption about the instrument, not a theorem: a package that
DID throw off cash between entry and unwind would have that cash land in
``realized_pnl`` untagged, and the sum would come apart. Which is exactly why the
identity is asserted per run rather than argued once here -- if a future
structure breaks it, the build fails loudly instead of composing wrong curves.

Re-costing is then explicit rather than implicit. The unit run charges
``2 * cost_bp_one_way * package_dv01`` at each unwind, so the composition strips
that fee back out and re-applies it only to cohorts the gate actually traded::

    raw_c(t)   = value_c(t) while open;  gross_c once closed   (no fee)
    gated_c(t) = g * raw_c(t)  -  |g| * fee_new * 1{closed by t}

``|g|`` rather than ``g`` is the load-bearing character: a steepener pays the
same cost as a flattener, and writing ``g`` there would *pay* the trader for
every short. Standing aside (``g == 0``) costs nothing, because charging for it
would flatter whichever gate trades least.


Composition is certified against the engine, not asserted
----------------------------------------------------------
Three checks, in increasing strength, all run in the notebook:

1. **The ``always`` book is composed and must reproduce the engine's own
   ``mtm_history`` exactly** -- same run, so any error is pure composition
   arithmetic.
2. **Composed cohort totals must equal**
   ``strat1_threeway.apply_gate``'s ``gate_net_bp``, which is separately tested
   code reached by a different expression.
3. **A genuine, independent ``QueryDrivenBacktest`` of one gated book**
   (``5Y/30Y`` under ``listed_only`` -- the only structure whose gates bind at
   all) is run and compared to its composition, reporting the terminal gap and
   the daily-change correlation, the same two numbers
   ``strat2_convexity_vs_fly_gridsearch`` certifies its panel simulation with.

If (3) disagreed by more than a few percent the engine number would be the one
to believe. It does not; :func:`certify_composition` reports the measured gap
either way.


Read the sample size before reading any Sharpe
-----------------------------------------------
One-year holds over 7.6 years is ~7.5 independent observations per structure, and
the four structures are not four bets: their measured pairwise unit-cohort P&L
correlation is 0.698, so ``k_eff = 4 / (1 + 3*0.698) = 1.29`` and the pooled
count is ~9.7. Three of the four structures are also **saturated** -- the curve
is cheap gamma against every benchmark on 100% of days -- so their ``swaption_only``,
``listed_only`` and ``both`` books are the ``always`` book with holes punched in
it wherever a benchmark is missing, and nothing else. ``5Y/30Y`` is the only
structure on which any gate can differ. :func:`saturation_table` measures that
rather than repeating it, and every Sharpe below is quoted against
``expected_max_sharpe_under_null`` at four trials and the measured pooled count.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_threeway as tw
from RVUtils.ConvexityRV.strat1_listed import LONG_END_STRUCTURES

__all__ = [
    "LONGEND_STRUCTURES",
    "GATE_MODES",
    "DISTINCT_GATE_MODES",
    "ALWAYS",
    "REAL_BENCHMARK",
    "CM_BENCHMARK",
    "LongEndListedConfig",
    "safe_label",
    "strat1_config",
    "threeway_config",
    "load_threeway",
    "gate_series",
    "cohort_contributions",
    "compose_gate_equity",
    "compose_all_books",
    "saturation_table",
    "book_stats",
    "cost_sensitivity",
    "breakeven_cost_bp",
    "certify_composition",
    "sharpe_scoreboard",
]

#: Strategy 1's own long-end four, imported rather than restated so a change to
#: the universe cannot leave two modules disagreeing about what "30Y/50Y" means.
LONGEND_STRUCTURES: Tuple[Tuple[str, str, str], ...] = LONG_END_STRUCTURES

#: The always-on control's name. Not a member of ``strat1_threeway.GATE_MODES``
#: because it is not a gate on anything -- it consults no benchmark at all.
ALWAYS: str = "always"

#: Books run here, control first.
GATE_MODES: Tuple[str, ...] = (ALWAYS, "swaption_only", "listed_only", "both")

#: What the multiple-testing correction counts. Identical to :data:`GATE_MODES`:
#: four books, four trials. The constant-maturity control is deliberately NOT in
#: here -- it is ``listed_only`` against a differently-built version of the same
#: benchmark, and counting it would inflate the trial count without adding a
#: degree of freedom. ``cheapest`` is absent because ``strat1_threeway`` proves
#: it is identical to ``both``.
DISTINCT_GATE_MODES: Tuple[str, ...] = GATE_MODES

#: The REAL dated contract benchmark: US (30Y bond future) options, expiry picked
#: nearest the one-year horizon and rolled. ``primary`` for all four structures.
REAL_BENCHMARK: str = "US@H365"
#: The constant-maturity control, same root, 30-day interpolated surface. Pinned
#: by ROOT rather than by role because ``US_30`` is ``primary`` for two
#: structures and ``alt`` for the other two, and a role-based selection would
#: silently compare US against UL.
CM_BENCHMARK: Tuple[str, int] = ("US", 30)


@dataclasses.dataclass(frozen=True)
class LongEndListedConfig:
    """Every knob of THIS study. Nothing here is tuned on the P&L.

    The backtest knobs are deliberately absent: they belong to
    :func:`strat1_config`, which restates strategy 1's committed base run
    unchanged ($100k package DV01, monthly cohorts, 1-year hold, 0.5 bp one-way,
    no force-close, 2019-01-02..2026-08-14). Duplicating them here is how two
    configs drift apart and how "directly comparable to the base run" quietly
    stops being true.
    """

    #: The books, control first. ``always`` is not a gate on anything -- it
    #: consults no benchmark and is the control every gated book is read
    #: against, because "the signal made money" and "being long the flattener
    #: made money" are different claims.
    gate_modes: Tuple[str, ...] = GATE_MODES
    #: Trials the multiple-testing correction counts. Four books, four trials.
    distinct_gate_modes: Tuple[str, ...] = DISTINCT_GATE_MODES
    #: The REAL dated contract benchmark for ``listed_only`` / ``both``.
    real_benchmark: str = REAL_BENCHMARK
    #: The constant-maturity control, reported ALONGSIDE ``listed_only`` so the
    #: real-vs-interpolated difference shows up in P&L. Robustness, not a trial.
    cm_benchmark: Tuple[str, int] = CM_BENCHMARK
    #: Cost multiples on ``strat1_config().cost_bp_one_way`` (0.5 bp one way).
    #: ``1.0`` is the headline; ``0.0`` isolates gross; ``2.0`` is 1 bp one way.
    cost_multipliers: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)
    #: The (structure, gate) pair re-run through a GENUINE engine pass to certify
    #: the composition. ``5Y/30Y`` because it is the only structure whose gates
    #: bind at all -- certifying a saturated structure would certify the identity
    #: ``g == 1`` and prove nothing. ``listed_only`` because it is the book this
    #: study exists to produce and the one with no stored engine run anywhere.
    certify_structure: str = "5Y/30Y"
    certify_gate: str = "listed_only"
    #: Business days per year, for annualising the daily-MTM Sharpe. Matches the
    #: bp/day bridge every vol in the signal panel was converted with.
    business_days_per_year: float = 252.0

    def labels(self) -> Tuple[str, ...]:
        return tuple(s[0] for s in LONGEND_STRUCTURES)

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def safe_label(label: str) -> str:
    """Filesystem-safe structure label. ``"5Y/30Y"`` -> ``"5Y-30Y"``."""
    return str(label).replace("/", "-").replace(" ", "_")


def strat1_config(**overrides: Any) -> s1.Strat1Config:
    """Strategy 1's OWN config, restricted to the long-end four.

    Every knob is left at the committed base run's value on purpose -- $100k
    package DV01, monthly cohorts, a 1-year hold, 0.5 bp one-way, no force-close
    at the end, 2019-01-01..2026-08-14. The whole point of this study is that its
    books are directly comparable to that run, and a single differing knob would
    make every comparison below a comparison of two configurations instead of
    two gates.
    """
    base: Dict[str, Any] = dict(structures=LONGEND_STRUCTURES)
    base.update(overrides)
    return s1.Strat1Config(**base)


def threeway_config(**overrides: Any) -> tw.Strat1ThreeWayConfig:
    """The three-way config, i.e. ``strat1_threeway.longend_config``.

    Reused rather than re-derived so the gates here are the same gates the signal
    study reported: same 0.0 threshold, same two-sided rule, same
    ``require_all_three``, same one-day lag.
    """
    return tw.longend_config(**overrides)


# ---------------------------------------------------------------- the benchmarks


def load_threeway(data_dir: Any, *, benchmark: str = "real",
                  cfg: Optional[tw.Strat1ThreeWayConfig] = None) -> pd.DataFrame:
    """The ``(date, structure)`` three-way frame for one benchmark.

    ``benchmark="real"``
        the real dated contract :data:`REAL_BENCHMARK`, selected out of
        ``strat1_contracts_panel.parquet`` by ``listed_symbol``.
    ``benchmark="cm"``
        the constant-maturity control :data:`CM_BENCHMARK`, selected out of
        ``strat1_contracts_cm_control.parquet`` through
        ``strat1_threeway.select_longend_benchmark`` by ROOT.

    Both go through ``strat1_threeway.threeway_frame`` unmodified, so the gates,
    the ranking and the usable mask are the signal study's, not a second
    implementation of them. The curve and swaption columns are identical between
    the two frames by construction -- only ``listed_atm_bp_day`` differs, which
    is exactly the experiment.
    """
    cfg = cfg or threeway_config()
    d = pathlib.Path(data_dir)
    b = str(benchmark).lower()
    if b == "real":
        panel = pd.read_parquet(d / "strat1_contracts_panel.parquet")
        sel = panel[panel["listed_symbol"].astype(str) == REAL_BENCHMARK].copy()
        if sel.empty:
            raise ValueError(f"no rows for listed_symbol={REAL_BENCHMARK!r}")
        if sel.duplicated(subset=["date", "structure"]).any():
            raise ValueError(f"{REAL_BENCHMARK} has a duplicated (date, structure) key")
        return tw.threeway_frame(sel, cfg)
    if b == "cm":
        panel = pd.read_parquet(d / "strat1_contracts_cm_control.parquet")
        root, cm_days = CM_BENCHMARK
        sel = tw.select_longend_benchmark(panel, role=None, root=root, cm_days=cm_days)
        return tw.threeway_frame(sel, cfg)
    raise ValueError(f"benchmark must be 'real' or 'cm', got {benchmark!r}")


def gate_series(three: pd.DataFrame, label: str, mode: str,
                *, index: Optional[pd.Index] = None) -> pd.Series:
    """One structure's UNLAGGED {+1, 0, -1} direction for one gate mode.

    The lag is applied by the consumer -- ``strat1_threeway.apply_gate`` lags
    internally, ``strat1_curve_gamma.build_backtest`` does not -- and lagging
    twice is the sort of error that makes a backtest look better while leaving
    no trace in any output. Everything downstream of this function takes the
    unlagged series and is explicit about where the shift happens.

    ``mode="always"`` returns +1 everywhere on ``index`` (or on the frame's own
    dates), consulting no benchmark: it is the control, and it must trade on
    cohort dates where a benchmark is missing, which is precisely what the gated
    books cannot do.
    """
    if str(mode) == ALWAYS:
        idx = index
        if idx is None:
            idx = three.xs(label, level="structure").index
        return pd.Series(1.0, index=pd.DatetimeIndex(pd.to_datetime(idx)))
    sub = three.xs(label, level="structure")
    col = f"gate_{mode}"
    if col not in sub.columns:
        raise KeyError(f"three-way frame has no {col!r}; have "
                       f"{[c for c in sub.columns if c.startswith('gate_')]}")
    out = sub[col].astype(float)
    out.index = pd.to_datetime(out.index)
    return out.sort_index() if index is None else out.reindex(pd.to_datetime(index))


# ------------------------------------------------------- the daily decomposition


def cohort_contributions(equity: pd.Series, cohorts: pd.DataFrame,
                         marks: pd.DataFrame, *,
                         cfg: Optional[s1.Strat1Config] = None,
                         check: bool = True, tol: float = 1e-6
                         ) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    """Split one engine run's daily equity into per-cohort daily contributions.

    Returns ``(raw, closed_step, max_abs_err)``:

    ``raw``
        ``date x tag`` of the cohort's GROSS contribution -- its marked value
        while open, and its gross realised P&L (fee removed) from its exit
        onward. Fee-free on purpose: the gate re-applies cost itself, because a
        cohort the gate stands aside from must not pay one.
    ``closed_step``
        ``date x tag`` 0/1 indicator of "this cohort has closed by now", which is
        what the re-applied fee multiplies.
    ``max_abs_err``
        the measured error of ``sum_c contribution_c(t) == equity(t)`` over every
        mark, in currency. This is an identity, so the number should be
        floating-point noise; it is returned rather than swallowed so a caller
        can print it, and asserted here when ``check``.

    The identity is what the whole composition rests on, so it is measured on
    every run rather than argued once in a docstring.
    """
    cfg = cfg or strat1_config()
    idx = pd.DatetimeIndex(pd.to_datetime(equity.index)).sort_values()
    eq = pd.Series(equity.to_numpy(float),
                   index=pd.to_datetime(equity.index)).sort_index().reindex(idx)

    tags = [str(t) for t in cohorts["tag"]]
    raw = pd.DataFrame(0.0, index=idx, columns=tags)
    step = pd.DataFrame(0.0, index=idx, columns=tags)
    fee_unit = 2.0 * float(cfg.cost_bp_one_way) * float(cfg.package_dv01)

    mk = marks.copy()
    mk.index = pd.to_datetime(mk.index)
    mk = mk.reindex(idx)

    for _, r in cohorts.iterrows():
        tag = str(r["tag"])
        if tag in mk.columns:
            raw[tag] = mk[tag].fillna(0.0).to_numpy(float)
        if bool(r["closed"]):
            on = (idx >= pd.Timestamp(r["exit"])).astype(float)
            step[tag] = on
            raw[tag] = raw[tag].to_numpy(float) + on * float(r["gross_pnl_ccy"])

    # The unit run's own equity = gross contributions minus the fee it charged.
    recon = raw.sum(axis=1) - fee_unit * step.sum(axis=1)
    err = float((recon - eq).abs().max())
    if check:
        scale = max(float(eq.abs().max()), 1.0)
        if not (err <= tol * scale):
            raise AssertionError(
                f"daily decomposition failed: max abs error ${err:,.2f} "
                f"({err / scale:.2e} relative). Every composed equity curve "
                "would be wrong -- prefer a per-gate engine run.")
    return raw, step, err


def compose_gate_equity(raw: pd.DataFrame, step: pd.DataFrame,
                        cohorts: pd.DataFrame, direction: pd.Series, *,
                        cfg: Optional[s1.Strat1Config] = None,
                        cost_bp_one_way: Optional[float] = None,
                        lag_days: int = 1) -> Tuple[pd.Series, pd.DataFrame]:
    """One gate's DAILY equity and cohort book, composed from one unit run.

    ``direction`` is the UNLAGGED date-indexed gate; the ``lag_days`` shift is
    applied here, once, matching ``strat1_threeway.apply_gate`` exactly so the
    daily curve and the cohort book cannot disagree about which cohorts traded.

    The arithmetic, per cohort::

        gated_c(t) = g_c * raw_c(t)  -  |g_c| * fee_new * closed_c(t)

    ``|g_c|`` and not ``g_c``: a steepener pays the same round trip as a
    flattener. Cohorts the gate skipped contribute nothing and pay nothing.

    Returns ``(equity_usd, book)``. ``book`` carries one row per cohort with its
    gated direction, gross, cost and net in bp of package DV01, plus
    ``marked_bp`` for cohorts still live at the sample end -- which are MARKED,
    never force-closed, so ``net`` is NaN for them by design.
    """
    cfg = cfg or strat1_config()
    cost = float(cfg.cost_bp_one_way if cost_bp_one_way is None else cost_bp_one_way)
    fee = 2.0 * cost * float(cfg.package_dv01)

    sig = pd.Series(direction).copy()
    sig.index = pd.to_datetime(sig.index)
    sig = sig.sort_index()
    if lag_days:
        sig = sig.shift(int(lag_days))
    sig = sig.fillna(0.0)

    idx = raw.index
    g = sig.reindex(pd.to_datetime(cohorts["entry"])).to_numpy(float)
    g = np.where(np.isfinite(g), g, 0.0)

    tags = [str(t) for t in cohorts["tag"]]
    G = pd.Series(g, index=tags)
    equity = (raw[tags].mul(G, axis=1).sum(axis=1)
              - fee * step[tags].mul(np.abs(G), axis=1).sum(axis=1))
    equity.index = idx

    dv01 = float(cfg.package_dv01)
    rows: List[Dict[str, Any]] = []
    for k, (_, r) in enumerate(cohorts.iterrows()):
        tag = str(r["tag"])
        gi = float(g[k])
        closed = bool(r["closed"])
        gross_bp = (gi * float(r["gross_pnl_ccy"]) / dv01) if closed else np.nan
        cost_bp = (2.0 * cost) if gi != 0.0 else 0.0
        rows.append({
            "tag": tag,
            "structure": r["structure"],
            "entry": pd.Timestamp(r["entry"]),
            "exit": pd.NaT if not closed else pd.Timestamp(r["exit"]),
            "unit_direction": float(r["direction"]),
            "gate_direction": gi,
            "traded": gi != 0.0,
            "closed": closed,
            "gate_closed": bool(closed and gi != 0.0),
            "gross_bp": 0.0 if (closed and gi == 0.0) else gross_bp,
            "cost_bp": cost_bp,
            "net_bp": (np.nan if not (closed and gi != 0.0)
                       else gross_bp - 2.0 * cost),
            "marked_bp": (np.nan if closed
                          else gi * float(raw[tag].iloc[-1]) / dv01),
        })
    return equity, pd.DataFrame(rows)


def compose_all_books(unit: Mapping[str, Dict[str, Any]],
                      gates: Mapping[str, Mapping[str, pd.Series]], *,
                      cfg: Optional[s1.Strat1Config] = None,
                      cost_bp_one_way: Optional[float] = None
                      ) -> Tuple[Dict[Tuple[str, str], pd.Series], pd.DataFrame]:
    """Every (structure, gate) book from the per-structure unit runs.

    ``unit`` maps label -> ``{"equity","cohorts","raw","step"}``; ``gates`` maps
    label -> {mode -> unlagged direction}. Returns the daily equity curves keyed
    ``(label, mode)`` and one concatenated cohort book.
    """
    cfg = cfg or strat1_config()
    eq: Dict[Tuple[str, str], pd.Series] = {}
    books: List[pd.DataFrame] = []
    for label, u in unit.items():
        for mode, d in gates.get(label, {}).items():
            e, b = compose_gate_equity(u["raw"], u["step"], u["cohorts"], d,
                                       cfg=cfg, cost_bp_one_way=cost_bp_one_way)
            b["gate_mode"] = mode
            eq[(label, mode)] = e
            books.append(b)
    if not books:
        raise ValueError("no (structure, gate) pair produced a book")
    return eq, pd.concat(books, ignore_index=True)


# --------------------------------------------------------------- what the gates do


def saturation_table(three: pd.DataFrame,
                     cfg: Optional[tw.Strat1ThreeWayConfig] = None) -> pd.DataFrame:
    """Per structure: is the verdict SATURATED, and can any gate differ?

    Printed before any P&L, because on three of the four structures the answer
    is "no" and four identical equity curves presented as four results would be
    the single most misleading thing this study could produce.

    ``frac_gate_equals_always`` is the number that matters: the share of
    ``usable`` days on which the gate is +1, i.e. does exactly what the always-on
    control does. ``frac_days_unusable`` is the OTHER way a gated book differs
    from the control -- not disagreement but a missing benchmark, which forces
    the gate to 0 while the control still trades.
    """
    cfg = cfg or threeway_config()
    df = three.reset_index()
    rows: List[Dict[str, Any]] = []
    for label, g in df.groupby("structure", sort=False):
        u = g["usable"].to_numpy(bool)
        gu = g[u]
        row: Dict[str, Any] = {
            "structure": label,
            "n_days": int(len(g)),
            "n_days_usable": int(u.sum()),
            "frac_days_unusable": float((~u).mean()) if len(g) else np.nan,
        }
        for mode in ("swaption_only", "listed_only", "both"):
            col = gu[f"gate_{mode}"].to_numpy(float)
            row[f"{mode}_frac_cheap"] = float((col > 0).mean()) if len(col) else np.nan
            row[f"{mode}_frac_rich"] = float((col < 0).mean()) if len(col) else np.nan
        row["saturated"] = bool(row["both_frac_cheap"] == 1.0)
        row["frac_signals_disagree"] = (
            float((~gu["signals_agree"].to_numpy(bool)).mean()) if len(gu) else np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- statistics


def book_stats(equity: pd.Series, book: pd.DataFrame, *,
               cfg: Optional[s1.Strat1Config] = None,
               carry_bp: float = float("nan"),
               business_days_per_year: float = 252.0) -> Dict[str, Any]:
    """Every headline number for ONE (structure, gate) book.

    Two different objects are summarised and they are deliberately not merged:

    * the **daily MTM equity** -- the engine's mark, which includes cohorts still
      live at the end. Its Sharpe is annualised off daily changes and its
      drawdown is the drawdown a book running this would have shown. It is
      quoted in bp of ONE package's DV01 while the book holds ~12 packages at
      once, so the drawdown must be read against that aggregate.
    * the **closed cohort round trips** -- one row per completed 1-year hold.
      Sharpe-per-trade, hit rate and the t-statistic are computed on these, and
      they are the only things comparable to strategy 1's own base run.

    ``t_stat_overlap_adj`` divides the nominal t by ``sqrt(n_closed / n_eff)``:
    monthly cohorts held a year share ~92% of their window, so the nominal count
    is an upper bound on the evidence and never the evidence itself.
    """
    cfg = cfg or strat1_config()
    dv01 = float(cfg.package_dv01)
    eq_bp = pd.Series(equity.to_numpy(float) / dv01,
                      index=pd.to_datetime(equity.index)).sort_index()
    d = eq_bp.diff().dropna()
    dd = eq_bp - eq_bp.cummax()

    closed = book[book["gate_closed"].to_numpy(bool)]
    p = closed["net_bp"].to_numpy(float)
    p = p[np.isfinite(p)]
    n = int(len(p))
    sd = float(p.std(ddof=1)) if n > 1 else np.nan
    sr_trade = float(p.mean() / sd) if n > 1 and sd > 0 else np.nan
    tstat = float(p.mean() / (sd / math.sqrt(n))) if n > 1 and sd > 0 else np.nan
    n_eff = (tw.effective_independent_n(closed["entry"], closed["exit"],
                                        cfg.horizon_years) if n else np.nan)
    sd_d = float(d.std(ddof=1)) if len(d) > 1 else np.nan
    sharpe_ann = (float(d.mean() / sd_d * math.sqrt(business_days_per_year))
                  if len(d) > 1 and sd_d > 0 else np.nan)

    live = book[(~book["closed"].to_numpy(bool)) & book["traded"].to_numpy(bool)]
    return {
        "n_cohorts": int(len(book)),
        "n_traded": int(book["traded"].sum()),
        "frac_traded": float(book["traded"].mean()) if len(book) else np.nan,
        "frac_flattener": (float((book.loc[book["traded"], "gate_direction"] > 0).mean())
                           if book["traded"].any() else np.nan),
        "n_closed": n,
        "n_live_marked": int(len(live)),
        "n_eff_independent": float(n_eff) if np.isfinite(n_eff) else np.nan,
        # --- closed round trips
        "total_net_bp": float(p.sum()) if n else np.nan,
        "total_net_usd": float(p.sum() * dv01) if n else np.nan,
        "mean_net_bp": float(p.mean()) if n else np.nan,
        "median_net_bp": float(np.median(p)) if n else np.nan,
        "std_net_bp": sd,
        "hit_rate": float((p > 0).mean()) if n else np.nan,
        "sharpe_per_trade": sr_trade,
        # Third and fourth moments of the closed round trips, so the deflated
        # Sharpe is computed with the book's OWN non-normality rather than the
        # normal defaults. ``kurtosis`` here is the RAW fourth standardised
        # moment (3.0 for a normal), which is what
        # ``strat1_threeway.deflated_sharpe_ratio`` expects -- feeding it an
        # EXCESS kurtosis would silently understate the deflation.
        "skew": (float(((p - p.mean()) ** 3).mean() / sd ** 3)
                 if n > 2 and np.isfinite(sd) and sd > 0 else np.nan),
        "kurtosis": (float(((p - p.mean()) ** 4).mean() / sd ** 4)
                     if n > 3 and np.isfinite(sd) and sd > 0 else np.nan),
        "t_stat_nominal": tstat,
        "t_stat_overlap_adj": (tstat / math.sqrt(n / n_eff)
                               if np.isfinite(tstat) and np.isfinite(n_eff) and n_eff > 0
                               else np.nan),
        "mean_carry_bp": float(carry_bp),
        # --- daily MTM equity
        "mtm_final_bp": float(eq_bp.iloc[-1]) if len(eq_bp) else np.nan,
        "mtm_final_usd": float(eq_bp.iloc[-1] * dv01) if len(eq_bp) else np.nan,
        "mtm_max_dd_bp": float(dd.min()) if len(dd) else np.nan,
        "mtm_max_dd_usd": float(dd.min() * dv01) if len(dd) else np.nan,
        "mtm_sharpe_ann": sharpe_ann,
        "mtm_n_marks": int(len(eq_bp)),
    }


def cost_sensitivity(raw: pd.DataFrame, step: pd.DataFrame, cohorts: pd.DataFrame,
                     direction: pd.Series, *, cfg: Optional[s1.Strat1Config] = None,
                     multipliers: Sequence[float] = (0.0, 0.5, 1.0, 2.0)
                     ) -> pd.DataFrame:
    """Closed-cohort net P&L at several cost levels.

    ``multipliers`` scale ``cfg.cost_bp_one_way`` (0.5 bp), so ``1.0`` is the
    headline run and ``2.0`` is 1.0 bp one-way / 2.0 bp round trip. Only the fee
    term moves; the gate, the cohorts and the gross P&L are identical across
    rows, which is what makes the column a sensitivity rather than four
    backtests.
    """
    cfg = cfg or strat1_config()
    base = float(cfg.cost_bp_one_way)
    rows: List[Dict[str, Any]] = []
    for m in multipliers:
        c = base * float(m)
        eq, book = compose_gate_equity(raw, step, cohorts, direction, cfg=cfg,
                                       cost_bp_one_way=c)
        cl = book[book["gate_closed"].to_numpy(bool)]
        p = cl["net_bp"].to_numpy(float)
        p = p[np.isfinite(p)]
        rows.append({
            "cost_multiple": float(m),
            "cost_bp_one_way": c,
            "cost_bp_round_trip": 2.0 * c,
            "n_closed": int(len(p)),
            "total_net_bp": float(p.sum()) if len(p) else np.nan,
            "mean_net_bp": float(p.mean()) if len(p) else np.nan,
            "hit_rate": float((p > 0).mean()) if len(p) else np.nan,
            "sharpe_per_trade": (float(p.mean() / p.std(ddof=1))
                                 if len(p) > 1 and p.std(ddof=1) > 0 else np.nan),
            "mtm_final_bp": float(eq.iloc[-1] / cfg.package_dv01) if len(eq) else np.nan,
        })
    return pd.DataFrame(rows)


def breakeven_cost_bp(book: pd.DataFrame) -> float:
    """One-way cost, bp of package DV01, at which the closed book's total is zero.

    Total net is linear in the cost -- ``sum(gross) - 2 * c * n_traded_closed`` --
    so this is exact rather than a search. Returns NaN when nothing closed, and
    a NEGATIVE number when the book loses money gross, which is a meaningful
    answer (no cost level rescues it) and is reported as such rather than
    clipped to zero.
    """
    cl = book[book["gate_closed"].to_numpy(bool)]
    g = cl["gross_bp"].to_numpy(float)
    g = g[np.isfinite(g)]
    n = len(g)
    if n == 0:
        return float("nan")
    return float(g.sum() / (2.0 * n))


def certify_composition(engine_equity: pd.Series, composed_equity: pd.Series,
                        *, label: str, mode: str,
                        cfg: Optional[s1.Strat1Config] = None) -> Dict[str, Any]:
    """Composed daily equity against a GENUINE engine run of the same book.

    The two numbers that matter, and the same two
    ``strat2_convexity_vs_fly_gridsearch`` certifies with: the **terminal gap**
    (level agreement) and the **correlation of daily changes** (path agreement).
    A composition can hit the terminal number by luck while taking a completely
    different path, and the daily correlation is what refuses to let that pass.

    Compared on the intersection of the two date indices, because the engine run
    and the unit run are driven off the same grid but a gated run holds nothing
    on days every cohort stands aside and can therefore end its history early.
    """
    cfg = cfg or strat1_config()
    dv01 = float(cfg.package_dv01)
    a = pd.Series(engine_equity.to_numpy(float),
                  index=pd.to_datetime(engine_equity.index)).sort_index()
    b = pd.Series(composed_equity.to_numpy(float),
                  index=pd.to_datetime(composed_equity.index)).sort_index()
    idx = a.index.intersection(b.index)
    a, b = a.reindex(idx), b.reindex(idx)
    da, db = a.diff().dropna(), b.diff().dropna()
    j = pd.concat({"engine": da, "composed": db}, axis=1).dropna()
    gap = float(a.iloc[-1] - b.iloc[-1]) if len(a) else float("nan")
    denom = max(abs(float(a.iloc[-1])), 1e-9) if len(a) else float("nan")
    return {
        "structure": label,
        "gate_mode": mode,
        "n_marks_common": int(len(idx)),
        "engine_terminal_usd": float(a.iloc[-1]) if len(a) else float("nan"),
        "composed_terminal_usd": float(b.iloc[-1]) if len(b) else float("nan"),
        "engine_terminal_bp": float(a.iloc[-1] / dv01) if len(a) else float("nan"),
        "composed_terminal_bp": float(b.iloc[-1] / dv01) if len(b) else float("nan"),
        "terminal_gap_usd": gap,
        "terminal_gap_pct": float(100.0 * gap / denom),
        "max_abs_daily_gap_usd": float((a - b).abs().max()) if len(a) else float("nan"),
        "corr_daily_changes": (float(j["engine"].corr(j["composed"]))
                               if len(j) > 2 else float("nan")),
        "n_daily_changes": int(len(j)),
    }


def sharpe_scoreboard(stats: pd.DataFrame, n_eff_pooled: float,
                      *, n_trials: int = len(DISTINCT_GATE_MODES),
                      sharpe_col: str = "sharpe_per_trade") -> pd.DataFrame:
    """Every book's Sharpe against what the BEST of ``n_trials`` nulls would give.

    ``expected_max_sharpe_under_null`` at the measured pooled effective count is
    the bar: pick the best of four gate modes on ~9.7 independent observations
    and a zero-edge strategy still scores this well on average. A Sharpe below it
    is not evidence of anything, and ``clears_max_null`` says so per row rather
    than leaving the reader to compare two columns.

    ``deflated_sharpe`` is Bailey & Lopez de Prado's probability that the true
    per-observation Sharpe exceeds that bar, computed with the book's own skew
    and kurtosis.
    """
    bar = tw.expected_max_sharpe_under_null(int(n_trials), n_obs=int(round(n_eff_pooled)))
    out = stats.copy()
    out["e_max_sharpe_null"] = bar
    out["clears_max_null"] = out[sharpe_col] > bar
    out["deflated_sharpe"] = [
        tw.deflated_sharpe_ratio(float(s), int(round(n_eff_pooled)), sr_benchmark=bar,
                                 skew=float(sk) if np.isfinite(sk) else 0.0,
                                 kurtosis=float(ku) if np.isfinite(ku) else 3.0)
        if np.isfinite(s) else np.nan
        for s, sk, ku in zip(out[sharpe_col],
                             out.get("skew", pd.Series(0.0, index=out.index)),
                             out.get("kurtosis", pd.Series(3.0, index=out.index)))
    ]
    return out
