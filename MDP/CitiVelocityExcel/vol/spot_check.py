r"""The check that can fail: price the cube, invert the premium, meet Citi's quote.

A vol -> cube -> vol round trip is a **tautology**. Every interpolator in this
package is exact at its own data sites by construction, so reading a node back out
and comparing it with the quote scores 2.8e-14 bp and proves only that nobody
transformed the number in transit. It cannot see a wrong annuity, a wrong
schedule, a wrong day count, a wrong discounting convention or a strike/forward
misalignment, because **none of those touch the interpolator**.

This closes the loop instead:

1. take a real ``(expiry, tenor, offset)`` node - ATM and every OTM offset;
2. price the actual swaption at ``strike = forward + offset/1e4`` through the
   pricer object, in every requested backend;
3. invert that premium back to a normal volatility with an implementation that
   did not price it;
4. compare against **Citi's quoted volatility** for that node, broken out by
   expiry, by tenor and by offset;
5. cross-check the rateslib premium against the QuantLib premium at the same node.

Why the inverter is the one it is
---------------------------------
``Query.Base.bachelier.implied_normal_vol`` is
``ql.bachelierBlackFormulaImpliedVolChoi`` and ``ql.Swaption.impliedVolatility``
is QuantLib inverting QuantLib. Both share the pricer they would be checking, so
neither can disprove it. The inverter used here is
:func:`RVUtils.ImpliedDistribution._bachelier.bachelier_implied_vol` - a bracketed
bisection over ``scipy.stats.norm``, the only implied-vol solver in the repo with
no QuantLib in it. Receivers are converted with the module's own
``put_to_call_parity`` rather than inverted directly.

Why the annuities are crossed
-----------------------------
``premium = notional * annuity * bachelier(K, F, sigma, T)``. Inverting a
backend's own premium with that backend's own ``(F, A, T)`` cannot see an error in
``A`` - it cancels exactly. It is worse than that on the native backend, whose
:meth:`NativeSwaptionCube.annuity` is itself *backed out of its own ATM premium*,
so a self-inversion there is very nearly an identity.

So every premium is inverted twice:

``implied_vol_self_bp``
    with the pricing backend's own ``(F, A, T)``. Catches a wrong volatility read,
    a wrong strike, a wrong option formula, a wrong sign.
``implied_vol_cross_bp``
    with the **other** library's ``(F, A, T)``. Catches everything above plus a
    divergent annuity, day count, schedule or discounting between the two.

Both are compared against Citi's quote, never against each other's vol - the
anchor is the published number, so a shared misunderstanding cannot cancel.

What else is asserted
---------------------
* payer/receiver put-call parity at every node:
  ``PV(payer) - PV(receiver) == notional * annuity * (F - K)``;
* premium monotone in strike - falling for payers, rising for receivers;
* the ATM node's forward equals a forward computed straight off the curve by a
  path that does not go through the cube at all, and - where the snapshot carries
  it - Citi's own published ``RATES.OIS.<idx>.FWD.<e>.<t>``.

Verify the checker before trusting it
-------------------------------------
``tests/test_citivelo_swaption_spot_check.py`` mutates a **real** cube five ways
and asserts each one is caught: shift one node by 1 bp, transpose two tenor
slices, perturb one forward, scale one annuity by 1%, and swap payer for receiver
on one node. The last two exist because the first three only exercise the
volatility-read leg; a check that cannot fail reports success and hides exactly
what it was built to find.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData
from MDP.CitiVelocityExcel.vol.swaption_cube import (
    CitiVeloSwaptionCube,
    build_citivelo_swaption_cube,
)

__all__ = [
    "SpotCheckError",
    "DEFAULT_TOLERANCES",
    "assert_spot_check",
    "build_ql_mirror_curve",
    "format_spot_check_report",
    "node_error_matrix",
    "spot_check_frame",
    "summarise_spot_check",
]

_logger = logging.getLogger(__name__)

#: Tolerances the check is asserted against. Every one is in an explicit unit and
#: every one was set from a measured clean run on the recorded 2026-08-06 USD
#: snapshot, then loosened by a couple of orders of magnitude - not chosen to make
#: a number pass.
DEFAULT_TOLERANCES: Dict[str, float] = {
    # A price -> vol round trip. On the rateslib backends this is a pure
    # arithmetic identity and the recorded 2026-08-06 USD grid returns 3e-9 bp.
    # The QuantLib backend runs to 3e-4 bp because its engine reads the vol at
    # `atmStrike + spread` while the strike here is measured from the swaption's
    # OWN par rate, and the two anchors differ by up to 0.0017 bp (see
    # `vol_anchor_gap_bp`); the residual is that gap times the local smile slope
    # and nothing else - annuity and time to expiry were measured identical to
    # 1e-16 and 4e-10. 1e-3 bp leaves a decade of headroom over the worst
    # observed node and still catches a hundredth of a basis point.
    "implied_vol_self_bp": 1e-3,
    # Adds everything the two libraries disagree on in (forward, annuity, tte).
    # Measured on the recorded grid against two independently bootstrapped
    # curves: 0.21 bp, all of it at 3M x 30Y +/-200 bp. Mirror the QuantLib curve
    # onto the rateslib nodes and it collapses to 2.9e-4 bp - identical to the
    # self residual - because the two libraries then agree on the forward to
    # 2e-13 bp and on the annuity to 5e-16 relative. So the cross residual is
    # ENTIRELY the curve bootstrap and NONE of it is the swaption: the schedules,
    # day counts and discounting match exactly.
    #
    # It is 0.2 bp rather than 0.0002 bp because a 3M option 200 bp in the money
    # has almost no vega - phi(3.45) ~ 0.001 - so the 3.5e-4 bp forward
    # difference has to be absorbed by a large volatility move. That is a real
    # property of the wings, not a defect, and it is why the wings are broken out
    # separately in the report. Pass `mirror_ql_curve=True` when the question is
    # about schedules rather than about curves.
    "implied_vol_cross_bp": 0.5,
    # PV(payer) - PV(receiver) against notional * annuity * (F - K), relative to
    # the annuity leg. Clean run: 4e-14.
    "parity_rel": 1e-9,
    # |ql premium - rl premium| / |rl premium|. Clean run: 3.3e-5 on separately
    # bootstrapped curves, 2e-8 on the mirrored one.
    "backend_price_rel": 1e-4,
    # Where the QuantLib surface anchors its strike spreads versus the
    # underlying's own par rate. Clean run: 0.0017 bp. A real anchor break - a
    # wrong swap index, a wrong settlement lag - is orders of magnitude larger.
    "vol_anchor_gap_bp": 0.05,
    # Our ATM forward against one computed straight off the curve by an
    # independent path. Clean run: 0.09 bp - the two use different roll
    # conventions for the forward start, which is a real difference and not an
    # error, so this is deliberately loose.
    "curve_forward_gap_bp": 1.0,
}

#: Reported, never asserted: Citi's published forward is an external number and a
#: gap against it is information about the curve, not a defect in this package.
CITI_FORWARD_GAP_WARN_BP = 1.0


class SpotCheckError(CitiVelocityError, AssertionError):
    """A priced-and-inverted node did not reproduce Citi's quoted volatility."""


