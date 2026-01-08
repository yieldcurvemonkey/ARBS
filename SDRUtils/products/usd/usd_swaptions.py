"""
USD Swaptions product module.

Provides classification and detection for USD swaption trades
reported to the DTCC SDR.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import pandas as pd
import QuantLib as ql
from collections.abc import Iterable, Sequence

from SDRUtils.config import PRODUCT_TYPES, TRADE_ID
from SDRUtils.core.classification import SwaptionTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.packages import detect_and_link_swaption_packages_df, SwaptionPackageDetectionConfig, merge_package_legs_to_one_row
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
            event_action=f"{row['Action type']}-{row['Event type']}",
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
            premium=float(str(row.get("Option Premium Amount", "").replace(",", ""))),
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
        detect_swaption_packages: bool = True,
        swaption_package_config: Optional[SwaptionPackageDetectionConfig] = None,
        merge_package_legs: bool = True,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """
        Build a classification dataframe from SDR messages.

        Uses ProductModule.classify_messages to resolve lifecycle events.

        Args:
            start: Start timestamp for SDR data
            end: End timestamp for SDR data
            cache_path: Path for caching SDR data
            ignore_cache: Whether to ignore cached data
            detect_swaption_packages: Whether to detect swaption packages
            swaption_package_config: Configuration for swaption package detection
            merge_package_legs: Whether to merge package legs into single rows
            **kwargs: Additional arguments

        Returns:
            DataFrame with classified swaption trades and package annotations
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
        classifications_df = classifications_to_dataframe(classifications)

        if classifications_df.empty:
            return classifications_df

        # Merge with raw SDR columns needed for package detection
        classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
        raw_sdr_trades_df = raw_sdr_trades_df.copy()
        raw_sdr_trades_df[TRADE_ID] = raw_sdr_trades_df[TRADE_ID].astype("string")

        # Columns needed for package detection
        package_cols = [
            TRADE_ID,
            "UPI Underlier Name",
            "Unique Product Identifier",
            "Platform identifier",
            "Cleared",
            "Package indicator",
            "Package transaction price",
            "Option Premium Amount",
        ]
        # Only include columns that exist
        package_cols = [c for c in package_cols if c in raw_sdr_trades_df.columns]

        package_df = classifications_df.merge(
            raw_sdr_trades_df[package_cols],
            on=TRADE_ID,
            how="left",
        )

        # Normalize column names (convert CamelCase and spaces to snake_case)
        package_df = package_df.drop(columns=[TRADE_ID], errors="ignore")
        package_df.columns = [
            re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_")
            for col in package_df.columns
        ]

        # Detect swaption packages
        if detect_swaption_packages:
            package_df = detect_and_link_swaption_packages_df(
                package_df,
                config=swaption_package_config,
            )

        # Optionally merge package legs into single rows
        if merge_package_legs:
            package_df = merge_package_legs_to_one_row(package_df)

        return package_df.sort_values(by="execution_timestamp")

    def metadata(self) -> Dict[str, str]:
        return {
            "product": self.name,
            "package_type": self.package_type,
            "currency": self.currency,
        }
