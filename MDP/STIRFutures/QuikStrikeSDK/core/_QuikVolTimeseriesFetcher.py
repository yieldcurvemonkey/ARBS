import logging
import warnings
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, List


from MDP.STIRFutures.QuikStrikeSDK.core._BaseQuikStrikeFetcher import _BaseQuikStrikeFetcher
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolQuery import QuikVolQuery
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolTimeseriesQueryBuilder import QuikVolTimeseriesQueryBuilder

warnings.simplefilter(action="ignore", category=FutureWarning)


class _QuikVolTimeseriesFetcher(_BaseQuikStrikeFetcher):

    def __init__(
        self,
        cme_insid: str,
        cme_qsid: int,
        timeout: Optional[float] = None,
        proxies: Optional[Dict[str, str]] = None,
        log_level: Optional[int] = logging.WARN,
        max_connections: Optional[int] = 5,
        max_keepalive: Optional[int] = 2,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[float] = 0.5,
    ):
        super().__init__(
            cme_insid=cme_insid,
            cme_qsid=cme_qsid,
            timeout=timeout or 10.0,
            proxies=proxies,
            log_level=log_level,
            max_connections=max_connections,
            max_keepalive=max_keepalive,
            http2=True,
        )

        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self.timeseries_url = f"https://cmegroup-tools.quikstrike.net/AjaxPages/Charts/QuikVol/Service.aspx/GetView?insid={self._cme_insid}&qsid={self._cme_qsid}"

    async def fetch_timeseries(self, start_date: datetime, end_date: datetime, queries: List[QuikVolQuery]) -> pd.DataFrame:
        timeseries_headers = self._base_headers.copy()
        timeseries_headers["referer"] = (
            f"https://cmegroup-tools.quikstrike.net//User/QuikStrikeView.aspx?pid=362&pf=3&viewitemid=AboutCMEHistory&insid={self._cme_insid}&qsid={self._cme_qsid}"
        )

        payload = {
            "criteria": {
                "minDate": start_date.timestamp() * 1000,
                "maxDate": end_date.timestamp() * 1000,
                "Series": [
                    QuikVolTimeseriesQueryBuilder.build_elements_dict(globex_symbol=q.globex_symbol, qv_value_type=q.qv_value_type, delta=q.delta, strike=q.strike)
                    for q in queries
                ],
            }
        }

        post = await self.request_with_retry(
            "POST",
            self.timeseries_url,
            headers=timeseries_headers,
            json=payload,
            retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

        data = post.json()["d"]["Series"]
        records = []
        for entry in data:
            for point in entry["Points"]:
                dt = pd.to_datetime(point["x"], unit="ms")
                records.append({"Date": dt, "Symbol": entry["Symbol"], "y": point["y"]})

        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame()
        return df.pivot(index="Date", columns="Symbol", values="y").rename_axis(columns=None)