class CitiVeloSpotCheckSetupError(CitiVelocityError, ValueError):
    """The spot check was asked for a backend it has no curve for."""


# ------------------------------------------------------------------ #
#                        the independent inverter                    #
# ------------------------------------------------------------------ #


def _implied_normal_vol_bp(
    *,
    premium: float,
    notional: float,
    annuity: float,
    strike: float,
    forward: float,
    tte: float,
    right: str,
) -> float:
    """Invert a present-valued premium to normal vol in bp, without QuantLib.

    The premium is divided by ``notional * annuity`` first, which puts it in the
    same undiscounted forward space the Bachelier formula lives in; the discount
    factor handed to the solver is therefore 1.0 and the annuity is the *only*
    thing carrying discounting. That is exactly what makes crossing the annuities
    a test of them.
    """
    from RVUtils.ImpliedDistribution._bachelier import (
        bachelier_implied_vol,
        put_to_call_parity,
    )

    from MDP.CitiVelocityExcel.vol.rl_cube import _right

    if not (math.isfinite(annuity) and annuity > 0.0 and notional > 0.0):
        return float("nan")
    unit = float(premium) / (float(notional) * float(annuity))
    if _right(right) == "P":
        # The solver inverts CALLS only; a receiver is the put. Converting with
        # parity rather than writing a second solver keeps the inverter single
        # and makes a payer/receiver mix-up visible instead of self-cancelling.
        unit = put_to_call_parity(unit, float(strike), float(forward), 1.0)
    return bachelier_implied_vol(unit, float(strike), float(forward), float(tte), 1.0) * 1e4


