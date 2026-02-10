import argparse
import datetime
import json
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.IRSwapsTB import IRSwapsTB
from TB.TimeseriesBuilder import TimeseriesBuilder


def _to_iso(val: Any):
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    return val


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


def _extract_cusip(text: str) -> Optional[str]:
    match = re.search(r"\b[0-9A-Z]{9}\b", str(text or "").upper())
    return match.group(0) if match else None


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


def _build_points_df(
    as_of_date: datetime.date,
    include_mmss: bool,
    curve_name: str,
    min_ttm: float,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

    ref_df = usts_mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
    ref_df = ref_df.drop(columns=["record_date"], errors="ignore").rename(columns={"label": "ust_label"})
    ref_df = _ensure_numeric_columns(ref_df, ["ttm", "rank", "cpn"])
    ref_df = ref_df[ref_df["ttm"] >= min_ttm].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")

    ts_for_pricing: datetime.date | str = "live" if as_of_date == datetime.date.today() else as_of_date
    pricers = usts_mdp.get_pricer(
        request={
            "cusips": ref_df["cusip"].tolist(),
            "timestamp": ts_for_pricing,
            "show_tqdm": False,
        }
    )

    metrics: List[Dict[str, Any]] = []
    for cusip, pricer in pricers.items():
        meta = {}
        try:
            meta = pricer.meta() or {}
        except Exception:
            meta = {}

        metrics.append(
            {
                "cusip": str(cusip),
                "ytm": _safe_float(pricer.ytm() if hasattr(pricer, "ytm") else None),
                "mdur": _safe_float(pricer.mod_duration() if hasattr(pricer, "mod_duration") else None),
                "clean_price": _safe_float(pricer.clean_price() if hasattr(pricer, "clean_price") else None),
                "dirty_price": _safe_float(pricer.dirty_price() if hasattr(pricer, "dirty_price") else None),
                "market_timestamp": _to_iso(meta.get("timestamp")),
            }
        )

    metrics_df = pd.DataFrame(metrics)
    if metrics_df.empty:
        merged_df = ref_df.copy()
        merged_df["ytm"] = np.nan
        merged_df["mdur"] = np.nan
        merged_df["clean_price"] = np.nan
        merged_df["dirty_price"] = np.nan
        merged_df["market_timestamp"] = None
    else:
        merged_df = ref_df.merge(metrics_df, on="cusip", how="left")

    if include_mmss and not merged_df.empty:
        swaps_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
        tb = TimeseriesBuilder(
            irswaps_tb=IRSwapsTB(swaps_mdp),
            fixedratebonds_tb=FixedRateBondsTB(usts_mdp),
        )

        queries = [IRSwapQuery(curve=curve_name, tenor=c, value=IRSwapValue.MMSS) for c in merged_df["cusip"].tolist()]
        ts_df = tb.get_timeseries(
            start=as_of_date,
            end=as_of_date,
            queries=queries,
            n_jobs=5,
        )

        mmss_map: Dict[str, float] = {}
        if ts_df is not None and not ts_df.empty:
            latest = ts_df.iloc[-1]
            for col_name, val in latest.items():
                c = _extract_cusip(col_name)
                fv = _safe_float(val)
                if c and fv is not None:
                    mmss_map[c] = fv

        merged_df["mmss"] = merged_df["cusip"].map(mmss_map)
    else:
        merged_df["mmss"] = np.nan

    merged_df["coupon"] = merged_df["cpn"] if "cpn" in merged_df.columns else np.nan
    merged_df = _ensure_numeric_columns(
        merged_df,
        ["rank", "ttm", "coupon", "ytm", "mdur", "clean_price", "dirty_price", "mmss"],
    )
    merged_df = merged_df.sort_values(by=["ttm", "oi", "rank"], kind="mergesort")

    meta = {
        "asOf": as_of_date.isoformat(),
        "pointCount": int(len(merged_df)),
        "curveName": curve_name,
    }
    return merged_df, meta


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


def build_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
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
    include_mmss = ("mmss" in include_values) or any(
        str(cfg.get("valueColumn") or "").lower() == "mmss" for cfg in spline_cfgs
    )

    points_df, base_meta = _build_points_df(
        as_of_date=effective_date,
        include_mmss=include_mmss,
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
            "ttm": _json_value(row.get("ttm")),
            "mdur": _json_value(row.get("mdur")),
            "ytm": _json_value(row.get("ytm")),
            "mmss": _json_value(row.get("mmss")),
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

    return {
        "requestedAsOf": requested_date.isoformat(),
        "asOf": effective_date.isoformat(),
        "requestedLive": requested_live,
        "curveName": curve_name,
        "xColumn": x_column,
        "includeValues": include_values,
        "availableValueColumns": ["mmss", "ytm", "clean_price", "dirty_price", "mdur", "coupon"],
        "points": points,
        "splineSeries": spline_series,
        "meta": {**base_meta, "warnings": warnings},
    }


def main():
    parser = argparse.ArgumentParser(description="UST RV notebook endpoint: points + custom splines")
    parser.add_argument("--payload", default=None, help="JSON payload. If omitted, read from stdin.")
    args = parser.parse_args()

    try:
        payload = _parse_payload(args.payload)
        out = build_payload(payload)
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
