from __future__ import annotations

import datetime
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import diskcache
import numpy as np
import pandas as pd
import QuantLib as ql
from scipy.interpolate import BSpline

from Caching.layered_cache_mixin import LayeredDictProxy
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator


CARRY_ROLL_HORIZONS: tuple[tuple[str, str, float], ...] = (
    ("1m", "1M", 1.0 / 12.0),
    ("2m", "2M", 2.0 / 12.0),
    ("3m", "3M", 3.0 / 12.0),
    ("6m", "6M", 6.0 / 12.0),
)

CARRY_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"carry_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)
CARRY_AND_ROLL_BPS_HORIZON_COLUMNS: tuple[str, ...] = tuple(
    f"carry_and_roll_{label}_bps" for label, _, _ in CARRY_ROLL_HORIZONS
)

DEFAULT_CARRY_ROLL_HORIZON_LABEL = "3m"
_HORIZON_BY_LABEL = {label: (label, tenor, years) for label, tenor, years in CARRY_ROLL_HORIZONS}
_HORIZON_BY_TENOR = {tenor.upper(): (label, tenor, years) for label, tenor, years in CARRY_ROLL_HORIZONS}
_ROLL_SPLINE_CACHE_VERSION = 1
_ROLL_SPLINE_CORE_CACHE_NS = f"frb_roll_spline_cache_v{_ROLL_SPLINE_CACHE_VERSION}"
_ROLL_SPLINE_CACHE: dict[
    datetime.date,
    tuple[float, float, "RollSplineEvaluator", dict[str, tuple[Optional[float], Optional[float]]]],
] = {}
_ROLL_SPLINE_CACHE_LOCK = threading.RLock()
_ROLL_SPLINE_DISK_CACHE: Any = None
_ROLL_SPLINE_DISK_CACHE_LOCK = threading.RLock()


