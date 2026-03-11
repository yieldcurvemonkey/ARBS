from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Iterable, Optional

import numpy as np
import QuantLib as ql

from definitions.IRSwaptions import EXTENDED_EXPIRY_LABELS, EXTENDED_TAIL_LABELS
from MDP.IRSwaptions.MONKEYCUBE.cube import NormalSabrVolCube
from MDP.IRSwaptions.MONKEYCUBE.definitions import resolve_data_dir

# Module-level cache: (curve_name, date_iso) → NormalSabrVolCube
_CUBE_CACHE: dict[tuple[str, str], NormalSabrVolCube] = {}


def _label_to_ql_period(label: str) -> ql.Period:
    token = str(label).strip().lower()
    if token.endswith("m"):
        return ql.Period(int(token[:-1]), ql.Months)
    if token.endswith("y"):
        return ql.Period(int(token[:-1]), ql.Years)
    raise ValueError(f"Unsupported tenor label: {label}")


def _normalize_dates(dates: Iterable[dt.date | dt.datetime]) -> list[dt.date]:
    out: list[dt.date] = []
    seen: set[dt.date] = set()
    for item in dates:
        d = item.date() if isinstance(item, dt.datetime) else item
        if d not in seen:
            seen.add(d)
            out.append(d)
    return sorted(out)


def _load_sabr_params(data_dir: str, d: dt.date) -> dict[str, dict[str, float]] | None:
    """Load SABR params JSON for a single date. Returns None if file not found."""
    path = os.path.join(data_dir, f"{d:%Y-%m-%d}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return data.get("sabr_params", data)


def _build_atm_surface(
    cube: NormalSabrVolCube,
    eval_date: ql.Date,
    expiry_labels: list[str],
    tail_labels: list[str],
) -> ql.SwaptionVolatilityStructureHandle:
    """Build a QuantLib SwaptionVolatilityMatrix of ATM normal vols from the cube."""
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bdc = ql.ModifiedFollowing
    day_count = ql.Actual365Fixed()

    vol_matrix = cube.atm_vol_matrix(expiry_labels, tail_labels)

    ql_expiries = ql.PeriodVector()
    for label in expiry_labels:
        ql_expiries.append(_label_to_ql_period(label))
    ql_tails = ql.PeriodVector()
    for label in tail_labels:
        ql_tails.append(_label_to_ql_period(label))

    ql_vols = ql.Matrix(len(expiry_labels), len(tail_labels))
    for i in range(len(expiry_labels)):
        for j in range(len(tail_labels)):
            ql_vols[i][j] = float(vol_matrix[i, j])

    surf = ql.SwaptionVolatilityMatrix(
        calendar,
        bdc,
        ql_expiries,
        ql_tails,
        ql_vols,
        day_count,
        False,
        ql.Normal,
    )
    handle = ql.SwaptionVolatilityStructureHandle(surf)
    handle.enableExtrapolation()
    return handle


def get_sabr_vol_surfaces(
    *,
    curve_name: str,
    dates: Iterable[dt.date | dt.datetime],
    surface_type: str = "sabr_cube",
    data_dir: Optional[str] = None,
    **kwargs: Any,
) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
    """
    Build SABR vol cubes from YCMONKEY JSON files and return ATM vol surface handles.

    For each date, reads the SABR params JSON, constructs a NormalSabrVolCube,
    caches it, and returns an ATM SwaptionVolatilityMatrix handle for engine
    compatibility. The full cube is accessible via get_cached_cube().

    Parameters
    ----------
    curve_name : str
        Curve identifier (e.g., "USD-SOFR-1D").
    dates : iterable of date
        Dates to build surfaces for.
    surface_type : str
        Surface type label (stored in metadata, not filtered).
    data_dir : str, optional
        Override path to SABR param JSON directory.
    **kwargs
        Additional keyword arguments (forwarded, currently unused).

    Returns
    -------
    dict[dt.date, SwaptionVolatilityStructureHandle]
        ATM normal vol surface handles keyed by date.
    """
    _ = kwargs
    resolved_dir = resolve_data_dir(data_dir)
    date_list = _normalize_dates(dates)
    if not date_list:
        return {}

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dc = ql.Actual365Fixed()

    surfaces: dict[dt.date, ql.SwaptionVolatilityStructureHandle] = {}

    for d in date_list:
        sabr_map = _load_sabr_params(resolved_dir, d)
        if sabr_map is None:
            continue

        ql_eval = ql.Date(d.day, d.month, d.year)
        ql.Settings.instance().evaluationDate = ql_eval

        cube = NormalSabrVolCube(sabr_map, calendar, dc, ql_eval)
        _CUBE_CACHE[(curve_name, d.isoformat())] = cube

        handle = _build_atm_surface(
            cube,
            ql_eval,
            EXTENDED_EXPIRY_LABELS,
            EXTENDED_TAIL_LABELS,
        )
        surfaces[d] = handle

    return surfaces


def get_cached_cube(curve_name: str, d: dt.date) -> NormalSabrVolCube | None:
    """Retrieve a previously built NormalSabrVolCube from the module cache."""
    return _CUBE_CACHE.get((curve_name, d.isoformat()))


def clear_cube_cache() -> None:
    """Clear the module-level cube cache."""
    _CUBE_CACHE.clear()
