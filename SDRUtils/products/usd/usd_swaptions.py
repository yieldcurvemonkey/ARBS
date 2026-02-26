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
from SDRUtils.products._swaps.filters import new_sofr_swap_trades
from SDRUtils.products.usd.base import USDProductBase


def _is_blank_series(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype("string").str.strip().eq("")


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def _backfill_swaption_fields(package_df: pd.DataFrame) -> pd.DataFrame:
    out = package_df.copy()

    if "action_type" in out.columns and "event_type" in out.columns:
        action_text = out["action_type"].fillna("").astype("string").str.strip()
        event_text = out["event_type"].fillna("").astype("string").str.strip()
        event_action_fallback = (action_text + "-" + event_text).str.strip("-")
        event_action_fallback = event_action_fallback.mask(event_action_fallback.eq(""), "NEWT-TRAD")
        if "event_action" not in out.columns:
            out["event_action"] = event_action_fallback
        else:
            missing_event_action = _is_blank_series(out["event_action"])
            out.loc[missing_event_action, "event_action"] = event_action_fallback.loc[missing_event_action]

    if "description" in out.columns:
        if "trade_label" not in out.columns:
            out["trade_label"] = out["description"]
        else:
            missing_trade_label = _is_blank_series(out["trade_label"])
            out.loc[missing_trade_label, "trade_label"] = out.loc[missing_trade_label, "description"]

    if "upi_fisn" in out.columns:
        fisn_text = out["upi_fisn"].fillna("").astype("string").str.lower()

        if "exercise_style" not in out.columns:
            out["exercise_style"] = None
        missing_exercise_style = _is_blank_series(out["exercise_style"])
        exercise_fallback = pd.Series("AMERICAN", index=out.index, dtype="string")
        exercise_fallback = exercise_fallback.mask(fisn_text.str.contains("epn", na=False), "EUROPEAN")
        exercise_fallback = exercise_fallback.mask(fisn_text.str.contains("brm", na=False), "BERMUDAN")
        out.loc[missing_exercise_style, "exercise_style"] = exercise_fallback.loc[missing_exercise_style]

    if "product_type" in out.columns:
        missing_product_type = _is_blank_series(out["product_type"])
        if missing_product_type.any():
            needed_cols = [c for c in ["upi_fisn", "upi_underlier_name", "fixed_rate_leg_1"] if c in out.columns]

            def _infer_product_type(row: pd.Series) -> str:
                scratch_row = pd.Series(
                    {
                        "UPI FISN": row.get("upi_fisn", ""),
                        "UPI Underlier Name": row.get("upi_underlier_name", ""),
                        "Fixed rate-Leg 1": row.get("fixed_rate_leg_1", ""),
                    }
                )
                return classify_product_type(scratch_row)

            if needed_cols:
                inferred = out.loc[missing_product_type, needed_cols].apply(_infer_product_type, axis=1)
                out.loc[missing_product_type, "product_type"] = inferred

    if "tenor_label" in out.columns and "tenor_years" in out.columns:
        missing_tenor_label = _is_blank_series(out["tenor_label"])
        if missing_tenor_label.any():
            fallback_tenor = out.loc[missing_tenor_label].apply(
                lambda row: tenor_to_label(
                    float(row.get("tenor_years")) if pd.notna(row.get("tenor_years")) else 0.0,
                    pd.to_datetime(row.get("expiration_date"), errors="coerce"),
                    True,
                ),
                axis=1,
            )
            out.loc[missing_tenor_label, "tenor_label"] = fallback_tenor

    if "forward_label" in out.columns and "forward_start_years" in out.columns:
        missing_forward_label = _is_blank_series(out["forward_label"])
        if missing_forward_label.any():
            fallback_forward = out.loc[missing_forward_label].apply(
                lambda row: forward_to_label(
                    float(row.get("forward_start_years")) if pd.notna(row.get("forward_start_years")) else 0.0,
                    pd.to_datetime(row.get("expiration_date"), errors="coerce"),
                    True,
                ),
                axis=1,
            )
            out.loc[missing_forward_label, "forward_label"] = fallback_forward

    if "trade_label" in out.columns:
        missing_trade_label = _is_blank_series(out["trade_label"])
        if missing_trade_label.any():
            fallback_trade_label = out.loc[missing_trade_label].apply(
                lambda row: build_trade_label(
                    _clean_text(row.get("forward_label")) or "OD",
                    _clean_text(row.get("tenor_label")) or "UNK",
                    True,
                ),
                axis=1,
            )
            out.loc[missing_trade_label, "trade_label"] = fallback_trade_label

    return out


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
        description_has_usd = swaption_trades_df["description"].astype("string").str.contains("USD", na=False, regex=False)
        has_underlier_maturity = swaption_trades_df["Maturity date of the underlier"].notna()
        swaption_trades_df = swaption_trades_df[description_has_usd & has_underlier_maturity]
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
        action_type = _clean_text(row.get("Action type"))
        event_type = _clean_text(row.get("Event type"))
        event_action = "TERM-ETRM" if forward_label == "OD" else f"{action_type}-{event_type}".strip("-")
        if not event_action:
            event_action = "NEWT-TRAD"
        trade_label = _clean_text(row.get("description"))
        if not trade_label:
            trade_label = build_trade_label(_clean_text(forward_label) or "OD", _clean_text(tenor_label) or "UNK", True)
        notional_currency = _clean_text(row.get("Notional currency-Leg 1")) or _clean_text(row.get("Notional currency-Leg 2")) or "USD"

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
            event_action=event_action,
            trade_id=trade_id,
            execution_timestamp=execution_ts,
            effective_date=effective_date,
            expiration_date=expiration_date,
            underlying_expiration_date=underlying_expiration_date,
            product_type=product_type,
            trade_label=trade_label,
            tenor_years=tenor_years,
            tenor_label=tenor_label,
            forward_label=forward_label,
            forward_start_years=forward_years,
            notional=notional,
            notional_currency=notional_currency,
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
        detect_delta_hedges: bool = True,
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
            detect_delta_hedges: Whether to detect swaption/swap delta-hedge packages
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

        raw_sofr_swaps_df = pd.DataFrame()
        if detect_swaption_packages and detect_delta_hedges:
            raw_sofr_swaps_df = sdr.grab_sdr_trades(
                start_timestamp=start,
                end_timestamp=end,
                agency="CFTC",
                asset_class="RATES",
                filter_func=new_sofr_swap_trades,
            )
            if not raw_sofr_swaps_df.empty:
                swap_exec_dates = pd.to_datetime(raw_sofr_swaps_df["Event timestamp"], errors="coerce").dt.date
                raw_sofr_swaps_df = raw_sofr_swaps_df.assign(_execution_date=swap_exec_dates)

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

        # cached_frames = []
        missing_dates = []
        for exec_date, count in raw_sdr_trades_df["_execution_date"].value_counts().items():
        #     if pd.isna(exec_date):
        #         continue
        #     date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
        #     final_marker = date_dir / "final.marker"

        #     found_cache = False
        #     if date_dir.exists() and (ignore_cache is False):
        #         if _is_historical(exec_date) and not final_marker.exists():
        #             found_cache = False
        #         else:
        #             cache_candidates = []
        #             for fp in date_dir.glob("*.parquet"):
        #                 # pick the latest created file
        #                 cache_candidates.append((fp.stat().st_mtime, fp))

        #             if cache_candidates:
        #                 _, best_cache_fp = max(cache_candidates, key=lambda x: x[0])
        #                 try:
        #                     cached_frames.append(pd.read_parquet(best_cache_fp, engine="pyarrow"))
        #                     found_cache = True
        #                 except Exception:
        #                     best_cache_fp.unlink(missing_ok=True)

        #     if not found_cache:
        #         missing_dates.append(exec_date)
            missing_dates.append(exec_date)

        def _to_utc(ts: pd.Timestamp) -> pd.Timestamp:
            timestamp = pd.Timestamp(ts)
            if timestamp.tzinfo is None:
                return timestamp.tz_localize(pytz.utc)
            return timestamp.tz_convert(pytz.utc)

        # if not missing_dates:
        #     if cached_frames:
        #         final_df = pd.concat(cached_frames, ignore_index=True)
        #         start_ts = _to_utc(start)
        #         end_ts = _to_utc(end)
        #         final_df = final_df[(final_df["execution_timestamp"] >= start_ts) & (final_df["execution_timestamp"] <= end_ts)]
        #         final_df = final_df.sort_values(by="execution_timestamp")
        #         if merge_package_legs:
        #             final_df = merge_package_legs_to_one_row(final_df)
        #             final_df = merge_vega_curve_packages(final_df)
        #         return final_df

        #     return pd.DataFrame()

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
                "UPI FISN",
                "Unique Product Identifier",
                "Platform identifier",
                "Cleared",
                "Action type",
                "Event type",
                "Package indicator",
                "Package transaction price",
                "Option Premium Amount",
                "description",
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
            package_df = _backfill_swaption_fields(package_df)

            # Defensive guard: package detection/classification should only run on NEWT/TRAD rows.
            if "action_type" in package_df.columns and "event_type" in package_df.columns:
                newt_trad_mask = (
                    package_df["action_type"].astype("string").str.upper().eq("NEWT")
                    & package_df["event_type"].astype("string").str.upper().eq("TRAD")
                )
                package_df = package_df.loc[newt_trad_mask].copy()
                if package_df.empty:
                    continue

            if "strike" in package_df.columns:
                package_df["strike"] = pd.to_numeric(package_df["strike"], errors="coerce")

            # Detect swaption packages
            if detect_swaption_packages:
                day_swap_df = pd.DataFrame()
                if detect_delta_hedges and not raw_sofr_swaps_df.empty:
                    day_swap_df = raw_sofr_swaps_df[raw_sofr_swaps_df["_execution_date"] == exec_date].copy()

                if detect_delta_hedges and not day_swap_df.empty:
                    package_df = detect_and_link_swaption_packages_df(
                        package_df,
                        config=swaption_package_config,
                        pricer=mdp.get_pricer(dict(curve_name="USD-SOFR-1D", timestamp=exec_date)),
                        detect_delta_hedges=True,
                        swap_candidates_df=day_swap_df,
                    )
                else:
                    package_df = detect_and_link_swaption_packages_df(
                        package_df,
                        config=swaption_package_config,
                        pricer=mdp.get_pricer(dict(curve_name="USD-SOFR-1D", timestamp=exec_date)),
                    )

            # count = len(day_df)
            # date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
            # date_dir.mkdir(parents=True, exist_ok=True)
            # cache_fp = date_dir / f"{count}.parquet"
            # tmp_fp = cache_fp.with_suffix(".parquet.tmp")
            # table = pa.Table.from_pandas(package_df, preserve_index=False)
            # pq.write_table(table, tmp_fp, compression="zstd")
            # tmp_fp.replace(cache_fp)
            # if _is_historical(exec_date):
            #     final_marker = date_dir / "final.marker"
            #     final_marker.touch()

            built_frames.append(package_df)

        # all_frames = [*cached_frames, *built_frames]
        all_frames = [*built_frames]
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
