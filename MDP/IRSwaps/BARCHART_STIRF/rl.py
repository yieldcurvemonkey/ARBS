import contextlib
import datetime
import hashlib
import io
import logging
import math
import multiprocessing as mp
import os
import pickle
import re
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

import pandas as pd
import pytz
import rateslib as rl
from pandas.tseries.offsets import DateOffset
from itertools import islice

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

_STIR_ROOT_CODE_RE = re.compile(
    r"^(SR1|SER|SL|SR3|SFR|SQ|ZQ|FF|RA|EB|IJ|RG|IM|TV|J8|JU|T0|IT|J2)([FGHJKMNQUVXZ]\d{2})$",
    re.IGNORECASE,
)
_CALIBRATION_EXECUTORS = frozenset({"thread", "process"})
_CALIBRATION_CFG_KEYS = frozenset(
    {
        "interpolation",
        "max_tenor_from_timestamp_months",
        "mixed_interpolation",
        "mixed_spline_add_boundary_nodes",
        "mixed_spline_drop_last_node",
        "mixed_spline_end_years",
        "mixed_spline_endpoints",
        "mixed_spline_start_years",
        "mixed_spline_tail_days",
        "node_reference_key",
        "reference_key",
        "rl_irs_spec",
        "serff_skew",
        "serff_skew_direct_sr1",
        "serff_skew_direct_weight",
        "serff_skew_extrap_constant_from_last",
        "serff_skew_extrap_min_years",
        "serff_skew_extrap_mode",
        "serff_skew_extrap_roots",
        "serff_skew_extrap_weight",
        "serff_skew_extrapolate",
        "sofr_reference_key",
    }
)


def _flatten_pricers(pricers: Dict[str, List["RLSTIRFuturePricer"]]) -> List["RLSTIRFuturePricer"]:
    # Each key maps to a list (often length 1). Keep all, preserve order.
    out: List["RLSTIRFuturePricer"] = []
    for lst in pricers.values():
        if lst:
            out.extend(lst)
    return out


def _sort_pricers_for_solver(
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
) -> List["RLSTIRFuturePricer"]:
    """
    Deterministic ordering for solver:
      1) by effective date
      2) then by maturity date
      3) then by rl_stirf_id (or symbol) as a stable tie-breaker
    """
    flat = _flatten_pricers(pricers)
    return sorted(
        flat,
        key=lambda p: (
            getattr(p, "_effective_date", None),
            getattr(p, "_maturity_date", None),
            getattr(p, "_rl_stirf_id", None) or getattr(p, "_meta_data", {}).get("symbol", ""),
        ),
    )


def _sort_nodes(nodes: Dict) -> Dict:
    # nodes keys are rateslib dt (datetime-like); dict insertion order matters
    return dict(sorted(nodes.items(), key=lambda kv: kv[0]))


def _as_node_ts(d: datetime.date, *, base_ts: pd.Timestamp) -> pd.Timestamp:
    """
    Create a date-anchored node timestamp (00:00) for rateslib curves.

    Do not carry intraday time-of-day from quote timestamps into curve nodes.
    RFR float periods and fixings are date-based; intraday node starts can make
    front contracts fail with missing-fixing errors even when fixings are present.
    """
    dt = d.date() if isinstance(d, (pd.Timestamp, datetime.datetime)) else d
    return rl.dt(dt.year, dt.month, dt.day)


def _cm_instruments(prefix: str, count: int = 12) -> List[str]:
    return [f"{prefix}CM{i}" for i in range(1, count + 1)]


def _build_stirf_nodes(
    *,
    timestamp: datetime.datetime,
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    central_bank_dates: Dict[str, Dict[str, Tuple[datetime.date, datetime.date]]],
    reference_key: str,
    max_tenor_from_timestamp_months: int,
    initial_nodes: Optional[Dict[pd.Timestamp, float]] = None,
) -> Dict[pd.Timestamp, float]:
    assert isinstance(timestamp, datetime.datetime)
    assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None

    base_ts = pd.Timestamp(timestamp)
    base_date = timestamp.date()
    horizon_date = (base_ts + DateOffset(months=max_tenor_from_timestamp_months)).date()

    # --- central bank end dates (period boundaries) ---
    cb_map = central_bank_dates.get(reference_key, {})
    all_cb_ends: List[datetime.date] = sorted({end for (_start, end) in cb_map.values()})

    cb_extends_beyond_horizon = bool(all_cb_ends) and (max(all_cb_ends) > horizon_date)

    # take CB ends in (base_date, horizon_date]
    cb_ends_in_range = [d for d in all_cb_ends if (d > base_date and d <= horizon_date)]

    # if horizon is before the next CB end (rare, but handle), include the next end after base_date
    if not cb_ends_in_range:
        next_end = min((d for d in all_cb_ends if d > base_date), default=None)
        if next_end is not None:
            cb_ends_in_range = [next_end]

    node_dates: List[datetime.date] = list(cb_ends_in_range)
    last_cb_date: Optional[datetime.date] = max(node_dates) if node_dates else None

    # --- extend with pricer maturities only if CB schedule does NOT cover the horizon ---
    if (not cb_extends_beyond_horizon) and pricers:
        flat = _flatten_pricers(pricers)
        pricer_mats = sorted({p._maturity_date for p in flat if getattr(p, "_maturity_date", None) is not None})

        cutoff = last_cb_date or base_date
        extra = [d for d in pricer_mats if (d > cutoff and d <= horizon_date)]
        node_dates.extend(extra)

    # de-dupe + sort
    node_dates = sorted(set(node_dates))

    # build nodes dict (values are placeholders / initial guesses)
    nodes: Dict[pd.Timestamp, float] = {_as_node_ts(base_date, base_ts=base_ts): 1.0}
    for d in node_dates:
        key = _as_node_ts(d, base_ts=base_ts)
        nodes[key] = initial_nodes.get(key, 1.0) if initial_nodes else 1.0

    return nodes


def _should_suppress_solver_output(line: str) -> bool:
    return "SUCCESS: `conv_tol` reached" in line and "(levenberg_marquardt)" in line


@contextlib.contextmanager
def _suppress_solver_output() -> Iterable[None]:
    class _FilteredWriteStream(io.TextIOBase):
        def __init__(self, stream: Any):
            self._stream = stream
            self._buffer = ""

        def writable(self) -> bool:
            return True

        def write(self, s: str) -> int:
            if not s:
                return 0
            self._buffer += s
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if not _should_suppress_solver_output(line):
                    self._stream.write(line + "\n")
            return len(s)

        def flush(self) -> None:
            if self._buffer and not _should_suppress_solver_output(self._buffer):
                self._stream.write(self._buffer)
            self._buffer = ""
            self._stream.flush()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._stream, name)

    stdout = _FilteredWriteStream(sys.stdout)
    stderr = _FilteredWriteStream(sys.stderr)
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            yield
        finally:
            stdout.flush()
            stderr.flush()


def _emit_calibration_status(
    *,
    curve_name: str,
    executor_mode: str,
    workers: int,
    jobs: int,
    show_tqdm: bool,
    tqdm_mod: Any,
) -> None:
    message = (
        f"[BARCHART_STIRF] calibration_executor={executor_mode} "
        f"workers={workers} jobs={jobs} curve={curve_name}"
    )
    if show_tqdm and tqdm_mod is not None:
        try:
            tqdm_mod.tqdm.write(message)
            return
        except Exception:
            pass
    logging.getLogger(__name__).info(message)


def _validate_spawn_process_pool_environment() -> None:
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", None)
    if not isinstance(main_file, str) or not main_file or main_file.startswith("<") or not os.path.exists(main_file):
        raise RuntimeError(
            "Process-pool calibration requires an importable __main__ module when using spawn. "
            "Interactive stdin/REPL sessions are not supported."
        )


def _reduced_calibration_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    reduced = {key: cfg[key] for key in _CALIBRATION_CFG_KEYS if key in cfg}
    bad_keys = [key for key, value in reduced.items() if callable(value)]
    if bad_keys:
        raise TypeError(f"Calibration config contains non-picklable callables: {bad_keys}")
    try:
        pickle.dumps(reduced)
    except Exception as exc:
        raise TypeError("Reduced calibration config is not pickleable") from exc
    return reduced


