r"""The Citi Velocity swaption cube as data: expiry x swap tenor x strike offset.

Citi publishes a **ready-made cube**, so nothing here interpolates to populate it -
only to read between its nodes::

    RATES.VOL.<ccy>.ATM_RFR.{NORMAL,BLACK,PREMIUM,FWDPREMIUM}[.ANNUAL].<expiry>.<tenor>
    RATES.VOL.<ccy>.OTM_RFR.{PREMIUM,NORMALABSOLUTE,NORMALSKEW,RISK_REVERSAL}[.ANNUAL]
        .OTM_<off>.<expiry>.<tenor>

Eleven currencies carry it: AUD CAD CHF DKK EUR GBP JPY KRW NOK SEK USD.

But the HARVEST is uneven, and that decides what is buildable today. Call
:func:`vol_coverage` for the live picture; as committed it reads:

===================  ==============================================================
USD                  walked to the expiry AND strike-offset levels (17 x 12)
CAD CHF EUR GBP JPY  ``_RFR`` branches and measures recorded, axes below them not -
                     pass ``expiries=``/``tenors=`` explicitly; OTM tags inherit
                     USD's offset spelling and are UNVERIFIED
AUD DKK KRW NOK SEK  only the legacy ``ATM/OTM/REALIZED/VOL_RATIO`` branches were
                     recorded, and those return no data - :func:`cube_tags` raises
===================  ==============================================================

None of that is patched over here. A currency whose ``ATM_RFR`` branch the walk
never saw fails loudly rather than being assumed into existence.

Tag spelling is NOT re-implemented here
---------------------------------------
The negative-offset spelling is per measure - ``NORMALABSOLUTE`` uses ``OTM_M25``
while ``PREMIUM`` uses ``OTM_N25`` - and the optional ``ANNUAL`` level is
branch-local. Both are read from the harvested catalog by
:func:`~MDP.CitiVelocityExcel.tags.vol_otm` / :func:`~MDP.CitiVelocityExcel.tags.vol_atm`,
which this module calls rather than duplicating.

UNITS: what the wire carries, and how that was decided
------------------------------------------------------
This module treats ``ATM_RFR.NORMAL.ANNUAL`` as an annualised **normal
(Bachelier) volatility quoted in BASIS POINTS** - a USD 1Y10Y serves as ~90, not
as ~0.0090 - and stores every number in bp.

That default started life as a declaration and has since been **MEASURED**:
on 2026-08-05 a live probe of
``RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y`` returned ``80.9518``, which is
basis points of annualised normal vol and not decimal (~0.0081) or percent
(~0.81). ``served_unit="bp"`` is therefore correct for ``ATM_RFR.NORMAL``. It
remains exposed as ``served_unit=`` on every entry point, because the other
measures (``PREMIUM``, ``FWDPREMIUM``, and the ``OTM_RFR`` skew branches) have
NOT been measured and need not share it.

It is deliberately a declaration rather than a magnitude heuristic.
``NormalSabrVolCube._normalize_normal_vol`` in ``MDP/IRSwaptions/MONKEYCUBE/cube.py``
does ``v / 10000 if abs(v) > 1 else v``, which accepts either unit silently and
leaves no record of which one a given vintage actually used. This module instead
fails loudly: :func:`assert_vol_units` raises :class:`VolUnitError` naming
``served_unit=`` when the served numbers do not fit the declared unit, so a cube
built from decimal quotes under ``served_unit="bp"`` raises rather than producing
a surface 10,000x too flat.

Re-run ``MDP/CitiVelocityExcel/harvest/verify_live.py`` to re-measure the ATM
unit; the same probe should be extended to a ``PREMIUM`` and an ``OTM_RFR`` node
before either is trusted.

Which skew measures become a vol level
--------------------------------------
=================  ==========================================================
``NORMALABSOLUTE`` normal vol AT the offset strike -> stored as-is
``NORMALSKEW``     vol MINUS atm -> stored as ``atm + spread``
``PREMIUM``        an option premium, not a vol -> rejected
``RISK_REVERSAL``  ``vol(+off) - vol(-off)``, one number for two strikes ->
                   rejected (it cannot be split into two levels without a
                   butterfly, which Citi does not publish on this branch)
=================  ==========================================================

**``NORMALSKEW`` is coded but UNVERIFIED and currently un-taggable.** The
spread-to-level conversion is implemented, but the catalog walk stopped at
``OTM_RFR.NORMALSKEW.ANNUAL`` without recording its strike-offset level, so
:func:`cube_tags` cannot generate a tag for it and raises saying so. Nothing in
this package has ever fetched a ``NORMALSKEW`` number, and the ``atm + spread``
arithmetic is therefore untested against real data. ``NORMALABSOLUTE`` is the
working route and is the default. If a live probe records the ``NORMALSKEW``
offset axis, no code here changes - only the catalog.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from MDP.CitiVelocityExcel import tags as cv_tags
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog, sort_tenors, tenor_years
from MDP.CitiVelocityExcel.errors import CitiVelocityError, UnknownTagError

__all__ = [
    "SwaptionCubeData",
    "VolUnitError",
    "RaggedCubeError",
    "cube_tags",
    "cube_from_quotes",
    "fetch_cube",
    "assert_vol_units",
    "default_cube_axes",
    "vol_coverage",
    "VOL_UNIT_BOUNDS",
    "VOL_UNIT_TO_BP",
    "SPREAD_UNIT_BOUNDS",
    "DEFAULT_SWAP_TENORS",
    "DEFAULT_OFFSETS_BP",
    "ABSOLUTE_SKEW_MEASURES",
    "SPREAD_SKEW_MEASURES",
    "REJECTED_SKEW_MEASURES",
    "VOL_CURRENCIES",
]

_logger = logging.getLogger(__name__)

#: The eleven currencies ``RATES.VOL`` carries, from the harvested catalog.
VOL_CURRENCIES: Tuple[str, ...] = (
    "AUD",
    "CAD",
    "CHF",
    "DKK",
    "EUR",
    "GBP",
    "JPY",
    "KRW",
    "NOK",
    "SEK",
    "USD",
)

#: The swap-tenor axis. The catalog records the EXPIRY level of ``ATM_RFR.NORMAL``
#: (``1M 2M 3M 6M 9M 1Y 18M 2Y 3Y 4Y 5Y 7Y 10Y 12Y 15Y 20Y 30Y``) but the walk was
#: depth-capped above the tenor level, so the tenor axis below it is UNVERIFIED -
#: it mirrors the recorded expiry axis from 1Y out, which is the shape Citi's own
#: vol grid shows. Pass ``tenors=`` explicitly once a live probe settles it.
DEFAULT_SWAP_TENORS: Tuple[str, ...] = (
    "1Y",
    "2Y",
    "3Y",
    "4Y",
    "5Y",
    "7Y",
    "10Y",
    "12Y",
    "15Y",
    "20Y",
    "30Y",
)

#: The strike offsets recorded under every ``OTM_RFR`` measure, signed in bp.
DEFAULT_OFFSETS_BP: Tuple[float, ...] = (
    -200.0,
    -100.0,
    -75.0,
    -50.0,
    -25.0,
    -10.0,
    10.0,
    25.0,
    50.0,
    75.0,
    100.0,
    200.0,
)

#: OTM measures that serve an absolute vol level at the offset strike.
ABSOLUTE_SKEW_MEASURES: Tuple[str, ...] = ("NORMALABSOLUTE",)
#: OTM measures that serve a vol spread over ATM.
SPREAD_SKEW_MEASURES: Tuple[str, ...] = ("NORMALSKEW",)
#: OTM measures that are not a volatility at all and cannot build a cube.
REJECTED_SKEW_MEASURES: Tuple[str, ...] = ("PREMIUM", "RISK_REVERSAL")

#: Plausible magnitude band per declared unit for an annualised NORMAL swaption
#: vol. These bands are a guard, not a classifier: ``bp`` and ``percent`` overlap
#: on ``[0.5, 10]`` and no band can separate them there. They exist to catch the
#: 10,000x error, which is the one that actually happens.
VOL_UNIT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "bp": (0.5, 1000.0),
    "decimal": (5e-5, 0.10),
    "percent": (5e-3, 10.0),
}

#: Multiplier taking a value in the keyed unit to basis points.
VOL_UNIT_TO_BP: Dict[str, float] = {"bp": 1.0, "decimal": 1e4, "percent": 1e2}

#: Same idea for a vol SPREAD (``NORMALSKEW``), which is signed and may be ~0.
#: Bounds are on the absolute value.
SPREAD_UNIT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "bp": (0.0, 500.0),
    "decimal": (0.0, 0.05),
    "percent": (0.0, 5.0),
}


class VolUnitError(CitiVelocityError, ValueError):
    """Served vol values do not fit the declared ``served_unit``."""


class RaggedCubeError(CitiVelocityError, ValueError):
    """A cube is missing nodes, has mismatched axes, or holds non-finite vols."""


# ------------------------------------------------------------------ #
#                             units guard                            #
# ------------------------------------------------------------------ #


def assert_vol_units(
    values: Iterable[float],
    *,
    unit: str,
    kind: str = "level",
    label: str = "",
) -> None:
    """Fail loudly when served values cannot be the declared unit.

    Parameters
    ----------
    values
        The numbers exactly as the add-in served them, before any rescaling.
    unit
        ``'bp'``, ``'decimal'`` or ``'percent'`` - what the caller DECLARED the
        feed to be.
    kind
        ``'level'`` for a vol, ``'spread'`` for a ``NORMALSKEW`` difference (which
        is signed and may sit at zero).
    label
        Prefixed to the error message, e.g. the measure name.

    Raises
    ------
    VolUnitError
        When any finite value falls outside the plausible band for ``unit``. The
        message names ``served_unit=`` because that is the knob that fixes it.

    Notes
    -----
    This is deliberately not a magnitude heuristic. A heuristic that divides by
    10,000 "when the number looks big" cannot be audited later, because the
    stored cube then carries no record of which unit the vintage used.
    """
    bounds = SPREAD_UNIT_BOUNDS if kind == "spread" else VOL_UNIT_BOUNDS
    if unit not in bounds:
        raise VolUnitError(
            f"Unknown vol unit {unit!r}. Supported: {', '.join(sorted(bounds))}. "
            "Set served_unit= to one of these."
        )
    lo, hi = bounds[unit]
    arr = np.asarray(list(values), dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return
    probe = np.abs(finite) if kind == "spread" else finite
    bad = probe[(probe < lo) | (probe > hi)]
    if bad.size == 0:
        return

    worst = float(bad[np.argmax(np.abs(bad - np.clip(bad, lo, hi)))])
    prefix = f"{label}: " if label else ""
    # Name the unit the magnitude WOULD fit, so the fix is one edit.
    suggestions = [
        u
        for u, (l2, h2) in bounds.items()
        if u != unit and l2 <= float(np.median(np.abs(finite))) <= h2
    ]
    hint = f" The observed magnitudes fit served_unit={suggestions[0]!r}." if suggestions else ""
    raise VolUnitError(
        f"{prefix}{bad.size} of {finite.size} served value(s) are outside the plausible band "
        f"[{lo}, {hi}] for served_unit={unit!r} (worst: {worst!r}).{hint} "
        "Nothing was rescaled - set served_unit= explicitly rather than letting a magnitude "
        "heuristic guess, because a guessed rescale leaves no record of which unit the "
        "vintage used."
    )


# ------------------------------------------------------------------ #
#                             the record                             #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class SwaptionCubeData:
    """One dated Citi swaption cube: ATM surface plus per-offset skew surfaces.

    Every stored volatility is an annualised **normal vol in basis points**,
    whatever ``served_unit`` the feed used - the conversion happens once, in
    :func:`cube_from_quotes`, and ``served_unit`` records what it converted from.

    Attributes
    ----------
    as_of
        The observation date the quotes were taken at.
    currency
        ISO code, one of :data:`VOL_CURRENCIES`.
    measure
        The ATM measure, normally ``'NORMAL'``.
    atm
        ``index=expiry token``, ``columns=swap tenor token``, values normal vol in
        bp. Both axes are in maturity order.
    skew
        ``{signed offset in bp: DataFrame}`` with the SAME index and columns as
        ``atm``, values the normal vol in bp AT that offset strike (an absolute
        level, not a spread - use :meth:`spreads` for the difference).
    skew_measure
        Which OTM measure the skew frames came from.
    served_unit
        The unit the wire was DECLARED to carry. See the module docstring: this
        is asserted and guarded, not measured.
    vol_unit
        The unit of the stored numbers. Always ``'bp'``.
    strike_unit
        The unit of the ``skew`` keys. Always ``'bp'``, signed.
    source
        Free-form provenance string.
    """

    as_of: datetime.date
    currency: str
    measure: str
    atm: pd.DataFrame = field(repr=False)
    skew: Dict[float, pd.DataFrame] = field(default_factory=dict, repr=False)
    skew_measure: str = "NORMALABSOLUTE"
    served_unit: str = "bp"
    vol_unit: str = "bp"
    strike_unit: str = "bp"
    source: str = "citivelo_excel"

    # -- axes -----------------------------------------------------------

    def expiries(self) -> list[str]:
        """Option expiry tokens, in maturity order."""
        return list(self.atm.index)

    def tenors(self) -> list[str]:
        """Swap tenor tokens, in maturity order."""
        return list(self.atm.columns)

    def offsets(self) -> list[float]:
        """Signed strike offsets in bp, ascending, INCLUDING ``0.0`` for ATM."""
        return sorted({0.0, *(float(o) for o in self.skew)})

    def skew_offsets(self) -> list[float]:
        """Signed strike offsets in bp that have their own skew frame."""
        return sorted(float(o) for o in self.skew)

    # -- reads ----------------------------------------------------------

    def atm_vol(self, expiry: str, tenor: str) -> float:
        """ATM normal vol in bp at one node.

        Raises
        ------
        KeyError
            When ``(expiry, tenor)`` is not a node. Interpolation is a job for
            :mod:`~MDP.CitiVelocityExcel.vol.ql_cube` /
            :mod:`~MDP.CitiVelocityExcel.vol.rl_cube`, not for the data record.
        """
        try:
            return float(self.atm.at[str(expiry), str(tenor)])
        except KeyError as exc:
            raise KeyError(
                f"({expiry!r}, {tenor!r}) is not an ATM node. Expiries: "
                f"{', '.join(self.expiries())}. Tenors: {', '.join(self.tenors())}."
            ) from exc

    def vol(self, expiry: str, tenor: str, offset_bp: float = 0.0) -> float:
        """Normal vol in bp at one cube node.

        ``offset_bp == 0`` reads :attr:`atm`; anything else reads the matching
        skew frame.
        """
        off = float(offset_bp)
        if off == 0.0:
            return self.atm_vol(expiry, tenor)
        frame = self.skew.get(off)
        if frame is None:
            raise KeyError(
                f"No skew frame at offset {off:+g}bp. Available: "
                f"{', '.join(f'{o:+g}' for o in self.skew_offsets()) or '(none)'}. "
                "Rebuild the cube with offsets_bp= including this offset."
            )
        try:
            return float(frame.at[str(expiry), str(tenor)])
        except KeyError as exc:
            raise KeyError(
                f"({expiry!r}, {tenor!r}) is not a node of the {off:+g}bp skew frame."
            ) from exc

    def spreads(self) -> Dict[float, pd.DataFrame]:
        """``{offset: vol - atm}`` in bp, same axes as :attr:`atm`."""
        return {float(o): (f - self.atm) for o, f in sorted(self.skew.items())}

    def smile(self, expiry: str, tenor: str) -> Dict[float, float]:
        """``{offset in bp: normal vol in bp}`` at one node, ascending in offset."""
        return {o: self.vol(expiry, tenor, o) for o in self.offsets()}

    def to_frame(self) -> pd.DataFrame:
        """Long form: one row per ``(expiry, tenor, offset)`` node.

        Columns ``as_of currency expiry tenor offset_bp vol_bp atm_bp
        spread_bp expiry_years tenor_years``.
        """
        rows: list[Dict[str, Any]] = []
        for expiry in self.expiries():
            ey = tenor_years(expiry)
            for tenor in self.tenors():
                atm = self.atm_vol(expiry, tenor)
                for off in self.offsets():
                    vol = self.vol(expiry, tenor, off)
                    rows.append(
                        {
                            "as_of": self.as_of,
                            "currency": self.currency,
                            "expiry": expiry,
                            "tenor": tenor,
                            "offset_bp": off,
                            "vol_bp": vol,
                            "atm_bp": atm,
                            "spread_bp": vol - atm,
                            "expiry_years": ey,
                            "tenor_years": tenor_years(tenor),
                        }
                    )
        return pd.DataFrame(rows)

    # -- integrity ------------------------------------------------------

    def validate(self) -> "SwaptionCubeData":
        """Raise unless the cube is rectangular, finite and positive.

        Returns ``self`` so it chains onto a constructor.

        Raises
        ------
        RaggedCubeError
            Empty axes, duplicate labels, a skew frame whose axes differ from
            ``atm``, any non-finite value, or any non-positive vol. A cube with a
            NaN column is exactly the "silent NaN shipped as success" failure the
            repo has already paid for once, so it is refused here rather than
            carried into a solver.
        VolUnitError
            When the stored numbers are not plausible basis points.
        """
        if self.atm.empty:
            raise RaggedCubeError(
                f"{self.currency} {self.as_of} cube has an empty ATM surface. "
                "Check the expiries=/tenors= axes and the tag verification status."
            )
        if self.atm.index.has_duplicates or self.atm.columns.has_duplicates:
            raise RaggedCubeError("Cube axes contain duplicate expiry or tenor tokens.")

        bad = self.atm.isna().to_numpy()
        if bool(bad.any()):
            rows, cols = np.where(bad)
            missing = [f"{self.atm.index[i]}x{self.atm.columns[j]}" for i, j in zip(rows, cols)]
            raise RaggedCubeError(
                f"{len(missing)} ATM node(s) are NaN: {', '.join(missing[:12])}"
                f"{' ...' if len(missing) > 12 else ''}. A cube with holes must not be built - "
                "narrow expiries=/tenors= to the nodes that actually serve, or pass strict=False "
                "to cube_from_quotes() which DROPS incomplete rows/columns instead of NaN-filling."
            )
        if bool((self.atm.to_numpy() <= 0.0).any()):
            raise RaggedCubeError("ATM surface contains non-positive normal vols.")

        for off, frame in sorted(self.skew.items()):
            if list(frame.index) != list(self.atm.index) or list(frame.columns) != list(self.atm.columns):
                raise RaggedCubeError(
                    f"Skew frame at {off:+g}bp has axes {list(frame.index)} x {list(frame.columns)}, "
                    f"which differ from the ATM axes. Every offset must share the ATM grid."
                )
            if bool(frame.isna().to_numpy().any()):
                raise RaggedCubeError(f"Skew frame at {off:+g}bp contains NaN nodes.")
            if bool((frame.to_numpy() <= 0.0).any()):
                raise RaggedCubeError(f"Skew frame at {off:+g}bp contains non-positive normal vols.")

        assert_vol_units(self.atm.to_numpy().ravel(), unit=self.vol_unit, label="ATM surface")
        for off, frame in sorted(self.skew.items()):
            assert_vol_units(frame.to_numpy().ravel(), unit=self.vol_unit, label=f"{off:+g}bp skew")
        return self

    def __repr__(self) -> str:  # frames would otherwise dump into every traceback
        return (
            f"SwaptionCubeData({self.currency} {self.as_of} {self.measure}/{self.skew_measure}, "
            f"{len(self.atm.index)}x{len(self.atm.columns)} nodes, "
            f"offsets={[f'{o:+g}' for o in self.skew_offsets()]}, unit={self.vol_unit})"
        )


# ------------------------------------------------------------------ #
#                       skew forward-fill                            #
# ------------------------------------------------------------------ #


def ffill_skew(
    current: SwaptionCubeData,
    donor: SwaptionCubeData,
) -> SwaptionCubeData:
    """Augment an ATM-only cube with the skew shape from a donor cube.

    For each offset the donor carries, the synthetic vol is::

        synthetic[offset] = current.atm + (donor.skew[offset] - donor.atm)

    The skew shape is preserved; only the ATM level shifts.  Nodes that
    exist in ``current`` but not in ``donor`` are dropped (intersection
    only).

    Returns a new ``SwaptionCubeData`` whose ``source`` records the donor
    date.  Raises nothing — an empty intersection returns ``current``
    unchanged.
    """
    donor_offsets = [o for o in donor.skew_offsets() if o != 0.0]
    if not donor_offsets:
        return current

    shared_exp = [e for e in current.expiries() if e in donor.atm.index]
    shared_ten = [t for t in current.tenors() if t in donor.atm.columns]
    if not shared_exp or not shared_ten:
        return current

    atm = current.atm.loc[shared_exp, shared_ten]
    donor_spreads = donor.spreads()

    synthetic_skew: Dict[float, pd.DataFrame] = {}
    for off in donor_offsets:
        spread = donor_spreads[off]
        spread_aligned = spread.reindex(index=shared_exp, columns=shared_ten)
        mask = spread_aligned.notna()
        synthetic_skew[off] = atm.where(~mask, atm + spread_aligned)

    return replace(
        current,
        atm=atm,
        skew=synthetic_skew,
        skew_measure=donor.skew_measure,
        source=current.source + f"/skew_ffill<{donor.as_of}>",
    )


# ------------------------------------------------------------------ #
#                          tag construction                          #
# ------------------------------------------------------------------ #


def default_cube_axes(
    currency: str,
    *,
    measure: str = "NORMAL",
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    catalog: Optional[CitiVeloCatalog] = None,
) -> Tuple[list[str], list[str]]:
    """Resolve the ``(expiries, tenors)`` axes for a currency.

    ``expiries=None`` takes the recorded expiry level of the ATM branch;
    ``tenors=None`` takes :data:`DEFAULT_SWAP_TENORS`, which is unverified (the
    catalog walk was depth-capped above the tenor level).
    """
    grid = cv_tags.vol_atm_grid(
        currency,
        expiries=list(expiries) if expiries else None,
        tenors=list(tenors) if tenors else list(DEFAULT_SWAP_TENORS),
        measure=measure,
        catalog=catalog,
    )
    if not grid:
        raise RaggedCubeError(
            f"No ATM tags for {currency!r} measure={measure!r}. The catalog recorded no expiry "
            "axis for that branch - pass expiries= and tenors= explicitly."
        )
    exp_axis = sort_tenors({e for e, _ in grid})
    ten_axis = sort_tenors({t for _, t in grid})
    return exp_axis, ten_axis


def cube_tags(
    *,
    currency: str,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets_bp: Sequence[float] = (),
    measure: str = "NORMAL",
    skew_measure: str = "NORMALABSOLUTE",
    catalog: Optional[CitiVeloCatalog] = None,
) -> Dict[str, Tuple[str, str, str, float]]:
    """Every Velocity tag a cube needs, mapped back to its cube coordinate.

    Parameters
    ----------
    currency
        One of :data:`VOL_CURRENCIES`.
    expiries, tenors
        Axis overrides; see :func:`default_cube_axes`.
    offsets_bp
        Signed strike offsets in bp. Empty means ATM-only.
    measure
        ATM measure. Only ``'NORMAL'`` yields a normal-vol cube.
    skew_measure
        OTM measure. ``'NORMALABSOLUTE'`` (levels) or ``'NORMALSKEW'`` (spreads);
        ``'PREMIUM'`` and ``'RISK_REVERSAL'`` are rejected.

    Returns
    -------
    dict[str, tuple[str, str, str, float]]
        ``{tag: (kind, expiry, tenor, offset_bp)}`` where ``kind`` is ``'ATM'``
        or ``'OTM'``. ATM entries carry ``offset_bp == 0.0``.

    Raises
    ------
    ValueError
        On a rejected ``skew_measure``.
    """
    if offsets_bp and str(skew_measure).upper() in REJECTED_SKEW_MEASURES:
        raise ValueError(
            f"skew_measure={skew_measure!r} does not serve a volatility level. "
            f"PREMIUM is an option premium and RISK_REVERSAL is vol(+off) - vol(-off), one number "
            f"for two strikes. Use one of {ABSOLUTE_SKEW_MEASURES + SPREAD_SKEW_MEASURES}."
        )

    exp_axis, ten_axis = default_cube_axes(
        currency, measure=measure, expiries=expiries, tenors=tenors, catalog=catalog
    )

    out: Dict[str, Tuple[str, str, str, float]] = {}
    for (exp, ten), tag in cv_tags.vol_atm_grid(
        currency, expiries=exp_axis, tenors=ten_axis, measure=measure, catalog=catalog
    ).items():
        out[tag] = ("ATM", exp, ten, 0.0)

    signed = [float(o) for o in offsets_bp if float(o) != 0.0]
    if signed:
        try:
            otm_grid = cv_tags.vol_otm_grid(
                currency,
                signed,
                expiries=exp_axis,
                tenors=ten_axis,
                measure=skew_measure,
                catalog=catalog,
            )
        except UnknownTagError as exc:
            otm_grid = _otm_grid_by_recorded_sibling(
                currency=currency,
                offsets_bp=signed,
                expiries=exp_axis,
                tenors=ten_axis,
                measure=skew_measure,
                catalog=catalog,
                cause=exc,
            )
        for (exp, ten, off), tag in otm_grid.items():
            out[tag] = ("OTM", exp, ten, float(off))
    return out


def vol_coverage(catalog: Optional[CitiVeloCatalog] = None) -> pd.DataFrame:
    """What the catalog actually recorded per vol currency. Computed, not stored.

    The ``RATES.VOL`` harvest is uneven, and the unevenness decides which
    currencies :func:`cube_tags` can serve:

    * ``rfr_branches`` False - the walk recorded only the legacy
      ``ATM/OTM/REALIZED/VOL_RATIO`` branches, which return no data. Those
      currencies cannot be built at all today; :func:`cube_tags` raises from
      ``tags._vol_branch`` naming the accepted branches.
    * ``n_expiries`` 0 - the ATM expiry axis was not walked, so ``expiries=``
      must be given explicitly (values are not validated in that case).
    * ``n_offsets`` 0 - the strike-offset level was not walked, so OTM tags are
      built by inheriting the shape of the one currency that was
      (see :func:`_otm_grid_by_recorded_sibling`) and are UNVERIFIED.

    Returns
    -------
    pandas.DataFrame
        ``index=currency``, columns ``rfr_branches n_expiries n_offsets``.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    rows: list[Dict[str, Any]] = []
    for ccy in cat.options("RATES.VOL"):
        branches = cat.options(f"RATES.VOL.{ccy}")
        has_rfr = "ATM_RFR" in branches
        atm_node = f"RATES.VOL.{ccy}.ATM_RFR.NORMAL"
        atm_opts = cat.options(atm_node)
        if "ANNUAL" in atm_opts or "DAILY" in atm_opts:
            atm_node = f"{atm_node}.{'ANNUAL' if 'ANNUAL' in atm_opts else 'DAILY'}"
            atm_opts = cat.options(atm_node)
        otm_node = f"RATES.VOL.{ccy}.OTM_RFR.NORMALABSOLUTE"
        otm_opts = cat.options(otm_node)
        if "ANNUAL" in otm_opts or "DAILY" in otm_opts:
            otm_opts = cat.options(f"{otm_node}.{'ANNUAL' if 'ANNUAL' in otm_opts else 'DAILY'}")
        rows.append(
            {
                "currency": ccy,
                "rfr_branches": bool(has_rfr),
                "n_expiries": len([o for o in atm_opts if o != "ANNUAL"]),
                "n_offsets": len([o for o in otm_opts if o.startswith("OTM_")]),
            }
        )
    return pd.DataFrame(rows).set_index("currency")


