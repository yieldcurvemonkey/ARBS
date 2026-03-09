"""USD SOFR cap/floor product module."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Optional

import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from SDRUtils.config import PRODUCT_TYPES, TRADE_ID
from SDRUtils.core.classification import (
    CapFloorTradeClassification,
    classifications_to_dataframe,
)
from SDRUtils.core.dates import (
    calculate_forward_start_years,
    calculate_tenor_years,
    is_forward_starting,
)
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import forward_to_label, tenor_from_dates
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.products._capfloors.pricing import strip_cap_vol
from SDRUtils.products._capfloors.upi import build_capfloor_upi_set
from SDRUtils.products.usd.base import USDProductBase

_CAPFLOOR_FISN = {"NA/O CALL EPN USD", "NA/O P EPN USD"}
_PRICING_ANALYTIC_FIELDS = (
    "implied_vol_bps",
    "num_caplets",
    "moneyness_bps",
    "bpvol",
    "caplet_details",
    "model_premium",
    "market_premium",
    "pricing_error",
    "warnings",
)


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return ""
    return text


def _parse_numeric(value: object) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip()
    if not text:
        return float("nan")
    text = text.replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except Exception:
        return float("nan")


def _parse_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .map({"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False})
        .fillna(False)
    )


def _parse_cap_floor_type(value: object) -> str:
    text = _clean_text(value).upper()
    if "CALL" in text:
        return "CAP"
    if " P " in f" {text} " or "PUT" in text or "NA/O P" in text:
        return "FLOOR"
    return "CAP"


def _parse_reset_frequency(row: pd.Series) -> str:
    multiplier = _parse_numeric(row.get("Floating rate reset frequency period multiplier-leg 1"))
    if not math.isfinite(multiplier) or multiplier <= 0:
        multiplier = 1.0
    period = _clean_text(
        row.get("Floating rate reset frequency period-leg 1")
        or row.get("Floating rate reset frequency period unit-leg 1")
        or row.get("Floating rate reset frequency period unit")
    ).upper()
    if period.startswith("DAY") or period == "D":
        suffix = "D"
    elif period.startswith("WEEK") or period == "W":
        suffix = "W"
    elif period.startswith("YEAR") or period == "Y":
        suffix = "Y"
    else:
        suffix = "M"
    return f"{int(round(multiplier))}{suffix}"


def _parse_strike(row: pd.Series) -> Optional[float]:
    strike = _parse_numeric(row.get("Strike Price"))
    notation = _parse_numeric(row.get("Strike price notation"))
    if not math.isfinite(strike):
        return None
    if math.isfinite(notation) and abs(notation - 3.0) < 1e-9 and strike >= 1:
        return strike / 100.0
    if strike > 1:
        return strike / 100.0
    return strike


def _format_strike_percent(strike: Optional[float]) -> str:
    if strike is None or not math.isfinite(strike):
        return "UNK"
    return f"{strike * 100:.2f}%"


def _underlier_label(row: pd.Series) -> str:
    raw = _clean_text(row.get("UPI Underlier Name")).upper()
    if "SOFR" in raw and ("TERM" in raw or "CME" in raw):
        return "USD-SOFR-CME-TERM"
    if "SOFR" in raw and "COMPOUND" in raw:
        return "USD-SOFR-COMPOUND"
    if "SOFR" in raw:
        return "USD-SOFR"
    normalized = re.sub(r"[^A-Z0-9]+", "-", raw).strip("-")
    return normalized or "USD-SOFR"


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [
        re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_")
        for col in out.columns
    ]
    return out


def _extract_pricing_analytics(result: dict[str, Any]) -> dict[str, Any]:
    return {field: result[field] for field in _PRICING_ANALYTIC_FIELDS if field in result}


def _resolve_curve_handle(
    exec_date: dt.date,
    *,
    curve_source: str,
    curve_name: str,
) -> Any:
    attempts = [
        (curve_source, curve_name),
        ("BARCHART_STIRF-RL", "USD-SOFR-1D-Q12xM12STIRT"),
        ("ERIS_EOD_LIVE-RL_BASIC", "USD-SOFR-1D"),
    ]
    errors: list[str] = []
    for source_name, curve_name_value in attempts:
        try:
            curve_obj = IRSwapsMDP(source=source_name)._get_curve(curve_name=curve_name_value, timestamp=exec_date)
            return curve_obj.handle() if hasattr(curve_obj, "handle") else curve_obj
        except Exception as exc:  # pragma: no cover - exercised only when curve sources fail
            errors.append(f"{source_name}/{curve_name_value}: {exc}")
    raise RuntimeError("Unable to resolve SOFR curve handle: " + "; ".join(errors))


class USD_CapFloors(USDProductBase):
    name = "USD-CAPFLOORS"
    product_type = PRODUCT_TYPES.CAP
    package_type = "OUTRIGHT"

    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        upi_set = build_capfloor_upi_set(kwargs.get("base_dir"))
        out = df.copy()

        fisn = out.get("UPI FISN", pd.Series("", index=out.index)).astype("string").str.strip().str.upper()
        upi = out.get("Unique Product Identifier", pd.Series("", index=out.index)).astype("string").str.strip().str.upper()
        underlier = out.get("UPI Underlier Name", pd.Series("", index=out.index)).astype("string")
        premium = out.get("Option Premium Amount", pd.Series(index=out.index, dtype="float64")).apply(_parse_numeric)
        package_indicator = _parse_bool_series(out.get("Package indicator", pd.Series(False, index=out.index)))
        action_type = out.get("Action type", pd.Series("", index=out.index)).astype("string").str.strip().str.upper()

        mask = (
            (fisn.isin(_CAPFLOOR_FISN) | upi.isin(upi_set))
            & underlier.str.contains("SOFR", case=False, na=False)
            & premium.gt(0)
            & ~package_indicator
            & action_type.eq("NEWT")
        )
        return out.loc[mask].copy()

    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> CapFloorTradeClassification:
        execution_ts = pd.to_datetime(row.get("Event timestamp"))
        effective_date = pd.to_datetime(row.get("Effective Date"))
        expiration_date = pd.to_datetime(row.get("Expiration Date"))

        cap_floor_type = _parse_cap_floor_type(row.get("UPI FISN"))
        product_type = cap_floor_type
        tenor_years = calculate_tenor_years(
            effective_date,
            expiration_date,
            conventions=self.conventions,
        )
        tenor_label = tenor_from_dates(effective_date, expiration_date, is_swaptions=True)

        forward_years = max(
            calculate_forward_start_years(
                execution_ts,
                effective_date,
                conventions=self.conventions,
            ),
            0.0,
        )
        forward_label = (
            forward_to_label(forward_years, effective_date, True)
            if is_forward_starting(execution_ts, effective_date, conventions=self.conventions)
            else "0D"
        )

        action_type = _clean_text(row.get("Action type"))
        event_type = _clean_text(row.get("Event type"))
        event_action = f"{action_type}-{event_type}".strip("-") or "NEWT-TRAD"
        notional_currency = (
            _clean_text(row.get("Notional currency-Leg 1"))
            or _clean_text(row.get("Notional currency-Leg 2"))
            or "USD"
        )
        notional, is_notional_capped = parse_notional(row.get("Notional amount-Leg 1", 0))
        strike = _parse_strike(row)
        premium = _parse_numeric(row.get("Option Premium Amount"))
        reset_frequency = _parse_reset_frequency(row)
        trade_label = " ".join(
            [
                _underlier_label(row),
                reset_frequency,
                tenor_label,
                cap_floor_type,
                _format_strike_percent(strike),
            ]
        ).strip()

        fisn = _clean_text(row.get("UPI FISN")).lower()
        if "brm" in fisn:
            exercise_style = "BERMUDAN"
        elif "epn" in fisn:
            exercise_style = "EUROPEAN"
        else:
            exercise_style = "AMERICAN"

        return CapFloorTradeClassification(
            event_action=event_action,
            trade_id=trade_id,
            execution_timestamp=execution_ts,
            effective_date=effective_date,
            expiration_date=expiration_date,
            product_type=product_type,
            trade_label=trade_label,
            tenor_years=tenor_years,
            tenor_label=tenor_label,
            forward_start_years=forward_years,
            forward_label=forward_label,
            premium=premium if math.isfinite(premium) else None,
            exercise_style=exercise_style,
            strike=strike,
            notional=notional,
            notional_currency=notional_currency,
            is_notional_capped=is_notional_capped,
            package_type=self.package_type,
            cap_floor_type=cap_floor_type,
            reset_frequency=reset_frequency,
        )

    def build_classification_dataframe(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        cache_path: str,
        ignore_cache: bool = False,
        merge_package_legs: bool = False,
        only_newt: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame:
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=self.detect,
            ignore_cache=ignore_cache,
        )

        if raw_df.empty:
            return raw_df

        if only_newt:
            raw_df = raw_df[(raw_df["Action type"] == "NEWT") & (raw_df["Event type"] == "TRAD")].copy()
            if raw_df.empty:
                return raw_df

        exec_dates = pd.to_datetime(raw_df["Event timestamp"], errors="coerce").dt.date
        raw_df = raw_df.assign(_execution_date=exec_dates)

        curve_source = str(kwargs.get("curve_source", "BARCHART_STIRF-RL")).replace("/", "_")
        curve_name = str(kwargs.get("curve_name", "USD-SOFR-1D-Q12xM12STIRT"))

        built_frames: list[pd.DataFrame] = []
        for exec_date in raw_df["_execution_date"].dropna().sort_values().unique():
            day_df = raw_df[raw_df["_execution_date"] == exec_date].copy()
            classifications = self.classify_messages(day_df, **kwargs)
            classifications_df = classifications_to_dataframe(classifications)
            if classifications_df.empty:
                continue

            classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
            day_df[TRADE_ID] = day_df[TRADE_ID].astype("string")
            merged = classifications_df.merge(day_df, on=TRADE_ID, how="left")

            try:
                curve = _resolve_curve_handle(exec_date, curve_source=curve_source, curve_name=curve_name)
            except Exception:
                curve = None

            analytics: list[dict[str, Any]] = []
            valuation_date = pd.Timestamp(exec_date)
            for _, trade_row in merged.iterrows():
                if curve is None:
                    analytics.append({})
                    continue
                try:
                    result = strip_cap_vol(trade_row.to_dict(), curve, valuation_date=valuation_date)
                    analytics.append(_extract_pricing_analytics(result))
                except Exception as exc:
                    analytics.append({"pricing_error": str(exc)})

            analytics_df = pd.DataFrame(analytics, index=merged.index)
            for column in analytics_df.columns:
                merged[column] = analytics_df[column]

            package_df = merged.drop(columns=[TRADE_ID], errors="ignore")
            package_df = _normalize_columns(package_df)
            package_df = package_df.loc[:, ~package_df.columns.duplicated()].copy()
            if "action_type" in package_df.columns and "event_type" in package_df.columns:
                mask = (
                    package_df["action_type"].astype("string").str.upper().eq("NEWT")
                    & package_df["event_type"].astype("string").str.upper().eq("TRAD")
                )
                package_df = package_df.loc[mask].copy()
                if package_df.empty:
                    continue

            if "trade_id" not in package_df.columns:
                package_df["trade_id"] = merged[TRADE_ID].astype("string")

            package_df["package_id"] = package_df["trade_id"].astype("string").map(lambda x: f"OUTRIGHT-{x}")
            package_df["package_type"] = "OUTRIGHT"
            if "implied_vol_bps" in package_df.columns:
                package_df["bpvol"] = package_df["implied_vol_bps"]
                package_df["outright_bpvol_yr"] = package_df["implied_vol_bps"]

            built_frames.append(package_df)

        if not built_frames:
            return pd.DataFrame()

        final_df = pd.concat(built_frames, ignore_index=True)
        final_df["execution_timestamp"] = pd.to_datetime(final_df["execution_timestamp"], errors="coerce", utc=True)
        start_ts = pd.Timestamp(start).tz_convert("UTC") if pd.Timestamp(start).tzinfo else pd.Timestamp(start).tz_localize("UTC")
        end_ts = pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else pd.Timestamp(end).tz_localize("UTC")
        final_df = final_df[(final_df["execution_timestamp"] >= start_ts) & (final_df["execution_timestamp"] <= end_ts)]
        final_df = final_df.sort_values(by="execution_timestamp")
        if merge_package_legs:
            from SDRUtils.packages.utils import merge_package_legs_to_one_row

            final_df = merge_package_legs_to_one_row(final_df)
        return final_df

    def metadata(self) -> dict[str, str]:
        return {
            "product": self.name,
            "package_type": self.package_type,
            "currency": self.currency,
        }
