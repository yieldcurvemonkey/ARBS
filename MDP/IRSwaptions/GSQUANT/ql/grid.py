from __future__ import annotations

import datetime as dt
import os
from typing import Iterable

import numpy as np
import pandas as pd
import QuantLib as ql
from gs_quant.data import Dataset
from gs_quant.session import GsSession
from scipy.interpolate import griddata

from definitions.IRSwaptions import ASSET_IDS_MAP, EXPIRY_LABELS, TAIL_LABELS

_DATASET_NAME = "IR_SWAPTION_VOLS_V1_STANDARD"


def _label_to_years(label: str) -> float:
    token = str(label).strip().lower()
    if token.endswith("m"):
        return float(int(token[:-1])) / 12.0
    if token.endswith("y"):
        return float(int(token[:-1]))
    raise ValueError(f"Unsupported tenor label: {label}")


def _label_to_ql_period(label: str) -> ql.Period:
    token = str(label).strip().lower()
    if token.endswith("m"):
        return ql.Period(int(token[:-1]), ql.Months)
    if token.endswith("y"):
        return ql.Period(int(token[:-1]), ql.Years)
    raise ValueError(f"Unsupported tenor label: {label}")


def _interpolate_missing(vol_matrix: np.ndarray) -> np.ndarray:
    if not np.isnan(vol_matrix).any():
        return vol_matrix

    expiry_years = np.array([_label_to_years(e) for e in EXPIRY_LABELS], dtype=float)
    tail_years = np.array([_label_to_years(t) for t in TAIL_LABELS], dtype=float)
    log_exp = np.log(expiry_years)
    log_tail = np.log(tail_years)

    known_mask = ~np.isnan(vol_matrix)
    known_pts = np.array(
        [(log_exp[i], log_tail[j]) for i in range(len(EXPIRY_LABELS)) for j in range(len(TAIL_LABELS)) if known_mask[i, j]],
        dtype=float,
    )
    known_vals = vol_matrix[known_mask]

    if len(known_vals) == 0:
        raise ValueError("No GS swaption vol points available to build a surface.")

    grid_exp, grid_tail = np.meshgrid(log_exp, log_tail, indexing="ij")
    cubic = griddata(known_pts, known_vals, (grid_exp, grid_tail), method="cubic")
    linear = griddata(known_pts, known_vals, (grid_exp, grid_tail), method="linear")
    filled = np.where(np.isnan(cubic), linear, cubic)

    # Final fallback to nearest-neighbor when cubic/linear cannot cover boundaries.
    nearest = griddata(known_pts, known_vals, (grid_exp, grid_tail), method="nearest")
    filled = np.where(np.isnan(filled), nearest, filled)
    return np.where(np.isnan(vol_matrix), filled, vol_matrix)


def _normalize_dates(dates: Iterable[dt.date | dt.datetime | pd.Timestamp]) -> list[dt.date]:
    out: list[dt.date] = []
    seen: set[dt.date] = set()
    for item in dates:
        if isinstance(item, pd.Timestamp):
            d = item.date()
        elif isinstance(item, dt.datetime):
            d = item.date()
        elif isinstance(item, dt.date):
            d = item
        else:
            raise TypeError(f"Unsupported date type: {type(item)}")
        if d not in seen:
            seen.add(d)
            out.append(d)
    return sorted(out)


def _ensure_gs_session() -> None:
    client_id = os.getenv("GS_CLIENT_ID", "2eb2f48872304c1d94fa1642fa691afe").strip()
    client_secret = os.getenv("GS_CLIENT_SECRET", "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4").strip()
    if not client_id or not client_secret:
        raise ValueError("Missing GS credentials. Set GS_CLIENT_ID and GS_CLIENT_SECRET environment variables.")

    GsSession.use(
        client_id=client_id,
        client_secret=client_secret,
        scopes=GsSession.Scopes.get_default(),
    )


def get_atmf_grid(
    curve: str,
    dates: Iterable[dt.date | dt.datetime | pd.Timestamp],
    *,
    surface_type: str = "atmf_normal",
) -> dict[dt.date, ql.SwaptionVolatilityStructureHandle]:
    if str(surface_type).lower() != "atmf_normal":
        raise NotImplementedError(f"Unsupported GS surface_type: {surface_type}")
    if curve not in ASSET_IDS_MAP:
        raise KeyError(f"Curve '{curve}' not configured in definitions.IRSwaptions.ASSET_IDS_MAP")

    date_list = _normalize_dates(dates)
    if not date_list:
        return {}

    _ensure_gs_session()
    asset_map = ASSET_IDS_MAP[curve]

    df = Dataset(_DATASET_NAME).get_data(
        start=min(date_list),
        end=max(date_list),
        assetId=list(asset_map.keys()),
    )

    if df is None or len(df) == 0:
        raise ValueError(f"No GS swaption data returned for curve={curve}, range={min(date_list)}..{max(date_list)}")

    df = df.copy()
    df["swaption_structure"] = df["assetId"].map(asset_map)
    df["bpvol"] = pd.to_numeric(df["impliedNormalVolatility"], errors="coerce") * (252.0 ** 0.5)
    df = df[df["swaption_structure"].notna() & df["bpvol"].notna()]
    if df.empty:
        raise ValueError(f"GS swaption data is empty after mapping for curve={curve}")

    df[["expiry", "tail"]] = df["swaption_structure"].str.split(" ", expand=True)
    surfaces: dict[dt.date, ql.SwaptionVolatilityStructureHandle] = {}

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bdc = ql.ModifiedFollowing
    day_count = ql.Actual365Fixed()

    ql_expiries = ql.PeriodVector()
    for label in EXPIRY_LABELS:
        ql_expiries.append(_label_to_ql_period(label))
    ql_tails = ql.PeriodVector()
    for label in TAIL_LABELS:
        ql_tails.append(_label_to_ql_period(label))

    for d in date_list:
        # Index may be tz-aware timestamp; normalize to date.
        curr_df = df[df.index.map(lambda x: pd.Timestamp(x).date() == d)]
        if curr_df.empty:
            raise ValueError(f"No GS swaption points for curve={curve} on {d.isoformat()}")

        vol_matrix = np.full((len(EXPIRY_LABELS), len(TAIL_LABELS)), np.nan, dtype=float)
        for _, row in curr_df.iterrows():
            try:
                i = EXPIRY_LABELS.index(str(row["expiry"]).lower())
                j = TAIL_LABELS.index(str(row["tail"]).lower())
            except ValueError:
                continue
            vol_matrix[i, j] = float(row["bpvol"])

        vol_matrix = _interpolate_missing(vol_matrix)

        ql_eval = ql.Date(d.day, d.month, d.year)
        ql.Settings.instance().evaluationDate = ql_eval

        ql_vols = ql.Matrix(len(EXPIRY_LABELS), len(TAIL_LABELS))
        for i in range(len(EXPIRY_LABELS)):
            for j in range(len(TAIL_LABELS)):
                # GS bpvol in bp/yr, QuantLib normal vol expects decimal.
                ql_vols[i][j] = float(vol_matrix[i, j]) / 10_000.0

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
        surfaces[d] = handle

    return surfaces

