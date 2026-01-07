"""
USD Swaptions product module.

Provides classification and detection for USD swaption trades
reported to the DTCC SDR.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import QuantLib as ql
from collections.abc import Iterable, Sequence

from SDRUtils.config import PRODUCT_TYPES
from SDRUtils.core.classification import SwaptionTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products._swaptions.upi import make_swaption_desc_func, _build_upi_df


class USD_Swaptions(USDProductBase):
    """
    USD Swaption product handler.

    Matches USD swaption trades based on SDR taxonomy fields
    and UPI attributes.
    """

    name = "USD-SWAPTIONS"
    product_type = PRODUCT_TYPES.SWAPTION
    package_type = "SWAPTION"

    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        swaption_upis = _build_upi_df(kwargs.get("base_dir"))
        mask = df["Unique Product Identifier"].isin(swaption_upis["swaption_Identifier_UPI"])
        swaption_trades_df = df.loc[mask].copy()
        desc_fn = make_swaption_desc_func()
        swaption_trades_df.loc[:, "description"] = swaption_trades_df.apply(desc_fn, axis=1)
        swaption_trades_df = swaption_trades_df[
            (swaption_trades_df["description"].str.contains("USD")) & (swaption_trades_df["Maturity date of the underlier"].notna())
        ]
        return swaption_trades_df

    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> SwaptionTradeClassification:
        execution_ts = pd.to_datetime(row.get("Event timestamp"))
        effective_date = pd.to_datetime(row.get("Effective Date"))
        expiration_date = pd.to_datetime(row.get("Expiration Date"))
        underlying_expiration_date = pd.to_datetime(row.get("Maturity date of the underlier"))

        product_type = classify_product_type(row)

        tenor_years = calculate_tenor_years(
            expiration_date,
            underlying_expiration_date,
            conventions=self.conventions,
        )
        tenor_label = tenor_to_label(tenor_years, expiration_date=underlying_expiration_date)

        forward_years = calculate_forward_start_years(
            effective_date,
            expiration_date,
            conventions=self.conventions,
        )

        forward_label = forward_to_label(forward_years, effective_date=expiration_date)

        notional = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
        if isinstance(notional, Sequence):
            is_capped = notional[1]
            notional = notional[0]
        else:
            is_capped = False

        strike = row.get("Strike Price")

        return SwaptionTradeClassification(
            event_action=f"{row["Action type"]}-{row["Event type"]}",
            trade_id=trade_id,
            execution_timestamp=execution_ts,
            effective_date=effective_date,
            expiration_date=expiration_date,
            underlying_expiration_date=underlying_expiration_date,
            product_type=product_type,
            trade_label=row["description"],
            tenor_years=tenor_years,
            tenor_label=tenor_label,
            forward_label=forward_label,
            forward_start_years=forward_years,
            notional=notional,
            notional_currency=row.get("Notional currency-Leg 1", "USD"),
            strike=strike if pd.notna(strike) else None,
            premium=None,
            exercise_style=(
                "EUROPEAN" if "epn" in str(row.get("UPI FISN", "")).lower() else "BERMUDAN" if "brm" in str(row.get("UPI FISN", "")).lower() else "AMERICAN"
            ),
            estimated_pv01=0.0,
            package_type=self.package_type,
            is_capped=is_capped,
        )

    def build_classification_dataframe(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        cache_path: str,
        ignore_cache: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """
        Build a classification dataframe from SDR messages.

        Uses ProductModule.classify_messages to resolve lifecycle events.
        """
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=self.detect,
            ignore_cache=ignore_cache,
        )

        if raw_sdr_trades_df.empty:
            return raw_sdr_trades_df

        classifications = self.classify_messages(raw_sdr_trades_df, **kwargs)
        return classifications_to_dataframe(classifications).sort_values(by="execution_timestamp")

    def metadata(self) -> Dict[str, str]:
        return {
            "product": self.name,
            "package_type": self.package_type,
            "currency": self.currency,
        }
