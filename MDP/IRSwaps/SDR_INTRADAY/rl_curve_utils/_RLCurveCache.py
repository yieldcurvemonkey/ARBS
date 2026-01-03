import datetime
import hashlib
import re
from typing import List, Optional, Union, Literal, Tuple, Dict

import pandas as pd

from Caching.ZODBCacheMixin import ZODBCacheMixin


def _series_sha1(s: pd.Series) -> str:
    ss = s.copy()
    ss.index = pd.to_datetime(ss.index)
    ss = ss.sort_index()
    parts = (f"{idx.date().isoformat()}={val:.12g}" for idx, val in ss.items())
    h = hashlib.sha1("\n".join(parts).encode()).hexdigest()
    return h[:10]


def _normalize_snap(snap: Union[datetime.date, datetime.datetime, List[Union[datetime.date, datetime.datetime]]]) -> List[str]:
    def _one(x):
        if isinstance(x, datetime.datetime):
            return x.replace(microsecond=0).isoformat(timespec="seconds")
        elif isinstance(x, datetime.date):
            return datetime.datetime.combine(x, datetime.time()).isoformat(timespec="seconds")
        else:
            raise TypeError(f"Unsupported snap type: {type(x)}")

    if isinstance(snap, (list, tuple)):
        return [_one(x) for x in snap]
    return [_one(snap)]


def _make_key(
    curve_id: str,
    snap: Union[datetime.date, datetime.datetime, List[Union[datetime.date, datetime.datetime]]],
    sofr_fixings: pd.Series,
    n_ser: int,
    n_sfr: int,
    n_plus_fomc_years: int,
) -> str:
    snap_norm = _normalize_snap(snap)
    fhash = _series_sha1(sofr_fixings)
    base = f"{curve_id}__snap={','.join(snap_norm)}__fx={fhash}__ser={n_ser}__sfr={n_sfr}__fomc={n_plus_fomc_years}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base)[:200]


