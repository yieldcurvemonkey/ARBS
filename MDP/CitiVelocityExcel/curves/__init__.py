"""Swap curves built from Citi Velocity par quotes, in rateslib and QuantLib.

``RATES.OIS.<ccy>_<idx>.PAR.<tenor>`` gives 20 validated RFR curves x 44 tenors.
Velocity supplies the quotes; every curve here is stripped locally, because the
``CVD*`` pricers are not entitled.

Typical use::

    frame = fetch_par_grid(client=client, citi_index="EUR_EUROSTR", period="1Y")
    snap = par_grid_snapshot(frame)                      # last row, asof
    rlc = build_rl_ois_curve(par_rates=snap, ref_date=snap.name,
                             citi_index="EUR_EUROSTR")
    qlc = build_ql_ois_curve(par_rates=snap, ref_date=snap.name,
                             citi_index="EUR_EUROSTR")

Both backends anchor on the same rolled reference date, use the same spot lag,
payment lag and end-of-month rule, and pin their nodes on the same swap maturity
dates. On a synthetic self-consistent grid they agree to 1e-5 bp on 5Yx5Y,
10Yx10Y and 20Yx10Y forwards once the rateslib solver tolerance is tightened
past its default; at the default ``func_tol=1e-9`` the gap is the solver
residual, ~0.002 bp. See ``curves/_smoke.py``.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.curves.conventions import (
    CITI_OIS_CONVENTIONS,
    CurveConvention,
    conventions_for,
    rl_calendar_from_quantlib,
    supported_indices,
)
from MDP.CitiVelocityExcel.curves.par_grid import (
    SNAPSHOT_METHODS,
    fetch_par_grid,
    par_grid_snapshot,
    tenor_columns_from_tags,
)
from MDP.CitiVelocityExcel.curves.ql_builder import (
    END_OF_MONTH_BY_INDEX,
    PAYMENT_LAG_BY_INDEX,
    QLOisCurve,
    build_ql_mirror_curve,
    build_ql_ois_curve,
    evaluation_date,
    ql_forward_rate,
    ql_par_reprice_errors_bp,
)
from MDP.CitiVelocityExcel.curves.rl_builder import (
    build_rl_ois_curve,
    build_rl_ois_curve_from_quotes,
    end_of_month_for,
    forward_rate,
    make_rl_irs,
    par_reprice_errors_bp,
    payment_lag_for,
    spot_date,
)

__all__ = [
    # conventions
    "CITI_OIS_CONVENTIONS",
    "CurveConvention",
    "conventions_for",
    "rl_calendar_from_quantlib",
    "supported_indices",
    "END_OF_MONTH_BY_INDEX",
    "PAYMENT_LAG_BY_INDEX",
    "end_of_month_for",
    "payment_lag_for",
    # par grids
    "SNAPSHOT_METHODS",
    "fetch_par_grid",
    "par_grid_snapshot",
    "tenor_columns_from_tags",
    # rateslib
    "build_rl_ois_curve",
    "build_rl_ois_curve_from_quotes",
    "forward_rate",
    "make_rl_irs",
    "par_reprice_errors_bp",
    "spot_date",
    # QuantLib
    "QLOisCurve",
    "build_ql_mirror_curve",
    "build_ql_ois_curve",
    "evaluation_date",
    "ql_forward_rate",
    "ql_par_reprice_errors_bp",
]
