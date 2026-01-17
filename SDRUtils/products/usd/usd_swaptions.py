"""
USD Swaptions product module.

Provides classification and detection for USD swaption trades
reported to the DTCC SDR.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytz
import QuantLib as ql

import Query.IRSwaps.adapter  # noqa: F401
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

from SDRUtils.config import PRODUCT_TYPES, TRADE_ID
from SDRUtils.core.classification import SwaptionTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_from_dates, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages.swaption_packages import (
    SwaptionPackageDetectionConfig,
    detect_and_link_swaption_packages_df,
)
from SDRUtils.packages.utils import merge_package_legs_to_one_row, merge_vega_curve_packages
from SDRUtils.products._swaptions.upi import _build_upi_df, make_swaption_desc_func
from SDRUtils.products.usd.base import USDProductBase


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
        tenor_label = tenor_to_label(tenor_years, expiration_date, True)

        forward_years = calculate_tenor_years(
            effective_date,
            expiration_date,
            conventions=self.conventions,
        )
        forward_label = forward_to_label(forward_years, expiration_date, True)

        notional, is_notional_capped = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
        strike = row.get("Strike Price")

        def _extract_prem(row):
            try:
                opa = float(str(row.get("Option Premium Amount", "").replace(",", "")))
                if opa == 0:
                    opa = float(str(row.get("Package transaction price", "").replace(",", "")))
                return opa
            except:
                return 0

        return SwaptionTradeClassification(
            event_action=f"{row.get("Action type", "")}-{row.get("Event type", "")}",
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
            is_notional_capped=is_notional_capped,
            strike=strike if pd.notna(strike) else None,
            premium=_extract_prem(row),
            exercise_style=(
                "EUROPEAN" if "epn" in str(row.get("UPI FISN", "")).lower() else "BERMUDAN" if "brm" in str(row.get("UPI FISN", "")).lower() else "AMERICAN"
            ),
            package_type=self.package_type,
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
        only_newt: Optional[bool] = False,
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
            # ignore_cache=ignore_cache,
        )

        if raw_sdr_trades_df.empty:
            return raw_sdr_trades_df

        if only_newt:
            raw_sdr_trades_df = raw_sdr_trades_df[(raw_sdr_trades_df["Action type"] == "NEWT") & (raw_sdr_trades_df["Event type"] == "TRAD")]

        curve_source = str(kwargs.get("curve_source", "ERIS_EOD_LIVE-QL_BASIC")).replace("/", "_")
        mdp = IRSwapsMDP(source=curve_source)

        exec_dates = pd.to_datetime(raw_sdr_trades_df["Event timestamp"], errors="coerce").dt.date
        raw_sdr_trades_df = raw_sdr_trades_df.assign(_execution_date=exec_dates)

        cache_flags = f"swaption_pkgs{int(detect_swaption_packages)}_merge{int(merge_package_legs)}"
        cache_base = Path(cache_path) / "classification_cache" / "usd_swaptions" / cache_flags
        cache_base.mkdir(parents=True, exist_ok=True)

        eastern_tz = pytz.timezone("US/Eastern")
        today_eastern = pd.Timestamp.now(tz=eastern_tz).date()

        def _is_historical(exec_date: pd.Timestamp | Any) -> bool:
            return exec_date < today_eastern

        cached_frames = []
        missing_dates = []
        for exec_date, count in raw_sdr_trades_df["_execution_date"].value_counts().items():
            if pd.isna(exec_date):
                continue
            date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
            final_marker = date_dir / "final.marker"

            found_cache = False
            if date_dir.exists() and (ignore_cache is False):
                if _is_historical(exec_date) and not final_marker.exists():
                    found_cache = False
                else:
                    cache_candidates = []
                    for fp in date_dir.glob("*.parquet"):
                        # pick the latest created file
                        cache_candidates.append((fp.stat().st_mtime, fp))

                    if cache_candidates:
                        _, best_cache_fp = max(cache_candidates, key=lambda x: x[0])
                        try:
                            cached_frames.append(pd.read_parquet(best_cache_fp, engine="pyarrow"))
                            found_cache = True
                        except Exception:
                            best_cache_fp.unlink(missing_ok=True)

            if not found_cache:
                missing_dates.append(exec_date)

        def _to_utc(ts: pd.Timestamp) -> pd.Timestamp:
            timestamp = pd.Timestamp(ts)
            if timestamp.tzinfo is None:
                return timestamp.tz_localize(pytz.utc)
            return timestamp.tz_convert(pytz.utc)

        if not missing_dates:
            if cached_frames:
                final_df = pd.concat(cached_frames, ignore_index=True)
                start_ts = _to_utc(start)
                end_ts = _to_utc(end)
                final_df = final_df[(final_df["execution_timestamp"] >= start_ts) & (final_df["execution_timestamp"] <= end_ts)]
                final_df = final_df.sort_values(by="execution_timestamp")
                if merge_package_legs:
                    final_df = merge_package_legs_to_one_row(final_df)
                    final_df = merge_vega_curve_packages(final_df)
                return final_df

            return pd.DataFrame()

        built_frames = []
        for exec_date in missing_dates:
            if exec_date > end.date() or exec_date < start.date():
                continue

            day_df = raw_sdr_trades_df[raw_sdr_trades_df["_execution_date"] == exec_date]
            classifications = self.classify_messages(day_df, **kwargs)
            classifications_df = classifications_to_dataframe(classifications)

            if classifications_df.empty:
                continue

            # Merge with raw SDR columns needed for package detection
            classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
            day_df = day_df.copy()
            day_df[TRADE_ID] = day_df[TRADE_ID].astype("string")

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
            package_cols = [c for c in package_cols if c in day_df.columns]

            package_df = classifications_df.merge(
                day_df[package_cols],
                on=TRADE_ID,
                how="left",
            )

            # Normalize column names (convert CamelCase and spaces to snake_case)
            package_df = package_df.drop(columns=[TRADE_ID], errors="ignore")
            package_df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_") for col in package_df.columns]

            if "strike" in package_df.columns:
                package_df["strike"] = pd.to_numeric(package_df["strike"], errors="coerce")

            # Detect swaption packages
            if detect_swaption_packages:
                package_df = detect_and_link_swaption_packages_df(
                    package_df, config=swaption_package_config, pricer=mdp.get_pricer(dict(curve_name="USD-SOFR-1D", timestamp=exec_date))
                )

            count = len(day_df)
            date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
            date_dir.mkdir(parents=True, exist_ok=True)
            cache_fp = date_dir / f"{count}.parquet"
            tmp_fp = cache_fp.with_suffix(".parquet.tmp")
            table = pa.Table.from_pandas(package_df, preserve_index=False)
            pq.write_table(table, tmp_fp, compression="zstd")
            tmp_fp.replace(cache_fp)
            if _is_historical(exec_date):
                final_marker = date_dir / "final.marker"
                final_marker.touch()

            built_frames.append(package_df)

        all_frames = [*cached_frames, *built_frames]
        if not all_frames:
            return pd.DataFrame()

        final_df = pd.concat(all_frames, ignore_index=True)
        start_ts = _to_utc(start)
        end_ts = _to_utc(end)
        final_df = final_df[(final_df["execution_timestamp"] >= start_ts) & (final_df["execution_timestamp"] <= end_ts)]
        final_df = final_df.sort_values(by="execution_timestamp")
        if merge_package_legs:
            final_df = merge_package_legs_to_one_row(final_df)
            final_df = merge_vega_curve_packages(final_df)
        return final_df

    def metadata(self) -> Dict[str, str]:
        return {
            "product": self.name,
            "package_type": self.package_type,
            "currency": self.currency,
        }