def _build_curve_from_pricers_core(
    *,
    curve_name: str,
    timestamp: datetime.datetime,
    cfg: Dict[str, Any],
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    initial_nodes: Optional[Dict[pd.Timestamp, float]] = None,
    solver_tolerances: Optional[Dict[str, float]] = None,
) -> Tuple[rl.Curve, rl.Solver]:
    _func_tol = (solver_tolerances or {}).get("func_tol", 1e-5)
    _conv_tol = (solver_tolerances or {}).get("conv_tol", 1e-5)
    curve_cls = BARCHART_STIRF_CURVE
    sorted_pricers = _sort_pricers_for_solver(pricers)
    node_reference_key = cfg.get("node_reference_key", cfg["reference_key"])
    interpolation = cfg.get("interpolation", "log_linear")

    def one_day_irs(eff_date, curve_key):
        cal_name = RATESLIB_CURVE_DEFINITIONS[curve_key]["Calendar"]
        bus_conv = str(RATESLIB_CURVE_DEFINITIONS[curve_key].get("BusinessConvention", "mf")).upper()
        cal = rl.get_calendar(cal_name)
        eff_date = cal.roll(eff_date, modifier=bus_conv, settlement=False)
        return rl.IRS(
            effective=eff_date,
            termination="1b",
            spec=cfg["rl_irs_spec"],
            stub=None,
            curves=curve_key,
        )

    def butterfly(d0, d1, d2, curve_key):
        return rl.Spread(
            rl.Spread(one_day_irs(d0, curve_key), one_day_irs(d1, curve_key)),
            rl.Spread(one_day_irs(d1, curve_key), one_day_irs(d2, curve_key)),
        )

    if cfg.get("serff_skew", False):
        ff_pricers_by_code: Dict[str, RLSTIRFuturePricer] = {}
        ser_pricers_by_code: Dict[str, RLSTIRFuturePricer] = {}
        base_pricers: List[RLSTIRFuturePricer] = []

        for p in sorted_pricers:
            root_and_code = curve_cls._pricer_root_and_code(p)
            if root_and_code is None:
                base_pricers.append(p)
                continue

            root, code = root_and_code
            if root == "ZQ":
                ff_pricers_by_code[code] = p
                continue

            base_pricers.append(p)
            if root == "SR1":
                ser_pricers_by_code[code] = p

        serff_basis = {
            code: float(ser_pricers_by_code[code]._price - ff_pricers_by_code[code]._price)
            for code in ser_pricers_by_code
            if code in ff_pricers_by_code
        }
        serff_basis_points = curve_cls._build_serff_basis_points(
            base_date=timestamp.date(),
            ser_pricers_by_code=ser_pricers_by_code,
            ff_pricers_by_code=ff_pricers_by_code,
        )
        serff_basis_last = float(serff_basis_points[-1][1]) if serff_basis_points else None
        serff_direct_sr1 = bool(cfg.get("serff_skew_direct_sr1", True))
        serff_extrapolate = bool(cfg.get("serff_skew_extrapolate", False))
        serff_extrap_constant_from_last = bool(cfg.get("serff_skew_extrap_constant_from_last", False))
        serff_extrap_mode = str(cfg.get("serff_skew_extrap_mode", "linear")).lower()
        serff_extrap_min_years = float(cfg.get("serff_skew_extrap_min_years", 0.0) or 0.0)
        serff_direct_weight = float(cfg.get("serff_skew_direct_weight", 1e7))
        serff_extrap_weight = float(cfg.get("serff_skew_extrap_weight", 1e5))
        serff_extrap_roots = {str(x).upper() for x in cfg.get("serff_skew_extrap_roots", ["SR3"])}
        base_date = timestamp.date()

        nodes = _build_stirf_nodes(
            timestamp=timestamp,
            pricers={"BASE": base_pricers},
            central_bank_dates=_CENTRAL_BANK_DATES,
            reference_key=node_reference_key,
            max_tenor_from_timestamp_months=cfg["max_tenor_from_timestamp_months"],
            initial_nodes=initial_nodes,
        )
        nodes = _sort_nodes(nodes)
        nodes = curve_cls._ensure_mixed_support_nodes(nodes=nodes, cfg=cfg, base_date=timestamp.date())
        curve_interp_kwargs = curve_cls._curve_interp_kwargs(
            nodes=nodes,
            cfg=cfg,
            base_date=timestamp.date(),
            interpolation=interpolation,
        )

        sofr_reference_key = cfg["sofr_reference_key"]
        rl_sofr_curve = rl.Curve(
            nodes=nodes,
            id=sofr_reference_key,
            convention=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[sofr_reference_key]["BusinessConvention"],
            **curve_interp_kwargs,
        )

        sofr_meeting_dates = sorted(k for k in nodes.keys())
        sofr_bflies = [
            butterfly(sofr_meeting_dates[i - 1], sofr_meeting_dates[i], sofr_meeting_dates[i + 1], sofr_reference_key)
            for i in range(1, len(sofr_meeting_dates) - 1)
        ]
        sofr_solver = rl.Solver(
            curves=[rl_sofr_curve],
            instruments=[curve_cls._build_pricable_for_curve(p, curve_key=sofr_reference_key) for p in base_pricers] + sofr_bflies,
            s=[p._rate for p in base_pricers] + [0.0] * len(sofr_bflies),
            id=f"{curve_name}-SOFR-ANCHOR",
            weights=[1.0] * len(base_pricers) + [1e-8] * len(sofr_bflies),
            func_tol=_func_tol,
            conv_tol=_conv_tol,
        )

        skew_s: List[float] = []
        skew_w: List[float] = []
        for p in base_pricers:
            root_and_code = curve_cls._pricer_root_and_code(p)
            basis_adjustment: Optional[float] = None
            target_weight = 1.0

            if serff_direct_sr1 and root_and_code and root_and_code[0] == "SR1" and root_and_code[1] in serff_basis:
                basis_adjustment = float(serff_basis[root_and_code[1]])
                target_weight = serff_direct_weight
            elif serff_extrapolate and root_and_code and root_and_code[0] in serff_extrap_roots and serff_basis_points:
                tenor_years = curve_cls._tenor_years(base_date, getattr(p, "_maturity_date", None))
                if tenor_years is not None and tenor_years >= serff_extrap_min_years:
                    if serff_extrap_constant_from_last and serff_basis_last is not None:
                        basis_adjustment = float(serff_basis_last)
                    else:
                        basis_adjustment = curve_cls._serff_basis_interp(
                            tenor_years=tenor_years,
                            points=serff_basis_points,
                            extrap_mode=serff_extrap_mode,
                        )
                    if basis_adjustment is not None:
                        target_weight = serff_extrap_weight

            if basis_adjustment is not None:
                sofr_pricable = curve_cls._build_pricable_for_curve(p, curve_key=sofr_reference_key)
                skew_s.append(float(sofr_pricable.rate(solver=sofr_solver).real) + float(basis_adjustment))
                skew_w.append(float(target_weight))
            else:
                skew_s.append(float(p._rate))
                skew_w.append(1.0)

        rl_curve = rl.Curve(
            nodes=nodes,
            id=cfg["reference_key"],
            convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
            **curve_interp_kwargs,
        )

        meeting_dates = sorted(k for k in nodes.keys())
        bflies = [butterfly(meeting_dates[i - 1], meeting_dates[i], meeting_dates[i + 1], cfg["reference_key"]) for i in range(1, len(meeting_dates) - 1)]
        rl_solver = rl.Solver(
            curves=[rl_curve],
            instruments=[curve_cls._build_pricable_for_curve(p, curve_key=cfg["reference_key"]) for p in base_pricers] + bflies,
            s=skew_s + [0.0] * len(bflies),
            id=curve_name,
            weights=skew_w + [1e-8] * len(bflies),
            func_tol=_func_tol,
            conv_tol=_conv_tol,
        )

        return rl_curve, rl_solver

    nodes = _build_stirf_nodes(
        timestamp=timestamp,
        pricers=pricers,
        central_bank_dates=_CENTRAL_BANK_DATES,
        reference_key=node_reference_key,
        max_tenor_from_timestamp_months=cfg["max_tenor_from_timestamp_months"],
        initial_nodes=initial_nodes,
    )
    nodes = _sort_nodes(nodes)
    nodes = curve_cls._ensure_mixed_support_nodes(nodes=nodes, cfg=cfg, base_date=timestamp.date())
    curve_interp_kwargs = curve_cls._curve_interp_kwargs(
        nodes=nodes,
        cfg=cfg,
        base_date=timestamp.date(),
        interpolation=interpolation,
    )

    rl_curve = rl.Curve(
        nodes=nodes,
        id=cfg["reference_key"],
        convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
        calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
        modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
        **curve_interp_kwargs,
    )

    instruments = [curve_cls._build_pricable_for_curve(p, curve_key=cfg["reference_key"]) for p in sorted_pricers]
    s = [p._rate for p in sorted_pricers]

    meeting_dates = sorted(k for k in nodes.keys())
    bflies = [butterfly(meeting_dates[i - 1], meeting_dates[i], meeting_dates[i + 1], cfg["reference_key"]) for i in range(1, len(meeting_dates) - 1)]
    pseudo_targets = [0.0] * len(bflies)

    instruments = instruments + bflies
    s = s + pseudo_targets
    weights = [1.0] * len(sorted_pricers) + [1e-8] * len(bflies)

    rl_solver = rl.Solver(
        curves=[rl_curve],
        instruments=instruments,
        s=s,
        id=curve_name,
        weights=weights,
        func_tol=_func_tol,
        conv_tol=_conv_tol,
    )

    return rl_curve, rl_solver


def _process_curve_calibration_job(
    curve_name: str,
    timestamp: datetime.datetime,
    cfg: Dict[str, Any],
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
    initial_nodes: Optional[Dict] = None,
    solver_tolerances: Optional[Dict[str, float]] = None,
) -> Tuple[datetime.datetime, rl.Curve]:
    with _suppress_solver_output():
        curve_obj, _ = _build_curve_from_pricers_core(
            curve_name=curve_name,
            timestamp=timestamp,
            cfg=cfg,
            pricers=pricers,
            initial_nodes=initial_nodes,
            solver_tolerances=solver_tolerances,
        )
    return timestamp, curve_obj


def _extract_nodes(curve: rl.Curve) -> Dict[pd.Timestamp, float]:
    """Extract calibrated node values from a solved rateslib Curve."""
    raw = curve.nodes._nodes if hasattr(curve.nodes, "_nodes") else dict(curve.nodes)
    return {k: float(v) for k, v in raw.items()}


def _float_signature(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return str(value)
    if math.isnan(numeric):
        return "nan"
    if math.isinf(numeric):
        return "inf" if numeric > 0 else "-inf"
    return repr(numeric)


def _date_signature(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except Exception:
        return str(value)


def _pricer_signature(pricer: "RLSTIRFuturePricer") -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int]:
    return (
        getattr(pricer, "_rl_stirf_id", None) or getattr(pricer, "_meta_data", {}).get("symbol", ""),
        _date_signature(getattr(pricer, "_effective_date", None)),
        _date_signature(getattr(pricer, "_maturity_date", None)),
        _float_signature(getattr(pricer, "_price", None)),
        _float_signature(getattr(pricer, "_rate", None)),
        int(getattr(pricer, "_contracts", 1) or 1),
    )


def _calibration_job_signature(
    pricers: Dict[str, List["RLSTIRFuturePricer"]],
) -> Tuple[Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int], ...]:
    return tuple(_pricer_signature(pricer) for pricer in _sort_pricers_for_solver(pricers))


def _curve_nodes_payload(curve: rl.Curve) -> Dict[str, float]:
    return {
        pd.Timestamp(node_ts).isoformat(): float(value)
        for node_ts, value in curve.nodes.nodes.items()
    }


