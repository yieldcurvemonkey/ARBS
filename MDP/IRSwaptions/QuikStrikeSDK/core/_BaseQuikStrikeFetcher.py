import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional, Union
from zoneinfo import ZoneInfo

import httpx
import ujson as json
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID
from MDP.STIRFutures.QuikStrikeSDK.core.utils.misc import HTTPXProxies


class _BaseQuikStrikeFetcher:
    _cme_insid: str
    _cme_qsid: str
    _timeout: str
    _proxies: HTTPXProxies
    _log_level: int
    _max_connections: int
    _max_keepalive: int
    _max_retries: int
    _backoff_factor: float

    _base_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "connection": "keep-alive",
        "dnt": "1",
        "host": "cmegroup-tools.quikstrike.net",
        "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    }

    def __init__(
        self,
        cme_insid: str,
        cme_qsid: int,
        timeout: Optional[Union[float, httpx.Timeout]] = 10.0,
        proxies: Optional[Dict[str, str]] = None,
        log_level: Optional[Union[int, str]] = logging.WARN,
        max_connections: Optional[int] = 10,
        max_keepalive: Optional[int] = 5,
        http2: Optional[bool] = True,
    ) -> None:
        self._cme_insid = cme_insid
        self._cme_qsid = cme_qsid

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            mounts=proxies or {},
            limits=limits,
            http2=http2,
        )

        self._logger = logging.getLogger(self.__class__.__name__)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
        self._logger.setLevel(log_level)
        self._logger.propagate = False

    def _activate_quikstrike_page(self) -> None:
        chrome_opts = Options()
        chrome_opts.add_argument("--headless")
        chrome_opts.add_argument("--disable-gpu")

        driver = webdriver.Chrome(options=chrome_opts)
        wait = WebDriverWait(driver, 15)

        try:
            history_url = (
                "https://cmegroup-tools.quikstrike.net//User/QuikStrikeView.aspx"
                f"?pid=362&pf=3&viewitemid=AboutCMEHistory"
                f"&insid={self._cme_insid}&qsid={self._cme_qsid}"
            )
            driver.get(history_url)
            active_btn = wait.until(EC.element_to_be_clickable((By.ID, "MainContent_ucViewControl_AboutCMEHistory_View5_btnView")))
            active_btn.click()
            info_btn = wait.until(EC.element_to_be_clickable((By.ID, "ucPopupStatus_hlProductStatus")))
            info_btn.click()
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#popupStatus_ContentDiv")))
        finally:
            driver.quit()

    async def fetch(
        self,
        url: str,
        method: str,
        **kwargs: Any,
    ) -> httpx.Response:
        self._logger.debug("Request: %s %s, params=%s, data=%s", method, url, kwargs.get("params"), kwargs.get("data"))
        response = await self._client.request(method, url, **kwargs)
        self._logger.debug("Response [%s]: %s", response.status_code, response.text)
        response.raise_for_status()
        return response

    async def request_with_retry(
        self,
        method: str,
        url: str,
        retries: Optional[int] = 3,
        backoff_factor: Optional[float] = 1.0,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(1, retries + 1):
            try:
                self._logger.debug("Request attempt %s: %s %s", attempt, method, url)
                response = await self._client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if attempt == retries:
                    self._logger.error("Final HTTP error for %s %s: %s", method, url, e)
                    raise
                wait = backoff_factor * (2 ** (attempt - 1))
                self._logger.warning("HTTP error, retrying in %ss (attempt %s/%s): %s", wait, attempt, retries, e)
                await asyncio.sleep(wait)
            except Exception as e:
                if attempt == retries:
                    self._logger.error("Final error for %s %s: %s", method, url, e)
                    raise
                wait = backoff_factor * (2 ** (attempt - 1))
                self._logger.warning("Error, retrying in %ss (attempt %s/%s): %s", wait, attempt, retries, e)
                await asyncio.sleep(wait)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_product_status(
        self, product_id: QuikVolProductID, add_contract_specs: Optional[bool] = False, add_scaling_factors: Optional[bool] = False
    ) -> Dict[str, any]:
        atm_ts_url = f"https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx?pid={product_id.value.underlying_pid}&pf=3&viewitemid=IntegratedVolTermTool&insid={self._cme_insid}&qsid={self._cme_qsid}"
        await self.request_with_retry(
            "GET",
            atm_ts_url,
            headers=self._base_headers,
            retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

        product_status_url = f"https://cmegroup-tools.quikstrike.net//User/ProductStatus.aspx?insid={self._cme_insid}&qsid={self._cme_qsid}"
        resp = await self.request_with_retry(
            "GET",
            product_status_url,
            headers={
                "accept": "text/html, */*; q=0.01",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-US,en;q=0.9",
                "connection": "keep-alive",
                "dnt": "1",
                "host": "cmegroup-tools.quikstrike.net",
                "referer": atm_ts_url,
                "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "x-requested-with": "XMLHttpRequest",
            },
            retries=self._max_retries,
            backoff_factor=self._backoff_factor,
        )

        soup = BeautifulSoup(resp.text, "html.parser")
        content = soup.select_one("div#productstatus-content")
        if content is None:
            raise ValueError("Product status content not found")

        result: Dict[str, Any] = {}
        # Product name
        title_el = content.select_one("table.grid-thm .group th")
        result["product"] = title_el.get_text(strip=True) if title_el else None

        # Helper to locate a section by header text
        def find_table(regex):
            return next(
                (tbl for tbl in content.find_all("table", class_="grid-thm") if tbl.find(lambda t: t.name == "th" and re.search(regex, t.get_text(strip=True)))),
                None,
            )

        # Parse Product Status section
        status_tbl = find_table(r"^Product Status$")
        if status_tbl:
            compact_rows = status_tbl.find_all("tr", class_="compact")
            # select the first row that contains <td> elements (data row)
            data_rows = [r for r in compact_rows if r.find_all("td")]
            if data_rows:
                data_row = data_rows[0]
                vals = [td.get_text(strip=True) for td in data_row.find_all("td")]
                keys = [
                    "volatility_last_update",
                    "settles_last_update",
                    "settles_status",
                    "open_interest_date",
                    "open_interest_status",
                    "history_latest_date",
                ]
                for k, v in zip(keys, vals):
                    result[k] = v

        specs_tbl = find_table(r"^Contract Specs$")
        if add_contract_specs and specs_tbl:
            # skip header rows, take first data row
            data_row = specs_tbl.find_all("tr", class_="compact")[-1]
            vals = [td.get_text(strip=True) for td in data_row.select("td")]
            spec_keys = [
                "pricing_model",
                "tick_amount_option",
                "tick_value_ccy",
                "premium_per_point",
                "premium_multiplier",
                "tick_amount_future",
                "tick_value_future",
            ]
            for k, v in zip(spec_keys, vals):
                result[k] = v

        # Parse Scale Factors
        scale_tbl = find_table(r"^Scale Factors$")
        if add_scaling_factors and scale_tbl:
            row = scale_tbl.select_one("tr.compact:nth-of-type(2)")
            vals = [td.get_text(strip=True) for td in row.select("td")] if row else []
            factor_keys = ["premium", "volatility", "delta", "gamma", "vega", "theta"]
            result["scale_factors"] = {k: v for k, v in zip(factor_keys, vals)}

        datetime_fields = {
            "volatility_last_update": "%m/%d/%Y %I:%M %p",
            "settles_last_update": "%m/%d/%Y %I:%M %p",
            "open_interest_date": "%m/%d/%Y",
            "history_latest_date": "%m/%d/%Y",
        }
        for field, fmt in datetime_fields.items():
            raw = result.get(field)
            if raw:
                try:
                    parsed = datetime.strptime(raw, fmt)
                    result[field] = parsed.replace(tzinfo=ZoneInfo("US/Central"))
                except ValueError:
                    self._logger.warning(f"Couldn't parse {field!r}: {raw!r}")

        return result

    def _extract_hidden_inputs(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        data: Dict[str, Any] = {}
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name")
            if not name:
                continue
            data[name] = inp.get("value", "")

        data["__ASYNCPOST"] = True
        parts = html.split("|")
        for key in ("__VIEWSTATE", "__VIEWSTATEGENERATOR"):
            if key in parts:
                idx = parts.index(key)
                if idx + 1 < len(parts):
                    data[key] = parts[idx + 1]

        return data

    def _with_event(self, payload: Dict[str, Any], event_target: str) -> Dict[str, Any]:
        payload["__EVENTTARGET"] = event_target
        payload["__EVENTARGUMENT"] = ""
        payload["smPublic"] = f"upMain|{event_target}"
        return payload

    async def __aenter__(self) -> "_BaseQuikStrikeFetcher":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_value: Optional[BaseException],
        traceback: Optional[Any],
    ) -> None:
        await self.aclose()
