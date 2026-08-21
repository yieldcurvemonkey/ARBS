import math
import numpy as np
from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve, _IRSwapGenericObject


class IRSwapValue(Enum):
    RATE = auto()
    PV01 = auto()
    DV01 = auto()
    GAMMA_01 = auto()
    NPV = auto()
    NOTIONAL = auto()
    CARRY_BPS_RUNNING = auto()
    ROLL_BPS_RUNNING = auto()
    CARRY_AND_ROLL_BPS_RUNNING = auto()

    SPREADOVER = auto()
    MMSS = auto()
    SPREADOVER_CARRY_ADJUSTED = auto()
    MMSS_CARRY_ADJUSTED = auto()
    SPREADOVER_ROLL_ADJUSTED = auto()
    MMSS_ROLL_ADJUSTED = auto()
    SPREADOVER_CR_ADJUSTED = auto()
    MMSS_CR_ADJUSTED = auto()
    PAR_PAR_ASW = auto()
    TRUE_ASW = auto()
    PROCEEDS_ASW = auto()
    MARKET_ASW = auto()

    # TODO
    CVX_ADJ = auto()
    CVX_ADJ_EMPIRICAL = auto()

    ROLL_ADJ_DIFFERENCE = auto()
    ROLL_ADJ_RATIO = auto()
    ROLL_ADJ_CALENDAR_WEIGHT = auto()

    # Appended, deliberately, rather than filed next to SPREADOVER/MMSS above:
    # ``auto()`` renumbers every member after an insertion point, so slotting it
    # in the middle would silently change the int value of a dozen existing
    # members. See IRSwapValueFunctionMap._citivelo_swap_spread for what this is
    # and how it differs from the two computed spreads.
    CITIVELO_SWAP_SPREAD = auto()


# _swap_structure_sign_mapper = {
#     IRSwapStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
#     IRSwapStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
#     IRSwapStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
# }
_swap_structure_sign_mapper = {
    IRSwapStructure.OUTRIGHT: lambda rws: rws,
    IRSwapStructure.CURVE: lambda rws: rws,
    IRSwapStructure.FLY: lambda rws: [-1 * np.abs(rws[0]), 1 * np.abs(rws[1]), -1 * np.abs(rws[2])],  # always keep belly risk weight pos, wings risk weight negative
}

_swap_structure_legs_mapper = {
    1: (IRSwapStructure.OUTRIGHT, 100),
    2: (IRSwapStructure.CURVE, 10_000),
    3: (IRSwapStructure.FLY, 10_000),
}

#: Which ``value_kwargs`` ``CITIVELO_SWAP_SPREAD`` forwards. Named explicitly
#: rather than splatted: ``apply()`` merges the map's own ``curve``/``package``/
#: ``risk_weights`` into the same dict, and a blind ``**kwargs`` would pass
#: ``risk_weights`` through as an unexpected keyword.
_CITIVELO_SWAP_SPREAD_KWARGS = frozenset(
    {
        "tenor",
        "quotes",
        "catalog",
        "max_staleness",
        "offline",
        "force_refresh",
        "return_quote",
        # Reachable only when ``quotes`` is omitted, which is exactly the batch
        # case that could not tune the connect at all before.
        "client_kwargs",
    }
)


