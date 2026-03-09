"""
Builds a live intraday ATMF swaption surface from GS EOD grids and SDR straddles.

The pipeline is split into three modes:
  - range: backfill EOD surfaces, fit/store the PCA model, and freeze close snapshots
  - once: build today's live snapshots once
  - service: refresh live snapshots on a polling loop
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import QuantLib as ql
from scipy.interpolate import griddata
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from tqdm import tqdm

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP, IRSwaptionMarketContext
from Query.Base.query_resolution import resolve_query
from Query.IRSwaptions import IRSwaptionQuery, IRSwaptionStructure, IRSwaptionValue
from RVUtils.surface_pca_model import (
    ConditionalMVNUpdateResult,
    SurfacePCAModel,
    conditional_mvn_update,
    fit_surface_pca_from_eod_grids,
)
from definitions.IRSwaptions import (
    EXPIRY_LABELS,
    EXTENDED_EXPIRY_LABELS,
    EXTENDED_TAIL_LABELS,
    SURFACE_NODE_KEYS,
    TAIL_LABELS,
)


EOD_HISTORY_TABLE = "arbs_atmf_grid_eod_history_v1"
PCA_MODELS_TABLE = "arbs_atmf_grid_pca_models_v1"
SNAPSHOTS_TABLE = "arbs_live_atmf_grid_snapshots_v1"
OBSERVATIONS_TABLE = "arbs_live_atmf_grid_observations_v1"
MANUAL_STRADDLES_TABLE = "arbs_swaption_manual_straddles_v1"

DEFAULT_CURVE_NAME = "USD-SOFR-1D"
DEFAULT_SURFACE_TYPE = "atmf_normal"
DEFAULT_COMPONENTS = 5
DEFAULT_LOOKBACK_BUSINESS_DAYS = 520
DEFAULT_HALF_LIFE_MINUTES = 120.0
DEFAULT_MAX_STALENESS_MINUTES = 480.0
DEFAULT_BASE_NOISE_BPVOL = 0.5
DEFAULT_TENOR_WEIGHT = 0.7
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_PREMIUM_NOTIONAL = 100_000_000.0
DIRECT_OBSERVATION_ANCHOR_MIN_WEIGHT = 0.95
DIRECT_ANCHOR_PROPAGATION_LENGTH_SCALE = 0.7
DIRECT_ANCHOR_PROPAGATION_PRIOR_WEIGHT = 1.0
ET_ZONE = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR_ET = 17
IDB_MIC_CODES = {"BGCD", "ISWV", "TPSE"}
ACTION_ALLOWLIST = ("NEWT", "MODI", "CORR")
STRADDLE_STYLE = "EURO VANILLA PHYS"
STRADDLE_SPLIT_FACTOR = 0.5
ASSUMED_STRADDLE_MAX_STRIKE_OFFSET_BPS = 3.0
ASSUMED_STRADDLE_MIN_RATIO_TO_REFERENCE = 1.45
ASSUMED_STRADDLE_MAX_RATIO_TO_REFERENCE = 2.95

SNAPSHOT_KIND_INTRADAY = "intraday"
SNAPSHOT_KIND_CLOSE_PCA = "close_pca"
SNAPSHOT_KIND_CLOSE_MDP = "close_mdp"
SNAPSHOT_KINDS = (
    SNAPSHOT_KIND_INTRADAY,
    SNAPSHOT_KIND_CLOSE_PCA,
    SNAPSHOT_KIND_CLOSE_MDP,
)

CALIBRATION_PRESETS: dict[str, dict[str, Any]] = {
    "idb_straddles": {"platform_types": {"idb"}},
    "custy_only": {"platform_types": {"custy"}},
    "custy_and_idb": {"platform_types": {"idb", "custy"}},
}

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {EOD_HISTORY_TABLE} (
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    surface_type TEXT NOT NULL,
    source TEXT NOT NULL,
    grid_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, curve_name, surface_type)
);

CREATE TABLE IF NOT EXISTS {PCA_MODELS_TABLE} (
    curve_name TEXT NOT NULL,
    surface_type TEXT NOT NULL,
    fitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    explained_variance_ratio DOUBLE PRECISION,
    model_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (curve_name, surface_type)
);

CREATE TABLE IF NOT EXISTS {SNAPSHOTS_TABLE} (
    snapshot_id BIGSERIAL PRIMARY KEY,
    as_of_date DATE NOT NULL,
    eod_as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    surface_type TEXT NOT NULL,
    calibration_preset TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT '{SNAPSHOT_KIND_INTRADAY}',
    snapshot_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    grid_data JSONB NOT NULL,
    eod_grid_data JSONB NOT NULL,
    node_metadata JSONB NOT NULL,
    pca_factors JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    calibration_config JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    observation_count INTEGER NOT NULL DEFAULT 0,
    filtered_out_count INTEGER NOT NULL DEFAULT 0,
    last_observation_ts TIMESTAMPTZ,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {OBSERVATIONS_TABLE} (
    as_of_date DATE NOT NULL,
    curve_name TEXT NOT NULL,
    surface_type TEXT NOT NULL,
    calibration_preset TEXT NOT NULL,
    package_id TEXT NOT NULL,
    execution_timestamp TIMESTAMPTZ NOT NULL,
    grid_node_key TEXT NOT NULL,
    display_node_key TEXT NOT NULL,
    expiry_label TEXT NOT NULL,
    tenor_label TEXT NOT NULL,
    display_expiry_label TEXT NOT NULL,
    display_tenor_label TEXT NOT NULL,
    observed_bpvol DOUBLE PRECISION NOT NULL,
    delta_bpvol DOUBLE PRECISION,
    premium DOUBLE PRECISION,
    notional DOUBLE PRECISION,
    platform_type TEXT,
    platform_identifier TEXT,
    event_action TEXT,
    mapping_distance DOUBLE PRECISION,
    staleness_weight DOUBLE PRECISION,
    age_minutes DOUBLE PRECISION,
    trade_label TEXT,
    trade_metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, curve_name, surface_type, calibration_preset, package_id)
);

CREATE INDEX IF NOT EXISTS idx_atmf_history_curve_date
    ON {EOD_HISTORY_TABLE}(curve_name, surface_type, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_atmf_snapshots_lookup
    ON {SNAPSHOTS_TABLE}(curve_name, surface_type, calibration_preset, snapshot_kind, as_of_date DESC, snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_atmf_snapshots_latest
    ON {SNAPSHOTS_TABLE}(calibration_preset, snapshot_kind, as_of_date DESC, snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS idx_atmf_obs_lookup
    ON {OBSERVATIONS_TABLE}(calibration_preset, as_of_date DESC, execution_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_atmf_obs_node
    ON {OBSERVATIONS_TABLE}(display_node_key, calibration_preset, execution_timestamp DESC);
"""

SCHEMA_PATCH_SQL = [
    (
        f"ALTER TABLE {SNAPSHOTS_TABLE} "
        f"ADD COLUMN IF NOT EXISTS snapshot_kind TEXT NOT NULL DEFAULT '{SNAPSHOT_KIND_INTRADAY}'"
    ),
    (
        f"CREATE INDEX IF NOT EXISTS idx_atmf_snapshots_kind_lookup "
        f"ON {SNAPSHOTS_TABLE}(calibration_preset, snapshot_kind, as_of_date DESC, snapshot_ts DESC)"
    ),
    (
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_atmf_snapshots_unique_frozen "
        f"ON {SNAPSHOTS_TABLE}(curve_name, surface_type, calibration_preset, as_of_date, snapshot_kind) "
        f"WHERE snapshot_kind IN ('{SNAPSHOT_KIND_CLOSE_PCA}', '{SNAPSHOT_KIND_CLOSE_MDP}')"
    ),
]


_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)([DWMY])$", re.IGNORECASE)


@dataclass(frozen=True)
class GridNode:
    key: str
    expiry_label: str
    tenor_label: str
    expiry_years: float
    tenor_years: float


@dataclass
class StraddleObservation:
    package_id: str
    execution_timestamp: dt.datetime
    forward_label: str | None
    tenor_label: str | None
    forward_years: float | None
    tenor_years: float | None
    observed_bpvol: float
    premium: float | None
    notional: float | None
    platform_identifier: str | None
    platform_type: str
    event_action: str | None
    trade_label: str
    core_node_key: str | None = None
    display_node_key: str | None = None
    mapping_distance: float | None = None
    display_mapping_distance: float | None = None
    staleness_weight: float = 1.0
    age_minutes: float = 0.0
    delta_bpvol: float | None = None
    grid_weights: dict[str, float] | None = None
    is_inferred_incomplete: bool = False
    inferred_reason: str | None = None
    source_package_type: str | None = None
    is_manual_straddle: bool = False

    def to_trade_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "forward_label": self.forward_label,
            "tenor_label": self.tenor_label,
            "forward_years": self.forward_years,
            "tenor_years": self.tenor_years,
            "source_package_type": self.source_package_type,
            "is_inferred_incomplete_straddle": self.is_inferred_incomplete,
            "inferred_reason": self.inferred_reason,
            "is_manual_straddle": self.is_manual_straddle,
        }
        if self.grid_weights is not None:
            meta["grid_weights"] = self.grid_weights
            meta["weight_concentration"] = max(self.grid_weights.values()) if self.grid_weights else 1.0
        return meta

    def to_calibration_observation(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "packageId": self.package_id,
            "executionTimestamp": int(self.execution_timestamp.timestamp() * 1000),
            "platform": self.platform_identifier,
            "packageType": "STRADDLE",
            "bpvolYr": self.observed_bpvol,
            "premium": self.premium,
            "notional": self.notional,
            "tradeLabel": self.trade_label,
            "isCalibrationTrade": True,
            "gridNodeKey": self.core_node_key,
            "displayNodeKey": self.display_node_key,
            "expiry": self.forward_label.upper() if self.forward_label else None,
            "tenor": self.tenor_label.upper() if self.tenor_label else None,
            "mappingDistance": self.mapping_distance,
            "stalenessWeight": self.staleness_weight,
            "deltaBpvol": self.delta_bpvol,
        }
        if self.grid_weights is not None:
            result["gridWeights"] = self.grid_weights
        return result


@dataclass(frozen=True)
class PremiumQuote:
    premium: float
    premium_bps: float


def _label_to_years(label: str) -> float:
    match = _TOKEN_RE.match(str(label).strip())
    if not match:
        raise ValueError(f"Unsupported tenor label: {label}")
    value = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "D":
        return value / 365.0
    if unit == "W":
        return value / 52.0
    if unit == "M":
        return value / 12.0
    if unit == "Y":
        return value
    raise ValueError(f"Unsupported tenor label: {label}")


def _label_to_period(label: str) -> ql.Period:
    match = _TOKEN_RE.match(str(label).strip())
    if not match:
        raise ValueError(f"Unsupported tenor label: {label}")
    value = int(float(match.group(1)))
    unit = match.group(2).upper()
    if unit == "D":
        return ql.Period(value, ql.Days)
    if unit == "W":
        return ql.Period(value, ql.Weeks)
    if unit == "M":
        return ql.Period(value, ql.Months)
    if unit == "Y":
        return ql.Period(value, ql.Years)
    raise ValueError(f"Unsupported tenor label: {label}")


def _with_years(nodes: list[tuple[str, str]]) -> list[GridNode]:
    return [
        GridNode(
            key=f"{expiry}_{tenor}",
            expiry_label=expiry,
            tenor_label=tenor,
            expiry_years=_label_to_years(expiry),
            tenor_years=_label_to_years(tenor),
        )
        for expiry, tenor in nodes
    ]


CORE_GRID_NODES = _with_years(
    [(expiry, tenor) for expiry in EXPIRY_LABELS for tenor in TAIL_LABELS]
)
DISPLAY_GRID_NODES = _with_years(
    [(expiry, tenor) for expiry in EXTENDED_EXPIRY_LABELS for tenor in EXTENDED_TAIL_LABELS]
)


