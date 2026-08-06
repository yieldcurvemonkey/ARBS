r"""The Citi Velocity swaption vol cube, in both backends.

Citi publishes the cube already gridded - ``expiry x swap tenor x strike
offset`` - so this package's job is to read it faithfully and hand it to a
pricer, not to build a surface out of scattered quotes::

    RATES.VOL.<ccy>.ATM_RFR.NORMAL.ANNUAL.<expiry>.<tenor>
    RATES.VOL.<ccy>.OTM_RFR.NORMALABSOLUTE.ANNUAL.OTM_<off>.<expiry>.<tenor>

Layers
------
``cube_data``  :class:`SwaptionCubeData`, the dated, unit-explicit record, plus
               tag construction and the cached-then-live fetch
``ql_cube``    ``ql.SwaptionVolatilityMatrix`` -> ``ql.InterpolatedSwaptionVolatilityCube``
               (or the SABR variant), with the volSpreads row-ordering contract
               enforced by :func:`assert_vol_spread_ordering`
``rl_cube``    :class:`CitiVeloNormalVolCube`, a locally-built cube over rateslib
               primitives (``PPSplineF64`` + ``Query.Base.bachelier``). Works on
               every supported rateslib, including 2.1.x, which has no IR vol at
               all. This is the DEFAULT backend.
``rl_native_cube``
               :class:`NativeSwaptionCube` over ``rl.IRSplineCube`` and
               ``rl.IRSCall``, available from rateslib 2.7.0. Prices identically
               (~1e-9 relative) but carries AD risk back to the curve and vol
               nodes and can be calibrated inside a ``Solver``. Select it with
               ``build_rl_vol_cube(..., backend='native')``.

The two backends are reconciled node by node by
:func:`~MDP.CitiVelocityExcel.vol.rl_native_cube.compare_backends`, which is what
``harvest/verify_live.py --vol-compare`` runs against real Citi quotes.

Two things worth reading before use
-----------------------------------
**Units are declared, not sniffed.** ``served_unit='bp'`` is the default and it
is an assertion about the wire, guarded by :func:`assert_vol_units`, which raises
rather than rescaling. It has NOT been checked against a live add-in.

**The QuantLib volSpreads matrix is optionTenors-outer, swapTenors-inner.** The
transposed matrix has the same shape, constructs without error and misprices by
several bp. :func:`assert_vol_spread_ordering` reconstructs every node out of the
built object to prove which layout was used.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.vol.cube_data import (
    DEFAULT_OFFSETS_BP,
    DEFAULT_SWAP_TENORS,
    VOL_CURRENCIES,
    RaggedCubeError,
    SwaptionCubeData,
    VolUnitError,
    assert_vol_units,
    cube_from_quotes,
    cube_tags,
    default_cube_axes,
    fetch_cube,
    vol_coverage,
)
from MDP.CitiVelocityExcel.vol.ql_cube import (
    VOL_CCY_DEFAULT_OIS_INDEX,
    QLSwaptionCube,
    VolCubeOrderingError,
    assert_vol_spread_ordering,
    build_ql_atm_matrix,
    build_ql_swaption_cube,
    swap_indices_for,
    vol_spreads_matrix,
)
from MDP.CitiVelocityExcel.vol.rl_cube import (
    CitiVeloNormalVolCube,
    build_rl_vol_cube,
    convention_for_cube,
)
from MDP.CitiVelocityExcel.vol.rl_native_cube import (
    NATIVE_VOL_PARAM_UNIT,
    RATESLIB_NATIVE_AVAILABLE,
    NativeCubeUnverifiedError,
    NativeSwaptionCube,
    assert_native_cube_round_trips,
    build_rl_native_cube,
    build_rl_native_swaption_cube,
    compare_backends,
    irs_series_for,
    native_spline_order,
)

__all__ = [
    "CitiVeloNormalVolCube",
    "NATIVE_VOL_PARAM_UNIT",
    "NativeCubeUnverifiedError",
    "NativeSwaptionCube",
    "RATESLIB_NATIVE_AVAILABLE",
    "assert_native_cube_round_trips",
    "build_rl_native_cube",
    "build_rl_native_swaption_cube",
    "compare_backends",
    "convention_for_cube",
    "irs_series_for",
    "native_spline_order",
    "DEFAULT_OFFSETS_BP",
    "DEFAULT_SWAP_TENORS",
    "QLSwaptionCube",
    "RaggedCubeError",
    "SwaptionCubeData",
    "VOL_CCY_DEFAULT_OIS_INDEX",
    "VOL_CURRENCIES",
    "VolCubeOrderingError",
    "VolUnitError",
    "assert_vol_spread_ordering",
    "assert_vol_units",
    "build_ql_atm_matrix",
    "build_ql_swaption_cube",
    "build_rl_vol_cube",
    "cube_from_quotes",
    "cube_tags",
    "default_cube_axes",
    "fetch_cube",
    "swap_indices_for",
    "vol_coverage",
    "vol_spreads_matrix",
]
