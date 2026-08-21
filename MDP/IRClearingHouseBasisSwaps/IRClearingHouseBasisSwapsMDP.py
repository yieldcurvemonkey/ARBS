from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pandas as pd

from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import (
    CCPBasisCache,
    basis_panel,
    default_coverage_path,
)
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
    """LCH vs CME clearing-house basis from GS Quant ``IR_SWAP_RATES_V1_STANDARD``.

    Request dict::

        tenor: str, ccy: str (default USD), index: str (default SOFR),
        clearing_house_a: str (default LCH), clearing_house_b: str (default CME),
        start: date, end: date, allow_network: bool (default False)

    ``basis_data`` columns are ``rate_a`` and ``rate_b`` (decimal, as served) and
    ``basis_bps`` = ``(rate_a - rate_b) * 1e4``, i.e. **clearing_house_a minus
    clearing_house_b** -- LCH minus CME on the defaults.  Measured reference:
    USD SOFR 10y on 2026-08-10 is **-2.00 bp** (LCH 0.04288489, CME 0.04308489).

    Reads come from the disk cache (:class:`CCPBasisCache`).  A cold window
    raises rather than refetching, unless ``allow_network=True`` is passed --
    every call used to hit the network, which made a backtest unrunnable.
    """

    def __init__(
        self,
        coverage_path: Optional[Any] = None,
        gs_client_id: Optional[str] = None,
        gs_secret_key: Optional[str] = None,
        cache: Optional[CCPBasisCache] = None,
        **kwargs: Any,
    ):
        super().__init__(source="GSQUANT_CH_BASIS", **kwargs)
        # Resolve from this module's own location. The previous default was an
        # absolute path into a different checkout, so a worktree silently read
        # another tree's catalogue.
        self._coverage_path = Path(coverage_path) if coverage_path is not None else default_coverage_path()
        self._gs_client_id = gs_client_id
        self._gs_secret_key = gs_secret_key
        self._cache = cache or CCPBasisCache(
            coverage_path=self._coverage_path,
            gs_client_id=gs_client_id,
            gs_secret_key=gs_secret_key,
        )

    @property
    def coverage_path(self) -> Path:
        return self._coverage_path

    @property
    def cache(self) -> CCPBasisCache:
        return self._cache

    def _load_coverage(self) -> pd.DataFrame:
        return self._cache.coverage()

    def get_pricer(self, request: Any) -> ClearingHouseBasisPricer:
        tenor = request["tenor"]
        ccy = request.get("ccy", "USD")
        index = request.get("index", "SOFR")
        ch_a = request.get("clearing_house_a", "LCH")
        ch_b = request.get("clearing_house_b", "CME")
        allow_network = bool(request.get("allow_network", False))

        start = request.get("start", request.get("start_date"))
        end = request.get("end", request.get("end_date"))
        if start is None or end is None:
            raise ValueError("Request must include start/end or start_date/end_date.")

        panel = basis_panel(
            start,
            end,
            tenors=[tenor],
            ccy=ccy,
            index=index,
            long_ch=ch_a,
            short_ch=ch_b,
            cache=self._cache,
            allow_network=allow_network,
        )
        rate_a = self._cache.read_leg(ccy, index, tenor, ch_a, start, end)
        rate_b = self._cache.read_leg(ccy, index, tenor, ch_b, start, end)

        basis_data = pd.DataFrame(
            {
                "rate_a": rate_a.reindex(panel.index),
                "rate_b": rate_b.reindex(panel.index),
                "basis_bps": panel[tenor],
            }
        )
        basis_data.index.name = "date"
        return ClearingHouseBasisPricer(
            basis_data=basis_data,
            meta_data={
                "source": self.source,
                "tenor": tenor,
                "ccy": ccy,
                "index": index,
                "clearing_house_a": ch_a,
                "clearing_house_b": ch_b,
                "sign_convention": f"{ch_a} minus {ch_b}",
                "units": "bp",
                "rate_units": "decimal",
            },
        )

    def basis_panel(
        self,
        start: Any,
        end: Any,
        tenors: Sequence[str],
        ccy: str = "USD",
        index: str = "SOFR",
        long_ch: str = "LCH",
        short_ch: str = "CME",
        allow_network: bool = False,
    ) -> pd.DataFrame:
        """Date-indexed, one column per tenor, in bp, ``long_ch`` minus ``short_ch``."""
        return basis_panel(
            start,
            end,
            tenors=tenors,
            ccy=ccy,
            index=index,
            long_ch=long_ch,
            short_ch=short_ch,
            cache=self._cache,
            allow_network=allow_network,
        )