# ------------------------------------------------------------------ #
#                        the mirrored QuantLib curve                 #
# ------------------------------------------------------------------ #


#: A ``ql.DiscountCurve`` carrying a rateslib curve's own discount factors. Lives
#: in :mod:`MDP.CitiVelocityExcel.curves.ql_builder` because the Citi Velocity
#: CurveStore serves rateslib curves and nothing else, so a QuantLib engine
#: sometimes has no other way to price off the Citi curve. Re-exported here
#: because the cross-backend leg of this check is what it was built for.
from MDP.CitiVelocityExcel.curves.ql_builder import build_ql_mirror_curve  # noqa: E402


# ------------------------------------------------------------------ #
#                          independent forwards                      #
# ------------------------------------------------------------------ #


def _anchor_gap_bp(cube_obj: CitiVeloSwaptionCube, expiry: str, tenor: str) -> float:
    """Where the surface anchors its strike spreads, versus the swap's own forward.

    QuantLib's ``SwaptionVolatilityCube`` measures every spread from
    ``atmStrike``, which it derives from an ``OvernightIndexedSwapIndex`` whose
    fixed-leg conventions are the index's defaults, not the Citi row the swaption
    is built on. The gap is small - 0.0017 bp at 10Yx30Y on the recorded snapshot,
    2e-7 bp at 1Yx2Y - but it is exactly and entirely what the QuantLib backend's
    self-inversion residual is: gap times the local smile slope. Reported so that
    residual has a name instead of looking like a timing bug.

    ``NaN`` on the rateslib backends, whose strike axis is bp-from-forward and has
    no separate anchor to disagree with.
    """
    if not cube_obj.is_quantlib:
        return float("nan")
    try:
        return float(cube_obj.inner.forward_diagnostics(str(expiry), str(tenor))["gap_bp"])
    except Exception:  # noqa: BLE001 - a diagnostic that fails must not fail the check
        return float("nan")


def _curve_forward_decimal(cube_obj: CitiVeloSwaptionCube, expiry: str, tenor: str) -> float:
    """A forward computed off the curve without going through the pricer.

    Uses the curve package's own ``forward_rate`` / ``ql_forward_rate``, which
    build their swap as ``spot + expiry`` adjusted FOLLOWING rather than as
    ``option date + settlement lag``. The two rules coincide most of the time and
    differ by a day around month ends, which is why the tolerance on this is a
    full basis point: it is a sanity check on the level, not a schedule check.
    """
    from MDP.CitiVelocityExcel.curves import forward_rate, ql_forward_rate

    if cube_obj.is_quantlib:
        curve = cube_obj.ql_curve
        if hasattr(curve, "conventions"):
            return float(ql_forward_rate(curve, forward=str(expiry), tenor=str(tenor))) / 100.0
        return float("nan")
    curve = cube_obj.rl_curve
    if getattr(curve, "meta", None) is None:
        return float("nan")
    try:
        return float(forward_rate(curve, forward=str(expiry), tenor=str(tenor))) / 100.0
    except Exception:  # noqa: BLE001 - a curve without provenance simply cannot say
        return float("nan")