def calc_spread_rate(
    curve: _IRSwapGenericCurve,
    package: List[_IRSwapGenericObject],
    risk_weights: List[float],
) -> float:
    """Risk-weighted sum of the legs' fair rates.

    The leg rate is used with its own SIGN. It used to be wrapped in ``abs()``,
    which is invisible while every rate in the book is positive and wrong the
    moment one is not: measured 2026-08-07 against Citi Velocity's own quotes, the
    CHF SARON curve's front is -0.055314% and an outright came back as
    +0.055314% - an 11.06 bp error, exactly twice the rate. A CHF 1s10s curve
    trade whose legs straddle zero was out by a similar amount in the other
    direction.

    ``abs()`` cannot have been doing sign normalisation: ``fair_rate`` is a par
    rate and carries no direction - the direction lives in ``risk_weights``, which
    ``_swap_structure_sign_mapper`` has already applied on the line above.
    """
    risk_weights = _swap_structure_sign_mapper[_swap_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum([risk_weights[i] * curve.fair_rate(sw) for i, sw in enumerate(package)])


class IRSwapValueFunctionMap(BaseValueFunctionMap[IRSwapValue, float]):
    def __init__(
        self,
        curve: _IRSwapGenericCurve,
        package: List[_IRSwapGenericObject],
        risk_weights: List[float],
    ):
        super().__init__(IRSwapValue, package=package, risk_weights=risk_weights, curve=curve)

    def _create_map(self) -> Dict[IRSwapValue, Callable[..., float]]:
        return {
            IRSwapValue.RATE: self._rate,
            IRSwapValue.PV01: self._pv01,
            IRSwapValue.DV01: self._dv01,
            IRSwapValue.GAMMA_01: self._gamma,
            IRSwapValue.NPV: self._npv,
            IRSwapValue.NOTIONAL: self._notional,
            IRSwapValue.CARRY_BPS_RUNNING: self._carry_bps_running,
            IRSwapValue.ROLL_BPS_RUNNING: self._rolldown_bps_running,
            IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING: self._carry_and_roll_bps_running,
            IRSwapValue.CVX_ADJ: self._convexity_adjustment,
            IRSwapValue.CVX_ADJ_EMPIRICAL: self._convexity_adjustment_empirical,
            IRSwapValue.CITIVELO_SWAP_SPREAD: self._citivelo_swap_spread,
        }

    def _rate(self, **kwargs: Any) -> float:
        if "kwargs" in kwargs and "curve" not in kwargs:
            kwargs = kwargs["kwargs"]
        return calc_spread_rate(kwargs["curve"], kwargs["package"], kwargs["risk_weights"]) * _swap_structure_legs_mapper[len(kwargs["package"])][1]

    def _npv(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.npv(s) for s in kwargs["package"])

    def _pv01(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.pv01(s) for s in kwargs["package"])

    def _dv01(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.dv01(s) for s in kwargs["package"])

    def _gamma(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(curve.gamma(s) for s in kwargs["package"])

    def _notional(self, **kwargs: Any) -> float:
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(math.copysign(curve.notional(s), curve.pv01(s)) for s in kwargs["package"])

    def _carry_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.carry_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _rolldown_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.roll_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _carry_and_roll_bps_running(self, **kwargs: Any) -> float:
        assert "horizon" in kwargs, 'Expecting an "horizon" with type str | ql.Period in args e.g. `ql.Period("1M")`'
        curve: _IRSwapGenericCurve = kwargs["curve"]
        return sum(kwargs["risk_weights"][i] * curve.carry_and_roll_bps_running(s, kwargs["horizon"]) for i, s in enumerate(kwargs["package"]))

    def _convexity_adjustment(self, **kwargs: Any) -> float:
        r"""``pack_rate - matched_swap_rate``, in basis points.

        Two things about this function were wrong for as long as it existed, and
        both are the same mistake: a quantity was read in the wrong unit or the
        wrong convention because nothing external graded it. It is now pinned to
        Citi's published SOFR screen (Rates Vol Lab, 12-Jun-2023, Figure 58,
        close 6/9/2023) in ``tests/test_convexity_rv_shared_ca_path.py``, the
        same thirteen rows that grade ``RVUtils.ConvexityRV``'s own kernel.

        **The matched swap is quarterly/quarterly.**
        Citi specifies it verbatim -- *"both fixed and floating legs of this swap
        have a quarterly payment frequency"* -- while the ``usd_irs`` spec these
        curves carry quotes **annual** fixed. Reading the par rate off the
        package (``curve.fair_rate(swap_obj)``) therefore took the spec default.
        Measured against Q/Q on three dates spanning 2023-2025: ``+4.585``,
        ``+5.816``, ``+5.884`` bp. Since ``CA = pack_rate - swap_rate``, every
        adjustment this function returned was low by that much -- larger than the
        Whites/Reds adjustment itself, which runs 1.3-6.8 bp.

        The swap leg is now built here, at the frequency asked for, rather than
        read off whatever the query happened to construct. Pass
        ``matched_frequency=None`` to fall back to the spec default; that is the
        negative control the test suite requires to fail.

        **The futures leg is in percent and always was.**
        The previous code ran both legs through

        .. code-block:: python

            def _as_percent(x):
                return x * 100.0 if abs(x) < 1.0 else x

        which is correct for ``curve.fair_rate`` -- a decimal by this wrapper's
        own contract -- and wrong for ``rl.STIRFuture.fixed_rate``, which
        rateslib already carries in percent. Any SR3 priced above 99.00 was
        multiplied by a hundred: 99.05 implies 0.95 % and was read as 95 %, an
        error of 9,405 bp. That is the whole ZIRP window, 2020-03 to 2022-06,
        for Whites, Reds and Greens, and the deferred strip into 2021.

        One heuristic, two quantities, two units. Each leg now converts
        explicitly, so neither depends on the magnitude of the number.
        """
        assert len(kwargs["package"]) == 1, "convexity not supported for packages!"
        assert "sfr" in kwargs, "must pass in SFR object"

        import rateslib as rl
        import numpy as np
        from decimal import Decimal, ROUND_HALF_UP

        assert all(type(p) == rl.STIRFuture for p in kwargs["sfr"]), "convexity only supported for rateslib backend"
        assert all(type(p) == rl.IRS for p in kwargs["package"]), "convexity only supported for rateslib backend"

        sfrs: List[rl.STIRFuture] = kwargs["sfr"]
        pack_tick: float = float(kwargs.get("pack_tick", 0.0025))  # ¼ tick
        do_round: bool = bool(kwargs.get("round_pack_to_tick", True))

        def _fixed_rate_percent(sfr: rl.STIRFuture) -> float:
            """``rl.STIRFuture.fixed_rate`` is PERCENT. No magnitude heuristic."""
            fr = getattr(sfr, "fixed_rate", None)
            if fr is None:
                raise ValueError("STIRFuture missing fixed_rate")
            try:
                return float(getattr(fr, "real", fr))
            except Exception:
                return float(fr.iloc[-1])

        leg_rates_pct = [_fixed_rate_percent(s) for s in sfrs]
        leg_prices = [100.0 - r for r in leg_rates_pct]
        avg_price = float(np.mean(leg_prices))

        if do_round and len(leg_prices) >= 2:
            q = Decimal(str(pack_tick))
            pack_avg_price = float((Decimal(str(avg_price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)
            pack_avg_price = float(Decimal(str(pack_avg_price)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
        else:
            pack_avg_price = avg_price

        implied_fut_yield_pct = 100.0 - pack_avg_price

        curve = kwargs["curve"]
        swap_obj = kwargs["package"][0]

        # ``matched_frequency`` absent means Citi's convention, which is the only
        # one that ties out. It is a keyword rather than a constant so the
        # spec-default variant stays reachable as a negative control -- and,
        # because it travels in the query's ``value_kwargs``, it is part of the
        # timeseries cache fingerprint, so a change of convention orphans the
        # rows computed under the old one instead of silently serving them.
        matched_frequency = kwargs.get("matched_frequency", "Q")
        matched_leg2_frequency = kwargs.get("matched_leg2_frequency", "Q")

        if matched_frequency is None and matched_leg2_frequency is None:
            # ``fair_rate`` returns a DECIMAL by this wrapper's contract.
            swap_yield_pct = float(curve.fair_rate(swap_obj)) * 100.0
        else:
            from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

            swap_yield_pct = matched_forward_swap_rate(
                curve,
                curve.effective_date(swap_obj),
                curve.maturity_date(swap_obj),
                frequency=matched_frequency,
                leg2_frequency=matched_leg2_frequency,
            )

        return (implied_fut_yield_pct - swap_yield_pct) * 100.0

    def _citivelo_swap_spread(self, **kwargs: Any) -> float:
        r"""Citi Velocity's PUBLISHED swap spread. A THIRD number, not a replacement.

        Served from ``RATES.OIS.<index>.SWAP_SPREAD.<tenor>`` for a curve built by
        ``IRSwapsMDP(source="CITIVELO_EXCEL")``, at that curve's own instant. This
        repo already has two swap spreads and this one agrees with neither; the
        point of the comparison below is that they are three different questions,
        not three estimates of one answer.

        What each one actually is
        -------------------------
        Read off the implementations, not the names -
        ``MDP/IRSwapSpreads/IRSwapSpreadsMDP.py`` (``IRSwapSpreadPricer``) and
        ``Query/IRSwaps/adapter.py`` (``IRSProductAdapter.edit_query``):

        ``IRSwapValue.MMSS`` - **matched-maturity swap spread, computed here.**
            The tenor token is a CUSIP or a UST alias (``CT10``, ``O10``,
            ``Ox110``, ``MMYY``). ``edit_query`` resolves it against the FiscalData
            reference table, throws the swap's tenor away and pins the swap to
            ``effective = calendar_advance(as_of, "2D")`` and ``maturity = that
            bond's maturity date``. The cash leg is the SAME bond's yield to
            maturity from ``FixedRateBondsMDP``. So both legs mature on the same
            day, to the day.

        ``IRSwapValue.SPREADOVER`` - **benchmark spreadover, computed here.**
            The two legs are deliberately NOT matched. ``_resolve_bond_symbol``
            rewrites ``10Y`` to ``CT10`` for the cash leg, and ``_build_swap_query``
            rewrites ``CT10`` back to ``10Y`` for the swap leg. The swap is a round
            10-year par swap starting spot; the bond is whatever note is currently
            on the run, whose remaining life is *less* than ten years by however
            far into the auction cycle the date sits. The difference between MMSS
            and SPREADOVER on the same day is that maturity mismatch running along
            the curve, and it is a real number, not noise.

        Both computed values are then::

            (swap_rate_percent - bond_ytm_percent) * 100.0      # IRSwapSpreadPricer.spread_bps

        i.e. **swap minus cash, in basis points**, so a USD spread is negative when
        the swap rate is below the Treasury yield. ``swap_rate_percent`` is
        ``IRSwapValue.RATE`` on a one-leg package, which is ``curve.fair_rate() *
        100`` - a percent, because ``fair_rate`` is a decimal. The four
        ``*_CARRY_ADJUSTED`` / ``*_ROLL_ADJUSTED`` / ``*_CR_ADJUSTED`` members are
        the same number plus a 3M-horizon carry and/or roll adjustment in bp.

        ``IRSwapValue.CITIVELO_SWAP_SPREAD`` - **Citi's published quote.**
            Nothing is computed. One tag is read and returned. Citi does not
            publish, anywhere in the harvested catalog, which Treasury it spreads
            against, whether that leg is matched-maturity or an interpolated
            benchmark, which yield convention it uses, or which of its own curves
            the swap leg comes from. **Those are unknown here and are not
            inferred.** What IS known is the shape of the axis: it is ragged and
            per-index (USD 11 tenors including 1M/3M/6M and no 4Y/15Y/25Y; GBP a
            different 10 with 15Y/40Y/50Y and no money-market tenors; EUR none at
            all), which is itself evidence that this is a desk's published grid
            rather than a mechanical function of the par curve.

        Why they can disagree, in rough order of size
        --------------------------------------------
        1. **Which Treasury.** Matched-maturity, on-the-run, or an interpolated
           benchmark are three different bonds; the on-the-run/off-the-run and
           roll effects between them are worth basis points, not fractions.
        2. **Whose swap curve.** Citi's mid against Citi's own curve versus this
           repo's curve from whichever ``IRSwapsMDP`` source was used.
        3. **Whose Treasury marks, and at what time.** ``FixedRateBondsMDP`` marks
           come from FedInvest/WSJ at their own timestamps; Citi's spread is
           stamped on Citi's clock (America/New_York - see
           ``CITIVELO_EXCEL/timestamps.py``).
        4. **Sign and convention.** The repo's is swap-minus-cash by construction,
           above. Citi's sign convention is NOT verified here (see units).

        Do not reconcile these into one number. If two of them are wanted on the
        same axis, carry both columns.

        Units
        -----
        Returned **exactly as published, unscaled**. As of 2026-08-08 zero
        ``SWAP_SPREAD`` tags are cached and Excel was unavailable, so bp-versus-
        decimal has *not* been measured and is not claimed - the module constant
        is literally ``UNIT = "as_published"``. The magnitude discriminator is
        unambiguous once one number exists (a USD 10Y swap spread is tens of bp,
        so ``|x| > 1`` is bp and ``|x| < 1`` is not), and the check that settles it
        is ``scripts/citivelo_swap_spread_tieout.py``, which prints Citi's raw
        level beside this repo's ``SPREADOVER`` in bp for the same tenor and date.
        Until that has run, do NOT subtract this from an MMSS series.

        Parameters (via ``value_kwargs``)
        ---------------------------------
        ``tenor``
            The Citi tenor token, e.g. ``"10Y"``. Omitted, it is derived from the
            swap's own effective and maturity dates (whole months, then years when
            exact) and validated against the index's axis - so a 4Y swap raises
            with the accepted list rather than silently reading the 5Y quote.
        ``quotes``
            A ``CitiVeloQuotes``-shaped object. Injectable so this is testable with
            no Excel. **Omitted, one is built lazily with ``offline=False``** - the
            same default the curve fetcher uses - so a cold tag cache will try to
            connect to a signed-in Excel *during pricing*. Pass ``quotes=`` or
            ``offline=True`` from a batch job that must not do that.

        Raises
        ------
        ValueError
            When the curve did not come from the ``citivelo_excel`` source, naming
            the source that was found.
        NotImplementedError
            For a multi-leg package: Citi publishes ``CURVES`` and ``BFLY`` as
            separate sub-types, and risk-weighting two published spreads would
            manufacture a quote that never existed.
        SpotStartRequiredError
            A subclass of the above, for a package that does not start SPOT.
            Citi's axis indexes a maturity, not a ``(forward, tenor)`` pair, and
            nothing in the tag or the returned number says so: a 5Yx5Y forward
            derives tenor ``5Y`` from ``maturity - effective`` and would read the
            SPOT 5Y quote, byte-identical to the spot answer. Differencing that
            against the swap's own forward rate leaves the entire forward/spot
            spread as a residual, so it refuses rather than warns. The tolerance
            is ``swap_spreads.MAX_SPOT_START_LAG`` (10 days: T+2 across a holiday
            weekend is at most 6, and the shortest forward anybody trades is 1M).
            Already-running swaps are refused for the mirror-image reason - the
            derived tenor is their ORIGINAL span, not their remaining life.
        """
        from MDP.IRSwaps.CITIVELO_EXCEL.swap_spreads import swap_spread_for_curve

        return swap_spread_for_curve(
            curve=kwargs["curve"],
            package=kwargs["package"],
            **{k: v for k, v in kwargs.items() if k in _CITIVELO_SWAP_SPREAD_KWARGS},
        )

    def _convexity_adjustment_empirical(self, **kwargs: Any) -> float:
        curve = kwargs["curve"]
        if not hasattr(curve, "pricer_a") or not hasattr(curve, "pricer_b"):
            raise TypeError("CVX_ADJ_EMPIRICAL requires a spread-style pricer with 'pricer_a' and 'pricer_b'.")

        package = kwargs["package"]
        risk_weights = kwargs["risk_weights"]
        structure = _swap_structure_legs_mapper[len(package)][0]
        risk_weights = _swap_structure_sign_mapper[structure](risk_weights)

        pricer_a = curve.pricer_a
        pricer_b = curve.pricer_b
        return sum(
            risk_weights[i] * (pricer_a.fair_rate(sw) - pricer_b.fair_rate(sw))
            for i, sw in enumerate(package)
        ) * 10_000.0