def _offset_reference_currency(
    cat: CitiVeloCatalog, measure: str
) -> Optional[Tuple[str, str]]:
    """The currency whose ``OTM_RFR.<measure>`` strike-offset level WAS recorded.

    Returns ``(currency, node)`` or ``None``. The walk was depth-capped, and in
    practice it descended past the offset level for exactly one currency, so this
    finds the sibling whose shape the others inherit.
    """
    for ccy in cat.options("RATES.VOL"):
        node = f"RATES.VOL.{ccy}.OTM_RFR.{measure}"
        options = cat.options(node)
        if "ANNUAL" in options or "DAILY" in options:
            node = f"{node}.{'ANNUAL' if 'ANNUAL' in options else 'DAILY'}"
            options = cat.options(node)
        if any(o.startswith("OTM_") for o in options):
            return ccy, node
    return None


def _otm_grid_by_recorded_sibling(
    *,
    currency: str,
    offsets_bp: Sequence[float],
    expiries: Sequence[str],
    tenors: Sequence[str],
    measure: str,
    catalog: Optional[CitiVeloCatalog],
    cause: BaseException,
) -> Dict[Tuple[str, str, float], str]:
    """Build OTM tags for a currency whose offset level the walk never recorded.

    Only **USD** was walked past ``OTM_RFR.<measure>.ANNUAL``; every other
    currency stops at or above it, so :func:`~MDP.CitiVelocityExcel.tags.vol_otm`
    cannot validate an offset token for them and raises.

    This applies the catalog's own documented rule - *unexpanded siblings inherit
    the shape of the sibling that was expanded* - across the CURRENCY axis: the
    tag is built by :func:`~MDP.CitiVelocityExcel.tags.vol_otm` for the recorded
    currency and only the currency segment is substituted. The offset spelling is
    therefore still derived from the harvest (``OTM_M25`` vs ``OTM_N25`` is
    per-measure and is never guessed here), but the resulting tag is
    **shape-inferred and unverified**: nothing has ever asked the add-in for it.
    Validate with ``client.validate()`` before relying on a non-USD skew cube.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    reference = _offset_reference_currency(cat, str(measure).upper())
    if reference is None:
        raise UnknownTagError(
            f"{cause} No currency under RATES.VOL has a recorded strike-offset level for "
            f"measure {measure!r}, so there is no sibling shape to inherit. Pass the tags "
            "straight to the client - it accepts any RATES.* string - and assemble the cube "
            "with cube_from_quotes()."
        ) from cause

    ref_ccy, ref_node = reference
    if ref_ccy.upper() == str(currency).upper():
        raise UnknownTagError(str(cause)) from cause

    _logger.warning(
        "RATES.VOL.%s.OTM_RFR.%s has no recorded strike-offset level; inheriting the shape of "
        "%s (the only expanded sibling). The resulting tags are SHAPE-INFERRED and unverified - "
        "run client.validate() on them before trusting a %s skew cube.",
        str(currency).upper(),
        str(measure).upper(),
        ref_node,
        str(currency).upper(),
    )

    out: Dict[Tuple[str, str, float], str] = {}
    for (exp, ten, off), tag in cv_tags.vol_otm_grid(
        ref_ccy,
        list(offsets_bp),
        expiries=list(expiries),
        tenors=list(tenors),
        measure=measure,
        catalog=cat,
    ).items():
        parts = tag.split(".")
        parts[2] = str(currency).upper()  # RATES . VOL . <ccy> . ...
        out[(exp, ten, off)] = ".".join(parts)
    return out


# ------------------------------------------------------------------ #
#                          cube construction                         #
# ------------------------------------------------------------------ #


def cube_from_quotes(
    *,
    quotes: Mapping[str, float],
    currency: str,
    as_of: datetime.date,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets_bp: Sequence[float] = (),
    measure: str = "NORMAL",
    skew_measure: str = "NORMALABSOLUTE",
    served_unit: str = "bp",
    strict: bool = True,
    source: str = "citivelo_excel",
    catalog: Optional[CitiVeloCatalog] = None,
) -> SwaptionCubeData:
    """Assemble a :class:`SwaptionCubeData` from ``{tag: value}``.

    Parameters
    ----------
    quotes
        Tag -> served number, exactly as the add-in gave it (no rescaling).
    served_unit
        ``'bp'`` (default), ``'decimal'`` or ``'percent'``. See the module
        docstring: this is a declaration, guarded by :func:`assert_vol_units`,
        not something the code sniffs.
    strict
        ``True`` raises when any node of the requested grid is missing. ``False``
        DROPS whole expiries or tenors that are incomplete and logs which - it
        never NaN-fills, because a NaN column that ships as "success" is the
        exact failure ``_assert_risk_populated`` was added to stop.

    Returns
    -------
    SwaptionCubeData
        Already :meth:`~SwaptionCubeData.validate`-d.

    Raises
    ------
    RaggedCubeError
        Missing nodes under ``strict=True``, or nothing left after dropping.
    VolUnitError
        Served magnitudes inconsistent with ``served_unit``.
    """
    meas = str(measure).upper()
    skew_meas = str(skew_measure).upper()
    if meas != "NORMAL":
        raise ValueError(
            f"measure={measure!r} does not serve a normal vol. Only 'NORMAL' builds a "
            "Bachelier cube; BLACK is lognormal and PREMIUM/FWDPREMIUM are prices."
        )
    wanted = cube_tags(
        currency=currency,
        expiries=expiries,
        tenors=tenors,
        offsets_bp=offsets_bp,
        measure=meas,
        skew_measure=skew_meas,
        catalog=catalog,
    )

    missing = [t for t in wanted if t not in quotes or not np.isfinite(float(quotes.get(t, np.nan)))]
    if missing and strict:
        raise RaggedCubeError(
            f"{len(missing)} of {len(wanted)} cube tag(s) have no finite quote, e.g. "
            f"{', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}. "
            "Narrow expiries=/tenors=/offsets_bp= to what the add-in actually serves, or pass "
            "strict=False to DROP incomplete expiries/tenors (never to NaN-fill them)."
        )

    served: list[float] = []
    served_spread: list[float] = []
    for tag, (kind, _e, _t, _o) in wanted.items():
        value = quotes.get(tag)
        if value is None or not np.isfinite(float(value)):
            continue
        if kind == "OTM" and skew_meas in SPREAD_SKEW_MEASURES:
            served_spread.append(float(value))
        else:
            served.append(float(value))
    assert_vol_units(served, unit=served_unit, kind="level", label=f"{currency} {meas}")
    if served_spread:
        assert_vol_units(
            served_spread, unit=served_unit, kind="spread", label=f"{currency} {skew_meas}"
        )

    scale = VOL_UNIT_TO_BP[served_unit]

    exp_axis, ten_axis = default_cube_axes(
        currency, measure=meas, expiries=expiries, tenors=tenors, catalog=catalog
    )
    signed_offsets = sorted({float(o) for o in offsets_bp if float(o) != 0.0})

    atm = pd.DataFrame(np.nan, index=list(exp_axis), columns=list(ten_axis), dtype=float)
    frames = {
        off: pd.DataFrame(np.nan, index=list(exp_axis), columns=list(ten_axis), dtype=float)
        for off in signed_offsets
    }
    for tag, (kind, exp, ten, off) in wanted.items():
        value = quotes.get(tag)
        if value is None or not np.isfinite(float(value)):
            continue
        scaled = float(value) * scale
        if kind == "ATM":
            atm.at[exp, ten] = scaled
        else:
            frames[off].at[exp, ten] = scaled

    if skew_meas in SPREAD_SKEW_MEASURES:
        # NORMALSKEW serves vol - atm; store the level so every offset is
        # directly comparable with the ATM surface and with NORMALABSOLUTE.
        frames = {off: (atm + frame) for off, frame in frames.items()}

    if not strict:
        atm, frames = _drop_incomplete(atm, frames)

    cube = SwaptionCubeData(
        as_of=as_of,
        currency=str(currency).upper(),
        measure=meas,
        atm=atm,
        skew=frames,
        skew_measure=skew_meas,
        served_unit=served_unit,
        vol_unit="bp",
        strike_unit="bp",
        source=source,
    )
    return cube.validate()


def _largest_rectangle(mask: pd.DataFrame) -> Tuple[list[str], list[str]]:
    """The biggest fully-populated expiry x tenor block, by a two-pass heuristic.

    Maximum-rectangle over a binary matrix is NP-hard in general, so this tries
    the two obvious orders - drop incomplete rows then incomplete columns, and
    the reverse - and keeps whichever retains more cells, breaking ties towards
    more expiries. When both come back empty it shrinks greedily, dropping
    whichever axis entry carries the most holes.

    Documented as a heuristic on purpose: it is a convenience for ``strict=False``,
    not a guarantee of maximality.
    """

    def rows_then_cols() -> Tuple[list[str], list[str]]:
        rows = [e for e in mask.index if bool(mask.loc[e].all())]
        if not rows:
            return [], []
        sub = mask.loc[rows]
        return rows, [t for t in mask.columns if bool(sub[t].all())]

    def cols_then_rows() -> Tuple[list[str], list[str]]:
        cols = [t for t in mask.columns if bool(mask[t].all())]
        if not cols:
            return [], []
        sub = mask[cols]
        return [e for e in mask.index if bool(sub.loc[e].all())], cols

    candidates = [rows_then_cols(), cols_then_rows()]
    best_rows, best_cols = max(candidates, key=lambda rc: (len(rc[0]) * len(rc[1]), len(rc[0])))
    if best_rows and best_cols:
        return best_rows, best_cols

    rows = [e for e in mask.index if bool(mask.loc[e].any())]
    cols = [t for t in mask.columns if bool(mask[t].any())]
    sub = mask.loc[rows, cols] if rows and cols else mask.iloc[:0, :0]
    while rows and cols and not bool(sub.to_numpy().all()):
        row_bad = (~sub).sum(axis=1)
        col_bad = (~sub).sum(axis=0)
        if float(row_bad.max()) >= float(col_bad.max()):
            rows = [e for e in rows if e != row_bad.idxmax()]
        else:
            cols = [t for t in cols if t != col_bad.idxmax()]
        sub = mask.loc[rows, cols] if rows and cols else mask.iloc[:0, :0]
    return rows, cols


def _drop_incomplete(
    atm: pd.DataFrame, frames: Mapping[float, pd.DataFrame]
) -> Tuple[pd.DataFrame, Dict[float, pd.DataFrame]]:
    """Drop expiries/tenors that are not fully populated across every offset.

    Dropping, never filling: a NaN that survives into a solver is indistinguishable
    from a real number until it reaches a P&L.
    """
    stack = [atm] + [frames[o] for o in sorted(frames)]
    complete = ~np.any([f.isna().to_numpy() for f in stack], axis=0)
    mask = pd.DataFrame(complete, index=atm.index, columns=atm.columns)

    keep_rows, keep_cols = _largest_rectangle(mask)

    dropped_rows = [e for e in atm.index if e not in keep_rows]
    dropped_cols = [t for t in atm.columns if t not in keep_cols]
    if dropped_rows or dropped_cols:
        _logger.warning(
            "SwaptionCubeData: dropped %d expiry(ies) %s and %d tenor(s) %s with incomplete "
            "quotes (strict=False). Nothing was NaN-filled.",
            len(dropped_rows),
            dropped_rows,
            len(dropped_cols),
            dropped_cols,
        )
    if not keep_rows or not keep_cols:
        raise RaggedCubeError(
            "strict=False left no complete expiry x tenor rectangle. Every requested node is "
            "missing at least one offset - check offsets_bp= against the recorded OTM axis."
        )
    return (
        atm.loc[keep_rows, keep_cols],
        {off: f.loc[keep_rows, keep_cols] for off, f in frames.items()},
    )


# ------------------------------------------------------------------ #
#                              fetching                              #
# ------------------------------------------------------------------ #


def fetch_cube(
    *,
    client: Any,
    currency: str,
    as_of: Optional[datetime.date] = None,
    expiries: Optional[Sequence[str]] = None,
    tenors: Optional[Sequence[str]] = None,
    offsets_bp: Sequence[float] = (),
    cache: Optional[Any] = None,
    freq: str = "DAILY",
    measure: str = "NORMAL",
    skew_measure: str = "NORMALABSOLUTE",
    served_unit: str = "bp",
    price_point: str = "CLOSE",
    period: Optional[str] = None,
    max_staleness_days: int = 7,
    strict: bool = True,
    catalog: Optional[CitiVeloCatalog] = None,
) -> SwaptionCubeData:
    """Fetch one dated cube through the add-in, optionally via the parquet cache.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient` (or
        the fake from :mod:`MDP.CitiVelocityExcel.testing`).
    as_of
        Observation date. ``None`` takes the latest date present in EVERY series,
        which is the only date on which the whole cube is simultaneous.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`. When given, the
        cache does the fetching and only the missing spans hit Excel.
    max_staleness_days
        A node whose last observation is more than this many days before
        ``as_of`` raises rather than being carried forward. A stale vol carried
        into a live cube is a wrong number that looks right.

    Returns
    -------
    SwaptionCubeData

    Raises
    ------
    RaggedCubeError
        No common date across the requested tags, or a stale node.
    """
    wanted = cube_tags(
        currency=currency,
        expiries=expiries,
        tenors=tenors,
        offsets_bp=offsets_bp,
        measure=measure,
        skew_measure=skew_measure,
        catalog=catalog,
    )
    tag_list = list(wanted)

    if cache is not None:
        def _fetcher(
            tags_: Sequence[str],
            freq_: str,
            start_: Optional[datetime.datetime],
            end_: Optional[datetime.datetime],
            point_: str,
        ) -> Dict[str, pd.Series]:
            return client.fetch_timeseries(
                tags_, freq_, start=start_, end=end_, price_point=point_, period=period
            )

        series = cache.get(
            tag_list, freq, price_point=price_point, fetcher=_fetcher, end=as_of
        )
    else:
        series = client.fetch_timeseries(
            tag_list, freq, price_point=price_point, period=period, end=as_of
        )

    if not series:
        failures = getattr(client, "last_failures", lambda: {})()
        raise RaggedCubeError(
            f"No {currency} vol series returned for {len(tag_list)} tag(s). "
            f"Per-tag failures: {dict(list(failures.items())[:8])}"
        )

    stamp = _common_as_of(series, as_of=as_of)
    quotes: Dict[str, float] = {}
    stale: list[str] = []
    for tag, s in series.items():
        head = s[s.index <= pd.Timestamp(stamp)]
        if head.empty:
            continue
        last_index = head.index[-1]
        if (pd.Timestamp(stamp) - last_index).days > int(max_staleness_days):
            stale.append(f"{tag}@{last_index.date()}")
            continue
        quotes[tag] = float(head.iloc[-1])

    if stale:
        raise RaggedCubeError(
            f"{len(stale)} node(s) are more than {max_staleness_days} day(s) stale at {stamp}: "
            f"{', '.join(stale[:8])}{' ...' if len(stale) > 8 else ''}. Raise max_staleness_days= "
            "deliberately if a carried-forward quote is genuinely acceptable."
        )

    return cube_from_quotes(
        quotes=quotes,
        currency=currency,
        as_of=pd.Timestamp(stamp).date(),
        expiries=expiries,
        tenors=tenors,
        offsets_bp=offsets_bp,
        measure=measure,
        skew_measure=skew_measure,
        served_unit=served_unit,
        strict=strict,
        source=f"citivelo_excel/{freq}/{price_point}",
        catalog=catalog,
    )


def _common_as_of(
    series: Mapping[str, pd.Series], *, as_of: Optional[datetime.date]
) -> pd.Timestamp:
    """The latest date at or before ``as_of`` that EVERY series reaches."""
    if not series:
        raise RaggedCubeError("No series to date the cube from.")
    cutoff = pd.Timestamp(as_of) if as_of is not None else None
    lasts: list[pd.Timestamp] = []
    for tag, s in series.items():
        head = s if cutoff is None else s[s.index <= cutoff]
        if head.empty:
            raise RaggedCubeError(
                f"{tag} has no observation at or before {as_of}. Pass an as_of the whole cube "
                "reaches, or narrow the grid."
            )
        lasts.append(head.index[-1])
    return min(lasts)