class _RLCurveCache(ZODBCacheMixin):

    def __init__(
        self,
        cache_name: str,
        *,
        path: Optional[str] = None,
        use_btree: bool = True,
        force_refresh: bool = False,
    ) -> None:
        super().__init__(use_btree=use_btree, force_refresh=force_refresh)
        self._cache_attr = cache_name
        self._path = path or self.default_cache_path(self._cache_attr)
        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path)

    # TODO refactor: make general, pass in kwargs

    def get_rl_usd_sofr_mt(
        self,
        *,
        curve_id: str,
        snap: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
        sofr_fixings: pd.Series,
        n_ser: int,
        n_sfr: int,
        n_plus_fomc_years: int,
        medium_term_tenors=["5Y", "10Y", "30Y"],
        max_tenor="30Y",
        extrapolation_yrs=20,
        force_refresh: bool = False,
    ):
        from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_sofr_mt_builder import rl_usd_sofr_mt_builder

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        key = _make_key(curve_id, snap, sofr_fixings, n_ser, n_sfr, n_plus_fomc_years)

        if not force_refresh and key in mapping:
            return mapping[key]

        result_json = rl_usd_sofr_mt_builder(
            curve_id=curve_id,
            snap=snap,
            sofr_fixings=sofr_fixings,
            n_ser_contracts=n_ser,
            n_sfr_contracts=n_sfr,
            n_plus_fomc_years=n_plus_fomc_years,
            medium_term_tenors=medium_term_tenors,
            max_tenor=max_tenor,
            extrapolation_yrs=extrapolation_yrs,
        ).rl_pricing_curve.to_json()

        mapping[key] = result_json
        self.zodb_commit()
        return result_json

    def get_rl_usd_sofr_stir(
        self,
        *,
        curve_id: str,
        snap: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
        sofr_fixings: pd.Series,
        n_ser: int,
        n_sfr: int,
        n_plus_fomc_years: int,
        force_refresh: bool = False,
    ):
        from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_curve_stir_builder import rl_usd_sofr_stir_builder

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        key = _make_key(curve_id, snap, sofr_fixings, n_ser, n_sfr, n_plus_fomc_years)

        if not force_refresh and key in mapping:
            return mapping[key]

        result_json = rl_usd_sofr_stir_builder(
            curve_id=curve_id,
            snap=snap,
            sofr_fixings=sofr_fixings,
            n_ser_contracts=n_ser,
            n_sfr_contracts=n_sfr,
            n_plus_fomc_years=n_plus_fomc_years,
        ).rl_pricing_curve.to_json()

        mapping[key] = result_json
        self.zodb_commit()
        return result_json

    def get_rl_usd_ois_stir(
        self,
        *,
        curve_id: str,
        snap: Union[datetime.datetime, datetime.date, List[Union[datetime.datetime, datetime.date]]],
        sofr_fixings: pd.Series,
        n_ser: int,
        n_sfr: int,
        n_plus_fomc_years: int,
        force_refresh: bool = False,
    ):
        from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.rl_usd_curve_stir_builder import rl_usd_ois_stir_builder

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        key = _make_key(curve_id, snap, sofr_fixings, n_ser, n_sfr, n_plus_fomc_years)

        if not force_refresh and key in mapping:
            return mapping[key]

        _, curve = rl_usd_ois_stir_builder(
            curve_id=curve_id,
            snap=snap,
            sofr_fixings=sofr_fixings,
            n_ser_contracts=n_ser,
            n_sfr_contracts=n_sfr,
            n_plus_fomc_years=n_plus_fomc_years,
        )
        result_json = curve.to_json()
        mapping[key] = result_json
        self.zodb_commit()
        return result_json

    def get_gsquant_rl_basic(
        self,
        *,
        curve_id: str,
        as_of: datetime.date,
        force_refresh: bool = False,
    ):
        from MDP.IRSwaps.GSQUANT.rl_basic.build import build_rl_basic_gsquant_curve

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        key = f"{as_of}-GSQUANT-rl_basic_{curve_id}"

        if not force_refresh and key in mapping:
            return key, mapping[key]["result"], mapping[key]["pricing_location"]

        _, curve, pricing_location = build_rl_basic_gsquant_curve(curve=curve_id, as_of=as_of)
        result_json = curve.to_json()
        mapping[key] = {
            "result": result_json,
            "pricing_location": pricing_location,
        }
        self.zodb_commit()
        return key, result_json, pricing_location

    def _eris_key(self, curve_id: str, as_of: Union[datetime.date, str]) -> str:
        return f"{as_of}-ERIS_EOD_LIVE-rl_basic_{curve_id}"

    def get_eris_eod_live_rl_basic(
        self,
        *,
        curve_id: str,
        as_of: Union[datetime.date, Literal["live"]],
        force_refresh: bool = False,
        no_jumps_just_interp: bool = False,
        fetcher_kwargs: Optional[dict] = None,
    ) -> Tuple[str, str, Union[datetime.date, datetime.datetime]]:
        from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        key = self._eris_key(curve_id, as_of)
        if as_of != "live" and (not force_refresh) and key in mapping:
            stored = mapping[key]
            return key, stored["result"], stored["timestamp"]

        eff = ErisFuturesFetcher()
        kwargs = dict(show_tqdm=False, return_intraday_timestamp=True)
        if fetcher_kwargs:
            kwargs.update(fetcher_kwargs)

        rl_curve, ts = eff.fetch_intraday_discount_curve(
            curve_id=curve_id,
            date=None if as_of == "live" else as_of,
            no_jumps_just_interp=no_jumps_just_interp,
            **kwargs,
        )
        result_json = rl_curve.to_json()

        if as_of != "live":
            mapping[key] = {"result": result_json, "timestamp": ts}
            self.zodb_commit()

        return key, result_json, ts

    def bulk_get_eris_eod_live_rl_basic(
        self,
        *,
        base_curve_id: str,
        bdates: List[datetime.date],
        force_refresh: bool = False,
        fetcher_kwargs: Optional[dict] = None,
    ) -> Dict[datetime.date, str]:
        from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher

        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._path, force=force_refresh)
        mapping = getattr(self, self._cache_attr)

        to_fetch: List[datetime.date] = []
        out: Dict[datetime.date, str] = {}

        if not force_refresh:
            for d in bdates:
                k = self._eris_key(base_curve_id, d)
                if k in mapping:
                    out[d] = mapping[k]["result"]
                else:
                    to_fetch.append(d)
        else:
            to_fetch = list(bdates)

        if to_fetch:
            eff = ErisFuturesFetcher(force_refresh=force_refresh)
            kwargs = dict(show_tqdm=False, return_intraday_timestamp=False)
            if fetcher_kwargs:
                kwargs.update(fetcher_kwargs)

            built = eff.fetch_intraday_discount_curve(
                curve_id=base_curve_id,
                bdates=to_fetch,
                **kwargs,
            )  # Dict[date, rl.Curve]

            pending = []
            for d, curve in built.items():
                k = self._eris_key(base_curve_id, d)
                js = curve.to_json()
                out[d] = js
                pending.append((k, {"result": js, "timestamp": d}))

            if pending:
                with self.batched():  # write-all-once pattern
                    mapping = getattr(self, self._cache_attr)  # refresh in case of proxy
                    for k, payload in pending:
                        mapping[k] = payload

        return out
