r"""W3 dislocation book — PCA-neutral fly fades of extreme, sign-agreeing kinks.

Signal-panel-driven (the ``BT/signals/ustf_basis.py`` library shape): this
module takes a PRECOMPUTED kink-screen panel and turns it into episodes and a
``QueryDrivenBacktest``. It never computes screens internally — residuals,
z-scores, tags, edge and the PCA-neutral weights are the SCREEN's output
(``RVUtils.CvxSuite``); the engine owns marks, portfolio and realized P&L.

Panel contract (binding)
------------------------
``episodes_from_panel`` takes a DataFrame indexed by a two-level MultiIndex
named exactly ``("date", "point")`` — ``date`` ascending ``pd.Timestamp``-like,
``point`` the grid-point label (e.g. ``"5y1y"``) — with columns (extra columns
are ignored):

Gate columns (NaN in any REFUSES the entry — citi_rule semantics, exactly
``RVUtils.CvxSuite.books``):

* ``zs``         — z-score of the screen's COMPOSED MICRO-FLY level on the
  belly=+2 ruler ``L = 2b - f - k`` (DESIGN §6a item 1: ONE fly ruler
  suite-wide; the as-of screen runs it on convexity-adjusted legs, the
  historical panel's raw-quoted default is a stated approximation).
  POLARITY, pinned in RATE space: positive = the fly level is HIGH vs its
  own trailing window = the belly RATE is high vs the wings = the belly is
  CHEAP (an upward kink). Gate two-sided INCLUSIVE: ``abs(zs) >=
  cfg.min_abs_z``.
* ``sign_agree`` — {+1, -1, 0} from ``residuals.sign_agreement``; entry
  needs agreement WITH THE FADE: ``sign_agree == sign(zs)`` (§6a item 4 —
  +1 both-residuals-cheap confirms fading a CHEAP belly at zs > 0, -1
  both-rich confirms fading a RICH belly at zs < 0). 0, NaN, and residuals
  agreeing with each other AGAINST the traded direction all refuse. The
  pre-amendment gate checked only that the two residual methods agreed with
  EACH OTHER; 2 of the 23 frozen-config episodes had entered against both
  cross-sectional models — "sign-agreeing" now means what it says.
* ``tag``        — ``grids.classify_point`` string; entry needs exactly
  ``"clean"`` (no meeting-zone, no convexity-zone fades).
* ``edge_bp``    — the §6a SHARED EDGE FORMULA at the frozen book's own
  clock ``h = max_hold_bd = 63``: ``E[reversion]*P(hit<=h) -
  |carry_bp_day|*min(E[FPT], h) - cost``, ALREADY NET OF 1x COST, bp of the
  belly=+2 L. Gate STRICT: ``> cfg.min_edge_bp``.

Sizing columns, FROZEN AT ENTRY from the signal row (the screen computes
them; this module never re-derives or re-normalises weights):

* ``leg_front`` / ``leg_belly`` / ``leg_back`` — lowercase CurveFlyScreener
  leg labels of the fly around the point.
* ``w_front`` / ``w_belly`` / ``w_back`` — PCA-neutral DV01 weights per 1.0
  of ``cfg.package_dv01_usd``, in the LONG-THE-FLY orientation: ``w_belly >
  0``, wings ``< 0``. These are DOLLAR leg weights — per-leg DV01 fractions
  of the package dv01 (leg i trades ``bpv_i = direction * w_i * dv01``) —
  NOT the rate-space ``(-1, +2, -1)`` that defines the belly=+2 level L the
  gates run on: the panel's constant ``(-0.5, +1, -0.5) x dv01`` package
  pays ``dv01/2`` USD per bp of that L (the fee derivation below). NaN in
  any sizing field refuses the entry (a PCA ramp-in month legitimately has
  no weights); a WRONG SIGN PATTERN on a gate-passing row RAISES — an
  inverted orientation would silently flip the whole book through
  ``direction * w``.

Direction (the pinned rate-space polarity, kink_ledger.md section 0)
--------------------------------------------------------------------
``zs`` positive = the fly level is HIGH = the belly RATE is high vs the wings
= the belly is CHEAP (an upward kink). The fade RECEIVES the belly (receive
belly / pay wings) = SHORT local convexity — the side that collects the rent
while positioned for the reversion (kink_ledger.md section 0: "receive an
upward kink ... = short local convexity => you collect the rent"). ``zs``
negative = the fly level is LOW = belly RICH (a downward kink) -> the fade
PAYS the belly = LONG local convexity, paying rent to hold the fade. So
``direction = -1 (receive belly) if entry zs > 0 else +1 (pay belly)``, and
each leg trades ``bpv_i = direction * w_i * cfg.package_dv01_usd`` (``+bpv``
is a PAYER through this engine — rac_backtest convention, re-derived from the
engine by :func:`sign_probe` on every ``run_backtest``). The PRE-FIX mapping
(``+1 pay belly on zs > 0``) was BACKWARDS — it paid rent to fade what the
rent framework says to collect on; fixed 2026-08-26 with the fly-level zs.

Timing (deliberate conventions)
-------------------------------
Entries are LAG-1: the gate row is the panel date immediately BEFORE the fill
date in the FULL panel index (signal on day i fills day i+1; ``entry_zs``,
legs and weights all freeze from that signal row). Exits are evaluated on the
exit day's OWN row and fill at that same mark — the famb Book-A convention.
Exit rules, checked in PRECEDENCE order stop > target > horizon (the reason
label of a day where several fire is the first in that order):

* ``"stop"``    — ``abs(zs_now) >= abs(entry_zs) * cfg.exit_z_mult``
  (INCLUSIVE; the task's multiplicative form of DESIGN §6's "+2SD" exit).
* ``"target"``  — zero-cross: ``zs_now == 0`` or ``sign(zs_now) !=
  sign(entry_zs)``.
* ``"horizon"`` — held ``>= cfg.max_hold_bd`` grid positions since entry.
* ``"end"``     — the panel window ended while held (forced unwind).

A NaN/missing ``zs`` during the hold evaluates NO stop/target that day (you
cannot act on a mark you do not have) — the horizon clock still runs, and the
horizon/end exits are the fail-safes. One position per point; re-entry after
an exit is allowed from the next day's decision on.

Costs
-----
``fee_usd = cfg.cost_rt_bp * (cfg.package_dv01_usd / 2)`` booked once at
unwind (the engine's only cost hook), split by the engine equally across the
three legs. ``cost_rt_bp`` is the ALL-IN round trip for the 3-leg package in
bp OF THE BELLY=+2 FLY LEVEL ``L = 2b - f - k`` (DESIGN §6's 2.0-2.6bp RT
band, 2.3 the frozen mid; §6a item 1 pinned the ruler). The package pays
``dv01/2`` USD per bp of that L: legs trade ``(-0.5, +1, -0.5) x dv01`` of
DV01, so P&L = ``dv01 * (db - 0.5*df - 0.5*dk) = (dv01/2) * dL`` — hence
fee = ``cost_rt_bp x dv01/2`` ($57,500 at the frozen $50k config; the
pre-amendment ``cost_rt_bp x dv01`` charged the band on a belly=+1 ruler
the rest of the suite does not use, double-charging every per-leg anchor).
bp times USD-per-bp is USD, so there is NO further /1e4: dv01 already
carries the dollar scale (the rac_backtest convention).

Engine construction mirrors ``rac_backtest``/``cvx_kink_harvest``: three
OUTRIGHT legs with EXPLICIT effective/maturity resolved on the entry date's
offline curve (a relative tenor never ages), per-episode tags, trigger dates
as plain ``datetime.date`` (a pd.Timestamp is a silent no-op), offline curve
requests, and the assert_ran battery after every run. The caller controls
``dates``: grid days cost a curve fetch each, so pass held-window days only
when the book is flat between episodes (sv_h13 rationale).
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
    "GATE_COLUMNS",
    "SIZING_COLUMNS",
    "REQUIRED_COLUMNS",
    "TAG_CLEAN",
    "FlyDislocationConfig",
    "FlyEpisode",
    "episodes_from_panel",
    "build_backtest",
    "run_backtest",
    "sign_probe",
]

CURVE = "USD-SOFR-1D"
TAG_CLEAN = "clean"

GATE_COLUMNS: Tuple[str, ...] = ("zs", "sign_agree", "tag", "edge_bp")
SIZING_COLUMNS: Tuple[str, ...] = ("leg_front", "leg_belly", "leg_back",
                                   "w_front", "w_belly", "w_back")
REQUIRED_COLUMNS: Tuple[str, ...] = GATE_COLUMNS + SIZING_COLUMNS

_STRAT3_LABEL = re.compile(r"^(\d+(?:\.\d+)?)\s*Y\s*X\s*(\d+(?:\.\d+)?)\s*Y$", re.IGNORECASE)
_CFS_LABEL = re.compile(r"^(?:(\d+(?:\.\d+)?)y)?(\d+(?:\.\d+)?)y$")


def _parse_leg_label(label: str) -> Tuple[float, float]:
    """``"5y1y"`` | ``"5Yx1Y"`` | ``"1y"`` -> (fwd, tenor) years; loud otherwise."""
    s = str(label).strip()
    m = _STRAT3_LABEL.match(s) or _CFS_LABEL.match(s.lower())
    if m is None:
        raise ValueError(
            f"unparseable leg label {label!r}: expected '5Yx1Y', '5y1y' or '1y'")
    fwd = float(m.group(1)) if m.group(1) is not None else 0.0
    tenor = float(m.group(2))
    if not (math.isfinite(fwd) and math.isfinite(tenor)) or fwd < 0.0 or tenor <= 0.0:
        raise ValueError(f"leg label {label!r} has illegal coordinates ({fwd}, {tenor})")
    return fwd, tenor


@dataclass(frozen=True)
class FlyDislocationConfig:
    """The ONE frozen dislocation config (DESIGN §6; costs per the task).

    ``start``/``end`` default to the leg-history span (2019-01-02..2026-08-25)
    to keep the spec's field order under dataclass default rules; override per
    run. ``max_hold_bd`` counts GRID positions (panel business days) held —
    it is also the §6a edge clock the panel prices at. ``cost_rt_bp`` is
    denominated on the belly=+2 fly level L = 2b - f - k (§6a item 1; the
    package pays dv01/2 USD per bp of L, module docstring "Costs").
    """

    min_abs_z: float = 2.0
    min_edge_bp: float = 1.0
    max_hold_bd: int = 63
    exit_z_mult: float = 2.0
    package_dv01_usd: float = 50_000.0
    cost_rt_bp: float = 2.3
    start: dt.date = dt.date(2019, 1, 2)
    end: dt.date = dt.date(2026, 8, 25)


class FlyEpisode(NamedTuple):
    """One held fly. ``direction``: -1 receive belly (fade a CHEAP belly,
    entry zs > 0 — collects rent), +1 pay belly (fade a RICH belly, zs < 0)."""

    point: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    direction: int
    leg_front: str
    leg_belly: str
    leg_back: str
    w_front: float
    w_belly: float
    w_back: float
    entry_zs: float
    exit_reason: str


def _validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel.index, pd.MultiIndex) or panel.index.nlevels != 2:
        raise ValueError("panel must be indexed by a 2-level MultiIndex (date, point)")
    if list(panel.index.names) != ["date", "point"]:
        raise ValueError(
            f"panel index levels must be named ('date', 'point'), got {list(panel.index.names)}")
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise KeyError(f"panel is missing required columns {missing}; needs {list(REQUIRED_COLUMNS)}")
    if panel.index.duplicated().any():
        dups = panel.index[panel.index.duplicated()][:3].tolist()
        raise ValueError(f"panel has duplicate (date, point) rows, e.g. {dups}")
    return panel.sort_index()


def _entry_signal(row: Optional[dict], cfg: FlyDislocationConfig,
                  key: Tuple[Any, str]) -> Optional[dict]:
    """Gate one signal row. None = refuse; dict = the frozen entry terms.

    NaN in any gate OR sizing column refuses (no signal / cannot size — the
    PCA ramp-in case). The residuals must agree WITH the fade: ``sign_agree
    == sign(zs)`` (§6a item 4). A gate-PASSING row whose weights carry the
    wrong sign pattern RAISES: that is an inverted-orientation screen defect
    which ``direction * w`` would silently turn into the opposite book.
    """
    if row is None:
        return None
    z, agree, tag, edge = (row.get("zs"), row.get("sign_agree"),
                           row.get("tag"), row.get("edge_bp"))
    if pd.isna(z) or pd.isna(agree) or tag is None or (isinstance(tag, float) and pd.isna(tag)) \
            or pd.isna(edge):
        return None
    if abs(float(z)) < cfg.min_abs_z:          # INCLUSIVE at min_abs_z
        return None
    if float(agree) not in (1.0, -1.0):        # 0 disagrees; anything else refuses
        return None
    # §6a item 4 DIRECTION GATE: the residual methods must agree WITH the
    # fade, not merely with each other — zs > 0 fades a CHEAP belly and needs
    # both-cheap (+1); zs < 0 needs both-rich (-1). MUTATION: dropping this
    # check re-admits entries positioned against BOTH cross-sectional models
    # (2 of the 23 pre-amendment frozen-config episodes were).
    if float(agree) != (1.0 if float(z) > 0 else -1.0):
        return None
    if str(tag) != TAG_CLEAN:
        return None
    if not float(edge) > cfg.min_edge_bp:      # STRICT floor
        return None

    legs = [row.get(c) for c in ("leg_front", "leg_belly", "leg_back")]
    ws = [row.get(c) for c in ("w_front", "w_belly", "w_back")]
    if any(l is None or (isinstance(l, float) and pd.isna(l)) or str(l).strip() == ""
           for l in legs):
        return None
    if any(pd.isna(w) or not math.isfinite(float(w)) for w in ws):
        return None
    w_front, w_belly, w_back = (float(w) for w in ws)
    if not (w_belly > 0.0 and w_front < 0.0 and w_back < 0.0):
        raise ValueError(
            f"signal row {key} passes the gates but its weights "
            f"(w_front={w_front}, w_belly={w_belly}, w_back={w_back}) violate the "
            "long-the-fly orientation (belly > 0, wings < 0) — an inverted screen "
            "orientation would silently flip the book")
    return {
        # zs > 0 = fly HIGH = belly CHEAP -> RECEIVE the belly (collect rent);
        # zs < 0 = belly RICH -> PAY the belly. The pre-fix +sign(zs) mapping
        # was backwards (module docstring, Direction).
        "direction": -1 if float(z) > 0 else +1,
        "entry_zs": float(z),
        "leg_front": str(legs[0]), "leg_belly": str(legs[1]), "leg_back": str(legs[2]),
        "w_front": w_front, "w_belly": w_belly, "w_back": w_back,
    }


def episodes_from_panel(panel: pd.DataFrame, cfg: FlyDislocationConfig) -> List[FlyEpisode]:
    """Collapse the screen panel into held fly episodes.

    Timing, gates, direction and exits per the module docstring. Raises loudly
    on a malformed panel or an empty [start, end] window.
    """
    panel = _validate_panel(panel)
    if int(cfg.max_hold_bd) < 1:
        raise ValueError(f"max_hold_bd must be >= 1, got {cfg.max_hold_bd}")
    if not float(cfg.exit_z_mult) > 1.0:
        raise ValueError(
            f"exit_z_mult must be > 1.0 (a stop at or inside the entry z closes "
            f"instantly), got {cfg.exit_z_mult}")

    dates_all = panel.index.get_level_values("date").unique().sort_values()
    start_ts, end_ts = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if end_ts < start_ts:
        raise ValueError(f"cfg.end {cfg.end} is before cfg.start {cfg.start}")
    dates_in = [d for d in dates_all if start_ts <= d <= end_ts]
    if not dates_in:
        raise ValueError(
            f"no panel dates inside [{cfg.start}, {cfg.end}] — window/panel mismatch")

    pos_of = {d: i for i, d in enumerate(dates_all)}
    rows = panel[list(REQUIRED_COLUMNS)].to_dict("index")
    points = list(dict.fromkeys(panel.index.get_level_values("point")))
    last_date = dates_in[-1]

    episodes: List[FlyEpisode] = []
    for point in points:
        entry_j: Optional[int] = None
        terms: Optional[dict] = None
        for j, d in enumerate(dates_in):
            if entry_j is None:
                if d == last_date:
                    continue  # no time to hold an entry at the final date
                i = pos_of[d]
                sig_date = dates_all[i - 1] if i >= 1 else None  # LAG-1 row
                terms_new = _entry_signal(
                    rows.get((sig_date, point)) if sig_date is not None else None,
                    cfg, (sig_date, point))
                if terms_new is not None:
                    entry_j, terms = j, terms_new
                continue

            held = j - entry_j
            row_now = rows.get((d, point))
            zs_now = row_now.get("zs") if row_now is not None else None
            reason: Optional[str] = None
            if zs_now is not None and not pd.isna(zs_now):
                z_now, z0 = float(zs_now), float(terms["entry_zs"])
                if abs(z_now) >= abs(z0) * float(cfg.exit_z_mult):
                    reason = "stop"       # precedence: stop > target > horizon
                elif z_now == 0.0 or (z_now > 0) != (z0 > 0):
                    reason = "target"
            if reason is None and held >= int(cfg.max_hold_bd):
                reason = "horizon"
            if reason is None and d == last_date:
                reason = "end"
            if reason is not None:
                episodes.append(FlyEpisode(
                    point=point, entry_date=dates_in[entry_j], exit_date=d,
                    direction=int(terms["direction"]),
                    leg_front=terms["leg_front"], leg_belly=terms["leg_belly"],
                    leg_back=terms["leg_back"], w_front=terms["w_front"],
                    w_belly=terms["w_belly"], w_back=terms["w_back"],
                    entry_zs=terms["entry_zs"], exit_reason=reason))
                entry_j, terms = None, None
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


def sign_probe(mdp: Any, as_of: dt.date, *, leg: str = "5y1y",
               package_dv01_usd: float = 50_000.0) -> dict:
    """Re-derive the direction convention from the engine (the L-0012 seam).

    Same probe as ``cvx_kink_harvest.sign_probe``: the SAME leg resolved as
    ``+bpv`` and ``-bpv`` OUTRIGHTs through the marking path must show
    ``pay_pv01 > 0 > receive_pv01`` with the two mirroring to ~0. A
    direction-blind ``resolve_pricable`` prices both sides identically and
    fails the mirror; ``run_backtest`` raises on that.
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