def _pythonify(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_pythonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _pythonify(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return [_pythonify(item) for item in value.tolist()]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _to_json(value: Any) -> str:
    return json.dumps(_pythonify(value))


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _interpolate_surface_matrix(vol_matrix: np.ndarray) -> np.ndarray:
    if not np.isnan(vol_matrix).any():
        return vol_matrix

    expiry_years = np.array([_label_to_years(label) for label in EXPIRY_LABELS], dtype=float)
    tail_years = np.array([_label_to_years(label) for label in TAIL_LABELS], dtype=float)
    log_expiry = np.log(expiry_years)
    log_tail = np.log(tail_years)

    known_mask = ~np.isnan(vol_matrix)
    known_values = vol_matrix[known_mask]
    if len(known_values) == 0:
        raise ValueError("Surface grid is missing all core nodes.")

    known_points = np.array(
        [
            (log_expiry[i], log_tail[j])
            for i in range(len(EXPIRY_LABELS))
            for j in range(len(TAIL_LABELS))
            if known_mask[i, j]
        ],
        dtype=float,
    )
    grid_expiry, grid_tail = np.meshgrid(log_expiry, log_tail, indexing="ij")

    def _run_griddata(method: str) -> np.ndarray:
        try:
            return griddata(
                known_points,
                known_values,
                (grid_expiry, grid_tail),
                method=method,
            )
        except Exception:
            return np.full_like(vol_matrix, np.nan, dtype=float)

    cubic = _run_griddata("cubic")
    linear = _run_griddata("linear")
    filled = np.where(np.isnan(cubic), linear, cubic)

    # Final fallback to nearest-neighbor when cubic/linear cannot cover boundaries.
    nearest = _run_griddata("nearest")
    filled = np.where(np.isnan(filled), nearest, filled)
    return np.where(np.isnan(vol_matrix), filled, vol_matrix)


def _complete_surface_grid(grid_data: Mapping[str, Any]) -> dict[str, float]:
    vol_matrix = np.full((len(EXPIRY_LABELS), len(TAIL_LABELS)), np.nan, dtype=float)
    for expiry_index, expiry_label in enumerate(EXPIRY_LABELS):
        for tail_index, tail_label in enumerate(TAIL_LABELS):
            node_key = f"{expiry_label}_{tail_label}"
            bpvol = _parse_optional_float(grid_data.get(node_key))
            if bpvol is not None:
                vol_matrix[expiry_index, tail_index] = float(bpvol)

    completed = _interpolate_surface_matrix(vol_matrix)
    out: dict[str, float] = {}
    for expiry_index, expiry_label in enumerate(EXPIRY_LABELS):
        for tail_index, tail_label in enumerate(TAIL_LABELS):
            node_key = f"{expiry_label}_{tail_label}"
            value = completed[expiry_index, tail_index]
            if not np.isfinite(value):
                raise ValueError(f"Missing bpvol for swaption node {node_key}")
            out[node_key] = float(value)
    return out


def _extract_metric_number(metrics: Any, key: str) -> float | None:
    if not isinstance(metrics, Mapping) or key not in metrics:
        return None
    raw = metrics.get(key)
    if isinstance(raw, list) and raw:
        raw = raw[0]
    return _parse_optional_float(raw)


def _split_platform_tokens(platform_identifier: str | None) -> list[str]:
    if not platform_identifier:
        return []
    return [
        token
        for token in re.split(r"[\s,;/]+", platform_identifier.upper())
        if token
    ]


def _classify_platform(platform_identifier: str | None) -> str:
    tokens = _split_platform_tokens(platform_identifier)
    return "idb" if any(token in IDB_MIC_CODES for token in tokens) else "custy"


def _action_allowed(event_action: str | None) -> bool:
    if not event_action:
        return False
    normalized = event_action.upper()
    return normalized.startswith(ACTION_ALLOWLIST)


def _now_et() -> dt.datetime:
    return dt.datetime.now(tz=ET_ZONE)


def _log_status(message: str, *, level: str = "INFO") -> None:
    timestamp = _now_et().isoformat()
    tqdm.write(f"[{timestamp}] [{level}] {message}")


def _format_date_span(dates: Iterable[dt.date]) -> str:
    ordered = sorted(set(dates))
    if not ordered:
        return "empty"
    return f"{ordered[0].isoformat()} -> {ordered[-1].isoformat()} ({len(ordered)} dates)"


def _current_trade_date() -> dt.date:
    return _now_et().date()


def _is_after_market_close(now: dt.datetime | None = None) -> bool:
    current = (now or _now_et()).astimezone(ET_ZONE)
    return current.hour >= MARKET_CLOSE_HOUR_ET


def _market_close_timestamp(value: dt.date) -> dt.datetime:
    return dt.datetime.combine(
        value,
        dt.time(hour=MARKET_CLOSE_HOUR_ET, tzinfo=ET_ZONE),
    )


def _previous_business_day(value: dt.date) -> dt.date:
    return (pd.Timestamp(value) - pd.tseries.offsets.BDay(1)).date()


def _business_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    if start > end:
        return []
    return [timestamp.date() for timestamp in pd.bdate_range(start, end)]


def _build_trade_label(forward_label: str | None, tenor_label: str | None) -> str:
    forward = forward_label.upper() if forward_label else "--"
    tenor = tenor_label.upper() if tenor_label else "--"
    return f"{forward}x{tenor}"


def _normalize_package_type(package_type: Any) -> str:
    if package_type is None:
        return ""
    return str(package_type).strip().upper().replace("-", "_")


def _row_package_metrics(row: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = row.get("package_metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _row_legs(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    legs = row.get("legs_json")
    if not isinstance(legs, list):
        return []
    return [leg for leg in legs if isinstance(leg, Mapping)]


def _leg_metrics(leg: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = leg.get("leg_metrics")
    return metrics if isinstance(metrics, Mapping) else {}


def _resolve_platform_identifier(row: Mapping[str, Any]) -> str | None:
    platform_identifier = row.get("platform_identifier")
    if platform_identifier:
        return str(platform_identifier)

    for leg in _row_legs(row):
        metrics = _leg_metrics(leg)
        for key in ("platform_identifier", "platform", "mic"):
            value = metrics.get(key)
            if value:
                return str(value)
        for key in ("platform_identifier", "platform"):
            value = leg.get(key)
            if value:
                return str(value)

    metrics = _row_package_metrics(row)
    for key in ("platform_identifier", "platform", "mic"):
        value = metrics.get(key)
        if value:
            return str(value)
    return None


def _is_manual_package_row(row: Mapping[str, Any]) -> bool:
    if row.get("manual_link_id"):
        return True
    package_source = row.get("package_source")
    if package_source is None:
        return False
    return str(package_source).strip().upper() in {"MANUAL", "HYBRID"}


def _extract_leg_direction(leg: Mapping[str, Any]) -> str | None:
    raw = f"{leg.get('product_type') or ''} {leg.get('trade_label') or ''}".upper()
    if "PAYER" in raw:
        return "PAYER"
    if "RECEIVER" in raw:
        return "RECEIVER"
    return None


def _is_straddle_style_leg(leg: Mapping[str, Any]) -> bool:
    raw = f"{leg.get('trade_label') or ''} {leg.get('product_type') or ''}".upper()
    return STRADDLE_STYLE in raw


def _is_atm_outright_leg(leg: Mapping[str, Any]) -> bool:
    metrics = _leg_metrics(leg)
    moneyness = str(metrics.get("outright_moneyness") or "").strip().upper()
    if moneyness in {"ATM", "ATMF"}:
        return True
    rounded_offset = _extract_metric_number(metrics, "outright_strike_offset_rounded_bps")
    if rounded_offset is not None:
        return abs(rounded_offset) <= ASSUMED_STRADDLE_MAX_STRIKE_OFFSET_BPS
    raw_offset = _extract_metric_number(metrics, "outright_strike_offset_bps")
    if raw_offset is not None:
        return abs(raw_offset) <= ASSUMED_STRADDLE_MAX_STRIKE_OFFSET_BPS
    return False


def _date_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return None


def _resolve_row_forward_years(row: Mapping[str, Any]) -> float | None:
    forward_years = _parse_optional_float(row.get("forward_start_years"))
    if forward_years is not None:
        return forward_years
    forward_label = row.get("forward_label")
    if not forward_label:
        return None
    try:
        return _label_to_years(str(forward_label))
    except ValueError:
        return None


def _resolve_row_tenor_years(row: Mapping[str, Any]) -> float | None:
    tenor_years = _parse_optional_float(row.get("tenor_years"))
    if tenor_years is not None:
        return tenor_years
    tenor_label = row.get("tenor_label")
    if not tenor_label:
        return None
    try:
        return _label_to_years(str(tenor_label))
    except ValueError:
        return None


def _resolve_row_series_key(row: Mapping[str, Any]) -> str | None:
    forward_label = row.get("forward_label")
    tenor_label = row.get("tenor_label")
    if not forward_label or not tenor_label:
        return None
    return f"{str(forward_label).strip().lower()}x{str(tenor_label).strip().lower()}"


def _resolve_row_notional(
    row: Mapping[str, Any],
    *,
    treat_as_straddle: bool,
) -> float | None:
    legs = _row_legs(row)
    if treat_as_straddle and legs:
        leg_notional = _parse_optional_float(legs[0].get("notional"))
        if leg_notional is not None:
            return leg_notional
    total_notional = _parse_optional_float(row.get("total_notional"))
    if total_notional is not None:
        return total_notional
    if legs:
        return _parse_optional_float(legs[0].get("notional"))
    return None


def _resolve_display_notional(row: Mapping[str, Any]) -> float | None:
    return _resolve_row_notional(
        row,
        treat_as_straddle=_normalize_package_type(row.get("package_type")) == "STRADDLE",
    )


def _resolve_row_straddle_bpvol(
    row: Mapping[str, Any],
    *,
    assumed_incomplete: bool,
) -> float | None:
    metrics = _row_package_metrics(row)
    direct_value = _extract_metric_number(metrics, "straddle_bpvol_yr")
    if direct_value is not None:
        return direct_value

    legs = _row_legs(row)
    if legs:
        leg_value = _extract_metric_number(_leg_metrics(legs[0]), "straddle_bpvol_yr")
        if leg_value is not None:
            return leg_value

    if assumed_incomplete and legs:
        outright_bpvol = _extract_metric_number(_leg_metrics(legs[0]), "outright_bpvol_yr")
        if outright_bpvol is not None:
            return outright_bpvol * STRADDLE_SPLIT_FACTOR
    return None


def _resolve_row_straddle_premium(row: Mapping[str, Any]) -> float | None:
    total: float | None = None
    for leg in _row_legs(row):
        premium_value = _parse_optional_float(leg.get("premium"))
        if premium_value is None:
            continue
        premium_value *= STRADDLE_SPLIT_FACTOR
        total = premium_value if total is None else total + premium_value
    if total is not None:
        return total
    return _parse_optional_float(row.get("total_premium"))


def _build_incomplete_straddle_signature(row: Mapping[str, Any]) -> str | None:
    series_key = _resolve_row_series_key(row)
    if not series_key:
        return None
    notional = _resolve_display_notional(row)
    if notional is None or not math.isfinite(notional) or notional == 0:
        return None
    notional_bucket_mm = round(abs(notional) / 1_000_000.0)
    return "|".join(
        [
            _date_key(row.get("execution_start")) or _date_key(row.get("as_of_date")) or "",
            _date_key(row.get("expiration_date")) or "",
            _date_key(row.get("underlying_expiration_date")) or "",
            series_key,
            str(notional_bucket_mm),
        ]
    )


def _fallback_assumed_straddle_min_bpvol(forward_years: float | None) -> float:
    if forward_years is None:
        return 120.0
    if forward_years <= 0.5:
        return 130.0
    if forward_years <= 1.0:
        return 125.0
    if forward_years <= 2.0:
        return 120.0
    if forward_years <= 5.0:
        return 112.0
    if forward_years <= 10.0:
        return 100.0
    return 90.0


def _build_assumed_straddle_reason(
    row: Mapping[str, Any],
    *,
    recent_reference_bpvol: float | None,
    baseline_bpvol: float | None,
) -> str | None:
    if _normalize_package_type(row.get("package_type")) != "OUTRIGHT":
        return None
    if _is_manual_package_row(row):
        return None
    if _classify_platform(_resolve_platform_identifier(row)) != "idb":
        return None

    legs = _row_legs(row)
    if len(legs) != 1:
        return None
    leg = legs[0]
    if not _is_atm_outright_leg(leg) or not _is_straddle_style_leg(leg):
        return None
    if _extract_leg_direction(leg) is None:
        return None

    outright_bpvol = _extract_metric_number(_leg_metrics(leg), "outright_bpvol_yr")
    if outright_bpvol is None or not math.isfinite(outright_bpvol) or outright_bpvol <= 0:
        return None

    series_key = _resolve_row_series_key(row) or "--"
    if recent_reference_bpvol is not None and recent_reference_bpvol > 0:
        ratio = outright_bpvol / recent_reference_bpvol
        if ASSUMED_STRADDLE_MIN_RATIO_TO_REFERENCE <= ratio <= ASSUMED_STRADDLE_MAX_RATIO_TO_REFERENCE:
            return (
                f"IDB ATM outright bpvol ({outright_bpvol:.3f}) is {ratio:.2f}x the most recent "
                f"{series_key} straddle bpvol ({recent_reference_bpvol:.3f}); flagged as intraday "
                "incomplete straddle."
            )

    if baseline_bpvol is not None and baseline_bpvol > 0:
        ratio = outright_bpvol / baseline_bpvol
        if ASSUMED_STRADDLE_MIN_RATIO_TO_REFERENCE <= ratio <= ASSUMED_STRADDLE_MAX_RATIO_TO_REFERENCE:
            return (
                f"IDB ATM outright bpvol ({outright_bpvol:.3f}) is {ratio:.2f}x the "
                f"{series_key} straddle baseline ({baseline_bpvol:.3f}); flagged as intraday "
                "incomplete straddle."
            )

    fallback_threshold = _fallback_assumed_straddle_min_bpvol(_resolve_row_forward_years(row))
    if outright_bpvol >= fallback_threshold:
        return (
            f"IDB ATM outright bpvol ({outright_bpvol:.3f}) exceeds fallback threshold "
            f"({fallback_threshold:.3f}) with no reliable recent same-structure straddle "
            "reference; flagged as intraday incomplete straddle."
        )
    return None


def _build_straddle_observations_from_package_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    manual_straddle_ids: set[str] | None = None,
) -> list[StraddleObservation]:
    manual_ids = manual_straddle_ids or set()
    normalized_rows = [dict(row) for row in rows]

    complete_signatures: set[str] = set()
    signature_directions: dict[str, set[str]] = {}
    recent_straddle_by_series: dict[str, tuple[float, float]] = {}
    baseline_samples: dict[str, list[float]] = {}

    for row in normalized_rows:
        package_type = _normalize_package_type(row.get("package_type"))
        signature = _build_incomplete_straddle_signature(row)
        if package_type == "STRADDLE":
            if signature:
                complete_signatures.add(signature)
            series_key = _resolve_row_series_key(row)
            bpvol = _resolve_row_straddle_bpvol(row, assumed_incomplete=False)
            if series_key and bpvol is not None and math.isfinite(bpvol) and bpvol > 0:
                execution_timestamp = row.get("execution_start")
                if isinstance(execution_timestamp, pd.Timestamp):
                    execution_timestamp = execution_timestamp.to_pydatetime()
                timestamp_value = (
                    execution_timestamp.timestamp()
                    if isinstance(execution_timestamp, dt.datetime)
                    else 0.0
                )
                current = recent_straddle_by_series.get(series_key)
                if current is None or timestamp_value >= current[1]:
                    recent_straddle_by_series[series_key] = (bpvol, timestamp_value)
                baseline_samples.setdefault(series_key, []).append(bpvol)
            continue

        if package_type != "OUTRIGHT":
            continue
        if _is_manual_package_row(row):
            continue
        if _classify_platform(_resolve_platform_identifier(row)) != "idb":
            continue

        legs = _row_legs(row)
        if len(legs) != 1:
            continue
        leg = legs[0]
        if not _is_atm_outright_leg(leg) or not _is_straddle_style_leg(leg):
            continue
        if not signature:
            continue
        direction = _extract_leg_direction(leg)
        if direction is None:
            continue
        signature_directions.setdefault(signature, set()).add(direction)

    baseline_by_series = {
        series_key: float(np.median(samples))
        for series_key, samples in baseline_samples.items()
        if samples
    }

    observations: list[StraddleObservation] = []
    for row in normalized_rows:
        package_type = _normalize_package_type(row.get("package_type"))
        package_id = str(row.get("package_id") or "")
        is_manual_straddle = package_id in manual_ids
        assumed_incomplete = False
        inferred_reason: str | None = None

        if package_type != "STRADDLE":
            if is_manual_straddle:
                assumed_incomplete = True
                inferred_reason = (
                    "Manually marked as intraday incomplete straddle from the trade-selection toolbar."
                )
            else:
                signature = _build_incomplete_straddle_signature(row)
                directions = signature_directions.get(signature or "", set())
                if (
                    signature
                    and signature not in complete_signatures
                    and len(directions) <= 1
                ):
                    series_key = _resolve_row_series_key(row)
                    recent_reference = (
                        recent_straddle_by_series.get(series_key, (None, 0.0))[0]
                        if series_key
                        else None
                    )
                    baseline = baseline_by_series.get(series_key) if series_key else None
                    inferred_reason = _build_assumed_straddle_reason(
                        row,
                        recent_reference_bpvol=recent_reference,
                        baseline_bpvol=baseline,
                    )
                    assumed_incomplete = inferred_reason is not None

        if package_type != "STRADDLE" and not assumed_incomplete:
            continue

        observed_bpvol = _resolve_row_straddle_bpvol(
            row,
            assumed_incomplete=assumed_incomplete,
        )
        if observed_bpvol is None or not math.isfinite(observed_bpvol):
            continue

        execution_timestamp = row.get("execution_start")
        if isinstance(execution_timestamp, pd.Timestamp):
            execution_timestamp = execution_timestamp.to_pydatetime()
        if execution_timestamp is None:
            continue
        if not isinstance(execution_timestamp, dt.datetime):
            execution_timestamp = pd.Timestamp(execution_timestamp).to_pydatetime()
        if execution_timestamp.tzinfo is None:
            execution_timestamp = execution_timestamp.replace(tzinfo=dt.timezone.utc)

        forward_label = row.get("forward_label")
        tenor_label = row.get("tenor_label")
        observations.append(
            StraddleObservation(
                package_id=package_id,
                execution_timestamp=execution_timestamp,
                forward_label=str(forward_label).lower() if forward_label else None,
                tenor_label=str(tenor_label).lower() if tenor_label else None,
                forward_years=_resolve_row_forward_years(row),
                tenor_years=_resolve_row_tenor_years(row),
                observed_bpvol=float(observed_bpvol),
                premium=_resolve_row_straddle_premium(row),
                notional=_resolve_row_notional(row, treat_as_straddle=True),
                platform_identifier=_resolve_platform_identifier(row),
                platform_type=_classify_platform(_resolve_platform_identifier(row)),
                event_action=(str(row.get("event_action")) if row.get("event_action") else None),
                trade_label=_build_trade_label(
                    str(forward_label) if forward_label else None,
                    str(tenor_label) if tenor_label else None,
                ),
                is_inferred_incomplete=assumed_incomplete,
                inferred_reason=inferred_reason,
                source_package_type=package_type or None,
                is_manual_straddle=is_manual_straddle,
            )
        )

    return observations


def _grid_distance(
    forward_years: float,
    tenor_years: float,
    node: GridNode,
    tenor_weight: float,
) -> float:
    log_expiry = math.log(forward_years) - math.log(node.expiry_years)
    log_tenor = math.log(tenor_years) - math.log(node.tenor_years)
    return math.sqrt(log_expiry * log_expiry + (tenor_weight * log_tenor) ** 2)


def _nearest_node(
    forward_years: float,
    tenor_years: float,
    nodes: Iterable[GridNode],
    tenor_weight: float,
) -> tuple[GridNode, float]:
    best_node: GridNode | None = None
    best_distance: float | None = None
    for node in nodes:
        distance = _grid_distance(forward_years, tenor_years, node, tenor_weight)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_node = node
    if best_node is None or best_distance is None:
        raise ValueError("Unable to map observation to a grid node.")
    return best_node, best_distance


def _compute_bilinear_weights(
    forward_years: float,
    tenor_years: float,
    nodes: list[GridNode],
) -> dict[str, float]:
    """Compute bilinear interpolation weights in log-space for an off-grid observation.

    Returns a dict ``{node_key: weight}`` with 1-4 non-zero entries that sum to 1.
    When the observation falls exactly on a grid node the dict contains a single
    entry with weight 1.0 (reproducing nearest-node behaviour).
    """
    expiry_set = sorted({n.expiry_years for n in nodes})
    tenor_set = sorted({n.tenor_years for n in nodes})
    node_map: dict[tuple[float, float], GridNode] = {
        (n.expiry_years, n.tenor_years): n for n in nodes
    }

    # Bracket along the expiry axis
    e_idx = bisect.bisect_right(expiry_set, forward_years) - 1
    e_idx = max(0, min(e_idx, len(expiry_set) - 2))
    e_lo, e_hi = expiry_set[e_idx], expiry_set[e_idx + 1]

    # Bracket along the tenor axis
    t_idx = bisect.bisect_right(tenor_set, tenor_years) - 1
    t_idx = max(0, min(t_idx, len(tenor_set) - 2))
    t_lo, t_hi = tenor_set[t_idx], tenor_set[t_idx + 1]

    # Log-space interpolation fractions, clamped to [0, 1] for boundary safety
    log_e_span = math.log(e_hi) - math.log(e_lo)
    s = (math.log(forward_years) - math.log(e_lo)) / log_e_span if log_e_span > 0 else 0.0
    s = max(0.0, min(1.0, s))

    log_t_span = math.log(t_hi) - math.log(t_lo)
    r = (math.log(tenor_years) - math.log(t_lo)) / log_t_span if log_t_span > 0 else 0.0
    r = max(0.0, min(1.0, r))

    weights: dict[str, float] = {}
    for e_val, t_val, w in [
        (e_lo, t_lo, (1.0 - s) * (1.0 - r)),
        (e_lo, t_hi, (1.0 - s) * r),
        (e_hi, t_lo, s * (1.0 - r)),
        (e_hi, t_hi, s * r),
    ]:
        if w > 1e-10:
            node = node_map.get((e_val, t_val))
            if node is not None:
                weights[node.key] = w

    return weights


def get_db_connection_string() -> str:
    host = os.getenv("SWAPPULSE_DB_HOST", "aws-0-us-east-1.pooler.supabase.com")
    port = os.getenv("SWAPPULSE_DB_PORT", "6543")
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres")
    user = os.getenv("SWAPPULSE_DB_USER", "postgres.rdobtpugtnmefxplgwyp")
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "0rbZUh8y0Fsvdlry")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def create_db_engine() -> Engine:
    return create_engine(
        get_db_connection_string(),
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
    )


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        for statement in SCHEMA_PATCH_SQL:
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def _extract_grid_from_context(context: IRSwaptionMarketContext) -> dict[str, float]:
    as_of_date = context.as_of_date
    ql_eval = ql.Date(as_of_date.day, as_of_date.month, as_of_date.year)
    ql.Settings.instance().evaluationDate = ql_eval
    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out: dict[str, float] = {}

    for node in CORE_GRID_NODES:
        option_date = calendar.advance(
            ql_eval,
            _label_to_period(node.expiry_label.upper()),
            ql.ModifiedFollowing,
        )
        value = context.vol_handle.volatility(
            option_date,
            _label_to_period(node.tenor_label.upper()),
            0.0,
        )
        out[node.key] = float(value) * 10_000.0

    return out


def fetch_eod_grids(
    curve_name: str,
    dates: Iterable[dt.date],
    *,
    surface_type: str,
    force_refresh: bool = False,
) -> dict[dt.date, dict[str, float]]:
    date_list = sorted(set(dates))
    if not date_list:
        return {}

    _log_status(
        "Fetching EOD grids for "
        f"{curve_name}/{surface_type}: {_format_date_span(date_list)} "
        f"(force_refresh={force_refresh})"
    )

    mdp = IRSwaptionMDP(source="GSQUANT-QL", force_refresh=force_refresh)
    request = {
        "endpoint": "swaption_snapshot",
        "curve_name": curve_name,
        "timestamps": date_list,
        "surface_type": surface_type,
        "ignore_cache": force_refresh,
    }

    try:
        contexts = mdp.bulk_get_data(request)
        fetched = {date: _extract_grid_from_context(context) for date, context in contexts.items()}
        _log_status(
            f"Bulk EOD grid fetch succeeded: {len(fetched)}/{len(date_list)} dates returned"
        )
        return fetched
    except Exception as exc:
        _log_status(
            "Bulk GS grid fetch failed, falling back to single-date requests: "
            f"{exc}",
            level="WARN",
        )

    out: dict[dt.date, dict[str, float]] = {}
    failures: list[tuple[dt.date, str]] = []
    progress = tqdm(
        date_list,
        desc="Fetching GS EOD grids",
        unit="day",
        leave=True,
    )
    for date in progress:
        try:
            context = mdp.get_data(
                {
                    "endpoint": "swaption_snapshot",
                    "curve_name": curve_name,
                    "timestamp": date,
                    "surface_type": surface_type,
                    "ignore_cache": force_refresh,
                }
            )
        except Exception as exc:
            failures.append((date, str(exc)))
            progress.set_postfix_str(f"ok={len(out)}/{len(date_list)} fail={len(failures)}")
            continue
        out[date] = _extract_grid_from_context(context)
        progress.set_postfix_str(f"ok={len(out)}/{len(date_list)} fail={len(failures)}")

    if failures:
        sample = ", ".join(
            f"{date.isoformat()} ({reason})"
            for date, reason in failures[:3]
        )
        extra = "" if len(failures) <= 3 else f", +{len(failures) - 3} more"
        _log_status(
            "Single-date EOD fetch skipped "
            f"{len(failures)} date(s): {sample}{extra}",
            level="WARN",
        )
    _log_status(
        f"Single-date EOD fetch complete: fetched={len(out)} missing={len(failures)}"
    )
    return out


def upsert_eod_history(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    grid_rows: Mapping[dt.date, Mapping[str, float]],
) -> None:
    if not grid_rows:
        return

    payload = [
        {
            "as_of_date": as_of_date,
            "curve_name": curve_name,
            "surface_type": surface_type,
            "source": "GSQUANT",
            "grid_data": _to_json(grid_data),
        }
        for as_of_date, grid_data in sorted(grid_rows.items())
    ]

    sql = text(
        f"""
        INSERT INTO {EOD_HISTORY_TABLE} (
            as_of_date,
            curve_name,
            surface_type,
            source,
            grid_data
        ) VALUES (
            :as_of_date,
            :curve_name,
            :surface_type,
            :source,
            CAST(:grid_data AS JSONB)
        )
        ON CONFLICT (as_of_date, curve_name, surface_type)
        DO UPDATE SET
            source = EXCLUDED.source,
            grid_data = EXCLUDED.grid_data,
            updated_at = NOW()
        """
    )

    with engine.begin() as conn:
        conn.execute(sql, payload)


def load_eod_history_df(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> pd.DataFrame:
    conditions = ["curve_name = :curve_name", "surface_type = :surface_type"]
    params: dict[str, Any] = {"curve_name": curve_name, "surface_type": surface_type}

    if start_date is not None:
        conditions.append("as_of_date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        conditions.append("as_of_date <= :end_date")
        params["end_date"] = end_date

    result = pd.read_sql_query(
        text(
            f"""
            SELECT as_of_date, grid_data
            FROM {EOD_HISTORY_TABLE}
            WHERE {" AND ".join(conditions)}
            ORDER BY as_of_date ASC
            """
        ),
        engine,
        params=params,
    )
    if result.empty:
        return pd.DataFrame(columns=SURFACE_NODE_KEYS)

    rows: list[pd.Series] = []
    for _, row in result.iterrows():
        grid_data = _complete_surface_grid(row["grid_data"] or {})
        rows.append(pd.Series(grid_data, name=pd.Timestamp(row["as_of_date"])))

    df = pd.DataFrame(rows).reindex(columns=SURFACE_NODE_KEYS)
    df.index.name = "as_of_date"
    return df


def load_latest_eod_grid(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    *,
    on_or_before: dt.date,
) -> tuple[dt.date, dict[str, float]]:
    sql = text(
        f"""
        SELECT as_of_date, grid_data
        FROM {EOD_HISTORY_TABLE}
        WHERE curve_name = :curve_name
          AND surface_type = :surface_type
          AND as_of_date <= :on_or_before
        ORDER BY as_of_date DESC
        LIMIT 1
        """
    )
    with engine.begin() as conn:
        row = conn.execute(
            sql,
            {
                "curve_name": curve_name,
                "surface_type": surface_type,
                "on_or_before": on_or_before,
            },
        ).mappings().first()

    if row is None:
        raise RuntimeError(
            f"No EOD ATMF grid found for {curve_name} on or before {on_or_before.isoformat()}."
        )

    return row["as_of_date"], _complete_surface_grid(row["grid_data"] or {})


def load_exact_eod_grid(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    *,
    as_of_date: dt.date,
) -> dict[str, float] | None:
    sql = text(
        f"""
        SELECT grid_data
        FROM {EOD_HISTORY_TABLE}
        WHERE curve_name = :curve_name
          AND surface_type = :surface_type
          AND as_of_date = :as_of_date
        LIMIT 1
        """
    )
    with engine.begin() as conn:
        row = conn.execute(
            sql,
            {
                "curve_name": curve_name,
                "surface_type": surface_type,
                "as_of_date": as_of_date,
            },
        ).mappings().first()

    if row is None:
        return None
    return _complete_surface_grid(row["grid_data"] or {})


def snapshot_exists(
    engine: Engine,
    *,
    as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    calibration_preset: str,
    snapshot_kind: str,
) -> bool:
    sql = text(
        f"""
        SELECT 1
        FROM {SNAPSHOTS_TABLE}
        WHERE as_of_date = :as_of_date
          AND curve_name = :curve_name
          AND surface_type = :surface_type
          AND calibration_preset = :calibration_preset
          AND snapshot_kind = :snapshot_kind
        LIMIT 1
        """
    )
    with engine.begin() as conn:
        row = conn.execute(
            sql,
            {
                "as_of_date": as_of_date,
                "curve_name": curve_name,
                "surface_type": surface_type,
                "calibration_preset": calibration_preset,
                "snapshot_kind": snapshot_kind,
            },
        ).first()
    return row is not None


def store_pca_model(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    model: SurfacePCAModel,
) -> float:
    explained_ratio = 0.0
    total_variance = float(np.sum(model.total_variance))
    if total_variance > 0:
        explained_ratio = float(np.sum(model.eigenvalues) / total_variance)

    payload = {
        "curve_name": curve_name,
        "surface_type": surface_type,
        "explained_variance_ratio": explained_ratio,
        "model_data": _to_json(model.to_json()),
    }
    sql = text(
        f"""
        INSERT INTO {PCA_MODELS_TABLE} (
            curve_name,
            surface_type,
            explained_variance_ratio,
            model_data
        ) VALUES (
            :curve_name,
            :surface_type,
            :explained_variance_ratio,
            CAST(:model_data AS JSONB)
        )
        ON CONFLICT (curve_name, surface_type)
        DO UPDATE SET
            fitted_at = NOW(),
            explained_variance_ratio = EXCLUDED.explained_variance_ratio,
            model_data = EXCLUDED.model_data,
            updated_at = NOW()
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, payload)
    return explained_ratio


def load_pca_model(
    engine: Engine,
    curve_name: str,
    surface_type: str,
) -> SurfacePCAModel | None:
    sql = text(
        f"""
        SELECT model_data
        FROM {PCA_MODELS_TABLE}
        WHERE curve_name = :curve_name
          AND surface_type = :surface_type
        """
    )
    with engine.begin() as conn:
        row = conn.execute(
            sql,
            {"curve_name": curve_name, "surface_type": surface_type},
        ).mappings().first()
    if row is None:
        return None
    return SurfacePCAModel.from_json(row["model_data"])


def ensure_history_and_model(
    engine: Engine,
    curve_name: str,
    surface_type: str,
    *,
    anchor_eod_date: dt.date,
    lookback_business_days: int,
    n_components: int,
    force_refresh: bool,
) -> tuple[SurfacePCAModel, float]:
    start_date = (pd.Timestamp(anchor_eod_date) - pd.tseries.offsets.BDay(lookback_business_days)).date()
    required_dates = _business_dates(start_date, anchor_eod_date)
    _log_status(
        "Ensuring EOD history/PCA model for "
        f"{curve_name}/{surface_type}: anchor={anchor_eod_date.isoformat()} "
        f"window={start_date.isoformat()} -> {anchor_eod_date.isoformat()} "
        f"({len(required_dates)} business dates, force_refresh={force_refresh})"
    )

    existing_df = load_eod_history_df(
        engine,
        curve_name,
        surface_type,
        start_date=start_date,
        end_date=anchor_eod_date,
    )
    existing_dates = {timestamp.date() for timestamp in existing_df.index}
    missing_dates = [date for date in required_dates if date not in existing_dates]
    _log_status(
        f"History availability: existing={len(existing_df)} required={len(required_dates)} "
        f"missing={len(missing_dates)}"
    )

    dates_to_fetch = required_dates if force_refresh else missing_dates
    if dates_to_fetch:
        _log_status(
            "Requesting EOD grids for "
            f"{_format_date_span(dates_to_fetch)}"
        )
        fetched = fetch_eod_grids(
            curve_name,
            dates_to_fetch,
            surface_type=surface_type,
            force_refresh=force_refresh,
        )
        upsert_eod_history(engine, curve_name, surface_type, fetched)
        existing_df = load_eod_history_df(
            engine,
            curve_name,
            surface_type,
            start_date=start_date,
            end_date=anchor_eod_date,
        )
        _log_status(
            f"History refresh complete: fetched={len(fetched)} stored_rows={len(existing_df)}"
        )
    else:
        _log_status("History already complete for requested window")

    model = load_pca_model(engine, curve_name, surface_type)
    if model is not None and model.training_end >= anchor_eod_date and not force_refresh:
        total_variance = float(np.sum(model.total_variance))
        explained_ratio = (
            float(np.sum(model.eigenvalues) / total_variance) if total_variance > 0 else 0.0
        )
        _log_status(
            "Reusing PCA model: "
            f"training={model.training_start.isoformat()} -> {model.training_end.isoformat()} "
            f"components={model.n_components} explained={explained_ratio:.4f}"
        )
        return model, explained_ratio

    if len(existing_df) < max(3, n_components + 1):
        raise RuntimeError(
            f"Not enough EOD history to fit PCA model: {len(existing_df)} rows available."
        )

    _log_status(
        f"Fitting PCA model on {len(existing_df)} EOD grids with {n_components} component(s)"
    )
    model, _ = fit_surface_pca_from_eod_grids(existing_df, n_components=n_components)
    explained_ratio = store_pca_model(engine, curve_name, surface_type, model)
    _log_status(
        "Stored PCA model: "
        f"training={model.training_start.isoformat()} -> {model.training_end.isoformat()} "
        f"components={model.n_components} explained={explained_ratio:.4f}"
    )
    return model, explained_ratio


def _manual_straddles_table_exists(engine: Engine) -> bool:
    sql = text("SELECT to_regclass(:table_name) AS rel")
    with engine.begin() as conn:
        row = conn.execute(sql, {"table_name": MANUAL_STRADDLES_TABLE}).mappings().first()
    return bool(row and row.get("rel"))


def fetch_straddle_observations(
    engine: Engine,
    as_of_date: dt.date,
) -> list[StraddleObservation]:
    manual_table_exists = _manual_straddles_table_exists(engine)
    manual_join = (
        f"LEFT JOIN {MANUAL_STRADDLES_TABLE} ms ON ms.package_id = p.package_id"
        if manual_table_exists
        else ""
    )
    manual_select = (
        "CASE WHEN ms.package_id IS NOT NULL THEN TRUE ELSE FALSE END AS is_manual_straddle"
        if manual_table_exists
        else "FALSE AS is_manual_straddle"
    )

    sql = text(
        f"""
        WITH leg_rollup AS (
            SELECT
                l.package_id,
                mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier,
                mode() WITHIN GROUP (ORDER BY l.event_action) AS event_action
            FROM arbs_swaption_legs_v1 l
            GROUP BY l.package_id
        )
        SELECT
            p.package_id,
            p.package_type,
            p.package_source,
            p.manual_link_id,
            p.as_of_date,
            p.execution_start,
            p.expiration_date,
            p.underlying_expiration_date,
            p.forward_label,
            p.tenor_label,
            p.forward_start_years,
            p.tenor_years,
            p.total_notional,
            p.total_premium,
            p.package_metrics,
            lr.platform_identifier,
            lr.event_action,
            COALESCE(legs.legs_json, '[]'::jsonb) AS legs_json,
            {manual_select}
        FROM arbs_swaption_packages_v1 p
        LEFT JOIN leg_rollup lr
          ON lr.package_id = p.package_id
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'trade_id', l.trade_id,
                    'leg_order', l.leg_order,
                    'product_type', l.product_type,
                    'trade_label', l.trade_label,
                    'notional', l.notional,
                    'premium', l.premium,
                    'platform_identifier', l.platform_identifier,
                    'leg_metrics', l.leg_metrics
                ) ORDER BY l.leg_order
            ) AS legs_json
            FROM arbs_swaption_legs_v1 l
            WHERE l.package_id = p.package_id
        ) legs ON TRUE
        {manual_join}
        WHERE (p.execution_start AT TIME ZONE 'America/New_York')::date = :as_of_date
          AND upper(replace(coalesce(p.package_type, ''), '-', '_')) IN ('STRADDLE', 'OUTRIGHT')
        ORDER BY p.execution_start ASC
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(sql, {"as_of_date": as_of_date}).mappings().all()

    manual_straddle_ids = {
        str(row["package_id"])
        for row in rows
        if row.get("is_manual_straddle")
    }
    return _build_straddle_observations_from_package_rows(
        rows,
        manual_straddle_ids=manual_straddle_ids,
    )


def filter_observations_for_preset(
    observations: list[StraddleObservation],
    preset: str,
    *,
    max_staleness_minutes: float | None,
    as_of_ts: dt.datetime,
) -> tuple[list[StraddleObservation], int]:
    preset_config = CALIBRATION_PRESETS[preset]
    allowed_platforms = preset_config["platform_types"]
    selected: list[StraddleObservation] = []

    for observation in observations:
        if observation.platform_type not in allowed_platforms:
            continue
        if not _action_allowed(observation.event_action):
            continue
        if observation.forward_years is None or observation.tenor_years is None:
            continue
        if max_staleness_minutes is not None:
            age_minutes = max((as_of_ts - observation.execution_timestamp).total_seconds() / 60.0, 0.0)
            if age_minutes > max_staleness_minutes:
                continue
        selected.append(observation)

    filtered_out_count = max(len(observations) - len(selected), 0)
    return selected, filtered_out_count


def map_observations_to_grid(
    observations: list[StraddleObservation],
    *,
    tenor_weight: float,
    use_continuous_observations: bool = True,
) -> list[StraddleObservation]:
    mapped: list[StraddleObservation] = []
    for observation in observations:
        if observation.forward_years is None or observation.tenor_years is None:
            continue
        if observation.forward_years <= 0 or observation.tenor_years <= 0:
            continue

        # Display grid mapping always uses nearest-node.
        display_node, display_distance = _nearest_node(
            observation.forward_years,
            observation.tenor_years,
            DISPLAY_GRID_NODES,
            tenor_weight,
        )

        if use_continuous_observations:
            # Bilinear interpolation weights across core grid.
            weights = _compute_bilinear_weights(
                observation.forward_years,
                observation.tenor_years,
                CORE_GRID_NODES,
            )
            # Primary node = highest weight (backward-compat with core_node_key).
            primary_key = max(weights, key=weights.get) if weights else None
            primary_node, primary_distance = _nearest_node(
                observation.forward_years,
                observation.tenor_years,
                CORE_GRID_NODES,
                tenor_weight,
            )
            mapped.append(
                StraddleObservation(
                    **{
                        **observation.__dict__,
                        "core_node_key": primary_node.key,
                        "display_node_key": display_node.key,
                        "mapping_distance": primary_distance,
                        "display_mapping_distance": display_distance,
                        "grid_weights": weights,
                    }
                )
            )
        else:
            # Legacy nearest-node path.
            core_node, core_distance = _nearest_node(
                observation.forward_years,
                observation.tenor_years,
                CORE_GRID_NODES,
                tenor_weight,
            )
            mapped.append(
                StraddleObservation(
                    **{
                        **observation.__dict__,
                        "core_node_key": core_node.key,
                        "display_node_key": display_node.key,
                        "mapping_distance": core_distance,
                        "display_mapping_distance": display_distance,
                    }
                )
            )
    return mapped


def compute_staleness_weights(
    observations: list[StraddleObservation],
    *,
    as_of_ts: dt.datetime,
    half_life_minutes: float,
) -> list[StraddleObservation]:
    updated: list[StraddleObservation] = []
    half_life = max(float(half_life_minutes), 1.0)

    for observation in observations:
        age_minutes = max((as_of_ts - observation.execution_timestamp).total_seconds() / 60.0, 0.0)
        decay = math.exp(-math.log(2.0) * age_minutes / half_life)
        staleness_weight = 1.0 / max(decay, 1e-6)
        updated.append(
            StraddleObservation(
                **{
                    **observation.__dict__,
                    "age_minutes": age_minutes,
                    "staleness_weight": staleness_weight,
                }
            )
        )

    return updated


def aggregate_observations_by_node(
    observations: list[StraddleObservation],
    *,
    base_noise_bpvol: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, list[StraddleObservation]]]:
    node_to_observations: dict[str, list[StraddleObservation]] = {}
    for observation in observations:
        if not observation.core_node_key:
            continue
        node_to_observations.setdefault(observation.core_node_key, []).append(observation)

    aggregated_values: dict[str, float] = {}
    effective_noise_weights: dict[str, float] = {}

    for node_key, node_observations in node_to_observations.items():
        noises = np.asarray(
            [base_noise_bpvol * max(obs.staleness_weight, 1e-6) for obs in node_observations],
            dtype=float,
        )
        precisions = 1.0 / np.clip(noises, a_min=1e-8, a_max=None)
        observed = np.asarray([obs.observed_bpvol for obs in node_observations], dtype=float)
        total_precision = float(np.sum(precisions))
        aggregated_values[node_key] = float(np.dot(precisions, observed) / total_precision)
        effective_noise = 1.0 / total_precision
        effective_noise_weights[node_key] = float(effective_noise / max(base_noise_bpvol, 1e-8))

    return aggregated_values, effective_noise_weights, node_to_observations


def build_observation_operator(
    observations: list[StraddleObservation],
    model_columns: list[str],
    *,
    base_noise_bpvol: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], dict[str, list[StraddleObservation]]]:
    """Build the observation operator matrix H for continuous-coordinate observations.

    Returns
    -------
    observed_values : ndarray, shape (n_obs,)
        The bpvol values of each observation.
    noise_weights : ndarray, shape (n_obs,)
        Per-observation staleness weights (fed to ``conditional_mvn_update``
        as ``staleness_weights``).
    H : ndarray, shape (n_obs, n_grid)
        Observation operator matrix -- each row maps one trade to its weighted
        combination of core grid nodes via bilinear interpolation.
    observation_labels : list[str]
        Human-readable label for each observation row.
    node_to_observations : dict[str, list[StraddleObservation]]
        Mapping from each influenced node key to the list of observations
        contributing to it (for metadata/audit).
    """
    column_index = {col: idx for idx, col in enumerate(model_columns)}
    n_grid = len(model_columns)

    valid_obs: list[StraddleObservation] = []
    for obs in observations:
        if obs.grid_weights:
            valid_obs.append(obs)

    n_obs = len(valid_obs)
    if n_obs == 0:
        return (
            np.empty(0, dtype=float),
            np.empty(0, dtype=float),
            np.empty((0, n_grid), dtype=float),
            [],
            {},
        )

    H = np.zeros((n_obs, n_grid), dtype=float)
    observed_values = np.empty(n_obs, dtype=float)
    noise_weights = np.empty(n_obs, dtype=float)
    labels: list[str] = []
    node_to_observations: dict[str, list[StraddleObservation]] = {}

    for i, obs in enumerate(valid_obs):
        observed_values[i] = obs.observed_bpvol
        noise_weights[i] = max(obs.staleness_weight, 1e-6)
        labels.append(obs.trade_label or obs.package_id)

        for node_key, weight in obs.grid_weights.items():
            col_idx = column_index.get(node_key)
            if col_idx is not None:
                H[i, col_idx] = weight
            node_to_observations.setdefault(node_key, []).append(obs)

    return observed_values, noise_weights, H, labels, node_to_observations


def _build_vol_handle_from_grid(
    grid_data: Mapping[str, float],
    *,
    as_of_date: dt.date,
    fallback_grid: Mapping[str, float] | None = None,
) -> ql.SwaptionVolatilityStructureHandle:
    ql_eval = ql.Date(as_of_date.day, as_of_date.month, as_of_date.year)
    ql.Settings.instance().evaluationDate = ql_eval

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    bdc = ql.ModifiedFollowing
    day_count = ql.Actual365Fixed()

    ql_expiries = ql.PeriodVector()
    for label in EXPIRY_LABELS:
        ql_expiries.append(_label_to_period(label.upper()))
    ql_tails = ql.PeriodVector()
    for label in TAIL_LABELS:
        ql_tails.append(_label_to_period(label.upper()))

    ql_vols = ql.Matrix(len(EXPIRY_LABELS), len(TAIL_LABELS))
    for expiry_index, expiry_label in enumerate(EXPIRY_LABELS):
        for tail_index, tail_label in enumerate(TAIL_LABELS):
            node_key = f"{expiry_label}_{tail_label}"
            bpvol = _parse_optional_float(grid_data.get(node_key))
            if bpvol is None and fallback_grid is not None:
                bpvol = _parse_optional_float(fallback_grid.get(node_key))
            if bpvol is None:
                raise ValueError(f"Missing bpvol for swaption node {node_key}")
            ql_vols[expiry_index][tail_index] = float(bpvol) / 10_000.0

    surface = ql.SwaptionVolatilityMatrix(
        calendar,
        bdc,
        ql_expiries,
        ql_tails,
        ql_vols,
        day_count,
        False,
        ql.Normal,
    )
    handle = ql.SwaptionVolatilityStructureHandle(surface)
    handle.enableExtrapolation()
    return handle


def _build_pricing_context_for_grid(
    base_context: IRSwaptionMarketContext,
    grid_data: Mapping[str, float],
) -> IRSwaptionMarketContext:
    fallback_grid = _extract_grid_from_context(base_context)
    vol_handle = _build_vol_handle_from_grid(
        grid_data,
        as_of_date=base_context.as_of_date,
        fallback_grid=fallback_grid,
    )
    day_counter = (
        base_context.curve.daycounter()
        if hasattr(base_context.curve, "daycounter")
        else ql.Actual365Fixed()
    )
    try:
        pricing_engine = ql.BachelierSwaptionEngine(base_context.curve_handle, vol_handle)
    except TypeError:
        pricing_engine = ql.BachelierSwaptionEngine(
            base_context.curve_handle,
            vol_handle,
            day_counter,
        )
    return replace(
        base_context,
        vol_handle=vol_handle,
        pricing_engine=pricing_engine,
        metadata={
            **dict(base_context.metadata or {}),
            "premium_grid_source": "live_atmf_grid",
        },
    )


def compute_straddle_premiums(
    grid_data: Mapping[str, float],
    *,
    curve_name: str,
    pricing_date: dt.date,
    surface_type: str,
    notional: float = DEFAULT_PREMIUM_NOTIONAL,
) -> dict[str, PremiumQuote]:
    mdp = IRSwaptionMDP(
        source="GSQUANT-QL",
        curve_source="ERIS_EOD_LIVE-QL_BASIC",
    )
    base_context = mdp.get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": curve_name,
            "timestamp": pricing_date,
            "surface_type": surface_type,
        }
    )
    context = _build_pricing_context_for_grid(base_context, grid_data)

    out: dict[str, PremiumQuote] = {}
    for node in CORE_GRID_NODES:
        vol = _parse_optional_float(grid_data.get(node.key))
        if vol is None or vol <= 0:
            out[node.key] = PremiumQuote(premium=0.0, premium_bps=0.0)
            continue
        try:
            query = IRSwaptionQuery(
                curve=curve_name,
                shorthand=f"{node.expiry_label}{node.tenor_label}",
                structure=IRSwaptionStructure.STRADDLE,
                strike="ATMF",
                structure_kwargs={"notional": notional},
            )
            resolved_query = resolve_query(
                query,
                timestamp=pricing_date,
                pricer_or_curve=context,
            )
            package, weights = resolved_query.resolve_package(pricer_or_curve=context)
            value_map = resolved_query.build_value_map(
                pricer_or_curve=context,
                package=package,
                risk_weights=weights,
            )
            # IRSwaptionValue.FWD_PREM is the canonical forward premium measure in bps.
            premium_bps = float(value_map.apply(IRSwaptionValue.FWD_PREM))
            out[node.key] = PremiumQuote(
                premium=float(premium_bps / 10_000.0 * notional),
                premium_bps=premium_bps,
            )
        except Exception as exc:
            print(
                f"Premium calc failed for {pricing_date.isoformat()} {node.key}: {exc}"
            )
            out[node.key] = PremiumQuote(premium=0.0, premium_bps=0.0)

    return out


