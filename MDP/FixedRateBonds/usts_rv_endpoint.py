import argparse
import datetime
import json
import os
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import QuantLib as ql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator


POINTS_TABLE = "arbs_ust_rv_points_v1"
AVAILABLE_VALUE_COLUMNS = ["mmss", "ytm", "clean_price", "dirty_price", "mdur", "coupon", "carry_bps", "roll_bps", "carry_and_roll_bps"]


def _json_value(val: Any):
    if val is None:
        return None

    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()

    if isinstance(val, (np.floating, np.integer)):
        val = val.item()

    if isinstance(val, float):
        if np.isnan(val) or np.isinf(val):
            return None
        return float(val)

    if isinstance(val, (int, str, bool)):
        return val

    if isinstance(val, dict):
        return {str(k): _json_value(v) for k, v in val.items()}

    if isinstance(val, (list, tuple)):
        return [_json_value(v) for v in val]

    return str(val)


def _safe_float(x: Any) -> Optional[float]:
    try:
        y = float(x)
    except Exception:
        return None
    if np.isnan(y) or np.isinf(y):
        return None
    return y


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _parse_payload(payload_arg: Optional[str]) -> Dict[str, Any]:
    if payload_arg:
        raw = payload_arg.strip()
        if not raw:
            return {}
        return json.loads(raw)

    raw_stdin = ""
    try:
        import sys

        raw_stdin = sys.stdin.read()
    except Exception:
        raw_stdin = ""

    raw_stdin = (raw_stdin or "").strip()
    if not raw_stdin:
        return {}
    return json.loads(raw_stdin)


def _parse_date(raw: Any) -> Tuple[datetime.date, bool]:
    today = datetime.date.today()
    if raw is None:
        return today, True

    txt = str(raw).strip()
    if not txt:
        return today, True

    if txt.lower() in {"live", "today"}:
        return today, True

    try:
        parsed = datetime.date.fromisoformat(txt)
        return parsed, parsed == today
    except Exception:
        pass

    try:
        parsed_dt = datetime.datetime.fromisoformat(txt.replace("Z", "+00:00"))
        parsed = parsed_dt.date()
        return parsed, parsed == today
    except Exception as exc:
        raise ValueError(f"Invalid asOf date '{raw}'. Expected YYYY-MM-DD, 'today', or 'live'.") from exc


def _adjust_to_business_day(d: datetime.date) -> datetime.date:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    probe = ql.Date(d.day, d.month, d.year)
    while not cal.isBusinessDay(probe):
        probe = cal.advance(probe, ql.Period(-1, ql.Days))
    return datetime.date(probe.year(), probe.month(), probe.dayOfMonth())


def _normalize_knots(raw: Any, x_min: float, x_max: float) -> List[float]:
    if raw is None:
        return []

    vals: List[float] = []
    if isinstance(raw, list):
        for item in raw:
            f = _safe_float(item)
            if f is None:
                continue
            if x_min < f < x_max:
                vals.append(float(f))
    else:
        txt = str(raw)
        for tok in txt.split(","):
            f = _safe_float(tok.strip())
            if f is None:
                continue
            if x_min < f < x_max:
                vals.append(float(f))

    vals = sorted(set(vals))
    return vals


def _ensure_numeric_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _ct_alias_from_rank_oi(rank: Any, oi: Any) -> Optional[str]:
    try:
        r = int(float(rank))
    except Exception:
        return None
    if r != 0:
        return None
    import re

    match = re.search(r"(\d{1,2})", str(oi or ""))
    if not match:
        return None
    try:
        tenor = int(match.group(1))
    except Exception:
        return None
    if tenor <= 0:
        return None
    return f"CT{tenor}"


def get_db_connection_string(override: Optional[str] = None) -> str:
    if override and str(override).strip():
        conn_string = str(override).strip()
    else:
        conn_string = ""
        for key in ("SWAPPULSE_DATABASE_URL", "DATABASE_URL"):
            raw = os.getenv(key)
            if raw and raw.strip():
                conn_string = raw.strip()
                break

    if conn_string:
        if conn_string.startswith("postgres://"):
            conn_string = "postgresql://" + conn_string[len("postgres://") :]
        return conn_string

    host = os.getenv("SWAPPULSE_DB_HOST", "").strip()
    port = os.getenv("SWAPPULSE_DB_PORT", "5432").strip()
    dbname = os.getenv("SWAPPULSE_DB_NAME", "postgres").strip()
    user = os.getenv("SWAPPULSE_DB_USER", "").strip()
    password = os.getenv("SWAPPULSE_DB_PASSWORD", "").strip()
    sslmode = os.getenv("SWAPPULSE_DB_SSLMODE", "").strip()

    if not host or not user or not password:
        raise ValueError(
            "Postgres connection is not configured. Set one of "
            "SWAPPULSE_DATABASE_URL / DATABASE_URL, or set "
            "SWAPPULSE_DB_HOST, SWAPPULSE_DB_USER, SWAPPULSE_DB_PASSWORD "
            "(optionally SWAPPULSE_DB_PORT, SWAPPULSE_DB_NAME, SWAPPULSE_DB_SSLMODE)."
        )

    auth_user = quote_plus(user)
    auth_password = quote_plus(password)
    conn_string = f"postgresql://{auth_user}:{auth_password}@{host}:{port}/{dbname}"
    if sslmode:
        conn_string += f"?sslmode={sslmode}"
    return conn_string


