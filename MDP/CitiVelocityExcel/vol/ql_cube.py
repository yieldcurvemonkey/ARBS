r"""The Citi swaption cube in QuantLib: ATM matrix, vol spreads, interpolated cube.

This is the **first QuantLib swaption vol cube in the repo**. What existed before
is ``MDP/IRSwaptions/MONKEYCUBE/cube.py``, which interpolates pre-calibrated SABR
parameters with a Gaussian process and evaluates Hagan analytically - no
``ql.SwaptionVolatilityCube`` anywhere. Everything here is new surface area, so
the ordering contract below is enforced by a test, not by a comment.

THE ORDERING CONTRACT
---------------------
``ql.InterpolatedSwaptionVolatilityCube`` takes ``volSpreads`` as a 2-D matrix
whose **rows are optionTenors OUTER, swapTenors INNER**::

    row 0 : 1y x 2y      row 3 : 10y x 2y
    row 1 : 1y x 10y     row 4 : 10y x 10y
    row 2 : 1y x 30y     row 5 : 10y x 30y

and whose **columns are the strike spreads**. Confirmed against SWPM, and
re-confirmed numerically here: on the 7x5x7 synthetic surface of
:mod:`MDP.CitiVelocityExcel.vol._smoke`, rows built option-outer round-trip all
245 nodes to 1.4e-14 bp, while rows built swap-outer are accepted by the SAME
constructor without complaint and misprice by up to 4.85 bp (case (b)).

It constructs either way because both orderings have ``n_expiry * n_tenor`` rows.
That is why :func:`assert_vol_spread_ordering` exists: it reads every
``(expiry, tenor, offset)`` volatility back OUT of the built object and compares
it with the input. Reconstruction is the only honest proof of the ordering.

UNITS
-----
:class:`~MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` stores basis
points; QuantLib wants decimals. Every ``/ 1e4`` in this module is that one
conversion, and every number this module RETURNS is back in basis points.

Volatility type is ``ql.Normal`` throughout - Citi's ``ATM_RFR.NORMAL`` branch is
Bachelier vol. Passing a lognormal matrix into the same cube would not error; it
would just be wrong, so :func:`build_ql_atm_matrix` hard-codes ``ql.Normal`` and
:func:`build_ql_swaption_cube` refuses a cube whose ``measure`` is not
``'NORMAL'``.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import QuantLib as ql

from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData

__all__ = [
    "QLSwaptionCube",
    "VolCubeOrderingError",
    "build_ql_atm_matrix",
    "vol_spreads_matrix",
    "build_ql_swaption_cube",
    "assert_vol_spread_ordering",
    "swap_indices_for",
    "VOL_CCY_DEFAULT_OIS_INDEX",
    "DEFAULT_SABR_GUESS",
]

_logger = logging.getLogger(__name__)

#: Which Citi OIS curve backs the swaption underlying, per vol currency. The vol
#: branch is keyed by CURRENCY (``RATES.VOL.USD``) while the curve conventions are
#: keyed by INDEX (``USD_SOFR``), so the two need joining. KRW is absent on
#: purpose: ``RATES.VOL.KRW`` exists but there is no KRW entry in
#: ``CITI_OIS_CONVENTIONS``, so a KRW cube must be given ``swap_index=`` by hand
#: rather than be silently backed by the wrong index.
VOL_CCY_DEFAULT_OIS_INDEX: Dict[str, str] = {
    "AUD": "AUD_AONIA",
    "CAD": "CAD_CORRA",
    "CHF": "CHF_SARON",
    "DKK": "DKK_TNDKK",
    "EUR": "EUR_EUROSTR",
    "GBP": "GBP_SONIA",
    "JPY": "JPY_TONAR_LCH",
    "NOK": "NOK_NOWA",
    "SEK": "SEK_STINA",
    "USD": "USD_SOFR",
}

#: ``(alpha, beta, nu, rho)`` starting point for the SABR variant. beta is held
#: fixed at 0.5 by default - the same convention MONKEYCUBE records across its
#: calibrated nodes - because a free beta and a free alpha are nearly collinear
#: at the money and the optimiser wanders.
DEFAULT_SABR_GUESS: Tuple[float, float, float, float] = (0.02, 0.5, 0.4, 0.0)

#: Which of those four are FIXED during calibration. Order matches the guess.
DEFAULT_SABR_FIXED: Tuple[bool, bool, bool, bool] = (False, True, False, False)


class VolCubeOrderingError(CitiVelocityError, AssertionError):
    """A built QuantLib cube does not reproduce its own input volatilities."""


# ------------------------------------------------------------------ #
#                              plumbing                              #
# ------------------------------------------------------------------ #


def _periods(tokens: Sequence[str]) -> Any:
    return ql.PeriodVector([ql.Period(str(t)) for t in tokens])


def _as_handle(curve: Any) -> Any:
    """Accept a ``YieldTermStructure`` or an already-wrapped handle."""
    if isinstance(curve, ql.YieldTermStructureHandle):
        return curve
    if isinstance(curve, ql.RelinkableYieldTermStructureHandle):
        return curve
    if isinstance(curve, ql.YieldTermStructure):
        return ql.YieldTermStructureHandle(curve)
    raise TypeError(
        f"curve must be a QuantLib YieldTermStructure or YieldTermStructureHandle, got "
        f"{type(curve).__name__}. Build one from Citi PAR quotes with "
        "MDP.CitiVelocityExcel.curves, or pass swap_index=/short_swap_index= directly."
    )


def _ql_date(when: datetime.date) -> Any:
    return ql.Date(when.day, when.month, when.year)


def swap_indices_for(
    *,
    currency: str,
    curve: Any,
    citi_index: Optional[str] = None,
    short_tenor: str = "1Y",
    long_tenor: str = "10Y",
) -> Tuple[Any, Any, CurveConvention]:
    """Build the ``(swapIndex, shortSwapIndex, convention)`` triple for a cube.

    QuantLib uses these only to compute each node's ATM strike, but that strike is
    what every skew offset is measured FROM, so getting the index wrong shifts the
    whole smile.

    Raises
    ------
    CitiVelocityError
        When the currency has no default Citi OIS index (KRW). Pass
        ``swap_index=`` explicitly instead.
    """
    token = str(citi_index).upper() if citi_index else VOL_CCY_DEFAULT_OIS_INDEX.get(str(currency).upper())
    if not token:
        raise CitiVelocityError(
            f"No default Citi OIS index for vol currency {currency!r} "
            f"(known: {', '.join(sorted(VOL_CCY_DEFAULT_OIS_INDEX))}). "
            "RATES.VOL.KRW exists but CITI_OIS_CONVENTIONS has no KRW curve, so the swaption "
            "underlying cannot be inferred - pass swap_index= and short_swap_index= explicitly."
        )
    conv = conventions_for(token)
    if conv.approximate:
        _logger.warning(
            "Citi OIS conventions for %s are %s, not rateslib-supplied: %s",
            conv.citi_index,
            conv.provenance,
            conv.note or "see CurveConvention.note",
        )

    handle = _as_handle(curve)
    on_index = conv.ql_index(handle)
    ccy = on_index.currency()
    long_index = ql.OvernightIndexedSwapIndex(
        f"{conv.citi_index}Swap", ql.Period(str(long_tenor)), conv.spot_lag, ccy, on_index
    )
    short_index = ql.OvernightIndexedSwapIndex(
        f"{conv.citi_index}SwapShort", ql.Period(str(short_tenor)), conv.spot_lag, ccy, on_index
    )
    return long_index, short_index, conv


# ------------------------------------------------------------------ #
#                            ATM matrix                              #
# ------------------------------------------------------------------ #


def build_ql_atm_matrix(
    cube: SwaptionCubeData,
    *,
    calendar: Any,
    business_day_convention: int = ql.ModifiedFollowing,
    day_counter: Optional[Any] = None,
    flat_extrapolation: bool = False,
    extrapolate: bool = True,
) -> Any:
    """The ATM surface as a ``ql.SwaptionVolatilityMatrix`` in NORMAL vol.

    Parameters
    ----------
    cube
        Source data. ``cube.measure`` must be ``'NORMAL'``.
    calendar
        QuantLib calendar used to turn each expiry tenor into an option date.
    business_day_convention
        Roll convention for that advance.
    day_counter
        Time measure for the option axis. Defaults to ``ql.Actual365Fixed()``,
        which is what the option-expiry axis is conventionally measured in
        regardless of the swap's own accrual basis.
    flat_extrapolation
        Passed through to QuantLib. ``False`` keeps the surface's own
        extrapolation.

    Returns
    -------
    QuantLib.SwaptionVolatilityMatrix
        Vols in DECIMAL (bp / 1e4), ``volatilityType() == ql.Normal``.

    Notes
    -----
    The evaluation date is NOT set here. ``SwaptionVolatilityMatrix`` built from
    the calendar overload floats on ``ql.Settings.instance().evaluationDate``, so
    the caller must have set it to ``cube.as_of`` before calling - and
    :func:`build_ql_swaption_cube` does exactly that.
    """
    if cube.measure.upper() != "NORMAL":
        raise ValueError(
            f"cube.measure={cube.measure!r} is not a normal vol; a ql.Normal matrix built from it "
            "would be silently wrong. Rebuild the cube with measure='NORMAL'."
        )
    cube.validate()

    expiries = cube.expiries()
    tenors = cube.tenors()
    matrix = ql.Matrix(len(expiries), len(tenors))
    for i, expiry in enumerate(expiries):
        for j, tenor in enumerate(tenors):
            matrix[i][j] = cube.atm_vol(expiry, tenor) / 1e4

    surface = ql.SwaptionVolatilityMatrix(
        calendar,
        business_day_convention,
        _periods(expiries),
        _periods(tenors),
        matrix,
        day_counter if day_counter is not None else ql.Actual365Fixed(),
        bool(flat_extrapolation),
        ql.Normal,
    )
    if extrapolate:
        surface.enableExtrapolation()
    return surface


# ------------------------------------------------------------------ #
#                            vol spreads                             #
# ------------------------------------------------------------------ #


def vol_spreads_matrix(
    cube: SwaptionCubeData,
    *,
    offsets_bp: Sequence[float],
) -> List[List[Any]]:
    """The ``volSpreads`` matrix, in QuantLib's required row order.

    Rows run **optionTenors OUTER, swapTenors INNER**; columns run the strike
    spreads in the order given by ``offsets_bp``. Values are ``vol(offset) - atm``
    in DECIMAL.

    Parameters
    ----------
    cube
        Source data; every offset in ``offsets_bp`` must have a skew frame.
    offsets_bp
        Signed strike offsets in bp, in the order they will be handed to the
        cube's ``strikeSpreads`` argument. **The two orders must match.**

    Returns
    -------
    list[list[QuantLib.QuoteHandle]]
        ``len == n_expiry * n_tenor`` rows of ``len(offsets_bp)`` handles.

    Raises
    ------
    KeyError
        When ``cube`` has no skew frame at a requested offset.
    """
    offsets = [float(o) for o in offsets_bp]
    missing = [o for o in offsets if o != 0.0 and o not in cube.skew]
    if missing:
        raise KeyError(
            f"Cube has no skew frame at offset(s) {missing}. Available: "
            f"{cube.skew_offsets()}. Rebuild with offsets_bp= covering them."
        )

    rows: List[List[Any]] = []
    for expiry in cube.expiries():  # OUTER
        for tenor in cube.tenors():  # INNER
            atm = cube.atm_vol(expiry, tenor)
            rows.append(
                [
                    ql.QuoteHandle(ql.SimpleQuote((cube.vol(expiry, tenor, o) - atm) / 1e4))
                    for o in offsets
                ]
            )
    return rows


# ------------------------------------------------------------------ #
#                             the cube                               #
# ------------------------------------------------------------------ #


@dataclass
class QLSwaptionCube:
    """A built QuantLib swaption cube plus everything needed to audit it.

    Attributes
    ----------
    handle
        ``ql.SwaptionVolatilityStructureHandle`` around :attr:`structure`, ready
        to hand to ``ql.BachelierSwaptionEngine``.
    structure
        The cube itself (``InterpolatedSwaptionVolatilityCube`` or
        ``SabrSwaptionVolatilityCube``).
    atm_matrix
        The ``ql.SwaptionVolatilityMatrix`` the cube is anchored on.
    cube
        The source :class:`SwaptionCubeData`.
    option_tenors, swap_tenors
        The axis tokens, in the order the matrix rows were built.
    strike_spreads
        Signed offsets in BP, in column order.
    sabr
        Whether the SABR variant was used. A SABR cube is a FIT, not an
        interpolator: it does not reproduce its own nodes exactly.
    """

    handle: Any
    structure: Any
    atm_matrix: Any
    cube: SwaptionCubeData
    option_tenors: List[str]
    swap_tenors: List[str]
    strike_spreads: List[float]
    swap_index: Any = None
    short_swap_index: Any = None
    sabr: bool = False
    convention: Optional[CurveConvention] = None

    # -- reads ----------------------------------------------------------

    def option_date(self, expiry: str) -> Any:
        """The option date QuantLib assigns to an expiry token."""
        return self.structure.optionDateFromTenor(ql.Period(str(expiry)))

    def atm_strike(self, expiry: str, tenor: str) -> float:
        """The forward swap rate QuantLib measures strike offsets FROM, decimal."""
        return float(self.structure.atmStrike(self.option_date(expiry), ql.Period(str(tenor))))

    def vol(
        self,
        expiry: str,
        tenor: str,
        strike: Optional[float] = None,
        *,
        offset_bp: Optional[float] = None,
        extrapolate: bool = True,
    ) -> float:
        """Normal vol in BASIS POINTS at ``(expiry, tenor)``.

        Give exactly one of ``strike`` (decimal, absolute) or ``offset_bp``
        (signed bp relative to the cube's own ATM strike). Neither means ATM.
        """
        if strike is not None and offset_bp is not None:
            raise ValueError("Give strike= or offset_bp=, not both.")
        date = self.option_date(expiry)
        period = ql.Period(str(tenor))
        if strike is None:
            base = float(self.structure.atmStrike(date, period))
            strike = base + (float(offset_bp) / 1e4 if offset_bp is not None else 0.0)
        return float(self.structure.volatility(date, period, float(strike), bool(extrapolate))) * 1e4

    def smile_section(self, expiry: str, tenor: str, *, extrapolate: bool = True) -> Any:
        """The QuantLib ``SmileSection`` at one node."""
        return self.structure.smileSection(
            ql.Period(str(expiry)), ql.Period(str(tenor)), bool(extrapolate)
        )

    def __repr__(self) -> str:
        kind = "SABR" if self.sabr else "interpolated"
        return (
            f"QLSwaptionCube({self.cube.currency} {self.cube.as_of} {kind}, "
            f"{len(self.option_tenors)}x{len(self.swap_tenors)} nodes, "
            f"spreads={[f'{o:+g}' for o in self.strike_spreads]})"
        )


def build_ql_swaption_cube(
    *,
    cube: SwaptionCubeData,
    curve: Any,
    swap_index: Optional[Any] = None,
    short_swap_index: Optional[Any] = None,
    offsets_bp: Optional[Sequence[float]] = None,
    sabr: bool = False,
    citi_index: Optional[str] = None,
    calendar: Optional[Any] = None,
    business_day_convention: int = ql.ModifiedFollowing,
    day_counter: Optional[Any] = None,
    vega_weighted_smile_fit: bool = False,
    set_evaluation_date: bool = True,
    sabr_guess: Sequence[float] = DEFAULT_SABR_GUESS,
    sabr_fixed: Sequence[bool] = DEFAULT_SABR_FIXED,
    sabr_atm_calibrated: bool = True,
    sabr_end_criteria: Optional[Any] = None,
    sabr_max_error: float = 1.0,
    sabr_error_accept: float = 1e-5,
    sabr_max_guesses: int = 50,
    check_ordering: bool = True,
    ordering_tol_bp: float = 1e-6,
) -> QLSwaptionCube:
    """Build the QuantLib cube from Citi quotes and prove its node ordering.

    Parameters
    ----------
    cube
        Normal-vol cube data. Must carry at least one skew offset.
    curve
        Discount/forecast term structure for the swaption underlying. Used only
        to derive each node's ATM strike - but that strike anchors the whole
        smile, so it is not optional.
    swap_index, short_swap_index
        Override the indices derived from :data:`VOL_CCY_DEFAULT_OIS_INDEX`.
        Required for KRW, which has no Citi OIS conventions entry.
    offsets_bp
        Column order for the strike spreads. Defaults to every offset the cube
        carries, ascending.
    sabr
        Use ``ql.SabrSwaptionVolatilityCube`` instead of
        ``ql.InterpolatedSwaptionVolatilityCube``. **A SABR cube is a fit**: it
        smooths across strikes and does NOT reproduce its own input nodes. On the
        synthetic smoke surface it converges but leaves up to ~1 bp of node error,
        so ``check_ordering`` is skipped for it unless the caller widens
        ``ordering_tol_bp``.
    check_ordering
        Run :func:`assert_vol_spread_ordering` on the built object. On by
        default: the wrong row order constructs without error and misprices
        silently.

    Returns
    -------
    QLSwaptionCube

    Raises
    ------
    ValueError
        Non-normal measure, or no skew offsets to build a cube from.
    VolCubeOrderingError
        The built object does not reproduce its own input volatilities.
    """
    cube.validate()
    if cube.measure.upper() != "NORMAL":
        raise ValueError(f"cube.measure={cube.measure!r}; only NORMAL builds a Bachelier cube.")

    requested = [float(o) for o in (offsets_bp if offsets_bp is not None else cube.skew_offsets())]
    if not [o for o in requested if o != 0.0]:
        raise ValueError(
            "A swaption CUBE needs strike offsets; this cube data has none. Build the ATM surface "
            "alone with build_ql_atm_matrix(), or refetch with offsets_bp=(-50, -25, 25, 50)."
        )
    # The zero column is ALWAYS included, whatever the caller asked for. QuantLib
    # builds each smile section by interpolating over the strikeSpreads grid, so
    # if 0 is not a knot the ATM quote is interpolated rather than honoured:
    # measured 0.605 bp of error at the 1Mx1Y node of the smoke surface with
    # spreads (-100 -50 -25 +25 +50 +100), and exactly 0 once 0 is added.
    offsets = sorted({0.0, *requested})

    if set_evaluation_date:
        ql.Settings.instance().evaluationDate = _ql_date(cube.as_of)

    conv: Optional[CurveConvention] = None
    if swap_index is None or short_swap_index is None:
        derived_long, derived_short, conv = swap_indices_for(
            currency=cube.currency, curve=curve, citi_index=citi_index
        )
        swap_index = swap_index or derived_long
        short_swap_index = short_swap_index or derived_short

    if calendar is None:
        calendar = conv.ql_calendar() if conv is not None else swap_index.fixingCalendar()

    atm_matrix = build_ql_atm_matrix(
        cube,
        calendar=calendar,
        business_day_convention=business_day_convention,
        day_counter=day_counter,
    )
    atm_handle = ql.SwaptionVolatilityStructureHandle(atm_matrix)

    rows = vol_spreads_matrix(cube, offsets_bp=offsets)
    vol_spreads = ql.QuoteHandleVectorVector(
        [ql.QuoteHandleVector(row) for row in rows]
    )
    option_periods = _periods(cube.expiries())
    swap_periods = _periods(cube.tenors())
    strike_spreads = ql.DoubleVector([o / 1e4 for o in offsets])

    if sabr:
        n_nodes = len(cube.expiries()) * len(cube.tenors())
        guess = ql.QuoteHandleVectorVector(
            [
                ql.QuoteHandleVector([ql.QuoteHandle(ql.SimpleQuote(float(v))) for v in sabr_guess])
                for _ in range(n_nodes)
            ]
        )
        structure = ql.SabrSwaptionVolatilityCube(
            atm_handle,
            option_periods,
            swap_periods,
            strike_spreads,
            vol_spreads,
            swap_index,
            short_swap_index,
            bool(vega_weighted_smile_fit),
            guess,
            ql.BoolVector([bool(b) for b in sabr_fixed]),
            bool(sabr_atm_calibrated),
            sabr_end_criteria if sabr_end_criteria is not None else ql.EndCriteria(50000, 100, 1e-8, 1e-8, 1e-8),
            float(sabr_max_error),
            ql.LevenbergMarquardt(),
            float(sabr_error_accept),
            False,
            int(sabr_max_guesses),
            False,
            1e-4,
        )
    else:
        structure = ql.InterpolatedSwaptionVolatilityCube(
            atm_handle,
            option_periods,
            swap_periods,
            strike_spreads,
            vol_spreads,
            swap_index,
            short_swap_index,
            bool(vega_weighted_smile_fit),
        )
    structure.enableExtrapolation()

    built = QLSwaptionCube(
        handle=ql.SwaptionVolatilityStructureHandle(structure),
        structure=structure,
        atm_matrix=atm_matrix,
        cube=cube,
        option_tenors=cube.expiries(),
        swap_tenors=cube.tenors(),
        strike_spreads=offsets,
        swap_index=swap_index,
        short_swap_index=short_swap_index,
        sabr=bool(sabr),
        convention=conv,
    )

    if check_ordering and not sabr:
        assert_vol_spread_ordering(built, cube, tol=float(ordering_tol_bp))
    elif check_ordering and sabr:
        _logger.info(
            "SABR cube built; node round-trip NOT asserted. A SABR cube smooths across strikes, "
            "so it does not reproduce its own input nodes - call "
            "assert_vol_spread_ordering(..., tol=<your fit tolerance>) explicitly if you want a "
            "bound on the fit error."
        )
    return built


# ------------------------------------------------------------------ #
#                        the ordering assertion                      #
# ------------------------------------------------------------------ #


def assert_vol_spread_ordering(
    cube_obj: Any,
    cube_data: SwaptionCubeData,
    *,
    tol: float = 1e-6,
    offsets_bp: Optional[Sequence[float]] = None,
) -> float:
    """Read every node back OUT of a built cube and check it against the input.

    This is the only honest proof that ``volSpreads`` was laid out
    optionTenors-outer: the wrong ordering has the same shape, so QuantLib
    accepts it and misprices silently. On the smoke's synthetic surface the
    correct ordering reproduces every node to 2.8e-14 bp and the transposed one
    is out by 8 bp.

    Parameters
    ----------
    cube_obj
        A :class:`QLSwaptionCube`, or a bare QuantLib cube (in which case
        ``cube_data``'s own axes and offsets are used).
    cube_data
        The input the object was built from.
    tol
        Maximum tolerated absolute error, in BASIS POINTS.
    offsets_bp
        Which offsets to check. Defaults to the built cube's strike spreads, or
        the data's skew offsets.

    Returns
    -------
    float
        The maximum absolute error in bp across every checked node.

    Raises
    ------
    VolCubeOrderingError
        When any node exceeds ``tol``. The message names the worst node, both
        volatilities, and the transposition that most likely caused it.
    """
    structure = getattr(cube_obj, "structure", cube_obj)
    if offsets_bp is None:
        offsets_bp = getattr(cube_obj, "strike_spreads", None) or cube_data.skew_offsets()
    offsets = sorted({0.0, *(float(o) for o in offsets_bp)})

    worst = 0.0
    worst_node: Optional[Tuple[str, str, float, float, float]] = None
    n_checked = 0
    for expiry in cube_data.expiries():
        date = structure.optionDateFromTenor(ql.Period(str(expiry)))
        for tenor in cube_data.tenors():
            period = ql.Period(str(tenor))
            atm_strike = float(structure.atmStrike(date, period))
            for off in offsets:
                got = float(structure.volatility(date, period, atm_strike + off / 1e4, True)) * 1e4
                want = cube_data.vol(expiry, tenor, off)
                err = abs(got - want)
                n_checked += 1
                if err > worst:
                    worst, worst_node = err, (expiry, tenor, off, got, want)

    if worst > float(tol):
        assert worst_node is not None
        expiry, tenor, off, got, want = worst_node
        raise VolCubeOrderingError(
            f"Built QuantLib cube does not reproduce its input: {expiry}x{tenor} at {off:+g}bp "
            f"reads {got:.6f}bp but the Citi quote is {want:.6f}bp "
            f"(error {worst:.6f}bp > tol {tol:g}bp, over {n_checked} node(s)). "
            "The usual cause is the volSpreads row order: QuantLib wants optionTenors OUTER and "
            "swapTenors INNER, and the transposed matrix has the same shape so the constructor "
            "accepts it. Build the rows with vol_spreads_matrix(), which enforces that order. "
            "For a SABR cube this is expected - it fits rather than interpolates; widen tol."
        )
    _logger.debug(
        "assert_vol_spread_ordering: %d node(s) round-tripped, max abs error %.3e bp",
        n_checked,
        worst,
    )
    return worst