class RollSplineEvaluator:
    def __init__(
        self,
        *,
        knots: np.ndarray,
        coeffs: np.ndarray,
        degree: int,
        tail_start: float,
        tail_base: float,
        tail_slope: float,
    ) -> None:
        self.knots = np.asarray(knots, dtype=float)
        self.coeffs = np.asarray(coeffs, dtype=float)
        self.degree = int(degree)
        self.tail_start = float(tail_start)
        self.tail_base = float(tail_base)
        self.tail_slope = float(tail_slope)
        self._restore()

    def _restore(self) -> None:
        self._base_spline = BSpline(self.knots, self.coeffs, self.degree)

    def __getstate__(self) -> dict[str, Any]:
        return {
            "knots": self.knots,
            "coeffs": self.coeffs,
            "degree": self.degree,
            "tail_start": self.tail_start,
            "tail_base": self.tail_base,
            "tail_slope": self.tail_slope,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.knots = np.asarray(state["knots"], dtype=float)
        self.coeffs = np.asarray(state["coeffs"], dtype=float)
        self.degree = int(state["degree"])
        self.tail_start = float(state["tail_start"])
        self.tail_base = float(state["tail_base"])
        self.tail_slope = float(state["tail_slope"])
        self._restore()

    def __call__(self, z: np.ndarray | float) -> np.ndarray:
        arr = np.asarray(z, dtype=float)
        scalar_input = arr.ndim == 0
        if scalar_input:
            arr = arr.reshape(1)

        out = np.asarray(self._base_spline(arr), dtype=float)
        tail_mask = arr >= self.tail_start
        if np.any(tail_mask):
            out = out.copy()
            out[tail_mask] = self.tail_base + self.tail_slope * (arr[tail_mask] - self.tail_start)

        if scalar_input:
            return np.asarray(out[0], dtype=float)
        return out


def normalize_horizon_spec(horizon: Any = None) -> tuple[str, str, float]:
    if horizon is None:
        return _HORIZON_BY_LABEL[DEFAULT_CARRY_ROLL_HORIZON_LABEL]

    txt = str(horizon).strip()
    if not txt:
        return _HORIZON_BY_LABEL[DEFAULT_CARRY_ROLL_HORIZON_LABEL]

    key = txt.lower()
    if key in _HORIZON_BY_LABEL:
        return _HORIZON_BY_LABEL[key]

    tenor_key = txt.upper()
    if tenor_key in _HORIZON_BY_TENOR:
        return _HORIZON_BY_TENOR[tenor_key]

    raise ValueError(f"Unsupported carry/roll horizon: {horizon!r}. Expected one of 1m/2m/3m/6m or 1M/2M/3M/6M.")


def safe_float(x: Any) -> Optional[float]:
    try:
        y = float(x)
    except Exception:
        return None
    if np.isnan(y) or np.isinf(y):
        return None
    return y


def ensure_numeric_columns(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def load_curve_fixing_pct(as_of_date: datetime.date, curve_name: str) -> Optional[float]:
    from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

    try:
        fixings = _fetch_fixings(as_of_date=as_of_date, curve_name=curve_name)
    except Exception:
        return None
    if fixings is None:
        return None

    try:
        s = pd.Series(fixings).copy()
    except Exception:
        return None
    if s.empty:
        return None

    idx = pd.to_datetime(s.index, errors="coerce")
    val = pd.to_numeric(s, errors="coerce")
    tmp = pd.DataFrame({"fixing": val}, index=idx)
    tmp = tmp[~tmp.index.isna()]
    tmp = tmp.dropna(subset=["fixing"])
    tmp = tmp[tmp.index.date < as_of_date].sort_index()
    if tmp.empty:
        return None

    fixing_pct = float(tmp["fixing"].iloc[-1])
    if not np.isfinite(fixing_pct):
        return None

    if abs(fixing_pct) <= 1.0:
        fixing_pct *= 100.0
    return fixing_pct


def load_sofr_fixing_pct(as_of_date: datetime.date) -> Optional[float]:
    return load_curve_fixing_pct(as_of_date=as_of_date, curve_name="USD-SOFR-1D")


def load_us_treasury_gc_fixing_pct(as_of_date: datetime.date) -> Optional[float]:
    """
    Resolve the unsecured overnight proxy used for UST financing.

    Use SOFR when that fixing history is available for the requested date and
    fall back to Fed Funds for earlier dates before SOFR's publication history.
    """
    for curve_name in ("USD-SOFR-1D", "USD-FEDFUNDS"):
        fixing_pct = load_curve_fixing_pct(as_of_date=as_of_date, curve_name=curve_name)
        if fixing_pct is not None:
            return fixing_pct
    return None


def _resolve_roll_spline_cache_dir() -> Path:
    arbs_cache_dir = os.getenv("ARBS_CACHE_DIR")
    if arbs_cache_dir:
        return (Path(arbs_cache_dir) / "Query" / "FixedRateBonds" / "roll_spline_cache").resolve()

    try:
        from platformdirs import user_cache_dir

        return (Path(user_cache_dir(appname="ARBS", appauthor=False)) / "Query" / "FixedRateBonds" / "roll_spline_cache").resolve()
    except Exception:
        if os.name == "nt":
            return (Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "Query" / "FixedRateBonds" / "roll_spline_cache").resolve()
        return (Path.home() / ".cache" / "arbs" / "Query" / "FixedRateBonds" / "roll_spline_cache").resolve()


def _get_roll_spline_disk_cache() -> Any:
    global _ROLL_SPLINE_DISK_CACHE

    with _ROLL_SPLINE_DISK_CACHE_LOCK:
        if _ROLL_SPLINE_DISK_CACHE is None:
            cache_dir = _resolve_roll_spline_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_cache = diskcache.Cache(directory=str(cache_dir))

            try:
                from Caching.supabase_engine import SUPABASE_ENABLED

                if SUPABASE_ENABLED:
                    _ROLL_SPLINE_DISK_CACHE = LayeredDictProxy(
                        local_cache,
                        _ROLL_SPLINE_CORE_CACHE_NS,
                        l2_read=True,
                        l2_write=True,
                        ttl_seconds=365 * 24 * 3600,
                    )
                else:
                    _ROLL_SPLINE_DISK_CACHE = local_cache
            except Exception:
                _ROLL_SPLINE_DISK_CACHE = local_cache
        return _ROLL_SPLINE_DISK_CACHE


def _roll_spline_cache_key(as_of_date: datetime.date) -> str:
    return f"roll_spline:v{_ROLL_SPLINE_CACHE_VERSION}:{as_of_date.isoformat()}"


def _clear_roll_spline_l2_cache() -> None:
    try:
        from sqlalchemy import text

        from Caching.supabase_engine import SUPABASE_ENABLED, get_engine
        from Caching.supabase_schema import ensure_schema

        if not SUPABASE_ENABLED:
            return
        engine = get_engine()
        if engine is None or not ensure_schema(engine):
            return
        with engine.begin() as conn:
            conn.execute(
                text("""
                    DELETE FROM arbs_kv_cache_v1
                    WHERE cache_ns = :cache_ns
                """),
                {"cache_ns": _ROLL_SPLINE_CORE_CACHE_NS},
            )
    except Exception:
        pass


def fit_roll_spline(ttm: np.ndarray, ytm: np.ndarray) -> Optional[Callable[[np.ndarray], np.ndarray]]:
    if ttm.size == 0 or ytm.size == 0:
        return None

    df = pd.DataFrame({"ttm": ttm, "ytm": ytm})
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["ttm", "ytm"])
    if df.empty:
        return None

    dedup = df.groupby("ttm", as_index=False)["ytm"].mean().sort_values(by="ttm")
    if len(dedup) < 4:
        return None

    x = dedup["ttm"].to_numpy(dtype=float)
    y = dedup["ytm"].to_numpy(dtype=float)
    degree = max(1, min(3, len(x) - 1))
    try:
        interp = GeneralCurveInterpolator(x=x, y=y)
        base_func = interp.b_spline1_interpolation(k=degree, return_func=True)
        if not isinstance(base_func, BSpline):
            return None
        if len(x) < 2:
            return RollSplineEvaluator(
                knots=np.asarray(base_func.t, dtype=float),
                coeffs=np.asarray(base_func.c, dtype=float),
                degree=int(base_func.k),
                tail_start=float(x[-1]),
                tail_base=float(y[-1]),
                tail_slope=0.0,
            )

        tail_start = float(x[-2])
        tail_end = float(x[-1])
        tail_base = float(y[-2])
        tail_slope = float(y[-1] - y[-2]) / float(tail_end - tail_start)
        return RollSplineEvaluator(
            knots=np.asarray(base_func.t, dtype=float),
            coeffs=np.asarray(base_func.c, dtype=float),
            degree=int(base_func.k),
            tail_start=tail_start,
            tail_base=tail_base,
            tail_slope=tail_slope,
        )
    except Exception:
        return None


def _fit_df_for_roll(frame: pd.DataFrame) -> pd.DataFrame:
    base = frame.copy()
    if "rank" in base.columns:
        rank = pd.to_numeric(base["rank"], errors="coerce")
        off_runs = base.loc[~rank.isin([0, 1, 2])].copy()
        if not off_runs.empty:
            base = off_runs
    return (
        base[["ttm", "ytm"]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=["ttm", "ytm"])
        .groupby("ttm", as_index=False)["ytm"]
        .mean()
        .sort_values(by="ttm")
    )


def _cached_roll_spline(
    *,
    as_of_date: datetime.date,
    fit_df: pd.DataFrame,
) -> tuple[
    Optional[RollSplineEvaluator],
    Optional[float],
    Optional[float],
    dict[str, tuple[Optional[float], Optional[float]]],
]:
    func, fit_min, fit_max, edge_rolls = _get_cached_roll_spline(as_of_date=as_of_date)
    if func is not None and fit_min is not None and fit_max is not None:
        return func, fit_min, fit_max, edge_rolls

    if fit_df.empty or len(fit_df) < 4:
        return None, None, None, {}

    func = fit_roll_spline(
        ttm=fit_df["ttm"].to_numpy(dtype=float),
        ytm=fit_df["ytm"].to_numpy(dtype=float),
    )
    if func is None:
        return None, None, None, {}

    fit_min = float(fit_df["ttm"].iloc[0])
    fit_max = float(fit_df["ttm"].iloc[-1])
    edge_rolls: dict[str, tuple[Optional[float], Optional[float]]] = {}
    x_now = fit_df["ttm"].to_numpy(dtype=float)
    try:
        y_now = np.asarray(func(x_now), dtype=float)
    except Exception:
        y_now = np.full_like(x_now, np.nan, dtype=float)

    for label, _, horizon_years in CARRY_ROLL_HORIZONS:
        x_prev = x_now - horizon_years
        valid = np.isfinite(x_now) & np.isfinite(y_now) & np.isfinite(x_prev) & (x_prev >= fit_min) & (x_prev <= fit_max)
        if not np.any(valid):
            edge_rolls[label] = (None, None)
            continue
        try:
            y_prev = np.asarray(func(x_prev[valid]), dtype=float)
            roll_vals = (y_now[valid] - y_prev) * 100.0
            roll_vals[~np.isfinite(roll_vals)] = np.nan
        except Exception:
            edge_rolls[label] = (None, None)
            continue
        finite_rolls = roll_vals[np.isfinite(roll_vals)]
        if finite_rolls.size == 0:
            edge_rolls[label] = (None, None)
            continue
        edge_rolls[label] = (float(finite_rolls[0]), float(finite_rolls[-1]))

    with _ROLL_SPLINE_CACHE_LOCK:
        _ROLL_SPLINE_CACHE[as_of_date] = (fit_min, fit_max, func, edge_rolls)
    try:
        _get_roll_spline_disk_cache()[_roll_spline_cache_key(as_of_date)] = {
            "fit_min": fit_min,
            "fit_max": fit_max,
            "func": func,
            "edge_rolls": edge_rolls,
        }
    except Exception:
        pass
    return func, fit_min, fit_max, edge_rolls


def _get_cached_roll_spline(
    *,
    as_of_date: datetime.date,
) -> tuple[
    Optional[RollSplineEvaluator],
    Optional[float],
    Optional[float],
    dict[str, tuple[Optional[float], Optional[float]]],
]:
    with _ROLL_SPLINE_CACHE_LOCK:
        hit = _ROLL_SPLINE_CACHE.get(as_of_date)
    if hit is not None:
        fit_min, fit_max, func, edge_rolls = hit
        return func, fit_min, fit_max, edge_rolls

    try:
        payload = _get_roll_spline_disk_cache().get(_roll_spline_cache_key(as_of_date))
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return None, None, None, {}

    fit_min = safe_float(payload.get("fit_min"))
    fit_max = safe_float(payload.get("fit_max"))
    func = payload.get("func")
    edge_rolls = payload.get("edge_rolls") or {}
    if fit_min is None or fit_max is None or not isinstance(func, RollSplineEvaluator):
        return None, None, None, {}

    edge_rolls_clean: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for label, edge_pair in dict(edge_rolls).items():
        if not isinstance(edge_pair, (tuple, list)) or len(edge_pair) != 2:
            continue
        edge_rolls_clean[str(label)] = (safe_float(edge_pair[0]), safe_float(edge_pair[1]))

    with _ROLL_SPLINE_CACHE_LOCK:
        _ROLL_SPLINE_CACHE[as_of_date] = (fit_min, fit_max, func, edge_rolls_clean)
    return func, fit_min, fit_max, edge_rolls_clean


def clear_roll_spline_cache(*, include_persistent: bool = True) -> None:
    with _ROLL_SPLINE_CACHE_LOCK:
        _ROLL_SPLINE_CACHE.clear()
    if include_persistent:
        try:
            _get_roll_spline_disk_cache().clear()
        except Exception:
            pass
        _clear_roll_spline_l2_cache()


def coerce_date(val: Any) -> Optional[datetime.date]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    if isinstance(val, ql.Date):
        return datetime.date(val.year(), val.month(), val.dayOfMonth())
    try:
        year = getattr(val, "year", None)
        month = getattr(val, "month", None)
        day = getattr(val, "day", None)
        if callable(year):
            year = year()
        if callable(month):
            month = month()
        if callable(day):
            day = day()
        if year is not None and month is not None and day is not None:
            return datetime.date(int(year), int(month), int(day))
    except Exception:
        pass
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def to_ql_date(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def advance_horizon_date(
    *,
    as_of_date: datetime.date,
    pricer: Any = None,
    horizon_tenor: str = "3M",
) -> datetime.date:
    if pricer is not None:
        try:
            adv = pricer.calendar_advance(as_of_date, horizon_tenor)
            d = coerce_date(adv)
            if d is not None:
                return d
        except Exception:
            pass

    try:
        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        qd = to_ql_date(as_of_date)
        adv = cal.advance(qd, ql.Period(horizon_tenor), ql.ModifiedFollowing)
        return datetime.date(adv.year(), adv.month(), adv.dayOfMonth())
    except Exception:
        return as_of_date + datetime.timedelta(days=91)


def normalize_coupon_pct(cpn_raw: Optional[float]) -> Optional[float]:
    if cpn_raw is None or not np.isfinite(cpn_raw):
        return None
    cpn = float(cpn_raw)
    if abs(cpn) <= 1.0:
        cpn *= 100.0
    return cpn


def coupon_accrual_price_per_100(
    *,
    issue_date: Optional[datetime.date],
    maturity_date: Optional[datetime.date],
    coupon_pct: Optional[float],
    start_date: datetime.date,
    end_date: datetime.date,
) -> Optional[float]:
    if end_date <= start_date:
        return 0.0

    cpn = normalize_coupon_pct(coupon_pct)
    if issue_date is not None and maturity_date is not None and cpn is not None:
        try:
            cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
            sched = ql.Schedule(
                to_ql_date(issue_date),
                to_ql_date(maturity_date),
                ql.Period(6, ql.Months),
                cal,
                ql.ModifiedFollowing,
                ql.ModifiedFollowing,
                ql.DateGeneration.Backward,
                False,
            )
            qs = to_ql_date(start_date)
            qe = to_ql_date(end_date)
            total = 0.0
            cpn_per_period = cpn / 2.0

            for i in range(len(sched) - 1):
                a0 = sched[i]
                a1 = sched[i + 1]
                if a1 <= qs or a0 >= qe:
                    continue
                ov_start = a0 if a0 > qs else qs
                ov_end = a1 if a1 < qe else qe
                ov_days = int(ov_end - ov_start)
                period_days = int(a1 - a0)
                if ov_days <= 0 or period_days <= 0:
                    continue
                total += cpn_per_period * (ov_days / period_days)

            if total > 0.0:
                return float(total)
        except Exception:
            pass

    if cpn is None:
        return None
    days = max((end_date - start_date).days, 0)
    return float(cpn) * (days / 365.0)


def compute_carry_roll_columns(
    df: pd.DataFrame,
    *,
    as_of_date: datetime.date,
    pricers: Dict[str, Any],
) -> pd.DataFrame:
    out = df.copy()
    metric_cols = [
        "carry_bps",
        "roll_bps",
        "carry_and_roll_bps",
        *CARRY_BPS_HORIZON_COLUMNS,
        *ROLL_BPS_HORIZON_COLUMNS,
        *CARRY_AND_ROLL_BPS_HORIZON_COLUMNS,
    ]
    for col in metric_cols:
        out[col] = np.nan
    if out.empty:
        return out

    out = ensure_numeric_columns(out, ["ttm", "ytm", "coupon", "dirty_price", "mdur"])

    sofr_pct = load_sofr_fixing_pct(as_of_date=as_of_date)
    if sofr_pct is not None:
        sofr_dec = float(sofr_pct) / 100.0
        horizon_defaults: dict[str, datetime.date] = {
            label: advance_horizon_date(as_of_date=as_of_date, horizon_tenor=tenor)
            for label, tenor, _ in CARRY_ROLL_HORIZONS
        }
        carry_by_horizon: dict[str, list[float]] = {
            label: [] for label, _, _ in CARRY_ROLL_HORIZONS
        }

        for _, row in out.iterrows():
            cusip = str(row.get("cusip") or "")
            pricer = pricers.get(cusip)

            dirty0 = safe_float(row.get("dirty_price"))
            if dirty0 is None and pricer is not None and hasattr(pricer, "dirty_price"):
                dirty0 = safe_float(pricer.dirty_price())

            mdur = safe_float(row.get("mdur"))
            if mdur is None and pricer is not None and hasattr(pricer, "mod_duration"):
                mdur = safe_float(pricer.mod_duration())

            if dirty0 is None or mdur is None or dirty0 <= 0 or mdur <= 0:
                for label, _, _ in CARRY_ROLL_HORIZONS:
                    carry_by_horizon[label].append(np.nan)
                continue

            issue_date = coerce_date(row.get("issue_date"))
            maturity_date = coerce_date(row.get("maturity_date"))
            cpn = safe_float(row.get("coupon"))

            if (issue_date is None or maturity_date is None or cpn is None) and pricer is not None:
                try:
                    if issue_date is None:
                        issue_date = coerce_date(pricer.issue_date())
                    if maturity_date is None:
                        maturity_date = coerce_date(pricer.maturity_date())
                    if cpn is None:
                        cpn = safe_float(pricer.coupon())
                except Exception:
                    pass

            dv01 = mdur * dirty0 / 10000.0
            if dv01 <= 0 or not np.isfinite(dv01):
                for label, _, _ in CARRY_ROLL_HORIZONS:
                    carry_by_horizon[label].append(np.nan)
                continue

            for label, tenor, _ in CARRY_ROLL_HORIZONS:
                horizon_date = horizon_defaults[label]
                if pricer is not None:
                    horizon_date = advance_horizon_date(
                        as_of_date=as_of_date,
                        pricer=pricer,
                        horizon_tenor=tenor,
                    )

                if horizon_date <= as_of_date:
                    carry_by_horizon[label].append(np.nan)
                    continue

                horizon_days = max((horizon_date - as_of_date).days, 1)
                coupon_accrual = coupon_accrual_price_per_100(
                    issue_date=issue_date,
                    maturity_date=maturity_date,
                    coupon_pct=cpn,
                    start_date=as_of_date,
                    end_date=horizon_date,
                )

                if coupon_accrual is None:
                    carry_by_horizon[label].append(np.nan)
                    continue

                financing_cost = dirty0 * sofr_dec * (horizon_days / 360.0)
                carry_price = coupon_accrual - financing_cost
                carry_bps = carry_price / dv01
                if not np.isfinite(carry_bps):
                    carry_bps = np.nan
                carry_by_horizon[label].append(float(carry_bps))

        for label, _, _ in CARRY_ROLL_HORIZONS:
            out[f"carry_{label}_bps"] = pd.Series(carry_by_horizon[label], index=out.index)

    roll_func, fit_min, fit_max, edge_rolls = _get_cached_roll_spline(as_of_date=as_of_date)
    if roll_func is None or fit_min is None or fit_max is None:
        fit_df = _fit_df_for_roll(out)
        roll_func, fit_min, fit_max, edge_rolls = _cached_roll_spline(as_of_date=as_of_date, fit_df=fit_df)
    if roll_func is not None and fit_min is not None and fit_max is not None:
        for label, _, horizon_years in CARRY_ROLL_HORIZONS:
            shifted_ttm = out["ttm"] - horizon_years
            valid = (
                out["ttm"].notna()
                & out["ytm"].notna()
                & shifted_ttm.notna()
                & (shifted_ttm >= fit_min)
                & (shifted_ttm <= fit_max)
            )
            if not bool(valid.any()):
                continue
            x_now = out.loc[valid, "ttm"].to_numpy(dtype=float)
            x_prev = shifted_ttm.loc[valid].to_numpy(dtype=float)
            try:
                y_now = np.asarray(roll_func(x_now), dtype=float)
                y_prev = np.asarray(roll_func(x_prev), dtype=float)
                roll_bps = (y_now - y_prev) * 100.0
                roll_bps[~np.isfinite(roll_bps)] = np.nan
                out.loc[valid, f"roll_{label}_bps"] = roll_bps
            except Exception:
                pass

        # Approximate edge rolls by carrying forward the nearest available run roll.
        # This keeps front-end packages like CT2/CT10 from collapsing to NaN while
        # still deriving the curve shape from the runs-only spline.
        for label, _, _ in CARRY_ROLL_HORIZONS:
            roll_col = f"roll_{label}_bps"
            valid_rolls = out.loc[out[roll_col].notna(), ["ttm", roll_col]].sort_values("ttm")
            if valid_rolls.empty:
                edge_front, edge_back = edge_rolls.get(label, (None, None))
                for idx in out.index[out[roll_col].isna() & out["ttm"].notna()]:
                    ttm_val = float(out.at[idx, "ttm"])
                    if ttm_val < fit_min + horizon_years and edge_front is not None:
                        out.at[idx, roll_col] = float(edge_front)
                    elif ttm_val > fit_max and edge_back is not None:
                        out.at[idx, roll_col] = float(edge_back)
                continue

            for idx in out.index[out[roll_col].isna() & out["ttm"].notna()]:
                ttm_val = float(out.at[idx, "ttm"])
                nearest_idx = (valid_rolls["ttm"] - ttm_val).abs().idxmin()
                out.at[idx, roll_col] = float(valid_rolls.at[nearest_idx, roll_col])

    for label, _, _ in CARRY_ROLL_HORIZONS:
        carry_col = f"carry_{label}_bps"
        roll_col = f"roll_{label}_bps"
        carry_roll_col = f"carry_and_roll_{label}_bps"
        out[carry_roll_col] = out[carry_col] + out[roll_col]

    out["carry_bps"] = out["carry_3m_bps"]
    out["roll_bps"] = out["roll_3m_bps"]
    out["carry_and_roll_bps"] = out["carry_and_roll_3m_bps"]
    return out


def build_pricer_metrics_frame(pricers: Dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, pricer in pricers.items():
        try:
            meta = pricer.meta() or {}
        except Exception:
            meta = {}

        cusip = str(meta.get("cusip") or key)
        rows.append(
            {
                "cusip": cusip,
                "oi": meta.get("oi"),
                "ust_label": meta.get("ust_label") or meta.get("label"),
                "rank": safe_float(meta.get("rank")),
                "ttm": safe_float(meta.get("ttm") if meta.get("ttm") is not None else (pricer.time_to_maturity() if hasattr(pricer, "time_to_maturity") else None)),
                "ytm": safe_float(pricer.ytm() if hasattr(pricer, "ytm") else None),
                "mdur": safe_float(pricer.mod_duration() if hasattr(pricer, "mod_duration") else None),
                "clean_price": safe_float(pricer.clean_price() if hasattr(pricer, "clean_price") else None),
                "dirty_price": safe_float(pricer.dirty_price() if hasattr(pricer, "dirty_price") else None),
                "coupon": safe_float(meta.get("coupon") if meta.get("coupon") is not None else meta.get("cpn")),
                "issue_date": meta.get("issue_date"),
                "maturity_date": meta.get("maturity_date"),
                "market_timestamp": meta.get("timestamp"),
            }
        )

    return pd.DataFrame(rows)


def compute_carry_roll_frame(
    *,
    pricers: Dict[str, Any],
    as_of_date: datetime.date,
) -> pd.DataFrame:
    base = build_pricer_metrics_frame(pricers)
    if base.empty:
        return base
    out = compute_carry_roll_columns(base, as_of_date=as_of_date, pricers={str(k): v for k, v in pricers.items()})
    return out


def frame_supports_roll(frame: pd.DataFrame, *, as_of_date: datetime.date | None = None) -> bool:
    if frame is None or frame.empty:
        return False
    if "ttm" not in frame.columns or "ytm" not in frame.columns:
        return False
    if as_of_date is None:
        as_of_date = coerce_date(frame.get("market_timestamp", pd.Series(dtype="object")).dropna().iloc[0]) if "market_timestamp" in frame.columns and not frame["market_timestamp"].dropna().empty else None
    if as_of_date is None:
        as_of_date = datetime.date.today()
    roll_func, fit_min, fit_max, _ = _get_cached_roll_spline(as_of_date=as_of_date)
    if roll_func is not None and fit_min is not None and fit_max is not None:
        return True
    fit_df = _fit_df_for_roll(frame)
    if len(fit_df) < 4:
        return False
    func, _, _, _ = _cached_roll_spline(as_of_date=as_of_date, fit_df=fit_df)
    return func is not None


def _infer_pricing_timestamp(pricers: Dict[str, Any], as_of_date: datetime.date) -> datetime.date | datetime.datetime | str:
    if not pricers:
        return as_of_date

    first_pricer = next(iter(pricers.values()))
    try:
        meta = first_pricer.meta() or {}
    except Exception:
        meta = {}

    raw = meta.get("timestamp")
    if raw is None:
        return as_of_date
    if isinstance(raw, str) and raw.lower() == "live":
        return "live"
    if isinstance(raw, datetime.datetime):
        return raw
    if isinstance(raw, datetime.date):
        return raw
    try:
        ts = pd.Timestamp(raw)
    except Exception:
        return as_of_date
    if ts.tzinfo is not None:
        return ts.to_pydatetime()
    if ts.time() != datetime.time():
        return ts.to_pydatetime()
    return ts.date()


def _infer_universe_source(pricers: Dict[str, Any], pricing_timestamp: datetime.date | datetime.datetime | str) -> str:
    if not pricers:
        return "USTS_FEDINVEST_WSJ_LIVE-QL"

    first_pricer = next(iter(pricers.values()))
    try:
        meta = first_pricer.meta() or {}
    except Exception:
        meta = {}

    meta_source = meta.get("source")
    if meta_source:
        return str(meta_source)

    if hasattr(first_pricer, "_ql_frb_id"):
        return "USTS_FEDINVEST_WSJ_LIVE-QL"

    if isinstance(pricing_timestamp, datetime.datetime):
        return "USTS_WEBULL_WSJ_LIVE-RL"

    return "USTS_FEDINVEST_WSJ_LIVE-QL"


def expand_pricer_universe_for_carry_roll(
    *,
    pricers: Dict[str, Any],
    as_of_date: datetime.date,
    min_ttm: float = 1.0,
) -> Dict[str, Any]:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    pricing_timestamp = _infer_pricing_timestamp(pricers, as_of_date)
    source = _infer_universe_source(pricers, pricing_timestamp)
    mdp = FixedRateBondsMDP(source=source)
    ref_df = mdp.get_bond_reference_data(as_of_date=as_of_date).copy()
    if ref_df.empty:
        return pricers

    ref_df = ref_df.drop(columns=["record_date"], errors="ignore")
    if "ttm" in ref_df.columns:
        ref_df["ttm"] = pd.to_numeric(ref_df["ttm"], errors="coerce")
        ref_df = ref_df[ref_df["ttm"] >= float(min_ttm)].copy()
    ref_df["cusip"] = ref_df["cusip"].astype(str)
    requested_cusips: set[str] = set()
    for key, pricer in pricers.items():
        try:
            meta = pricer.meta() or {}
        except Exception:
            meta = {}
        requested_cusips.add(str(meta.get("cusip") or key))
    if "rank" in ref_df.columns:
        rank = pd.to_numeric(ref_df["rank"], errors="coerce")
        ref_df = ref_df.loc[~rank.isin([0, 1, 2]) | ref_df["cusip"].isin(requested_cusips)].copy()
    ref_df = ref_df.drop_duplicates(subset=["cusip"], keep="last")
    if ref_df.empty:
        return pricers

    expanded = mdp.get_pricer(
        request={
            "cusips": ref_df["cusip"].tolist(),
            "timestamp": pricing_timestamp,
            "show_tqdm": False,
        }
    )
    return expanded or pricers