def _extract_last_observation(
    node_observations: list[StraddleObservation],
) -> StraddleObservation | None:
    if not node_observations:
        return None
    return max(node_observations, key=lambda obs: obs.execution_timestamp)


def _observation_weight_on_node(
    observation: StraddleObservation,
    *,
    node_key: str | None = None,
) -> float:
    target_node = node_key or observation.core_node_key
    if not target_node:
        return 0.0
    if observation.grid_weights is None:
        return 1.0
    return float(observation.grid_weights.get(target_node, 0.0))


def _build_direct_node_anchors(
    observations: list[StraddleObservation],
    *,
    base_noise_bpvol: float,
    min_weight: float = DIRECT_OBSERVATION_ANCHOR_MIN_WEIGHT,
) -> tuple[dict[str, float], dict[str, float], dict[str, list[StraddleObservation]]]:
    direct_observations = [
        observation
        for observation in observations
        if observation.core_node_key
        and _observation_weight_on_node(observation) >= float(min_weight)
    ]
    if not direct_observations:
        return {}, {}, {}
    return aggregate_observations_by_node(
        direct_observations,
        base_noise_bpvol=base_noise_bpvol,
    )


def _apply_direct_node_anchors(
    update: ConditionalMVNUpdateResult,
    *,
    eod_grid: Mapping[str, float],
    anchored_values: Mapping[str, float],
) -> ConditionalMVNUpdateResult:
    if not anchored_values:
        return update

    anchored_live_grid = update.live_grid.copy()
    anchored_delta_grid = update.delta_grid.copy()
    for node_key, anchored_value in anchored_values.items():
        if node_key not in anchored_live_grid.index or node_key not in eod_grid:
            continue
        anchored_live_grid[node_key] = float(anchored_value)
        anchored_delta_grid[node_key] = float(anchored_value) - float(eod_grid[node_key])

    return replace(
        update,
        live_grid=anchored_live_grid,
        delta_grid=anchored_delta_grid,
    )