# ------------------------------------------------------------------ #
#                              the check                             #
# ------------------------------------------------------------------ #


def spot_check_frame(
    *,
    cube: SwaptionCubeData,
    rl_curve: Any = None,
    ql_curve: Any = None,
    cube_obj: Optional[CitiVeloSwaptionCube] = None,
    backends: Sequence[str] = ("rl-native", "ql"),
    citi_index: Optional[str] = None,
    notional: float = 1e8,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets: Optional[Sequence[float]] = None,
    rights: Sequence[str] = ("payer", "receiver"),
    citi_forwards: Optional[Dict[Tuple[str, str], float]] = None,
    mirror_ql_curve: bool = False,
) -> pd.DataFrame:
    """Price, invert and compare every requested node. One row per node and right.

    Parameters
    ----------
    cube
        The Citi cube data.
    rl_curve, ql_curve
        Curves for the rateslib and QuantLib backends. ``ql_curve=None`` with
        ``mirror_ql_curve=True`` builds one from ``rl_curve``'s own nodes - see
        :func:`build_ql_mirror_curve`.
    cube_obj
        An already-built :class:`CitiVeloSwaptionCube` to reuse instead of
        building one.
    backends
        Which backends to price through. At least two, from different libraries,
        for the cross-inversion and the cross-backend price check to say anything.
    citi_forwards
        ``{(expiry, tenor): percent}`` from ``RATES.OIS.<idx>.FWD.<e>.<t>``, if
        the snapshot carries them. Reported, never asserted.

    Returns
    -------
    pandas.DataFrame
        Columns: ``backend expiry tenor offset_bp right quoted_vol_bp forward
        strike annuity tte pv premium implied_vol_self_bp implied_vol_cross_bp
        err_self_bp err_cross_bp parity_err parity_rel curve_forward
        curve_forward_gap_bp citi_forward citi_forward_gap_bp``, plus
        ``backend_price_rel`` filled where two libraries priced the same node.
    """
    if ql_curve is None and mirror_ql_curve and rl_curve is not None:
        ql_curve = build_ql_mirror_curve(
            getattr(rl_curve, "rl_pricing_curve", None) or rl_curve
        )

    base = cube_obj or build_citivelo_swaption_cube(
        cube=cube,
        rl_curve=rl_curve,
        ql_curve=ql_curve,
        backend=str(backends[0]),
        citi_index=citi_index,
        notional=notional,
    )
    wanted = [b for b in backends]
    missing = [b for b in wanted if b not in base.backends_available]
    if missing:
        raise CitiVeloSpotCheckSetupError(
            f"Backend(s) {missing} are not available on this cube (have "
            f"{base.backends_available}). Pass the curve each one needs."
        )
    objs = {b: base.with_backend(b) for b in wanted}

    exps = list(expiries) if expiries else cube.expiries()
    tens = list(tenors) if tenors else cube.tenors()
    offs = [float(o) for o in (offsets if offsets is not None else cube.offsets())]

    # (F, A, T) per backend per point, so the cross-inversion has something to
    # cross with and every backend is measured on the same grid.
    points: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    for name, obj in objs.items():
        for expiry in exps:
            for tenor in tens:
                points[(name, expiry, tenor)] = (
                    obj.forward(expiry, tenor),
                    obj.annuity(expiry, tenor),
                    obj.time_to_expiry(expiry),
                )

    def _cross_of(name: str) -> Optional[str]:
        """The other library's backend, if one was asked for."""
        from MDP.CitiVelocityExcel.vol.swaption_cube import BACKEND_LIBRARY

        mine = BACKEND_LIBRARY[name]
        for other in wanted:
            if BACKEND_LIBRARY[other] != mine:
                return other
        return None

    rows: List[Dict[str, Any]] = []
    for name, obj in objs.items():
        cross = _cross_of(name)
        for expiry in exps:
            for tenor in tens:
                fwd, ann, tte = points[(name, expiry, tenor)]
                x_fwd, x_ann, x_tte = points.get((cross, expiry, tenor), (fwd, ann, tte)) if cross else (fwd, ann, tte)
                curve_fwd = _curve_forward_decimal(obj, expiry, tenor)
                anchor_gap = _anchor_gap_bp(obj, expiry, tenor)
                citi_fwd = None
                if citi_forwards:
                    raw = citi_forwards.get((str(expiry), str(tenor)))
                    citi_fwd = float(raw) / 100.0 if raw is not None else None
                for off in offs:
                    quoted = float(cube.vol(expiry, tenor, off))
                    strike = fwd + off / 1e4
                    pv_by_right: Dict[str, float] = {}
                    for right in rights:
                        pv = obj.price(expiry, tenor, strike, right=right, notional=notional)
                        pv_by_right[right] = pv
                        iv_self = _implied_normal_vol_bp(
                            premium=pv,
                            notional=notional,
                            annuity=ann,
                            strike=strike,
                            forward=fwd,
                            tte=tte,
                            right=right,
                        )
                        iv_cross = _implied_normal_vol_bp(
                            premium=pv,
                            notional=notional,
                            annuity=x_ann,
                            strike=strike,
                            forward=x_fwd,
                            tte=x_tte,
                            right=right,
                        )
                        rows.append(
                            {
                                "backend": name,
                                "cross_backend": cross,
                                "expiry": expiry,
                                "tenor": tenor,
                                "offset_bp": off,
                                "right": right,
                                "quoted_vol_bp": quoted,
                                "model_vol_bp": obj.normal_vol(expiry, tenor, offset_bp=off),
                                "forward": fwd,
                                "strike": strike,
                                "annuity": ann,
                                "tte": tte,
                                "pv": pv,
                                "implied_vol_self_bp": iv_self,
                                "implied_vol_cross_bp": iv_cross,
                                "err_self_bp": iv_self - quoted,
                                "err_cross_bp": iv_cross - quoted,
                                "vol_anchor_gap_bp": anchor_gap,
                                "curve_forward": curve_fwd,
                                "curve_forward_gap_bp": (fwd - curve_fwd) * 1e4
                                if curve_fwd == curve_fwd
                                else float("nan"),
                                "citi_forward": citi_fwd if citi_fwd is not None else float("nan"),
                                "citi_forward_gap_bp": (fwd - citi_fwd) * 1e4
                                if citi_fwd is not None
                                else float("nan"),
                            }
                        )
                    if "payer" in pv_by_right and "receiver" in pv_by_right:
                        expected = notional * ann * (fwd - strike)
                        actual = pv_by_right["payer"] - pv_by_right["receiver"]
                        scale = max(abs(expected), abs(pv_by_right["payer"]), 1.0)
                        for row in rows[-len(rights) :]:
                            row["parity_err"] = actual - expected
                            row["parity_rel"] = abs(actual - expected) / scale

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if "parity_err" not in frame:
        frame["parity_err"] = np.nan
        frame["parity_rel"] = np.nan

    frame = _attach_backend_price_diff(frame)
    frame = _attach_monotonicity(frame)
    return frame


