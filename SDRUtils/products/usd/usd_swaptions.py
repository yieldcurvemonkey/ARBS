"""
USD Swaptions product module.

Provides classification and detection for USD swaption trades
reported to the DTCC SDR.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import QuantLib as ql

from SDRUtils.config import PRODUCT_TYPES
from SDRUtils.core.classification import TradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.products._swaps.filters import sofr_swaption_trades
from SDRUtils.products.usd.base import USDProductBase


class USD_Swaptions(USDProductBase):
    """
    USD Swaption product handler.

    Matches USD swaption trades based on SDR taxonomy fields
    and UPI attributes.
    """

    name = "USD-SWAPTIONS"
    product_type = PRODUCT_TYPES.SWAPTION_CALL
    package_type = "SWAPTION"

    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """
        Identify USD Swaption rows.

        Args:
            df: SDR trades DataFrame.
            **kwargs: Optional filters like action_types.

        Returns:
            Filtered DataFrame containing USD swaption trades.
        """
        if df.empty:
            return df.copy()

        mask = pd.Series(True, index=df.index)

        currency_mask = None
        for col in ("Notional currency-Leg 1", "Notional currency-Leg 2", "Notional currency"):
            if col in df.columns:
                col_mask = df[col].astype(str).str.upper().eq(self.currency)
                currency_mask = col_mask if currency_mask is None else (currency_mask | col_mask)
        if currency_mask is not None:
            mask &= currency_mask

        if "Asset class" in df.columns:
            asset_mask = df["Asset class"].astype(str).str.upper().isin({"RATES", "INTEREST RATE", "INTERESTRATE"})
            mask &= asset_mask

        option_mask = pd.Series(False, index=df.index)
        if "Product name" in df.columns:
            option_mask |= df["Product name"].astype(str).str.contains("Swaption", case=False, na=False)
        if "Taxonomy" in df.columns:
            option_mask |= df["Taxonomy"].astype(str).str.contains("Swaption|Option", case=False, na=False)
        if "UPI FISN" in df.columns:
            fisn = df["UPI FISN"].astype(str)
            option_mask |= (
                fisn.str.contains("CALL", case=False, na=False)
                | fisn.str.contains("PUT", case=False, na=False)
                | fisn.str.contains("NA/O", case=False, na=False)
                | fisn.str.contains("O P", case=False, na=False)
            )

        if {"UPI FISN", "UPI Underlier Name", "Action type"}.issubset(df.columns):
            action_types = kwargs.get("action_types")
            if action_types is not None:
                sofr_subset = sofr_swaption_trades(df, action_types=action_types)
            else:
                sofr_subset = sofr_swaption_trades(df, action_types=tuple(df["Action type"].dropna().unique()))
            option_mask |= df.index.isin(sofr_subset.index)

        return df[mask & option_mask].copy()

    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> TradeClassification:
        """
        Classify a single USD swaption trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments

        Returns:
            TradeClassification object
        """
        execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
        effective_date = pd.to_datetime(row.get("Effective Date"))
        expiration_date = pd.to_datetime(row.get("Expiration Date"))

        product_type = classify_product_type(row)

        tenor_years = calculate_tenor_years(
            effective_date,
            expiration_date,
            conventions=self.conventions,
        )
        tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

        forward_years = calculate_forward_start_years(
            execution_ts,
            effective_date,
            conventions=self.conventions,
        )

        ql_exec = to_ql_date(execution_ts)
        ql_eff = to_ql_date(effective_date)

        is_forward = False
        if ql_exec and ql_eff:
            t_plus_2 = self.conventions.calendar.advance(ql_exec, 2, ql.Days)
            if ql_eff > t_plus_2:
                is_forward = True

        forward_label = forward_to_label(forward_years, effective_date=effective_date)
        trade_label = build_trade_label(forward_label, tenor_label, is_forward)

        notional = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
        fixed_rate = row.get("Fixed rate-Leg 1", row.get("Fixed rate-Leg 2"))
        strike = row.get("Strike Price")

        return TradeClassification(
            trade_id=trade_id,
            execution_timestamp=execution_ts,
            effective_date=effective_date,
            expiration_date=expiration_date,
            product_type=product_type,
            tenor_years=tenor_years,
            tenor_label=tenor_label,
            is_forward=is_forward,
            forward_start_years=forward_years,
            forward_label=forward_label,
            trade_label=trade_label,
            notional=notional,
            notional_currency=row.get("Notional currency-Leg 1", "USD"),
            fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
            strike=strike if pd.notna(strike) else None,
            estimated_pv01=0.0,
            package_type=self.package_type,
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
        return classifications_to_dataframe(classifications)

    def metadata(self) -> Dict[str, str]:
        return {
            "product": self.name,
            "package_type": self.package_type,
            "currency": self.currency,
        }