def _propagate_direct_node_anchor_residuals(
    base_live_grid: Mapping[str, float],
    anchored_values: Mapping[str, float],
    *,
    tenor_weight: float,
    length_scale: float = DIRECT_ANCHOR_PROPAGATION_LENGTH_SCALE,
    prior_weight: float = DIRECT_ANCHOR_PROPAGATION_PRIOR_WEIGHT,
) -> tuple[dict[str, float], dict[str, str | None], dict[str, float]]:
    if not anchored_values:
        return {}, {}, {}

    node_map = {node.key: node for node in CORE_GRID_NODES if node.key in base_live_grid}
    anchor_nodes: list[tuple[str, GridNode, float]] = []
    for node_key, anchored_value in anchored_values.items():
        node = node_map.get(node_key)
        base_value = _parse_optional_float(base_live_grid.get(node_key))
        if node is None or base_value is None:
            continue
        anchor_nodes.append((node_key, node, float(anchored_value) - float(base_value)))

    if not anchor_nodes:
        return {}, {}, {}

    scale = max(float(length_scale), 1e-6)
    baseline = max(float(prior_weight), 0.0)
    residuals: dict[str, float] = {}
    last_propagated_from: dict[str, str | None] = {}
    propagation_factor: dict[str, float] = {}

    for node_key, target_node in node_map.items():
        weighted_sum = 0.0
        total_weight = 0.0
        best_anchor_key: str | None = None
        best_anchor_weight = 0.0

        for anchor_key, anchor_node, anchor_residual in anchor_nodes:
            distance = _grid_distance(
                anchor_node.expiry_years,
                anchor_node.tenor_years,
                target_node,
                tenor_weight,
            )
            weight = math.exp(-distance / scale)
            weighted_sum += weight * anchor_residual
            total_weight += weight
            if weight > best_anchor_weight:
                best_anchor_weight = weight
                best_anchor_key = anchor_key

        denominator = baseline + total_weight
        residuals[node_key] = weighted_sum / denominator if denominator > 0 else 0.0
        last_propagated_from[node_key] = best_anchor_key
        propagation_factor[node_key] = total_weight / denominator if denominator > 0 else 0.0

    return residuals, last_propagated_from, propagation_factor


