#!/usr/bin/env python
"""Warm intraday IRS curve and computed-timeseries caches ahead of users.

Examples:
    python -m scripts.warm_intraday_irs_cache
    python -m scripts.warm_intraday_irs_cache --window-template cme_trading_day --date 2026-03-16
    python -m scripts.warm_intraday_irs_cache --curve USD-SOFR-1D-Q12STIRT --tenor fomc_dec26 --tenor 5Y

Cron example:
    */15 6-17 * * 1-5 cd C:/Users/chris/clee/ARBS && conda run -n stir python -m scripts.warm_intraday_irs_cache
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

DEFAULT_CURVES = ("USD-SOFR-1D-Q12STIRT",)
DEFAULT_LAG_MINUTES = 15
_BASE_OUTRIGHT_TENORS = tuple(
    [f"{months}M" for months in range(1, 24)]
    + [f"{years}Y" for years in range(1, 41)]
)
_STIRT_OUTRIGHT_TENORS = tuple([f"{months}M" for months in range(1, 24)] + ["1Y", "2Y", "27M", "30M", "33M", "3Y"])
_STIRT_MAX_MATURITY_YEARS = 3
_STIRT_IMM_SPANS = (1, 4)
_STIRT_IMM_HORIZON_COUNT = 13
_FORWARD_START_TENORS = (
    "1M1Y",
    "1M2Y",
    "3M1Y",
    "3M2Y",
    "6M1Y",
    "6M2Y",
    "1Y1Y",
    "1Y2Y",
    "2Y1Y",
)

_GENERIC_CB_FORWARD_START_TENORS = (
    "1Y1Y",
    "1Y2Y",
    "2Y1Y",
)
_CB_TOKEN_PREFIX = {"FOMC": "fomc"}
_IMM_MONTH_CODE = {
    3: "H",
    6: "M",
    9: "U",
    12: "Z",
}


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date '{value}'. Expected YYYY-MM-DD.") from exc


def _parse_time(value: str) -> dt.time:
    try:
        return dt.time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid time '{value}'. Expected HH:MM or HH:MM:SS.") from exc


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _resolve_dates(
    *,
    explicit_dates: Sequence[dt.date],
    start_date: dt.date | None,
    end_date: dt.date | None,
    default_date: dt.date,
) -> list[dt.date]:
    if explicit_dates:
        return sorted(set(explicit_dates))
    if start_date is None and end_date is None:
        return [default_date]
    if start_date is None or end_date is None:
        raise ValueError("Both --start-date and --end-date are required when either is provided.")
    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date.")
    out: list[dt.date] = []
    current = start_date
    while current <= end_date:
        out.append(current)
        current += dt.timedelta(days=1)
    return out


def _current_trading_date(*, now_utc: dt.datetime | None = None) -> dt.date:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)
    now_chi = now_utc.astimezone(ZoneInfo("America/Chicago"))
    if now_chi.hour >= 17:
        return now_chi.date() + dt.timedelta(days=1)
    return now_chi.date()


def _window_for_date(
    trading_date: dt.date,
    *,
    window_template: str,
    timezone_name: str,
    start_time: dt.time,
    end_time: dt.time,
) -> tuple[dt.datetime, dt.datetime]:
    if window_template == "cme_trading_day":
        chi = ZoneInfo("America/Chicago")
        start = dt.datetime.combine(trading_date - dt.timedelta(days=1), dt.time(17, 0), tzinfo=chi)
        end = dt.datetime.combine(trading_date, dt.time(16, 0), tzinfo=chi)
        return start, end

    if window_template == "nyc_rth":
        timezone_name = "America/New_York"
        start_time = dt.time(7, 0)
        end_time = dt.time(17, 0)

    tz = ZoneInfo(timezone_name)
    start = dt.datetime.combine(trading_date, start_time, tzinfo=tz)
    end = dt.datetime.combine(trading_date, end_time, tzinfo=tz)
    if end < start:
        raise ValueError("Custom window requires --end-time to be on or after --start-time.")
    return start, end


def _floor_to_minute(value: dt.datetime) -> dt.datetime:
    return value.replace(second=0, microsecond=0)


def _cap_end_at_now(
    start: dt.datetime,
    end: dt.datetime,
    *,
    now_utc: dt.datetime | None = None,
    delay_minutes: int = DEFAULT_LAG_MINUTES,
) -> tuple[dt.datetime, dt.datetime] | None:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = _floor_to_minute(
        now_utc.astimezone(start.tzinfo or dt.timezone.utc) - dt.timedelta(minutes=int(delay_minutes))
    )
    capped_end = min(end, now_local)
    if capped_end < start:
        return None
    return start, capped_end


def _build_minute_timestamps(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    if end < start:
        return []
    out: list[dt.datetime] = []
    current = start
    step = dt.timedelta(minutes=1)
    while current <= end:
        out.append(current)
        current += step
    return out


def _curve_reference_id(curve_name: str) -> str:
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CURVE_TO_CB

    curve_upper = str(curve_name or "").strip().upper()
    for candidate in sorted(_CURVE_TO_CB, key=len, reverse=True):
        if curve_upper == candidate or curve_upper.startswith(candidate) or candidate in curve_upper:
            return candidate
    return curve_upper


def _is_stirt_curve(curve_name: str) -> bool:
    return "STIRT" in str(curve_name or "").upper()


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if hasattr(value, "to_pydatetime"):
        py_value = value.to_pydatetime()
        return py_value.date() if isinstance(py_value, dt.datetime) else py_value
    year = getattr(value, "year", None)
    month = getattr(value, "month", None)
    day = getattr(value, "day", None)
    if year is None or month is None or day is None:
        raise TypeError(f"Cannot coerce {type(value)!r} to date.")
    return dt.date(int(year), int(month), int(day))


def _next_imm_dates(as_of: dt.date, *, count: int) -> list[dt.date]:
    from rateslib.scheduling import next_imm

    imm = dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time())
    out: list[dt.date] = []
    for _ in range(max(0, int(count))):
        imm_date = _as_date(next_imm(imm))
        out.append(imm_date)
        imm = dt.datetime.combine(imm_date, dt.time())
    return out


def _imm_code_for_date(value: dt.date) -> str:
    date_value = _as_date(value)
    return f"{_IMM_MONTH_CODE[date_value.month]}{date_value.year % 100:02d}"


def _add_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year + int(years))
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + int(years))


def _resolve_imm_token(token: str, ref_date: dt.date) -> dt.date:
    from rateslib.scheduling import get_imm, next_imm

    imm_token = str(token).strip().upper()
    if not imm_token.startswith("IMM_"):
        raise ValueError(f"IMM tenor token required, got {token!r}")

    suffix = imm_token.split("IMM_", 1)[1]
    if suffix.isnumeric():
        offset = int(suffix) - 1
        imm = dt.datetime.combine(ref_date + dt.timedelta(days=1), dt.time())
        for _ in range(offset + 1):
            imm = next_imm(imm)
        return _as_date(imm)

    return _as_date(get_imm(code=suffix))


def _stirt_tenor_maturity_date(curve_name: str, tenor: str, *, anchor_date: dt.date) -> dt.date | None:
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

    tenor_token = str(tenor or "").strip()
    if not tenor_token:
        return None

    if tenor_token.upper().startswith("IMM_") and "X" in tenor_token.upper():
        try:
            imm_date_token, mat_date_token = tenor_token.upper().split("X", 1)
            effective_date = _resolve_imm_token(imm_date_token, anchor_date)
            return _resolve_imm_token(mat_date_token, effective_date)
        except Exception:
            return None

    try:
        cb_dates = resolve_central_bank_tenor(
            _curve_reference_id(curve_name),
            tenor_token,
            as_of=anchor_date,
        )
    except Exception:
        cb_dates = None
    if cb_dates is not None:
        return _as_date(cb_dates[1])

    return None


def _relative_imm_pair_tenors(*, max_imm_index: int, spans: Sequence[int]) -> list[str]:
    tenors: list[str] = []
    for span in spans:
        for start_idx in range(1, max_imm_index - int(span) + 1):
            tenors.append(f"IMM_{start_idx}xIMM_{start_idx + int(span)}")
    return tenors


def _explicit_imm_pair_tenors(*, as_of: dt.date, horizon_count: int, spans: Sequence[int]) -> list[str]:
    imm_dates = _next_imm_dates(as_of, count=horizon_count)
    imm_codes = [_imm_code_for_date(d) for d in imm_dates]
    tenors: list[str] = []
    for span in spans:
        for offset in range(0, len(imm_codes) - int(span)):
            tenors.append(f"IMM_{imm_codes[offset]}xIMM_{imm_codes[offset + int(span)]}")
    return tenors


def _default_tenors_for_curve(curve_name: str, *, anchor_date: dt.date | None = None) -> list[str]:
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_for_curve

    if anchor_date is None:
        anchor_date = dt.date.today()

    base = list(_BASE_OUTRIGHT_TENORS)
    if _is_stirt_curve(curve_name):
        stirt_base = list(_STIRT_OUTRIGHT_TENORS)
        max_maturity_date = _add_years(anchor_date, _STIRT_MAX_MATURITY_YEARS)
        stirt_imm_relative = [
            tenor
            for tenor in _relative_imm_pair_tenors(max_imm_index=_STIRT_IMM_HORIZON_COUNT, spans=_STIRT_IMM_SPANS)
            if (
                (maturity_date := _stirt_tenor_maturity_date(curve_name, tenor, anchor_date=anchor_date))
                is not None
                and maturity_date <= max_maturity_date
            )
        ]
        stirt_imm_explicit = [
            tenor
            for tenor in _explicit_imm_pair_tenors(
                as_of=anchor_date,
                horizon_count=_STIRT_IMM_HORIZON_COUNT,
                spans=_STIRT_IMM_SPANS,
            )
            if (
                (maturity_date := _stirt_tenor_maturity_date(curve_name, tenor, anchor_date=anchor_date))
                is not None
                and maturity_date <= max_maturity_date
            )
        ]
        cb_name = central_bank_for_curve(_curve_reference_id(curve_name))
        meeting_tenors = (
            [
                f"{_CB_TOKEN_PREFIX[cb_name]}_{rank}"
                for rank in range(1, 25)
                if (
                    (maturity_date := _stirt_tenor_maturity_date(
                        curve_name,
                        f"{_CB_TOKEN_PREFIX[cb_name]}_{rank}",
                        anchor_date=anchor_date,
                    ))
                    is not None
                    and maturity_date <= max_maturity_date
                )
            ]
            if cb_name in _CB_TOKEN_PREFIX
            else []
        )
        return _dedupe_preserve_order(stirt_base + meeting_tenors + stirt_imm_relative + stirt_imm_explicit)

    forward_starts = list(_FORWARD_START_TENORS)
    cb_name = central_bank_for_curve(_curve_reference_id(curve_name))
    if cb_name in _CB_TOKEN_PREFIX:
        meeting_prefix = _CB_TOKEN_PREFIX[cb_name]
        return _dedupe_preserve_order(
            base
            + [f"{meeting_prefix}_{rank}" for rank in range(1, 25)]
            + list(_GENERIC_CB_FORWARD_START_TENORS)
        )
    return _dedupe_preserve_order(base + forward_starts[:37])


def _resolve_curve_store_name(mdp: Any, curve_name: str) -> str:
    builder = mdp._get_curve_store_builder() if hasattr(mdp, "_get_curve_store_builder") else None
    if hasattr(mdp, "_resolve_curve_store_curve_name"):
        try:
            return str(
                mdp._resolve_curve_store_curve_name(
                    requested_curve_name=curve_name,
                    kwargs={},
                    builder=builder,
                )
            )
        except Exception:
            pass
    return str(curve_name)


def _latest_curve_store_timestamp(store: Any, curve_name: str) -> dt.datetime | None:
    import pandas as pd

    try:
        trading_dates = list(store.available_dates(curve_name))
    except Exception:
        return None

    for trading_date in reversed(trading_dates):
        try:
            df = store.read_raw_nodes(curve_name, start=trading_date, end=trading_date)
        except Exception:
            continue
        if df is None or df.empty or "timestamp_utc" not in df.columns:
            continue
        ts_series = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dropna()
        if ts_series.empty:
            continue
        return ts_series.max().to_pydatetime()
    return None


def _resolve_incremental_timestamp_range(
    *,
    curve_name: str,
    mdp: Any,
    ts_builder: Any,
    window_template: str,
    timezone_name: str,
    start_time: dt.time,
    end_time: dt.time,
    now_utc: dt.datetime | None = None,
) -> list[dt.datetime]:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)

    store_curve_name = _resolve_curve_store_name(mdp, curve_name)
    latest_timestamp = _latest_curve_store_timestamp(mdp._get_curve_store(), store_curve_name)

    if latest_timestamp is None:
        default_date = _current_trading_date(now_utc=now_utc) if window_template == "cme_trading_day" else now_utc.astimezone(
            ZoneInfo("America/New_York")
        ).date()
        window = _cap_end_at_now(
            *_window_for_date(
                default_date,
                window_template=window_template,
                timezone_name=timezone_name,
                start_time=start_time,
                end_time=end_time,
            ),
            now_utc=now_utc,
        )
        if window is None:
            return []
        start, end = window
    else:
        start = _floor_to_minute(latest_timestamp)
        end = _floor_to_minute(
            now_utc.astimezone(start.tzinfo or dt.timezone.utc) - dt.timedelta(minutes=DEFAULT_LAG_MINUTES)
        )
        if end < start:
            return []

    raw_timestamps = _build_minute_timestamps(start, end)
    if not raw_timestamps:
        return []

    filtered = ts_builder._prepare_product_intraday_timestamps(
        product="IRS",
        mdp=mdp,
        start=start,
        end=end,
        freq=None,
        timestamps=raw_timestamps,
    )
    return filtered if filtered is not None else raw_timestamps


def _concat_timeseries_frames(frames: Sequence[Any]) -> Any:
    import pandas as pd

    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0]
    out = pd.concat(non_empty, axis=1)
    return out.loc[:, ~out.columns.duplicated(keep="last")].sort_index()


def _safe_warm_raw_curves(
    mdp: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
    ignore_cache: bool,
    n_jobs: int,
    calibration_executor: str,
) -> tuple[int, list[dt.datetime]]:
    timestamp_list = list(timestamps)
    if not timestamp_list:
        return 0, []

    def _run(batch: Sequence[dt.datetime], *, depth: int = 0) -> tuple[int, list[dt.datetime]]:
        batch_list = list(batch)
        request = {
            "curve_name": curve_name,
            "timestamps": batch_list,
            "ignore_cache": ignore_cache,
            "n_jobs": n_jobs,
            "calibration_executor": calibration_executor,
        }
        try:
            return len(mdp.bulk_get_data(request)), []
        except Exception as exc:
            if len(batch_list) == 1:
                print(f"  WARN RAW {curve_name}: failed timestamp {batch_list[0].isoformat()} ({exc})")
                return 0, batch_list
            if depth == 0:
                print(
                    f"  WARN RAW {curve_name}: bulk warm failed for {len(batch_list)} timestamps ({exc}); "
                    "retrying by smaller batches."
                )
            midpoint = max(1, len(batch_list) // 2)
            left_count, left_failed = _run(batch_list[:midpoint], depth=depth + 1)
            right_count, right_failed = _run(batch_list[midpoint:], depth=depth + 1)
            return left_count + right_count, left_failed + right_failed

    return _run(timestamp_list)


def _safe_warm_timeseries(
    ts_builder: Any,
    *,
    start: dt.datetime,
    end: dt.datetime,
    queries: Sequence[Any],
    n_jobs: int,
    ignore_cache: bool,
    timestamps: Sequence[dt.datetime],
    mdps: dict[str, Any],
    curve_name: str,
) -> tuple[Any, list[str]]:
    import pandas as pd

    failures: list[str] = []
    query_list = list(queries)
    if not query_list:
        return pd.DataFrame(), failures

    def _run(batch: Sequence[Any], *, depth: int = 0) -> Any:
        batch_list = list(batch)
        try:
            return ts_builder.get_timeseries(
                start=start,
                end=end,
                queries=batch_list,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=None,
                timestamps=list(timestamps),
                mdps=mdps,
            )
        except Exception as exc:
            if len(batch_list) == 1:
                tenor = str(getattr(batch_list[0], "tenor", "<unknown>"))
                failures.append(tenor)
                print(f"  WARN TS  {curve_name}: failed tenor {tenor} ({exc})")
                return pd.DataFrame()
            if depth == 0:
                print(
                    f"  WARN TS  {curve_name}: batch warm failed for {len(batch_list)} tenors ({exc}); "
                    "retrying by smaller batches."
                )
            midpoint = max(1, len(batch_list) // 2)
            left = _run(batch_list[:midpoint], depth=depth + 1)
            right = _run(batch_list[midpoint:], depth=depth + 1)
            return _concat_timeseries_frames([left, right])

    return _run(query_list), failures


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warm intraday IRS raw curves and computed timeseries caches.")
    parser.add_argument("--curve", action="append", default=[], help="Curve name to warm. Repeatable.")
    parser.add_argument("--tenor", action="append", default=[], help="Computed-timeseries tenor to warm. Repeatable.")
    parser.add_argument("--source", default="BARCHART_STIRF-RL", help="IRSwapsMDP source.")
    parser.add_argument("--date", action="append", type=_parse_date, default=[], help="Trading date to warm. Repeatable.")
    parser.add_argument("--start-date", type=_parse_date, default=None, help="Inclusive start date.")
    parser.add_argument("--end-date", type=_parse_date, default=None, help="Inclusive end date.")
    parser.add_argument(
        "--window-template",
        choices=("nyc_rth", "cme_trading_day", "custom"),
        default="nyc_rth",
        help="Timestamp expansion template for each trading date.",
    )
    parser.add_argument("--timezone", default="America/New_York", help="Custom window timezone.")
    parser.add_argument("--start-time", type=_parse_time, default=dt.time(7, 0), help="Custom window start time.")
    parser.add_argument("--end-time", type=_parse_time, default=dt.time(17, 0), help="Custom window end time.")
    parser.add_argument("--freq", default="1min", help="Computed timeseries frequency.")
    parser.add_argument("--n-jobs", type=int, default=12, help="Worker count for raw curve and TS warming.")
    parser.add_argument(
        "--calibration-executor",
        choices=("thread", "process"),
        default="process",
        help="Executor for raw bulk curve calibration.",
    )
    parser.add_argument("--ignore-cache", action="store_true", help="Force cache refresh for raw curves and TS values.")
    parser.add_argument("--disable-l2", action="store_true", help="Disable Supabase L2 for this run.")
    parser.add_argument("--skip-curve-warm", action="store_true", help="Skip raw curve warming.")
    parser.add_argument("--skip-timeseries-warm", action="store_true", help="Skip computed-timeseries warming.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.disable_l2:
        os.environ["ARBS_SUPABASE_ENABLED"] = "0"

    curves = _dedupe_preserve_order(args.curve or list(DEFAULT_CURVES))
    explicit_tenors = _dedupe_preserve_order(args.tenor)
    use_incremental_mode = not args.date and args.start_date is None and args.end_date is None

    if args.skip_curve_warm and args.skip_timeseries_warm:
        parser.error("At least one of raw curve warming or timeseries warming must remain enabled.")

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.TimeseriesBuilder import TimeseriesBuilder

    ny_now = dt.datetime.now(ZoneInfo("America/New_York"))
    trading_dates = [] if use_incremental_mode else _resolve_dates(
        explicit_dates=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        default_date=ny_now.date(),
    )

    mdp = IRSwapsMDP(source=args.source)
    ts_builder = TimeseriesBuilder()

    warmed_curve_windows = 0
    warmed_ts_windows = 0
    failed_curve_timestamps = 0
    failed_ts_tenors = 0
    failed_windows = 0
    successful_windows = 0

    def _warm_curve(curve: str, timestamps: list[dt.datetime], *, label: str) -> None:
        nonlocal warmed_curve_windows, warmed_ts_windows
        nonlocal failed_curve_timestamps, failed_ts_tenors, failed_windows, successful_windows
        if not timestamps:
            print(f"SKIP {curve} because no timestamps were generated for {label}.")
            return

        anchor_date = timestamps[0].date()
        curve_tenors = [] if args.skip_timeseries_warm else (
            explicit_tenors or _default_tenors_for_curve(curve, anchor_date=anchor_date)
        )
        start = timestamps[0]
        end = timestamps[-1]
        print(
            f"WARM {curve} "
            f"label={label} "
            f"window={start.isoformat()}..{end.isoformat()} "
            f"minutes={len(timestamps)} tenors={len(curve_tenors)}"
        )

        succeeded = False
        try:
            if not args.skip_curve_warm:
                curve_count, failed_timestamps = _safe_warm_raw_curves(
                    mdp,
                    curve_name=curve,
                    timestamps=timestamps,
                    ignore_cache=args.ignore_cache,
                    n_jobs=args.n_jobs,
                    calibration_executor=args.calibration_executor,
                )
                warmed_curve_windows += 1
                failed_curve_timestamps += len(failed_timestamps)
                succeeded = succeeded or curve_count > 0
                print(
                    f"  RAW {curve}: {curve_count}/{len(timestamps)} curve snapshots ready"
                    + (f" ({len(failed_timestamps)} failed timestamps)" if failed_timestamps else "")
                )

            if not args.skip_timeseries_warm:
                queries = [
                    UnifiedQuery(
                        curve=curve,
                        tenor=tenor,
                        value=UnifiedValue.IRS_RATE,
                    )
                    for tenor in curve_tenors
                ]
                df, failed_tenors = _safe_warm_timeseries(
                    ts_builder,
                    start=start,
                    end=end,
                    queries=queries,
                    n_jobs=args.n_jobs,
                    ignore_cache=args.ignore_cache,
                    timestamps=timestamps,
                    mdps={"IRS": mdp},
                    curve_name=curve,
                )
                warmed_ts_windows += 1
                failed_ts_tenors += len(failed_tenors)
                succeeded = succeeded or not df.empty
                print(
                    f"  TS  {curve}: rows={len(df)} cols={len(df.columns)}"
                    + (f" ({len(failed_tenors)} failed tenors)" if failed_tenors else "")
                )

            if succeeded:
                successful_windows += 1
            else:
                failed_windows += 1
                print(f"  WARN {curve}: no successful warm results for {label}")
        except Exception as exc:
            failed_windows += 1
            print(f"  WARN {curve}: window {label} failed unexpectedly ({exc})")

    if use_incremental_mode:
        now_utc = dt.datetime.now(dt.timezone.utc)
        for curve in curves:
            try:
                timestamps = _resolve_incremental_timestamp_range(
                    curve_name=curve,
                    mdp=mdp,
                    ts_builder=ts_builder,
                    window_template=args.window_template,
                    timezone_name=args.timezone,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    now_utc=now_utc,
                )
            except Exception as exc:
                failed_windows += 1
                print(f"WARN {curve}: failed to resolve incremental window ({exc})")
                continue
            _warm_curve(curve, timestamps, label="incremental-from-db")
    else:
        for trading_date in trading_dates:
            if args.window_template != "cme_trading_day" and trading_date.weekday() >= 5:
                print(f"SKIP weekend date {trading_date.isoformat()} for {args.window_template}.")
                continue

            try:
                window = _cap_end_at_now(
                    *_window_for_date(
                        trading_date,
                        window_template=args.window_template,
                        timezone_name=args.timezone,
                        start_time=args.start_time,
                        end_time=args.end_time,
                    )
                )
            except Exception as exc:
                failed_windows += 1
                print(f"WARN {trading_date.isoformat()}: failed to resolve window ({exc})")
                continue
            if window is None:
                print(f"SKIP {trading_date.isoformat()} because the requested window is entirely in the future.")
                continue

            start, end = window
            timestamps = _build_minute_timestamps(start, end)
            if not timestamps:
                print(f"SKIP {trading_date.isoformat()} because no timestamps were generated.")
                continue

            for curve in curves:
                _warm_curve(curve, timestamps, label=trading_date.isoformat())

    print(
        "DONE "
        f"curve_windows={warmed_curve_windows} "
        f"timeseries_windows={warmed_ts_windows} "
        f"failed_timestamps={failed_curve_timestamps} "
        f"failed_tenors={failed_ts_tenors} "
        f"failed_windows={failed_windows}"
    )
    return 0 if successful_windows > 0 or failed_windows == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
