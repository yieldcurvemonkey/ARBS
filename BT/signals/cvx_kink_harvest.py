r"""W3 harvest book — same-tenor forward pairs held on kink-screen gates.

Signal-panel-driven (the ``BT/signals/ustf_basis.py`` library shape): this
module takes a PRECOMPUTED screen panel and turns it into episodes and a
``QueryDrivenBacktest``. It never computes screens internally — residuals,
breakevens and rac_net belong to the kink screen (``RVUtils.CvxSuite``); the
engine owns marks, portfolio and realized P&L (the panel-is-not-P&L rule).

Panel contract (binding)
------------------------
``episodes_from_panel`` takes a DataFrame indexed by a two-level MultiIndex
named exactly ``("date", "pair")`` — ``date`` ascending ``pd.Timestamp``-like,
``pair`` the lowercase CurveFlyScreener pair label ``"10y10y/15y10y"`` — with
columns (further columns are ignored):

* ``be_over_rv`` — sigma_BE / sigma_rlzd, both bp/day, unitless. Gate
  INCLUSIVE: ``>= cfg.min_be_over_rv``.
* ``zs``         — z-score of the ADJUSTED level, POLARITY positive = RICH
  (books.py contract). Gate INCLUSIVE: ``<= cfg.max_z``.
* ``rac_net``    — rac_net@FPT, bp. Gate STRICT: ``> cfg.min_rac_net``
  (DESIGN §5 "rac_net@FPT > 0" — the floor is exclusive).

NaN in any gate input REFUSES that decision (citi_rule semantics, exactly
``RVUtils.CvxSuite.books``); a missing ``(date, pair)`` row refuses the same
way. Inclusivities mirror ``books.classify_books`` and are mutation-tested.

Reform mechanics and lag-1 (deliberate conventions)
---------------------------------------------------
Decisions happen ONLY at monthly reform dates: the first panel date of each
``cfg.reform`` period ("M") inside ``[cfg.start, cfg.end]`` (a mid-period
start's first date IS a reform date — the book forms at inception). EVERY
reform decision — enter, keep holding, exit — reads the row at **t-1**: the
panel date immediately BEFORE the reform date in the FULL panel index (history
before ``cfg.start`` is legal signal). Signal on day i fills on day i+1; a
same-day read is the classic lookahead and the tests plant rows that catch it.
Gate changes BETWEEN reform dates are ignored entirely (monthly reform, not a
daily stop). An episode still open after the last reform decision exits on the
last in-range panel date; an entry is refused AT that last date (no time to
hold). One position per pair; re-entry at a later reform is allowed.

Direction (pinned to the framework, re-derived from the engine)
---------------------------------------------------------------
The harvest book is SHORT local convexity (kink_ledger.md §"The two books":
"Harvest book — short local convexity … same-tenor forward pairs. Needs no
reversion to pay — the roll-off is the P&L"). On a pair ``front/back`` that is
the STEEPENER: RECEIVE the front leg (``bpv = -dv01``), PAY the back leg
(``bpv = +dv01``) — the mirror of the Citi flattener, which
docs/convexityrv/DESIGN.md §1 measured as long convexity (``CURVE bpv < 0``).
``+bpv`` is a PAYER through this engine (rac_backtest convention; the display
label says otherwise and is wrong — trap L-0012). ``sign_probe`` re-derives
the ±bpv mirror from the engine on every ``run_backtest`` rather than
trusting this paragraph.

Engine construction (rac_backtest pattern, reasons recorded there)
------------------------------------------------------------------
Two ``IRSwapStructure.OUTRIGHT`` legs per episode with EXPLICIT effective and
maturity dates resolved against the ENTRY date's curve — a relative tenor
re-resolves at every mark to a fresh at-market package whose NPV is ~0 by
construction, and the position never ages. Trigger dates are plain
``datetime.date`` — ``DateTriggerRequirements`` compares ``state.date()``
against its set, and a ``pd.Timestamp`` there is a silent no-op that marks
zero on every date. Fee is booked once, at unwind (the engine's only cost
hook): ``2 legs x 2 sides x cfg.half_spread_bp x cfg.package_dv01_usd`` USD
(bp of rate times USD-per-bp; NO further /1e4 — dv01 already carries the
dollar scale; at the frozen config that is the incumbent's flat $100,000 per
closed round trip). Curve requests carry ``{"offline": True}`` — the offline
store discipline; callers run under ``ARBS_SUPABASE_ENABLED=0``.

The caller controls ``dates`` (the TimeGrid): every grid day costs a curve
fetch whether or not the book holds anything, so pass held-window days only
when the book is flat between episodes (sv_h13 rationale, trap k).
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CURVE",
    "REQUIRED_COLUMNS",
    "KinkHarvestConfig",
    "HarvestEpisode",
    "episodes_from_panel",
    "build_backtest",
    "run_backtest",
    "sign_probe",
]

CURVE = "USD-SOFR-1D"

#: Exact gate columns the panel must carry (books.py naming).
REQUIRED_COLUMNS: Tuple[str, ...] = ("be_over_rv", "zs", "rac_net")

# "20Yx10Y" (strat3) | "20y10y" / "10y" (CurveFlyScreener cache form).
_STRAT3_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*Y\s*X\s*(\d+(?:\.\d+)?)\s*Y$", re.IGNORECASE)
_CFS_LABEL = re.compile(r"^(?:(\d+(?:\.\d+)?)y)?(\d+(?:\.\d+)?)y$")


def _parse_leg_label(label: str) -> Tuple[float, float]:
    """``"10y10y"`` | ``"20Yx10Y"`` | ``"10y"`` -> (fwd, tenor) years; loud otherwise."""
    s = str(label).strip()
    m = _STRAT3_LABEL.match(s) or _CFS_LABEL.match(s.lower())
    if m is None:
        raise ValueError(
            f"unparseable leg label {label!r}: expected '20Yx10Y', '20y10y' or '10y'")
    fwd = float(m.group(1)) if m.group(1) is not None else 0.0
    tenor = float(m.group(2))
    if not (math.isfinite(fwd) and math.isfinite(tenor)) or fwd < 0.0 or tenor <= 0.0:
        raise ValueError(f"leg label {label!r} has illegal coordinates ({fwd}, {tenor})")
    return fwd, tenor


def _parse_pair(pair: str) -> Tuple[str, str]:
    """``"10y10y/15y10y"`` -> (front_label, back_label); both legs must parse."""
    parts = [p.strip() for p in str(pair).split("/")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"pair {pair!r} must be 'front/back' with exactly two legs")
    for p in parts:
        _parse_leg_label(p)
    return parts[0], parts[1]


@dataclass(frozen=True)
class KinkHarvestConfig:
    """Frozen reference config (DESIGN §6 'Kink harvest'; costs per the task).

    ``start``/``end`` default to the leg-history span (2019-01-02..2026-08-25)
    so the field order of the spec survives dataclass default rules; override
    per run. ``half_spread_bp`` is ONE-WAY bp of rate per leg (0.25 = 0.5bp
    round trip per leg, the rac_backtest convention).
    """

    pairs: Tuple[str, ...] = ("10y10y/15y10y", "10y10y/20y10y", "15y5y/20y10y")
    min_be_over_rv: float = 1.17
    max_z: float = 0.5
    min_rac_net: float = 0.0
    reform: str = "M"
    package_dv01_usd: float = 100_000.0
    half_spread_bp: float = 0.25
    start: dt.date = dt.date(2019, 1, 2)
    end: dt.date = dt.date(2026, 8, 25)


class HarvestEpisode(NamedTuple):
    """One held pair: ``(pair, entry_date, exit_date)`` — unpackable as the spec tuple."""

    pair: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp


def _validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel.index, pd.MultiIndex) or panel.index.nlevels != 2:
        raise ValueError("panel must be indexed by a 2-level MultiIndex (date, pair)")
    if list(panel.index.names) != ["date", "pair"]:
        raise ValueError(
            f"panel index levels must be named ('date', 'pair'), got {list(panel.index.names)}")
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise KeyError(f"panel is missing required columns {missing}; needs {list(REQUIRED_COLUMNS)}")
    if panel.index.duplicated().any():
        dups = panel.index[panel.index.duplicated()][:3].tolist()
        raise ValueError(f"panel has duplicate (date, pair) rows, e.g. {dups}")
    return panel.sort_index()


def _gates_pass(row: Optional[dict], cfg: KinkHarvestConfig) -> bool:
    """The three harvest gates; NaN or a missing row REFUSES (never a silent pass).

    Inclusivities are the books.py contract: be_over_rv INCLUSIVE >=,
    zs INCLUSIVE <=, rac_net STRICT >.
    """
    if row is None:
        return False
    be, z, rac = row.get("be_over_rv"), row.get("zs"), row.get("rac_net")
    if pd.isna(be) or pd.isna(z) or pd.isna(rac):
        return False
    return (float(be) >= cfg.min_be_over_rv
            and float(z) <= cfg.max_z
            and float(rac) > cfg.min_rac_net)


def episodes_from_panel(panel: pd.DataFrame, cfg: KinkHarvestConfig) -> List[HarvestEpisode]:
    """Collapse the screen panel into held episodes under monthly reform.

    See the module docstring for the reform/lag-1 conventions. Raises loudly
    on a malformed panel, a configured pair absent from the panel entirely, or
    an empty [start, end] window — an empty book must be a data statement
    (gates refused), never a silent configuration accident.
    """
    panel = _validate_panel(panel)
    for pair in cfg.pairs:
        _parse_pair(pair)

    dates_all = panel.index.get_level_values("date").unique().sort_values()
    pairs_present = set(panel.index.get_level_values("pair"))
    absent = [p for p in cfg.pairs if p not in pairs_present]
    if absent:
        raise ValueError(
            f"configured pairs {absent} never appear in the panel — config/screen mismatch")

    start_ts, end_ts = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if end_ts < start_ts:
        raise ValueError(f"cfg.end {cfg.end} is before cfg.start {cfg.start}")
    dates_in = [d for d in dates_all if start_ts <= d <= end_ts]
    if not dates_in:
        raise ValueError(
            f"no panel dates inside [{cfg.start}, {cfg.end}] — window/panel mismatch")

    # Reform dates: first in-range panel date of each cfg.reform period.
    periods = [pd.Period(d, freq=cfg.reform) for d in dates_in]
    reform_dates = [d for i, d in enumerate(dates_in)
                    if i == 0 or periods[i] != periods[i - 1]]
    last_date = dates_in[-1]

    pos_of = {d: i for i, d in enumerate(dates_all)}
    rows = panel[list(REQUIRED_COLUMNS)].to_dict("index")

    episodes: List[HarvestEpisode] = []
    for pair in cfg.pairs:
        entry: Optional[pd.Timestamp] = None
        for r in reform_dates:
            i = pos_of[r]
            sig_date = dates_all[i - 1] if i >= 1 else None  # t-1: the LAG-1 row
            row = rows.get((sig_date, pair)) if sig_date is not None else None
            ok = _gates_pass(row, cfg)
            if entry is None:
                if ok and r != last_date:  # no time to hold an entry at the final date
                    entry = r
            elif not ok:
                episodes.append(HarvestEpisode(pair, entry, r))
                entry = None
        if entry is not None:
            episodes.append(HarvestEpisode(pair, entry, last_date))
    return episodes


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def _pricer_for(mdp: Any, as_of: dt.date) -> Any:
    """One curve for one date through the PUBLIC MDP surface, offline always."""
    return mdp.get_pricer({"curve_name": CURVE, "timestamp": as_of, "offline": True})


def _fwd_arg(fwd: float) -> str:
    """Spot legs go through the backend's settlement-day path, not '0Y'."""
    return "0D" if fwd == 0.0 else f"{fwd:g}Y"