def _apply_residual_adjustments(
    update: ConditionalMVNUpdateResult,
    *,
    eod_grid: Mapping[str, float],
    residual_adjustments: Mapping[str, float],
) -> ConditionalMVNUpdateResult:
    if not residual_adjustments:
        return update

    adjusted_live_grid = update.live_grid.copy()
    adjusted_delta_grid = update.delta_grid.copy()
    for node_key, residual in residual_adjustments.items():
        if node_key not in adjusted_live_grid.index or node_key not in eod_grid:
            continue
        adjusted_live_grid[node_key] = float(adjusted_live_grid[node_key]) + float(residual)
        adjusted_delta_grid[node_key] = float(adjusted_live_grid[node_key]) - float(eod_grid[node_key])

    return replace(
        update,
        live_grid=adjusted_live_grid,
        delta_grid=adjusted_delta_grid,
    )


def build_live_grid(
    model: SurfacePCAModel,
    eod_grid: Mapping[str, float],
    observations: list[StraddleObservation],
    *,
    base_noise_bpvol: float,
    curve_name: str,
    surface_type: str,
    pricing_date: dt.date,
    tenor_weight: float = DEFAULT_TENOR_WEIGHT,
    use_continuous_observations: bool = True,
) -> tuple[ConditionalMVNUpdateResult, dict[str, Any], dict[str, PremiumQuote], dt.datetime | None]:
    # Determine whether any observation carries grid_weights.
    has_grid_weights = any(obs.grid_weights for obs in observations)

    if use_continuous_observations and has_grid_weights:
        # --- Continuous observation operator path ---
        obs_values, obs_noise, H, obs_labels, node_groups = build_observation_operator(
            observations,
            model.columns,
            base_noise_bpvol=base_noise_bpvol,
        )
        update = conditional_mvn_update(
            model,
            eod_grid,
            obs_values,
            obs_noise,
            base_noise=base_noise_bpvol,
            observation_operator=H,
            observation_labels=obs_labels,
        )
    else:
        # --- Legacy nearest-node path ---
        observed_values, staleness_weights, node_groups = aggregate_observations_by_node(
            observations,
            base_noise_bpvol=base_noise_bpvol,
        )
        update = conditional_mvn_update(
            model,
            eod_grid,
            observed_values,
            staleness_weights,
            base_noise=base_noise_bpvol,
        )

    direct_anchor_values, _, direct_node_groups = _build_direct_node_anchors(
        observations,
        base_noise_bpvol=base_noise_bpvol,
    )
    propagated_anchor_residuals, propagated_anchor_sources, propagated_anchor_factors = (
        _propagate_direct_node_anchor_residuals(
            update.live_grid,
            direct_anchor_values,
            tenor_weight=tenor_weight,
        )
    )
    update = _apply_residual_adjustments(
        update,
        eod_grid=eod_grid,
        residual_adjustments=propagated_anchor_residuals,
    )
    update = _apply_direct_node_anchors(
        update,
        eod_grid=eod_grid,
        anchored_values=direct_anchor_values,
    )

    live_grid = {key: float(value) for key, value in update.live_grid.items()}
    premiums = compute_straddle_premiums(
        live_grid,
        curve_name=curve_name,
        pricing_date=pricing_date,
        surface_type=surface_type,
    )
    eod_premiums = compute_straddle_premiums(
        eod_grid,
        curve_name=curve_name,
        pricing_date=pricing_date,
        surface_type=surface_type,
    )
    global_last_observation = (
        max((obs.execution_timestamp for obs in observations), default=None)
        if observations
        else None
    )
    global_age_minutes = (
        min((obs.age_minutes for obs in observations), default=None)
        if observations
        else None
    )

    node_metadata: dict[str, Any] = {}
    for node_key in model.columns:
        contributing = node_groups.get(node_key, [])
        direct_observations = direct_node_groups.get(node_key, [])
        propagated_from_node = propagated_anchor_sources.get(node_key)
        propagated_observations = (
            direct_node_groups.get(propagated_from_node, [])
            if propagated_from_node is not None
            else []
        )
        last_observation = _extract_last_observation(direct_observations) or _extract_last_observation(
            contributing
        ) or _extract_last_observation(
            propagated_observations
        )
        premium_quote = premiums.get(node_key)
        eod_premium_quote = eod_premiums.get(node_key)

        # Compute weighted observation count (sum of weights from all trades).
        weighted_count = 0.0
        contributing_trades: list[dict[str, Any]] = []
        for obs in contributing:
            w = (obs.grid_weights or {}).get(node_key, 1.0)
            weighted_count += w
            contributing_trades.append({
                "package_id": obs.package_id,
                "weight": w,
                "trade_label": obs.trade_label,
            })

        source = "prior"
        if direct_observations:
            source = "direct_observation"
        elif observations:
            source = "propagated"

        node_metadata[node_key] = {
            "source": source,
            "confidence": float(update.confidence[node_key]),
            "change_bpvol": float(update.delta_grid[node_key]),
            "staleness_minutes": (
                min(obs.age_minutes for obs in contributing)
                if contributing
                else (
                    min(obs.age_minutes for obs in propagated_observations)
                    if propagated_observations
                    else global_age_minutes
                )
            ),
            "premium": premium_quote.premium if premium_quote is not None else None,
            "premium_bps": premium_quote.premium_bps if premium_quote is not None else None,
            "eod_premium": (
                eod_premium_quote.premium if eod_premium_quote is not None else None
            ),
            "eod_premium_bps": (
                eod_premium_quote.premium_bps if eod_premium_quote is not None else None
            ),
            "change_premium_bps": (
                float(premium_quote.premium_bps - eod_premium_quote.premium_bps)
                if premium_quote is not None and eod_premium_quote is not None
                else None
            ),
            "observation_count": len(contributing),
            "direct_observation_count": len(direct_observations),
            "weighted_observation_count": weighted_count,
            "last_propagated_from": (
                propagated_from_node
                if source == "propagated" and propagated_from_node is not None
                else None
            ),
            "propagation_factor": float(propagated_anchor_factors.get(node_key, 0.0)),
            "contributing_trades": contributing_trades,
            "eod_bpvol": float(eod_grid[node_key]),
            "last_observation_time": (
                last_observation.execution_timestamp.isoformat()
                if last_observation is not None
                else (global_last_observation.isoformat() if global_last_observation else None)
            ),
            "last_observation": (
                last_observation.to_calibration_observation()
                if last_observation is not None
                else None
            ),
        }

    return update, node_metadata, premiums, global_last_observation


