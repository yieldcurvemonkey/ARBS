from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import QuantLib as ql
from tqdm.auto import tqdm as _tqdm

from BT.misc import ql_cal_date_range
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.FixedRateBonds.WSJ.WSJFetcher import WSJFetcher
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure, IRSwapStructureFunctionMap
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date
from SDRUtils.data.builder import SDRDataBuilder
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.utils import DateLike

_LOGGER_NAME = "IRSwapSpreadsTB"
_SOURCE_SDR_WSJ_INTRADAY_SPREADOVER = "SDR-WSJ-INTRADAY-SPREADOVER"
_SOURCE_SDR_USTS_WEBULL_WSJ_LIVE_INTRADAY_SPREADOVER = "SDR-USTS_WEBULL_WSJ_LIVE-INTRADAY-SPREADOVER"
_LIQUID_TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")
_SOFR_SDR_UPIS: tuple[str, ...] = (
    "QZXQ4R16245X",
    "QZPB5VSBGRCD",
    "QZM88X1WWFMD",
)
_WSJ_CT_TICKERS: dict[str, str] = {
    "2Y": "TMUBMUSD02Y",
    "5Y": "TMUBMUSD05Y",
    "10Y": "TMUBMUSD10Y",
    "30Y": "TMUBMUSD30Y",
}
_WSJ_INTRADAY_MAX_DAYS = 10
_USTS_WEBULL_INTRADAY_N_JOBS = 12


def _empty_frame(index_name: str) -> pd.DataFrame:
    return pd.DataFrame().set_index(pd.Index([], name=index_name))


def _column(df: pd.DataFrame, name: str, default: object = pd.NA) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index)