def build_backtest(episodes: Sequence[FlyEpisode], dates: Sequence[Any],
                   mdp: Any = None, *, cfg: FlyDislocationConfig,
                   show_progress: bool = False) -> Any:
    """Episodes -> one ``QueryDrivenBacktest`` (NOT yet run).

    Per episode: three OUTRIGHT legs at ``bpv_i = direction * w_i *
    package_dv01_usd`` with explicit effective/maturity resolved on the entry
    date's offline curve, one unique tag per episode, unwind fee
    ``cost_rt_bp * package_dv01_usd / 2`` (bp of the belly=+2 L times the
    package's USD-per-bp-of-L — module docstring "Costs"). Raises on an
    empty episode list, on
    any episode date missing from ``dates`` (an off-grid DateTrigger silently
    never fires), on a direction outside {+1,-1} and on a weight sign pattern
    violating the long-the-fly orientation (belly > 0, wings < 0) — a zero
    weight would otherwise reach the backend's ``bpv=0`` falsy branch and
    build a silent 1mm-notional default leg.
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

    #: cost_rt_bp is bp of the belly=+2 fly level L = 2b - f - k (§6a item 1);
    #: the (-0.5, +1, -0.5) x dv01 package pays dv01/2 USD per bp of L, so the
    #: USD round trip is cost_rt_bp x dv01/2 — $57,500 at the frozen $50k
    #: config (no /1e4: dv01 already carries the dollar scale, the
    #: rac_backtest convention).
    fee = float(cfg.cost_rt_bp) * float(cfg.package_dv01_usd) / 2.0

    triggers = []
    for k, e in enumerate(episodes):
        entry_d = pd.Timestamp(e.entry_date).date()
        exit_d = pd.Timestamp(e.exit_date).date()
        if entry_d not in grid_days or exit_d not in grid_days:
            raise ValueError(
                f"episode {k} ({e.point}) dates {entry_d}..{exit_d} not on the time grid — "
                "its DateTriggers would silently never fire")
        if not entry_d < exit_d:
            raise ValueError(f"episode {k} ({e.point}) entry {entry_d} !< exit {exit_d}")
        if int(e.direction) not in (1, -1):
            raise ValueError(f"episode {k} ({e.point}) direction must be +1/-1, got {e.direction}")
        if not (float(e.w_belly) > 0.0 and float(e.w_front) < 0.0 and float(e.w_back) < 0.0):
            raise ValueError(
                f"episode {k} ({e.point}) weights ({e.w_front}, {e.w_belly}, {e.w_back}) "
                "violate the long-the-fly orientation (belly > 0, wings < 0)")

        tag = f"fd{k}"
        pricer = _pricer_for(mdp, entry_d)
        actions = []
        for leg_label, w in ((e.leg_front, float(e.w_front)),
                             (e.leg_belly, float(e.w_belly)),
                             (e.leg_back, float(e.w_back))):
            fwd, tenor = _parse_leg_label(leg_label)
            swap = pricer.build_irswap(fwd=_fwd_arg(fwd), tenor=f"{tenor:g}Y", notional=1.0)
            q = IRSwapQuery(
                curve=CURVE, structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                effective_date=pd.Timestamp(pricer.effective_date(swap)).date(),
                maturity_date=pd.Timestamp(pricer.maturity_date(swap)).date(),
                structure_kwargs={"bpv": float(int(e.direction) * w * abs(cfg.package_dv01_usd))},
                market_request={"offline": True},
                tags=(tag,),
            )
            actions.append(AddQueryAction(
                query=q, meta={"tags": [tag, "fly_dislocation", e.point, leg_label],
                               "entry_zs": float(e.entry_zs),
                               "exit_reason": str(e.exit_reason)}))
        # datetime.date, NEVER pd.Timestamp (silent no-op — module docstring).
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[entry_d]),
                                    actions=actions))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[exit_d]),
                                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    strat = QueryStrategy(name="cvx_fly_dislocation", triggers=triggers)
    return QueryDrivenBacktest(time_grid=TimeGrid(grid), strategy=strat, mdp=mdp,
                               show_progress=show_progress,
                               progress_desc="cvx_fly_dislocation (QDB)")


def run_backtest(episodes: Sequence[FlyEpisode], dates: Sequence[Any],
                 mdp: Any = None, *, cfg: FlyDislocationConfig, probe: bool = True,
                 show_progress: bool = False) -> Tuple[Any, pd.Series]:
    """Build, probe, run, assert. Returns ``(bt, equity)``; equity is the
    engine's CUMULATIVE total P&L per grid state (not equity vs capital).

    ``probe=True`` runs :func:`sign_probe` on the first episode's belly leg
    at its entry date and raises if the engine does not exhibit the ±bpv
    payer mirror. After the run the rac_backtest ``assert_ran`` battery runs
    (non-empty, full grid coverage, finite, not identically zero) PLUS the
    closed-position count check ``closed == 3 * len(episodes)`` (§6a item 6,
    the strikeless ``expect_closed`` battery pattern — the engine books NO
    fee on a no-match unwind and the rac battery alone cannot see that) —
    ``QueryDrivenBacktest.run()`` swallows per-step exceptions, so the
    artifacts are the only evidence.
    """
    from RVUtils.ConvexityRV.rac_backtest import assert_ran

    bt = build_backtest(episodes, dates, mdp, cfg=cfg, show_progress=show_progress)
    if probe:
        pr = sign_probe(bt.mdp, pd.Timestamp(episodes[0].entry_date).date(),
                        leg=episodes[0].leg_belly,
                        package_dv01_usd=cfg.package_dv01_usd)
        if not pr["is_payer_convention"]:
            raise AssertionError(
                f"sign probe failed — the engine does not show the +bpv-payer mirror: {pr}")
    bt.run()
    assert_ran(bt, expect_days=len(list(dates)), n_episodes=len(episodes))
    # §6a item 6: every episode is 3 legs opened and 3 closed. A no-match
    # unwind silently drops BOTH the close and its fee (query_engine returns
    # before reading the fee), leaving open positions accruing unrealized
    # P&L — the flattering direction. MUTATION: removing this check lets the
    # ghost-tag test run to a green finish with zero closes and no fee.
    closed = getattr(getattr(bt, "portfolio", None), "closed_positions_log", []) or []
    n_expect = 3 * len(episodes)
    if len(closed) != n_expect:
        raise AssertionError(
            f"closed {len(closed)} positions, expected {n_expect} (3 legs x "
            f"{len(episodes)} episodes) — an unwind missed its tag or an add "
            "never filled, and the engine books no fee on a no-match unwind.")
    eq = pd.Series(bt.mtm_history)
    if not np.isfinite(eq.to_numpy(dtype=float)).all():
        raise AssertionError("non-finite marks in mtm_history")
    return bt, eq
