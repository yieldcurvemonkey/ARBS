r"""Price swaps through MDP -> Query -> Structure and check them against Citi's quotes.

The point of this module is that it is **not** the builder checking itself.
``build_rl_ois_curve`` already re-prices its own calibration inputs to ~1e-3 bp, and
that number cannot catch a convention error because the same conventions produced
both sides. Everything here goes out through :class:`IRSwapQuery`, which builds its
swaps from ``RATESLIB_CURVE_DEFINITIONS`` / ``QUANTLIB_CURVE_DEFINITIONS`` - a
different code path, reading a different table - and compares against numbers Citi
published.

Four checks, in increasing order of how much they can catch
-----------------------------------------------------------
``par``
    Every tenor's par rate through ``IRSwapQuery`` against ``RATES.OIS.<idx>.PAR.<t>``.
    Nearly circular on the *curve*, but not on the *definitions*: if the registered
    ``RATESLIB_CURVE_DEFINITIONS`` row disagrees with ``conventions.py`` about the
    calendar, the payment frequency, the settlement lag or the day count, the swap
    Query builds is not the swap the curve was calibrated with and this check moves.
    That is the one thing it exists to catch.

``forward``
    Forward-starting swaps against Citi's published ``RATES.OIS.<idx>.FWD.<e>.<t>``.
    **Independent data** - nothing about our curve went into it - so this is the
    check the +/-1bp claim rests on.

``interpolation``
    Drop one interior tenor from the calibration set, rebuild, and ask the curve to
    price the tenor it no longer knows about. The only check here that probes
    between the nodes; a repricing check is blind to interpolation by construction.

``backends``
    The same trade through rateslib and through QuantLib. This is what catches
    schedule, day-count and annuity divergence, because the two libraries agree on
    nothing by accident.

Reading the forward numbers honestly
------------------------------------
``IRSwapQuery``'s ``"5Yx10Y"`` shorthand and Citi's ``FWD.5Y.10Y`` are **not the
same trade**. ``RLIRSwapCurve.build_irswap`` measures the forward from the curve's
*reference date* and adjusts modified-following; Citi (and
``curves/rl_builder.forward_rate``, and QuantLib's ``MakeOIS``) measures it from
*spot* and adjusts following. That is a two-business-day difference in the start
date. Both are computed and reported: ``fwd_shorthand_bp`` uses the shorthand,
``err_bp`` uses explicit Citi-convention dates. Quoting the shorthand against
Citi's number and calling the difference an error would be measuring a convention,
not a curve.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

__all__ = [
    "TieOutRow",
    "FORWARD_POINTS",
    "citi_forward_dates",
    "query_par_rate",
    "tie_out_curve",
    "tie_out_frame",
]

_logger = logging.getLogger(__name__)

#: The forward points harvested from Citi for every curve on 2026-08-07. Chosen to
#: span the grid so an interpolation error at either end shows up.
FORWARD_POINTS: Tuple[Tuple[str, str], ...] = (
    ("1Y", "1Y"),
    ("1Y", "10Y"),
    ("2Y", "5Y"),
    ("5Y", "5Y"),
    ("5Y", "10Y"),
    ("10Y", "10Y"),
)

#: Interior tenors dropped one at a time for the interpolation check. Interior on
#: purpose: dropping 1D or 40Y tests extrapolation, which is a different claim.
INTERPOLATION_TENORS: Tuple[str, ...] = ("3Y", "7Y", "12Y", "25Y")


@dataclass
class TieOutRow:
    """One comparison. ``err_bp`` is model minus Citi, in basis points."""

    curve_name: str
    citi_index: str
    mode: str
    check: str
    backend: str
    point: str
    citi: Optional[float] = None
    model: Optional[float] = None
    err_bp: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out = {
            "curve_name": self.curve_name,
            "citi_index": self.citi_index,
            "mode": self.mode,
            "check": self.check,
            "backend": self.backend,
            "point": self.point,
            "citi": self.citi,
            "model": self.model,
            "err_bp": self.err_bp,
            "error": self.error,
        }
        out.update(self.extra)
        return out


# ------------------------------------------------------------------ #
#                      Citi's own forward convention                 #
# ------------------------------------------------------------------ #


def citi_forward_dates(
    citi_index: str, ref_date: datetime.date, forward: str, tenor: str
) -> Tuple[datetime.date, datetime.date]:
    """``(effective, maturity)`` for Citi's ``FWD.<forward>.<tenor>``.

    Spot is ``spot_lag`` good business days after the reference date; the forward
    start is spot plus ``forward`` adjusted **following**; the maturity is read off
    a real ``rl.IRS`` built with this curve's own conventions rather than
    re-derived, so it cannot drift from what the builder does.
    """
    import rateslib as rl

    from MDP.CitiVelocityExcel.curves.conventions import conventions_for
    from MDP.CitiVelocityExcel.curves.rl_builder import make_rl_irs

    conv = conventions_for(citi_index)
    cal = conv.rl_calendar_object()
    ref = cal.roll(rl.dt(ref_date.year, ref_date.month, ref_date.day), "P", False)
    spot = cal.add_bus_days(ref, int(conv.spot_lag), True)
    effective = rl.add_tenor(spot, forward, "f", cal)
    irs = make_rl_irs(
        conv=conv,
        calendar=cal,
        effective=effective,
        tenor=tenor,
        curve_id="tie-out",
        fixed_rate=0.0,
    )
    termination = irs.leg1.schedule.termination
    return effective.date(), termination.date()


# ------------------------------------------------------------------ #
#                        pricing through Query                       #
# ------------------------------------------------------------------ #


def query_par_rate(
    curve: Any,
    *,
    curve_name: str,
    tenor: Optional[str] = None,
    effective_date: Optional[datetime.date] = None,
    maturity_date: Optional[datetime.date] = None,
    notional: float = 1_000_000.0,
) -> float:
    """The par rate of one swap, in PERCENT, through the full Query path.

    Goes ``IRSwapQuery -> resolve_package -> build_value_map -> RATE`` so that the
    curve is exercised exactly the way a caller's query would exercise it -
    including ``build_irswap``, which reads the curve-definition table rather than
    the calibration conventions.

    Units: ``IRSwapValue.RATE`` scales by ``_swap_structure_legs_mapper[n_legs]``,
    which is **100 for a one-leg package** - so an outright already comes back in
    PERCENT, the same unit Citi quotes ``RATES.OIS.<idx>.PAR.<tenor>`` in, and no
    conversion belongs here. (A two- or three-leg package scales by 10,000 instead,
    because a curve or fly is quoted in basis points of spread; that is why the
    factor is read from the map rather than hardcoded anywhere.) Getting this
    backwards is not subtle - it showed up as a 44,566 bp "error" - but a units
    slip that lands within a plausible range would not, which is why it is spelled
    out here.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    kwargs: Dict[str, Any] = {"notional": notional}
    query = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.RATE,
        tenor=tenor,
        effective_date=effective_date,
        maturity_date=maturity_date,
        curve=curve_name,
        structure_kwargs=kwargs,
    )
    package, weights = query.resolve_package(pricer_or_curve=curve)
    value_map = query.build_value_map(
        pricer_or_curve=curve, package=package, risk_weights=weights
    )
    if len(package) != 1:
        raise ValueError(
            f"query_par_rate expected a single-leg package, got {len(package)}; the RATE scaling "
            "differs (100 for one leg, 10,000 for a curve or fly)."
        )
    return float(value_map.apply(IRSwapValue.RATE))