def _attach_backend_price_diff(frame: pd.DataFrame) -> pd.DataFrame:
    """``|pv - pv_other| / |pv|`` between the two libraries at the same node."""
    from MDP.CitiVelocityExcel.vol.swaption_cube import BACKEND_LIBRARY

    frame = frame.copy()
    frame["library"] = frame["backend"].map(BACKEND_LIBRARY)
    key = ["expiry", "tenor", "offset_bp", "right"]
    pivot = frame.pivot_table(index=key, columns="library", values="pv", aggfunc="first")
    if not {"rl", "ql"}.issubset(pivot.columns):
        frame["backend_price_diff"] = np.nan
        frame["backend_price_rel"] = np.nan
        return frame
    diff = (pivot["ql"] - pivot["rl"]).rename("backend_price_diff")
    denom = pivot["rl"].abs().where(lambda s: s > 0.0, other=np.nan)
    rel = (diff.abs() / denom).rename("backend_price_rel")
    joined = pd.concat([diff, rel], axis=1).reset_index()
    return frame.merge(joined, on=key, how="left")


def _attach_monotonicity(frame: pd.DataFrame) -> pd.DataFrame:
    """Flag any (backend, point, right) whose premium is not monotone in strike.

    A payer is worth less the higher the strike and a receiver more; a smile steep
    enough to break that is an arbitrage, and an off-by-one in the offset axis
    breaks it immediately.
    """
    frame = frame.copy()
    frame["monotonic_violation"] = 0.0
    for (backend, expiry, tenor, right), block in frame.groupby(
        ["backend", "expiry", "tenor", "right"], sort=False
    ):
        ordered = block.sort_values("offset_bp")
        pv = ordered["pv"].to_numpy(dtype=float)
        steps = np.diff(pv)
        sign = -1.0 if str(right).lower().startswith(("pay", "c")) else 1.0
        bad = np.maximum(-sign * steps, 0.0)
        worst = float(bad.max()) if bad.size else 0.0
        frame.loc[ordered.index, "monotonic_violation"] = worst / max(
            float(np.abs(pv).max()), 1.0
        )
    return frame


