import logging
import re
import warnings
from collections import defaultdict
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

import tqdm
import httpx
import copy
import pandas as pd
import ujson as json
import asyncio
import tqdm.asyncio

from bs4 import BeautifulSoup

from MDP.STIRFutures.QuikStrikeSDK.core._BaseQuikStrikeFetcher import _BaseQuikStrikeFetcher
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolQuery import QuikVolQuery

warnings.simplefilter(action="ignore", category=FutureWarning)


class _QuikVolCalculationFetcher(_BaseQuikStrikeFetcher):
    _option_type_key = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$ddlOptionType"
    _option_strike_price_key = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$tbStrike"
    _smile_calc_cache: Dict[Tuple[str, int], str]

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

        self._smile_calc_cache: Dict[Tuple[str, int], str] = {}

        self._pricer_base_url = f"https://cmegroup-tools.quikstrike.net/User/Integrated.aspx?tmpl=Integrated&viewitemid=IntegratedCalculator&insid={self._cme_insid}&qsid={self._cme_qsid}"
        self._pricer_base_headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "connection": "keep-alive",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "dnt": "1",
            "host": "cmegroup-tools.quikstrike.net",
            "origin": "https://cmegroup-tools.quikstrike.net",
            "referer": self._pricer_base_url,
            "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        }
        self._pricer_trigger_headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "dnt": "1",
            "host": "cmegroup-tools.quikstrike.net",
            "origin": "https://cmegroup-tools.quikstrike.net",
            "referer": self._pricer_base_url,
            "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "x-microsoftajax": "Delta=true",
            "x-requested-with": "XMLHttpRequest",
        }

    async def single_contract_pricer(
        self,
        product: QuikVolProductID,
        option_contract: str,
        option_type: Optional[Literal["Call", "Put", "Straddle"]] = "Straddle",
        option_strike_price: Optional[float] = None,
        option_premium: Optional[float] = None,
        option_vol: Optional[float] = None,
    ) -> str:
        resp = await self._build_calculator(product=product, option_contract=option_contract, copies=1)
        payload = self._build_pricer_payload(html=resp.text, option_type=option_type, strikes=[option_strike_price] if option_strike_price else None)

        if option_premium:
            payload = self._with_event(
                payload, "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$btnPriceToVol"
            )
            payload["ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$tbPremium"] = (
                option_premium
            )
        elif option_vol:
            payload = self._with_event(
                payload, "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$btnVolToPrice"
            )
            payload["ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$tbVol"] = option_vol

        resp = await self.request_with_retry("POST", self._pricer_base_url, headers=self._pricer_trigger_headers, data=payload)

        with open("temp1.html", "w") as f:
            f.write(resp.text)

        return self.pricer_parser(resp.text, use_prev_calc=option_premium != None or option_vol != None)

    async def get_latest_calculated_smile(
        self,
        product: QuikVolProductID,
        option_contract: str,
        max_batch_size: int = 5,
        filter_zero_deltas: Optional[bool] = True,
    ) -> pd.DataFrame:
        cache_key = (option_contract, max_batch_size)
        if cache_key in self._smile_calc_cache:
            html0 = self._smile_calc_cache[cache_key]
        else:
            resp0 = await self._build_calculator(
                product=product,
                option_contract=option_contract,
                copies=max_batch_size,
            )
            html0 = resp0.text
            self._smile_calc_cache[cache_key] = html0

        df0 = self.pricer_parser(html0)

        atm_idx = df0["ATM Strike Offset"].abs().idxmin()
        atm = df0.at[atm_idx, "Strike"]

        strikes = sorted(self._get_all_listed_strikes(html0))
        sides = [
            ([s for s in strikes if s < atm], "Put"),
            ([s for s in strikes if s >= atm], "Call"),
        ]

        async def _price_batch(strikes_batch: List[float], opt_type: str) -> pd.DataFrame:
            payload = self._build_pricer_payload(
                html=html0,
                option_type=opt_type,
                strikes=strikes_batch,
            )
            resp = await self.request_with_retry(
                "POST",
                self._pricer_base_url,
                headers=self._pricer_trigger_headers,
                data=payload,
            )
            df = self.pricer_parser(resp.text)
            return df.head(len(strikes_batch))

        tasks: List[asyncio.Task] = []
        for side_strikes, opt_type in sides:
            for i in range(0, len(side_strikes), max_batch_size):
                batch = side_strikes[i : i + max_batch_size]
                if batch:
                    tasks.append(_price_batch(batch, opt_type))

        if not tasks:
            return pd.DataFrame()

        dfs = await tqdm.asyncio.tqdm.gather(*tasks, desc=f"FETCHING {option_contract} SMILE...")
        full: pd.DataFrame = pd.concat(dfs, ignore_index=True)
        smile_df = full.drop_duplicates(subset=["Strike"]).sort_values("Strike").reset_index(drop=True)
        if filter_zero_deltas:
            smile_df = smile_df[smile_df["Delta"].abs() > 0.01]
        
        return smile_df

    async def _build_calculator(
        self,
        product: QuikVolProductID,
        option_contract: str,
        copies: Optional[int] = 10,
    ):
        # initial GET & hidden inputs
        resp = await self.request_with_retry("GET", self._pricer_base_url, headers=self._pricer_base_headers)
        payload = self._extract_hidden_inputs(resp.text)

        # Asset Class click
        payload = self._with_event(payload, product.value.calculator_asset_class_event_target)

        resp = await self.request_with_retry("POST", self._pricer_base_url, headers=self._pricer_base_headers, data=payload)
        payload = self._extract_hidden_inputs(resp.text)

        # Underlying Contract click
        payload = self._with_event(payload, product.value.calculator_underlying_contract_event_target)
        resp = await self.request_with_retry("POST", self._pricer_base_url, headers=self._pricer_base_headers, data=payload)

        # Option Symbol click
        soup = BeautifulSoup(resp.text, "html.parser")
        anchor = soup.find("a", attrs={"title": re.compile(rf"Option Symbol:\s*{re.escape(option_contract)}")})
        if not anchor:
            raise RuntimeError(f"Could not find link for option symbol {option_contract}")

        event_target = re.search(r"__doPostBack\('([^']+)'", anchor["href"]).group(1)
        payload = self._extract_hidden_inputs(resp.text)
        payload = self._with_event(payload, event_target)
        resp = await self.request_with_retry("POST", self._pricer_base_url, headers=self._pricer_base_headers, data=payload)
        if copies == 1:
            return resp

        resp = await self._copy_calculator(post=resp, copies=copies, option_contract=option_contract)
        return resp

    async def _copy_calculator(self, post: httpx.Response, copies: int, option_contract: Optional[str] = None):
        for _ in tqdm.tqdm(range(0, copies), desc=f"BUILDING {option_contract} PRICERS..." if option_contract else "BUILDING PRICERS..."):
            payload = {}
            parts = post.text.split("|")

            def grab(name):
                if name in parts:
                    return parts[parts.index(name) + 1]
                return ""

            payload["smPublic"] = (
                "upMain|ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$ucItemTools$lbCopy"
            )
            payload["__EVENTTARGET"] = (
                "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl0$ucCalcItem$ucItemTools$lbCopy"
            )
            payload["__EVENTARGUMENT"] = grab("__EVENTARGUMENT")
            payload["__VIEWSTATE"] = grab("__VIEWSTATE")
            payload["__VIEWSTATEGENERATOR"] = grab("__VIEWSTATEGENERATOR")
            payload["__ASYNCPOST"] = True

            post = await self.request_with_retry("POST", self._pricer_base_url, headers=self._pricer_base_headers, data=payload)

        return post

    def _build_pricer_payload(self, html: str, option_type: str, strikes: Optional[List[float]] = None):
        soup = BeautifulSoup(html, "html.parser")

        payload = {
            "smPublic": "",
            "global_attributes": "",
            "global_viewAttributes": "",
            "ucFix$calendarFix": "",
        }

        zeroth_num, zeroth_str, zeroth_json = self.build_pricer_payload_keys(i=0)

        max_i = len(strikes) if strikes else 1
        for i in range(max_i):
            num_keys, str_keys, json_keys = self.build_pricer_payload_keys(i=i)
            valid = set(num_keys + str_keys + json_keys)

            for tag in soup.find_all(["input", "select", "textarea"]):
                name = tag.get("name")
                if not name or name not in valid:
                    continue

                if tag.name == "input":
                    val = tag.get("value", "")
                elif tag.name == "select":
                    sel = tag.find("option", selected=True)
                    val = sel["value"] if sel and sel.has_attr("value") else (tag.find("option") or {}).get("value", "")
                else:
                    val = tag.text or ""

                if name in num_keys:
                    payload[name] = float(val)
                elif name in str_keys:
                    payload[name] = val
                else:
                    payload[name] = json.loads(val)

            if i > 0:
                for k in zeroth_num:
                    newk = k.replace("$ctrl0$", f"$ctrl{i}$")
                    payload[newk] = payload[k]
                for k in zeroth_str:
                    newk = k.replace("$ctrl0$", f"$ctrl{i}$")
                    payload[newk] = payload[k]

                from0 = zeroth_json[0]
                to1 = json_keys[0]
                payload[to1] = copy.deepcopy(payload[from0])
                payload[to1]["RawValueClientId"] = (
                    f"ucViewControl_IntegratedCalculator_ucSimpleCalc_"
                    f"ucProductNavigator_ucCalculator_ucCalcControl_"
                    f"lvItems_ctrl{i}_ucCalcItem_txtFuturePriceraw"
                )

            payload[
                f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$" f"ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$ddlOptionType"
            ] = option_type
            if strikes:
                payload[f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$" f"ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$tbStrike"] = (
                    strikes[i]
                )

            payload["smPublic"] = "upMain|ucViewControl_IntegratedCalculator$ucSimpleCalc$…$ctrl1$ucCalcItem$ddlOptionType"

        parts = soup.text.split("|")

        def grab(n):
            return parts[parts.index(n) + 1] if n in parts else ""

        payload.update(
            {
                "__EVENTTARGET": "ucViewControl_IntegratedCalculator$ucSimpleCalc$…$ctrl1$ucCalcItem$ddlOptionType",
                "__EVENTARGUMENT": grab("__EVENTARGUMENT"),
                "__VIEWSTATE": grab("__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": grab("__VIEWSTATEGENERATOR"),
                "__ASYNCPOST": "true",
            }
        )
        return payload

    def build_pricer_payload_keys(self, i: int):
        to_numeric_pricer_keys = [
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$tbStrike",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$txtFuturePrice",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$txtFuturePriceraw",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$dpDTE$txtDays",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$tbRate",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$tbVol",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$tbPremium",
        ]
        to_string_pricer_keys = [
            f"ucViewControl_IntegratedCalculator$ucToolbar$ucExpirationPicker$ucNewTrigger$hfPopupTrigger",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$ddlOptionType",
            f"ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucCalculator$ucCalcControl$lvItems$ctrl{i}$ucCalcItem$dpDTE$txtDate",
        ]
        to_json_pricer_keys = [
            f"ucViewControl_IntegratedCalculator_ucSimpleCalc_ucProductNavigator_ucCalculator_ucCalcControl_lvItems_ctrl{i}_ucCalcItem_txtFuturePrice_hdn",
        ]
        return to_numeric_pricer_keys, to_string_pricer_keys, to_json_pricer_keys

    def _get_all_listed_strikes(self, pricer_html: str):
        pricer_soup = BeautifulSoup(pricer_html, "html.parser")
        return sorted(
            float(a.text)
            for a in pricer_soup.select(
                "#ucViewControl_IntegratedCalculator_ucSimpleCalc_ucProductNavigator_" "ucCalculator_ucCalcControl_lvItems_ctrl0_ucCalcItem_ucStrikes_pnlContainer a"
            )
        )

    def pricer_parser(self, html: str, use_prev_calc: Optional[bool] = False) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")

        if use_prev_calc:
            all_tables = soup.select("table.grid-thm.grid-thm-v2")
            if len(all_tables) % 2:
                raise RuntimeError(f"expected even number of grid-thm tables, got {len(all_tables)}")

            header_tbl = all_tables[0]
            metrics_tbl = all_tables[1]
            span = header_tbl.find("span", class_="bold")
            symbol = span.get_text(strip=True)

            settle_td = metrics_tbl.find("td", {"rowspan": "2"})
            rows = settle_td.select("tr")
            price_cell = rows[0].find_all("td")[1].get_text(strip=True).replace(",", "")
            settle_val1 = float(price_cell)
            vol_cell = rows[1].find_all("td")[1].get_text(strip=True).replace(",", "")
            settle_val2 = float(vol_cell)

            header_tr = soup.find("tr", id=lambda s: s and s.endswith("_trHeader"))
            if not header_tr:
                raise RuntimeError("Previous Calculations header not found")

            table = header_tr.find_parent("table")
            columns = [th.get_text(strip=True) for th in header_tr.find_all("th") if th.get_text(strip=True)]
            rows = []
            for tr in table.select("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < len(columns):
                    continue
                cells = [td.get_text(strip=True).replace(",", "") for td in tds[: len(columns) + 2]]
                rows.append(cells)

            prev_calc_formatted_cols = [
                "None0",
                "inputs_strike",
                "inputs_option_type",
                "inputs_future_price",
                "inputs_dte_days",
                "Rate (%)",
                "Model",
                "Price",
                "None1",
                "Vol",
                "ABPV",
                "DBPV",
                "Delta",
                "Gamma",
                "Vega",
                "Theta",
            ]
            df = pd.DataFrame(rows, columns=prev_calc_formatted_cols)
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="ignore")

            df["Contract"] = symbol
            df["Settle Price"] = settle_val1
            df["Settle Vol"] = settle_val2

        else:
            all_tables = soup.select("table.grid-thm.grid-thm-v2")
            if len(all_tables) % 2:
                raise RuntimeError(f"expected even number of grid-thm tables, got {len(all_tables)}")

            results: List[Dict[str, Any]] = []
            for i in range(0, len(all_tables), 2):
                header_tbl = all_tables[i]
                metrics_tbl = all_tables[i + 1]

                span = header_tbl.find("span", class_="bold")
                symbol = span.get_text(strip=True)

                expiry_txt = span.parent.get_text(separator="\n", strip=True).split("\n", 1)[1]
                expiry = datetime.strptime(expiry_txt, "%m/%d/%Y").date()

                def get_input_value(suffix: str) -> str:
                    inp = header_tbl.find("input", id=lambda i: i and i.endswith(suffix))
                    if not inp:
                        raise RuntimeError(f"missing input …{suffix!r}")
                    return inp["value"]

                inputs = {
                    "strike": float(get_input_value("tbStrike")),
                    "option_type": header_tbl.find("select", id=lambda i: i and i.endswith("ddlOptionType")).find("option", selected=True)["value"],
                    "future_price": float(get_input_value("txtFuturePrice")),
                    "dte_days": float(get_input_value("dpDTE_txtDays")),
                    "rate": float(get_input_value("tbRate")),
                }

                ths = metrics_tbl.select("tr.compact th")
                labels = [th.get_text(strip=True) for th in ths if th.get_text(strip=True)]
                numeric_headers = labels[1:]  # drop the "Settle" column

                settle_td = metrics_tbl.find("td", {"rowspan": "2"})
                rows = settle_td.select("tr")
                price_cell = rows[0].find_all("td")[1].get_text(strip=True).replace(",", "")
                settle_val1 = float(price_cell)
                vol_cell = rows[1].find_all("td")[1].get_text(strip=True).replace(",", "")
                settle_val2 = float(vol_cell)

                data_rows = metrics_tbl.select("tr")[1:3]
                metrics: List[Dict[str, float]] = []
                for tr in data_rows:
                    vals: List[float] = []
                    for td in tr.select("td.number"):
                        inp = td.find("input")
                        raw = inp["value"] if inp else td.get_text(strip=True)
                        clean = str(raw).replace(",", "")
                        vals.append(float(clean))
                    if not vals:
                        continue
                    row = {"Settle Price": settle_val1, "Settle Vol": settle_val2}
                    row.update(zip(numeric_headers, vals))
                    metrics.append(row)

                results.append({"symbol": symbol, "expiry": expiry, "inputs": inputs, "metrics": metrics})

            df = pd.json_normalize(
                results,
                record_path="metrics",
                meta=[
                    "symbol",
                    "expiry",
                    ["inputs", "strike"],
                    ["inputs", "option_type"],
                    ["inputs", "future_price"],
                    ["inputs", "dte_days"],
                    ["inputs", "rate"],
                ],
                sep="_",
            )
            if "Vol (%)" in df.columns:
                df = df.rename(columns={"Vol (%)": "Vol"})

        df["ATM Strike Offset"] = round(df["inputs_strike"] - df["inputs_future_price"])

        ordered_pricer_cols = {
            "symbol": "Contract",
            "inputs_dte_days": "DTE",
            "inputs_option_type": "Type",
            "inputs_strike": "Strike",
            "ATM Strike Offset": "ATM Strike Offset",
            "Settle Price": "Prev Settle Price",
            "Settle Vol": "Prev Settle Vol",
            "Price": "Price",
            "Vol": "Vol",
            "ABPV": "ABPV",
            "DBPV": "DBPV",
            "Delta": "Delta",
            "Gammaa": "Gamma",
            "Vega": "Vega",
            "Theta": "Theta",
        }
        df = df.rename(columns=ordered_pricer_cols)

        return df[ordered_pricer_cols.values()]
