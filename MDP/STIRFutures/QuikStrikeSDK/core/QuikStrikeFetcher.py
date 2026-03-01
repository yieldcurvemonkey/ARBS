import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import pandas as pd
import tqdm
import httpx

from MDP.STIRFutures.QuikStrikeSDK.core._QuikVolCalculatorFetcher import _QuikVolCalculationFetcher
from MDP.STIRFutures.QuikStrikeSDK.core._QuikVolTermStructureFetcher import _QuikVolTermStructureFetcher
from MDP.STIRFutures.QuikStrikeSDK.core._QuikVolTimeseriesFetcher import _QuikVolTimeseriesFetcher
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolQuery import QuikVolQuery
from MDP.STIRFutures.QuikStrikeSDK.core.utils.misc import HTTPXProxies


class QuikStrikeFetcher:
    _cme_insid: str
    _cme_qsid: str
    _timeout: str
    _proxies: HTTPXProxies
    _log_level: int
    _max_connections: int
    _max_keepalive: int
    _max_retries: int
    _backoff_factor: float

    def __init__(
        self,
        cme_insid: str,
        cme_qsid: Union[int, str],
        run_selenium: Optional[bool] = False,
        timeout: Optional[float] = 10.0,
        proxies: Optional[HTTPXProxies] = None,
        log_level: Optional[int] = logging.WARN,
        max_connections: Optional[int] = 12,
        max_keepalive: Optional[int] = 5,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[float] = 0.5,
    ) -> None:
        self._cme_insid = cme_insid
        self._cme_qsid = cme_qsid
        self._timeout = timeout
        self._proxies = proxies
        self._log_level = log_level
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

        self._init_term_structure_fetcher()
        self._init_vol_timeseries_fetcher()
        self._init_calculation_fetcher()

        if run_selenium:
            self._term_structure_fetcher._activate_quikstrike_page()

    def _init_term_structure_fetcher(self) -> None:
        self._term_structure_fetcher = _QuikVolTermStructureFetcher(
            cme_insid=self._cme_insid,
            cme_qsid=self._cme_qsid,
            timeout=self._timeout,
            proxies=self._proxies,
            log_level=self._log_level,
            max_connections=self._max_connections,
            max_keepalive=self._max_keepalive,
            max_retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

    def _init_vol_timeseries_fetcher(self) -> None:
        self._vol_timeseries_fetcher = _QuikVolTimeseriesFetcher(
            cme_insid=self._cme_insid,
            cme_qsid=self._cme_qsid,
            timeout=self._timeout,
            proxies=self._proxies,
            log_level=self._log_level,
            max_connections=self._max_connections,
            max_keepalive=self._max_keepalive,
            max_retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

    def _init_calculation_fetcher(self) -> None:
        self._calculation_fetcher = _QuikVolCalculationFetcher(
            cme_insid=self._cme_insid,
            cme_qsid=self._cme_qsid,
            timeout=self._timeout,
            proxies=self._proxies,
            log_level=self._log_level,
            max_connections=self._max_connections,
            max_keepalive=self._max_keepalive,
            max_retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

    async def fetch_product_status_async_worker(self, qv_pid: QuikVolProductID):
        if getattr(self._term_structure_fetcher._client, "is_closed", False):
            self._init_term_structure_fetcher()
        return await self._term_structure_fetcher.get_product_status(qv_pid)

    def fetch_product_status(self, qv_pid: QuikVolProductID):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(self.fetch_product_status_async_worker(qv_pid=qv_pid))
        self.close()
        return result

    async def fetch_latest_atm_term_structure_async_worker(
        self,
        qv_pid: QuikVolProductID,
    ) -> Tuple[str, Dict[str, float]]:
        if getattr(self._term_structure_fetcher._client, "is_closed", False):
            self._init_term_structure_fetcher()
        return await self._term_structure_fetcher.fetch_latest_atm_term_structure(qv_pid)

    def fetch_latest_atm_term_structures(
        self,
        qv_pids: List[QuikVolProductID],
    ) -> Dict[str, Tuple[str, Dict[str, float]]]:

        async def fetch_all(
            qv_pids: List[QuikVolProductID],
        ) -> Dict[str, Any]:

            future_to_name: Dict[asyncio.Task, str] = {}
            underlyings_pid_status = set()

            for qv_pid in qv_pids:
                tname = f"{qv_pid.name}_atm_vol_term_structure"
                task1 = asyncio.create_task(self.fetch_latest_atm_term_structure_async_worker(qv_pid))
                future_to_name[task1] = tname

                if not qv_pid.value.underlying_pid in underlyings_pid_status:
                    pname = f"{qv_pid.name}_pid_status"
                    task2 = asyncio.create_task(self.fetch_product_status_async_worker(qv_pid))
                    future_to_name[task2] = pname

                underlyings_pid_status.add(qv_pid.value.underlying_pid)

            pending = set(future_to_name.keys())
            results: Dict[str, Any] = {}

            with tqdm.tqdm(total=len(pending), desc="FETCHING ATM VOL TERM STRUCTURES...") as pbar:
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for fut in done:
                        name = future_to_name[fut]
                        try:
                            results[name] = fut.result()
                        except Exception as e:
                            results[name] = ("ERROR", {"error": str(e)})
                        pbar.update(1)

            return results

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if getattr(self._term_structure_fetcher._client, "is_closed", False):
            self._init_term_structure_fetcher()

        results = loop.run_until_complete(fetch_all(qv_pids))
        self.close()
        return results

    async def fetch_latest_surface_async_worker(
        self,
        qv_pid: QuikVolProductID,
    ) -> Tuple[str, Dict[str, float]]:
        if getattr(self._term_structure_fetcher._client, "is_closed", False):
            self._init_term_structure_fetcher()
        return await self._term_structure_fetcher.fetch_latest_surface(qv_pid)

    def fetch_latest_surface(
        self,
        qv_pid: QuikVolProductID,
    ) -> pd.DataFrame:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(self._term_structure_fetcher.fetch_latest_surface(qv_pid=qv_pid))
        self.close()
        return result

    async def fetch_quikvol_timeseries_async(
        self,
        start_date: datetime,
        end_date: datetime,
        queries: List[QuikVolQuery],
    ) -> pd.DataFrame:
        client = self._vol_timeseries_fetcher._client
        if getattr(client, "is_closed", False):
            self._init_vol_timeseries_fetcher()

        return await self._vol_timeseries_fetcher.fetch_timeseries(start_date, end_date, queries)

    def fetch_quikvol_timeseries(
        self,
        start_date: datetime,
        end_date: datetime,
        queries: List[QuikVolQuery],
    ) -> pd.DataFrame:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        client = self._vol_timeseries_fetcher._client
        if getattr(client, "is_closed", False):
            self._init_vol_timeseries_fetcher()

        df: pd.DataFrame = loop.run_until_complete(self.fetch_quikvol_timeseries_async(start_date, end_date, queries))
        self.close()
        return df

    def close(self) -> None:
        # close term-structure and timeseries clients
        for fetcher in (self._term_structure_fetcher, self._vol_timeseries_fetcher):
            client = getattr(fetcher, "_client", None)
            if client and not getattr(client, "is_closed", False):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(fetcher.aclose())
                    else:
                        loop.run_until_complete(fetcher.aclose())
                except RuntimeError:
                    asyncio.run(fetcher.aclose())

        # close calculation fetcher client
        calc = getattr(self, "_calculation_fetcher", None)
        if calc and hasattr(calc, "aclose"):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(calc.aclose())
                else:
                    loop.run_until_complete(calc.aclose())
            except RuntimeError:
                asyncio.run(calc.aclose())

    async def single_contract_pricer_async(
        self,
        product: QuikVolProductID,
        option_contract: str,
        option_type: Optional[Literal["Call", "Put", "Straddle"]] = "Straddle",
        option_strike_price: Optional[float] = None,
        option_premium: Optional[float] = None,
        option_vol: Optional[float] = None,
    ) -> str:
        if getattr(self._calculation_fetcher._client, "is_closed", False):
            self._init_calculation_fetcher()
        return await self._calculation_fetcher.single_contract_pricer(
            product=product,
            option_contract=option_contract,
            option_type=option_type,
            option_strike_price=option_strike_price,
            option_premium=option_premium,
            option_vol=option_vol,
        )

    def single_contract_pricer(
        self,
        product: QuikVolProductID,
        option_contract: str,
        option_type: Optional[Literal["Call", "Put", "Straddle"]] = "Straddle",
        option_strike_price: Optional[float] = None,
        option_premium: Optional[float] = None,
        option_vol: Optional[float] = None,
    ) -> str:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if getattr(self._calculation_fetcher._client, "is_closed", False):
            self._init_calculation_fetcher()

        result = loop.run_until_complete(
            self.single_contract_pricer_async(
                product=product,
                option_contract=option_contract,
                option_type=option_type,
                option_strike_price=option_strike_price,
                option_premium=option_premium,
                option_vol=option_vol,
            )
        )
        self.close()
        return result

    def _reopen_calculation_client(self):
        limits = httpx.Limits(
            max_connections=self._max_connections,
            max_keepalive_connections=self._max_keepalive,
        )
        self._calculation_fetcher._client = httpx.AsyncClient(
            timeout=self._timeout,
            mounts=self._proxies or {},
            limits=limits,
            http2=True,
        )

    async def get_latest_calculated_smile_async(
        self,
        product: QuikVolProductID,
        option_contract: str,
    ) -> str:
        if getattr(self._calculation_fetcher._client, "is_closed", False):
            self._init_calculation_fetcher()
        return await self._calculation_fetcher.get_latest_calculated_smile(product, option_contract)

    def get_latest_calculated_smile(
        self,
        product: QuikVolProductID,
        option_contract: str,
    ) -> pd.DataFrame:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if getattr(self._calculation_fetcher._client, "is_closed", False):
            self._reopen_calculation_client()

        result = loop.run_until_complete(self.get_latest_calculated_smile_async(product, option_contract))
        self.close()
        return result

    @classmethod
    async def async_client(
        cls,
        insid: str,
        qsid: Union[int, str],
        timeout: float = 10.0,
        proxies: Optional[Dict[str, str]] = None,
        log_level: int = logging.WARN,
        max_connections: int = 5,
        max_keepalive: int = 2,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        client = cls(
            insid=insid,
            qsid=qsid,
            timeout=timeout,
            proxies=proxies,
            log_level=log_level,
            max_connections=max_connections,
            max_keepalive=max_keepalive,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
        )
        return client

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._term_structure_fetcher.aclose()
