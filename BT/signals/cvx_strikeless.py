r"""W1 strikeless-vol reference strategy — replay strat3's hedge tape through QDB.

The strategy itself lives in ``RVUtils.ConvexityRV.strat3_strikeless_vol``: a
long-convexity forward-curve flattener (pay the short-dated forward, receive the
long-dated one, DV01-neutral), delta-hedged at each ``hedge_threshold_bp`` move
in the longer forward rate and rolled every ``roll_months``. That module's
``hedge_schedule(curve_map, cfg)`` emits the EXACT trade tape the rule produces
(initiate / hedge / roll / unwind, one row per traded event, with each leg's own
effective/maturity dates and signed ``bpv``). This module replays that tape
through ``QueryDrivenBacktest`` as dated triggers and certifies the engine
equity against the strat3 unit ledger for the same window.

Why explicit effective/maturity dates (the relative-tenor trap)
---------------------------------------------------------------
A query carrying a RELATIVE forward tenor ("15Yx5Y") is re-resolved against
every mark date: the engine then prices a fresh at-market package each day, its
NPV is ~0 by construction, and the position never ages — a flat equity curve
indistinguishable from "made no money" (``rac_backtest`` measured exactly that
on 1,470 dates before its assert battery caught it). Every leg here is an
``IRSwapStructure.OUTRIGHT`` with the tape's explicit dates, struck at par at
entry and FROZEN, so the position ages the way the panel's aged package does.

Sign convention (re-derived from the engine, never trusted from a label)
------------------------------------------------------------------------
``bpv > 0`` = PAYER. The flattener pays the short leg (+DV01) and receives the
long leg (−beta·DV01); ``bpv < 0`` on a CURVE package = flattener = long
convexity (docs/convexityrv/DESIGN.md §1 measured table). :func:`sign_probe`
re-derives this from ``resolve_pricable`` before any run — the seam regressed
once before (ledger L-0012: an ``abs()`` slip prices +bpv and −bpv as the
identical package) and no downstream statistic catches it.

Fees (the engine's only cost hook is ``UnwindPositionsAction.fee``)
-------------------------------------------------------------------
strat3's ledger charges, per Citi Figure 9 via ``cost_schedule_for``:
one-way initiation on day 0, one-way roll on each roll date, one-way hedge on
each resize, and NO terminal exit. QDB can only charge fees at unwinds (entry
fees do not exist; ``_handle_unwind`` drops the fee when nothing matches), so:

* the roll fee for the package that OPENS segment ``k+1`` rides segment ``k``'s
  unwind — the two share the roll date, so it books on the panel's exact date;
* the initiation fee and each segment's hedge fees ride that segment's unwind —
  a timing deferral (≤ one roll period), never a total change.

Total fees equal the strat3 schedule exactly: ``1×initiate + (S−1)×roll +
Σ hedge``. :func:`certify` compares GROSS (fees added back via
:func:`fee_events`), so the deferral cannot touch the certification.

Certification and the panel-is-not-P&L rule
-------------------------------------------
Both sides of :func:`certify` are engine-REPRICED P&L: the QDB marks frozen
packages via ``resolve_pricable`` NPVs, and the strat3 unit ledger reprices the
same aged packages through ``StrikelessVol.replication.CurvePricer``. Neither
side is a Δrate×DV01 par-panel approximation — a par panel is not a P&L model
(measured 1.5–6× Sharpe overstatement on hedged books), and certifying against
one would grade the engine on a number that is itself wrong. Because both sides
reprice the SAME trade tape on the SAME curves, corr ≥ 0.99 on daily gross P&L
is a fair bar (sv_h13 measured 0.9999 with this construction on this pair).
Residual daily gaps come from two named conventions: leg notionals sized off
analytic delta (``build_irswap(bpv=...)``) vs the panel's repriced
central-difference DV01, and hedge increments booked as separate at-market
swaps vs the panel resizing the original off-market swap (Citi Doc A l.140
names the at-market increment as the practical implementation).

Offline discipline: every query's ``market_request`` carries ``"offline": True``
(a store miss then raises instead of reaching Excel COM), and the reference run
serves marks from :class:`CurveMapMDP`, a closed dict of pre-fetched store-backed
pricers with no fetch path at all.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CurveMapMDP",
    "CvxStrikelessConfig",
    "CvxStrikelessResult",
    "EVENT_KINDS",
    "TAPE_COLUMNS",
    "assert_ran",
    "build_backtest",
    "build_curve_map",
    "build_tape",
    "certify",
    "fee_events",
    "run_reference",
    "sign_probe",
    "strat3_unit_ledger",
]

CURVE = "USD-SOFR-1D"

#: Columns ``strat3_strikeless_vol.hedge_schedule`` emits, in contract order.
TAPE_COLUMNS: Tuple[str, ...] = ("segment", "date", "kind", "leg", "bpv", "effective", "maturity")

#: Tape kinds that add risk (one ``AddQueryAction`` each). ``"unwind"`` closes a segment.
EVENT_KINDS: Tuple[str, ...] = ("initiate", "roll", "hedge")


def _is_plain_date(d: Any) -> bool:
    """True only for a ``datetime.date`` that is NOT a ``datetime``/``pd.Timestamp``.

    ``DateTriggerRequirements.has_triggered`` tests ``state.date() in set(dates)``
    and a ``pd.Timestamp`` never equals a ``date``, so a Timestamp in a trigger is
    a SILENT no-op: the run completes, the equity curve has no holes, and every
    mark is exactly zero. ``isinstance(d, datetime.date)`` alone would wave
    Timestamps through (Timestamp ⊂ datetime ⊂ date), which is the trap itself.
    """
    return isinstance(d, dt.date) and not isinstance(d, dt.datetime)


def _as_plain_date(d: Any) -> dt.date:
    if _is_plain_date(d):
        return d
    if isinstance(d, dt.datetime):
        return d.date()
    return pd.Timestamp(d).date()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CvxStrikelessConfig:
    """Frozen reference config (DESIGN §6: Strikeless W1).

    ``cost_multiplier`` scales the Figure-9 schedule served by
    ``strat3.cost_schedule_for`` (0.75/0.30 for the published tight pairs,
    1.00/0.40 for unpublished ones); pass ``costs`` to override the schedule
    entirely. ``entry_rule`` is deliberately absent: the tape is the always-on
    Figure-4 specification, gating belongs to ``strat3.entry_state``.
    """

    short_leg: str = "15Yx5Y"           # paid  (shorter-dated forward)
    long_leg: str = "20Yx10Y"           # received (longer-dated forward)
    curve_name: str = CURVE
    market: str = "USD"
    package_dv01_usd: float = 100_000.0
    hedge_threshold_bp: float = 25.0
    beta: float = 1.0
    resize_mode: str = "neutral"
    roll_months: int = 12
    cost_multiplier: float = 1.0
    #: Optional explicit ``StrikelessVol.costs.CostSchedule``; None -> Figure 9.
    costs: Optional[Any] = None
    start: dt.date = dt.date(2019, 1, 2)
    end: dt.date = dt.date(2026, 8, 14)
    corr_min: float = 0.99              # certification bar (DESIGN §5/§6)
    show_progress: bool = False

    def __post_init__(self):
        if not (np.isfinite(self.package_dv01_usd) and self.package_dv01_usd > 0):
            raise ValueError(f"package_dv01_usd must be finite and > 0, got {self.package_dv01_usd}")
        if not (np.isfinite(self.hedge_threshold_bp) and self.hedge_threshold_bp > 0):
            raise ValueError(f"hedge_threshold_bp must be finite and > 0, got {self.hedge_threshold_bp}")
        if int(self.roll_months) < 1:
            raise ValueError(f"roll_months must be >= 1, got {self.roll_months}")
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")

    @property
    def pair_name(self) -> str:
        return f"{self.short_leg}/{self.long_leg}"

    def cost_schedule(self):
        """The fee curve: explicit ``costs`` if given, else Figure 9 for the pair."""
        if self.costs is not None:
            return self.costs
        from RVUtils.ConvexityRV.strat3_strikeless_vol import cost_schedule_for

        return cost_schedule_for(self.short_leg, self.long_leg, multiplier=self.cost_multiplier)

    def to_strat3(self):
        """The ``Strat3Config`` the tape and unit ledger are built from."""
        from RVUtils.ConvexityRV.strat3_strikeless_vol import Strat3Config

        return Strat3Config(
            short_leg=self.short_leg,
            long_leg=self.long_leg,
            curve_name=self.curve_name,
            market=self.market,
            package_dv01_usd=float(self.package_dv01_usd),
            hedge_threshold_bp=float(self.hedge_threshold_bp),
            beta=float(self.beta),
            resize_mode=self.resize_mode,
            roll_months=int(self.roll_months),
            cost_multiplier=float(self.cost_multiplier),
            entry_rule="always",
            start=self.start,
            end=self.end,
        )


# ---------------------------------------------------------------------------
# Curve map + serving MDP
# ---------------------------------------------------------------------------


def build_curve_map(
    dates: Sequence[Any],
    *,
    curve_name: str = CURVE,
    mdp: Any = None,
    n_jobs: int = 1,
) -> Dict[dt.date, Any]:
    """Store-backed ``{date: RLIRSwapCurve}`` via one offline ``bulk_get_data``.

    * ``"offline": True`` in the request — a store miss RAISES inside the
      fetcher instead of reaching Excel COM; holidays/weekends are dropped by
      the bulk path's own calendar validation (omitted, not raised).
    * refuses any date >= today: ``bulk_get_data`` COERCES today to ``"live"``
      (IRSwapsMDP.py:3888), which routes to the live wire.
    * every served pricer must be store-backed (``meta()["from_curve_store"]``)
      and must price its own date (``reference_date`` match) — a quotes-rebuild
      fallback or a neighbouring-day serve raises rather than slipping in.
    """
    days = sorted({_as_plain_date(d) for d in dates})
    if not days:
        raise ValueError("build_curve_map: no dates requested")
    today = dt.date.today()
    bad = [d for d in days if d >= today]
    if bad:
        raise ValueError(
            f"build_curve_map: {len(bad)} date(s) >= today ({bad[0]}..): bulk_get_data "
            "coerces today to 'live' and routes to the live wire — never ask for today."
        )
    if mdp is None:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")

    raw = mdp.bulk_get_data(
        {
            "curve_name": curve_name,
            "timestamps": list(days),
            "offline": True,
            "n_jobs": int(n_jobs),
        }
    )

    out: Dict[dt.date, Any] = {}
    n_none = n_refdate = 0
    for ts, pricer in raw.items():
        d = _as_plain_date(ts)
        if pricer is None:
            n_none += 1
            continue
        ref = pricer.reference_date()
        ref_d = _as_plain_date(ref)
        if ref_d != d:
            n_refdate += 1
            continue
        meta = pricer.meta() if callable(getattr(pricer, "meta", None)) else {}
        if not (meta or {}).get("from_curve_store"):
            raise RuntimeError(
                f"build_curve_map: pricer for {d} is NOT store-backed "
                f"(meta={dict(meta or {})!r}). A quotes-rebuild fallback served it; "
                "warm the EOD store instead of accepting a non-store curve."
            )
        out[d] = pricer

    dropped = len(days) - len(out)
    if dropped:
        print(
            f"build_curve_map: {len(out)} curves kept of {len(days)} requested "
            f"({n_none} None, {n_refdate} reference-date mismatches, "
            f"{dropped - n_none - n_refdate} absent — holidays/unwarmed)",
            flush=True,
        )
    if not out:
        raise ValueError(
            f"build_curve_map: no curve served for any of {len(days)} dates "
            f"({days[0]}..{days[-1]}) — is the {curve_name} EOD store warmed?"
        )
    return dict(sorted(out.items()))


class CurveMapMDP:
    """Serve QDB pricer requests from a closed ``{date: pricer}`` map.

    The engine calls ``mdp.get_pricer(request)`` once per (query-signature,
    date); routing those through a real ``IRSwapsMDP`` re-reads the store per
    day, while the reference run already holds every pricer it is allowed to
    see. This wrapper has NO fetch path at all — a lookup miss raises — which
    is the strongest form of the offline discipline.
    """

    source = "CURVE_MAP"

    def __init__(self, curve_map: Mapping[Any, Any], *, curve_name: Optional[str] = None):
        if not curve_map:
            raise ValueError("CurveMapMDP: empty curve_map")
        self._curves: Dict[dt.date, Any] = {
            _as_plain_date(k): v for k, v in curve_map.items() if v is not None and k != "live"
        }
        self._days = sorted(self._curves)
        self.curve_name = curve_name

    def dates(self) -> List[dt.date]:
        return list(self._days)

    def _lookup(self, timestamp: Any) -> Any:
        d = _as_plain_date(timestamp)
        try:
            return self._curves[d]
        except KeyError:
            raise KeyError(
                f"CurveMapMDP: no curve for {d} (map covers {self._days[0]}..{self._days[-1]}, "
                f"{len(self._days)} days). The time grid must be the curve_map's own days."
            ) from None

    def get_pricer(self, request: Mapping[str, Any]) -> Any:
        return self._lookup(request["timestamp"])

    # get_data / _get_curve aliases so sign_probe and ad-hoc callers work.
    def get_data(self, request: Mapping[str, Any]) -> Any:
        return self._lookup(request["timestamp"])

    def _get_curve(self, *, curve_name: str = None, timestamp: Any = None, **_: Any) -> Any:
        return self._lookup(timestamp)


# ---------------------------------------------------------------------------
# Tape
# ---------------------------------------------------------------------------


def build_tape(curve_map: Mapping[Any, Any], cfg: CvxStrikelessConfig) -> pd.DataFrame:
    """The exact strat3 trade tape for this config, validated for QDB replay."""
    from RVUtils.ConvexityRV.strat3_strikeless_vol import hedge_schedule

    tape = hedge_schedule(curve_map, cfg.to_strat3())
    validate_tape(tape)
    return tape


def validate_tape(tape: pd.DataFrame) -> None:
    """Refuse a tape QDB would silently misplay. Loud failures only.

    * ``date``/``effective``/``maturity`` on event rows must be PLAIN
      ``datetime.date`` — a ``pd.Timestamp`` inside ``DateTriggerRequirements``
      is the silent-no-op trap (every mark exactly zero, run reports success).
    * event rows need finite non-zero ``bpv`` and both leg dates; unwind rows
      are exempt (their ``bpv`` is NaN and dates are None by contract).
    * exactly one unwind per segment, dated on the segment's last event day or
      later; segments are 0..S-1 with no gaps.
    """
    if tape is None or len(tape) == 0:
        raise ValueError("tape is empty — hedge_schedule produced no trades")
    missing = [c for c in TAPE_COLUMNS if c not in tape.columns]
    if missing:
        raise KeyError(f"tape is missing columns {missing}; have {list(tape.columns)}")

    kinds = set(tape["kind"].unique())
    unknown = kinds - set(EVENT_KINDS) - {"unwind"}
    if unknown:
        raise ValueError(f"tape has unknown kinds {sorted(unknown)}")

    segs = sorted(tape["segment"].unique())
    if segs != list(range(len(segs))):
        raise ValueError(f"tape segments must be 0..S-1 with no gaps, got {segs}")

    for idx, row in tape.iterrows():
        if not _is_plain_date(row["date"]):
            raise TypeError(
                f"tape row {idx} ({row['kind']}): date {row['date']!r} is "
                f"{type(row['date']).__name__}, not a plain datetime.date. A "
                "pd.Timestamp in DateTriggerRequirements is a SILENT no-op (zero marks)."
            )
        if row["kind"] == "unwind":
            continue
        if not (pd.notna(row["bpv"]) and np.isfinite(row["bpv"]) and row["bpv"] != 0.0):
            raise ValueError(f"tape row {idx} ({row['kind']}): bpv must be finite non-zero, got {row['bpv']!r}")
        for col in ("effective", "maturity"):
            if not _is_plain_date(row[col]):
                raise TypeError(
                    f"tape row {idx} ({row['kind']}): {col} {row[col]!r} is "
                    f"{type(row[col]).__name__}, not a plain datetime.date — explicit "
                    "leg dates are the contract (relative tenors re-resolve to NPV~0)."
                )

    for k, seg in tape.groupby("segment"):
        unwinds = seg[seg["kind"] == "unwind"]
        if len(unwinds) != 1:
            raise ValueError(f"segment {k}: expected exactly 1 unwind row, got {len(unwinds)}")
        events = seg[seg["kind"] != "unwind"]
        if len(events) == 0:
            raise ValueError(f"segment {k}: no event rows")
        if unwinds["date"].iloc[0] < events["date"].max():
            raise ValueError(
                f"segment {k}: unwind {unwinds['date'].iloc[0]} predates its last event "
                f"{events['date'].max()}"
            )
        opening = events[events["kind"].isin(("initiate", "roll"))]
        want = "initiate" if k == 0 else "roll"
        if set(opening["kind"].unique()) != {want}:
            raise ValueError(
                f"segment {k}: opening rows must all be '{want}' "
                f"(got {sorted(opening['kind'].unique())}) — stitch relabels later openings as rolls"
            )


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


def _segment_fees(tape: pd.DataFrame, cfg: CvxStrikelessConfig) -> Dict[int, float]:
    """USD fee attached to each segment's unwind, per the strat3 cost model.

    ``fee[k] = (initiate if k==0) + (roll opening k+1 if k < S-1) + Σ hedge_k``.
    Openings charge on the PACKAGE DV01 (one charge per event, not per leg row,
    and not scaled by beta) — exactly ``simulate_strat3``'s
    ``cost_usd("initiate"|"roll", abs(package_dv01_usd))``; each hedge charges
    on its own traded risk ``|bpv|``. There is no terminal exit charge in the
    strat3 schedule, so none is added here.
    """
    costs = cfg.cost_schedule()
    segs = sorted(tape["segment"].unique())
    n = len(segs)
    fees: Dict[int, float] = {}
    for k in segs:
        fee = 0.0
        if k == 0:
            fee += costs.cost_usd("initiate", abs(cfg.package_dv01_usd))
        if k < n - 1:
            fee += costs.cost_usd("roll", abs(cfg.package_dv01_usd))
        hedges = tape[(tape["segment"] == k) & (tape["kind"] == "hedge")]
        for bpv in hedges["bpv"]:
            fee += costs.cost_usd("hedge", abs(float(bpv)))
        fees[int(k)] = float(fee)
    return fees


def fee_events(tape: pd.DataFrame, cfg: CvxStrikelessConfig) -> pd.Series:
    """Per-date USD fees as booked by the QDB unwinds (one entry per segment)."""
    validate_tape(tape)
    fees = _segment_fees(tape, cfg)
    unwind_date = {
        int(k): seg[seg["kind"] == "unwind"]["date"].iloc[0] for k, seg in tape.groupby("segment")
    }
    out: Dict[dt.date, float] = {}
    for k, fee in fees.items():
        d = unwind_date[k]
        out[d] = out.get(d, 0.0) + fee
    return pd.Series(out, dtype=float).sort_index()


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


def build_backtest(
    tape: pd.DataFrame,
    mdp: Any,
    *,
    cfg: CvxStrikelessConfig,
    grid_dates: Sequence[Any],
) -> Any:
    """One ``QueryDrivenBacktest`` replaying the tape as dated triggers.

    * one ``DateTrigger`` per (segment, event date) carrying that date's
      ``AddQueryAction``s; trigger dates are PLAIN ``datetime.date`` (validated
      upstream — the pd.Timestamp silent-no-op trap);
    * every leg is an OUTRIGHT with the tape's EXPLICIT effective/maturity and
      signed ``bpv`` (payer > 0), tagged ``s{k}`` per segment — distinct tags
      because entries fill BEFORE unwinds in a step, so segment ``k``'s roll-date
      unwind must not close the package segment ``k+1`` just opened;
    * one ``UnwindPositionsAction(match_tag="s{k}", fee=...)`` per segment with
      the strat3 fee mapping (see :func:`_segment_fees`);
    * ``market_request`` carries ``"offline": True`` so a per-mark store miss
      raises instead of reaching Excel COM (moot under :class:`CurveMapMDP`,
      binding under a real ``IRSwapsMDP``).

    ``grid_dates`` must cover every tape date; the reference run passes the
    curve_map's own days so the engine marks exactly the days the panel prices.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    validate_tape(tape)
    grid = sorted({_as_plain_date(d) for d in grid_dates})
    grid_set = set(grid)
    off_grid = sorted(set(tape["date"]) - grid_set)
    if off_grid:
        raise ValueError(
            f"{len(off_grid)} tape date(s) not in the time grid (first: {off_grid[0]}); "
            "the grid must be the curve_map's own days."
        )

    fees = _segment_fees(tape, cfg)
    triggers: List[Any] = []
    for k, seg in tape.groupby("segment", sort=True):
        tag = f"s{int(k)}"
        events = seg[seg["kind"] != "unwind"]
        for d, rows in events.groupby("date", sort=True):
            actions = []
            for _, row in rows.iterrows():
                q = IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    effective_date=row["effective"],
                    maturity_date=row["maturity"],
                    curve=cfg.curve_name,
                    market_request={"curve_name": cfg.curve_name, "offline": True},
                    structure_kwargs={"bpv": float(row["bpv"])},
                    tags=(tag,),
                )
                actions.append(
                    AddQueryAction(
                        query=q,
                        meta={
                            "tags": [tag],
                            "segment": int(k),
                            "kind": str(row["kind"]),
                            "leg": str(row["leg"]),
                        },
                    )
                )
            triggers.append(DateTrigger(DateTriggerRequirements(dates=[d]), actions=actions))
        unwind_d = seg[seg["kind"] == "unwind"]["date"].iloc[0]
        triggers.append(
            DateTrigger(
                DateTriggerRequirements(dates=[unwind_d]),
                actions=[UnwindPositionsAction(match_tag=tag, fee=fees[int(k)])],
            )
        )

    strat = QueryStrategy(
        name=f"cvx_strikeless_{cfg.short_leg}_{cfg.long_leg}", triggers=triggers
    )
    return QueryDrivenBacktest(
        time_grid=TimeGrid([pd.Timestamp(d) for d in grid]),
        strategy=strat,
        mdp=mdp,
        show_progress=cfg.show_progress,
    )