# ------------------------------------------------------------------ #
#                             the checks                             #
# ------------------------------------------------------------------ #


def tie_out_curve(
    *,
    curve_name: str,
    mode: str,
    timestamp: Any,
    quotes: Any,
    backends: Sequence[str] = ("rl", "ql"),
    checks: Sequence[str] = ("par", "forward", "interpolation", "backends"),
    par_tenors: Optional[Sequence[str]] = None,
    forward_points: Sequence[Tuple[str, str]] = FORWARD_POINTS,
    mdp_kwargs: Optional[Mapping[str, Any]] = None,
) -> List[TieOutRow]:
    """Run every requested check for one curve in one mode.

    ``quotes`` is a :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`, used
    ONLY to read Citi's published numbers to compare against - never to build the
    curve. The curve comes from ``IRSwapsMDP``, which is the path under test.
    """
    from MDP.CitiVelocityExcel import tags as T
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import citi_index_for_curve_name
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    citi_index = citi_index_for_curve_name(curve_name)
    rows: List[TieOutRow] = []

    def _row(check: str, backend: str, point: str, **kw: Any) -> TieOutRow:
        row = TieOutRow(
            curve_name=curve_name, citi_index=citi_index, mode=mode,
            check=check, backend=backend, point=point, **kw,
        )
        rows.append(row)
        return row

    curves: Dict[str, Any] = {}
    snapshots: Dict[str, Any] = {}
    for backend in backends:
        source = "CITIVELO_EXCEL-QL" if backend == "ql" else "CITIVELO_EXCEL-RL"
        try:
            mdp = IRSwapsMDP(source=source)
            curve = mdp.get_data(
                {"curve_name": curve_name, "timestamp": timestamp, **dict(mdp_kwargs or {})}
            )
            curves[backend] = curve
            snapshots[backend] = curve.meta()
        except Exception as exc:  # noqa: BLE001 - a failure IS the result to record
            _row("build", backend, "-", error=f"{type(exc).__name__}: {exc}")
    if not curves:
        return rows

    ref_backend = "rl" if "rl" in curves else list(curves)[0]
    meta = snapshots[ref_backend]
    snapshot_at = pd.Timestamp(meta["snapshot_at"])
    ref_date = snapshot_at.date()

    # ---- Citi's published numbers at this same instant --------------
    freq = meta.get("freq", "DAILY")
    par_tag_map = {t.rsplit(".", 1)[-1]: t for t in T.ois_par_grid(citi_index)}
    if par_tenors:
        par_tag_map = {t: par_tag_map[t] for t in par_tenors if t in par_tag_map}
    fwd_tag_map = {
        (e, t): f"RATES.OIS.{citi_index}.FWD.{e}.{t}" for e, t in forward_points
    }
    citi_par = _quotes_at(quotes, list(par_tag_map.values()), freq, snapshot_at)
    citi_fwd = _quotes_at(quotes, list(fwd_tag_map.values()), "DAILY", snapshot_at)

    # ---- 1. par ------------------------------------------------------
    if "par" in checks:
        for backend, curve in curves.items():
            for tenor, tag in par_tag_map.items():
                quoted = citi_par.get(tag)
                if quoted is None:
                    continue
                try:
                    model = query_par_rate(curve, curve_name=curve_name, tenor=tenor)
                except Exception as exc:  # noqa: BLE001
                    _row("par", backend, tenor, citi=quoted, error=f"{type(exc).__name__}: {exc}")
                    continue
                _row("par", backend, tenor, citi=quoted, model=model,
                     err_bp=(model - quoted) * 100.0)

    # ---- 2. forward, against Citi's published forwards ---------------
    if "forward" in checks:
        for backend, curve in curves.items():
            for (expiry, tenor), tag in fwd_tag_map.items():
                quoted = citi_fwd.get(tag)
                if quoted is None:
                    continue
                point = f"{expiry}x{tenor}"
                try:
                    eff, mat = citi_forward_dates(citi_index, ref_date, expiry, tenor)
                    model = query_par_rate(
                        curve, curve_name=curve_name, effective_date=eff, maturity_date=mat
                    )
                except Exception as exc:  # noqa: BLE001
                    _row("forward", backend, point, citi=quoted, error=f"{type(exc).__name__}: {exc}")
                    continue
                extra: Dict[str, Any] = {"effective": eff.isoformat(), "maturity": mat.isoformat()}
                # The shorthand is reported alongside so the convention difference
                # is visible as a number rather than a claim in a docstring.
                try:
                    shorthand = query_par_rate(curve, curve_name=curve_name, tenor=point)
                    extra["fwd_shorthand_bp"] = (shorthand - quoted) * 100.0
                except Exception as exc:  # noqa: BLE001
                    extra["fwd_shorthand_bp"] = None
                    extra["fwd_shorthand_error"] = f"{type(exc).__name__}: {exc}"
                _row("forward", backend, point, citi=quoted, model=model,
                     err_bp=(model - quoted) * 100.0, extra=extra)

    # ---- 3. interpolation: drop a node, then price it ----------------
    if "interpolation" in checks and "rl" in curves:
        rows.extend(
            _interpolation_rows(
                curve_name=curve_name,
                citi_index=citi_index,
                mode=mode,
                ref_date=ref_date,
                snapshot_at=snapshot_at,
                par_quotes={t: citi_par[tag] for t, tag in par_tag_map.items() if tag in citi_par},
            )
        )

    # ---- 4. the two backends against each other ---------------------
    if "backends" in checks and {"rl", "ql"} <= set(curves):
        for tenor in ("2Y", "5Y", "10Y", "30Y"):
            if tenor not in par_tag_map:
                continue
            try:
                a = query_par_rate(curves["rl"], curve_name=curve_name, tenor=tenor)
                b = query_par_rate(curves["ql"], curve_name=curve_name, tenor=tenor)
            except Exception as exc:  # noqa: BLE001
                _row("backends", "rl-ql", tenor, error=f"{type(exc).__name__}: {exc}")
                continue
            _row("backends", "rl-ql", tenor, citi=b, model=a, err_bp=(a - b) * 100.0)

    return rows