def _split_chronological(
    jobs: List[Tuple[datetime.datetime, Any]],
    n_chunks: int,
) -> List[List[Tuple[datetime.datetime, Any]]]:
    """Split jobs into n_chunks contiguous chronological chunks for warm-start chains."""
    sorted_jobs = sorted(jobs, key=lambda x: x[0])
    if n_chunks <= 1 or len(sorted_jobs) <= 1:
        return [sorted_jobs]
    chunk_size = max(1, len(sorted_jobs) // n_chunks)
    chunks: List[List[Tuple[datetime.datetime, Any]]] = []
    for i in range(0, len(sorted_jobs), chunk_size):
        chunks.append(sorted_jobs[i : i + chunk_size])
    # Merge any tiny trailing chunk into the last real chunk
    if len(chunks) > n_chunks and chunks[-1]:
        chunks[-2].extend(chunks[-1])
        chunks.pop()
    return chunks


def _to_plot_bound(value: Optional[Union[str, datetime.date, datetime.datetime, pd.Timestamp]]) -> Optional[Union[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return rl.dt(value.year, value.month, value.day)
    return value


def _coerce_label_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None

    try:
        if isinstance(value, pd.Timestamp):
            return value

        if isinstance(value, datetime.datetime):
            return pd.Timestamp(value)

        if isinstance(value, datetime.date):
            return pd.Timestamp(datetime.datetime(value.year, value.month, value.day))

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            unit = "ms" if abs(float(value)) > 1e11 else "s"
            return pd.to_datetime(value, unit=unit, utc=True)

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            return pd.Timestamp(raw)
    except Exception:
        return None

    return None


def _extract_curve_timestamp_for_label(curve: Any) -> Optional[pd.Timestamp]:
    attr_candidates = (
        "timestamp",
        "as_of",
        "curve_timestamp",
        "timestamp_utc",
        "snapshot_timestamp",
        "pricing_timestamp",
    )
    for attr in attr_candidates:
        ts = _coerce_label_timestamp(getattr(curve, attr, None))
        if ts is not None:
            return ts

    for meta_attr in ("meta_data", "metadata", "_meta_data"):
        meta = getattr(curve, meta_attr, None)
        if isinstance(meta, dict):
            for key in ("timestamp", "as_of", "timestamp_utc", "curve_timestamp", "snapshotTs", "snapshot_ts"):
                ts = _coerce_label_timestamp(meta.get(key))
                if ts is not None:
                    return ts

    # Fallback to curve anchor date (first node) when no explicit snapshot ts exists.
    nodes = getattr(curve, "nodes", None)
    keys = getattr(nodes, "keys", None)
    if isinstance(keys, list) and keys:
        ts = _coerce_label_timestamp(keys[0])
        if ts is not None:
            return ts

    return None


def _format_label_timestamp(ts: pd.Timestamp) -> str:
    if ts.tzinfo is not None:
        ts = ts.tz_convert(pytz.timezone("America/New_York"))
        if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
            return ts.strftime("%Y-%m-%d")
        return ts.strftime("%Y-%m-%d %H:%M %Z")

    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _build_curve_default_label(curve: Any, idx: int) -> str:
    name_candidates = (
        getattr(curve, "actual_curve_name", None),
        getattr(curve, "curve_name", None),
        getattr(curve, "name", None),
        getattr(curve, "id", None),
    )
    base = ""
    for n in name_candidates:
        if n is None:
            continue
        s = str(n).strip()
        if s:
            base = s
            break
    if not base:
        base = f"curve_{idx+1}"

    ts = _extract_curve_timestamp_for_label(curve)
    if ts is None:
        return base

    return f"{base} ({_format_label_timestamp(ts)})"


def plot_overnight_forward_curves(
    curves: Sequence[rl.Curve],
    labels: Optional[Sequence[str]] = None,
    tenor: str = "1d",
    left: Optional[Union[str, datetime.date, datetime.datetime, pd.Timestamp]] = None,
    right: Optional[Union[str, datetime.date, datetime.datetime, pd.Timestamp]] = None,
    difference: bool = False,
    title: Optional[str] = None,
):
    """
    Overlay overnight forward curves from a list of rateslib curves on one figure.

    Parameters
    ----------
    curves
        Sequence of rateslib Curve objects.
    labels
        Optional labels matching `curves` length.
    tenor
        Forward tenor; defaults to "1d" for overnight forwards.
    left, right
        Optional plot bounds accepted by rateslib Curve.plot (tenor string or date-like).
    difference
        If True, plot comparator-minus-base differences.
    title
        Optional chart title.
    """
    curve_list = list(curves or [])
    if not curve_list:
        raise ValueError("`curves` must contain at least one rateslib curve.")

    for idx, curve in enumerate(curve_list):
        if not hasattr(curve, "plot"):
            raise TypeError(f"`curves[{idx}]` must be a rateslib curve-like object with `.plot()`, got {type(curve)}")

    if labels is None:
        auto_labels: List[str] = []
        for i, curve in enumerate(curve_list):
            auto_labels.append(_build_curve_default_label(curve, i))
        use_labels: Optional[List[str]] = auto_labels
    else:
        use_labels = [str(x) for x in labels]
        if len(use_labels) != len(curve_list):
            raise ValueError("`labels` length must match number of `curves`.")

    plot_kwargs: Dict[str, Any] = {
        "tenor": tenor,
        "difference": bool(difference),
    }
    left_bound = _to_plot_bound(left)
    right_bound = _to_plot_bound(right)
    if left_bound is not None:
        plot_kwargs["left"] = left_bound
    if right_bound is not None:
        plot_kwargs["right"] = right_bound
    if len(curve_list) > 1:
        plot_kwargs["comparators"] = curve_list[1:]
    if use_labels:
        plot_kwargs["labels"] = use_labels

    fig, ax, lines = curve_list[0].plot(**plot_kwargs)
    try:
        import matplotlib.dates as mdates
        import matplotlib.ticker as mticker

        # Increase major tick density so more x labels are shown.
        x_sample = None
        if lines:
            x_data = lines[0].get_xdata()
            if len(x_data):
                x_sample = x_data[0]

        is_date_axis = isinstance(x_sample, (datetime.date, datetime.datetime, pd.Timestamp))
        if is_date_axis:
            locator = mdates.AutoDateLocator(minticks=10, maxticks=20)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        else:
            ax.xaxis.set_major_locator(mticker.MaxNLocator(nbins=14, min_n_ticks=8))

        ax.tick_params(axis="x", labelrotation=45)
        fig.tight_layout()
    except Exception:
        pass

    if title:
        try:
            ax.set_title(title)
        except Exception:
            pass
    return fig, ax, lines


def build_rl_stirf_turn_flies(
    turn_nodes: List[Union[datetime.date, datetime.datetime]], curve_id: str, spec: str, one_step: Optional[bool] = False
) -> Dict[str, rl.Fly]:
    args = {"termination": "1d", "spec": spec, "curves": curve_id}

    rl_irs = [rl.IRS(effective=node, **args) for node in turn_nodes]
    flies = {}
    if len(rl_irs) < 3:
        return flies

    if one_step:
        for i in range(0, len(rl_irs) - 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly
    else:
        for i in range(3, len(rl_irs) - 2, 2):
            fly = rl.Fly(rl_irs[i], rl_irs[i + 1], rl_irs[i + 2])
            flies[f"{i}/{i+1}/{i+2}"] = fly

    return flies


class BARCHART_STIRF_CURVE(LayeredCacheMixin):
    _CURVE_CACHE_SCHEMA = 1
    _CURVE_CACHE_ATTR = "_barchart_stirf_curve_cache"
    _CURVE_CACHE_STEM = "BARCHART_STIRF-RL_CURVE_CACHE"
    L2_READ = False
    L2_WRITE = False

    # In-memory LRU for deserialized curves – avoids diskcache I/O + rl.from_json()
    # on repeated bulk fetches. Class-level so all instances share the same pool.
    _CURVE_MEM_CACHE: Dict[str, Any] = {}
    _CURVE_MEM_CACHE_LOCK = threading.Lock()
    _CURVE_MEM_CACHE_MAXSIZE = 100_000

    def __init__(self, curve_cache_dir: Optional[Union[str, Path]] = None):
        LayeredCacheMixin.__init__(self)
        self.stirf_mdp = STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")
        self.stirf_mdp_schwab_app = STIRFutureMDP(source="SCHWAB_APP_STIRF-RL")
        self.stirf_mdp_barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
        self._curve_cache_path = self._resolve_curve_cache_path(base_cache_dir=curve_cache_dir)
        self.open_cache(cache_attr=self._CURVE_CACHE_ATTR, path=self._curve_cache_path)

        # support mixed interpolation: https://quant.stackexchange.com/questions/81563/second-layer-instruments-in-rateslib
        self._STIRF_CURVE_CONFIGS = {
            "USD-SOFR-1D-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-SOFR-1D-Q16STIRT": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                    "SFRCM13",
                    "SFRCM14",
                    "SFRCM15",
                    "SFRCM16",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 48,
                "rl_irs_spec": "usd_irs",
            },
            "USD-SOFR-1D-Q20STIRT": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                    "SFRCM13",
                    "SFRCM14",
                    "SFRCM15",
                    "SFRCM16",
                    "SFRCM17",
                    "SFRCM18",
                    "SFRCM19",
                    "SFRCM20",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 60,
                "rl_irs_spec": "usd_irs",
            },
            "USD-SOFR-1D-Q12x3STIRT": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-SOFR-1D-Q12xM12STIRT": {
                "fetch_pricers_func": self.stirf_mdp.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
            },
            "USD-OIS-Q12xM11STIRT": {
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    # "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    # "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "usd_irs_lt_2y",
                "serff_skew": True,
            },
            "USD-OIS-Q12xM12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
                "serff_skew": True,
            },
            "USD-OIS-Q12xM12STIRT-SERFFX": {
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
                "serff_skew": True,
                "serff_skew_extrapolate": True,
                "serff_skew_extrap_roots": ["SR3"],
                "serff_skew_extrap_mode": "log-linear",
                "serff_skew_extrap_weight": 1e5,
            },
            "USD-OIS-Q12xM12STIRT-SERFFX-MIX23": { # main fomc swap curve
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
                "serff_skew": True,
                "serff_skew_extrapolate": True,
                "serff_skew_extrap_roots": ["SR3"],
                "serff_skew_extrap_mode": "flat",
                "serff_skew_extrap_min_years": 1.0,
                "serff_skew_extrap_weight": 1e3,
                "mixed_interpolation": True,
                "mixed_spline_start_years": 2.0,
                "mixed_spline_end_years": 3.0,
                "mixed_spline_tail_days": 120,
                "mixed_spline_drop_last_node": True,
                "mixed_spline_endpoints": ("natural", "natural"),
                "mixed_spline_add_boundary_nodes": True,
            },
            "USD-OIS-Q12xM12STIRT-MIX23": {
                "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
                "instruments": [
                    "SERCM1",
                    "SERCM2",
                    "SERCM3",
                    "SERCM4",
                    "SERCM5",
                    "SERCM6",
                    "SERCM7",
                    "SERCM8",
                    "SERCM9",
                    "SERCM10",
                    "SERCM11",
                    "SERCM12",
                    "FFCM1",
                    "FFCM2",
                    "FFCM3",
                    "FFCM4",
                    "FFCM5",
                    "FFCM6",
                    "FFCM7",
                    "FFCM8",
                    "FFCM9",
                    "FFCM10",
                    "FFCM11",
                    "FFCM12",
                    "SFRCM1",
                    "SFRCM2",
                    "SFRCM3",
                    "SFRCM4",
                    "SFRCM5",
                    "SFRCM6",
                    "SFRCM7",
                    "SFRCM8",
                    "SFRCM9",
                    "SFRCM10",
                    "SFRCM11",
                    "SFRCM12",
                ],
                "reference_key": "USD-OIS",
                "node_reference_key": "USD-FEDFUNDS",
                "sofr_reference_key": "USD-SOFR-1D",
                "max_tenor_from_timestamp_months": 36,
                "rl_irs_spec": "usd_irs_lt_2y",
                # Keep direct SER/FF anchoring on matched SR1 contracts only.
                "serff_skew": True,
                # Disable basis term-structure extrapolation into longer tenors.
                "serff_skew_extrapolate": False,
                "mixed_interpolation": True,
                "mixed_spline_start_years": 2.0,
                "mixed_spline_end_years": 3.0,
                "mixed_spline_tail_days": 120,
                "mixed_spline_drop_last_node": True,
                "mixed_spline_endpoints": ("natural", "natural"),
                "mixed_spline_add_boundary_nodes": True,
            },
            # "USD-OIS-Q12xM12STIRT-SERFFXCONST-MIX23": {
            #     "fetch_pricers_func": self.stirf_mdp_schwab_app.get_data,
            #     "fetch_pricers_bulk_func": self.stirf_mdp_schwab_app.get_bulk_data,
            #     "instruments": [
            #         "SERCM1",
            #         "SERCM2",
            #         "SERCM3",
            #         "SERCM4",
            #         "SERCM5",
            #         "SERCM6",
            #         "SERCM7",
            #         "SERCM8",
            #         "SERCM9",
            #         "SERCM10",
            #         "SERCM11",
            #         "SERCM12",
            #         "FFCM1",
            #         "FFCM2",
            #         "FFCM3",
            #         "FFCM4",
            #         "FFCM5",
            #         "FFCM6",
            #         "FFCM7",
            #         "FFCM8",
            #         "FFCM9",
            #         "FFCM10",
            #         "FFCM11",
            #         "FFCM12",
            #         "SFRCM1",
            #         "SFRCM2",
            #         "SFRCM3",
            #         "SFRCM4",
            #         "SFRCM5",
            #         "SFRCM6",
            #         "SFRCM7",
            #         "SFRCM8",
            #         "SFRCM9",
            #         "SFRCM10",
            #         "SFRCM11",
            #         "SFRCM12",
            #     ],
            #     "reference_key": "USD-OIS",
            #     "node_reference_key": "USD-FEDFUNDS",
            #     "sofr_reference_key": "USD-SOFR-1D",
            #     "max_tenor_from_timestamp_months": 36,
            #     "rl_irs_spec": "usd_irs_lt_2y",
            #     "serff_skew": True,
            #     "serff_skew_direct_sr1": False,
            #     "serff_skew_extrapolate": True,
            #     "serff_skew_extrap_roots": ["SR3"],
            #     # Flat extrapolation => longer tenors use the final SER/FF basis (CM12).
            #     "serff_skew_extrap_mode": "flat",
            #     "serff_skew_extrap_constant_from_last": True,
            #     "serff_skew_extrap_min_years": 1.0,
            #     "serff_skew_extrap_weight": 1e3,
            #     "mixed_interpolation": True,
            #     "mixed_spline_start_years": 2.0,
            #     "mixed_spline_end_years": 3.0,
            #     "mixed_spline_tail_days": 120,
            #     "mixed_spline_drop_last_node": True,
            #     "mixed_spline_endpoints": ("natural", "natural"),
            #     "mixed_spline_add_boundary_nodes": True,
            # },
            "EUR-ESTR-LONDON-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": [
                    "RACM1",
                    "RACM2",
                    "RACM3",
                    "RACM4",
                    "RACM5",
                    "RACM6",
                    "RACM7",
                    "RACM8",
                    "RACM9",
                    "RACM10",
                    "RACM11",
                    "RACM12",
                ],
                "reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
            },
            "EUR-ESTR-NYC-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": [
                    "EBCM1",
                    "EBCM2",
                    "EBCM3",
                    "EBCM4",
                    "EBCM5",
                    "EBCM6",
                    "EBCM7",
                    "EBCM8",
                    "EBCM9",
                    "EBCM10",
                    "EBCM11",
                    "EBCM12",
                ],
                "reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
            },
            # "EUR-ESTR-ICE-Q12xM12STIRT": {
            #     "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
            #     "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
            #     "instruments": _cm_instruments("IJ", 8) + _cm_instruments("EB"),
            #     "reference_key": "EUR-ESTR",
            #     "max_tenor_from_timestamp_months": 24,
            #     "rl_irs_spec": "eur_irs",
            # },
            "CAD-CORRA-Q8STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("RG", 8),
                "reference_key": "CAD-CORRA",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "cad_irs",
            },
            "GBP-SONIA-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                # "instruments": _cm_instruments("J8") + _cm_instruments("JU"),
                "instruments": _cm_instruments("J8"),
                "reference_key": "GBP-SONIA",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "gbp_irs",
            },
            "JPY-TONA-JPX-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("T0"),
                "reference_key": "JPY-TONA",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "jpy_irs",
            },
            "JPY-TONA-TFX-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("IT"),
                "reference_key": "JPY-TONA",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "jpy_irs",
            },
            "CHF-SARON-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("J2"),
                "reference_key": "CHF-SARON",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "chf_irs",
            },
            "EUR-EURIBOR-ICE-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("IM"),
                "reference_key": "EUR-EURIBOR-3M",
                "node_reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
                "interpolation": "linear_zero_rate",
            },
            "EUR-EURIBOR-EUREX-Q12STIRT": {
                "fetch_pricers_func": self.stirf_mdp_barchart.get_data,
                "fetch_pricers_bulk_func": self.stirf_mdp_barchart.get_bulk_data,
                "instruments": _cm_instruments("TV"),
                "reference_key": "EUR-EURIBOR-3M",
                "node_reference_key": "EUR-ESTR",
                "max_tenor_from_timestamp_months": 24,
                "rl_irs_spec": "eur_irs",
                "interpolation": "linear_zero_rate",
            },
        }

    @staticmethod
    def _resolve_curve_cache_path(base_cache_dir: Optional[Union[str, Path]] = None) -> str:
        if base_cache_dir:
            return str(Path(base_cache_dir).expanduser().resolve())

        arbs_cache_dir = os.getenv("ARBS_CACHE_DIR")
        if arbs_cache_dir:
            return str((Path(arbs_cache_dir) / "IRSwaps" / "BARCHART_STIRF" / "curve_cache").resolve())

        return LayeredCacheMixin.default_cache_path(BARCHART_STIRF_CURVE._CURVE_CACHE_STEM)

    @staticmethod
    def _curve_cfg_hash(cfg: Dict[str, Any]) -> str:
        cfg_blob = "|".join(
            [
                str(cfg.get("reference_key", "")),
                str(cfg.get("node_reference_key", cfg.get("reference_key", ""))),
                str(cfg.get("sofr_reference_key", "")),
                str(cfg.get("rl_irs_spec", "")),
                str(cfg.get("interpolation", "log_linear")),
                str(int(bool(cfg.get("serff_skew", False)))),
                str(int(bool(cfg.get("serff_skew_direct_sr1", True)))),
                str(int(bool(cfg.get("serff_skew_extrapolate", False)))),
                str(int(bool(cfg.get("serff_skew_extrap_constant_from_last", False)))),
                ",".join(str(x).upper() for x in cfg.get("serff_skew_extrap_roots", [])),
                str(cfg.get("serff_skew_extrap_mode", "linear")),
                str(cfg.get("serff_skew_extrap_min_years", "")),
                str(cfg.get("serff_skew_direct_weight", "")),
                str(cfg.get("serff_skew_extrap_weight", "")),
                str(int(bool(cfg.get("mixed_interpolation", False)))),
                str(cfg.get("mixed_spline_start_years", "")),
                str(cfg.get("mixed_spline_end_years", "")),
                str(cfg.get("mixed_spline_tail_days", "")),
                str(int(bool(cfg.get("mixed_spline_drop_last_node", False)))),
                ",".join(str(x) for x in cfg.get("mixed_spline_endpoints", ())),
                str(int(bool(cfg.get("mixed_spline_add_boundary_nodes", False)))),
                str(cfg.get("max_tenor_from_timestamp_months", "")),
                ",".join(str(x) for x in cfg.get("instruments", [])),
            ]
        )
        return hashlib.sha1(cfg_blob.encode()).hexdigest()[:16]

    @classmethod
    def _curve_cache_key(cls, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> str:
        ts_utc = timestamp.astimezone(pytz.utc).replace(microsecond=0)
        ts_str = ts_utc.strftime("%Y%m%dT%H%M%SZ")
        cfg_hash = cls._curve_cfg_hash(cfg)
        return re.sub(r"[^A-Za-z0-9_.-]", "_", f"v{cls._CURVE_CACHE_SCHEMA}_{curve_name}_{ts_str}_{cfg_hash}")

    @classmethod
    def _curve_cache_daily_bundle_key(cls, curve_name: str, date: datetime.date, cfg: Dict[str, Any]) -> str:
        cfg_hash = cls._curve_cfg_hash(cfg)
        return re.sub(r"[^A-Za-z0-9_.-]", "_", f"v{cls._CURVE_CACHE_SCHEMA}_BUNDLE_{curve_name}_{date.strftime('%Y%m%d')}_{cfg_hash}")

    def _curve_cache_mapping(self):
        self.open_cache(cache_attr=self._CURVE_CACHE_ATTR, path=self._curve_cache_path)
        return getattr(self, self._CURVE_CACHE_ATTR)

    @staticmethod
    def _attach_curve_context(curve: rl.Curve, *, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> rl.Curve:
        # Attach lightweight metadata used by downstream plotting/reporting helpers.
        try:
            curve.timestamp = timestamp
            curve.timestamp_utc = timestamp.astimezone(pytz.UTC)
            # Keep explicit human-readable names alongside rateslib `id` (which stays reference-key based).
            curve.curve_name = curve_name
            curve.name = curve_name
            curve.actual_curve_name = curve_name
            curve.reference_key = cfg.get("reference_key")
            curve.node_reference_key = cfg.get("node_reference_key", cfg.get("reference_key"))
        except Exception:
            pass
        return curve

    def _curve_from_bundle_nodes(
        self,
        *,
        curve_name: str,
        timestamp: datetime.datetime,
        cfg: Dict[str, Any],
        bundle_date: datetime.date,
        node_values: Dict[str, float],
    ) -> rl.Curve:
        raw_nodes = {pd.Timestamp(node_ts): float(v) for node_ts, v in node_values.items()}
        sorted_nodes = _sort_nodes({rl.dt(d.year, d.month, d.day): v for d, v in raw_nodes.items()})
        curve_obj = rl.Curve(
            nodes=sorted_nodes,
            id=cfg["reference_key"],
            convention=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["DayCounter"],
            calendar=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["Calendar"],
            modifier=RATESLIB_CURVE_DEFINITIONS[cfg["reference_key"]]["BusinessConvention"],
            **self._curve_interp_kwargs(
                nodes=sorted_nodes,
                cfg=cfg,
                base_date=bundle_date,
                interpolation=cfg.get("interpolation", "log_linear"),
            ),
        )
        curve_obj = self._attach_curve_context(
            curve_obj,
            curve_name=curve_name,
            timestamp=timestamp,
            cfg=cfg,
        )
        self._mem_cache_put(self._curve_cache_key(curve_name, timestamp, cfg), curve_obj)
        return curve_obj

    def _curve_cache_bundle_get(
        self,
        curve_name: str,
        timestamp: datetime.datetime,
        cfg: Dict[str, Any],
    ) -> Optional[rl.Curve]:
        bundle_date = self._trading_date_for_timestamp(timestamp)
        bundle_nodes = self._curve_cache_daily_bundle_get(curve_name, bundle_date, cfg)
        if not isinstance(bundle_nodes, dict):
            return None
        node_values = bundle_nodes.get(timestamp.isoformat())
        if not isinstance(node_values, dict):
            return None
        try:
            return self._curve_from_bundle_nodes(
                curve_name=curve_name,
                timestamp=timestamp,
                cfg=cfg,
                bundle_date=bundle_date,
                node_values=node_values,
            )
        except Exception:
            return None

    def _curve_cache_get(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any]) -> Optional[rl.Curve]:
        key = self._curve_cache_key(curve_name, timestamp, cfg)
        # Check in-memory cache first (avoids diskcache I/O + rl.from_json).
        mem_hit = self._CURVE_MEM_CACHE.get(key)
        if mem_hit is not None:
            return self._attach_curve_context(mem_hit, curve_name=curve_name, timestamp=timestamp, cfg=cfg)
        mapping = self._curve_cache_mapping()
        payload = mapping.get(key)
        if payload is None:
            return self._curve_cache_bundle_get(curve_name, timestamp, cfg)
        try:
            if isinstance(payload, str):
                curve_json = payload
            elif isinstance(payload, dict):
                curve_json = payload.get("curve_json")
            else:
                return self._curve_cache_bundle_get(curve_name, timestamp, cfg)
            if not curve_json:
                return self._curve_cache_bundle_get(curve_name, timestamp, cfg)
            curve = rl.from_json(curve_json)
            self._mem_cache_put(key, curve)
            return self._attach_curve_context(curve, curve_name=curve_name, timestamp=timestamp, cfg=cfg)
        except Exception:
            return self._curve_cache_bundle_get(curve_name, timestamp, cfg)

    def _curve_cache_put(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any], curve: rl.Curve) -> None:
        key = self._curve_cache_key(curve_name, timestamp, cfg)
        mapping = self._curve_cache_mapping()
        ts_utc = timestamp.astimezone(pytz.utc).replace(microsecond=0)
        mapping[key] = {
            "schema": self._CURVE_CACHE_SCHEMA,
            "curve_name": curve_name,
            "timestamp_utc": ts_utc.isoformat(),
            "curve_json": curve.to_json(),
        }
        self._mem_cache_put(key, curve)

    def _curve_cache_put_local(self, curve_name: str, timestamp: datetime.datetime, cfg: Dict[str, Any], curve: rl.Curve) -> None:
        """Persist a single curve to the local diskcache only, bypassing L2 writes."""
        key = self._curve_cache_key(curve_name, timestamp, cfg)
        mapping = self._curve_cache_mapping()
        l1_mapping = mapping.raw if hasattr(mapping, "raw") else mapping
        ts_utc = timestamp.astimezone(pytz.utc).replace(microsecond=0)
        l1_mapping[key] = {
            "schema": self._CURVE_CACHE_SCHEMA,
            "curve_name": curve_name,
            "timestamp_utc": ts_utc.isoformat(),
            "curve_json": curve.to_json(),
        }
        self._mem_cache_put(key, curve)

    def _mem_cache_put(self, key: str, curve) -> None:
        mem = self._CURVE_MEM_CACHE
        with self._CURVE_MEM_CACHE_LOCK:
            if len(mem) >= self._CURVE_MEM_CACHE_MAXSIZE:
                for k in list(islice(mem, self._CURVE_MEM_CACHE_MAXSIZE // 10)):
                    del mem[k]
            mem[key] = curve

    def _curve_cache_bulk_get(
        self,
        curve_name: str,
        timestamps: List[datetime.datetime],
        cfg: Dict[str, Any],
    ) -> Tuple[Dict[datetime.datetime, Any], List[datetime.datetime]]:
        """Bulk cache lookup with in-memory LRU + parallel disk reads.

        Returns (hits_dict, misses_list).
        """
        cfg_hash = self._curve_cfg_hash(cfg)
        schema = self._CURVE_CACHE_SCHEMA
        sanitize = re.compile(r"[^A-Za-z0-9_.-]")

        # Pre-generate all cache keys (cfg_hash computed once, not per-ts).
        keys: List[str] = []
        for ts in timestamps:
            ts_utc = ts.astimezone(pytz.utc).replace(microsecond=0)
            ts_str = ts_utc.strftime("%Y%m%dT%H%M%SZ")
            keys.append(sanitize.sub("_", f"v{schema}_{curve_name}_{ts_str}_{cfg_hash}"))

        hits: Dict[datetime.datetime, Any] = {}
        disk_needed: List[Tuple[str, datetime.datetime]] = []

        # Phase 1: in-memory cache lookups (instant).
        mem = self._CURVE_MEM_CACHE
        for key, ts in zip(keys, timestamps):
            cached = mem.get(key)
            if cached is not None:
                hits[ts] = self._attach_curve_context(cached, curve_name=curve_name, timestamp=ts, cfg=cfg)
            else:
                disk_needed.append((key, ts))

        if not disk_needed:
            return hits, []

        # Phase 2: parallel disk reads for cache misses.
        mapping = self._curve_cache_mapping()
        misses: List[datetime.datetime] = []

        def _read_one(item: Tuple[str, datetime.datetime]) -> Tuple[str, datetime.datetime, Any]:
            key, ts = item
            payload = mapping.get(key)
            if payload is None:
                return key, ts, None
            try:
                if isinstance(payload, str):
                    curve_json = payload
                elif isinstance(payload, dict):
                    curve_json = payload.get("curve_json")
                else:
                    return key, ts, None
                if not curve_json:
                    return key, ts, None
                return key, ts, rl.from_json(curve_json)
            except Exception:
                return key, ts, None

        n_workers = min(len(disk_needed), 8)
        if n_workers <= 1:
            results = [_read_one(item) for item in disk_needed]
        else:
            with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="curve-cache-read") as pool:
                results = list(pool.map(_read_one, disk_needed))

        with self._CURVE_MEM_CACHE_LOCK:
            for key, ts, curve in results:
                if curve is not None:
                    if len(mem) >= self._CURVE_MEM_CACHE_MAXSIZE:
                        for k in list(islice(mem, self._CURVE_MEM_CACHE_MAXSIZE // 10)):
                            del mem[k]
                    mem[key] = curve
                    hits[ts] = self._attach_curve_context(curve, curve_name=curve_name, timestamp=ts, cfg=cfg)
                else:
                    misses.append(ts)

        return hits, misses

    def _curve_cache_daily_bundle_get(
        self, curve_name: str, date: datetime.date, cfg: Dict[str, Any]
    ) -> Optional[Dict[datetime.datetime, Dict[pd.Timestamp, float]]]:
        """Fetch node values for an entire day from a single bundle entry."""
        key = self._curve_cache_daily_bundle_key(curve_name, date, cfg)
        mapping = self._curve_cache_mapping()
        payload = mapping.get(key)
        if not isinstance(payload, dict):
            return None
        return payload.get("nodes_by_ts")

    def _curve_cache_daily_bundle_put(
        self, curve_name: str, date: datetime.date, cfg: Dict[str, Any], curves_by_ts: Dict[datetime.datetime, rl.Curve]
    ) -> None:
        """Store node values for an entire day into a single local bundle entry."""
        key = self._curve_cache_daily_bundle_key(curve_name, date, cfg)
        mapping = self._curve_cache_daily_bundle_mapping()
        l1_mapping = mapping.raw if hasattr(mapping, "raw") else mapping

        # Extract nodes from all curves. Nodes keys are pd.Timestamp (dt) or rl.dt.
        # We store them as a nested dict: {ts_iso: {node_ts_iso: value}}
        nodes_by_ts: Dict[str, Dict[str, float]] = {}
        for ts, curve in curves_by_ts.items():
            ts_iso = ts.isoformat()
            ts_nodes = {}
            for node_ts, val in curve.nodes.nodes.items():
                node_ts_iso = pd.Timestamp(node_ts).isoformat()
                ts_nodes[node_ts_iso] = float(val)
            nodes_by_ts[ts_iso] = ts_nodes

        l1_mapping[key] = {
            "schema": self._CURVE_CACHE_SCHEMA,
            "curve_name": curve_name,
            "date": date.strftime("%Y-%m-%d"),
            "nodes_by_ts": nodes_by_ts,
        }

    def _curve_cache_daily_bundle_mapping(self):
        # Bundles go in the same diskcache path but we could separate them if needed.
        # For now, reuse the same mapping.
        return self._curve_cache_mapping()

    def _curve_store_write_day(
        self,
        curve_name: str,
        date: datetime.date,
        cfg: Dict[str, Any],
        curves_by_ts: Dict[datetime.datetime, rl.Curve],
    ) -> None:
        """Persist a bulk trading day once via CurveStore for day-block Supabase sync."""
        if not curves_by_ts:
            return

        from Caching.curve_store import CurveSnapshot, CurveStore

        cfg_hash = self._curve_cfg_hash(cfg)
        snapshots = [
            CurveSnapshot.from_rl_curve(curve, curve_name=curve_name, cfg=cfg, cfg_hash=cfg_hash)
            for _, curve in sorted(curves_by_ts.items())
        ]
        if not snapshots:
            return

        store = CurveStore.default()
        store.write_day(curve_name, date, snapshots, overwrite=True)

        try:
            from Caching.curve_analytics import (
                analytics_tenors_for_curve,
                build_analytics_frame,
                compute_analytics_row,
            )

            analytics_tenors = analytics_tenors_for_curve(curve_name)
            analytics_rows = [
                compute_analytics_row(
                    curve,
                    timestamp_utc=ts,
                    trading_date=date,
                    tenors=analytics_tenors,
                    curve_name=curve_name,
                )
                for ts, curve in sorted(curves_by_ts.items())
            ]
            analytics_df = build_analytics_frame(analytics_rows)
            if not analytics_df.empty:
                store.write_analytics_day(curve_name, date, analytics_df, overwrite=True)
        except Exception:
            pass

    def _persist_bulk_curves(
        self,
        *,
        curve_name: str,
        cfg: Dict[str, Any],
        out: Dict[datetime.datetime, Any],
        fresh_curves: Dict[datetime.datetime, rl.Curve],
        curve_only: bool,
    ) -> None:
        if not out:
            return

        curves_to_store_by_day: Dict[datetime.date, Dict[datetime.datetime, rl.Curve]] = {}
        for ts, val in out.items():
            curve_to_save = val if curve_only else val[0]
            if isinstance(curve_to_save, rl.Curve):
                curves_to_store_by_day.setdefault(self._trading_date_for_timestamp(ts), {})[ts] = curve_to_save

        fresh_curves_by_day: Dict[datetime.date, Dict[datetime.datetime, rl.Curve]] = {}
        for ts, curve_obj in fresh_curves.items():
            fresh_curves_by_day.setdefault(self._trading_date_for_timestamp(ts), {})[ts] = curve_obj

        for dt, day_curves in curves_to_store_by_day.items():
            try:
                self._curve_store_write_day(curve_name, dt, cfg, day_curves)
            except Exception:
                pass

            if len(day_curves) > 10:
                try:
                    self._curve_cache_daily_bundle_put(curve_name, dt, cfg, day_curves)
                except Exception:
                    pass
                continue

            for ts, curve_obj in fresh_curves_by_day.get(dt, {}).items():
                self._curve_cache_put_local(curve_name, ts, cfg, curve_obj)

    @staticmethod
    def _pricer_symbol(pricer: "RLSTIRFuturePricer") -> str:
        sym = getattr(pricer, "_rl_stirf_id", None) or getattr(pricer, "_meta_data", {}).get("symbol", "")
        return str(sym).strip().upper().replace("/", "")

    @classmethod
    def _pricer_root_and_code(cls, pricer: "RLSTIRFuturePricer") -> Optional[Tuple[str, str]]:
        m = _STIR_ROOT_CODE_RE.match(cls._pricer_symbol(pricer))
        if not m:
            return None

        root, code = m.group(1).upper(), m.group(2).upper()
        root = {"SER": "SR1", "SL": "SR1", "SFR": "SR3", "SQ": "SR3", "FF": "ZQ"}.get(root, root)
        return root, code

    @staticmethod
    def _tenor_years(start_date: datetime.date, end_date: Optional[datetime.date]) -> Optional[float]:
        if end_date is None:
            return None
        days = (end_date - start_date).days
        if days <= 0:
            return None
        return float(days) / 365.25

    @staticmethod
    def _serff_basis_interp(tenor_years: float, points: Sequence[Tuple[float, float]], extrap_mode: str = "linear") -> Optional[float]:
        if tenor_years <= 0.0 or not points:
            return None

        sorted_points = sorted(points, key=lambda kv: kv[0])
        if len(sorted_points) == 1:
            return float(sorted_points[0][1])

        mode = str(extrap_mode or "linear").strip().lower().replace("_", "-")
        use_log_tenor = mode == "log-linear"

        def _x(v: float) -> float:
            if use_log_tenor:
                if v <= 0.0:
                    return 0.0
                return float(math.log(v))
            return float(v)

        def _interp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
            if x1 == x0:
                return float(y1)
            return float(y0 + (x - x0) * (y1 - y0) / (x1 - x0))

        x_query = _x(float(tenor_years))

        if tenor_years <= sorted_points[0][0]:
            x0, y0 = sorted_points[0]
            x1, y1 = sorted_points[1]
            if mode == "flat":
                return float(y0)
            return _interp(x_query, _x(x0), y0, _x(x1), y1)

        for i in range(1, len(sorted_points)):
            x1, y1 = sorted_points[i]
            if tenor_years <= x1:
                x0, y0 = sorted_points[i - 1]
                return _interp(x_query, _x(x0), y0, _x(x1), y1)

        x0, y0 = sorted_points[-2]
        x1, y1 = sorted_points[-1]
        if mode == "flat":
            return float(y1)
        return _interp(x_query, _x(x0), y0, _x(x1), y1)

    @classmethod
    def _build_serff_basis_points(
        cls,
        *,
        base_date: datetime.date,
        ser_pricers_by_code: Dict[str, "RLSTIRFuturePricer"],
        ff_pricers_by_code: Dict[str, "RLSTIRFuturePricer"],
    ) -> List[Tuple[float, float]]:
        points_by_tenor: Dict[float, float] = {}
        for code, ser_pricer in ser_pricers_by_code.items():
            ff_pricer = ff_pricers_by_code.get(code)
            if ff_pricer is None:
                continue

            tenor_years = cls._tenor_years(base_date, getattr(ser_pricer, "_maturity_date", None))
            if tenor_years is None:
                continue

            points_by_tenor[tenor_years] = float(ser_pricer._price - ff_pricer._price)

        return sorted(points_by_tenor.items(), key=lambda kv: kv[0])

    @staticmethod
    def _coerce_date(value: Any) -> Optional[datetime.date]:
        if isinstance(value, pd.Timestamp):
            value = value.to_pydatetime()
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return None

    @staticmethod
    def _date_to_rl_dt(d: datetime.date):
        return rl.dt(d.year, d.month, d.day)

    @staticmethod
    def _mixed_spline_window_dates(
        *,
        base_date: datetime.date,
        start_years: float,
        end_years: float,
        tail_days: int = 0,
    ) -> Optional[Tuple[datetime.date, datetime.date]]:
        if end_years <= start_years:
            return None
        start_months = int(round(start_years * 12.0))
        end_months = int(round(end_years * 12.0))
        spline_left = (pd.Timestamp(base_date) + DateOffset(months=start_months)).date()
        spline_right = (pd.Timestamp(base_date) + DateOffset(months=end_months)).date() + datetime.timedelta(days=max(0, int(tail_days)))
        if spline_right <= spline_left:
            return None
        return spline_left, spline_right

    @classmethod
    def _ensure_mixed_support_nodes(
        cls,
        *,
        nodes: Dict[Any, Any],
        cfg: Dict[str, Any],
        base_date: datetime.date,
    ) -> Dict[Any, Any]:
        if not bool(cfg.get("mixed_interpolation", False)):
            return nodes
        if not bool(cfg.get("mixed_spline_add_boundary_nodes", True)):
            return nodes

        out = dict(nodes)
        start_years = float(cfg.get("mixed_spline_start_years", 2.0))
        end_years = float(cfg.get("mixed_spline_end_years", 3.0))
        tail_days = int(cfg.get("mixed_spline_tail_days", 0) or 0)
        drop_last_node = bool(cfg.get("mixed_spline_drop_last_node", True))
        endpoints_cfg = cfg.get("mixed_spline_endpoints", ("natural", "natural"))
        if isinstance(endpoints_cfg, (list, tuple)) and len(endpoints_cfg) == 2:
            endpoints = (str(endpoints_cfg[0]), str(endpoints_cfg[1]))
        else:
            endpoints = ("natural", "natural")

        def _solvable(node_map: Dict[Any, Any]) -> bool:
            t_knots = cls._build_mixed_spline_t(
                node_dates=list(node_map.keys()),
                base_date=base_date,
                start_years=start_years,
                end_years=end_years,
                tail_days=tail_days,
                drop_last_node=drop_last_node,
            )
            if t_knots is None:
                return False
            return cls._mixed_t_is_solvable(node_dates=list(node_map.keys()), t_knots=t_knots, endpoints=endpoints)

        if _solvable(out):
            return _sort_nodes(out)

        window_no_tail = cls._mixed_spline_window_dates(base_date=base_date, start_years=start_years, end_years=end_years, tail_days=0)
        window = cls._mixed_spline_window_dates(base_date=base_date, start_years=start_years, end_years=end_years, tail_days=tail_days)
        if window is None:
            return _sort_nodes(out)

        left_date, right_date = window
        candidate_dates: List[datetime.date] = [left_date]
        if window_no_tail is not None:
            candidate_dates.append(window_no_tail[1])
        candidate_dates.append(right_date)

        for d in candidate_dates:
            out.setdefault(cls._date_to_rl_dt(d), 1.0)
            if _solvable(out):
                break

        return _sort_nodes(out)

    @classmethod
    def _build_mixed_spline_t(
        cls,
        *,
        node_dates: Sequence[Any],
        base_date: datetime.date,
        start_years: float,
        end_years: float,
        tail_days: int = 0,
        drop_last_node: bool = True,
    ) -> Optional[List[Any]]:
        if end_years <= start_years:
            return None

        clean_nodes = sorted({d for d in (cls._coerce_date(x) for x in node_dates) if d is not None})
        if not clean_nodes:
            return None

        window = cls._mixed_spline_window_dates(base_date=base_date, start_years=start_years, end_years=end_years, tail_days=tail_days)
        if window is None:
            return None
        spline_left, spline_right = window

        if spline_left < clean_nodes[0]:
            spline_left = clean_nodes[0]
        if spline_right <= spline_left:
            return None

        interior_dates = [d for d in clean_nodes if d > spline_left and d < spline_right]
        # Mirror medium-term mixed-curve practice: hold one terminal node outside spline knots.
        if drop_last_node and len(interior_dates) >= 1:
            interior_dates = interior_dates[:-1]
        interior = [cls._date_to_rl_dt(d) for d in interior_dates]
        left = cls._date_to_rl_dt(spline_left)
        right = cls._date_to_rl_dt(spline_right)

        return [left, left, left, left] + interior + [right, right, right, right]

    @classmethod
    def _mixed_t_is_solvable(
        cls,
        *,
        node_dates: Sequence[Any],
        t_knots: Sequence[Any],
        endpoints: Tuple[str, str],
    ) -> bool:
        if len(t_knots) < 8:
            return False

        clean_nodes = sorted(d for d in (cls._coerce_date(x) for x in node_dates) if d is not None)
        if not clean_nodes:
            return False

        left_date = cls._coerce_date(t_knots[0])
        if left_date is None:
            return False

        nodes_ge_left = sum(1 for d in clean_nodes if d >= left_date)
        t_len = len(t_knots)
        tau_extra = 0

        left_ep = str(endpoints[0]).lower()
        right_ep = str(endpoints[1]).lower()
        if left_ep == "natural":
            tau_extra += 1
        elif left_ep == "not_a_knot":
            t_len -= 1
        else:
            return False

        if right_ep == "natural":
            tau_extra += 1
        elif right_ep == "not_a_knot":
            t_len -= 1
        else:
            return False

        n = t_len - 4
        if n <= 0:
            return False

        return (nodes_ge_left + tau_extra) >= n

    @classmethod
    def _curve_interp_kwargs(
        cls,
        *,
        nodes: Dict[Any, Any],
        cfg: Dict[str, Any],
        base_date: datetime.date,
        interpolation: str,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"interpolation": interpolation}
        if not bool(cfg.get("mixed_interpolation", False)):
            return kwargs

        start_years = float(cfg.get("mixed_spline_start_years", 2.0))
        end_years = float(cfg.get("mixed_spline_end_years", 3.0))
        tail_days = int(cfg.get("mixed_spline_tail_days", 0) or 0)
        drop_last_node = bool(cfg.get("mixed_spline_drop_last_node", True))
        t_knots = cls._build_mixed_spline_t(
            node_dates=list(nodes.keys()),
            base_date=base_date,
            start_years=start_years,
            end_years=end_years,
            tail_days=tail_days,
            drop_last_node=drop_last_node,
        )
        if t_knots is None:
            return kwargs

        endpoints_cfg = cfg.get("mixed_spline_endpoints", ("natural", "natural"))
        if isinstance(endpoints_cfg, (list, tuple)) and len(endpoints_cfg) == 2:
            endpoints = (str(endpoints_cfg[0]), str(endpoints_cfg[1]))
        else:
            endpoints = ("natural", "natural")

        if not cls._mixed_t_is_solvable(node_dates=list(nodes.keys()), t_knots=t_knots, endpoints=endpoints):
            return kwargs

        kwargs["t"] = t_knots
        kwargs["endpoints"] = endpoints
        return kwargs

    @classmethod
    def _build_pricable_for_curve(cls, pricer: "RLSTIRFuturePricer", curve_key: str) -> rl.STIRFuture:
        root_and_code = cls._pricer_root_and_code(pricer)
        is_ser = bool(root_and_code and root_and_code[0] == "SR1")
        if root_and_code and root_and_code[0] in {"RA", "EB"}:
            spec = "eur_stir"
        elif root_and_code and root_and_code[0] == "IJ":
            spec = "eur_stir1"
        else:
            spec_key = "ReferenceRate3" if is_ser else "ReferenceRate2"
            spec = RATESLIB_CURVE_DEFINITIONS[curve_key].get(spec_key, RATESLIB_CURVE_DEFINITIONS[curve_key]["ReferenceRate"])

        meta = getattr(pricer, "_meta_data", {}) or {}
        kwargs = {
            "effective": rl.dt(pricer._effective_date.year, pricer._effective_date.month, pricer._effective_date.day),
            "termination": rl.dt(pricer._maturity_date.year, pricer._maturity_date.month, pricer._maturity_date.day),
            "spec": spec,
            "price": float(pricer._price),
            "contracts": int(getattr(pricer, "_contracts", 1) or 1),
            "curves": curve_key,
        }
        if is_ser and meta.get("fixings") is not None:
            kwargs["leg2_fixings"] = meta["fixings"]

        return rl.STIRFuture(**kwargs)

    @staticmethod
    def _normalize_timestamp(timestamp: Union[datetime.datetime, pd.Timestamp, str]) -> datetime.datetime:
        if isinstance(timestamp, str) and timestamp.lower() == "live":
            return datetime.datetime.now(tz=pytz.timezone("America/New_York"))

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        assert isinstance(timestamp, datetime.datetime), "timestamp must be datetime.datetime, pd.Timestamp, or 'live'"
        assert timestamp.tzinfo is not None and timestamp.tzinfo.utcoffset(timestamp) is not None, "timestamp must be timezone aware"
        assert timestamp.astimezone(pytz.utc) < datetime.datetime.now(tz=pytz.utc), "timestamp cannot be in the future"
        return timestamp

    @staticmethod
    def _cme_session_open_chi(timestamp: datetime.datetime) -> datetime.datetime:
        chi = pytz.timezone("America/Chicago")
        ts_chi = timestamp.astimezone(chi)
        session_open = ts_chi.replace(hour=17, minute=0, second=0, microsecond=0)
        if ts_chi < session_open:
            session_open = session_open - datetime.timedelta(days=1)
        return session_open

    @staticmethod
    def _trading_date_for_timestamp(timestamp: datetime.datetime) -> datetime.date:
        chi = pytz.timezone("America/Chicago")
        ts_chi = timestamp.astimezone(chi)
        if ts_chi.hour >= 17:
            return (ts_chi + datetime.timedelta(days=1)).date()
        return ts_chi.date()

    @staticmethod
    def _is_live_request(timestamp: Any) -> bool:
        return isinstance(timestamp, str) and timestamp.lower() == "live"

    @staticmethod
    def _is_usd_curve(cfg: Dict[str, Any]) -> bool:
        return str(cfg.get("reference_key", "")).upper().startswith("USD-")

    @staticmethod
    def _timestamp_to_date(timestamp: Any) -> datetime.date:
        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()

        if isinstance(timestamp, datetime.date):
            return timestamp

        if isinstance(timestamp, str):
            if timestamp.lower() == "live":
                return datetime.datetime.now(tz=pytz.timezone("America/New_York")).date()
            return pd.Timestamp(timestamp).date()

        return datetime.datetime.now(tz=pytz.timezone("America/New_York")).date()

    @staticmethod
    def _has_any_pricers(pricers: Optional[Dict[str, List[RLSTIRFuturePricer]]]) -> bool:
        if not pricers:
            return False
        return any(bool(lst) for lst in pricers.values())

    def _fetch_non_usd_live_with_latest_fallback(self, request: Dict[str, Any]) -> Dict[str, List[RLSTIRFuturePricer]]:
        # Barchart "live" intraday can be empty outside active prints. Fall back to
        # the most recent business-day snapshot.
        last_error: Optional[Exception] = None
        live_req = dict(request)
        live_req["timestamp"] = "live"

        try:
            live_pricers = self.stirf_mdp_barchart.get_data(request=live_req)
            if self._has_any_pricers(live_pricers):
                return live_pricers
        except Exception as exc:
            last_error = exc

        anchor_date = self._timestamp_to_date(request.get("timestamp"))
        business_days_checked = 0
        days_back = 0
        max_business_day_lookback = 10
        while business_days_checked < max_business_day_lookback:
            candidate = anchor_date - datetime.timedelta(days=days_back)
            days_back += 1

            if candidate.weekday() >= 5:
                continue

            business_days_checked += 1
            fallback_req = dict(request)
            fallback_req["timestamp"] = candidate
            try:
                fallback_pricers = self.stirf_mdp_barchart.get_data(request=fallback_req)
                if self._has_any_pricers(fallback_pricers):
                    return fallback_pricers
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise RuntimeError("Barchart live fetch returned no data and latest-available fallback failed.") from last_error
        raise RuntimeError("Barchart live fetch returned no data and latest-available fallback produced no instruments.")

    def _resolve_fetchers_for_request(
        self,
        *,
        cfg: Dict[str, Any],
        is_live_request: bool,
    ) -> Tuple[Any, Optional[Any]]:
        def _is_schwab_fetcher(fetcher: Any) -> bool:
            return getattr(fetcher, "__self__", None) is self.stirf_mdp_schwab_app

        if not is_live_request:
            # return cfg["fetch_pricers_func"], cfg.get("fetch_pricers_bulk_func", None)
            # Some USD curve configs use SCHWAB fetchers for live mode quality.
            # Historical/as-of timestamps must stay on the non-SCHWAB pipeline.
            fetch_pricers_func = cfg["fetch_pricers_func"]
            fetch_pricers_bulk_func = cfg.get("fetch_pricers_bulk_func", None)
            if self._is_usd_curve(cfg) and _is_schwab_fetcher(fetch_pricers_func):
                return self.stirf_mdp.get_data, self.stirf_mdp.get_bulk_data

            return fetch_pricers_func, fetch_pricers_bulk_func

        if self._is_usd_curve(cfg):
            return self.stirf_mdp_schwab_app.get_data, self.stirf_mdp_schwab_app.get_bulk_data

        return self._fetch_non_usd_live_with_latest_fallback, None

    def _build_curve_from_pricers(
        self,
        *,
        curve_name: str,
        timestamp: datetime.datetime,
        cfg: Dict[str, Any],
        pricers: Dict[str, List[RLSTIRFuturePricer]],
        initial_nodes: Optional[Dict] = None,
        solver_tolerances: Optional[Dict[str, float]] = None,
    ) -> Tuple[rl.Curve, rl.Solver]:
        return _build_curve_from_pricers_core(
            curve_name=curve_name,
            timestamp=timestamp,
            cfg=cfg,
            pricers=pricers,
            initial_nodes=initial_nodes,
            solver_tolerances=solver_tolerances,
        )

    def _get_primed_session_df(
        self,
        timestamp: datetime.datetime,
        cfg: Dict[str, Any],
    ) -> Optional[pd.DataFrame]:
        """Retrieve the full-session DataFrame cached during priming, if available."""
        session_key = self._cme_session_open_chi(timestamp).isoformat()
        mdp = self.stirf_mdp
        return mdp._session_dfs.get(session_key)

    def _calibrate_chunk(
        self,
        *,
        chunk: List[Tuple[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]]],
        curve_name: str,
        cfg: Dict[str, Any],
        solver_tolerances: Optional[Dict[str, float]] = None,
        curve_only: bool = True,
    ) -> Dict[datetime.datetime, Any]:
        """Calibrate a chronological chunk with warm-starting from previous curve's nodes."""
        results: Dict[datetime.datetime, Any] = {}
        prior_nodes: Optional[Dict] = None
        for ts, ts_pricers in chunk:
            with _suppress_solver_output():
                curve_obj, solver_obj = self._build_curve_from_pricers(
                    curve_name=curve_name,
                    timestamp=ts,
                    cfg=cfg,
                    pricers=ts_pricers,
                    initial_nodes=prior_nodes,
                    solver_tolerances=solver_tolerances,
                )
            prior_nodes = _extract_nodes(curve_obj)
            curve_obj = self._attach_curve_context(curve_obj, curve_name=curve_name, timestamp=ts, cfg=cfg)
            self._mem_cache_put(self._curve_cache_key(curve_name, ts, cfg), curve_obj)
            results[ts] = curve_obj if curve_only else (curve_obj, solver_obj)
        return results

    def build_curve(
        self,
        curve_name: str,
        timestamp: Union[datetime.datetime, pd.Timestamp, str, Sequence[Union[datetime.datetime, pd.Timestamp]]],
        kwargs: Optional[Dict[str, Any]] = None,
        curve_only: bool = True,
    ) -> Union[
        rl.Curve,
        Tuple[rl.Curve, rl.Solver],
        Dict[datetime.datetime, rl.Curve],
        Dict[datetime.datetime, Tuple[rl.Curve, rl.Solver]],
    ]:
        if kwargs is None:
            kwargs = {}

        assert curve_name in self._STIRF_CURVE_CONFIGS, f"{curve_name} not defined in configs"
        cfg = self._STIRF_CURVE_CONFIGS[curve_name]

        is_bulk = isinstance(timestamp, Sequence) and not isinstance(timestamp, (str, bytes, datetime.datetime))
        if is_bulk:
            raw_timestamps = list(timestamp)
            assert raw_timestamps, "timestamp list is empty"
            normalized_timestamps = [self._normalize_timestamp(ts) for ts in raw_timestamps]
            live_by_timestamp: Dict[datetime.datetime, bool] = {}
            for raw_ts, norm_ts in zip(raw_timestamps, normalized_timestamps):
                is_live_ts = self._is_live_request(raw_ts)
                live_by_timestamp[norm_ts] = bool(live_by_timestamp.get(norm_ts, False) or is_live_ts)
            local_kwargs = dict(kwargs)
            calibration_executor = str(local_kwargs.pop("calibration_executor", "thread") or "thread").strip().lower()
            if calibration_executor not in _CALIBRATION_EXECUTORS:
                raise ValueError(
                    f"Unsupported calibration_executor '{calibration_executor}'. "
                    f"Expected one of {sorted(_CALIBRATION_EXECUTORS)}."
                )
            if calibration_executor == "process":
                if not curve_only:
                    raise ValueError("Process-pool calibration only supports curve_only=True for bulk historical runs.")
                if any(live_by_timestamp.values()):
                    raise ValueError("Process-pool calibration only supports bulk historical runs, not live timestamps.")
            show_tqdm = bool(local_kwargs.pop("show_tqdm", True))
            auto_prime_bulk = bool(local_kwargs.pop("auto_prime_bulk", True))
            stirf_fetch_max_workers = local_kwargs.pop("stirf_fetch_max_workers", None)
            calibration_max_workers = local_kwargs.pop("calibration_max_workers", None)
            force_refresh = bool(local_kwargs.get("force_refresh", False))
            use_curve_cache = bool(curve_only) and not force_refresh

            # Deduplicate normalized timestamps.
            seen_ts: Set[datetime.datetime] = set()
            unique_timestamps: List[datetime.datetime] = []
            for ts in normalized_timestamps:
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    unique_timestamps.append(ts)

            # Seed output from curve-cache (bulk: in-memory LRU + parallel disk reads).
            out: Dict[datetime.datetime, Any] = {}
            if use_curve_cache:
                # --- [OPTIMIZATION] Check Daily Bundles first ---
                by_date: Dict[datetime.date, List[datetime.datetime]] = {}
                for ts in unique_timestamps:
                    by_date.setdefault(self._trading_date_for_timestamp(ts), []).append(ts)

                remaining_unique_timestamps: List[datetime.datetime] = []
                for dt, d_timestamps in by_date.items():
                    bundle_nodes = self._curve_cache_daily_bundle_get(curve_name, dt, cfg)
                    if bundle_nodes is not None:
                        for ts in d_timestamps:
                            ts_iso = ts.isoformat()
                            node_values = bundle_nodes.get(ts_iso)
                            if node_values is not None:
                                curve_obj = self._curve_from_bundle_nodes(
                                    curve_name=curve_name,
                                    timestamp=ts,
                                    cfg=cfg,
                                    bundle_date=dt,
                                    node_values=node_values,
                                )
                                out[ts] = curve_obj if curve_only else (curve_obj, None)
                                continue
                            remaining_unique_timestamps.append(ts)
                    else:
                        remaining_unique_timestamps.extend(d_timestamps)
                
                # Check individual cache for anything not in bundles.
                if remaining_unique_timestamps:
                    hits, misses = self._curve_cache_bulk_get(curve_name, remaining_unique_timestamps, cfg)
                    out.update(hits)
                    pending_timestamps = misses
                else:
                    pending_timestamps = []
            else:
                pending_timestamps = list(unique_timestamps)

            if not pending_timestamps:
                return out

            tqdm_mod = None
            if show_tqdm:
                try:
                    import tqdm as tqdm_mod  # type: ignore[no-redef]
                except Exception:
                    tqdm_mod = None

            # Phase 1: optional auto-prime to minimize Barchart calls on bulk runs.
            primed_dfs: Dict[str, pd.DataFrame] = {}
            if auto_prime_bulk:
                prime_kwargs = dict(local_kwargs)
                prime_kwargs["cache_full_intraday_fetch"] = bool(prime_kwargs.get("cache_full_intraday_fetch", True))
                prime_kwargs.setdefault("show_tqdm", False)

                session_rep_timestamps: List[datetime.datetime] = []
                seen_sessions: Set[datetime.datetime] = set()
                for ts in pending_timestamps:
                    session_open = self._cme_session_open_chi(ts)
                    if session_open not in seen_sessions:
                        seen_sessions.add(session_open)
                        session_rep_timestamps.append(ts)

                prime_iter: Iterable[datetime.datetime] = session_rep_timestamps
                if tqdm_mod is not None and len(session_rep_timestamps) > 1:
                    prime_iter = tqdm_mod.tqdm(session_rep_timestamps, desc=f"PRIMING {curve_name} STIR CACHE")

                primed_dfs: Dict[str, pd.DataFrame] = {}
                for ts_prime in prime_iter:
                    prime_req = dict(symbols=cfg["instruments"], timestamp=ts_prime, **prime_kwargs)
                    fetch_pricers_func, _ = self._resolve_fetchers_for_request(
                        cfg=cfg,
                        is_live_request=bool(live_by_timestamp.get(ts_prime, False)),
                    )
                    fetch_pricers_func(request=prime_req)
                    # Capture the full session DataFrame for fast bulk lookup
                    session_key = self._cme_session_open_chi(ts_prime).isoformat()
                    cached_df = self._get_primed_session_df(ts_prime, cfg)
                    if cached_df is not None:
                        primed_dfs[session_key] = cached_df

            # Phase 2: fetch STIR pricers for all requested timestamps (prefer cache).
            pricers_by_ts: Dict[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]] = {}
            fetch_pricers_bulk_func = None
            live_modes = {bool(live_by_timestamp.get(ts, False)) for ts in pending_timestamps}
            if len(live_modes) == 1:
                _, fetch_pricers_bulk_func = self._resolve_fetchers_for_request(
                    cfg=cfg,
                    is_live_request=next(iter(live_modes)),
                )
            if fetch_pricers_bulk_func is not None:
                bulk_kwargs = dict(local_kwargs)
                if auto_prime_bulk:
                    bulk_kwargs["force_refresh"] = False
                    bulk_kwargs["cache_full_intraday_fetch"] = True
                    if "max_workers" not in bulk_kwargs:
                        bulk_kwargs["max_workers"] = int(stirf_fetch_max_workers or 1)
                elif stirf_fetch_max_workers is not None and "max_workers" not in bulk_kwargs:
                    bulk_kwargs["max_workers"] = int(stirf_fetch_max_workers)

                bulk_req = dict(symbols=cfg["instruments"], timestamps=pending_timestamps,
                                primed_session_data=primed_dfs or None, **bulk_kwargs)
                pricers_by_ts = fetch_pricers_bulk_func(request=bulk_req)

            calibration_jobs: List[Tuple[datetime.datetime, Dict[str, List[RLSTIRFuturePricer]]]] = []
            duplicate_timestamps_by_canonical: Dict[datetime.datetime, List[datetime.datetime]] = {}
            canonical_timestamp_by_signature: Dict[
                Tuple[Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int], ...],
                datetime.datetime,
            ] = {}
            for ts in pending_timestamps:
                ts_pricers = pricers_by_ts.get(ts, None)
                if ts_pricers is None:
                    fetch_kwargs = dict(local_kwargs)
                    if auto_prime_bulk:
                        fetch_kwargs["force_refresh"] = False
                        fetch_kwargs["cache_full_intraday_fetch"] = True
                    pricer_req = dict(symbols=cfg["instruments"], timestamp=ts, **fetch_kwargs)
                    fetch_pricers_func, _ = self._resolve_fetchers_for_request(
                        cfg=cfg,
                        is_live_request=bool(live_by_timestamp.get(ts, False)),
                    )
                    ts_pricers = fetch_pricers_func(request=pricer_req)
                signature = _calibration_job_signature(ts_pricers)
                canonical_ts = canonical_timestamp_by_signature.get(signature)
                if canonical_ts is None:
                    canonical_timestamp_by_signature[signature] = ts
                    duplicate_timestamps_by_canonical[ts] = []
                    calibration_jobs.append((ts, ts_pricers))
                    continue
                duplicate_timestamps_by_canonical.setdefault(canonical_ts, []).append(ts)

            # Phase 3: parallel curve calibrations with warm-start chains + tqdm progress.
            cal_workers = int(calibration_max_workers or len(calibration_jobs))
            cal_workers = max(1, min(cal_workers, len(calibration_jobs)))
            fresh_curves: Dict[datetime.datetime, rl.Curve] = {}

            # Relaxed tolerances for bulk timeseries calibration.
            bulk_solver_tolerances = {"func_tol": 1e-3, "conv_tol": 1e-3}

            _emit_calibration_status(
                curve_name=curve_name,
                executor_mode="thread-warmstart",
                workers=cal_workers,
                jobs=len(calibration_jobs),
                show_tqdm=show_tqdm,
                tqdm_mod=tqdm_mod,
            )

            if calibration_executor == "process":
                # Process pool: no warm-start possible (kept as escape hatch).
                reduced_cfg = _reduced_calibration_cfg(cfg)
                _validate_spawn_process_pool_environment()
                with ProcessPoolExecutor(
                    max_workers=cal_workers,
                    mp_context=mp.get_context("spawn"),
                ) as pool:
                    futures = {
                        pool.submit(
                            _process_curve_calibration_job,
                            curve_name,
                            ts,
                            reduced_cfg,
                            ts_pricers,
                            None,  # no warm-start
                            bulk_solver_tolerances,
                        ): ts
                        for ts, ts_pricers in calibration_jobs
                    }
                    completed = as_completed(futures)
                    if tqdm_mod is not None:
                        completed = tqdm_mod.tqdm(completed, total=len(futures), desc=f"CALIBRATING {curve_name}")
                    for fut in completed:
                        ts = futures[fut]
                        _, curve_obj = fut.result()
                        curve_obj = self._attach_curve_context(curve_obj, curve_name=curve_name, timestamp=ts, cfg=cfg)
                        self._mem_cache_put(self._curve_cache_key(curve_name, ts, cfg), curve_obj)
                        fresh_curves[ts] = curve_obj
                        out[ts] = curve_obj if curve_only else (curve_obj, None)
            elif cal_workers == 1:
                # Single worker: sequential warm-start chain.
                chunk_results = self._calibrate_chunk(
                    chunk=sorted(calibration_jobs, key=lambda x: x[0]),
                    curve_name=curve_name,
                    cfg=cfg,
                    solver_tolerances=bulk_solver_tolerances,
                    curve_only=curve_only,
                )
                for ts, val in chunk_results.items():
                    curve_obj = val if curve_only else val[0]
                    fresh_curves[ts] = curve_obj
                    out[ts] = val
            else:
                # Multi-worker: partition into chronological chunks, warm-start within each.
                chunks = _split_chronological(calibration_jobs, cal_workers)
                with ThreadPoolExecutor(max_workers=cal_workers, thread_name_prefix="stir-curve-calib") as pool:
                    futures = {
                        pool.submit(
                            self._calibrate_chunk,
                            chunk=chunk,
                            curve_name=curve_name,
                            cfg=cfg,
                            solver_tolerances=bulk_solver_tolerances,
                            curve_only=curve_only,
                        ): idx
                        for idx, chunk in enumerate(chunks)
                    }
                    completed = as_completed(futures)
                    if tqdm_mod is not None:
                        completed = tqdm_mod.tqdm(completed, total=len(futures), desc=f"CALIBRATING {curve_name}")
                    for fut in completed:
                        chunk_results = fut.result()
                        for ts, val in chunk_results.items():
                            curve_obj = val if curve_only else val[0]
                            fresh_curves[ts] = curve_obj
                            out[ts] = val

            coalesced_duplicates = 0
            for canonical_ts, duplicate_timestamps in duplicate_timestamps_by_canonical.items():
                if not duplicate_timestamps:
                    continue
                canonical_val = out.get(canonical_ts)
                if canonical_val is None:
                    continue
                canonical_curve = canonical_val if curve_only else canonical_val[0]
                if not isinstance(canonical_curve, rl.Curve):
                    continue
                node_values = _curve_nodes_payload(canonical_curve)
                for duplicate_ts in duplicate_timestamps:
                    duplicate_curve = self._curve_from_bundle_nodes(
                        curve_name=curve_name,
                        timestamp=duplicate_ts,
                        cfg=cfg,
                        bundle_date=self._trading_date_for_timestamp(duplicate_ts),
                        node_values=node_values,
                    )
                    fresh_curves[duplicate_ts] = duplicate_curve
                    out[duplicate_ts] = duplicate_curve if curve_only else (duplicate_curve, None)
                    coalesced_duplicates += 1

            if coalesced_duplicates:
                logging.getLogger(__name__).debug(
                    "Coalesced %s duplicate calibration jobs for %s (%s unique calibrations across %s requested timestamps).",
                    coalesced_duplicates,
                    curve_name,
                    len(calibration_jobs),
                    len(pending_timestamps),
                )

            self._persist_bulk_curves(
                curve_name=curve_name,
                cfg=cfg,
                out=out,
                fresh_curves=fresh_curves,
                curve_only=curve_only,
            )

            return out

        is_live_request = self._is_live_request(timestamp)
        normalized_timestamp = self._normalize_timestamp(timestamp)
        local_kwargs = dict(kwargs)
        calibration_executor = str(local_kwargs.pop("calibration_executor", "thread") or "thread").strip().lower()
        if calibration_executor not in _CALIBRATION_EXECUTORS:
            raise ValueError(
                f"Unsupported calibration_executor '{calibration_executor}'. "
                f"Expected one of {sorted(_CALIBRATION_EXECUTORS)}."
            )
        if calibration_executor == "process":
            raise ValueError("Process-pool calibration only supports bulk historical runs with curve_only=True.")
        force_refresh = bool(local_kwargs.get("force_refresh", False))
        if curve_only and not force_refresh:
            cached_curve = self._curve_cache_get(curve_name, normalized_timestamp, cfg)
            if cached_curve is not None:
                return cached_curve

        pricer_req = dict(symbols=cfg["instruments"], timestamp=normalized_timestamp, **local_kwargs)
        fetch_pricers_func, _ = self._resolve_fetchers_for_request(cfg=cfg, is_live_request=is_live_request)
        pricers: Dict[str, List[RLSTIRFuturePricer]] = fetch_pricers_func(request=pricer_req)
        built = self._build_curve_from_pricers(curve_name=curve_name, timestamp=normalized_timestamp, cfg=cfg, pricers=pricers)
        curve_obj, solver_obj = built
        curve_obj = self._attach_curve_context(curve_obj, curve_name=curve_name, timestamp=normalized_timestamp, cfg=cfg)
        self._curve_cache_put(curve_name, normalized_timestamp, cfg, curve_obj)
        return curve_obj if curve_only else (curve_obj, solver_obj)