def sign_probe(mdp: Any, as_of: dt.date, *, leg: str = "10y10y",
               package_dv01_usd: float = 100_000.0) -> dict:
    """Re-derive the direction convention from the engine (the L-0012 seam).

    Resolves the SAME leg as ``bpv = +dv01`` and ``bpv = -dv01`` OUTRIGHTs
    through ``resolve_package`` + ``resolve_pricable`` (exactly the marking
    path) and reads PV01. The convention this book relies on: ``+bpv`` is the
    PAYER, so ``pay_pv01 > 0 > receive_pv01`` and the two mirror to ~0. A
    direction-blind ``resolve_pricable`` regression prices both sides
    identically — then the sum is ~2x one side and ``is_payer_convention`` is
    False. ``run_backtest`` raises on that.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    as_of = pd.Timestamp(as_of).date()
    pricer = _pricer_for(mdp, as_of)
    fwd, tenor = _parse_leg_label(leg)
    swap = pricer.build_irswap(fwd=_fwd_arg(fwd), tenor=f"{tenor:g}Y", notional=1.0)
    eff = pd.Timestamp(pricer.effective_date(swap)).date()
    mat = pd.Timestamp(pricer.maturity_date(swap)).date()

    out = {}
    for name, bpv in (("pay_pv01", +abs(package_dv01_usd)),
                      ("receive_pv01", -abs(package_dv01_usd))):
        q = IRSwapQuery(curve=CURVE, structure=IRSwapStructure.OUTRIGHT,
                        value=IRSwapValue.NPV, effective_date=eff, maturity_date=mat,
                        structure_kwargs={"bpv": float(bpv)},
                        market_request={"offline": True})
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        resolved = [pricer.resolve_pricable(p, risk_weight=w)
                    for p, w in zip(package, weights)]
        out[name] = float(sum(float(pricer.pv01(s)) for s in resolved))

    total = out["pay_pv01"] + out["receive_pv01"]
    scale = max(1.0, abs(out["pay_pv01"]))
    ok = (out["pay_pv01"] > 0.0 > out["receive_pv01"]) and abs(total) < 1e-6 * scale
    return {**out, "sum": total, "leg": leg, "as_of": as_of, "is_payer_convention": ok}


def build_backtest(episodes: Sequence[HarvestEpisode], dates: Sequence[Any],
                   mdp: Any = None, *, cfg: KinkHarvestConfig,
                   show_progress: bool = False) -> Any:
    """Episodes -> one ``QueryDrivenBacktest`` (NOT yet run).

    Per episode: two OUTRIGHT legs, STEEPENER (receive front ``-dv01``, pay
    back ``+dv01`` — short convexity, the harvest side), explicit
    effective/maturity resolved on the entry date's offline curve, one unique
    tag per episode, unwind fee ``2*2*half_spread_bp*package_dv01_usd``.
    Raises on an empty episode list and on any episode date missing from
    ``dates`` (a DateTrigger off the grid never fires and the run reports a
    flat zero book that looks 'completed').
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    if not episodes:
        raise ValueError("no episodes — a planning failure, not a flat result")
    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")

    grid = [pd.Timestamp(d) for d in dates]
    if not grid:
        raise ValueError("empty time grid")
    grid_days = {t.date() for t in grid}

    #: 2 legs x 2 sides of the one-way half spread, in bp of rate on the
    #: package DV01; USD because dv01 is USD-per-bp (no /1e4).
    fee = 2.0 * 2.0 * float(cfg.half_spread_bp) * float(cfg.package_dv01_usd)

    triggers = []
    for k, e in enumerate(episodes):
        entry_d = pd.Timestamp(e.entry_date).date()
        exit_d = pd.Timestamp(e.exit_date).date()
        if entry_d not in grid_days or exit_d not in grid_days:
            raise ValueError(
                f"episode {k} ({e.pair}) dates {entry_d}..{exit_d} not on the time grid — "
                "its DateTriggers would silently never fire")
        if not entry_d < exit_d:
            raise ValueError(f"episode {k} ({e.pair}) entry {entry_d} !< exit {exit_d}")

        front_label, back_label = _parse_pair(e.pair)
        tag = f"kh{k}"
        pricer = _pricer_for(mdp, entry_d)
        actions = []
        # STEEPENER = short convexity = the harvest side: receive front, pay back.
        for leg_label, leg_sign in ((front_label, -1.0), (back_label, +1.0)):
            fwd, tenor = _parse_leg_label(leg_label)
            swap = pricer.build_irswap(fwd=_fwd_arg(fwd), tenor=f"{tenor:g}Y", notional=1.0)
            q = IRSwapQuery(
                curve=CURVE, structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                effective_date=pd.Timestamp(pricer.effective_date(swap)).date(),
                maturity_date=pd.Timestamp(pricer.maturity_date(swap)).date(),
                structure_kwargs={"bpv": float(leg_sign * abs(cfg.package_dv01_usd))},
                market_request={"offline": True},
                tags=(tag,),
            )
            actions.append(AddQueryAction(
                query=q, meta={"tags": [tag, "kink_harvest", e.pair, leg_label]}))
        # datetime.date, NEVER pd.Timestamp (silent no-op — module docstring).
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[entry_d]),
                                    actions=actions))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[exit_d]),
                                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    strat = QueryStrategy(name="cvx_kink_harvest", triggers=triggers)
    return QueryDrivenBacktest(time_grid=TimeGrid(grid), strategy=strat, mdp=mdp,
                               show_progress=show_progress,
                               progress_desc="cvx_kink_harvest (QDB)")