def _interpolation_rows(
    *,
    curve_name: str,
    citi_index: str,
    mode: str,
    ref_date: datetime.date,
    snapshot_at: pd.Timestamp,
    par_quotes: Mapping[str, float],
) -> List[TieOutRow]:
    """Rebuild without one interior tenor, then price the tenor that is now missing.

    This is the only check that looks *between* the calibration nodes. It builds
    the reduced curve directly rather than through the MDP, because the MDP has no
    way to say "serve me this grid minus one point" - and the thing under test here
    is the curve's interpolation, not the source's plumbing.
    """
    from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve, forward_rate

    rows: List[TieOutRow] = []
    for tenor in INTERPOLATION_TENORS:
        if tenor not in par_quotes:
            continue
        reduced = {t: v for t, v in par_quotes.items() if t != tenor}
        if len(reduced) < 8:
            continue
        try:
            rlc = build_rl_ois_curve(
                par_rates=reduced, ref_date=ref_date, citi_index=citi_index,
                curve_id=f"{curve_name}-drop-{tenor}", timestamp=snapshot_at,
            )
            model = forward_rate(rlc, forward="0D", tenor=tenor)
        except Exception as exc:  # noqa: BLE001
            rows.append(TieOutRow(curve_name, citi_index, mode, "interpolation", "rl", tenor,
                                  citi=par_quotes[tenor], error=f"{type(exc).__name__}: {exc}"))
            continue
        rows.append(TieOutRow(
            curve_name, citi_index, mode, "interpolation", "rl", tenor,
            citi=par_quotes[tenor], model=model,
            err_bp=(model - par_quotes[tenor]) * 100.0,
            extra={"n_nodes": len(reduced)},
        ))
    return rows


