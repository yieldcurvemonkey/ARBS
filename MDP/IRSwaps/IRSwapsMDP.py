import contextlib
import datetime
import io
import os
import sys
import threading
import logging
import re
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Union

import pandas as pd
import pytz
import tqdm 

from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricable import _GenericPricable
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


class IRSwapsMDP(MarketDataProvider[_GenericPricable]):
    _DEFAULT_GRID_FWDS: tuple[str, ...] = ("Spot", "1M", "3M", "6M", "1Y", "2Y", "5Y", "7Y", "10Y")
    _DEFAULT_GRID_SWAP_TENORS: tuple[str, ...] = ("1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "8Y", "9Y", "10Y", "15Y", "20Y", "25Y", "30Y")
    _BARCHART_STIRF_STATE: Dict[str, Any] = {
        "builder": None,
        "lock": threading.RLock(),
        "io_lock": threading.RLock(),
    }
    _CURVE_STORE_STATE: Dict[str, Any] = {
        "store": None,
        "lock": threading.Lock(),
    }
    _CITIVELO_STATE: Dict[str, Any] = {
        "fetchers": {},
        "lock": threading.RLock(),
    }
    _CITIVELO_STORE_ASSET: str = "USD-SOFR-1D-CITIVELO"
    _ERIS_LIVE_STORE_ASSET: str = "USD-SOFR-1D-ERISLIVE"
    _GSQUANT_IGNORED_DATES_BY_CURVE: Dict[str, frozenset[datetime.date]] = {
        "USD-OIS": frozenset(
            datetime.date.fromisoformat(date_str)
            for date_str in (
                "2012-01-02", "2012-01-16", "2012-02-20", "2012-04-06", "2012-05-28", "2012-07-04", "2012-09-03",
                "2012-11-22", "2012-12-25",
                "2013-01-01", "2013-01-21", "2013-02-18", "2013-03-29", "2013-05-27", "2013-07-04", "2013-09-02",
                "2013-11-28", "2013-12-25",
                "2014-01-01", "2014-01-20", "2014-02-17", "2014-02-26", "2014-04-18", "2014-05-26", "2014-07-04",
                "2014-09-01", "2014-11-27", "2014-12-25",
                "2015-01-01", "2015-01-19", "2015-02-16", "2015-04-03", "2015-05-25", "2015-07-03", "2015-09-07",
                "2015-11-26", "2015-12-25",
                "2016-01-01", "2016-01-18", "2016-02-15", "2016-03-25", "2016-05-30", "2016-07-04", "2016-09-05",
                "2016-11-24", "2016-12-26",
                "2017-01-02", "2017-01-16", "2017-02-20", "2017-04-14", "2017-05-29", "2017-07-04", "2017-09-04",
                "2017-11-23", "2017-12-25",
                "2018-01-01", "2018-01-15", "2018-02-19", "2018-03-30", "2018-05-28", "2018-07-04", "2018-09-03",
                "2018-11-22", "2018-12-25",
                "2019-01-01", "2019-01-21", "2019-02-18", "2019-04-19", "2019-05-27", "2019-07-04", "2019-09-02",
                "2019-11-28", "2019-12-25",
                "2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10", "2020-05-25", "2020-07-03", "2020-09-07",
                "2020-11-26", "2020-12-25",
                "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31", "2021-07-05", "2021-09-06",
                "2021-11-25", "2021-12-24", "2021-12-31",
                "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-04", "2022-05-30", "2022-06-20", "2022-07-04",
                "2022-09-05", "2022-10-10", "2022-11-11", "2022-11-24", "2022-12-26",
                "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19",
                "2023-07-04", "2023-09-04", "2023-10-09", "2023-11-23", "2023-12-25",
                "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19",
                "2024-07-04", "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28", "2024-12-25",
                "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
                "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
                "2026-01-01", "2026-01-19", "2026-02-16",
            )
        )
    }

    def __init__(self, source: str = "CME_NY_EOD_LIVE-ql_basic", force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
        super().__init__(source, **kwargs)
        self.force_refresh_fixings = force_refresh_fixings

        if "SDR_INTRADAY-RL" in source.upper() or "SDR_INTRADAY_RL" in source.upper() or "SDR_3PM_EOD-RL" in source.upper() or "SDR_3PM_EOD_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="SDR_INTRADAY-RL_CURVE_CACHE")

        if "ERIS_EOD_LIVE-RL_BASIC" in source.upper() or "ERIS_EOD_LIVE_RL_BASIC" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="ERIS_EOD_LIVE-RL_BASIC")

        if "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS" in source.upper() or "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")

        if "GSQUANT-RL" in source.upper() or "GSQUANT_RL" in source.upper():
            from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils._RLCurveCache import _RLCurveCache

            self._rl_curve_cache = _RLCurveCache(cache_name="GSQUANT-RL_CURVE_CACHE")

    @staticmethod
    def _get_curve_store() -> Any:
        S = IRSwapsMDP._CURVE_STORE_STATE
        with S["lock"]:
            if S["store"] is None:
                from Caching.curve_store import CurveStore

                S["store"] = CurveStore.default()
            return S["store"]

    def _get_barchart_stirf_curve_builder(self) -> Any:
        from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

        S = IRSwapsMDP._BARCHART_STIRF_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

    def _get_citivelo_fetcher(self, *, workbook_path: str, curve_id: str = "USD-SOFR-1D") -> Any:
        """Lazily build + cache a CitiVelocityIntradayFetcher per (workbook, curve).

        The fetcher parses the workbook once and memoizes built curves internally,
        so reusing it across get_pricer / bulk_get_data calls avoids re-reading the
        ~1-2s xlsx on every request (mirrors the BARCHART_STIRF builder cache).
        """
        S = IRSwapsMDP._CITIVELO_STATE
        key = (str(workbook_path), str(curve_id))
        with S["lock"]:
            fetcher = S["fetchers"].get(key)
            if fetcher is None:
                from MDP.IRSwaps.CITI_VELOCITY_INTRADAY import CitiVelocityIntradayFetcher

                fetcher = CitiVelocityIntradayFetcher(workbook_path, curve_id=curve_id)
                S["fetchers"][key] = fetcher
            return fetcher

    def _load_citivelo_curve_store_point(
        self,
        *,
        requested_curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        method: str = "nearest",
    ) -> Optional["_IRSwapGenericCurve"]:
        """Serve a CitiVelo curve from the CurveStore (local parquet / Supabase L2).

        Reconstructs the stored snapshot nearest ``timestamp`` from the ET
        calendar-date partition of the ``USD-SOFR-1D-CITIVELO`` asset — no
        workbook parsing. ``timestamp="live"`` uses the latest partition/row.
        Returns ``None`` when the store has no data for that day (the caller
        decides whether to fall back to the workbook).
        """
        import pytz
        from pathlib import Path

        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        ASSET = self._CITIVELO_STORE_ASSET
        NYC = pytz.timezone("America/New_York")
        store = self._get_curve_store()

        if timestamp == "live":
            asset_dir = Path(store._base_dir) / "raw" / f"asset={ASSET}"
            parts = sorted(asset_dir.glob("date=*")) if asset_dir.exists() else []
            if not parts:
                return None
            et_date = datetime.date.fromisoformat(parts[-1].name.split("=", 1)[1])
            target_utc = None
        else:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize(NYC)  # naive assumed ET (workbook source tz)
            et_date = ts.tz_convert(NYC).date()
            target_utc = ts.tz_convert("UTC")

        if not store.has_day(ASSET, et_date):
            return None
        raw = store.read_raw_day(ASSET, et_date)
        if raw is None or getattr(raw, "empty", True):
            return None

        tvec = pd.to_datetime(raw["timestamp_utc"], utc=True).reset_index(drop=True)
        if target_utc is None:
            pos = len(tvec) - 1
        elif method == "exact":
            hits = tvec.index[tvec == target_utc]
            if len(hits) == 0:
                return None
            pos = int(hits[0])
        elif method == "asof":
            le = tvec[tvec <= target_utc]
            if le.empty:
                return None
            pos = int(le.idxmax())
        else:  # nearest
            pos = int((tvec - target_utc).abs().values.argmin())

        row = raw.iloc[[pos]]
        curves = store.reconstruct_curves_batch(row, cfg=None, max_workers=1)
        if not curves:
            return None
        rl_curve_handle = next(iter(curves.values()))

        snap_et = tvec.iloc[pos].tz_convert(NYC)
        ref = snap_et.date()
        ts_out = snap_et.tz_localize(None).to_pydatetime()  # naive ET (matches workbook path)

        sofr_fixings = _fetch_fixings(
            as_of_date=ref, curve_name=requested_curve_name, force_refresh=self.force_refresh_fixings
        ).sort_index()
        sofr_fixings = sofr_fixings[sofr_fixings.index.date < ref] * 100

        curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_out}"
        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=sofr_fixings,
            meta_data={"timestamp": ts_out, "id": curve_id, "source": "curve_store"},
        )

    def _load_eris_live_intraday_point(
        self,
        *,
        requested_curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        method: str = "asof",
        sync: Optional["SupabaseCurveSync"] = None,
    ) -> Optional["_IRSwapGenericCurve"]:
        """Serve a stored ERIS-live intraday curve from arbs_curve_snapshots_v1.

        Reads one row by indexed as-of SQL (no whole-day materialization),
        reconstructs the rl.Curve, and wraps it as an RLIRSwapCurve.
        Returns None when the store has no matching row. Pass ``sync`` to reuse
        a single ``SupabaseCurveSync`` across a bulk read (see ``bulk_get_data``).
        """
        import pytz

        from Caching.curve_store import CurveStore
        from Caching.supabase_curve_sync import SupabaseCurveSync
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        assert requested_curve_name == "USD-SOFR-1D", "ERIS live intraday is USD-SOFR-1D only"
        ASSET = self._ERIS_LIVE_STORE_ASSET
        NYC = pytz.timezone("America/New_York")
        if sync is None:
            sync = SupabaseCurveSync.from_defaults()

        if timestamp == "live":
            row = sync.pull_latest_snapshot(ASSET)
        else:
            ts = pd.Timestamp(timestamp)
            if ts.tzinfo is None:
                ts = ts.tz_localize(NYC)  # naive assumed ET
            row = sync.pull_snapshot_asof(ASSET, ts.tz_convert("UTC").to_pydatetime(), method)
        if row is None:
            return None

        rl_curve_handle = CurveStore.reconstruct_curve(row, cfg=None)

        snap_utc = pd.Timestamp(row["timestamp_utc"])
        if snap_utc.tzinfo is None:
            snap_utc = snap_utc.tz_localize("UTC")
        snap_et = snap_utc.tz_convert(NYC)
        ref = snap_et.date()
        ts_out = snap_et.to_pydatetime()

        sofr_fixings = _fetch_fixings(
            as_of_date=ref, curve_name=requested_curve_name, force_refresh=self.force_refresh_fixings
        ).sort_index()
        sofr_fixings = sofr_fixings[sofr_fixings.index.date < ref] * 100

        curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_out}"
        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=sofr_fixings,
            meta_data={"timestamp": ts_out, "id": curve_id, "source": "eris_live_intraday"},
        )

    @staticmethod
    def _eris_local_l1_enabled() -> bool:
        """Whether to use the read-only local Parquet L1 cache for
        eris_live_intraday settled-day curve reads (default on)."""
        return os.environ.get("ARBS_ERIS_LOCAL_CURVE_L1", "1").strip().lower() not in (
            "0", "false", "no", "off", ""
        )

    def _ensure_eris_day_local(self, store, sync, asset, trading_date, today_et):
        """Snapshot rows for one SETTLED ET trading_date, served from (and
        populated once, on first touch) a read-only local Parquet L1 mirroring the
        BARCHART_STIRF curve cache. Returns empty for today/future (still
        appending) so the caller does a remote windowed read instead. The L1
        materialize is local-only (push_l2=False) — no whole-day blob re-push."""
        import pandas as pd
        import pytz

        if store.has_day(asset, trading_date):
            # local hit — partition exists, so read_raw_day won't hit the blob fallback
            return store.read_raw_day(asset, trading_date)
        if trading_date >= today_et:
            return pd.DataFrame()  # incomplete day -> caller reads remote
        df = sync.pull_snapshots_day(asset, trading_date)
        if df is None or df.empty:
            return pd.DataFrame()

        from Caching.curve_store import CurveSnapshot

        _CHI = pytz.timezone("America/Chicago")
        snaps = []
        for _, r in df.iterrows():
            ts_utc = pd.Timestamp(r["timestamp_utc"])
            ts_utc = ts_utc.tz_localize("UTC") if ts_utc.tzinfo is None else ts_utc.tz_convert("UTC")
            snaps.append(
                CurveSnapshot(
                    timestamp_utc=ts_utc.to_pydatetime(),
                    timestamp_local=ts_utc.tz_convert(_CHI).to_pydatetime(),
                    trading_date=trading_date,
                    session_minute=int(r["session_minute"]),
                    curve_name=asset,
                    cfg_hash="",
                    reference_key=str(r["reference_key"]),
                    interpolation=str(r["interpolation"]),
                    source_variant=str(r["source_variant"]),
                    node_dates=list(r["node_dates"]),
                    discount_factors=[float(v) for v in r["discount_factors"]],
                )
            )
        snaps.sort(key=lambda s: s.timestamp_utc)
        store.write_day(asset, trading_date, snaps, overwrite=True, push_l2=False)
        return store.read_raw_day(asset, trading_date)

    def _curve_store_source_family(self) -> Optional[str]:
        source = str(self.source).upper()
        if source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
            return "barchart_stirf"
        if source in {"GSQUANT-RL", "GSQUANT_RL"}:
            return "gsquant_rl"
        if source in {"ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"}:
            return "eris_eod_rl_basic"
        if source in {"ERIS_EOD_LIVE-RL_BASIC-NOJUMPS", "ERIS_EOD_LIVE_RL_BASIC-NOJUMPS"}:
            return "eris_eod_rl_basic_nojumps"
        return None

    def _supports_curve_store_fast_path(self) -> bool:
        return self._curve_store_source_family() in {
            "barchart_stirf",
            "gsquant_rl",
            "eris_eod_rl_basic",
            "eris_eod_rl_basic_nojumps",
        }

    def _supports_curve_store_raw_curve_fast_path(self) -> bool:
        return self._curve_store_source_family() in {
            "barchart_stirf",
            "gsquant_rl",
            "eris_eod_rl_basic",
        }

    def _supports_curve_store_analytics_fast_path(self) -> bool:
        return self._curve_store_source_family() in {
            "barchart_stirf",
            "gsquant_rl",
            "eris_eod_rl_basic",
            "eris_eod_rl_basic_nojumps",
        }

    def _supports_curve_store_session_minute_filter(self) -> bool:
        return self._curve_store_source_family() == "barchart_stirf"

    def _curve_store_match_on_trading_date(self) -> bool:
        return self._curve_store_source_family() in {
            "gsquant_rl",
            "eris_eod_rl_basic",
            "eris_eod_rl_basic_nojumps",
        }

    def _get_curve_store_builder(self) -> Any:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._get_barchart_stirf_curve_builder()
        return None

    def _resolve_curve_store_curve_name(
        self,
        requested_curve_name: str,
        kwargs: Dict[str, Any],
        builder: Any = None,
    ) -> str:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._resolve_barchart_stirf_curve_name(
                requested_curve_name=requested_curve_name,
                kwargs=kwargs,
                builder=builder or self._get_barchart_stirf_curve_builder(),
            )
        return requested_curve_name

    @staticmethod
    def _to_eris_eod_timestamp(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        if timestamp == "live":
            return "live"

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        ny_tz = pytz.timezone("America/New_York")
        if isinstance(timestamp, datetime.datetime):
            if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
                timestamp = ny_tz.localize(timestamp)
            else:
                timestamp = timestamp.astimezone(ny_tz)
            return ny_tz.localize(
                datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0)
            )

        if isinstance(timestamp, datetime.date):
            return ny_tz.localize(
                datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 0)
            )

        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    def _to_curve_store_timestamp(
        self,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._to_barchart_stirf_timestamp(timestamp)
        if family == "gsquant_rl":
            return self._to_eris_eod_timestamp(timestamp)
        if family in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return self._to_eris_eod_timestamp(timestamp)
        raise NotImplementedError(f"CurveStore timestamps not supported for source '{self.source}'")

    def _curve_store_cfg(self, resolved_curve_name: str, builder: Any = None) -> Optional[Dict[str, Any]]:
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            active_builder = builder or self._get_barchart_stirf_curve_builder()
            return getattr(active_builder, "_STIRF_CURVE_CONFIGS", {}).get(resolved_curve_name)
        return None

    def _curve_calendar(self, curve_name: str) -> Any:
        from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS

        if curve_name in QUANTLIB_CURVE_DEFINITIONS:
            return QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"]
        if "USD" in str(curve_name).upper() and "USD-OIS" in QUANTLIB_CURVE_DEFINITIONS:
            return QUANTLIB_CURVE_DEFINITIONS["USD-OIS"]["Calendar"]
        return None

    @staticmethod
    def _request_calendar_date(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> datetime.date:
        if timestamp == "live":
            return datetime.date.today()
        if isinstance(timestamp, pd.Timestamp):
            return timestamp.date()
        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()
        if isinstance(timestamp, datetime.date):
            return timestamp
        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    def _requires_strict_eod_calendar_validation(self) -> bool:
        source = str(self.source).upper()
        if source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
            return False
        if "INTRADAY" in source and "EOD" not in source:
            return False
        if source in {"GSQUANT-RL", "GSQUANT_RL"}:
            return True
        return "EOD" in source

    def _validate_eod_curve_request_timestamp(
        self,
        *,
        curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

        calendar = self._curve_calendar(curve_name)
        if calendar is None:
            return

        request_date = self._request_calendar_date(timestamp)
        if not calendar.isBusinessDay(datetime_to_ql_date(request_date)):
            raise ValueError(f"{timestamp} is not a business day in the {calendar}!")

    def _validate_barchart_stirf_request_timestamp(
        self,
        *,
        curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

        calendar = self._curve_calendar(curve_name)
        if calendar is None:
            return

        rl_timestamp = self._to_barchart_stirf_timestamp(timestamp)
        if rl_timestamp == "live":
            return

        builder = self._get_barchart_stirf_curve_builder()
        trading_date = builder._trading_date_for_timestamp(rl_timestamp)
        if not calendar.isBusinessDay(datetime_to_ql_date(trading_date)):
            raise ValueError(f"{timestamp} maps to non-business trading date {trading_date} in the {calendar}!")

    def _validate_curve_request_timestamp(
        self,
        *,
        curve_name: str,
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        source = str(self.source).upper()
        if source in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
            self._validate_barchart_stirf_request_timestamp(curve_name=curve_name, timestamp=timestamp)
            return
        if self._requires_strict_eod_calendar_validation():
            self._validate_eod_curve_request_timestamp(curve_name=curve_name, timestamp=timestamp)

    def _build_fixings_cache_for_dates(
        self,
        *,
        curve_name: str,
        as_of_dates: Iterable[datetime.date],
    ) -> Dict[datetime.date, pd.Series]:
        unique_dates = sorted({d for d in as_of_dates if isinstance(d, datetime.date)})
        if not unique_dates:
            return {}

        max_ref = max(unique_dates)
        full_fixings = _fetch_fixings(
            as_of_date=max_ref,
            curve_name=curve_name,
            force_refresh=self.force_refresh_fixings,
        ).sort_index()
        full_fixings = full_fixings * 100.0

        out: Dict[datetime.date, pd.Series] = {}
        for ref_date in unique_dates:
            out[ref_date] = full_fixings[full_fixings.index.date < ref_date]
        return out

    @staticmethod
    def _to_gsquant_eod_date(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> datetime.date:
        if timestamp == "live":
            return datetime.date.today()
        if isinstance(timestamp, pd.Timestamp):
            return timestamp.date()
        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()
        if isinstance(timestamp, datetime.date):
            return timestamp
        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    def _build_gsquant_rl_curve(
        self,
        *,
        requested_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        pricing_location: Optional[str],
        curve_id: str,
        fixings_cache: Optional[Dict[datetime.date, pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        ref_date = self._to_gsquant_eod_date(request_timestamp)
        reference_curve_name = self._resolve_gsquant_reference_curve_name(requested_curve_name)

        fixings_series = None if fixings_cache is None else fixings_cache.get(ref_date)
        if fixings_series is None:
            fixings_series = _fetch_fixings(
                as_of_date=ref_date,
                curve_name=reference_curve_name,
                force_refresh=self.force_refresh_fixings,
            ).sort_index()
            fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0
            if fixings_cache is not None:
                fixings_cache[ref_date] = fixings_series

        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings_series,
            meta_data={
                "timestamp": ref_date,
                "id": curve_id,
                "pricing_location": pricing_location,
                "curve_name": requested_curve_name,
                "requested_curve_name": requested_curve_name,
                "reference_curve_name": reference_curve_name,
            },
        )

    def _build_eris_eod_rl_curve(
        self,
        *,
        requested_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        fixings_cache: Optional[Dict[datetime.date, pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        import rateslib as rl

        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
        from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

        if request_timestamp == "live":
            ref_date = datetime.date.today()
        elif isinstance(request_timestamp, pd.Timestamp):
            ref_date = request_timestamp.date()
        elif isinstance(request_timestamp, datetime.datetime):
            ref_date = request_timestamp.date()
        else:
            ref_date = request_timestamp

        fixings_series = None if fixings_cache is None else fixings_cache.get(ref_date)
        if fixings_series is None:
            fixings_series = _fetch_fixings(
                as_of_date=ref_date,
                curve_name=requested_curve_name,
                force_refresh=self.force_refresh_fixings,
            ).sort_index()
            fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0
            if fixings_cache is not None:
                fixings_cache[ref_date] = fixings_series

        curve_def = RATESLIB_CURVE_DEFINITIONS[requested_curve_name]
        cal = curve_def.get("Calendar", None)
        if cal is not None:
            try:
                rl_curve_handle.calendar = cal
            except Exception:
                rl_curve_handle = rl.Curve(
                    nodes=dict(rl_curve_handle.nodes.nodes),
                    calendar=cal,
                    id=getattr(rl_curve_handle, "id", None),
                )

        ts_meta = getattr(rl_curve_handle, "timestamp", None) or getattr(rl_curve_handle, "timestamp_utc", None)
        if ts_meta is None:
            ts_meta = self._to_eris_eod_timestamp(request_timestamp)
        curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_meta}"
        return RLIRSwapCurve(
            rl_curve_id=requested_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings_series,
            meta_data={
                "timestamp": ts_meta,
                "id": curve_id,
                "requested_curve_name": requested_curve_name,
                "curve_name": requested_curve_name,
                "reference_curve_name": requested_curve_name,
            },
        )

    def _eris_curve_store_source_variant(self) -> str:
        family = self._curve_store_source_family()
        if family == "eris_eod_rl_basic_nojumps":
            return "ERIS_RL_BASIC_NOJUMPS"
        return "ERIS_RL_BASIC"

    @staticmethod
    def _gsquant_curve_store_source_variant() -> str:
        return "GSQUANT_RL"

    def _promote_eris_curve_store_day(
        self,
        *,
        requested_curve_name: str,
        curve: Any,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        family = self._curve_store_source_family()
        if family not in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return
        if request_timestamp == "live":
            return

        store = self._get_curve_store()
        trading_date = (
            request_timestamp.date()
            if isinstance(request_timestamp, (datetime.datetime, pd.Timestamp))
            else request_timestamp
        )
        if trading_date is None:
            return

        need_raw = not bool(getattr(store, "has_day")(requested_curve_name, trading_date))
        has_analytics = getattr(store, "has_analytics_day", None)
        need_analytics = not bool(has_analytics(requested_curve_name, trading_date)) if callable(has_analytics) else True
        if not need_raw and not need_analytics:
            return

        ts_meta = None
        if hasattr(curve, "meta") and callable(curve.meta):
            ts_meta = (curve.meta() or {}).get("timestamp")
        ts_local = self._to_eris_eod_timestamp(ts_meta or request_timestamp)
        if ts_local == "live":
            return
        ts_utc = ts_local.astimezone(pytz.UTC)
        ts_chi = ts_utc.astimezone(pytz.timezone("America/Chicago"))

        rl_curve_handle = curve.handle() if hasattr(curve, "handle") else None
        if rl_curve_handle is None:
            return

        try:
            rl_curve_handle.timestamp = ts_local
            rl_curve_handle.timestamp_utc = ts_utc
        except Exception:
            pass

        if need_raw:
            from Caching.curve_store import CurveSnapshot

            raw_nodes: dict = (
                rl_curve_handle.nodes._nodes
                if hasattr(rl_curve_handle, "nodes") and hasattr(rl_curve_handle.nodes, "_nodes")
                else dict(getattr(rl_curve_handle, "nodes", {}) or {})
            )
            node_dates_sorted = sorted(raw_nodes.keys())
            node_dates = [
                d.date() if hasattr(d, "date") else d
                for d in node_dates_sorted
            ]
            discount_factors = [float(raw_nodes[d]) for d in node_dates_sorted]
            snapshot = CurveSnapshot(
                timestamp_utc=ts_utc,
                timestamp_local=ts_chi,
                trading_date=trading_date,
                session_minute=int((ts_chi - ts_chi.replace(hour=6, minute=0, second=0, microsecond=0)).total_seconds() // 60),
                curve_name=requested_curve_name,
                cfg_hash="",
                reference_key=str(getattr(rl_curve_handle, "id", "") or requested_curve_name),
                interpolation=str(getattr(rl_curve_handle, "interpolation", "log_linear") or "log_linear"),
                source_variant=self._eris_curve_store_source_variant(),
                node_dates=node_dates,
                discount_factors=discount_factors,
            )
            store.write_day(requested_curve_name, trading_date, [snapshot])

        if need_analytics:
            from Caching.curve_analytics import build_analytics_frame, compute_analytics_row

            analytics_df = build_analytics_frame(
                [
                    compute_analytics_row(
                        curve,
                        timestamp_utc=ts_utc,
                        trading_date=trading_date,
                    )
                ]
            )
            if not analytics_df.empty:
                store.write_analytics_day(requested_curve_name, trading_date, analytics_df)

    def _promote_gsquant_curve_store_day(
        self,
        *,
        requested_curve_name: str,
        curve: Any,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> None:
        if self._curve_store_source_family() != "gsquant_rl":
            return
        if request_timestamp == "live":
            return

        store = self._get_curve_store()
        trading_date = (
            request_timestamp.date()
            if isinstance(request_timestamp, (datetime.datetime, pd.Timestamp))
            else request_timestamp
        )
        if trading_date is None:
            return

        has_day = getattr(store, "has_day", None)
        raw_present = bool(has_day(requested_curve_name, trading_date)) if callable(has_day) else False
        need_raw = not raw_present or not self._curve_store_day_has_valid_raw_nodes(
            store=store,
            curve_name=requested_curve_name,
            trading_date=trading_date,
        )
        has_analytics = getattr(store, "has_analytics_day", None)
        need_analytics = not bool(has_analytics(requested_curve_name, trading_date)) if callable(has_analytics) else True
        if not need_raw and not need_analytics:
            return

        ts_meta = None
        if hasattr(curve, "meta") and callable(curve.meta):
            ts_meta = (curve.meta() or {}).get("timestamp")
        ts_local = self._to_eris_eod_timestamp(ts_meta or request_timestamp)
        if ts_local == "live":
            return
        ts_utc = ts_local.astimezone(pytz.UTC)
        ts_chi = ts_utc.astimezone(pytz.timezone("America/Chicago"))

        rl_curve_handle = curve.handle() if hasattr(curve, "handle") else None
        if rl_curve_handle is None:
            return

        try:
            rl_curve_handle.timestamp = ts_local
            rl_curve_handle.timestamp_utc = ts_utc
        except Exception:
            pass

        if need_raw:
            from Caching.curve_store import CurveSnapshot

            raw_nodes: dict = (
                rl_curve_handle.nodes._nodes
                if hasattr(rl_curve_handle, "nodes") and hasattr(rl_curve_handle.nodes, "_nodes")
                else dict(getattr(rl_curve_handle, "nodes", {}) or {})
            )
            node_dates_sorted = sorted(raw_nodes.keys())
            node_dates = [
                d.date() if hasattr(d, "date") else d
                for d in node_dates_sorted
            ]
            discount_factors = [float(raw_nodes[d]) for d in node_dates_sorted]
            snapshot = CurveSnapshot(
                timestamp_utc=ts_utc,
                timestamp_local=ts_chi,
                trading_date=trading_date,
                session_minute=int((ts_chi - ts_chi.replace(hour=6, minute=0, second=0, microsecond=0)).total_seconds() // 60),
                curve_name=requested_curve_name,
                cfg_hash="",
                reference_key=self._resolve_gsquant_reference_curve_name(requested_curve_name),
                interpolation=str(getattr(rl_curve_handle, "interpolation", "log_linear") or "log_linear"),
                source_variant=self._gsquant_curve_store_source_variant(),
                node_dates=node_dates,
                discount_factors=discount_factors,
            )
            store.write_day(requested_curve_name, trading_date, [snapshot])

        if need_analytics:
            from Caching.curve_analytics import build_analytics_frame, compute_analytics_row

            analytics_df = build_analytics_frame(
                [
                    compute_analytics_row(
                        curve,
                        timestamp_utc=ts_utc,
                        trading_date=trading_date,
                    )
                ]
            )
            if not analytics_df.empty:
                store.write_analytics_day(requested_curve_name, trading_date, analytics_df)

    def _wrap_curve_store_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        builder: Any = None,
        fixings_cache: Optional[Dict[Any, pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        family = self._curve_store_source_family()
        if family == "barchart_stirf":
            return self._build_barchart_stirf_rl_curve(
                requested_curve_name=requested_curve_name,
                resolved_curve_name=resolved_curve_name,
                request_timestamp=request_timestamp,
                rl_curve_handle=rl_curve_handle,
                builder=builder or self._get_barchart_stirf_curve_builder(),
                fixings_cache=fixings_cache,
            )
        if family in {"eris_eod_rl_basic", "eris_eod_rl_basic_nojumps"}:
            return self._build_eris_eod_rl_curve(
                requested_curve_name=requested_curve_name,
                request_timestamp=request_timestamp,
                rl_curve_handle=rl_curve_handle,
                fixings_cache=fixings_cache,
            )
        if family == "gsquant_rl":
            ts_meta = getattr(rl_curve_handle, "timestamp", None) or getattr(rl_curve_handle, "timestamp_utc", None)
            if ts_meta is None:
                ts_meta = self._to_eris_eod_timestamp(request_timestamp)
            curve_id = f"{self.source.upper()}-{requested_curve_name}-{ts_meta}"
            return self._build_gsquant_rl_curve(
                requested_curve_name=requested_curve_name,
                request_timestamp=request_timestamp,
                rl_curve_handle=rl_curve_handle,
                pricing_location=None,
                curve_id=curve_id,
                fixings_cache=fixings_cache,
            )
        raise NotImplementedError(f"CurveStore wrapper not supported for source '{self.source}'")

    @staticmethod
    def _curve_store_timestamp_key(
        value: Union[datetime.datetime, pd.Timestamp, Any],
    ) -> Optional[datetime.datetime]:
        if value is None:
            return None
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if not isinstance(value, datetime.datetime):
            return None
        if value.tzinfo is None:
            value = pytz.UTC.localize(value)
        else:
            value = value.astimezone(pytz.UTC)
        return value.replace(microsecond=0)

    @staticmethod
    def _resolve_curve_store_history_workers(
        max_workers: int,
        *,
        task_count: int,
    ) -> int:
        requested_workers = max(1, int(max_workers or 1))
        if requested_workers > 1 or task_count < 64:
            return requested_workers
        return max(2, min(int(task_count), int(os.cpu_count() or 4), 8))

    @staticmethod
    def _curve_store_row_has_nodes(row: Any) -> bool:
        node_dates = None
        discount_factors = None
        if isinstance(row, dict):
            node_dates = row.get("node_dates")
            discount_factors = row.get("discount_factors")
        else:
            node_dates = getattr(row, "node_dates", None)
            discount_factors = getattr(row, "discount_factors", None)
        try:
            if node_dates is None or discount_factors is None:
                return False
            return len(node_dates) > 0 and len(discount_factors) > 0
        except Exception:
            return False

    def _curve_store_day_has_valid_raw_nodes(
        self,
        *,
        store: Any,
        curve_name: str,
        trading_date: datetime.date,
    ) -> bool:
        raw_df = pd.DataFrame()
        try:
            if hasattr(store, "read_raw_day"):
                raw_df = store.read_raw_day(curve_name, trading_date)
            elif hasattr(store, "read_raw_nodes"):
                raw_df = store.read_raw_nodes(curve_name, start=trading_date, end=trading_date)
        except Exception:
            return False
        if raw_df is None or raw_df.empty:
            return False
        return any(self._curve_store_row_has_nodes(row) for row in raw_df.to_dict("records"))

    def _load_barchart_stirf_curve_store_point(
        self,
        *,
        requested_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        builder: Any = None,
        fixings_cache: Optional[Dict[Any, pd.Series]] = None,
        allow_prior_timestamp: bool = False,
        max_lookback_days: int = 7,
    ) -> Optional["_IRSwapGenericCurve"]:
        rl_timestamp = self._to_barchart_stirf_timestamp(request_timestamp)
        if rl_timestamp == "live":
            return None

        active_builder = builder or self._get_barchart_stirf_curve_builder()
        resolved_curve_name = self._resolve_barchart_stirf_curve_name(
            requested_curve_name=requested_curve_name,
            kwargs={},
            builder=active_builder,
        )
        store = self._get_curve_store()
        raw_df = pd.DataFrame()
        if hasattr(store, "read_raw_nodes"):
            raw_df = store.read_raw_nodes(
                resolved_curve_name,
                timestamps_utc=[rl_timestamp],
            )

        requested_key = self._curve_store_timestamp_key(rl_timestamp)
        if requested_key is None:
            return None

        def _wrap_single_row(
            candidate_df: pd.DataFrame,
            *,
            target_key: datetime.datetime,
        ) -> Optional["_IRSwapGenericCurve"]:
            if candidate_df is None or candidate_df.empty:
                return None

            working_df = candidate_df.copy()
            if "node_dates" in working_df.columns and "discount_factors" in working_df.columns:
                working_df = working_df.loc[
                    working_df.apply(self._curve_store_row_has_nodes, axis=1)
                ].copy()
                if working_df.empty:
                    return None

            curves_by_ts = store.reconstruct_curves_batch(
                working_df,
                cfg=self._curve_store_cfg(resolved_curve_name, active_builder),
                max_workers=1,
            )
            for ts_val, curve_val in curves_by_ts.items():
                if self._curve_store_timestamp_key(ts_val) == target_key:
                    return self._wrap_curve_store_curve(
                        requested_curve_name=requested_curve_name,
                        resolved_curve_name=resolved_curve_name,
                        request_timestamp=request_timestamp,
                        rl_curve_handle=curve_val,
                        builder=active_builder,
                        fixings_cache=fixings_cache,
                    )
            return None

        exact_df = pd.DataFrame()
        if raw_df is not None and not raw_df.empty and "timestamp_utc" in raw_df.columns:
            exact_df = raw_df.loc[
                raw_df["timestamp_utc"].map(self._curve_store_timestamp_key) == requested_key
            ].copy()
            exact_curve = _wrap_single_row(exact_df, target_key=requested_key)
            if exact_curve is not None:
                return exact_curve

        if not allow_prior_timestamp:
            return None

        def _read_raw_day(curve_store: Any, curve_name: str, trading_date: datetime.date) -> pd.DataFrame:
            if hasattr(curve_store, "read_raw_day"):
                return curve_store.read_raw_day(curve_name, trading_date)
            if hasattr(curve_store, "read_raw_nodes"):
                return curve_store.read_raw_nodes(curve_name, start=trading_date, end=trading_date)
            return pd.DataFrame()

        trading_date = active_builder._trading_date_for_timestamp(rl_timestamp)
        for day_offset in range(0, max(1, int(max_lookback_days))):
            search_date = trading_date - datetime.timedelta(days=day_offset)
            day_df = _read_raw_day(store, resolved_curve_name, search_date)
            if day_df is None or day_df.empty or "timestamp_utc" not in day_df.columns:
                continue

            day_ts_keys = day_df["timestamp_utc"].map(self._curve_store_timestamp_key)
            eligible_mask = day_ts_keys.notna()
            if day_offset == 0:
                eligible_mask &= day_ts_keys <= requested_key
            eligible_df = day_df.loc[eligible_mask].copy()
            if eligible_df.empty:
                continue

            eligible_df["_curve_store_ts_key"] = eligible_df["timestamp_utc"].map(self._curve_store_timestamp_key)
            eligible_df = eligible_df.sort_values("_curve_store_ts_key")
            latest_key = self._curve_store_timestamp_key(eligible_df["_curve_store_ts_key"].iloc[-1])
            if latest_key is None:
                continue
            latest_df = eligible_df.tail(1).drop(columns=["_curve_store_ts_key"])
            latest_curve = _wrap_single_row(latest_df, target_key=latest_key)
            if latest_curve is not None:
                return latest_curve

        return None

    def _load_eris_curve_store_history(
        self,
        *,
        requested_curve_name: str,
        request_dates: Iterable[datetime.date],
        fixings_cache: Optional[Dict[datetime.date, pd.Series]] = None,
        max_workers: int = 4,
    ) -> Dict[datetime.date, "_IRSwapGenericCurve"]:
        unique_dates = sorted({d for d in request_dates if isinstance(d, datetime.date)})
        if not unique_dates:
            return {}

        requested_timestamps = [
            ts
            for ts in (self._to_eris_eod_timestamp(ref_date) for ref_date in unique_dates)
            if ts != "live"
        ]
        if not requested_timestamps:
            return {}

        store = self._get_curve_store()
        raw_df = pd.DataFrame()
        if hasattr(store, "read_raw_nodes"):
            try:
                raw_df = store.read_raw_nodes(
                    requested_curve_name,
                    start=unique_dates[0],
                    end=unique_dates[-1],
                )
            except TypeError:
                raw_df = store.read_raw_nodes(
                    requested_curve_name,
                    start=unique_dates[0],
                    end=unique_dates[-1],
                )

        if raw_df is None or raw_df.empty or "timestamp_utc" not in raw_df.columns:
            return {}

        requested_dates_set = set(unique_dates)
        if "trading_date" in raw_df.columns:
            trading_dates = raw_df["trading_date"].map(
                lambda value: value.date() if isinstance(value, datetime.datetime) else value
            )
            filtered_df = raw_df.loc[trading_dates.isin(requested_dates_set)].copy()
        else:
            requested_keys = {
                key
                for key in (self._curve_store_timestamp_key(ts) for ts in requested_timestamps)
                if key is not None
            }
            ts_keys = raw_df["timestamp_utc"].map(self._curve_store_timestamp_key)
            filtered_df = raw_df.loc[ts_keys.isin(requested_keys)].copy()
        if filtered_df.empty:
            return {}

        reconstruct_workers = self._resolve_curve_store_history_workers(
            max_workers,
            task_count=len(filtered_df),
        )
        curves_by_ts = store.reconstruct_curves_batch(
            filtered_df,
            cfg=None,
            max_workers=reconstruct_workers,
        )
        curves_by_key = {
            key: curve
            for key, curve in (
                (self._curve_store_timestamp_key(ts_val), curve_val)
                for ts_val, curve_val in curves_by_ts.items()
            )
            if key is not None
        }
        trading_date_by_ts_key = {}
        if "trading_date" in filtered_df.columns:
            for row in filtered_df.itertuples(index=False):
                ts_key = self._curve_store_timestamp_key(getattr(row, "timestamp_utc", None))
                trading_date = getattr(row, "trading_date", None)
                if isinstance(trading_date, datetime.datetime):
                    trading_date = trading_date.date()
                if ts_key is not None and isinstance(trading_date, datetime.date):
                    trading_date_by_ts_key[ts_key] = trading_date

        out: Dict[datetime.date, _IRSwapGenericCurve] = {}
        for ref_date in unique_dates:
            rl_curve_handle = None
            if trading_date_by_ts_key:
                for ts_key, curve in curves_by_key.items():
                    if trading_date_by_ts_key.get(ts_key) == ref_date:
                        rl_curve_handle = curve
                        break
            else:
                requested_ts_key = self._curve_store_timestamp_key(self._to_eris_eod_timestamp(ref_date))
                rl_curve_handle = curves_by_key.get(requested_ts_key)
            if rl_curve_handle is None:
                continue
            out[ref_date] = self._build_eris_eod_rl_curve(
                requested_curve_name=requested_curve_name,
                request_timestamp=ref_date,
                rl_curve_handle=rl_curve_handle,
                fixings_cache=fixings_cache,
            )
        return out

    def _load_gsquant_curve_store_history(
        self,
        *,
        requested_curve_name: str,
        request_dates: Iterable[datetime.date],
        fixings_cache: Optional[Dict[datetime.date, pd.Series]] = None,
        max_workers: int = 4,
    ) -> Dict[datetime.date, "_IRSwapGenericCurve"]:
        unique_dates = sorted({d for d in request_dates if isinstance(d, datetime.date)})
        if not unique_dates:
            return {}

        requested_timestamps = [
            ts
            for ts in (self._to_eris_eod_timestamp(ref_date) for ref_date in unique_dates)
            if ts != "live"
        ]
        if not requested_timestamps:
            return {}

        store = self._get_curve_store()
        raw_df = pd.DataFrame()
        if hasattr(store, "read_raw_nodes"):
            raw_df = store.read_raw_nodes(
                requested_curve_name,
                start=unique_dates[0],
                end=unique_dates[-1],
            )

        if raw_df is None or raw_df.empty or "timestamp_utc" not in raw_df.columns:
            return {}

        if "node_dates" in raw_df.columns and "discount_factors" in raw_df.columns:
            raw_df = raw_df.loc[
                raw_df.apply(self._curve_store_row_has_nodes, axis=1)
            ].copy()
            if raw_df.empty:
                return {}

        requested_dates_set = set(unique_dates)
        if "trading_date" in raw_df.columns:
            trading_dates = raw_df["trading_date"].map(
                lambda value: value.date() if isinstance(value, datetime.datetime) else value
            )
            filtered_df = raw_df.loc[trading_dates.isin(requested_dates_set)].copy()
        else:
            requested_keys = {
                key
                for key in (self._curve_store_timestamp_key(ts) for ts in requested_timestamps)
                if key is not None
            }
            ts_keys = raw_df["timestamp_utc"].map(self._curve_store_timestamp_key)
            filtered_df = raw_df.loc[ts_keys.isin(requested_keys)].copy()
        if filtered_df.empty:
            return {}

        reconstruct_workers = self._resolve_curve_store_history_workers(
            max_workers,
            task_count=len(filtered_df),
        )
        curves_by_ts = store.reconstruct_curves_batch(
            filtered_df,
            cfg=None,
            max_workers=reconstruct_workers,
        )
        curves_by_key = {
            key: curve
            for key, curve in (
                (self._curve_store_timestamp_key(ts_val), curve_val)
                for ts_val, curve_val in curves_by_ts.items()
            )
            if key is not None
        }
        trading_date_by_ts_key = {}
        if "trading_date" in filtered_df.columns:
            for row in filtered_df.itertuples(index=False):
                ts_key = self._curve_store_timestamp_key(getattr(row, "timestamp_utc", None))
                trading_date = getattr(row, "trading_date", None)
                if isinstance(trading_date, datetime.datetime):
                    trading_date = trading_date.date()
                if ts_key is not None and isinstance(trading_date, datetime.date):
                    trading_date_by_ts_key[ts_key] = trading_date

        out: Dict[datetime.date, _IRSwapGenericCurve] = {}
        for ref_date in unique_dates:
            rl_curve_handle = None
            if trading_date_by_ts_key:
                for ts_key, curve in curves_by_key.items():
                    if trading_date_by_ts_key.get(ts_key) == ref_date:
                        rl_curve_handle = curve
                        break
            else:
                requested_ts_key = self._curve_store_timestamp_key(self._to_eris_eod_timestamp(ref_date))
                rl_curve_handle = curves_by_key.get(requested_ts_key)
            if rl_curve_handle is None:
                continue
            curve_id = f"{self.source.upper()}-{requested_curve_name}-{ref_date}"
            out[ref_date] = self._build_gsquant_rl_curve(
                requested_curve_name=requested_curve_name,
                request_timestamp=ref_date,
                rl_curve_handle=rl_curve_handle,
                pricing_location=None,
                curve_id=curve_id,
                fixings_cache=fixings_cache,
            )
        return out

    @staticmethod
    def _should_suppress_ratelibs_solver_output(line: str) -> bool:
        return (
            "(levenberg_marquardt)" in line
            and (
                "SUCCESS: `conv_tol` reached" in line
                or "SUCCESS: `func_tol` reached" in line
            )
        )

    @staticmethod
    @contextlib.contextmanager
    def _suppress_ratelibs_solver_output() -> Any:
        class _FilteredWriteStream(io.TextIOBase):
            def __init__(self, stream: Any):
                self._stream = stream
                self._buffer = ""

            def write(self, s: str) -> int:
                if not s:
                    return 0

                self._buffer += s
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    self._emit(line + "\n")
                return len(s)

            def flush(self) -> None:
                if self._buffer:
                    self._emit(self._buffer)
                    self._buffer = ""
                self._stream.flush()

            def _emit(self, line: str) -> None:
                if not IRSwapsMDP._should_suppress_ratelibs_solver_output(line):
                    self._stream.write(line)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._stream, name)

        S = IRSwapsMDP._BARCHART_STIRF_STATE
        stdout = _FilteredWriteStream(sys.stdout)
        stderr = _FilteredWriteStream(sys.stderr)
        with S["io_lock"]:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    yield
                finally:
                    stdout.flush()
                    stderr.flush()

    @staticmethod
    def _to_barchart_stirf_timestamp(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Union[datetime.datetime, Literal["live"]]:
        if timestamp == "live":
            return "live"

        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        if isinstance(timestamp, datetime.datetime):
            if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
                return pytz.timezone("America/New_York").localize(timestamp)
            return timestamp

        if isinstance(timestamp, datetime.date):
            return pytz.timezone("America/New_York").localize(datetime.datetime.combine(timestamp, datetime.time(hour=17, minute=0)))

        raise TypeError("timestamp must be datetime.date, datetime.datetime, pd.Timestamp, or 'live'")

    @staticmethod
    def _dict_get_case_insensitive(mapping: Dict[Any, Any], key: str) -> Any:
        if key in mapping:
            return mapping[key]

        needle = str(key).upper().strip()
        for k, v in mapping.items():
            if str(k).upper().strip() == needle:
                return v
        return None

    @staticmethod
    def _resolve_gsquant_reference_curve_name(curve_name: str) -> str:
        from MDP.IRSwaps.GSQUANT.rl_basic.build import GSQUANT_CURVE_MAP

        curve_cfg = GSQUANT_CURVE_MAP.get(curve_name, {}).get("rl_basic", {})
        return str(curve_cfg.get("reference_key") or curve_name)

    @staticmethod
    def _normalize_gsquant_curve_name(curve_name: str) -> str:
        return "USD-OIS" if str(curve_name).upper().strip() == "USD-FEDFUNDS" else str(curve_name)

    @staticmethod
    def _reference_point_date(
        ref_point: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> Optional[datetime.date]:
        if ref_point == "live":
            return None
        if isinstance(ref_point, pd.Timestamp):
            return ref_point.date()
        if isinstance(ref_point, datetime.datetime):
            return ref_point.date()
        if isinstance(ref_point, datetime.date):
            return ref_point
        return None

    def ignored_reference_dates_for_curve(self, curve_name: str) -> frozenset[datetime.date]:
        source = str(self.source).upper()
        if "GSQUANT-RL" not in source and "GSQUANT_RL" not in source:
            return frozenset()
        normalized_curve = self._normalize_gsquant_curve_name(curve_name)
        return self._GSQUANT_IGNORED_DATES_BY_CURVE.get(normalized_curve, frozenset())

    def filter_reference_points_for_curve(
        self,
        *,
        curve_name: str,
        reference_points: Iterable[Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]]],
    ) -> List[Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]]]:
        ignored_dates = self.ignored_reference_dates_for_curve(curve_name)
        if not ignored_dates:
            return list(reference_points)
        return [
            ref_point
            for ref_point in reference_points
            if self._reference_point_date(ref_point) not in ignored_dates
        ]

    def _resolve_barchart_stirf_curve_name(self, requested_curve_name: str, kwargs: Dict[str, Any], builder: Any) -> str:
        cfgs: Dict[str, Dict[str, Any]] = dict(getattr(builder, "_STIRF_CURVE_CONFIGS", {}))
        if requested_curve_name in cfgs:
            return requested_curve_name

        curve_names_arg = kwargs.pop("curve_names", None)
        if curve_names_arg is not None:
            resolved_name: Optional[str] = None
            if isinstance(curve_names_arg, str):
                resolved_name = curve_names_arg
            elif isinstance(curve_names_arg, dict):
                match = self._dict_get_case_insensitive(curve_names_arg, requested_curve_name)
                if match is None and len(curve_names_arg) == 1:
                    match = next(iter(curve_names_arg.values()))
                if match is not None:
                    resolved_name = str(match)
            else:
                raise TypeError("kwargs['curve_names'] must be a string or a dict")

            if resolved_name is None:
                raise ValueError(
                    f"Could not resolve curve name for '{requested_curve_name}' from kwargs['curve_names']: {curve_names_arg}"
                )
            if resolved_name not in cfgs:
                raise ValueError(f"BARCHART STIRF curve '{resolved_name}' not found in BARCHART_STIRF_CURVE configs")
            return resolved_name

        by_reference = [name for name, cfg in cfgs.items() if str(cfg.get("reference_key", "")).upper().strip() == requested_curve_name.upper().strip()]
        if len(by_reference) == 1:
            return by_reference[0]
        if len(by_reference) > 1:
            raise ValueError(
                f"Multiple BARCHART STIRF curves map to reference curve '{requested_curve_name}': {by_reference}. "
                "Pass kwargs['curve_names'] to disambiguate."
            )

        raise ValueError(
            f"Could not resolve BARCHART STIRF curve for '{requested_curve_name}'. "
            "Pass kwargs['curve_names'] with a concrete BARCHART curve config key."
        )

    @staticmethod
    def _barchart_stirf_reference_date(
        timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
    ) -> datetime.date:
        if timestamp == "live":
            return datetime.date.today()
        if isinstance(timestamp, pd.Timestamp):
            return timestamp.date()
        if isinstance(timestamp, datetime.datetime):
            return timestamp.date()
        return timestamp

    def _build_barchart_stirf_rl_curve(
        self,
        *,
        requested_curve_name: str,
        resolved_curve_name: str,
        request_timestamp: Union[datetime.datetime, datetime.date, pd.Timestamp, Literal["live"]],
        rl_curve_handle: Any,
        builder: Any,
        fixings_cache: Optional[Dict[tuple[datetime.date, str], pd.Series]] = None,
    ) -> "_IRSwapGenericCurve":
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

        reference_curve_name = str(getattr(rl_curve_handle, "id", "") or "")
        if not reference_curve_name:
            reference_curve_name = str(builder._STIRF_CURVE_CONFIGS[resolved_curve_name]["reference_key"])

        ref = self._barchart_stirf_reference_date(request_timestamp)
        fixings_key = (ref, reference_curve_name)
        fixings = None if fixings_cache is None else fixings_cache.get(fixings_key)
        if fixings is None:
            try:
                fixings = _fetch_fixings(
                    as_of_date=ref,
                    curve_name=reference_curve_name,
                    force_refresh=self.force_refresh_fixings,
                ).sort_index()
                fixings = fixings[fixings.index.date < ref] * 100
                if fixings_cache is not None:
                    fixings_cache[fixings_key] = fixings
            except:
                pass

        ts_meta = getattr(rl_curve_handle, "timestamp", request_timestamp)
        curve_id = f"{self.source.upper()}-{resolved_curve_name}-{ts_meta}"
        return RLIRSwapCurve(
            rl_curve_id=reference_curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings,
            meta_data={
                "timestamp": ts_meta,
                "id": curve_id,
                "requested_curve_name": requested_curve_name,
                "curve_name": resolved_curve_name,
            },
        )

    def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
        curve = self.get_data(request)  # reuse the existing logic
        if curve is None:
            raise RuntimeError(f"IRSwapsMDP could not build a curve for request: {request}")
        return curve

    @staticmethod
    def _normalize_grid_tenor(tenor: str, *, allow_spot: bool = False) -> str:
        token = str(tenor or "").strip().upper().replace(" ", "")
        if not token:
            raise ValueError("Grid tenor cannot be empty.")
        if allow_spot and token in {"SPOT", "0", "0D"}:
            return "0D"
        if not re.fullmatch(r"\d+[DWMY]", token):
            raise ValueError(f"Invalid grid tenor '{tenor}'. Expected values like 'Spot', '1M', or '10Y'.")
        return token

    @staticmethod
    def _grid_axis_labels(values: Sequence[str], axis_name: str) -> list[str]:
        labels = ["Spot" if value == "0D" else value for value in values]
        if len(labels) != len(set(labels)):
            raise ValueError(f"Duplicate {axis_name} labels after normalization: {labels}")
        return labels

    def get_grid(
        self,
        request: dict,
        *,
        fwds: Optional[Sequence[str]] = None,
        swap_tenors: Optional[Sequence[str]] = None,
        flip_axes: bool = False,
    ) -> pd.DataFrame:
        curve = self.get_pricer(dict(request))

        normalized_fwds = [
            self._normalize_grid_tenor(fwd, allow_spot=True)
            for fwd in (fwds or self._DEFAULT_GRID_FWDS)
        ]
        normalized_swap_tenors = [
            self._normalize_grid_tenor(swap_tenor)
            for swap_tenor in (swap_tenors or self._DEFAULT_GRID_SWAP_TENORS)
        ]

        forward_labels = self._grid_axis_labels(normalized_fwds, "fwds")
        swap_tenor_labels = self._grid_axis_labels(normalized_swap_tenors, "swap_tenors")

        grid = pd.DataFrame(index=swap_tenor_labels, columns=forward_labels, dtype=float)
        for swap_tenor, swap_label in zip(normalized_swap_tenors, swap_tenor_labels):
            for fwd, fwd_label in zip(normalized_fwds, forward_labels):
                swap = curve.build_irswap(fwd=fwd, tenor=swap_tenor)
                grid.at[swap_label, fwd_label] = float(curve.fair_rate(swap)) * 100.0

        grid.index.name = "swap_tenor"
        grid.columns.name = "forward_tenor"
        if flip_axes:
            grid = grid.T
            grid.index.name = "forward_tenor"
            grid.columns.name = "swap_tenor"
        return grid

    def get_data(self, request: dict) -> Optional[_IRSwapGenericCurve]:
        curve_name = request.pop("curve_name")
        timestamp = request.pop("timestamp")

        if not curve_name or not timestamp:
            raise ValueError("Request must contain 'curve_name' and 'timestamp'.")

        return self._get_curve(curve_name, timestamp, kwargs=request)

    def _get_curve(
        self, curve_name: str, timestamp: Union[datetime.datetime, datetime.date, Literal["live"]], kwargs: Optional[Dict[str, Any]] = {}
    ) -> Optional[_IRSwapGenericCurve]:
        self._validate_curve_request_timestamp(curve_name=curve_name, timestamp=timestamp)

        if self.source.upper() in ["CME_NY_EOD_LIVE-QL_BASIC", "CME_NY_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            cmef = CMEFetcherV2(**self.config)

            ts, ql_curve = next(
                iter(
                    cmef.build_ql_eod_curves(
                        curve=curve_name,
                        type="Df",
                        ql_day_count=ql_curve_def["DayCounter"],
                        ql_calendar=ql_curve_def["Calendar"],
                        bdates=[timestamp],
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["CME_NY_EOD_LIVE-RL_BASIC", "CME_NY_EOD_LIVE_RL_BASIC"]:
            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"
            cmef = CMEFetcherV2(**self.config)

            ts, rl_curve_handle = next(
                iter(
                    cmef.build_rl_eod_curves(
                        curve_id=curve_id,
                        curve=curve_name,
                        bdates=["live" if timestamp == datetime.date.today() else timestamp],
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]

            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=fixings_series, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"]:
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"
            force_refresh = bool(kwargs.get("force_refresh", kwargs.get("ignore_cache", False)))

            if timestamp == "live":
                eff = ErisFuturesFetcher(**self.config)
                rl_curve_handle, ts = eff.fetch_intraday_discount_curve(curve_id=curve_id, date=None, show_tqdm=True, return_intraday_timestamp=True, **kwargs)
            else:
                if not force_refresh and self._supports_curve_store_raw_curve_fast_path():
                    curve_store_hit = self._load_eris_curve_store_history(
                        requested_curve_name=curve_name,
                        request_dates=[timestamp],
                        max_workers=1,
                    ).get(timestamp)
                    if curve_store_hit is not None:
                        curve_store_hit._meta_data["id"] = curve_id
                        return curve_store_hit
                _, rl_json, ts = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=curve_id, as_of=timestamp, force_refresh=force_refresh, fetcher_kwargs={"show_tqdm": False}
                )
                rl_curve_handle = from_json(rl_json)

            curve = self._build_eris_eod_rl_curve(
                requested_curve_name=curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
            )
            curve._meta_data["timestamp"] = ts
            curve._meta_data["id"] = curve_id
            if timestamp != "live":
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=curve,
                    request_timestamp=timestamp,
                )
            return curve

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"]:
            from rateslib import from_json

            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in RATESLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."

            curve_id = f"{self.source.upper()}-{curve_name}-{timestamp}"

            if timestamp == "live":
                eff = ErisFuturesFetcher(**self.config)
                rl_curve_handle, ts = eff.fetch_intraday_discount_curve(
                    curve_id=curve_id, date=None, show_tqdm=True, return_intraday_timestamp=True, no_jumps_just_interp=True, **kwargs
                )
            else:
                _, rl_json, ts = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=curve_id,
                    as_of=timestamp,
                    force_refresh=kwargs.get("force_refresh", False),
                    no_jumps_just_interp=True,
                    fetcher_kwargs={"show_tqdm": False},
                )
                rl_curve_handle = from_json(rl_json)

            curve = self._build_eris_eod_rl_curve(
                requested_curve_name=curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
            )
            curve._meta_data["timestamp"] = ts
            curve._meta_data["id"] = curve_id
            if timestamp != "live":
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=curve,
                    request_timestamp=timestamp,
                )
            return curve

        elif self.source.upper() in ["ERIS_EOD_LIVE-QL_BASIC", "ERIS_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            erisf = ErisFuturesFetcher(**self.config)

            if "ignore_cache" in kwargs:
                kwargs["force_refresh"] = kwargs.pop("ignore_cache")

            # Filter kwargs to only include parameters accepted by the QL fetcher
            _ql_eris_valid_keys = {
                "start_date", "end_date", "bdates", "ql_dc", "ql_cal",
                "show_tqdm", "interpolation_algo", "enable_extrapolation",
                "append_intraday", "max_concurrent_tasks",
                "max_keepalive_connections", "ignore_cache", "force_refresh",
            }
            ql_kwargs = {k: v for k, v in kwargs.items() if k in _ql_eris_valid_keys}

            if timestamp == "live" or timestamp == datetime.date.today():
                eff = ErisFuturesFetcher(**self.config)
                ql_curve, ts = eff.fetch_intraday_discount_curve(show_tqdm=True, enable_extrapolation=True, return_intraday_timestamp=True, **ql_kwargs)
            else:
                ts, ql_curve = next(
                    iter(
                        erisf.fetch_historical_eod_discount_curves(
                            ql_dc=ql_curve_def["DayCounter"],
                            ql_cal=ql_curve_def["Calendar"],
                            bdates=[timestamp],
                            enable_extrapolation=True,
                            show_tqdm=False,
                            **ql_kwargs,
                        ).items()
                    )
                )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["ERIS_EOD_LIVE-QL_BASIC-NOJUMPS", "ERIS_EOD_LIVE_QL_BASIC-NOJUMPS"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.ErisFuturesFetcher import ErisFuturesFetcher
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            if type(timestamp) == datetime.datetime or hasattr(timestamp, "date"):
                timestamp = timestamp.date()

            assert type(timestamp) == datetime.date or timestamp == "live", "CME_NY_EOD ONLY HAS EOD - 'timestamp' must be type 'datetime.date' or Literal['live']"
            assert curve_name in QUANTLIB_CURVE_DEFINITIONS, f"Error: Curve definition for '{curve_name}' not found."
            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]

            erisf = ErisFuturesFetcher(**self.config)

            ts, ql_curve = next(
                iter(
                    erisf.fetch_historical_eod_discount_curves(
                        ql_dc=ql_curve_def["DayCounter"],
                        ql_cal=ql_curve_def["Calendar"],
                        bdates=[timestamp],
                        enable_extrapolation=True,
                        show_tqdm=False,
                        **kwargs,
                    ).items()
                )
            )

            ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
            irswap_index: ql.SwapIndex = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)

            ref = datetime.date.today() if type(timestamp) == str else timestamp
            fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            fixings_series: pd.Series = fixings_series[fixings_series.index.date < ref]
            fixings_dict = fixings_series.to_dict()
            for d, f in fixings_dict.items():
                try:
                    irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                except:
                    continue

            return QLIRSwapCurve(ql_curve_id=curve_name, ql_curve_handle=ql_curve_handle, ql_curve_index=irswap_index, meta_data={"timestamp": ts})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q12", "SDR_INTRADAY_RL_USD_SOFR_MT_Q12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q12.rl_usd_sofr_mt_q12 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q16", "SDR_INTRADAY_RL_USD_SOFR_MT_Q16"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q16.rl_usd_sofr_mt_q16 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_Q16"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_MISC", "SDR_INTRADAY_RL_USD_SOFR_MT_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_misc.rl_usd_sofr_mt_misc import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100
            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MT_MISC"

            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q12X8", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q12X8"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q12x8.rl_usd_sofr_stir_q12x8 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q12x8"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q13X10", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q13X10"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q13x10.rl_usd_sofr_stir_q13x10 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q13x10"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_Q12X9", "SDR_INTRADAY_RL_USD_OIS_STIR_Q12X9"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "USD-FEDFUNDS!"
            curve_name = "USD-SOFR-1D"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_q12x9.rl_usd_ois_stir_q12x9 import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_Q12x9"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_Q12X12", "SDR_INTRADAY_RL_USD_OIS_STIR_Q12X12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "USD-FEDFUNDS!"
            curve_name = "USD-SOFR-1D"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_q12x12.rl_usd_ois_stir_q12x12 import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_Q12x12"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id="USD-FEDFUNDS", rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_Q12X12", "SDR_INTRADAY_RL_USD_SOFR_STIR_Q12X12"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_q12x12.rl_usd_sofr_stir_q12x12 import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_Q12x12"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_STIR_MISC", "SDR_INTRADAY_RL_USD_SOFR_STIR_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_stir_misc.rl_usd_sofr_stir_misc import rl_usd_sofr_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_STIR_MISC"
            ts, rl_curve_handle = rl_usd_sofr_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_OIS_STIR_MISC", "SDR_INTRADAY_RL_USD_OIS_STIR_MISC"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-FEDFUNDS", "FEDFUNDS!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_ois_stir_misc.rl_usd_ois_stir_misc import rl_usd_ois_stir_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_OIS_STIR_MISC"
            ts, rl_curve_handle = rl_usd_ois_stir_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11", "SDR_INTRADAY_RL_USD_SOFR_MTV2_Q12X11"]:
            assert type(timestamp) == datetime.datetime or timestamp == "live", "need to pass in a 'datetime.datetime' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            curve_id = f"{timestamp}-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12x11"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12X11", "SDR_3PM_EOD_RL_USD_SOFR_MTV2_Q12X11"]:
            assert type(timestamp) == datetime.date or timestamp == "live", "need to pass in a 'datetime.date' timestamp"
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            # 3pm close
            if str(timestamp).lower() != "live":
                timestamp = pytz.timezone("America/New_York").localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 15, 00))

            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ref = datetime.date.today() if type(timestamp) == str else timestamp.date()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{timestamp}-SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12x11"
            ts, rl_curve_handle = rl_usd_sofr_mt_curve(
                curve_id=curve_id,
                snap=timestamp,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache if timestamp != "live" else None,
                force_refresh=kwargs.get("force_refresh", False),
            )
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif "GSQUANT-RL" in self.source.upper() or "GSQUANT_RL" in self.source.upper():
            assert type(timestamp) == datetime.date, "GSQUANT ONLY HAS EOD - 'timestamp' must be type 'datetime.date'"

            fixings_cache = self._build_fixings_cache_for_dates(
                curve_name=self._resolve_gsquant_reference_curve_name(curve_name),
                as_of_dates=[timestamp],
            )
            if self._supports_curve_store_raw_curve_fast_path():
                try:
                    curve_store_hits = self._load_gsquant_curve_store_history(
                        requested_curve_name=curve_name,
                        request_dates=[timestamp],
                        fixings_cache=fixings_cache,
                        max_workers=1,
                    )
                    if timestamp in curve_store_hits:
                        return curve_store_hits[timestamp]
                except Exception as _tier0_exc:
                    logging.getLogger(__name__).debug(
                        "GSQUANT CurveStore Tier 0 single-date fast path failed: %s",
                        _tier0_exc,
                    )

            from rateslib import from_json

            curve_id, rl_curve_serialized, pricing_location = self._rl_curve_cache.get_gsquant_rl_basic(
                curve_id=curve_name, as_of=timestamp, force_refresh=kwargs.get("force_refresh", False)
            )
            return self._build_gsquant_rl_curve(
                requested_curve_name=curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=from_json(rl_curve_serialized),
                pricing_location=pricing_location,
                curve_id=curve_id,
                fixings_cache=fixings_cache,
            )

        elif self.source.upper() in ["BARCHART_STIRF-RL", "BARCHART_STIRF_RL"]:
            local_kwargs = dict(kwargs)
            builder = self._get_barchart_stirf_curve_builder()
            resolved_curve_name = self._resolve_barchart_stirf_curve_name(
                requested_curve_name=curve_name,
                kwargs=local_kwargs,
                builder=builder,
            )

            rl_timestamp = self._to_barchart_stirf_timestamp(timestamp)
            local_force_refresh = bool(local_kwargs.get("force_refresh", local_kwargs.get("ignore_cache", False)))
            if rl_timestamp != "live" and not local_force_refresh and self._supports_curve_store_raw_curve_fast_path():
                try:
                    curve_store_hit = self._load_barchart_stirf_curve_store_point(
                        requested_curve_name=curve_name,
                        request_timestamp=timestamp,
                        builder=builder,
                        allow_prior_timestamp=bool(local_kwargs.get("ignore_cache_miss", False)),
                    )
                    if curve_store_hit is not None:
                        return curve_store_hit
                except Exception as _tier0_exc:
                    logging.getLogger(__name__).debug(
                        "BARCHART_STIRF CurveStore Tier 0 single-date fast path failed: %s",
                        _tier0_exc,
                    )
            if local_kwargs.get("ignore_cache_miss", False):
                return None
            with self._suppress_ratelibs_solver_output():
                rl_curve_handle = builder.build_curve(
                    curve_name=resolved_curve_name,
                    timestamp=rl_timestamp,
                    kwargs=local_kwargs,
                    curve_only=True,
                )

            return self._build_barchart_stirf_rl_curve(
                requested_curve_name=curve_name,
                resolved_curve_name=resolved_curve_name,
                request_timestamp=timestamp,
                rl_curve_handle=rl_curve_handle,
                builder=builder,
            )

        elif self.source.upper() in ["CITIVELO", "CITI_VELO", "CITIVELOCITY"]:
            assert curve_name == "USD-SOFR-1D", "SOFR!"

            method = kwargs.get("method", "nearest")

            # DEFAULT: serve the pre-warmed curve from the CurveStore (local parquet
            # backed by Supabase L2). Never parse the 365 MB workbook unless the
            # caller explicitly opts in via workbook_path / force_workbook.
            use_workbook = bool(kwargs.get("force_workbook", False)) or ("workbook_path" in kwargs)
            if not use_workbook:
                store_curve = self._load_citivelo_curve_store_point(
                    requested_curve_name=curve_name, timestamp=timestamp, method=method
                )
                if store_curve is not None:
                    return store_curve
                if not kwargs.get("fallback_workbook", False):
                    raise RuntimeError(
                        f"CitiVelo CurveStore (asset {self._CITIVELO_STORE_ASSET}) has no data for "
                        f"timestamp={timestamp!r}. Warm/sync it (scripts/citivelo_curve_service.py), or pass "
                        f"force_workbook=True / fallback_workbook=True to build from the Citi Velocity workbook."
                    )

            # Opt-in workbook build (explicit workbook_path/force_workbook, or fallback on store miss).
            from MDP.IRSwaps.CITI_VELOCITY_INTRADAY import DEFAULT_DB_PATH
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            workbook_path = kwargs.get("workbook_path", DEFAULT_DB_PATH)
            build_kwargs = {
                k: kwargs[k]
                for k in ("spline_start_tenor", "interpolation", "min_tenors", "spot_lag")
                if k in kwargs
            }

            fetcher = self._get_citivelo_fetcher(workbook_path=workbook_path, curve_id=curve_name)
            when = None if timestamp == "live" else timestamp  # 'live' -> latest snapshot in the workbook
            rlc = fetcher.build_curve(when, method=method, **build_kwargs)

            ts = rlc.timestamp
            rl_curve_handle = rlc.rl_pricing_curve

            ref = ts.date() if hasattr(ts, "date") else datetime.date.today()
            sofr_fixings = _fetch_fixings(as_of_date=ref, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < ref] * 100

            curve_id = f"{self.source.upper()}-{curve_name}-{ts}"
            return RLIRSwapCurve(rl_curve_id=curve_name, rl_curve_handle=rl_curve_handle, fixings=sofr_fixings, meta_data={"timestamp": ts, "id": curve_id})

        elif self.source.upper() in ["ERIS_LIVE_INTRADAY", "ERIS_LIVE-INTRADAY"]:
            assert curve_name == "USD-SOFR-1D", "SOFR!"
            method = kwargs.get("method", "asof")
            store_curve = self._load_eris_live_intraday_point(
                requested_curve_name=curve_name, timestamp=timestamp, method=method
            )
            if store_curve is not None:
                return store_curve
            raise RuntimeError(
                f"ERIS live intraday store (asset {self._ERIS_LIVE_STORE_ASSET}) has no data for "
                f"timestamp={timestamp!r}. Run the poller (scripts/eris_live_curve_service.py)."
            )

        else:
            raise NotImplementedError(f"Curve Build '{self.source}' does not exist")

    def bulk_get_data(self, request: dict) -> Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve]:
        if not isinstance(request, dict):
            raise ValueError("request must be a dict")

        curve_name: str = request.pop("curve_name", None)
        timestamps_in: Iterable[Union[datetime.date, datetime.datetime, Literal["live"]]] = request.pop("timestamps", None)
        ignore_cache = bool(request.pop("ignore_cache", False))
        ignore_cache_miss = bool(request.pop("ignore_cache_miss", False))
        n_jobs_raw = request.pop("n_jobs", None)
        n_jobs = int(n_jobs_raw) if n_jobs_raw is not None else 1
        n_jobs_requested = n_jobs_raw is not None
        calibration_executor = str(request.pop("calibration_executor", "thread") or "thread").strip().lower()
        if calibration_executor not in {"thread", "process"}:
            raise ValueError(
                f"Unsupported calibration_executor '{calibration_executor}'. "
                "Expected one of ['process', 'thread']."
            )

        if not curve_name or timestamps_in is None:
            raise ValueError("Request must contain 'curve_name' and 'timestamps'.")

        seen: set = set()
        timestamps: List[Union[datetime.date, datetime.datetime, Literal["live"]]] = []
        for t in timestamps_in:
            if t == datetime.date.today():
                t = "live"
            key = ("live",) if t == "live" else ("dt", t) if isinstance(t, datetime.datetime) else ("d", t)
            if key not in seen:
                seen.add(key)
                timestamps.append(t)

        timestamps = self.filter_reference_points_for_curve(
            curve_name=curve_name,
            reference_points=timestamps,
        )

        if not timestamps:
            raise ValueError("Request 'timestamps' resolved to an empty collection.")

        out: Dict[Union[datetime.date, datetime.datetime], _IRSwapGenericCurve] = {}

        if self.source.upper() in ["CME_NY_EOD_LIVE-QL_BASIC", "CME_NY_EOD_LIVE_QL_BASIC"]:
            import QuantLib as ql

            from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.quantlib.ql_curve_definitions_map import QUANTLIB_CURVE_DEFINITIONS
            from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
            from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]

            ql_curve_def = QUANTLIB_CURVE_DEFINITIONS[curve_name]
            cmef = CMEFetcherV2(**self.config)

            built = cmef.build_ql_eod_curves(
                curve=curve_name,
                type="Df",
                ql_day_count=ql_curve_def["DayCounter"],
                ql_calendar=ql_curve_def["Calendar"],
                bdates=bdates,
                show_tqdm=True,
                ignore_cache=ignore_cache,
                **request,
            )

            for ref_date, ql_curve in built.items():
                ts = ref_date
                if type(ref_date) == datetime.datetime or type(ref_date) == pd.Timestamp:
                    ref_date = ref_date.date()

                if ql_curve is None:
                    continue
                ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
                irswap_index = ql_curve_def["ReferenceRate"](ql_curve_handle)

                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date]
                for d, f in fixings_series.to_dict().items():
                    try:
                        irswap_index.addFixing(fixingDate=datetime_to_ql_date(d), fixing=f, forceOverwrite=True)
                    except Exception:
                        pass

                out[ref_date] = QLIRSwapCurve(
                    ql_curve_id=curve_name,
                    ql_curve_handle=ql_curve_handle,
                    ql_curve_index=irswap_index,
                    meta_data={"timestamp": ts},
                )

            return out

        elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"]:
            from rateslib import from_json

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already a date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]

            today = datetime.date.today()
            past_dates = [d for d in bdates if d < today]
            today_dates = [d for d in bdates if d == today]
            fixings_cache = self._build_fixings_cache_for_dates(
                curve_name=curve_name,
                as_of_dates=bdates,
            )

            if not ignore_cache and (past_dates or today_dates) and self._supports_curve_store_raw_curve_fast_path():
                try:
                    raw_candidate_dates = list(past_dates) + list(today_dates)
                    out.update(
                        self._load_eris_curve_store_history(
                            requested_curve_name=curve_name,
                            request_dates=raw_candidate_dates,
                            fixings_cache=fixings_cache,
                            max_workers=max(1, int(n_jobs or 1)),
                        )
                    )

                    if len([d for d in raw_candidate_dates if d in out]) >= len(raw_candidate_dates):
                        for ref_date in [d for d in today_dates if d not in out]:
                            _, rl_json_live, ts_live = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                                curve_id=f"{self.source}-{curve_name}-live",
                                as_of="live",
                                force_refresh=True if ignore_cache else False,
                                fetcher_kwargs={"show_tqdm": True},
                            )
                            out[ref_date] = self._build_eris_eod_rl_curve(
                                requested_curve_name=curve_name,
                                request_timestamp=ref_date,
                                rl_curve_handle=from_json(rl_json_live),
                                fixings_cache=fixings_cache,
                            )
                            out[ref_date]._meta_data["timestamp"] = ts_live
                        return out
                except Exception as _tier0_exc:
                    import logging as _logging

                    _logging.getLogger(__name__).debug(
                        "Eris CurveStore Tier 0 fast path failed: %s", _tier0_exc,
                    )
            if ignore_cache_miss:
                return out

            built_json: Dict[datetime.date, str] = {}
            remaining_past_dates = [d for d in past_dates if d not in out]
            if remaining_past_dates:
                built_json = self._rl_curve_cache.bulk_get_eris_eod_live_rl_basic(
                    base_curve_id=f"{self.source}-{curve_name}-bulk",
                    bdates=remaining_past_dates,
                    force_refresh=ignore_cache,
                    fetcher_kwargs={"show_tqdm": True},
                )

            remaining_today_dates = [d for d in today_dates if d not in out]
            for ref_date in remaining_today_dates:
                _, rl_json_live, ts_live = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                    curve_id=f"{self.source}-{curve_name}-live",
                    as_of="live",
                    force_refresh=True if ignore_cache else False,
                    fetcher_kwargs={"show_tqdm": True},
                )
                out[ref_date] = self._build_eris_eod_rl_curve(
                    requested_curve_name=curve_name,
                    request_timestamp=ref_date,
                    rl_curve_handle=from_json(rl_json_live),
                    fixings_cache=fixings_cache,
                )
                out[ref_date]._meta_data["timestamp"] = ts_live

            for ref_date, json_str in built_json.items():
                out[ref_date] = self._build_eris_eod_rl_curve(
                    requested_curve_name=curve_name,
                    request_timestamp=ref_date,
                    rl_curve_handle=from_json(json_str),
                    fixings_cache=fixings_cache,
                )
                self._promote_eris_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=out[ref_date],
                    request_timestamp=ref_date,
                )

            return out

        elif self.source.upper() in ["CME_NY_EOD_LIVE-RL_BASIC", "CME_NY_EOD_LIVE_RL_BASIC"]:
            from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.CMEFetcherV2 import CMEFetcherV2
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            def _to_date(x):
                if x == "live":
                    return datetime.date.today()
                if isinstance(x, datetime.datetime):
                    return x.date()
                return x  # already a date

            bdates: List[datetime.date] = [_to_date(t) for t in timestamps]
            cmef = CMEFetcherV2(**self.config)
            built = cmef.build_rl_eod_curves(
                curve_id=f"{self.source}-{curve_name}-bulk",
                curve=curve_name,
                type="Df",
                bdates=bdates,
                show_tqdm=True,
                ignore_cache=ignore_cache,
                **request,
            )

            for ref_date, rl_curve in built.items():
                ts = ref_date
                if isinstance(ref_date, (datetime.datetime, pd.Timestamp)):
                    ref_date = ref_date.date()

                if rl_curve is None:
                    continue

                fixings_series = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
                fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0

                out[ref_date] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=fixings_series,
                    meta_data={"timestamp": ts},
                )

            return out

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MT_Q12", "SDR_INTRADAY_RL_USD_SOFR_MT_Q12"]:
            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mt_q12.rl_usd_sofr_mt_q12 import rl_usd_sofr_mt_curve, rl_usd_sofr_mt_curve_bulk
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            max_ref_date = max(t.date() if isinstance(t, (datetime.date, datetime.datetime)) else datetime.date.today() for t in timestamps)
            full_fixings_series = _fetch_fixings(as_of_date=max_ref_date, curve_name="USD-SOFR-1D", force_refresh=self.force_refresh_fixings).sort_index()

            datetime_snaps = [t for t in timestamps if isinstance(t, datetime.datetime)]
            live_snap_requested = "live" in timestamps

            if not datetime_snaps:
                return {}

            built_curves = rl_usd_sofr_mt_curve_bulk(
                base_curve_id="SDR_INTRADAY-RL_USD_SOFR_MT_Q12",
                snaps=datetime_snaps,
                sofr_fixings=full_fixings_series,
                cache=self._rl_curve_cache,
                max_workers=n_jobs,
                force_refresh=ignore_cache,
            )

            for ts, rl_curve in built_curves.items():
                if rl_curve is None:
                    continue
                ref_date = ts.date()
                fixings_for_curve = full_fixings_series[full_fixings_series.index.date < ref_date] * 100.0
                curve_id_for_snap = f"{ts}-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
                out[ts] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=fixings_for_curve,
                    meta_data={"timestamp": ts, "id": curve_id_for_snap},
                )

            if live_snap_requested:
                ref_date = datetime.date.today()
                fixings_for_curve = full_fixings_series[full_fixings_series.index.date < ref_date] * 100.0
                curve_id = "live-SDR_INTRADAY-RL_USD_SOFR_MT_Q12"
                ts_out, rl_curve = rl_usd_sofr_mt_curve(
                    curve_id=curve_id,
                    snap="live",
                    sofr_fixings=fixings_for_curve,
                    cache=None,
                    force_refresh=True,
                )
                out["live"] = RLIRSwapCurve(
                    rl_curve_id="USD-SOFR-1D",
                    rl_curve_handle=rl_curve,
                    fixings=fixings_for_curve,
                    meta_data={"timestamp": ts_out, "id": curve_id},
                )

            return out

        elif self.source.upper() in ["SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11", "SDR_INTRADAY_RL_USD_SOFR_MTV2_Q12X11"]:
            from MDP.IRSwaps.SDR_INTRADAY.rl_usd_sofr_mtv2_q12x11.rl_usd_sofr_mtv2_q12x11 import rl_usd_sofr_mt_curve, rl_usd_sofr_mt_curve_bulk
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            max_ref_date = max(t.date() if isinstance(t, (datetime.date, datetime.datetime)) else datetime.date.today() for t in timestamps)

            sofr_fixings = _fetch_fixings(as_of_date=max_ref_date, curve_name=curve_name, force_refresh=self.force_refresh_fixings).sort_index()
            sofr_fixings: pd.Series = sofr_fixings[sofr_fixings.index.date < max_ref_date] * 100

            # for when we need to build curve before 8am est sofr fixings
            FIXINGS_TOL = 1
            if not sofr_fixings.empty:
                from pandas.tseries.holiday import USFederalHolidayCalendar
                from pandas.tseries.offsets import CustomBusinessDay

                cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
                target_dt = (pd.Timestamp(max_ref_date) - (cbd * FIXINGS_TOL)).normalize()
                idx_norm = sofr_fixings.index.normalize()
                if target_dt not in idx_norm:
                    last_val = sofr_fixings.iloc[-1]
                    sofr_fixings.loc[target_dt] = float(last_val)
                    sofr_fixings = sofr_fixings.sort_index()

            datetime_snaps = [t for t in timestamps if isinstance(t, datetime.datetime)]
            live_snap_requested = "live" in timestamps

            if not datetime_snaps:
                return {}

            built_curves = rl_usd_sofr_mt_curve_bulk(
                base_curve_id="SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11",
                snaps=datetime_snaps,
                sofr_fixings=sofr_fixings,
                cache=self._rl_curve_cache,
                max_workers=n_jobs,
                force_refresh=ignore_cache,
            )

            for ts, rl_curve in built_curves.items():
                if rl_curve is None:
                    continue
                ref_date = ts.date()
                curve_id_for_snap = f"{ts}-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11"
                out[ts] = RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve,
                    fixings=sofr_fixings,
                    meta_data={"timestamp": ts, "id": curve_id_for_snap},
                )

            if live_snap_requested:
                ref_date = datetime.date.today()
                curve_id = "live-SDR_INTRADAY-RL_USD_SOFR_MTV2_Q12X11"
                ts_out, rl_curve = rl_usd_sofr_mt_curve(
                    curve_id=curve_id,
                    snap="live",
                    sofr_fixings=sofr_fixings,
                    cache=None,
                    force_refresh=True,
                )
                out["live"] = RLIRSwapCurve(
                    rl_curve_id="USD-SOFR-1D",
                    rl_curve_handle=rl_curve,
                    fixings=sofr_fixings,
                    meta_data={"timestamp": ts_out, "id": curve_id},
                )

            return out

        elif "GSQUANT-RL" in self.source.upper() or "GSQUANT_RL" in self.source.upper():
            from rateslib import from_json

            bdates: List[datetime.date] = [self._to_gsquant_eod_date(t) for t in timestamps]
            fixings_cache = self._build_fixings_cache_for_dates(
                curve_name=self._resolve_gsquant_reference_curve_name(curve_name),
                as_of_dates=bdates,
            )

            if self._supports_curve_store_raw_curve_fast_path():
                try:
                    out.update(
                        self._load_gsquant_curve_store_history(
                            requested_curve_name=curve_name,
                            request_dates=bdates,
                            fixings_cache=fixings_cache,
                            max_workers=max(1, int(n_jobs or 1)),
                        )
                    )
                    if len([d for d in bdates if d in out]) >= len(bdates):
                        return out
                except Exception as _tier0_exc:
                    logging.getLogger(__name__).debug(
                        "GSQUANT CurveStore Tier 0 fast path failed: %s", _tier0_exc,
                    )
            if ignore_cache_miss:
                return out

            remaining_dates = [d for d in bdates if d not in out]
            built = self._rl_curve_cache.bulk_get_gsquant_rl_basic(
                curve_id=curve_name,
                bdates=remaining_dates,
                force_refresh=ignore_cache,
                max_workers=max(1, int(n_jobs or 1)),
            )

            for ref_date in remaining_dates:
                payload = built.get(ref_date)
                if payload is None:
                    continue
                curve_id, rl_curve_serialized, pricing_location = payload
                out[ref_date] = self._build_gsquant_rl_curve(
                    requested_curve_name=curve_name,
                    request_timestamp=ref_date,
                    rl_curve_handle=from_json(rl_curve_serialized),
                    pricing_location=pricing_location,
                    curve_id=curve_id,
                    fixings_cache=fixings_cache,
                )
                self._promote_gsquant_curve_store_day(
                    requested_curve_name=curve_name,
                    curve=out[ref_date],
                    request_timestamp=ref_date,
                )

            return out

        elif self.source.upper() in ["BARCHART_STIRF-RL", "BARCHART_STIRF_RL"]:
            local_request = dict(request)
            local_request.setdefault("force_refresh", bool(ignore_cache))
            if calibration_executor == "process" and "live" in timestamps:
                raise ValueError("Process-pool calibration only supports bulk historical BARCHART STIRF runs, not live timestamps.")
            if "live" not in timestamps:
                builder = self._get_barchart_stirf_curve_builder()
                bulk_request = dict(local_request)
                bulk_request["cache_full_intraday_fetch"] = True
                bulk_request.setdefault("show_tqdm", False)
                bulk_request["calibration_executor"] = calibration_executor
                if n_jobs_requested:
                    bulk_request.setdefault("calibration_max_workers", n_jobs)
                resolved_curve_name = self._resolve_barchart_stirf_curve_name(
                    requested_curve_name=curve_name,
                    kwargs=bulk_request,
                    builder=builder,
                )

                rl_timestamps: List[datetime.datetime] = []
                timestamps_by_rl_timestamp: Dict[datetime.datetime, List[Union[datetime.date, datetime.datetime, Literal["live"]]]] = {}
                for t in timestamps:
                    rl_timestamp = self._to_barchart_stirf_timestamp(t)
                    assert rl_timestamp != "live"
                    rl_timestamps.append(rl_timestamp)
                    timestamps_by_rl_timestamp.setdefault(rl_timestamp, []).append(t)

                # ── Tier 0: CurveStore Parquet fast path ──
                # Attempt bulk read from Parquet store. If all timestamps are
                # found, reconstruct rl.Curve objects and skip diskcache entirely.
                if not ignore_cache:
                    try:
                        store = self._get_curve_store()
                        import pandas as _pd
                        parquet_df = _pd.DataFrame()
                        try:
                            parquet_df = store.read_raw_nodes(
                                resolved_curve_name,
                                timestamps_utc=list(set(rl_timestamps)),
                            )
                        except TypeError:
                            unique_dates = sorted({
                                builder._trading_date_for_timestamp(t)
                                for t in rl_timestamps
                            })
                            day_dfs = []
                            for d in unique_dates:
                                day_df = store.read_raw_day(resolved_curve_name, d)
                                if not day_df.empty:
                                    day_dfs.append(day_df)
                            if day_dfs:
                                parquet_df = _pd.concat(day_dfs, ignore_index=True)

                        if not parquet_df.empty:
                            # Index by timestamp_utc for fast lookup (normalize to second precision).
                            # NB: must CONVERT to UTC, never relabel — read_raw_nodes returns a
                            # session-tz column for multi-date reads (DuckDB) and a UTC one for
                            # single-date reads (PyArrow short-circuit), so a `.replace(tzinfo=UTC)`
                            # here shifted every multi-date key by the local UTC offset and missed
                            # 100% of the time.
                            parquet_ts_set = set()
                            if "timestamp_utc" in parquet_df.columns:
                                for ts_val in parquet_df["timestamp_utc"]:
                                    key = self._curve_store_timestamp_key(ts_val)
                                    parquet_ts_set.add(key if key is not None else ts_val)

                            # Check coverage: do we have ALL requested timestamps?
                            rl_ts_utc = set()
                            for ts in set(rl_timestamps):
                                ts_utc = ts.astimezone(pytz.UTC).replace(microsecond=0)
                                rl_ts_utc.add(ts_utc)

                            # Match with tolerance (second-level)
                            matched_count = sum(
                                1 for ts in rl_ts_utc
                                if ts in parquet_ts_set
                            )

                            if matched_count >= len(rl_ts_utc) or ignore_cache_miss:
                                # All found — reconstruct and return
                                cfg = builder._STIRF_CURVE_CONFIGS[resolved_curve_name]
                                parquet_ts_keys = parquet_df["timestamp_utc"].map(
                                    lambda ts_val: (
                                        self._curve_store_timestamp_key(ts_val)
                                        if self._curve_store_timestamp_key(ts_val) is not None
                                        else ts_val
                                    )
                                )
                                parquet_df = parquet_df.loc[parquet_ts_keys.isin(rl_ts_utc)].copy()
                                curves_by_ts = store.reconstruct_curves_batch(
                                    parquet_df, cfg=cfg, max_workers=4,
                                )

                                fixings_cache_t0: Dict[tuple, _pd.Series] = {}
                                for rl_timestamp, original_timestamps in timestamps_by_rl_timestamp.items():
                                    ts_utc = rl_timestamp.astimezone(pytz.UTC).replace(microsecond=0)
                                    rl_curve_handle = curves_by_ts.get(ts_utc)
                                    if rl_curve_handle is None:
                                        # Try pandas Timestamp key
                                        for k, v in curves_by_ts.items():
                                            if hasattr(k, "to_pydatetime"):
                                                kk = k.to_pydatetime()
                                                if kk.tzinfo is None:
                                                    kk = pytz.UTC.localize(kk)
                                                if abs((kk - ts_utc).total_seconds()) < 1:
                                                    rl_curve_handle = v
                                                    break
                                            elif isinstance(k, datetime.datetime):
                                                kk = k if k.tzinfo else pytz.UTC.localize(k)
                                                if abs((kk - ts_utc).total_seconds()) < 1:
                                                    rl_curve_handle = v
                                                    break

                                    if rl_curve_handle is None:
                                        continue
                                    curve_wrapper = self._build_barchart_stirf_rl_curve(
                                        requested_curve_name=curve_name,
                                        resolved_curve_name=resolved_curve_name,
                                        request_timestamp=original_timestamps[0],
                                        rl_curve_handle=rl_curve_handle,
                                        builder=builder,
                                        fixings_cache=fixings_cache_t0,
                                    )
                                    for original_timestamp in original_timestamps:
                                        out[original_timestamp] = curve_wrapper

                                if len(out) >= len(timestamps_by_rl_timestamp):
                                    return out
                                if ignore_cache_miss:
                                    return out
                                # Partial hit — fall through to existing path for misses
                    except Exception as _tier0_exc:
                        import logging as _logging
                        _logging.getLogger(__name__).debug(
                            "CurveStore Tier 0 fast path failed: %s", _tier0_exc,
                        )

                # ── Tier 1+2: diskcache + solver fallback ──
                if ignore_cache_miss:
                    return out
                fixings_cache: Dict[tuple[datetime.date, str], pd.Series] = {}

                def _wrap_barchart_curves(curve_handles_by_timestamp: Dict[datetime.datetime, Any]) -> None:
                    for rl_timestamp, original_timestamps in timestamps_by_rl_timestamp.items():
                        rl_curve_handle = curve_handles_by_timestamp.get(rl_timestamp)
                        if rl_curve_handle is None:
                            continue
                        curve = self._build_barchart_stirf_rl_curve(
                            requested_curve_name=curve_name,
                            resolved_curve_name=resolved_curve_name,
                            request_timestamp=original_timestamps[0],
                            rl_curve_handle=rl_curve_handle,
                            builder=builder,
                            fixings_cache=fixings_cache,
                        )
                        for original_timestamp in original_timestamps:
                            out[original_timestamp] = curve

                def _attempt_bulk_build(
                    batch_timestamps: Sequence[datetime.datetime],
                    *,
                    request_kwargs: Dict[str, Any],
                ) -> Dict[datetime.datetime, Any]:
                    if not batch_timestamps:
                        return {}
                    with self._suppress_ratelibs_solver_output():
                        built = builder.build_curve(
                            curve_name=resolved_curve_name,
                            timestamp=list(batch_timestamps),
                            kwargs=request_kwargs,
                            curve_only=True,
                        )
                    if not isinstance(built, dict):
                        return {}
                    return {
                        ts: built.get(ts)
                        for ts in batch_timestamps
                        if built.get(ts) is not None
                    }

                built_curves: Dict[datetime.datetime, Any] = {}
                bulk_build_exc: Optional[Exception] = None
                try:
                    built_curves = _attempt_bulk_build(rl_timestamps, request_kwargs=bulk_request)
                except Exception as exc:
                    bulk_build_exc = exc

                if bulk_build_exc is not None and calibration_executor == "process":
                    raise RuntimeError("Process-pool calibration failed for BARCHART STIRF bulk_get_data.") from bulk_build_exc

                if built_curves:
                    _wrap_barchart_curves(built_curves)
                if calibration_executor == "process":
                    return out

                retry_request = dict(bulk_request)
                retry_request["show_tqdm"] = False

                remaining_rl_timestamps = [
                    rl_timestamp
                    for rl_timestamp in timestamps_by_rl_timestamp
                    if rl_timestamp not in built_curves
                ]
                if remaining_rl_timestamps:
                    by_trading_date: Dict[datetime.date, List[datetime.datetime]] = {}
                    for rl_timestamp in remaining_rl_timestamps:
                        by_trading_date.setdefault(builder._trading_date_for_timestamp(rl_timestamp), []).append(rl_timestamp)

                    for trading_date in sorted(by_trading_date):
                        day_timestamps = by_trading_date[trading_date]
                        recovered_day: Dict[datetime.datetime, Any] = {}
                        try:
                            recovered_day = _attempt_bulk_build(day_timestamps, request_kwargs=retry_request)
                        except Exception:
                            logging.getLogger(__name__).debug(
                                "BARCHART STIRF day-chunk retry failed for %s (%s timestamps)",
                                trading_date,
                                len(day_timestamps),
                                exc_info=True,
                            )
                        if recovered_day:
                            built_curves.update(recovered_day)

                        remaining_day_timestamps = [
                            rl_timestamp
                            for rl_timestamp in day_timestamps
                            if rl_timestamp not in recovered_day
                        ]
                        if not remaining_day_timestamps:
                            continue

                        for offset in range(0, len(remaining_day_timestamps), 120):
                            subchunk = remaining_day_timestamps[offset : offset + 120]
                            recovered_chunk: Dict[datetime.datetime, Any] = {}
                            try:
                                recovered_chunk = _attempt_bulk_build(subchunk, request_kwargs=retry_request)
                            except Exception:
                                logging.getLogger(__name__).debug(
                                    "BARCHART STIRF subchunk retry failed for %s (%s timestamps)",
                                    trading_date,
                                    len(subchunk),
                                    exc_info=True,
                                )
                            if recovered_chunk:
                                built_curves.update(recovered_chunk)

                if built_curves:
                    _wrap_barchart_curves(built_curves)
                if len(out) >= len(timestamps_by_rl_timestamp):
                    return out

                timestamps = [
                    original_timestamp
                    for original_timestamp in timestamps
                    if original_timestamp not in out
                ]
                if not timestamps:
                    return out
            elif ignore_cache_miss:
                return out

            for t in tqdm.tqdm(timestamps, desc=f"Building curves for {self.source}"):
                try:
                    out[t] = self._get_curve(
                        curve_name=curve_name,
                        timestamp=t,
                        kwargs=dict(local_request) | {"cache_full_intraday_fetch": True, "show_tqdm": False},
                    )
                except Exception:
                    continue
            return out

        elif self.source.upper() in ["ERIS_LIVE_INTRADAY", "ERIS_LIVE-INTRADAY"]:
            assert curve_name == "USD-SOFR-1D", "SOFR!"  # fail fast, matching the single-point path
            # Large-scale intraday batch path (port of the BARCHART_STIRF Tier-0
            # optimization): ONE range read + ONE parallel reconstruct pass +
            # request->snapshot dedup fan-out, replacing N indexed as-of queries +
            # N reconstructs + N fixings fetches. Value-identical to N calls of
            # _load_eris_live_intraday_point.
            from Caching.curve_store import CurveStore
            from Caching.supabase_curve_sync import SupabaseCurveSync
            from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

            ASSET = self._ERIS_LIVE_STORE_ASSET
            NYC = pytz.timezone("America/New_York")
            method = str(request.get("method", "asof"))
            sync = SupabaseCurveSync.from_defaults()

            # nearest/exact: keep the proven per-timestamp semantics exactly
            # (this IS the pre-optimization branch body, unchanged). asof is the
            # batched fast path below.
            if method != "asof":
                for t in timestamps:
                    try:
                        curve = self._load_eris_live_intraday_point(
                            requested_curve_name=curve_name,
                            timestamp=t,
                            method=method,
                            sync=sync,
                        )
                    except Exception:
                        continue
                    if curve is not None:
                        out[t] = curve
                return out

            # ======================= method == "asof" =======================
            # Per-ref-date SOFR fixings memo (identical values to the single-point
            # slice, just fetched once per distinct ref date instead of per snapshot).
            fixings_by_ref: Dict[datetime.date, pd.Series] = {}

            def _fixings_for_ref(ref: datetime.date) -> pd.Series:
                cached = fixings_by_ref.get(ref)
                if cached is None:
                    s = _fetch_fixings(
                        as_of_date=ref,
                        curve_name=curve_name,
                        force_refresh=self.force_refresh_fixings,
                    ).sort_index()
                    cached = s[s.index.date < ref] * 100
                    fixings_by_ref[ref] = cached
                return cached

            def _wrap(row: dict, rl_curve_handle: Any) -> "RLIRSwapCurve":
                # Byte-identical wrapping to _load_eris_live_intraday_point.
                snap_utc = pd.Timestamp(row["timestamp_utc"])
                if snap_utc.tzinfo is None:
                    snap_utc = snap_utc.tz_localize("UTC")
                snap_et = snap_utc.tz_convert(NYC)
                ref = snap_et.date()
                ts_out = snap_et.to_pydatetime()
                curve_id = f"{self.source.upper()}-{curve_name}-{ts_out}"
                return RLIRSwapCurve(
                    rl_curve_id=curve_name,
                    rl_curve_handle=rl_curve_handle,
                    fixings=_fixings_for_ref(ref),
                    meta_data={"timestamp": ts_out, "id": curve_id, "source": "eris_live_intraday"},
                )

            def _target_utc(t) -> pd.Timestamp:
                ts = pd.Timestamp(t)
                if ts.tzinfo is None:
                    ts = ts.tz_localize(NYC)  # naive assumed ET
                return ts.tz_convert("UTC")

            live_targets = [t for t in timestamps if isinstance(t, str) and t == "live"]
            dt_targets = [t for t in timestamps if not (isinstance(t, str) and t == "live")]

            # ---- (a) 'live' -> latest snapshot (shared across any 'live' targets)
            if live_targets:
                try:
                    live_row = sync.pull_latest_snapshot(ASSET)
                    if live_row is not None:
                        live_wrapper = _wrap(live_row, CurveStore.reconstruct_curve(live_row, cfg=None))
                        for t in live_targets:
                            out[t] = live_wrapper
                except Exception:
                    logging.getLogger(__name__).debug(
                        "ERIS live-intraday bulk: 'live' snapshot failed", exc_info=True
                    )

            # ---- (b) as-of batch for datetime/date targets
            if dt_targets:
                try:
                    target_utcs = [_target_utc(t) for t in dt_targets]
                    min_target = min(target_utcs)
                    max_target = max(target_utcs)

                    # Exact as-of row for the EARLIEST target -> provably-sufficient
                    # lower bound so every backward match sits inside the fetched window.
                    floor_row = sync.pull_snapshot_asof(ASSET, min_target.to_pydatetime(), "asof")
                    if floor_row is not None:
                        lo = pd.Timestamp(floor_row["timestamp_utc"])
                        lo = lo.tz_localize("UTC") if lo.tzinfo is None else lo.tz_convert("UTC")
                    else:
                        lo = min_target  # nothing at/before earliest target -> those omitted

                    if self._eris_local_l1_enabled():
                        # L1: settled ET trading-days served from local Parquet
                        # (materialized once on first touch); today from a remote
                        # window clamped to [lo, max_target] so the live edge is
                        # not over-fetched.
                        store = self._get_curve_store()
                        today_et = datetime.datetime.now(NYC).date()
                        floor_td = (
                            floor_row["trading_date"] if floor_row is not None
                            else pd.Timestamp(min_target).tz_convert(NYC).date()
                        )
                        max_td = pd.Timestamp(max_target).tz_convert(NYC).date()
                        # keep curve_name so reconstruct_curve sets curve.curve_name to
                        # the store asset key (parity with the non-L1 / single-point paths)
                        _cols = ["timestamp_utc", "curve_name", "node_dates",
                                 "discount_factors", "reference_key", "interpolation"]
                        frames = []
                        d = floor_td
                        last_settled = min(max_td, today_et - datetime.timedelta(days=1))
                        while d <= last_settled:
                            fr = self._ensure_eris_day_local(store, sync, ASSET, d, today_et)
                            if fr is not None and not fr.empty:
                                frames.append(fr[_cols])
                            d += datetime.timedelta(days=1)
                        if max_td >= today_et:
                            today_lo = max(
                                lo,
                                pd.Timestamp(NYC.localize(
                                    datetime.datetime.combine(today_et, datetime.time())
                                ).astimezone(pytz.UTC)),
                            )
                            if today_lo <= max_target:
                                fr = sync.pull_snapshots_range(
                                    ASSET, today_lo.to_pydatetime(), max_target.to_pydatetime()
                                )
                                if fr is not None and not fr.empty:
                                    frames.append(fr[_cols])
                        snaps_df = (
                            pd.concat(frames, ignore_index=True)
                            if frames else pd.DataFrame(columns=_cols)
                        )
                    else:
                        snaps_df = sync.pull_snapshots_range(
                            ASSET, lo.to_pydatetime(), max_target.to_pydatetime()
                        )

                    if not snaps_df.empty:
                        snaps_df = snaps_df.copy()
                        snaps_df["timestamp_utc"] = pd.to_datetime(snaps_df["timestamp_utc"], utc=True)
                        snaps_df = snaps_df.sort_values("timestamp_utc").reset_index(drop=True)

                        # Positional index keeps original request objects out of the
                        # DataFrame (a column would coerce date/datetime -> Timestamp).
                        targets_df = pd.DataFrame(
                            {"i": range(len(dt_targets)),
                             "target_utc": pd.to_datetime(target_utcs, utc=True)}
                        ).sort_values("target_utc").reset_index(drop=True)

                        merged = pd.merge_asof(
                            targets_df,
                            snaps_df[["timestamp_utc"]],
                            left_on="target_utc",
                            right_on="timestamp_utc",
                            direction="backward",  # == pull_snapshot_asof(method="asof")
                        )

                        matched_ts = merged["timestamp_utc"].dropna().unique()
                        if len(matched_ts):
                            distinct_df = snaps_df[snaps_df["timestamp_utc"].isin(matched_ts)].copy()
                            curves_by_ts = CurveStore.reconstruct_curves_batch(
                                distinct_df,
                                cfg=None,  # ERIS: no mixed_interpolation
                                max_workers=self._resolve_curve_store_history_workers(
                                    n_jobs, task_count=len(distinct_df)
                                ),
                            )
                            # One wrapper per distinct snapshot, shared across every
                            # target that mapped to it (meta is a function of the
                            # snapshot, not the request) -> value-identical to per-target.
                            wrapper_by_key: Dict[pd.Timestamp, "RLIRSwapCurve"] = {}
                            for ts_val, rl_curve_handle in curves_by_ts.items():
                                key = pd.Timestamp(ts_val).tz_convert("UTC")
                                wrapper_by_key[key] = _wrap({"timestamp_utc": ts_val}, rl_curve_handle)

                            for _, mrow in merged.iterrows():
                                snap_ts = mrow["timestamp_utc"]
                                if pd.isna(snap_ts):
                                    continue  # target before earliest snapshot -> omitted
                                wrapper = wrapper_by_key.get(pd.Timestamp(snap_ts).tz_convert("UTC"))
                                if wrapper is not None:
                                    out[dt_targets[int(mrow["i"])]] = wrapper
                except Exception:
                    logging.getLogger(__name__).debug(
                        "ERIS live-intraday bulk as-of batch failed; salvaging via single-point",
                        exc_info=True,
                    )
                    # Best-effort accelerator: on any batch failure, fill remaining
                    # targets one-by-one so results never regress vs the old branch.
                    for t in dt_targets:
                        if t in out:
                            continue
                        try:
                            curve = self._load_eris_live_intraday_point(
                                requested_curve_name=curve_name,
                                timestamp=t, method="asof", sync=sync,
                            )
                        except Exception:
                            continue
                        if curve is not None:
                            out[t] = curve

            return out

        # ------- default / not implemented -------
        # Fallback: build curves one-by-one for sources without a dedicated bulk implementation.
        for t in timestamps:
            single_request = dict(request)
            single_request["curve_name"] = curve_name
            single_request["timestamp"] = t
            single_request["ignore_cache"] = bool(ignore_cache)
            try:
                curve = self.get_data(single_request)
            except Exception:
                continue
            if curve is not None:
                out[t] = curve
        return out


def _normalize_leg(s: str) -> str:
    import re

    # grab tenor tokens like 3M, 6m, 1Y, 2y (case-insensitive)
    parts = re.findall(r"\d+\s*[dwmy]", s, flags=re.I)
    parts = [p.upper().replace(" ", "") for p in parts]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}x{parts[1]}"
    raise ValueError(f"Unexpected leg format: {s!r}")


def _format_fly_str(s: str) -> tuple[str]:
    w1, b, w2 = s.split("/")
    return _normalize_leg(w1), _normalize_leg(b), _normalize_leg(w2)