def build_close_mdp_metadata(
    mdp_grid: Mapping[str, float],
    *,
    eod_grid: Mapping[str, float],
    curve_name: str,
    pricing_date: dt.date,
    surface_type: str,
) -> tuple[dict[str, Any], dict[str, PremiumQuote]]:
    premiums = compute_straddle_premiums(
        mdp_grid,
        curve_name=curve_name,
        pricing_date=pricing_date,
        surface_type=surface_type,
    )
    eod_premiums = compute_straddle_premiums(
        eod_grid,
        curve_name=curve_name,
        pricing_date=pricing_date,
        surface_type=surface_type,
    )
    node_metadata: dict[str, Any] = {}
    for node in CORE_GRID_NODES:
        mdp_value = _parse_optional_float(mdp_grid.get(node.key))
        eod_value = _parse_optional_float(eod_grid.get(node.key))
        premium_quote = premiums.get(node.key)
        eod_premium_quote = eod_premiums.get(node.key)
        node_metadata[node.key] = {
            "source": "mdp_close",
            "confidence": 1.0,
            "change_bpvol": (
                float(mdp_value - eod_value)
                if mdp_value is not None and eod_value is not None
                else None
            ),
            "staleness_minutes": 0.0,
            "premium": premium_quote.premium if premium_quote is not None else None,
            "premium_bps": premium_quote.premium_bps if premium_quote is not None else None,
            "eod_premium": (
                eod_premium_quote.premium if eod_premium_quote is not None else None
            ),
            "eod_premium_bps": (
                eod_premium_quote.premium_bps if eod_premium_quote is not None else None
            ),
            "change_premium_bps": (
                float(premium_quote.premium_bps - eod_premium_quote.premium_bps)
                if premium_quote is not None and eod_premium_quote is not None
                else None
            ),
            "observation_count": 0,
            "eod_bpvol": float(eod_grid[node.key]),
            "last_observation_time": None,
            "last_observation": None,
            "last_propagated_from": None,
            "snapshot_kind": SNAPSHOT_KIND_CLOSE_MDP,
        }
    return node_metadata, premiums


def replace_observations(
    engine: Engine,
    *,
    as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    calibration_preset: str,
    observations: list[StraddleObservation],
    eod_grid: Mapping[str, float],
) -> None:
    delete_sql = text(
        f"""
        DELETE FROM {OBSERVATIONS_TABLE}
        WHERE as_of_date = :as_of_date
          AND curve_name = :curve_name
          AND surface_type = :surface_type
          AND calibration_preset = :calibration_preset
        """
    )
    insert_sql = text(
        f"""
        INSERT INTO {OBSERVATIONS_TABLE} (
            as_of_date,
            curve_name,
            surface_type,
            calibration_preset,
            package_id,
            execution_timestamp,
            grid_node_key,
            display_node_key,
            expiry_label,
            tenor_label,
            display_expiry_label,
            display_tenor_label,
            observed_bpvol,
            delta_bpvol,
            premium,
            notional,
            platform_type,
            platform_identifier,
            event_action,
            mapping_distance,
            staleness_weight,
            age_minutes,
            trade_label,
            trade_metadata
        ) VALUES (
            :as_of_date,
            :curve_name,
            :surface_type,
            :calibration_preset,
            :package_id,
            :execution_timestamp,
            :grid_node_key,
            :display_node_key,
            :expiry_label,
            :tenor_label,
            :display_expiry_label,
            :display_tenor_label,
            :observed_bpvol,
            :delta_bpvol,
            :premium,
            :notional,
            :platform_type,
            :platform_identifier,
            :event_action,
            :mapping_distance,
            :staleness_weight,
            :age_minutes,
            :trade_label,
            CAST(:trade_metadata AS JSONB)
        )
        """
    )

    payload = []
    for observation in observations:
        delta_bpvol = None
        if observation.core_node_key and observation.core_node_key in eod_grid:
            delta_bpvol = observation.observed_bpvol - float(eod_grid[observation.core_node_key])
        payload.append(
            {
                "as_of_date": as_of_date,
                "curve_name": curve_name,
                "surface_type": surface_type,
                "calibration_preset": calibration_preset,
                "package_id": observation.package_id,
                "execution_timestamp": observation.execution_timestamp,
                "grid_node_key": observation.core_node_key,
                "display_node_key": observation.display_node_key,
                "expiry_label": observation.forward_label.upper() if observation.forward_label else "--",
                "tenor_label": observation.tenor_label.upper() if observation.tenor_label else "--",
                "display_expiry_label": (
                    observation.display_node_key.split("_")[0].upper()
                    if observation.display_node_key
                    else "--"
                ),
                "display_tenor_label": (
                    observation.display_node_key.split("_")[1].upper()
                    if observation.display_node_key
                    else "--"
                ),
                "observed_bpvol": observation.observed_bpvol,
                "delta_bpvol": delta_bpvol,
                "premium": observation.premium,
                "notional": observation.notional,
                "platform_type": observation.platform_type,
                "platform_identifier": observation.platform_identifier,
                "event_action": observation.event_action,
                "mapping_distance": observation.mapping_distance,
                "staleness_weight": observation.staleness_weight,
                "age_minutes": observation.age_minutes,
                "trade_label": observation.trade_label,
                "trade_metadata": _to_json(observation.to_trade_metadata()),
            }
        )

    with engine.begin() as conn:
        conn.execute(
            delete_sql,
            {
                "as_of_date": as_of_date,
                "curve_name": curve_name,
                "surface_type": surface_type,
                "calibration_preset": calibration_preset,
            },
        )
        if payload:
            conn.execute(insert_sql, payload)