# ---------------------------------------------------------------------------
# Sign probe + assert battery
# ---------------------------------------------------------------------------


def sign_probe(
    mdp: Any,
    as_of: Any,
    *,
    short: str = "15Yx5Y",
    long: str = "20Yx10Y",
    package_dv01_usd: float = 100_000.0,
    curve_name: str = CURVE,
) -> dict:
    """Re-derive the direction convention from the engine, on every run.

    ``rac_backtest.sign_probe`` pattern plus the ±bpv mirror: resolve the CURVE
    package at ``bpv = -DV01`` AND ``+DV01``. For ``bpv < 0`` (flattener) the
    short leg's resolved PV01 must be positive, the long leg's negative, the two
    summing to ~0; the ``+DV01`` resolution must mirror both exactly.
    ``resolve_pricable`` BAKES the risk weight into the returned leg — reading
    the signed pv01 off the resolved leg (never re-multiplying by the weight)
    is the probe; a regressed seam (L-0012 ``abs()`` slip) fails it.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    as_of_d = _as_plain_date(as_of)
    if hasattr(mdp, "_get_curve"):
        pricer = mdp._get_curve(curve_name=curve_name, timestamp=as_of_d)
    else:
        pricer = mdp.get_pricer({"curve_name": curve_name, "timestamp": as_of_d})

    def _resolve(bpv: float) -> List[float]:
        q = IRSwapQuery(
            curve=curve_name,
            structure=IRSwapStructure.CURVE,
            value=IRSwapValue.PV01,
            structure_kwargs={
                "front_tenor": short,
                "back_tenor": long,
                "bpv": float(bpv),
                "risk_weights": [1.0, 1.0],
            },
        )
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        resolved = [pricer.resolve_pricable(p, w) for p, w in zip(package, weights)]
        return [float(pricer.pv01(s)) for s in resolved]

    minus = _resolve(-abs(package_dv01_usd))
    plus = _resolve(+abs(package_dv01_usd))
    tol = 1e-6 * abs(package_dv01_usd)
    mirror_ok = all(abs(m + p) < tol for m, p in zip(minus, plus))
    return {
        "front_pv01": minus[0],
        "back_pv01": minus[1],
        "sum": float(sum(minus)),
        "is_flattener": bool(minus[0] > 0 > minus[1]),
        "mirror": {"minus": minus, "plus": plus},
        "mirror_ok": bool(mirror_ok),
    }


def check_probe(probe: Mapping[str, Any]) -> None:
    """Refuse to run on a regressed direction seam. Loud, never a warning."""
    if not probe.get("is_flattener"):
        raise RuntimeError(
            f"sign probe FAILED: bpv<0 did not resolve to pay-front/receive-back "
            f"(front_pv01={probe.get('front_pv01')}, back_pv01={probe.get('back_pv01')}). "
            "The resolve_pricable direction seam has regressed (ledger L-0012); "
            "every downstream sign would be silently wrong."
        )
    if not probe.get("mirror_ok"):
        raise RuntimeError(
            f"sign probe FAILED: +bpv and -bpv do not mirror ({probe.get('mirror')}). "
            "resolve_pricable is dropping the risk-weight sign (ledger L-0012)."
        )


def assert_ran(bt: Any, *, expect_days: int, expect_closed: int) -> None:
    """``QueryDrivenBacktest.run()`` swallows per-step exceptions — assert on artifacts.

    A backtest that blew up on every date and one that never traded both show a
    flat curve; a pd.Timestamp trigger shows a COMPLETE, hole-free, identically
    zero curve. The battery: full grid coverage, finite marks, non-zero
    somewhere, and every tape event closed.
    """
    mtm = getattr(bt, "mtm_history", None)
    if mtm is None or len(mtm) == 0:
        raise AssertionError("mtm_history is empty; run() failed silently on every step")
    if len(mtm) != expect_days:
        raise AssertionError(
            f"mtm_history has {len(mtm)} marks, expected {expect_days} — the engine "
            "swallowed steps (equity-curve holes)."
        )
    eq = pd.Series(dict(mtm))
    if not np.isfinite(eq.to_numpy(dtype=float)).all():
        raise AssertionError("mtm_history contains non-finite marks")
    n_closed = len(getattr(getattr(bt, "portfolio", None), "closed_positions_log", []) or [])
    if float(eq.abs().max()) == 0.0:
        raise AssertionError(
            f"equity is identically zero on every date and {n_closed} positions closed; "
            "the engine priced nothing. If the closed count is 0 the triggers never "
            "fired — DateTriggerRequirements compares state.date() against its dates "
            "set, so a pd.Timestamp there matches nothing."
        )
    if n_closed != expect_closed:
        raise AssertionError(
            f"closed {n_closed} positions, expected {expect_closed} (one per tape event "
            "row) — an unwind missed its tag or an add never filled."
        )


# ---------------------------------------------------------------------------
# Reference run + certification
# ---------------------------------------------------------------------------


@dataclass
class CvxStrikelessResult:
    config: CvxStrikelessConfig
    tape: pd.DataFrame
    equity: pd.Series                 # cumulative TOTAL P&L, net of fees (mtm_history)
    equity_gross: pd.Series           # fees added back (certification series)
    fees: pd.Series                   # per-date USD fees as booked at unwinds
    closed_positions: pd.DataFrame
    probe: dict
    backtest: Any
    n_segments: int
    n_hedges: int
    n_rolls: int


def _mtm_series(bt: Any) -> pd.Series:
    data = {
        (_as_plain_date(ts)): float(v) for ts, v in bt.mtm_history.items()
    }
    return pd.Series(data, dtype=float).sort_index()


def strat3_unit_ledger(curve_map: Mapping[Any, Any], cfg: CvxStrikelessConfig) -> pd.DataFrame:
    """The zero-cost stitched strat3 unit ledger for this config's variant.

    Certification target: date-indexed ``carry/harvest/mtm/cross`` buckets (USD)
    plus volume/state columns, from ``unit_ledgers_for_pair`` — the same
    ``simulate_strat3`` code path that produced the tape, on the same curves.
    """
    from RVUtils.ConvexityRV.strat3_strikeless_vol import unit_ledgers_for_pair

    variants = [
        {
            "hedge_threshold_bp": float(cfg.hedge_threshold_bp),
            "beta": float(cfg.beta),
            "resize_mode": cfg.resize_mode,
        }
    ]
    ledgers = unit_ledgers_for_pair(
        dict(curve_map),
        cfg.short_leg,
        cfg.long_leg,
        variants,
        package_dv01_usd=float(cfg.package_dv01_usd),
        roll_months_set=(int(cfg.roll_months),),
        market=cfg.market,
        curve_name=cfg.curve_name,
    )
    key = (int(cfg.roll_months), float(cfg.hedge_threshold_bp), float(cfg.beta), cfg.resize_mode)
    if key not in ledgers:
        raise KeyError(f"unit_ledgers_for_pair returned {sorted(ledgers)} — missing {key}")
    ledger = ledgers[key]
    if ledger is None or len(ledger) == 0:
        raise ValueError("strat3 unit ledger is empty")
    return ledger


def run_reference(
    cfg: CvxStrikelessConfig,
    *,
    mdp: Any = None,
    curve_map: Optional[Mapping[Any, Any]] = None,
) -> CvxStrikelessResult:
    """Sign probe -> tape -> QDB replay -> assert battery -> result.

    ``curve_map`` (from :func:`build_curve_map`) is reused for the tape, the
    marks (via :class:`CurveMapMDP`) and the caller's unit ledger, so all three
    price the same day set. ``mdp`` is only consulted to BUILD the curve map
    when one is not passed.
    """
    if curve_map is None:
        days = [d.date() for d in pd.bdate_range(cfg.start, cfg.end)]
        curve_map = build_curve_map(days, curve_name=cfg.curve_name, mdp=mdp)
    curve_map = {
        _as_plain_date(k): v for k, v in curve_map.items() if v is not None and k != "live"
    }
    grid = sorted(curve_map)
    serving = CurveMapMDP(curve_map, curve_name=cfg.curve_name)

    probe = sign_probe(
        serving,
        grid[0],
        short=cfg.short_leg,
        long=cfg.long_leg,
        package_dv01_usd=cfg.package_dv01_usd,
        curve_name=cfg.curve_name,
    )
    check_probe(probe)

    tape = build_tape(curve_map, cfg)
    bt = build_backtest(tape, serving, cfg=cfg, grid_dates=grid)
    bt.run()

    n_events = int((tape["kind"] != "unwind").sum())
    assert_ran(bt, expect_days=len(grid), expect_closed=n_events)

    equity = _mtm_series(bt)
    fees = fee_events(tape, cfg)
    equity_gross = equity + fees.reindex(equity.index).fillna(0.0).cumsum()
    closed = pd.DataFrame(list(bt.portfolio.closed_positions_log))
    n_segments = int(tape["segment"].nunique())
    return CvxStrikelessResult(
        config=cfg,
        tape=tape,
        equity=equity,
        equity_gross=equity_gross,
        fees=fees,
        closed_positions=closed,
        probe=probe,
        backtest=bt,
        n_segments=n_segments,
        n_hedges=int((tape["kind"] == "hedge").sum()),
        n_rolls=n_segments - 1,
    )


def certify(
    result: CvxStrikelessResult,
    strat3_ledger: pd.DataFrame,
    *,
    corr_min: Optional[float] = None,
) -> dict:
    """Engine daily GROSS P&L vs the strat3 unit ledger's daily flows.

    Both sides are engine-REPRICED P&L of the same trade tape on the same
    curves (the panel-is-not-P&L rule: a Δrate×DV01 par panel is never a valid
    certification target — it overstated hedged books 1.5–6× in Sharpe). Gross
    vs gross so the QDB's fee-at-unwind timing deferral cannot leak in; the
    unit ledger is zero-cost by construction.

    ``pass`` is gated on the daily correlation only (the DESIGN §5 bar); the
    terminal gap is STATED in USD and bp of package DV01, alongside both sides'
    hedge/roll counts — the tape and ledger run the same ``simulate_strat3``,
    so a count mismatch means the two runs diverged and the corr is meaningless.
    """
    bar = float(result.config.corr_min if corr_min is None else corr_min)
    for col in ("carry", "harvest", "mtm", "cross"):
        if col not in strat3_ledger.columns:
            raise KeyError(f"strat3 ledger is missing bucket '{col}'")

    panel_daily = strat3_ledger[["carry", "harvest", "mtm", "cross"]].sum(axis=1)
    panel_daily.index = [_as_plain_date(d) for d in panel_daily.index]
    panel_daily = panel_daily.sort_index()

    gross = result.equity_gross.sort_index()
    engine_daily = gross.diff()
    if len(engine_daily):
        engine_daily.iloc[0] = gross.iloc[0]

    j = pd.DataFrame({"engine": engine_daily, "panel": panel_daily}).dropna()
    if len(j) < 2:
        raise RuntimeError(
            f"certify: only {len(j)} common days between engine "
            f"({gross.index.min()}..{gross.index.max()}) and ledger "
            f"({panel_daily.index.min()}..{panel_daily.index.max()}) — nothing to certify."
        )
    corr = float(j["engine"].corr(j["panel"]))
    engine_total = float(j["engine"].sum())
    panel_total = float(j["panel"].sum())
    gap_usd = engine_total - panel_total
    dv01 = float(result.config.package_dv01_usd)

    ledger_hedges = int(strat3_ledger["n_hedges"].sum()) if "n_hedges" in strat3_ledger else -1
    ledger_rolls = int(strat3_ledger["n_rolls"].sum()) if "n_rolls" in strat3_ledger else -1

    return {
        "n_common_days": int(len(j)),
        "corr": corr,
        "terminal_gap_usd": gap_usd,
        "terminal_gap_bp": gap_usd / dv01,
        "engine_gross_usd": engine_total,
        "panel_gross_usd": panel_total,
        "median_abs_daily_diff_bp": float((j["engine"] - j["panel"]).abs().median() / dv01),
        "n_hedges_engine": int(result.n_hedges),
        "n_hedges_ledger": ledger_hedges,
        "n_rolls_engine": int(result.n_rolls),
        "n_rolls_ledger": ledger_rolls,
        "corr_min": bar,
        "pass": bool(np.isfinite(corr) and corr >= bar),
    }
