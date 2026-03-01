import asyncio
import logging
import re
import warnings
import pandas as pd

from datetime import datetime
from typing import Dict, Optional, Tuple

import ujson as json
from bs4 import BeautifulSoup

from MDP.STIRFutures.QuikStrikeSDK.core._BaseQuikStrikeFetcher import _BaseQuikStrikeFetcher
from MDP.STIRFutures.QuikStrikeSDK.core._QuikVolCalculatorFetcher import _QuikVolCalculationFetcher
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID

warnings.simplefilter(action="ignore", category=FutureWarning)


class _QuikVolTermStructureFetcher(_BaseQuikStrikeFetcher):

    def __init__(
        self,
        cme_insid: str,
        cme_qsid: int,
        timeout: Optional[float] = None,
        proxies: Optional[Dict[str, str]] = None,
        log_level: Optional[int] = logging.WARN,
        max_connections: Optional[int] = 12,
        max_keepalive: Optional[int] = 5,
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

        self._quikvol_calculator_fetcher = _QuikVolCalculationFetcher(
            cme_insid=cme_insid,
            cme_qsid=cme_qsid,
            timeout=timeout,
            proxies=proxies,
            log_level=log_level,
            max_keepalive=max_keepalive,
            max_retries=max_retries,
            backoff_factor=backoff_factor,
        )

    async def fetch_latest_atm_term_structure(
        self,
        qv_pid: QuikVolProductID,
    ) -> Dict[str, float]:
        pid = qv_pid.value.underlying_pid
        subnav_css = qv_pid.value.latest_atm_term_structure_event_target
        url = (
            f"https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx"
            f"?pid={pid}&pf=3&viewitemid=IntegratedVolTermTool"
            f"&insid={self._cme_insid}&qsid={self._cme_qsid}"
        )

        pattern = re.compile(r'JSONSettings"\s*:\s*"(?P<escaped>\{(?:\\.|[^"\\])*\})"', re.DOTALL)
        last_text = None

        for attempt in range(1, self._max_retries + 1):
            resp = await self.request_with_retry("POST", url, headers=self._base_headers, retries=1, backoff_factor=0)
            soup = BeautifulSoup(resp.text, "html.parser")

            # determine which eventTarget to fire
            if subnav_css and (el := soup.select_one(subnav_css)) and el.get("href"):
                m = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", el["href"])
                event_target, event_arg = m.groups()
            else:
                event_target, event_arg = "ctl00$ctl09$refreshButton", ""

            def _grab(name: str) -> str:
                tag = soup.find("input", {"name": name})
                return tag["value"] if tag and tag.has_attr("value") else ""

            payload = {
                "ctl00$smPublic": "ctl00$uplRibbons|ctl00$ctl09$refreshButton",
                "ctl00$MainContent$global_viewAttributes": _grab("ctl00$MainContent$global_viewAttributes"),
                "ctl00$MainContent$ucViewControl_IntegratedVolTermTool$ucTweet$twittercard_title": _grab(
                    "ctl00$MainContent$ucViewControl_IntegratedVolTermTool$ucTweet$twittercard_title"
                ),
                "__EVENTTARGET": event_target,
                "__EVENTARGUMENT": event_arg,
                "__VIEWSTATE": _grab("__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": _grab("__VIEWSTATEGENERATOR"),
                "__ASYNCPOST": "true",
            }

            post = await self.request_with_retry(
                "POST",
                url,
                headers=self._base_headers,
                data=payload,
                retries=1,
                backoff_factor=0,
            )
            last_text = post.text

            m = pattern.search(last_text)
            if m:
                escaped = m.group("escaped")
                unescaped = escaped.encode("utf-8").decode("unicode_escape")
                config = json.loads(unescaped)
                data = {c["dataLabels"]["format"]: float(c["y"]) * 100 for c in config["Series"][0]["data"]}
                return data

            # if we get here, the regex didn't match
            if attempt < self._max_retries:
                wait = self._backoff_factor * (2 ** (attempt - 1))
                self._logger.warning("Attempt %s/%s: JSONSettings not found, retrying in %.1fs…", attempt, self._max_retries, wait)
                await asyncio.sleep(wait)
            else:
                # last attempt, give up
                raise ValueError(f"Could not find JSONSettings after {self._max_retries} attempts. " f"Last response snippet: {last_text[:200]!r}")

    async def fetch_latest_smile(self, qv_pid: QuikVolProductID, option_contract: str) -> pd.DataFrame:
        return self._quikvol_calculator_fetcher.get_latest_calculated_smile(product=qv_pid, option_contract=option_contract)
    
    async def fetch_latest_surface(self, qv_pid: QuikVolProductID):
        atm_term_structure = await self.fetch_latest_atm_term_structure(qv_pid=qv_pid)
        return atm_term_structure 

    # async def fetch_historical_term_structure(
    #     self,
    #     date: datetime,
    #     term_struct_id:,
    # ) -> Tuple[datetime, Dict[str, float]]:
    #     pass