def _build_pca_factors_payload(
    update: ConditionalMVNUpdateResult | None,
) -> dict[str, Any]:
    if update is None:
        return {}
    return {
        "posteriorFactors": update.posterior_factors.to_dict(),
        "posteriorFactorCov": update.posterior_factor_cov.to_dict(),
        "observedNodes": update.observed_nodes,
        "observationNoise": update.observation_noise.to_dict(),
    }


def write_snapshot(
    engine: Engine,
    *,
    as_of_date: dt.date,
    eod_as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    calibration_preset: str,
    snapshot_kind: str,
    snapshot_ts: dt.datetime,
    grid_data: Mapping[str, float],
    node_metadata: Mapping[str, Any],
    eod_grid: Mapping[str, float],
    observation_count: int,
    filtered_out_count: int,
    last_observation_ts: dt.datetime | None,
    calibration_config: Mapping[str, Any],
    source: str,
    pca_factors: Mapping[str, Any] | None = None,
) -> None:
    delete_sql = text(
        f"""
        DELETE FROM {SNAPSHOTS_TABLE}
        WHERE as_of_date = :as_of_date
          AND curve_name = :curve_name
          AND surface_type = :surface_type
          AND calibration_preset = :calibration_preset
          AND snapshot_kind = :snapshot_kind
        """
    )
    sql = text(
        f"""
        INSERT INTO {SNAPSHOTS_TABLE} (
            as_of_date,
            eod_as_of_date,
            curve_name,
            surface_type,
            calibration_preset,
            snapshot_kind,
            snapshot_ts,
            grid_data,
            eod_grid_data,
            node_metadata,
            pca_factors,
            calibration_config,
            observation_count,
            filtered_out_count,
            last_observation_ts,
            source
        ) VALUES (
            :as_of_date,
            :eod_as_of_date,
            :curve_name,
            :surface_type,
            :calibration_preset,
            :snapshot_kind,
            :snapshot_ts,
            CAST(:grid_data AS JSONB),
            CAST(:eod_grid_data AS JSONB),
            CAST(:node_metadata AS JSONB),
            CAST(:pca_factors AS JSONB),
            CAST(:calibration_config AS JSONB),
            :observation_count,
            :filtered_out_count,
            :last_observation_ts,
            :source
        )
        """
    )
    payload = {
        "as_of_date": as_of_date,
        "eod_as_of_date": eod_as_of_date,
        "curve_name": curve_name,
        "surface_type": surface_type,
        "calibration_preset": calibration_preset,
        "snapshot_kind": snapshot_kind,
        "snapshot_ts": snapshot_ts,
        "grid_data": _to_json(dict(grid_data)),
        "eod_grid_data": _to_json(dict(eod_grid)),
        "node_metadata": _to_json(node_metadata),
        "pca_factors": _to_json(dict(pca_factors or {})),
        "calibration_config": _to_json(calibration_config),
        "observation_count": observation_count,
        "filtered_out_count": filtered_out_count,
        "last_observation_ts": last_observation_ts,
        "source": source,
    }
    with engine.begin() as conn:
        if snapshot_kind != SNAPSHOT_KIND_INTRADAY:
            conn.execute(
                delete_sql,
                {
                    "as_of_date": as_of_date,
                    "curve_name": curve_name,
                    "surface_type": surface_type,
                    "calibration_preset": calibration_preset,
                    "snapshot_kind": snapshot_kind,
                },
            )
        conn.execute(sql, payload)


def build_snapshot_for_preset(
    engine: Engine,
    *,
    as_of_date: dt.date,
    eod_as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    model: SurfacePCAModel,
    raw_observations: list[StraddleObservation],
    preset: str,
    half_life_minutes: float,
    max_staleness_minutes: float,
    base_noise_bpvol: float,
    tenor_weight: float,
    snapshot_kind: str = SNAPSHOT_KIND_INTRADAY,
    write_observations: bool = True,
    snapshot_ts: dt.datetime | None = None,
    use_continuous_observations: bool = True,
) -> dict[str, Any]:
    if snapshot_ts is None:
        snapshot_ts = _now_et()
    elif snapshot_ts.tzinfo is None:
        snapshot_ts = snapshot_ts.replace(tzinfo=ET_ZONE)
    else:
        snapshot_ts = snapshot_ts.astimezone(ET_ZONE)
    selected, filtered_out_count = filter_observations_for_preset(
        raw_observations,
        preset,
        max_staleness_minutes=(
            max_staleness_minutes
            if snapshot_kind == SNAPSHOT_KIND_INTRADAY
            else None
        ),
        as_of_ts=snapshot_ts,
    )
    mapped = map_observations_to_grid(
        selected,
        tenor_weight=tenor_weight,
        use_continuous_observations=use_continuous_observations,
    )
    inferred_count = sum(1 for observation in selected if observation.is_inferred_incomplete)
    manual_count = sum(1 for observation in selected if observation.is_manual_straddle)
    _log_status(
        f"Building {preset}[{snapshot_kind}] snapshot: raw={len(raw_observations)} "
        f"selected={len(selected)} mapped={len(mapped)} filtered_out={filtered_out_count} "
        f"inferred={inferred_count} manual={manual_count} "
        f"continuous_obs={use_continuous_observations}"
    )
    mapped = compute_staleness_weights(
        mapped,
        as_of_ts=snapshot_ts,
        half_life_minutes=half_life_minutes,
    )

    _, eod_grid = load_latest_eod_grid(
        engine,
        curve_name,
        surface_type,
        on_or_before=eod_as_of_date,
    )
    for observation in mapped:
        if observation.core_node_key and observation.core_node_key in eod_grid:
            observation.delta_bpvol = observation.observed_bpvol - float(eod_grid[observation.core_node_key])

    update, node_metadata, _, last_observation_ts = build_live_grid(
        model,
        eod_grid,
        mapped,
        base_noise_bpvol=base_noise_bpvol,
        curve_name=curve_name,
        surface_type=surface_type,
        pricing_date=eod_as_of_date,
        tenor_weight=tenor_weight,
        use_continuous_observations=use_continuous_observations,
    )

    calibration_config = {
        "preset": preset,
        "halfLifeMinutes": half_life_minutes,
        "maxStalenessMinutes": max_staleness_minutes,
        "baseNoiseBpvol": base_noise_bpvol,
        "tenorWeight": tenor_weight,
        "snapshotKind": snapshot_kind,
        "useContinuousObservations": use_continuous_observations,
    }
    if write_observations:
        replace_observations(
            engine,
            as_of_date=as_of_date,
            curve_name=curve_name,
            surface_type=surface_type,
            calibration_preset=preset,
            observations=mapped,
            eod_grid=eod_grid,
        )
    write_snapshot(
        engine,
        as_of_date=as_of_date,
        eod_as_of_date=eod_as_of_date,
        curve_name=curve_name,
        surface_type=surface_type,
        calibration_preset=preset,
        snapshot_kind=snapshot_kind,
        snapshot_ts=snapshot_ts,
        grid_data=update.live_grid.to_dict(),
        node_metadata=node_metadata,
        eod_grid=eod_grid,
        observation_count=len(mapped),
        filtered_out_count=filtered_out_count,
        last_observation_ts=last_observation_ts,
        calibration_config=calibration_config,
        source=(
            "GSQUANT_EOD_PLUS_SDR_PCA_CLOSE"
            if snapshot_kind == SNAPSHOT_KIND_CLOSE_PCA
            else "GSQUANT_EOD_PLUS_SDR_PCA"
        ),
        pca_factors=_build_pca_factors_payload(update),
    )

    return {
        "preset": preset,
        "snapshot_kind": snapshot_kind,
        "observation_count": len(mapped),
        "filtered_out_count": filtered_out_count,
        "last_observation_ts": last_observation_ts,
    }


def try_fetch_current_day_mdp_close(
    engine: Engine,
    *,
    as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    force_refresh: bool,
) -> dict[str, float] | None:
    fetched = fetch_eod_grids(
        curve_name,
        [as_of_date],
        surface_type=surface_type,
        force_refresh=True if as_of_date == _current_trade_date() else force_refresh,
    )
    grid = fetched.get(as_of_date)
    if not grid:
        return None
    upsert_eod_history(engine, curve_name, surface_type, {as_of_date: grid})
    return grid


