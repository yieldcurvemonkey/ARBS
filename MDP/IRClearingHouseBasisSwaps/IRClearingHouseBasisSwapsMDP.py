from __future__ import annotations
from typing import Any, Dict, Optional
import pandas as pd
from MDP.MarketDataProvider import MarketDataProvider


class ClearingHouseBasisPricer:
    def __init__(self, basis_data: pd.DataFrame, meta_data: Dict[str, Any]):
        self._basis_data = basis_data
        self._meta_data = meta_data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data

    @property
    def basis_data(self) -> pd.DataFrame:
        return self._basis_data


class IRClearingHouseBasisSwapsMDP(MarketDataProvider):
    """
    LCH vs CME clearing house basis from GS Quant IR_SWAP_RATES_V1_STANDARD.

    Request dict:
        tenor: str, ccy: str (default USD), index: str (default SOFR),
        clearing_house_a: str (default LCH), clearing_house_b: str (default CME),
        start: date, end: date
    """

    def __init__(self, coverage_path: str, gs_client_id: str, gs_secret_key: str, **kwargs: Any):
        super().__init__(source="GSQUANT_CH_BASIS", **kwargs)
        self._coverage_path = coverage_path
        self._gs_client_id = gs_client_id
        self._gs_secret_key = gs_secret_key
        self._coverage: Optional[pd.DataFrame] = None

    def _load_coverage(self) -> pd.DataFrame:
        if self._coverage is None:
            self._coverage = pd.read_excel(self._coverage_path)
        return self._coverage

    def get_pricer(self, request: Any) -> ClearingHouseBasisPricer:
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import find_asset_pair, fetch_clearing_house_basis
        coverage = self._load_coverage()
        tenor = request.get("tenor", "5y")
        ccy = request.get("ccy", "USD")
        index = request.get("index", "SOFR")
        ch_a = request.get("clearing_house_a", "LCH")
        ch_b = request.get("clearing_house_b", "CME")
        start = request.get("start")
        end = request.get("end")
        pair = find_asset_pair(coverage, ccy=ccy, index=index, tenor=tenor, clearing_house_a=ch_a, clearing_house_b=ch_b)
        basis_data = fetch_clearing_house_basis(
            asset_id_a=pair["asset_id_a"], asset_id_b=pair["asset_id_b"],
            start=start, end=end,
            gs_client_id=self._gs_client_id, gs_secret_key=self._gs_secret_key,
        )
        return ClearingHouseBasisPricer(
            basis_data=basis_data,
            meta_data={"source": self.source, "tenor": tenor, "ccy": ccy, "index": index, "clearing_house_a": ch_a, "clearing_house_b": ch_b},
        )