# ------------------------------------------------------------------ #
#                            the summary                             #
# ------------------------------------------------------------------ #


def summarise_spot_check(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Break the error out by expiry, by tenor and by offset. A max hides a corner.

    Returns ``{'by_expiry': ..., 'by_tenor': ..., 'by_offset': ...,
    'by_backend': ..., 'worst': ...}``, all in bp of volatility.
    """
    if frame.empty:
        return {k: pd.DataFrame() for k in ("by_expiry", "by_tenor", "by_offset", "by_backend", "worst")}

    work = frame.copy()
    work["abs_self"] = work["err_self_bp"].abs()
    work["abs_cross"] = work["err_cross_bp"].abs()

    def _agg(by: str) -> pd.DataFrame:
        out = work.groupby(by, sort=False).agg(
            n=("abs_self", "size"),
            mean_self_bp=("abs_self", "mean"),
            max_self_bp=("abs_self", "max"),
            mean_cross_bp=("abs_cross", "mean"),
            max_cross_bp=("abs_cross", "max"),
            max_parity_rel=("parity_rel", "max"),
        )
        return out

    order_offsets = sorted(work["offset_bp"].unique())
    by_offset = _agg("offset_bp").reindex(order_offsets)
    worst = work.nlargest(min(10, len(work)), "abs_cross")[
        [
            "backend",
            "expiry",
            "tenor",
            "offset_bp",
            "right",
            "quoted_vol_bp",
            "implied_vol_self_bp",
            "implied_vol_cross_bp",
            "err_self_bp",
            "err_cross_bp",
            "pv",
        ]
    ]
    return {
        "by_expiry": _agg("expiry"),
        "by_tenor": _agg("tenor"),
        "by_offset": by_offset,
        "by_backend": _agg("backend"),
        "worst": worst,
    }


def node_error_matrix(
    frame: pd.DataFrame,
    *,
    column: str = "err_cross_bp",
    backend: Optional[str] = None,
    right: str = "payer",
) -> pd.DataFrame:
    """The per-node table: ``(expiry, tenor)`` rows against strike offsets.

    One cell per ``(expiry, tenor, offset)``, in bp of volatility - ATM in the
    ``0.0`` column and every OTM offset beside it. This is the shape the error
    actually has: a summary by expiry and a summary by offset each average over
    the other axis, and the interesting structure here (short expiries, long
    tails, deep wings) lives in one corner of the grid rather than along either
    margin.
    """
    if frame.empty:
        return pd.DataFrame()
    work = frame
    if backend is not None:
        work = work[work["backend"] == backend]
    if right is not None:
        work = work[work["right"] == right]
    if work.empty:
        return pd.DataFrame()
    table = work.pivot_table(
        index=["expiry", "tenor"], columns="offset_bp", values=column, aggfunc="max"
    )
    order = [
        (e, t)
        for e in dict.fromkeys(frame["expiry"])
        for t in dict.fromkeys(frame["tenor"])
        if (e, t) in table.index
    ]
    return table.reindex(order)


def assert_spot_check(
    frame: pd.DataFrame,
    *,
    tolerances: Optional[Dict[str, float]] = None,
    check_monotonicity: bool = True,
) -> Dict[str, float]:
    """Raise :class:`SpotCheckError` unless every node is inside tolerance.

    Returns the observed maxima, so a passing run still reports what it measured.

    Raises
    ------
    SpotCheckError
        Naming the failing metric, its tolerance, the observed value and the node
        it came from. A failure message that does not name the node is a failure
        message that costs an hour.
    """
    if frame.empty:
        raise SpotCheckError("The spot check produced no rows; there was nothing to check.")

    tol = dict(DEFAULT_TOLERANCES)
    tol.update(tolerances or {})
    observed: Dict[str, float] = {}
    failures: List[str] = []

    checks = [
        ("implied_vol_self_bp", frame["err_self_bp"].abs(), "bp of vol"),
        ("implied_vol_cross_bp", frame["err_cross_bp"].abs(), "bp of vol"),
        ("parity_rel", frame["parity_rel"].abs(), "relative"),
    ]
    if "backend_price_rel" in frame and frame["backend_price_rel"].notna().any():
        checks.append(("backend_price_rel", frame["backend_price_rel"].abs(), "relative"))
    if "vol_anchor_gap_bp" in frame and frame["vol_anchor_gap_bp"].notna().any():
        checks.append(("vol_anchor_gap_bp", frame["vol_anchor_gap_bp"].abs(), "bp of rate"))
    if "curve_forward_gap_bp" in frame and frame["curve_forward_gap_bp"].notna().any():
        checks.append(("curve_forward_gap_bp", frame["curve_forward_gap_bp"].abs(), "bp of rate"))

    for name, series in [(n, s) for n, s, _ in checks]:
        finite = series.dropna()
        observed[name] = float(finite.max()) if len(finite) else float("nan")

    nan_vols = int(frame["implied_vol_self_bp"].isna().sum() + frame["implied_vol_cross_bp"].isna().sum())
    if nan_vols:
        bad = frame[frame["implied_vol_self_bp"].isna() | frame["implied_vol_cross_bp"].isna()]
        failures.append(
            f"{nan_vols} premium(s) could not be inverted at all - the bisection returned NaN, "
            f"which means the premium sat below intrinsic or above the sigma->inf limit. "
            f"First: {_describe_node(bad.iloc[0])}."
        )

    for name, series, unit in checks:
        limit = tol.get(name)
        if limit is None:
            continue
        finite = series.dropna()
        if not len(finite):
            continue
        worst = float(finite.max())
        if worst > limit:
            node = frame.loc[finite.idxmax()]
            failures.append(
                f"{name}: worst {worst:.6g} {unit} > tolerance {limit:g} at {_describe_node(node)}."
            )

    if check_monotonicity and "monotonic_violation" in frame:
        worst = float(frame["monotonic_violation"].max())
        observed["monotonic_violation"] = worst
        if worst > 1e-12:
            node = frame.loc[frame["monotonic_violation"].idxmax()]
            failures.append(
                f"premium is not monotone in strike: violation {worst:.3e} of the largest premium "
                f"on that smile, at {_describe_node(node)}. A payer must be worth less the higher "
                "the strike; an off-by-one on the offset axis breaks this immediately."
            )

    if "citi_forward_gap_bp" in frame and frame["citi_forward_gap_bp"].notna().any():
        worst = float(frame["citi_forward_gap_bp"].abs().max())
        observed["citi_forward_gap_bp"] = worst
        if worst > CITI_FORWARD_GAP_WARN_BP:
            _logger.warning(
                "our ATM forward is up to %.3f bp from Citi's published forward. Citi measures its "
                "strike offsets from ITS forward, so the whole smile is shifted along the strike "
                "axis by that much - node vols still round-trip, a strike-quoted price does not.",
                worst,
            )

    if failures:
        raise SpotCheckError(
            "The Citi swaption cube did not reproduce its own quotes when priced and inverted:\n  "
            + "\n  ".join(failures)
            + "\n\nThis is a PRICING check, not an interpolation check: it inverts the premium "
            "with a bisection that shares no code with the pricer, and crosses the annuities "
            "between the two libraries, so a wrong annuity, schedule, day count or "
            "strike/forward alignment shows up here and nowhere else."
        )
    return observed


def _describe_node(row: Any) -> str:
    return (
        f"{row.get('backend', '?')} {row.get('expiry', '?')}x{row.get('tenor', '?')} "
        f"{float(row.get('offset_bp', float('nan'))):+g}bp {row.get('right', '?')} "
        f"(quoted {float(row.get('quoted_vol_bp', float('nan'))):.4f}bp, "
        f"self {float(row.get('implied_vol_self_bp', float('nan'))):.4f}bp, "
        f"cross {float(row.get('implied_vol_cross_bp', float('nan'))):.4f}bp)"
    )


def format_spot_check_report(frame: pd.DataFrame, *, title: str = "") -> str:
    """A printable per-node report: the breakdowns, then the worst nodes."""
    if frame.empty:
        return "(no rows)"
    parts: List[str] = []
    if title:
        parts.append(title)
        parts.append("=" * max(len(title), 8))
    summary = summarise_spot_check(frame)
    for label, key in (
        ("by backend", "by_backend"),
        ("by expiry", "by_expiry"),
        ("by swap tenor", "by_tenor"),
        ("by strike offset", "by_offset"),
    ):
        parts.append(f"\nimplied-vol error vs Citi's quote, {label} (bp of vol):")
        parts.append(summary[key].to_string(float_format=lambda v: f"{v:11.3e}"))
    for backend in dict.fromkeys(frame["backend"]):
        table = node_error_matrix(frame, backend=backend, right="payer")
        if table.empty:
            continue
        parts.append(
            f"\nPER NODE, {backend} payers: cross-inverted implied vol minus Citi's quote "
            "(bp of vol), ATM in the 0.0 column:"
        )
        parts.append(table.to_string(float_format=lambda v: f"{v:10.2e}"))
    parts.append("\nworst 10 nodes by |cross-inverted vol - quoted vol|:")
    parts.append(summary["worst"].to_string(index=False))

    extras: List[str] = []
    if "backend_price_rel" in frame and frame["backend_price_rel"].notna().any():
        extras.append(
            f"max relative rateslib-vs-QuantLib premium difference : "
            f"{frame['backend_price_rel'].abs().max():.3e}"
        )
    if "parity_rel" in frame:
        extras.append(f"max put-call parity error (relative)                : {frame['parity_rel'].abs().max():.3e}")
    if "monotonic_violation" in frame:
        extras.append(f"max monotonicity violation (relative)               : {frame['monotonic_violation'].max():.3e}")
    if "vol_anchor_gap_bp" in frame and frame["vol_anchor_gap_bp"].notna().any():
        extras.append(f"max |QuantLib atmStrike - underlying forward|        : {frame['vol_anchor_gap_bp'].abs().max():.5f} bp")
    if "curve_forward_gap_bp" in frame and frame["curve_forward_gap_bp"].notna().any():
        extras.append(f"max |our forward - curve forward|                   : {frame['curve_forward_gap_bp'].abs().max():.3f} bp")
    if "citi_forward_gap_bp" in frame and frame["citi_forward_gap_bp"].notna().any():
        extras.append(f"max |our forward - CITI's published forward|        : {frame['citi_forward_gap_bp'].abs().max():.3f} bp")
    if extras:
        parts.append("")
        parts.extend(extras)
    return "\n".join(parts)