def _quotes_at(quotes: Any, tags: Sequence[str], freq: str, when: pd.Timestamp) -> Dict[str, float]:
    """Citi's published values for ``tags`` as of ``when``, backward-only.

    Deliberately a separate read from the one that built the curve: comparing a
    curve against the very array it was constructed from, in the same call, is how
    a tie-out becomes a tautology without anyone noticing.
    """
    if not tags:
        return {}
    naive = pd.Timestamp(when).tz_localize(None) if pd.Timestamp(when).tzinfo else pd.Timestamp(when)
    lookback = datetime.timedelta(days=5 if freq in {"MI01", "MI10", "HOURLY"} else 21)
    frame = quotes.frame(list(tags), freq, start=naive - lookback, end=naive)
    if frame is None or frame.empty:
        return {}
    out: Dict[str, float] = {}
    for column in frame.columns:
        series = frame[column].dropna()
        series = series[series.index <= naive]
        if not series.empty:
            out[str(column)] = float(series.iloc[-1])
    return out


def tie_out_frame(rows: Iterable[TieOutRow]) -> pd.DataFrame:
    """The rows as a frame, ordered so the worst errors read first."""
    frame = pd.DataFrame([r.as_dict() for r in rows])
    if frame.empty:
        return frame
    frame["abs_err_bp"] = frame["err_bp"].abs()
    return frame.sort_values(["check", "abs_err_bp"], ascending=[True, False], na_position="last")
