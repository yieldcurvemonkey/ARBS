#!/usr/bin/env python
r"""Import a historical GSQUANT-style swap curve panel into the local CurveStore.

Usage:
    python -m scripts.import_gsquant_curve_panel --csv-path "C:\path\to\USD_OIS.csv"
    python -m scripts.import_gsquant_curve_panel --csv-path "C:\path\to\USD_OIS.csv" --overwrite

The input CSV is expected to be a wide par-rate panel with a `Date` column and
tenor columns such as `3m`, `6m`, `1Y`, `2Y`, ..., `30Y`. Curves are
calibrated as spot-start rateslib OIS curves using the repo's `USD-OIS`
conventions and then written into the Parquet-backed CurveStore.
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import pandas as pd
import pytz
import rateslib as rl

from Caching.curve_analytics import analytics_tenors_for_curve, build_analytics_frame, compute_session_minute
from Caching.curve_store import CurveSnapshot, CurveStore
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

_NY = pytz.timezone("America/New_York")
_UTC = pytz.UTC
_CHI = pytz.timezone("America/Chicago")

_USD_OIS_PANEL_TENORS: tuple[str, ...] = (
    "3M",
    "6M",
    "1Y",
    "2Y",
    "3Y",
    "4Y",
    "5Y",
    "6Y",
    "7Y",
    "8Y",
    "9Y",
    "10Y",
    "15Y",
    "20Y",
    "25Y",
    "30Y",
)


def _normalize_tenor_label(raw: Any) -> str:
    text = str(raw).strip().upper()
    if not text:
        return text
    if text.endswith("M") or text.endswith("Y"):
        return text
    raise ValueError(f"Unsupported tenor label: {raw!r}")


def _required_panel_columns(curve_name: str) -> tuple[str, ...]:
    if str(curve_name).upper() == "USD-OIS":
        return _USD_OIS_PANEL_TENORS
    raise NotImplementedError(f"Unsupported panel curve: {curve_name}")


def load_historical_curve_panel(
    csv_path: str | Path,
    *,
    curve_name: str = "USD-OIS",
) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "Date" not in df.columns:
        raise KeyError("Historical curve CSV must contain a 'Date' column.")

    rename_map: Dict[str, str] = {}
    for col in df.columns:
        if col == "Date":
            continue
        rename_map[col] = _normalize_tenor_label(col)
    df = df.rename(columns=rename_map)

    required_tenors = _required_panel_columns(curve_name)
    missing = [tenor for tenor in required_tenors if tenor not in df.columns]
    if missing:
        raise ValueError(f"Historical curve CSV is missing tenor columns: {missing}")

    out = df[["Date", *required_tenors]].copy()
    out["as_of"] = pd.to_datetime(out["Date"], format="%d-%b-%y", errors="coerce").dt.date
    out = out.drop(columns=["Date"])
    out = out.dropna(subset=["as_of"])
    for tenor in required_tenors:
        out[tenor] = pd.to_numeric(out[tenor], errors="coerce")
    out = out.dropna(subset=list(required_tenors))
    out = out.sort_values("as_of").reset_index(drop=True)
    return out


def _spot_start(as_of: dt.date, curve_name: str) -> Any:
    curve_def = RATESLIB_CURVE_DEFINITIONS[curve_name]
    settlement_days = int(curve_def.get("SettlementDays", 2) or 0)
    base = dt.datetime(as_of.year, as_of.month, as_of.day)
    if settlement_days <= 0:
        return base
    return rl.add_tenor(
        base,
        f"{settlement_days}b",
        modifier=curve_def["BusinessConvention"],
        calendar=curve_def["Calendar"],
    )


def _curve_timestamp(as_of: dt.date) -> dt.datetime:
    return _NY.localize(dt.datetime(as_of.year, as_of.month, as_of.day, 15, 0, 0))


def build_historical_panel_curve(
    *,
    curve_name: str,
    as_of: dt.date,
    par_rates: Dict[str, float],
) -> tuple[str, rl.Curve]:
    curve_def = RATESLIB_CURVE_DEFINITIONS[curve_name]
    curve_id = f"{as_of.isoformat()}-GSQUANT-rl_basic_{curve_name}"
    spot = _spot_start(as_of, curve_name)

    instruments = []
    node_dates: Dict[pd.Timestamp, float] = {pd.Timestamp(as_of): 1.0}
    for tenor in _required_panel_columns(curve_name):
        rate = float(par_rates[tenor])
        irs = rl.IRS(
            effective=spot,
            termination=tenor,
            fixed_rate=rate,
            curves=curve_id,
            spec=curve_def["ReferenceRate"],
        )
        maturity = max(pd.to_datetime(irs.leg1.cashflows()["Acc End"]))
        node_dates[pd.Timestamp(maturity)] = 1.0
        instruments.append(irs)

    curve = rl.Curve(
        nodes=dict(sorted(node_dates.items())),
        id=curve_id,
        convention=curve_def["DayCounter"],
        calendar=curve_def["Calendar"],
        modifier=curve_def["BusinessConvention"],
        interpolation="log_linear",
    )
    with IRSwapsMDP._suppress_ratelibs_solver_output():
        rl.Solver(
            curves=[curve],
            instruments=instruments,
            s=[float(par_rates[tenor]) for tenor in _required_panel_columns(curve_name)],
            id=curve_id,
            func_tol=1e-9,
            conv_tol=1e-9,
            max_iter=100,
            weights=[1.0] * len(instruments),
        )

    ts_local = _curve_timestamp(as_of)
    ts_utc = ts_local.astimezone(_UTC)
    curve.timestamp = ts_local
    curve.timestamp_utc = ts_utc
    curve.curve_name = curve_name
    curve.reference_key = curve_name
    return curve_id, curve


def _curve_to_snapshot(
    *,
    curve_name: str,
    as_of: dt.date,
    rl_curve: rl.Curve,
    source_variant: str,
) -> CurveSnapshot:
    ts_local_ny = getattr(rl_curve, "timestamp", None) or _curve_timestamp(as_of)
    if ts_local_ny.tzinfo is None:
        ts_local_ny = _NY.localize(ts_local_ny)
    ts_utc = ts_local_ny.astimezone(_UTC)
    ts_chi = ts_utc.astimezone(_CHI)

    raw_nodes = rl_curve.nodes._nodes if hasattr(rl_curve.nodes, "_nodes") else dict(rl_curve.nodes)
    node_dates_sorted = sorted(raw_nodes.keys())
    node_dates = [pd.Timestamp(node_dt).date() for node_dt in node_dates_sorted]
    discount_factors = [float(raw_nodes[node_dt]) for node_dt in node_dates_sorted]

    return CurveSnapshot(
        timestamp_utc=ts_utc,
        timestamp_local=ts_chi,
        trading_date=as_of,
        session_minute=compute_session_minute(ts_chi),
        curve_name=curve_name,
        cfg_hash="",
        reference_key=curve_name,
        interpolation=str(getattr(rl_curve, "interpolation", "log_linear") or "log_linear"),
        source_variant=source_variant,
        node_dates=node_dates,
        discount_factors=discount_factors,
    )


def _curve_to_analytics(
    *,
    curve_name: str,
    as_of: dt.date,
    rl_curve: rl.Curve,
) -> pd.DataFrame:
    ts_local_ny = getattr(rl_curve, "timestamp", None) or _curve_timestamp(as_of)
    if ts_local_ny.tzinfo is None:
        ts_local_ny = _NY.localize(ts_local_ny)
    ts_utc = ts_local_ny.astimezone(_UTC)
    curve_def = RATESLIB_CURVE_DEFINITIONS[curve_name]
    spot = _spot_start(as_of, curve_name)
    row: dict[str, Any] = {
        "timestamp_utc": ts_utc,
        "trading_date": as_of,
        "session_minute": compute_session_minute(ts_utc.astimezone(_CHI)),
    }
    for tenor in analytics_tenors_for_curve(curve_name):
        value = float("nan")
        try:
            irs = rl.IRS(
                effective=spot,
                termination=str(tenor),
                spec=curve_def["ReferenceRate"],
                curves=rl_curve,
            )
            value = float(irs.rate(curves=rl_curve).real)
        except Exception:
            value = float("nan")
        row[f"par_rate_{tenor}"] = value
        row[f"rate_{tenor}"] = value
    return build_analytics_frame([row])


def import_curve_panel(
    *,
    csv_path: str | Path,
    curve_name: str = "USD-OIS",
    source_variant: str = "GSQUANT_RL",
    overwrite: bool = False,
    store: Optional[CurveStore] = None,
) -> dict[str, Any]:
    panel_df = load_historical_curve_panel(csv_path, curve_name=curve_name)
    if store is None:
        store = CurveStore.default()

    print(f"CurveStore base dir: {store.base_dir}")
    print(f"Historical panel rows: {len(panel_df)}")

    rows_iter: Iterable[tuple[int, pd.Series]]
    try:
        import tqdm

        rows_iter = tqdm.tqdm(panel_df.iterrows(), total=len(panel_df), desc=f"Importing {curve_name}", unit=" days")
    except ImportError:
        rows_iter = panel_df.iterrows()

    days_written = 0
    analytics_written = 0
    days_skipped = 0
    errors: list[tuple[dt.date, str]] = []

    for _, row in rows_iter:
        as_of = row["as_of"]
        if not isinstance(as_of, dt.date):
            continue

        if not overwrite and store.has_day(curve_name, as_of) and store.has_analytics_day(curve_name, as_of):
            days_skipped += 1
            continue

        par_rates = {tenor: float(row[tenor]) for tenor in _required_panel_columns(curve_name)}
        try:
            _curve_id, rl_curve = build_historical_panel_curve(
                curve_name=curve_name,
                as_of=as_of,
                par_rates=par_rates,
            )
            snapshot = _curve_to_snapshot(
                curve_name=curve_name,
                as_of=as_of,
                rl_curve=rl_curve,
                source_variant=source_variant,
            )
            analytics_df = _curve_to_analytics(
                curve_name=curve_name,
                as_of=as_of,
                rl_curve=rl_curve,
            )
            raw_meta = store.write_day(curve_name, as_of, [snapshot], overwrite=overwrite)
            analytics_meta = store.write_analytics_day(curve_name, as_of, analytics_df, overwrite=overwrite)
            if raw_meta is not None:
                days_written += 1
            if analytics_meta is not None:
                analytics_written += 1
            if raw_meta is None and analytics_meta is None:
                days_skipped += 1
        except Exception as exc:
            errors.append((as_of, str(exc)))

    if errors:
        print(f"Failed dates: {len(errors)}")
        for as_of, message in errors[:10]:
            print(f"  {as_of}: {message}")

    return {
        "curve_name": curve_name,
        "rows": len(panel_df),
        "days_written": days_written,
        "analytics_written": analytics_written,
        "days_skipped": days_skipped,
        "errors": len(errors),
        "error_samples": errors[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a historical GSQUANT-style curve panel into CurveStore")
    parser.add_argument("--csv-path", required=True, help="Path to the historical curve panel CSV")
    parser.add_argument("--curve-name", default="USD-OIS", help="Curve name to calibrate")
    parser.add_argument("--source-variant", default="GSQUANT_RL", help="CurveStore source variant tag")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite identical day partitions if content changes")
    parser.add_argument("--base-dir", default=None, help="CurveStore base directory (default: auto)")
    args = parser.parse_args()

    store = CurveStore(base_dir=args.base_dir) if args.base_dir else CurveStore.default()
    summary = import_curve_panel(
        csv_path=args.csv_path,
        curve_name=args.curve_name,
        source_variant=args.source_variant,
        overwrite=args.overwrite,
        store=store,
    )
    print(f"Done. Summary: {summary}")


if __name__ == "__main__":
    main()