def _coerce_numeric(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return pd.to_numeric(
        series.astype("string").str.strip().str.replace(",", "", regex=False),
        errors="coerce",
    )


def _coerce_notional(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype("string").str.replace(r"[^\d.\-]", "", regex=True),
        errors="coerce",
    )


def _true_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    normalized = series.astype("string").str.strip().str.upper()
    return normalized.isin({"TRUE", "T", "YES", "Y", "1"})


def deadband_step_filter(x: pd.Series, threshold: float, snap: float | None = None) -> pd.Series:
    vals = x.to_numpy(dtype=float)
    if len(vals) == 0:
        return pd.Series(dtype=float, index=x.index)

    out = np.empty_like(vals)
    out[0] = vals[0]
    for idx in range(1, len(vals)):
        prev = out[idx - 1]
        cur = vals[idx]
        if np.isnan(cur):
            out[idx] = prev
            continue
        if np.isnan(prev) or abs(cur - prev) > threshold:
            new_level = cur if snap is None else np.round(cur / snap) * snap
            out[idx] = new_level
        else:
            out[idx] = prev
    return pd.Series(out, index=x.index).ffill()


class IRSwapSpreadsTB:
    """
    Intraday swap spread builder keyed by explicit source implementation.

    Supported sources:
    - `SDR-WSJ-INTRADAY-SPREADOVER`
      Uses raw SDR trades for swap-rate minute VWAPs and WSJ intraday CT
      yields for UST benchmarks. This mirrors the Oasis notebook workflow.
    - `SDR-USTS_WEBULL_WSJ_LIVE-INTRADAY-SPREADOVER`
      Uses the same SDR swap-rate minute VWAPs, but sources UST intraday
      yields through `FixedRateBondsTB(FixedRateBondsMDP("USTS_WEBULL_WSJ_LIVE-RL"))`.

    The implementation is intentionally narrow and only supports the liquid
    spot tenors `2Y`, `5Y`, `10Y`, and `30Y`.
    """

    LIQUID_TENORS = _LIQUID_TENORS
    DEFAULT_SOURCE = _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER
    SUPPORTED_SOURCES = frozenset(
        {
            _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER,
            _SOURCE_SDR_USTS_WEBULL_WSJ_LIVE_INTRADAY_SPREADOVER,
        }
    )

    def __init__(
        self,
        *,
        source: str = DEFAULT_SOURCE,
        curve_name: str = "USD-SOFR-1D",
        cache_path: Optional[str] = None,
        date_col: str = "Date",
        timezone_name: str = "America/New_York",
        show_tqdm: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        if source not in self.SUPPORTED_SOURCES:
            raise ValueError(
                f"Unsupported source '{source}'. Supported sources: {sorted(self.SUPPORTED_SOURCES)}"
            )
        if source in {
            _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER,
            _SOURCE_SDR_USTS_WEBULL_WSJ_LIVE_INTRADAY_SPREADOVER,
        } and curve_name != "USD-SOFR-1D":
            raise ValueError(
                "IRSwapSpreadsTB currently supports only curve_name='USD-SOFR-1D' "
                f"for source='{source}'."
            )
        self.source = source
        self.curve_name = curve_name
        self._cache_path = Path(cache_path or "./.cache/sdr")
        self._cache_path.mkdir(parents=True, exist_ok=True)
        self._date_col = date_col
        self._tz = ZoneInfo(timezone_name)
        self._calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        self._show_tqdm = show_tqdm
        self._logger = logger or logging.getLogger(_LOGGER_NAME)
        self._swap_date_cache: dict[tuple[datetime.date, str], tuple[datetime.date, datetime.date]] = {}
        self._usts_webull_wsj_live_mdp: Optional[FixedRateBondsMDP] = None
        self._usts_webull_wsj_live_tb: Optional[FixedRateBondsTB] = None

    def _coerce_timestamp_bound(self, value: DateLike, *, is_end: bool) -> datetime.datetime:
        if isinstance(value, datetime.datetime):
            if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
                return value.replace(tzinfo=self._tz)
            return value.astimezone(self._tz)
        clock = datetime.time(23, 59) if is_end else datetime.time(0, 0)
        return datetime.datetime.combine(value, clock, tzinfo=self._tz)

    def _normalize_window(self, start: DateLike, end: DateLike) -> tuple[datetime.datetime, datetime.datetime]:
        start_dt = self._coerce_timestamp_bound(start, is_end=False)
        end_dt = self._coerce_timestamp_bound(end, is_end=True)
        if start_dt > end_dt:
            raise ValueError("start must be <= end")
        span_days = end_dt - start_dt
        if (
            self.source == _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER
            and span_days > datetime.timedelta(days=_WSJ_INTRADAY_MAX_DAYS)
        ):
            raise ValueError(
                "WSJ intraday only retains roughly 10 days. "
                "Use a shorter intraday window for IRSwapSpreadsTB."
            )
        return start_dt, end_dt

    def _normalize_tenor(self, value: str | IRSwapQuery) -> str:
        if isinstance(value, IRSwapQuery):
            if value.curve not in {None, self.curve_name}:
                raise ValueError(f"IRSwapQuery curve must be '{self.curve_name}' for IRSwapSpreadsTB.")
            if getattr(value, "structure", IRSwapStructure.OUTRIGHT) != IRSwapStructure.OUTRIGHT:
                raise ValueError("IRSwapSpreadsTB only supports outright liquid tenors.")
            raw = str(value.tenor or "")
        else:
            raw = str(value)

        token = raw.strip().upper().replace(" ", "")
        if token.startswith("CT"):
            token = f"{token[2:]}Y"
        match = re.fullmatch(r"(\d+)(?:Y|YR|YEAR|YEARS)?", token)
        if not match:
            raise ValueError(f"Unsupported tenor '{raw}'. Use one of {_LIQUID_TENORS}.")
        normalized = f"{int(match.group(1))}Y"
        if normalized not in _LIQUID_TENORS:
            raise ValueError(f"Unsupported tenor '{raw}'. Use one of {_LIQUID_TENORS}.")
        return normalized

    def _normalize_tenors(self, tenors: Optional[Sequence[str | IRSwapQuery]]) -> list[str]:
        raw = tenors or list(_LIQUID_TENORS)
        normalized = [self._normalize_tenor(item) for item in raw]
        return list(dict.fromkeys(normalized))

    def _iter_progress(self, items: Sequence[object], desc: str):
        return _tqdm(items, desc=desc, disable=not self._show_tqdm)

    def _business_days(self, start: datetime.datetime, end: datetime.datetime) -> list[datetime.date]:
        out: list[datetime.date] = []
        for day in pd.date_range(start.date(), end.date(), freq="D").date.tolist():
            if self._calendar.isBusinessDay(datetime_to_ql_date(day)):
                out.append(day)
        return out

    def _build_flat_curve(self, ref_date: datetime.date) -> QLIRSwapCurve:
        cfg = QUANTLIB_CURVE_DEFINITIONS[self.curve_name]
        ql_curve = ql.FlatForward(
            datetime_to_ql_date(ref_date),
            0.01,
            cfg["DayCounter"],
            ql.Compounded,
        )
        curve_handle = ql.YieldTermStructureHandle(ql_curve)
        curve_index = cfg["ReferenceRate"](curve_handle)
        return QLIRSwapCurve(
            ql_curve_id=self.curve_name,
            ql_curve_handle=curve_handle,
            ql_curve_index=curve_index,
            meta_data={
                "requested_curve_name": self.curve_name,
                "curve_name": self.curve_name,
                "reference_date": ref_date,
            },
        )

    def _resolve_swap_dates(self, ref_date: datetime.date, tenor: str) -> tuple[datetime.date, datetime.date]:
        cache_key = (ref_date, tenor)
        cached = self._swap_date_cache.get(cache_key)
        if cached is not None:
            return cached

        curve = self._build_flat_curve(ref_date)
        package, _ = IRSwapStructureFunctionMap(curve=curve).apply(
            structure=IRSwapStructure.OUTRIGHT,
            tenor=tenor,
            is_for_timeseries=True,
        )
        if not package:
            raise ValueError(f"Could not resolve spot swap dates for tenor {tenor} on {ref_date}.")
        swap = package[0]
        resolved = (curve.effective_date(swap), curve.maturity_date(swap))
        self._swap_date_cache[cache_key] = resolved
        return resolved

    def _fetch_raw_sdr_trades(
        self,
        *,
        start: datetime.datetime,
        end: datetime.datetime,
        ignore_cache: bool,
    ) -> pd.DataFrame:
        if self.source not in {
            _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER,
            _SOURCE_SDR_USTS_WEBULL_WSJ_LIVE_INTRADAY_SPREADOVER,
        }:
            raise NotImplementedError(f"Raw SDR fetch not implemented for source '{self.source}'.")
        builder = SDRDataBuilder(
            cache_path=str(self._cache_path),
            show_tqdm=self._show_tqdm,
        )
        return builder.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            ts_col="Execution Timestamp",
            ignore_cache=ignore_cache,
        )

    def _apply_oasis_sdr_filters(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        if raw_df.empty:
            return raw_df.copy()

        df = raw_df.copy()
        df["Execution Timestamp"] = pd.to_datetime(df.get("Execution Timestamp"), utc=True, errors="coerce")
        df["Effective Date"] = pd.to_datetime(df.get("Effective Date"), errors="coerce")
        df["Expiration Date"] = pd.to_datetime(df.get("Expiration Date"), errors="coerce")
        df["_fixed_rate"] = _coerce_numeric(_column(df, "Fixed rate-Leg 1"))

        period_checks = (
            ((_column(df, "Floating rate reset frequency period-leg 1").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Floating rate reset frequency period multiplier-leg 1")) == 12))
            | ((_column(df, "Floating rate reset frequency period-leg 2").astype("string") == "YEAR") & (_coerce_numeric(_column(df, "Floating rate reset frequency period multiplier-leg 2")) == 1))
            | ((_column(df, "Floating rate reset frequency period-leg 2").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Floating rate reset frequency period multiplier-leg 2")) == 12))
            | ((_column(df, "Fixed rate payment frequency period-Leg 1").astype("string") == "YEAR") & (_coerce_numeric(_column(df, "Fixed rate payment frequency period multiplier-Leg 1")) == 1))
            | ((_column(df, "Fixed rate payment frequency period-Leg 1").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Fixed rate payment frequency period multiplier-Leg 1")) == 12))
            | ((_column(df, "Fixed rate payment frequency period-Leg 2").astype("string") == "YEAR") & (_coerce_numeric(_column(df, "Fixed rate payment frequency period multiplier-Leg 2")) == 1))
            | ((_column(df, "Fixed rate payment frequency period-Leg 2").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Fixed rate payment frequency period multiplier-Leg 2")) == 12))
            | ((_column(df, "Floating rate payment frequency period-Leg 1").astype("string") == "YEAR") & (_coerce_numeric(_column(df, "Floating rate payment frequency period multiplier-Leg 1")) == 1))
            | ((_column(df, "Floating rate payment frequency period-Leg 1").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Floating rate payment frequency period multiplier-Leg 1")) == 12))
            | ((_column(df, "Floating rate payment frequency period-Leg 2").astype("string") == "YEAR") & (_coerce_numeric(_column(df, "Floating rate payment frequency period multiplier-Leg 2")) == 1))
            | ((_column(df, "Floating rate payment frequency period-Leg 2").astype("string") == "MNTH") & (_coerce_numeric(_column(df, "Floating rate payment frequency period multiplier-Leg 2")) == 12))
        )

        platform = _column(df, "Platform identifier").astype("string").str.strip().str.upper()
        other_payment = _column(df, "Other payment type").astype("string").str.strip().str.upper()
        package_price_notation = _coerce_numeric(_column(df, "Package transaction price notation"))

        mask = (
            _column(df, "Unique Product Identifier").isin(_SOFR_SDR_UPIS)
            & (_column(df, "Action type").astype("string").str.strip().str.upper() == "NEWT")
            & (_column(df, "Event type").astype("string").str.strip().str.upper() == "TRAD")
            & _true_mask(_column(df, "Mandatory clearing indicator"))
            & df["_fixed_rate"].gt(0.0)
            & ~platform.isin(["XOFF", "BILT"])
            & _column(df, "Large notional off-facility swap election indicator").isna()
            & other_payment.ne("UFRO")
            & package_price_notation.ne(1)
            & period_checks.fillna(False)
        )
        return df.loc[mask].copy()

    def _build_full_day_minute_vwap(self, trades: pd.DataFrame, *, trade_day: datetime.date) -> pd.Series:
        if trades.empty:
            return pd.Series(dtype=float)

        work = trades.copy()
        work["_notional"] = _coerce_notional(_column(work, "Notional amount-Leg 1"))
        work["_wx"] = work["_fixed_rate"] * work["_notional"]
        work = work.dropna(subset=["_fixed_rate", "_notional", "_wx"])
        if work.empty:
            return pd.Series(dtype=float)

        minute_vwap = work.resample("1min").agg({"_wx": "sum", "_notional": "sum"})
        minute_vwap["_notional"] = minute_vwap["_notional"].replace(0.0, np.nan)
        minute_vwap["rate"] = minute_vwap["_wx"] / minute_vwap["_notional"]
        minute_vwap = minute_vwap[["rate"]]
        if minute_vwap.empty:
            return pd.Series(dtype=float)

        full_idx = pd.date_range(
            start=datetime.datetime.combine(trade_day, datetime.time(0, 0), tzinfo=self._tz),
            end=datetime.datetime.combine(trade_day, datetime.time(23, 59), tzinfo=self._tz),
            freq="1min",
        )
        return minute_vwap["rate"].reindex(full_idx).ffill().bfill() * 100.0

    def _swap_rate_col(self, tenor: str) -> str:
        return f"{tenor}_SWAP_RATE_PCT"

    def _ust_yield_col(self, tenor: str) -> str:
        return f"{tenor}_UST_YIELD_PCT"

    def _spread_col(self, tenor: str) -> str:
        return f"{tenor}_SWAP_SPREAD_BPS"

    def get_swap_rate_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        tenors: Optional[Sequence[str | IRSwapQuery]] = None,
        *,
        ignore_cache: bool = False,
    ) -> pd.DataFrame:
        start_dt, end_dt = self._normalize_window(start, end)
        resolved_tenors = self._normalize_tenors(tenors)
        raw_df = self._fetch_raw_sdr_trades(start=start_dt, end=end_dt, ignore_cache=ignore_cache)
        filtered = self._apply_oasis_sdr_filters(raw_df)
        if filtered.empty:
            return _empty_frame(self._date_col)

        filtered["Execution Timestamp"] = pd.to_datetime(
            filtered["Execution Timestamp"],
            utc=True,
            errors="coerce",
        ).dt.tz_convert(self._tz)
        filtered = filtered.dropna(subset=["Execution Timestamp", "Effective Date", "Expiration Date"])
        filtered = filtered.set_index("Execution Timestamp").sort_index()

        business_days = self._business_days(start_dt, end_dt)
        per_tenor: dict[str, pd.Series] = {}
        for tenor in resolved_tenors:
            pieces: list[pd.Series] = []
            for trade_day in self._iter_progress(business_days, desc=f"BUILDING {tenor} SDR VWAP"):
                effective_date, maturity_date = self._resolve_swap_dates(trade_day, tenor)
                subset = filtered.loc[filtered.index.date == trade_day]
                if subset.empty:
                    continue
                subset = subset[
                    (subset["Effective Date"].dt.date == effective_date)
                    & (subset["Expiration Date"].dt.date == maturity_date)
                ]
                series = self._build_full_day_minute_vwap(subset, trade_day=trade_day)
                if not series.empty:
                    pieces.append(series)
            if pieces:
                combined = pd.concat(pieces)
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                per_tenor[self._swap_rate_col(tenor)] = combined

        if not per_tenor:
            return _empty_frame(self._date_col)

        out = pd.concat(per_tenor, axis=1).sort_index()
        out.columns.name = None
        out.index.name = self._date_col
        return out.loc[(out.index >= start_dt) & (out.index <= end_dt)]

    def _fetch_wsj_ct_timeseries(
        self,
        *,
        start: datetime.datetime,
        end: datetime.datetime,
        tenors: Sequence[str],
    ) -> pd.DataFrame:
        wsj = WSJFetcher()
        mapping = {
            _WSJ_CT_TICKERS[tenor]: self._ust_yield_col(tenor)
            for tenor in tenors
        }
        wide = wsj.ust_intraday_timeseries(mapping, show_tqdm=self._show_tqdm)
        if wide.empty:
            return _empty_frame(self._date_col)
        wide = wide.sort_index()
        wide.index = wide.index.tz_convert(self._tz)
        wide.index.name = self._date_col
        return wide.loc[(wide.index >= start) & (wide.index <= end)].ffill()

    @staticmethod
    def _ct_alias_for_tenor(tenor: str) -> str:
        return f"CT{str(tenor).upper().replace('Y', '')}"

    def _get_usts_webull_wsj_live_tb(self) -> FixedRateBondsTB:
        if self._usts_webull_wsj_live_tb is None:
            self._usts_webull_wsj_live_mdp = FixedRateBondsMDP(source="USTS_WEBULL_WSJ_LIVE-RL")
            self._usts_webull_wsj_live_tb = FixedRateBondsTB(
                self._usts_webull_wsj_live_mdp,
                show_tqdm=self._show_tqdm,
            )
        return self._usts_webull_wsj_live_tb

    def _fetch_usts_webull_wsj_live_ct_timeseries(
        self,
        *,
        start: datetime.datetime,
        end: datetime.datetime,
        tenors: Sequence[str],
    ) -> pd.DataFrame:
        timestamps = ql_cal_date_range(
            self._calendar,
            start=start,
            end=end,
            freq="1min",
        )
        if not timestamps:
            return _empty_frame(self._date_col)

        queries = [
            FixedRateBondQuery(
                cusip=self._ct_alias_for_tenor(tenor),
                value=FixedRateBondValue.YTM,
            )
            for tenor in tenors
        ]
        rename_map = {
            query.col_name(): self._ust_yield_col(tenor)
            for tenor, query in zip(tenors, queries)
        }

        tb = self._get_usts_webull_wsj_live_tb()
        wide = tb.get_timeseries(
            start=None,
            end=None,
            timestamps=timestamps,
            queries=queries,
            n_jobs=_USTS_WEBULL_INTRADAY_N_JOBS,
        )
        if wide.empty:
            return _empty_frame(self._date_col)
        wide = wide.rename(columns=rename_map).sort_index().ffill()
        wide.index.name = self._date_col
        return wide.loc[(wide.index >= start) & (wide.index <= end)]

    def _fetch_ust_timeseries(
        self,
        *,
        start: datetime.datetime,
        end: datetime.datetime,
        tenors: Sequence[str],
    ) -> pd.DataFrame:
        if self.source == _SOURCE_SDR_WSJ_INTRADAY_SPREADOVER:
            return self._fetch_wsj_ct_timeseries(start=start, end=end, tenors=tenors)
        if self.source == _SOURCE_SDR_USTS_WEBULL_WSJ_LIVE_INTRADAY_SPREADOVER:
            return self._fetch_usts_webull_wsj_live_ct_timeseries(start=start, end=end, tenors=tenors)
        raise NotImplementedError(f"UST fetch not implemented for source '{self.source}'.")

    def _append_smoothing_columns(
        self,
        df: pd.DataFrame,
        *,
        spread_columns: Sequence[str],
        smoothing_window: int,
        deadband_threshold: float,
        deadband_snap: float | None,
    ) -> pd.DataFrame:
        out = df.copy()
        window = max(1, int(smoothing_window))
        for col in spread_columns:
            series = pd.to_numeric(out[col], errors="coerce")
            out[f"{col}_SMA_{window}"] = series.rolling(window=window, min_periods=1).mean()
            out[f"{col}_EMA_{window}"] = series.ewm(span=window, adjust=False).mean()
            out[f"{col}_MEDIAN_{window}"] = series.rolling(window=window, min_periods=1).median()
            out[f"{col}_STEP"] = deadband_step_filter(
                series,
                threshold=float(deadband_threshold),
                snap=deadband_snap,
            )
        return out

    def get_timeseries(
        self,
        start: DateLike,
        end: DateLike,
        tenors: Optional[Sequence[str | IRSwapQuery]] = None,
        *,
        ignore_cache: bool = False,
        include_components: bool = False,
        smoothing_window: int = 20,
        deadband_threshold: float = 0.33,
        deadband_snap: float | None = 0.25,
    ) -> pd.DataFrame:
        start_dt, end_dt = self._normalize_window(start, end)
        resolved_tenors = self._normalize_tenors(tenors)

        swap_df = self.get_swap_rate_timeseries(
            start=start_dt,
            end=end_dt,
            tenors=resolved_tenors,
            ignore_cache=ignore_cache,
        )
        ust_df = self._fetch_ust_timeseries(
            start=start_dt,
            end=end_dt,
            tenors=resolved_tenors,
        )
        if swap_df.empty or ust_df.empty:
            return _empty_frame(self._date_col)

        combined = pd.concat([swap_df, ust_df], axis=1).sort_index().ffill()
        spread_columns: list[str] = []
        for tenor in resolved_tenors:
            swap_col = self._swap_rate_col(tenor)
            ust_col = self._ust_yield_col(tenor)
            if swap_col not in combined.columns or ust_col not in combined.columns:
                continue
            spread_col = self._spread_col(tenor)
            combined[spread_col] = (combined[swap_col] - combined[ust_col]) * 100.0
            spread_columns.append(spread_col)

        if not spread_columns:
            return _empty_frame(self._date_col)

        combined = self._append_smoothing_columns(
            combined,
            spread_columns=spread_columns,
            smoothing_window=smoothing_window,
            deadband_threshold=deadband_threshold,
            deadband_snap=deadband_snap,
        )
        combined = combined.loc[(combined.index >= start_dt) & (combined.index <= end_dt)]
        combined.index.name = self._date_col

        if include_components:
            ordered_cols: list[str] = []
            for tenor in resolved_tenors:
                component_cols = [
                    self._swap_rate_col(tenor),
                    self._ust_yield_col(tenor),
                    self._spread_col(tenor),
                    f"{self._spread_col(tenor)}_SMA_{max(1, int(smoothing_window))}",
                    f"{self._spread_col(tenor)}_EMA_{max(1, int(smoothing_window))}",
                    f"{self._spread_col(tenor)}_MEDIAN_{max(1, int(smoothing_window))}",
                    f"{self._spread_col(tenor)}_STEP",
                ]
                ordered_cols.extend([col for col in component_cols if col in combined.columns])
            return combined[ordered_cols]

        ordered_spread_cols: list[str] = []
        for tenor in resolved_tenors:
            spread_col = self._spread_col(tenor)
            ordered_spread_cols.extend(
                [
                    col
                    for col in (
                        spread_col,
                        f"{spread_col}_SMA_{max(1, int(smoothing_window))}",
                        f"{spread_col}_EMA_{max(1, int(smoothing_window))}",
                        f"{spread_col}_MEDIAN_{max(1, int(smoothing_window))}",
                        f"{spread_col}_STEP",
                    )
                    if col in combined.columns
                ]
            )
        return combined[ordered_spread_cols]


__all__ = [
    "IRSwapSpreadsTB",
    "deadband_step_filter",
]