def freeze_close_pca_snapshots(
    engine: Engine,
    *,
    as_of_date: dt.date,
    eod_as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    model: SurfacePCAModel,
    raw_observations: list[StraddleObservation],
    presets: list[str],
    half_life_minutes: float,
    max_staleness_minutes: float,
    base_noise_bpvol: float,
    tenor_weight: float,
    force_refresh: bool,
    snapshot_ts: dt.datetime | None = None,
    write_observations: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for preset in presets:
        if (
            not force_refresh
            and snapshot_exists(
                engine,
                as_of_date=as_of_date,
                curve_name=curve_name,
                surface_type=surface_type,
                calibration_preset=preset,
                snapshot_kind=SNAPSHOT_KIND_CLOSE_PCA,
            )
        ):
            continue
        results.append(
            build_snapshot_for_preset(
                engine,
                as_of_date=as_of_date,
                eod_as_of_date=eod_as_of_date,
                curve_name=curve_name,
                surface_type=surface_type,
                model=model,
                raw_observations=raw_observations,
                preset=preset,
                half_life_minutes=half_life_minutes,
                max_staleness_minutes=max_staleness_minutes,
                base_noise_bpvol=base_noise_bpvol,
                tenor_weight=tenor_weight,
                snapshot_kind=SNAPSHOT_KIND_CLOSE_PCA,
                write_observations=write_observations,
                snapshot_ts=snapshot_ts,
            )
        )
    return results


def capture_close_mdp_snapshots(
    engine: Engine,
    *,
    as_of_date: dt.date,
    eod_as_of_date: dt.date,
    curve_name: str,
    surface_type: str,
    presets: list[str],
    force_refresh: bool,
    snapshot_ts: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    mdp_grid = load_exact_eod_grid(
        engine,
        curve_name,
        surface_type,
        as_of_date=as_of_date,
    )
    if mdp_grid is None:
        mdp_grid = try_fetch_current_day_mdp_close(
            engine,
            as_of_date=as_of_date,
            curve_name=curve_name,
            surface_type=surface_type,
            force_refresh=force_refresh,
        )
    if mdp_grid is None:
        return []

    _, previous_eod_grid = load_latest_eod_grid(
        engine,
        curve_name,
        surface_type,
        on_or_before=eod_as_of_date,
    )
    try:
        node_metadata, _ = build_close_mdp_metadata(
            mdp_grid,
            eod_grid=previous_eod_grid,
            curve_name=curve_name,
            pricing_date=as_of_date,
            surface_type=surface_type,
        )
    except Exception as exc:
        print(
            f"Skipping {SNAPSHOT_KIND_CLOSE_MDP} snapshot for {as_of_date.isoformat()}: {exc}"
        )
        return []
    results: list[dict[str, Any]] = []
    for preset in presets:
        if (
            not force_refresh
            and snapshot_exists(
                engine,
                as_of_date=as_of_date,
                curve_name=curve_name,
                surface_type=surface_type,
                calibration_preset=preset,
                snapshot_kind=SNAPSHOT_KIND_CLOSE_MDP,
            )
        ):
            continue
        write_snapshot(
            engine,
            as_of_date=as_of_date,
            eod_as_of_date=eod_as_of_date,
            curve_name=curve_name,
            surface_type=surface_type,
            calibration_preset=preset,
            snapshot_kind=SNAPSHOT_KIND_CLOSE_MDP,
            snapshot_ts=snapshot_ts or _now_et(),
            grid_data=mdp_grid,
            node_metadata=node_metadata,
            eod_grid=previous_eod_grid,
            observation_count=0,
            filtered_out_count=0,
            last_observation_ts=None,
            calibration_config={
                "preset": preset,
                "snapshotKind": SNAPSHOT_KIND_CLOSE_MDP,
                "referenceSurfaceDate": as_of_date.isoformat(),
            },
            source="GSQUANT_MDP_CLOSE",
            pca_factors={},
        )
        results.append(
            {
                "preset": preset,
                "snapshot_kind": SNAPSHOT_KIND_CLOSE_MDP,
                "observation_count": 0,
                "filtered_out_count": 0,
                "last_observation_ts": None,
            }
        )
    return results


def backfill_historical_close_snapshots(
    engine: Engine,
    *,
    start_date: dt.date,
    end_date: dt.date,
    curve_name: str,
    surface_type: str,
    model: SurfacePCAModel,
    explained_ratio: float,
    half_life_minutes: float,
    max_staleness_minutes: float,
    base_noise_bpvol: float,
    tenor_weight: float,
    force_refresh: bool,
    presets: list[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for as_of_date in _business_dates(start_date, end_date):
        reference_date = _previous_business_day(as_of_date)
        eod_as_of_date, _ = load_latest_eod_grid(
            engine,
            curve_name,
            surface_type,
            on_or_before=reference_date,
        )
        raw_observations = fetch_straddle_observations(engine, as_of_date)
        snapshot_ts = _market_close_timestamp(as_of_date)

        close_pca_results = freeze_close_pca_snapshots(
            engine,
            as_of_date=as_of_date,
            eod_as_of_date=eod_as_of_date,
            curve_name=curve_name,
            surface_type=surface_type,
            model=model,
            raw_observations=raw_observations,
            presets=presets,
            half_life_minutes=half_life_minutes,
            max_staleness_minutes=max_staleness_minutes,
            base_noise_bpvol=base_noise_bpvol,
            tenor_weight=tenor_weight,
            force_refresh=force_refresh,
            snapshot_ts=snapshot_ts,
            write_observations=True,
        )
        for result in close_pca_results:
            result["explained_variance_ratio"] = explained_ratio
        results.extend(close_pca_results)
        results.extend(
            capture_close_mdp_snapshots(
                engine,
                as_of_date=as_of_date,
                eod_as_of_date=eod_as_of_date,
                curve_name=curve_name,
                surface_type=surface_type,
                presets=presets,
                force_refresh=force_refresh,
                snapshot_ts=snapshot_ts,
            )
        )

    return results


def run_live_cycle(
    engine: Engine,
    *,
    curve_name: str,
    surface_type: str,
    lookback_business_days: int,
    n_components: int,
    half_life_minutes: float,
    max_staleness_minutes: float,
    base_noise_bpvol: float,
    tenor_weight: float,
    force_refresh: bool,
    presets: list[str],
    use_continuous_observations: bool = True,
) -> list[dict[str, Any]]:
    trade_date = _current_trade_date()
    anchor_eod_date = _previous_business_day(trade_date)
    _log_status(
        "Starting live cycle: "
        f"trade_date={trade_date.isoformat()} "
        f"anchor_eod_date={anchor_eod_date.isoformat()} "
        f"lookback_business_days={lookback_business_days}"
    )
    model, explained_ratio = ensure_history_and_model(
        engine,
        curve_name,
        surface_type,
        anchor_eod_date=anchor_eod_date,
        lookback_business_days=lookback_business_days,
        n_components=n_components,
        force_refresh=force_refresh,
    )
    eod_date, _ = load_latest_eod_grid(
        engine,
        curve_name,
        surface_type,
        on_or_before=anchor_eod_date,
    )
    _log_status(
        f"Using anchor EOD surface date {eod_date.isoformat()} with PCA explained variance "
        f"{explained_ratio:.4f}"
    )

    raw_observations = fetch_straddle_observations(engine, trade_date)
    inferred_count = sum(1 for observation in raw_observations if observation.is_inferred_incomplete)
    manual_count = sum(1 for observation in raw_observations if observation.is_manual_straddle)
    idb_count = sum(1 for observation in raw_observations if observation.platform_type == "idb")
    custy_count = sum(1 for observation in raw_observations if observation.platform_type == "custy")
    _log_status(
        f"Loaded {len(raw_observations)} raw observations for {trade_date.isoformat()} "
        f"(idb={idb_count}, custy={custy_count}, inferred={inferred_count}, manual={manual_count})"
    )
    results: list[dict[str, Any]] = []
    for preset in presets:
        summary = build_snapshot_for_preset(
            engine,
            as_of_date=trade_date,
            eod_as_of_date=eod_date,
            curve_name=curve_name,
            surface_type=surface_type,
            model=model,
            raw_observations=raw_observations,
            preset=preset,
            half_life_minutes=half_life_minutes,
            max_staleness_minutes=max_staleness_minutes,
            base_noise_bpvol=base_noise_bpvol,
            tenor_weight=tenor_weight,
            use_continuous_observations=use_continuous_observations,
        )
        summary["explained_variance_ratio"] = explained_ratio
        results.append(summary)

    if _is_after_market_close():
        close_pca_results = freeze_close_pca_snapshots(
            engine,
            as_of_date=trade_date,
            eod_as_of_date=eod_date,
            curve_name=curve_name,
            surface_type=surface_type,
            model=model,
            raw_observations=raw_observations,
            presets=presets,
            half_life_minutes=half_life_minutes,
            max_staleness_minutes=max_staleness_minutes,
            base_noise_bpvol=base_noise_bpvol,
            tenor_weight=tenor_weight,
            force_refresh=force_refresh,
        )
        for result in close_pca_results:
            result["explained_variance_ratio"] = explained_ratio
        results.extend(close_pca_results)
        results.extend(
            capture_close_mdp_snapshots(
                engine,
                as_of_date=trade_date,
                eod_as_of_date=eod_date,
                curve_name=curve_name,
                surface_type=surface_type,
                presets=presets,
                force_refresh=force_refresh,
            )
        )

    return results


def main_range(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)

    if args.start_date:
        start_date = dt.date.fromisoformat(args.start_date)
    else:
        start_date = (
            pd.Timestamp(dt.date.fromisoformat(args.end_date) if args.end_date else _previous_business_day(_current_trade_date()))
            - pd.tseries.offsets.BDay(args.lookback_business_days)
        ).date()

    end_date = (
        dt.date.fromisoformat(args.end_date)
        if args.end_date
        else _previous_business_day(_current_trade_date())
    )
    dates = _business_dates(start_date, end_date)
    fetched = fetch_eod_grids(
        args.curve_name,
        dates,
        surface_type=args.surface_type,
        force_refresh=args.force_refresh,
    )
    upsert_eod_history(engine, args.curve_name, args.surface_type, fetched)

    anchor_eod_date = _previous_business_day(end_date)
    model, explained_ratio = ensure_history_and_model(
        engine,
        args.curve_name,
        args.surface_type,
        anchor_eod_date=anchor_eod_date,
        lookback_business_days=args.lookback_business_days,
        n_components=args.n_components,
        force_refresh=args.force_refresh,
    )
    lookback_start = (
        pd.Timestamp(anchor_eod_date) - pd.tseries.offsets.BDay(args.lookback_business_days)
    ).date()
    levels_df = load_eod_history_df(
        engine,
        args.curve_name,
        args.surface_type,
        start_date=lookback_start,
        end_date=anchor_eod_date,
    )
    print(
        f"Stored {len(levels_df)} EOD grids and fitted PCA model with "
        f"{model.n_components} components. Explained variance={explained_ratio:.4f}"
    )

    results = backfill_historical_close_snapshots(
        engine,
        start_date=start_date,
        end_date=end_date,
        curve_name=args.curve_name,
        surface_type=args.surface_type,
        model=model,
        explained_ratio=explained_ratio,
        half_life_minutes=args.half_life_minutes,
        max_staleness_minutes=args.max_staleness_minutes,
        base_noise_bpvol=args.base_noise_bpvol,
        tenor_weight=args.tenor_weight,
        force_refresh=args.force_refresh,
        presets=args.presets,
    )
    for result in results:
        print(
            f"{result['preset']}[{result['snapshot_kind']}]: obs={result['observation_count']} "
            f"filtered={result['filtered_out_count']} "
            f"explained={result.get('explained_variance_ratio', 0.0):.4f}"
        )


def main_once(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)
    results = run_live_cycle(
        engine,
        curve_name=args.curve_name,
        surface_type=args.surface_type,
        lookback_business_days=args.lookback_business_days,
        n_components=args.n_components,
        half_life_minutes=args.half_life_minutes,
        max_staleness_minutes=args.max_staleness_minutes,
        base_noise_bpvol=args.base_noise_bpvol,
        tenor_weight=args.tenor_weight,
        force_refresh=args.force_refresh,
        presets=args.presets,
        use_continuous_observations=args.use_continuous_observations,
    )
    for result in results:
        print(
            f"{result['preset']}[{result['snapshot_kind']}]: obs={result['observation_count']} "
            f"filtered={result['filtered_out_count']} "
            f"explained={result.get('explained_variance_ratio', 0.0):.4f}"
        )


def main_service(args: argparse.Namespace) -> None:
    engine = create_db_engine()
    ensure_schema(engine)
    interval_seconds = max(int(args.interval_seconds), 30)
    _log_status(
        "Starting live-grid service: "
        f"curve={args.curve_name} surface={args.surface_type} "
        f"interval={interval_seconds}s lookback_business_days={args.lookback_business_days} "
        f"presets={','.join(args.presets)} continuous_obs={args.use_continuous_observations}"
    )

    cycle_number = 0

    while True:
        cycle_number += 1
        started = time.time()
        _log_status(f"Cycle {cycle_number} started")
        try:
            results = run_live_cycle(
                engine,
                curve_name=args.curve_name,
                surface_type=args.surface_type,
                lookback_business_days=args.lookback_business_days,
                n_components=args.n_components,
                half_life_minutes=args.half_life_minutes,
                max_staleness_minutes=args.max_staleness_minutes,
                base_noise_bpvol=args.base_noise_bpvol,
                tenor_weight=args.tenor_weight,
                force_refresh=args.force_refresh,
                presets=args.presets,
                use_continuous_observations=args.use_continuous_observations,
            )
            for result in results:
                last_observation_ts = result.get("last_observation_ts")
                last_observation_label = (
                    last_observation_ts.isoformat()
                    if isinstance(last_observation_ts, dt.datetime)
                    else (str(last_observation_ts) if last_observation_ts else "--")
                )
                _log_status(
                    f"{result['preset']}[{result['snapshot_kind']}]: "
                    f"obs={result['observation_count']} "
                    f"filtered={result['filtered_out_count']} "
                    f"explained={result.get('explained_variance_ratio', 0.0):.4f} "
                    f"last_obs={last_observation_label}"
                )
        except Exception as exc:
            _log_status(f"Cycle {cycle_number} failed: {exc}", level="ERROR")

        elapsed = time.time() - started
        sleep_seconds = max(interval_seconds - elapsed, 5)
        _log_status(
            f"Cycle {cycle_number} finished in {elapsed:.1f}s; sleeping {sleep_seconds:.1f}s"
        )
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill and build live ATMF swaption grids.",
    )
    parser.add_argument(
        "--mode",
        choices=("range", "once", "service"),
        required=True,
    )
    parser.add_argument("--curve-name", default=DEFAULT_CURVE_NAME)
    parser.add_argument("--surface-type", default=DEFAULT_SURFACE_TYPE)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--lookback-business-days",
        type=int,
        default=DEFAULT_LOOKBACK_BUSINESS_DAYS,
    )
    parser.add_argument("--n-components", type=int, default=DEFAULT_COMPONENTS)
    parser.add_argument(
        "--half-life-minutes",
        type=float,
        default=DEFAULT_HALF_LIFE_MINUTES,
    )
    parser.add_argument(
        "--max-staleness-minutes",
        type=float,
        default=DEFAULT_MAX_STALENESS_MINUTES,
    )
    parser.add_argument(
        "--base-noise-bpvol",
        type=float,
        default=DEFAULT_BASE_NOISE_BPVOL,
    )
    parser.add_argument("--tenor-weight", type=float, default=DEFAULT_TENOR_WEIGHT)
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--presets",
        default="idb_straddles,custy_only,custy_and_idb",
        help="Comma-separated preset list.",
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--no-continuous-obs",
        dest="use_continuous_observations",
        action="store_false",
        default=True,
        help="Disable continuous-coordinate observation layer (use legacy nearest-node).",
    )
    args = parser.parse_args()
    args.presets = [
        preset.strip()
        for preset in str(args.presets).split(",")
        if preset.strip()
    ]
    unknown = [preset for preset in args.presets if preset not in CALIBRATION_PRESETS]
    if unknown:
        raise ValueError(f"Unknown presets: {unknown}")
    return args


def main() -> None:
    args = parse_args()
    if args.mode == "range":
        main_range(args)
        return
    if args.mode == "once":
        main_once(args)
        return
    main_service(args)


if __name__ == "__main__":
    main()
