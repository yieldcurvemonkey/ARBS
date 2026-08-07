r"""The Citi Velocity swaption cube: one pricer, four backends, two libraries.

Citi publishes the cube already gridded - ``expiry x swap tenor x strike
offset`` - so this package's job is to read it faithfully and hand it to a
pricer, not to build a surface out of scattered quotes::

    RATES.VOL.<ccy>.ATM_RFR.NORMAL.ANNUAL.<expiry>.<tenor>
    RATES.VOL.<ccy>.OTM_RFR.NORMALABSOLUTE.ANNUAL.OTM_<off>.<expiry>.<tenor>

Start here
----------
:class:`~MDP.CitiVelocityExcel.vol.swaption_cube.CitiVeloSwaptionCube` is the one
object. It prices ATM **and every OTM offset** through whichever backend it is
asked for, and :meth:`~.CitiVeloSwaptionCube.with_backend` hands back a sibling
on the same data and the same curves::

    cube = build_citivelo_swaption_cube(cube=cube_data, rl_curve=rlc, ql_curve=qlc)
    k = cube.forward("1Y", "10Y") + 25e-4
    cube.price("1Y", "10Y", k, right="payer")
    cube.with_backend("ql").price("1Y", "10Y", k, right="payer")

===============  =========================================================
``rl-native``    ``rl.IRSplineCube`` + ``rl.IRSCall``. AD risk back to the
                 curve and vol nodes; can sit in a ``rateslib.Solver``.
``rl-hand``      ``PPSplineF64`` + ``Query.Base.bachelier``. Works on every
                 supported rateslib, including 2.1.x, which has no IR vol.
``ql``           ``ql.Swaption`` + ``ql.BachelierSwaptionEngine`` over
                 ``ql.InterpolatedSwaptionVolatilityCube``.
``ql-sabr``      the same over ``ql.SabrSwaptionVolatilityCube``. A FIT: it
                 does not reproduce its own input nodes.
===============  =========================================================

Reachable through the repo's seams, not only as a library
---------------------------------------------------------
* ``CitiVeloPricer.swaption_cube(currency, backend=...)`` - the Citi Velocity MDP.
* ``IRSwaptionMDP(source="CITIVELO-QL")`` / ``"CITIVELO-RL"`` - the repo's own
  swaption product, so every ``Query/IRSwaptions`` structure, value metric and
  strike spelling (``"ATMF+25"``) applies to the Citi cube.

Layers
------
``cube_data``      :class:`SwaptionCubeData`, the dated, unit-explicit record.
                   This is the data layer and it is unchanged.
``swaption_cube``  :class:`CitiVeloSwaptionCube`, the one pricer.
``spot_check``     price -> invert -> compare against Citi's quote. The check
                   that can actually fail; see below.
``live_snapshot``  recorded live captures, so the above runs offline on real
                   quotes.
``rl_cube`` / ``rl_native_cube`` / ``ql_cube`` / ``ql_pricing``
                   the internals :class:`CitiVeloSwaptionCube` delegates to.
                   Their entry points still work exactly as they did.

Three things worth reading before use
--------------------------------------
**A vol -> cube -> vol round trip is a tautology.** Every interpolator here is
exact at its own data sites, so reading a node back out and comparing it with the
quote scores 2.8e-14 bp and proves nothing about the annuity, the schedule, the
day count, the discounting or the strike alignment.
:func:`~MDP.CitiVelocityExcel.vol.spot_check.spot_check_frame` prices the
swaption and inverts the premium with a solver that shares no code with either
pricer, and it is mutation-tested against real Citi quotes.

**Units are declared, not sniffed.** ``served_unit='bp'`` is an assertion about
the wire, guarded by :func:`assert_vol_units`, which raises rather than rescaling.
It was measured live on 2026-08-05: USD 1Y10Y served ``80.9518``, which is basis
points. The other measures (``PREMIUM``, ``FWDPREMIUM``, and the ``OTM_RFR`` skew
branches) have NOT been measured and need not share it.

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
from MDP.CitiVelocityExcel.vol.live_snapshot import (
    LiveCubeSnapshot,
    available_snapshots,
    load_snapshot,
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
from MDP.CitiVelocityExcel.vol.ql_pricing import QLSwaptionPricer
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
from MDP.CitiVelocityExcel.vol.spot_check import (
    DEFAULT_TOLERANCES,
    SpotCheckError,
    assert_spot_check,
    build_ql_mirror_curve,
    format_spot_check_report,
    node_error_matrix,
    spot_check_frame,
    summarise_spot_check,
)
from MDP.CitiVelocityExcel.vol.swaption_cube import (
    BACKEND_LIBRARY,
    BACKENDS,
    CitiVeloSwaptionCube,
    UnavailableBackendError,
    build_citivelo_swaption_cube,
    normalise_backend,
)

__all__ = [
    # the one pricer
    "BACKENDS",
    "BACKEND_LIBRARY",
    "CitiVeloSwaptionCube",
    "UnavailableBackendError",
    "build_citivelo_swaption_cube",
    "normalise_backend",
    # the check that can fail
    "DEFAULT_TOLERANCES",
    "SpotCheckError",
    "assert_spot_check",
    "build_ql_mirror_curve",
    "format_spot_check_report",
    "node_error_matrix",
    "spot_check_frame",
    "summarise_spot_check",
    # recorded live quotes
    "LiveCubeSnapshot",
    "available_snapshots",
    "load_snapshot",
    # the data layer
    "DEFAULT_OFFSETS_BP",
    "DEFAULT_SWAP_TENORS",
    "RaggedCubeError",
    "SwaptionCubeData",
    "VOL_CURRENCIES",
    "VolUnitError",
    "assert_vol_units",
    "cube_from_quotes",
    "cube_tags",
    "default_cube_axes",
    "fetch_cube",
    "vol_coverage",
    # the internals, still public because 31 tests pin them by name
    "CitiVeloNormalVolCube",
    "NATIVE_VOL_PARAM_UNIT",
    "NativeCubeUnverifiedError",
    "NativeSwaptionCube",
    "QLSwaptionCube",
    "QLSwaptionPricer",
    "RATESLIB_NATIVE_AVAILABLE",
    "VOL_CCY_DEFAULT_OIS_INDEX",
    "VolCubeOrderingError",
    "assert_native_cube_round_trips",
    "assert_vol_spread_ordering",
    "build_ql_atm_matrix",
    "build_ql_swaption_cube",
    "build_rl_native_cube",
    "build_rl_native_swaption_cube",
    "build_rl_vol_cube",
    "compare_backends",
    "convention_for_cube",
    "irs_series_for",
    "native_spline_order",
    "swap_indices_for",
    "vol_spreads_matrix",
]