def create_db_engine(connection_string: Optional[str] = None) -> Engine:
    conn_string = get_db_connection_string(connection_string)
    return create_engine(
        conn_string,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def _coerce_date(val: Any) -> Optional[datetime.date]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.date.fromisoformat(str(val))
    except Exception:
        return None


def _load_points_df(
    engine: Engine,
    *,
    target_as_of: datetime.date,
    curve_name: str,
    min_ttm: float,
) -> Tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    warnings: List[str] = []
    selected_as_of: Optional[datetime.date] = None

    with engine.begin() as conn:
        selected_as_of_raw = conn.execute(
            text(
                f"""
                SELECT MAX(as_of_date) AS as_of_date
                FROM {POINTS_TABLE}
                WHERE curve_name = :curve_name
                  AND as_of_date <= :target_as_of
                """
            ),
            {"curve_name": curve_name, "target_as_of": target_as_of},
        ).scalar()
        selected_as_of = _coerce_date(selected_as_of_raw)

        if selected_as_of is None:
            latest_any_raw = conn.execute(
                text(
                    f"""
                    SELECT MAX(as_of_date) AS as_of_date
                    FROM {POINTS_TABLE}
                    WHERE curve_name = :curve_name
                    """
                ),
                {"curve_name": curve_name},
            ).scalar()
            selected_as_of = _coerce_date(latest_any_raw)
            if selected_as_of is not None:
                warnings.append(
                    f"No DB snapshot found on/before {target_as_of.isoformat()}; using latest available {selected_as_of.isoformat()}."
                )

        if selected_as_of is None:
            raise RuntimeError(
                f"No UST RV snapshots found in table '{POINTS_TABLE}' for curve '{curve_name}'. "
                "Run SDRUtils/_swappulse_scripts/ingest_ustrv.py first."
            )

        if selected_as_of != target_as_of:
            warnings.append(
                f"Using DB snapshot asOf {selected_as_of.isoformat()} for requested {target_as_of.isoformat()}."
            )

        rows = conn.execute(
            text(
                f"""
                SELECT
                    cusip,
                    oi,
                    ust_label,
                    rank,
                    ttm,
                    mdur,
                    ytm,
                    mmss,
                    carry_bps,
                    roll_bps,
                    carry_and_roll_bps,
                    clean_price,
                    dirty_price,
                    coupon,
                    issue_date,
                    maturity_date,
                    market_timestamp,
                    snapshot_ts
                FROM {POINTS_TABLE}
                WHERE curve_name = :curve_name
                  AND as_of_date = :as_of_date
                  AND (ttm IS NULL OR ttm >= :min_ttm)
                ORDER BY ttm NULLS LAST, oi NULLS LAST, rank NULLS LAST, cusip
                """
            ),
            {
                "curve_name": curve_name,
                "as_of_date": selected_as_of,
                "min_ttm": float(min_ttm),
            },
        ).mappings().all()

    column_names = [
        "cusip",
        "oi",
        "ust_label",
        "rank",
        "ttm",
        "mdur",
        "ytm",
        "mmss",
        "carry_bps",
        "roll_bps",
        "carry_and_roll_bps",
        "clean_price",
        "dirty_price",
        "coupon",
        "issue_date",
        "maturity_date",
        "market_timestamp",
        "snapshot_ts",
    ]
    if rows:
        points_df = pd.DataFrame(rows)
    else:
        points_df = pd.DataFrame(columns=column_names)

    points_df = _ensure_numeric_columns(
        points_df,
        ["rank", "ttm", "mdur", "ytm", "mmss", "carry_bps", "roll_bps", "carry_and_roll_bps", "clean_price", "dirty_price", "coupon"],
    )
    if "cusip" in points_df.columns:
        points_df["cusip"] = points_df["cusip"].astype(str)

    latest_snapshot_ts = None
    if "snapshot_ts" in points_df.columns and not points_df.empty:
        try:
            latest_snapshot_ts = pd.to_datetime(points_df["snapshot_ts"], errors="coerce").max()
        except Exception:
            latest_snapshot_ts = None

    meta = {
        "asOf": selected_as_of.isoformat(),
        "pointCount": int(len(points_df)),
        "curveName": curve_name,
        "snapshotTs": _json_value(latest_snapshot_ts),
    }
    return points_df, meta, warnings


def _build_single_spline(
    points_df: pd.DataFrame,
    cfg: Dict[str, Any],
    fallback_x_col: str,
    idx: int,
) -> Dict[str, Any]:
    spline_id = str(cfg.get("id") or f"spline_{idx + 1}")
    method = str(cfg.get("method") or "bspline").strip().lower()
    if method not in {"bspline", "loess"}:
        method = "bspline"

    name = str(cfg.get("name") or f"{method.upper()} {idx + 1}")
    x_col = str(cfg.get("xColumn") or fallback_x_col)
    y_col = str(cfg.get("valueColumn") or "mmss")
    color = cfg.get("color")
    line_width = _safe_float(cfg.get("lineWidth")) or 2.0
    point_count = int(_clamp(_safe_float(cfg.get("pointCount")) or 350, 25, 2000))

    if x_col not in points_df.columns:
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": 0,
            "x": [],
            "y": [],
            "error": f"Unknown xColumn '{x_col}'",
        }
    if y_col not in points_df.columns:
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": 0,
            "x": [],
            "y": [],
            "error": f"Unknown valueColumn '{y_col}'",
        }

    fit_df = points_df[[x_col, y_col, "rank"]].copy()
    fit_df = _ensure_numeric_columns(fit_df, [x_col, y_col, "rank"])

    exclude_ranks_raw = cfg.get("excludeRanks", [0, 1, 2])
    exclude_ranks: List[int] = []
    if isinstance(exclude_ranks_raw, list):
        for r in exclude_ranks_raw:
            try:
                exclude_ranks.append(int(r))
            except Exception:
                continue
    if exclude_ranks:
        fit_df = fit_df[~fit_df["rank"].isin(exclude_ranks)]

    fit_df = fit_df.dropna(subset=[x_col, y_col])
    if fit_df.empty:
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": 0,
            "x": [],
            "y": [],
            "error": "No fit points after filtering",
        }

    dedup_df = fit_df.groupby(x_col, as_index=False)[y_col].mean().sort_values(by=x_col)
    if len(dedup_df) < 4:
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": int(len(dedup_df)),
            "x": [],
            "y": [],
            "error": "Need at least 4 unique x points to build spline",
        }

    x = dedup_df[x_col].to_numpy(dtype=float)
    y = dedup_df[y_col].to_numpy(dtype=float)
    x_min_fit = float(np.nanmin(x))
    x_max_fit = float(np.nanmax(x))
    x_min_req = _safe_float(cfg.get("xMin"))
    x_max_req = _safe_float(cfg.get("xMax"))
    x_min = x_min_req if x_min_req is not None else x_min_fit
    x_max = x_max_req if x_max_req is not None else x_max_fit
    if not (x_max > x_min):
        x_min, x_max = x_min_fit, x_max_fit
    if not (x_max > x_min):
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": int(len(dedup_df)),
            "x": [],
            "y": [],
            "error": "Invalid x range for spline",
        }

    x_grid = np.linspace(x_min, x_max, point_count)

    try:
        interpolator = GeneralCurveInterpolator(x=x, y=y)
        if method == "loess":
            frac = _clamp(_safe_float(cfg.get("frac")) or 0.25, 0.05, 1.0)
            it = int(_clamp(_safe_float(cfg.get("it")) or 50, 0, 200))
            delta = _safe_float(cfg.get("delta")) or 0.0
            spline_func = interpolator.loess_interpolation(frac=frac, it=it, delta=delta, return_func=True)
        else:
            degree = int(_clamp(_safe_float(cfg.get("degree")) or 2, 1, 5))
            if len(x) <= degree:
                degree = max(1, len(x) - 1)
            knots = _normalize_knots(cfg.get("knots"), x_min_fit, x_max_fit)
            if knots:
                spline_func = interpolator.b_spline_with_knots_interpolation(
                    knots=knots,
                    k=degree,
                    return_func=True,
                )
            else:
                spline_func = interpolator.b_spline1_interpolation(k=degree, return_func=True)

        y_grid = np.asarray(spline_func(x_grid), dtype=float)
        valid = np.isfinite(x_grid) & np.isfinite(y_grid)
        x_plot = x_grid[valid]
        y_plot = y_grid[valid]

        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": int(len(dedup_df)),
            "x": [_json_value(v) for v in x_plot.tolist()],
            "y": [_json_value(v) for v in y_plot.tolist()],
            "error": None,
        }
    except Exception as exc:
        return {
            "id": spline_id,
            "name": name,
            "method": method,
            "valueColumn": y_col,
            "xColumn": x_col,
            "color": color,
            "lineWidth": line_width,
            "fitCount": int(len(dedup_df)),
            "x": [],
            "y": [],
            "error": str(exc),
        }


