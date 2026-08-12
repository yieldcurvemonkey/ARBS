r"""Strip an IBOR projection curve from Citi's ``RATES.SWAP_LIBOR`` par grid.

Everything else in :mod:`MDP.CitiVelocityExcel.curves` builds a **single** curve:
an OIS index discounts and forecasts itself, so one set of nodes satisfies both
roles. A EURIBOR swap does not work that way. Its floating leg forecasts
EURIBOR-6M and its cashflows discount on ESTR, and the two are different curves
with a real basis between them. That is exactly why the package README recorded
``RATES.SWAP_LIBOR`` as "quotes only - no local repricing": using the OIS
conventions would have been the wrong swap, not an approximation of the right
one.

This module builds the right swap.

The three eras, and why the discount curve is an argument
--------------------------------------------------------
Citi's EURIBOR par history reaches **2016-07-06** at one-minute resolution. The
euro OIS curves it would be discounted on do not reach as far, and they do not
reach the same distance as each other (measured 2026-08-09):

===============  ==========================  ==============================
era              discount curve              status
===============  ==========================  ==============================
2021-09-15 ->    ``EUR-ESTR-1D``             the modern convention
~2018-01-10 ->   ``EUR-EONIA-1D``            the pre-ESTR euro OIS index
2016-07-06 ->    *none available intraday*   self-discounted, and labelled
===============  ==========================  ==============================

So ``discount_curve`` is a parameter rather than something this module fetches,
and when it is ``None`` the build **self-discounts and says so** in the returned
metadata. A self-discounted EURIBOR curve is the pre-2008 construction: it
reproduces the par quotes exactly, its forwards are close but not equal to the
dual-curve ones, and any annuity or PV computed off it is a different number.
Recording which one was used is the difference between a documented
approximation and a silent one.

Repricing is checked, not assumed
---------------------------------
rateslib 2.7 made ``solver.result['status'] == 'SUCCESS'`` insufficient - a par
grid with a nonsense quote solves "successfully" into a curve that misprices its
own calibration instruments by 4.9e+05 bp. This module therefore asks the solved
curve to reprice the swaps it was built from and raises if it cannot, the same
guard ``build_rl_ois_curve`` grew for the same reason.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

__all__ = [
    "IborCurveSpec",
    "IBOR_CURVES",
    "ibor_spec_for",
    "build_rl_ibor_curve",
    "IborCurveResult",
]

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IborCurveSpec:
    """One IBOR swap curve: where its quotes live and what swap they price.

    ``rl_spec`` is a rateslib spec name, and the choice of index tenor is in it:
    ``eur_irs6`` is annual 30E/360 fixed against semi-annual act/360 EURIBOR-6M,
    which is the EUR market standard for tenors beyond one year and is what
    Citi's ``RATES.SWAP_LIBOR.EUR.PAR`` grid quotes.
    """

    curve_name: str
    citi_currency: str
    rl_spec: str
    calendar: str
    convention: str
    modifier: str
    spot_lag: int
    local_timezone: str
    #: Discount curves to try, newest convention first. Each entry is
    #: ``(available_from, curve_name)``; the build falls through to
    #: self-discounting when none of them has a snapshot at the instant asked for.
    discount_plan: Tuple[Tuple[datetime.date, str], ...] = ()
    note: str = ""

    def discount_curve_for(self, day: datetime.date) -> Optional[str]:
        """The discount curve to prefer on ``day``, or ``None`` to self-discount."""
        for available_from, name in self.discount_plan:
            if day >= available_from:
                return name
        return None


#: The one IBOR curve this package currently serves. Adding another is a row
#: here plus a validated tag family - ``RATES.SWAP_LIBOR`` coverage is PER
#: CURRENCY (EUR/AUD/INR served on 2026-08-05; GBP and JPY were empty after the
#: RFR migration), so a new row must be measured, not assumed.
IBOR_CURVES: Dict[str, IborCurveSpec] = {
    spec.curve_name: spec
    for spec in (
        IborCurveSpec(
            curve_name="EUR-EURIBOR-6M",
            citi_currency="EUR",
            rl_spec="eur_irs6",
            calendar="tgt",
            convention="act360",
            modifier="mf",
            spot_lag=2,
            local_timezone="Europe/Berlin",
            discount_plan=(
                (datetime.date(2021, 9, 15), "EUR-ESTR-1D"),
                (datetime.date(2018, 1, 10), "EUR-EONIA-1D"),
            ),
            note=(
                "Citi's EURIBOR par grid reaches 2016-07-06 at MI01, deeper than any "
                "euro OIS curve; days before the EONIA floor are self-discounted."
            ),
        ),
    )
}


def rateslib_definition(spec: IborCurveSpec) -> Dict[str, Any]:
    """The ``RATESLIB_CURVE_DEFINITIONS`` row for one IBOR curve."""
    return {
        "UseCase": "Fixed_Float_IBOR",
        "SingleorMultiCurrency": "Single Currency",
        "ReferenceRate": spec.rl_spec,
        "NotionalCurrency": spec.curve_name.split("-", 1)[0].lower(),
        "NotionalSchedule": "Constant",
        "DeliveryType": "PHYS",
        "DayCounter": spec.convention,
        "Calendar": spec.calendar,
        "BusinessConvention": spec.modifier,
        "SettlementDays": int(spec.spot_lag),
        "SDR_UPIs": [],
        "Provenance": "citivelo_excel_ibor",
    }


def register(*, force: bool = False) -> List[str]:
    """Teach ``RATESLIB_CURVE_DEFINITIONS`` about these curves. Idempotent.

    Without this, ``CurveStore.reconstruct_curve`` does not find the stored
    ``reference_key`` and silently falls back to **act360 / nyc / mf** — a EUR
    curve rebuilt on the *New York* calendar. It warns once per key and then
    carries on, so the only symptom is a log line nobody reads and date
    arithmetic that is quietly wrong for anything priced off the rebuilt curve.

    ``MDP.IRSwaps.CITIVELO_EXCEL.curve_definitions.register`` does this for the
    twenty OIS curves; an IBOR curve is not in that table and needs its own call.
    An existing name is never overwritten unless ``force`` — another source may
    already define it, and redefining a name in place would move numbers this
    package never touched.
    """
    from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
        RATESLIB_CURVE_DEFINITIONS,
    )

    added: List[str] = []
    for name, spec in IBOR_CURVES.items():
        if name in RATESLIB_CURVE_DEFINITIONS and not force:
            continue
        RATESLIB_CURVE_DEFINITIONS[name] = rateslib_definition(spec)
        added.append(name)
    if added:
        _logger.info("registered rateslib curve definitions for %s", ", ".join(added))
    return added


def ibor_spec_for(curve_name: str) -> IborCurveSpec:
    token = str(curve_name).strip().upper()
    if token in IBOR_CURVES:
        return IBOR_CURVES[token]
    raise KeyError(
        f"{curve_name!r} is not a Citi Velocity IBOR curve. Known: "
        f"{', '.join(sorted(IBOR_CURVES))}."
    )


def par_grid_tags(spec: IborCurveSpec, tenors: Optional[Sequence[str]] = None) -> List[str]:
    """Every ``PAR`` tag for this curve, in tenor order."""
    from MDP.CitiVelocityExcel.tags import swap_libor_par_grid

    import warnings

    with warnings.catch_warnings():
        # The per-currency coverage warning is right, and is already recorded on
        # IBOR_CURVES; re-raising it once per fetched window is noise.
        warnings.simplefilter("ignore")
        return swap_libor_par_grid(spec.citi_currency, tenors=tenors)


@dataclass
class IborCurveResult:
    """A solved projection curve and the provenance a reader needs to trust it."""

    curve: Any
    solver: Any
    discounting: str
    discount_curve_name: Optional[str]
    tenors: Tuple[str, ...] = ()
    node_dates: Tuple[Any, ...] = ()
    max_reprice_error_bp: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_self_discounted(self) -> bool:
        return self.discounting == "self"


_UNIT_YEARS = {"D": 1.0 / 365.25, "W": 7.0 / 365.25, "M": 1.0 / 12.0, "Y": 1.0}


def _tenor_years(tenor: str) -> float:
    text = str(tenor).strip().upper()
    try:
        return float(text[:-1]) * _UNIT_YEARS[text[-1]]
    except (ValueError, KeyError, IndexError):
        return math.inf


def _ordered(par_rates: Mapping[str, float]) -> List[Tuple[str, float]]:
    clean = [
        (str(t).strip().upper(), float(v))
        for t, v in par_rates.items()
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    clean.sort(key=lambda kv: _tenor_years(kv[0]))
    return [kv for kv in clean if math.isfinite(_tenor_years(kv[0]))]


def build_rl_ibor_curve(
    *,
    par_rates: Union[Mapping[str, float], "pd.Series"],
    ref_date: Any,
    curve_name: str = "EUR-EURIBOR-6M",
    discount_curve: Optional[Any] = None,
    discount_curve_name: Optional[str] = None,
    curve_id: Optional[str] = None,
    interpolation: str = "log_linear",
    min_tenors: int = 4,
    func_tol: float = 1e-9,
    conv_tol: float = 1e-10,
    max_reprice_error_bp: float = 1.0,
) -> IborCurveResult:
    """Solve an IBOR projection curve against one par snapshot.

    Parameters
    ----------
    par_rates
        ``{tenor: rate}`` in PERCENT, which is the unit Citi publishes.
    discount_curve
        A solved OIS ``rl.Curve`` for the same instant, or ``None`` to
        self-discount. Passing one is what makes this a dual-curve build; the
        returned :class:`IborCurveResult` records which happened.

    Notes
    -----
    The node dates are the swaps' own termination dates, taken from the built
    instruments rather than from tenor arithmetic - the same approach the OIS
    builder uses, and the reason a curve rebuilt from stored nodes lands on the
    identical schedule.

    Each node is seeded at ``exp(-par_t * t)`` rather than at 1.0. A flat seed
    diverges outright on steep, high-rate grids (measured on MXN and ZAR in the
    OIS builder: ``max_iter`` with ``f_val: nan``). The fixed point is unchanged;
    only whether one is reached at all.
    """
    import rateslib as rl

    spec = ibor_spec_for(curve_name)
    if isinstance(par_rates, pd.Series):
        par_rates = par_rates.dropna().to_dict()
    pairs = _ordered(par_rates)
    if len(pairs) < min_tenors:
        raise ValueError(
            f"{curve_name}: {len(pairs)} usable tenor(s) at {ref_date}, need {min_tenors}. "
            f"Got {[t for t, _ in pairs]}."
        )

    ref = pd.Timestamp(ref_date).to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)
    ref = rl.dt(ref.year, ref.month, ref.day)
    cal = rl.get_calendar(spec.calendar)
    while not cal.is_bus_day(ref):
        ref = ref - datetime.timedelta(days=1)
    spot = cal.add_bus_days(ref, spec.spot_lag, True)

    fwd_id = curve_id or "ibor"
    disc_id = f"{fwd_id}_disc"

    # Build the prototypes first so the node dates come from the swaps, then sort
    # by termination: Citi's tenor axis is already ordered, but a 40Y and a 45Y
    # with the same roll can tie and a solver wants strictly increasing nodes.
    protos = [
        (tenor, rl.IRS(effective=spot, termination=tenor, spec=spec.rl_spec, fixed_rate=2.0))
        for tenor, _ in pairs
    ]
    protos.sort(key=lambda p: p[1].leg1.schedule.termination)
    tenors = [p[0] for p in protos]
    node_dates = [p[1].leg1.schedule.termination for p in protos]
    rate_of = dict(pairs)

    nodes = {ref: 1.0}
    for date_j, tenor_j in zip(node_dates, tenors):
        years = max((date_j - ref).days / 365.0, 1e-6)
        nodes[date_j] = math.exp(-float(rate_of[tenor_j]) / 100.0 * years)

    projection = rl.Curve(
        nodes=dict(nodes),
        id=fwd_id,
        convention=spec.convention,
        calendar=spec.calendar,
        modifier=spec.modifier,
        interpolation=interpolation,
    )

    if discount_curve is None:
        # Self-discounted: leg1 and leg2 both point at the projection curve, so
        # the solve has exactly as many unknowns as quotes and reproduces them.
        curves = [projection, projection, projection, projection]
        solve_curves = [projection]
        discounting = "self"
    else:
        # curves = [leg1 forecast, leg1 discount, leg2 forecast, leg2 discount].
        # Only the projection curve is solved; the OIS curve is fixed input.
        curves = [projection, discount_curve, projection, discount_curve]
        solve_curves = [projection]
        discounting = discount_curve_name or "ois"

    instruments = [
        rl.IRS(effective=spot, termination=t, spec=spec.rl_spec, curves=curves)
        for t in tenors
    ]
    s = [float(rate_of[t]) for t in tenors]

    solver = rl.Solver(
        curves=solve_curves,
        instruments=instruments,
        s=s,
        id=fwd_id,
        func_tol=func_tol,
        conv_tol=conv_tol,
    )
    status = str(solver.result.get("status", "")).upper()
    if status != "SUCCESS":
        raise RuntimeError(
            f"{curve_name}: solver returned {status!r} at ref_date={ref.date()} on "
            f"{len(tenors)} tenor(s)."
        )

    # SUCCESS stopped being proof in rateslib 2.7. Reprice the calibration set.
    worst = 0.0
    errors: Dict[str, float] = {}
    for tenor, inst, quote in zip(tenors, instruments, s):
        try:
            repriced = float(inst.rate(solver=solver))
        except Exception as exc:  # noqa: BLE001 - a tenor that cannot reprice IS the failure
            raise RuntimeError(
                f"{curve_name}: {tenor} could not be repriced off its own solved curve "
                f"at ref_date={ref.date()}: {type(exc).__name__}: {exc}"
            ) from exc
        error_bp = abs(repriced - quote) * 100.0
        errors[tenor] = error_bp
        worst = max(worst, error_bp)
    if not (worst <= max_reprice_error_bp):
        offenders = sorted(errors.items(), key=lambda kv: -kv[1])[:5]
        raise RuntimeError(
            f"{curve_name}: the solved curve misprices its own calibration swaps by "
            f"{worst:.4g} bp, over the {max_reprice_error_bp:g} bp limit, at "
            f"ref_date={ref.date()} ({discounting} discounting). Worst: "
            + ", ".join(f"{t}={e:.4g}bp" for t, e in offenders)
        )

    return IborCurveResult(
        curve=projection,
        solver=solver,
        discounting="self" if discount_curve is None else "ois",
        discount_curve_name=None if discount_curve is None else discounting,
        tenors=tuple(tenors),
        node_dates=tuple(node_dates),
        max_reprice_error_bp=worst,
        meta={
            "ref_date": ref,
            "spot": spot,
            "spec": spec.rl_spec,
            "n_tenors": len(tenors),
            "reprice_errors_bp": errors,
            # Kept so a caller re-iterating this solver over later minutes can
            # still reprice it. Without them the fast path is unverified, and a
            # speed-up that removes a guard is not a speed-up.
            "instruments": instruments,
        },
    )