def run_backtest(episodes: Sequence[HarvestEpisode], dates: Sequence[Any],
                 mdp: Any = None, *, cfg: KinkHarvestConfig, probe: bool = True,
                 show_progress: bool = False) -> Tuple[Any, pd.Series]:
    """Build, probe, run, assert. Returns ``(bt, equity)``; equity is the
    engine's CUMULATIVE total P&L per grid state (not equity vs capital).

    ``probe=True`` runs :func:`sign_probe` on the first episode's entry date
    and raises if the engine does not exhibit the ±bpv payer mirror. After the
    run the rac_backtest ``assert_ran`` battery runs (non-empty, full grid
    coverage, finite, not identically zero) — ``QueryDrivenBacktest.run()``
    swallows per-step exceptions, so the artifacts are the only evidence.
    """
    from RVUtils.ConvexityRV.rac_backtest import assert_ran

    bt = build_backtest(episodes, dates, mdp, cfg=cfg, show_progress=show_progress)
    if probe:
        first_leg = _parse_pair(episodes[0].pair)[0]
        pr = sign_probe(bt.mdp, pd.Timestamp(episodes[0].entry_date).date(),
                        leg=first_leg, package_dv01_usd=cfg.package_dv01_usd)
        if not pr["is_payer_convention"]:
            raise AssertionError(
                f"sign probe failed — the engine does not show the +bpv-payer mirror: {pr}")
    bt.run()
    assert_ran(bt, expect_days=len(list(dates)), n_episodes=len(episodes))
    eq = pd.Series(bt.mtm_history)
    if not np.isfinite(eq.to_numpy(dtype=float)).all():
        raise AssertionError("non-finite marks in mtm_history")
    return bt, eq