def build_payload(payload: Dict[str, Any], db_connection_string: Optional[str] = None) -> Dict[str, Any]:
    raw_as_of = payload.get("asOf")
    requested_date, requested_live = _parse_date(raw_as_of)
    effective_date = _adjust_to_business_day(requested_date)

    min_ttm = _safe_float(payload.get("minTtm"))
    if min_ttm is None:
        min_ttm = 1.0

    x_column = str(payload.get("xColumn") or "ttm")
    curve_name = str(payload.get("curveName") or "USD-SOFR-1D")
    include_values = payload.get("includeValues") or ["mmss", "ytm"]
    include_values = [str(v) for v in include_values]

    spline_cfgs = payload.get("splineConfigs") or []
    engine = create_db_engine(db_connection_string)
    points_df, base_meta, load_warnings = _load_points_df(
        engine,
        target_as_of=effective_date,
        curve_name=curve_name,
        min_ttm=min_ttm,
    )

    points: List[Dict[str, Any]] = []
    for _, row in points_df.iterrows():
        point = {
            "cusip": _json_value(row.get("cusip")),
            "ust_label": _json_value(row.get("ust_label")),
            "oi": _json_value(row.get("oi")),
            "rank": _json_value(row.get("rank")),
            "ct_alias": _json_value(_ct_alias_from_rank_oi(row.get("rank"), row.get("oi"))),
            "ttm": _json_value(row.get("ttm")),
            "mdur": _json_value(row.get("mdur")),
            "ytm": _json_value(row.get("ytm")),
            "mmss": _json_value(row.get("mmss")),
            "carry_bps": _json_value(row.get("carry_bps")),
            "roll_bps": _json_value(row.get("roll_bps")),
            "carry_and_roll_bps": _json_value(row.get("carry_and_roll_bps")),
            "clean_price": _json_value(row.get("clean_price")),
            "dirty_price": _json_value(row.get("dirty_price")),
            "coupon": _json_value(row.get("coupon")),
            "issue_date": _json_value(row.get("issue_date")),
            "maturity_date": _json_value(row.get("maturity_date")),
            "market_timestamp": _json_value(row.get("market_timestamp")),
        }
        points.append(point)

    spline_series = []
    for i, cfg in enumerate(spline_cfgs):
        if not isinstance(cfg, dict):
            continue
        if cfg.get("enabled") is False:
            continue
        spline_series.append(_build_single_spline(points_df=points_df, cfg=cfg, fallback_x_col=x_column, idx=i))

    warnings: List[str] = []
    if requested_date != effective_date:
        warnings.append(f"Adjusted asOf from {requested_date.isoformat()} to prior business day {effective_date.isoformat()}.")
    warnings.extend(load_warnings)
    as_of_for_response = str(base_meta.get("asOf") or effective_date.isoformat())

    return {
        "requestedAsOf": requested_date.isoformat(),
        "asOf": as_of_for_response,
        "requestedLive": requested_live,
        "curveName": curve_name,
        "xColumn": x_column,
        "includeValues": include_values,
        "availableValueColumns": AVAILABLE_VALUE_COLUMNS,
        "points": points,
        "splineSeries": spline_series,
        "meta": {**base_meta, "warnings": warnings},
    }


def main():
    parser = argparse.ArgumentParser(description="UST RV notebook endpoint: points + custom splines")
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("SWAPPULSE_DATABASE_URL", os.getenv("DATABASE_URL")),
        help=(
            "Postgres connection URL. If omitted, resolves from "
            "SWAPPULSE_DATABASE_URL, then DATABASE_URL, then SWAPPULSE_DB_* vars."
        ),
    )
    parser.add_argument("--payload", default=None, help="JSON payload. If omitted, read from stdin.")
    args = parser.parse_args()

    try:
        payload = _parse_payload(args.payload)
        out = build_payload(payload, db_connection_string=args.database_url)
        print(json.dumps(out, ensure_ascii=True))
    except Exception as exc:
        err = {
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(err, ensure_ascii=True))
        raise


if __name__ == "__main__":
    main()
