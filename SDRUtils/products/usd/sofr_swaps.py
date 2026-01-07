"""
USD SOFR OIS Swap product module.

Provides classification and analysis for USD SOFR-based OIS swaps
reported to the DTCC SDR.
"""

from __future__ import annotations

import datetime
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import QuantLib as ql
import requests
from tqdm import tqdm

import Query.IRSwaps.adapter  # noqa: F401
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps._CME_INVOICE_SWAP_TICKERS import _CME_INVOICE_SWAP_TICKERS, _INDICATOR_TO_TICKER

from SDRUtils.config import PRODUCT_TYPES, TRADE_ID, USD_CONVENTIONS
from SDRUtils.core.classification import SwapTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages import detect_curve_trades_df, detect_fly_trades_df, detect_mms_trades_df, merge_package_legs_to_one_row
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products._swaps.filters import sofr_swap_trades
from SDRUtils.products._swaps._cme_mac import fetch_mac_ref_data


def classify_sofr_swap_trade(
    row: pd.Series,
    trade_id: int,
    curve: _IRSwapGenericCurve,
) -> SwapTradeClassification:
    """
    Classify a single USD SOFR OIS swap from SDR data.

    This function extracts all relevant trade characteristics:
    - Product type (OIS_SWAP, SWAPTION, etc.)
    - Tenor and forward start calculations
    - Special date detection (IMM/FOMC)
    - PV01 calculation (if curve provided)

    Args:
        row: SDR data row as pandas Series
        trade_id: Unique identifier for the trade
        curve: Optional curve object for PV01 calculation
        calculate_pv01: Whether to calculate PV01 (requires curve)

    Returns:
        SwapTradeClassification object with all trade details
    """
    # Extract dates
    execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
    effective_date = pd.to_datetime(row.get("Effective Date"))
    expiration_date = pd.to_datetime(row.get("Expiration Date"))

    # Determine product type
    product_type = classify_product_type(row)

    # Calculate tenor
    tenor_years = calculate_tenor_years(
        effective_date,
        expiration_date,
        conventions=USD_CONVENTIONS,
    )
    tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

    # Calculate forward start
    forward_years = calculate_forward_start_years(
        execution_ts,
        effective_date,
        conventions=USD_CONVENTIONS,
    )

    # Determine if forward-starting using T+2 convention
    ql_exec = to_ql_date(execution_ts)
    ql_eff = to_ql_date(effective_date)

    is_forward = False
    if ql_exec and ql_eff:
        t_plus_2 = USD_CONVENTIONS.calendar.advance(ql_exec, 2, ql.Days)
        if ql_eff > t_plus_2:
            is_forward = True

    forward_label = forward_to_label(forward_years, effective_date=effective_date)

    # Build trade label
    trade_label = build_trade_label(forward_label, tenor_label, is_forward)

    # Extract notional and rate
    notional = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
    fixed_rate = row.get("Fixed rate-Leg 1", row.get("Fixed rate-Leg 2"))
    # Calculate PV01 if curve provided
    pkg, _ = IRSwapQuery(
        curve="USD-SOFR-1D", effective_date=effective_date.date(), maturity_date=expiration_date.date(), structure_kwargs={"notional": notional}
    ).resolve_package(pricer_or_curve=curve)
    pv01 = curve.pv01(pkg[0])

    return SwapTradeClassification(
        event_action=f"{row["Action type"]}-{row["Event type"]}",
        trade_id=trade_id,
        execution_timestamp=execution_ts,
        effective_date=effective_date,
        expiration_date=expiration_date,
        product_type=product_type,
        trade_label=trade_label,
        tenor_years=tenor_years,
        tenor_label=tenor_label,
        is_forward=is_forward,
        forward_start_years=forward_years,
        forward_label=forward_label,
        notional=notional,
        notional_currency=row.get("Notional currency-Leg 1", "USD"),
        fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
    )


def detect_invoice_swaps(
    package_df: pd.DataFrame,
    execution_col: str = "execution_timestamp",
    show_tqdm: bool = True,
) -> pd.DataFrame:
    if package_df.empty:
        return package_df

    out = package_df.copy()
    exec_dates = pd.to_datetime(out.get(execution_col), errors="coerce")
    if exec_dates.isna().all():
        return out

    as_of = exec_dates.dt.date.value_counts().index[0]

    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
    from definitions.USTFutures import front_month

    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    roots = sorted({spec["root"] for spec in _CME_INVOICE_SWAP_TICKERS.values()})
    invoice_specs = []
    iterator = tqdm(roots, desc="FETCHING DELIVERY BASKETS...") if show_tqdm else roots
    for root in iterator:
        contract = front_month(as_of, root)

        try:
            basket = ustf_mdp.get_delivery_basket(as_of=as_of, symbol=contract, usts_mdp_source="USTS_FEDINVEST_WSJ_LIVE-RL")
        except Exception:
            basket = ustf_mdp.get_delivery_basket(as_of=as_of, symbol=contract, usts_mdp_source="USTS_TRADINGVIEW_LIVE-RL")

        delivery_start, delivery_end = basket["delivery"]

        try:
            pricer = ustf_mdp.get_pricer(request={"symbols": [contract], "timestamp": as_of, "usts_mdp_source": "USTS_FEDINVEST_WSJ_LIVE-RL"})[contract]
        except:
            pricer = ustf_mdp.get_pricer(request={"symbols": [contract], "timestamp": as_of, "usts_mdp_source": "USTS_TRADINGVIEW_LIVE-RL"})[contract]

        for indicator in "ABCDEF":
            ticker = _INDICATOR_TO_TICKER.get(root, {}).get(indicator)
            if not ticker:
                continue
            delivery_date = delivery_end if _CME_INVOICE_SWAP_TICKERS[ticker]["delivery"] == "last" else delivery_start
            ctd_pricer = pricer.ctd(indicator)
            if ctd_pricer is None:
                continue
            invoice_specs.append(
                {
                    "invoice_swap_delivery_date": delivery_date,
                    "invoice_swap_ctd_maturity": ctd_pricer.maturity_date(),
                    "invoice_swap_ticker": ticker,
                }
            )

    if not invoice_specs:
        out["invoice_swap_ticker"] = None
        return out

    lookup = pd.DataFrame(invoice_specs).drop_duplicates(subset=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"], keep="first")
    lookup["invoice_swap_delivery_date"] = pd.to_datetime(lookup["invoice_swap_delivery_date"])
    lookup["invoice_swap_ctd_maturity"] = pd.to_datetime(lookup["invoice_swap_ctd_maturity"])

    package_df["effective_date"] = pd.to_datetime(package_df["effective_date"])
    package_df["expiration_date"] = pd.to_datetime(package_df["expiration_date"])
    package_df["expiration_date_norm"] = package_df["expiration_date"].dt.normalize()

    df_invoice_subset = lookup[["invoice_swap_delivery_date", "invoice_swap_ctd_maturity", "invoice_swap_ticker"]].rename(
        columns={"invoice_swap_ticker": "invoice_swap_ticker_new"}
    )
    df_merged = package_df.merge(
        df_invoice_subset, left_on=["effective_date", "expiration_date_norm"], right_on=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"], how="left"
    )

    condition = (df_merged["matched_ust_maturity_trade_confidence"] == "high") & (df_merged["invoice_swap_ticker_new"].notna())
    df_merged.loc[condition, "invoice_swap_ticker"] = df_merged.loc[condition, "invoice_swap_ticker_new"]
    cols_to_drop = [
        "expiration_date_norm",
        "invoice_swap_ticker_new",
        "invoice_swap_delivery_date_y",  # If column existed in both, suffix might be applied
        "invoice_swap_ctd_maturity_y",
    ]
    existing_cols_to_drop = [c for c in df_merged.columns if c in cols_to_drop or c in df_invoice_subset.columns[:-1]]
    return df_merged.drop(columns=existing_cols_to_drop, errors="ignore")


def detect_mac_swaps(package_df: pd.DataFrame) -> pd.DataFrame:
    out = package_df.copy()

    out["_mac_eff"] = pd.to_datetime(out.get("effective_date"), errors="coerce").dt.normalize()
    out["_mac_exp"] = pd.to_datetime(out.get("expiration_date"), errors="coerce").dt.normalize()
    out["_fixed_rate"] = pd.to_numeric(out.get("fixed_rate"), errors="coerce")
    out["_fixed_rate_bp"] = (out["_fixed_rate"] * 10000).round().astype("Int64")

    mac_lookup_frames: list[pd.DataFrame] = []
    mac_cache: dict[tuple[int, int], pd.DataFrame] = {}

    for eff in out["_mac_eff"].dropna().unique():
        key = (int(eff.year), int(eff.month))
        if key not in mac_cache:
            try:
                mac_cache[key] = fetch_mac_ref_data(effective_date=eff)
            except Exception:
                mac_cache[key] = pd.DataFrame()
        if not mac_cache[key].empty:
            mac_lookup_frames.append(mac_cache[key])

    if not mac_lookup_frames:
        out["is_mac"] = False
        return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_bp"], errors="ignore")

    mac_lookup = pd.concat(mac_lookup_frames, ignore_index=True)
    mac_lookup = mac_lookup.dropna(subset=["imm_start_date", "expiration_date", "coupon"]).copy()

    mac_lookup["_mac_eff"] = pd.to_datetime(mac_lookup["imm_start_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_exp"] = pd.to_datetime(mac_lookup["expiration_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_coupon"] = pd.to_numeric(mac_lookup["coupon"], errors="coerce") / 100.0
    mac_lookup["_mac_coupon_bp"] = (mac_lookup["_mac_coupon"] * 10000).round().astype("Int64")

    mac_lookup = mac_lookup[["_mac_eff", "_mac_exp", "_mac_coupon_bp"]].drop_duplicates()

    tol_days = 5
    exp_lists = mac_lookup.groupby(["_mac_eff", "_mac_coupon_bp"])["_mac_exp"].apply(lambda s: tuple(pd.Series(s).dropna().unique())).to_dict()

    def _row_is_mac(eff, exp, coupon_bp) -> bool:
        if pd.isna(eff) or pd.isna(exp) or pd.isna(coupon_bp):
            return False
        exps = exp_lists.get((eff, int(coupon_bp)))
        if not exps:
            return False
        exp = pd.Timestamp(exp)
        for mexp in exps:
            if abs((exp - pd.Timestamp(mexp)).days) <= tol_days:
                return True
        return False

    # out["is_mac"] = [_row_is_mac(eff, exp, cpn) for eff, exp, cpn in zip(out["_mac_eff"].values, out["_mac_exp"].values, out["_fixed_rate_bp"].values)]
    out["is_mac"] = [
        _row_is_mac(eff, exp, cpn)
        for eff, exp, cpn in tqdm(
            zip(out["_mac_eff"].values, out["_mac_exp"].values, out["_fixed_rate_bp"].values),
            total=len(out),
            desc="Detecting MAC swaps",
            leave=False,
        )
    ]

    return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_bp"], errors="ignore")


def detect_spreadovers(package_df: pd.DataFrame):
    copy_df = package_df.copy()

    broker_spreadover_mask = (
        (copy_df["package_legs"].isna())
        & (copy_df["package_indicator"] == True)
        & (copy_df["package_transaction_spread"].notna())
        # & (copy_df["package_transaction_spread"] != "")
        & (copy_df["forward_label"] == "spot")
    )
    copy_df["is_spreadover"] = False
    copy_df.loc[broker_spreadover_mask, "is_spreadover"] = True

    asset_swap_mask = (
        (copy_df["package_legs"].isna())
        & (copy_df["package_indicator"] == True)
        & (copy_df["package_transaction_spread"].notna())
        & (copy_df["other_payment_type"] == "UFRO")
        & (copy_df["forward_label"] == "spot")
    )
    copy_df["is_asset_swap"] = False
    copy_df.loc[asset_swap_mask, "is_asset_swap"] = True

    return copy_df


class USD_SOFR_SwapProduct(USDProductBase):
    """
    USD SOFR OIS Swap product implementation.

    This class implements the ProductModule interface for USD SOFR swaps,
    providing trade classification and product type inference.
    """

    name = "USD-SOFR-OIS"
    product_type = PRODUCT_TYPES.OIS_SWAP

    def classify_trade(self, row: pd.Series, trade_id: int, curve: _IRSwapGenericCurve) -> SwapTradeClassification:
        """
        Classify a single USD SOFR swap trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments, including 'curve' for PV01

        Returns:
            SwapTradeClassification object
        """
        return classify_sofr_swap_trade(
            row,
            trade_id,
            curve,
        )

    def classify_product_type(self, row: pd.Series) -> str:
        """Infer product type from SDR row."""
        return classify_product_type(row)

    def build_classification_dataframe(
        self,
        start: datetime.datetime,
        end: datetime.datetime,
        cache_path: str,
        detect_curve=True,
        detect_fly=True,
        detect_mms=True,
        detect_invoice=True,
        detect_mac=True,
        detect_spreadover=True,
        ignore_cache: bool = False,
        **kwargs: Any,
    ):
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=sofr_swap_trades,
            ignore_cache=ignore_cache,
        )

        if raw_sdr_trades_df.empty:
            return raw_sdr_trades_df

        # TODO review needed
        # Execution Timestamp = Date and time a transaction was originally executed, resulting in the generation of a new UTI. This data element remains unchanged throughout the life of the UTI.
        # Event Timestamp = Date and time of occurrence of the event as determined by the reporting counterparty or a service provider
        # exec_dates = pd.to_datetime(raw_sdr_trades_df["Execution Timestamp"], errors="coerce").dt.date
        exec_dates = pd.to_datetime(raw_sdr_trades_df["Event timestamp"], errors="coerce").dt.date
        raw_sdr_trades_df = raw_sdr_trades_df.assign(_execution_date=exec_dates)
        curve_source = str(kwargs.get("curve_source", "ERIS_EOD_LIVE-RL_BASIC")).replace("/", "_")
        cache_flags = f"curve{int(detect_curve)}_fly{int(detect_fly)}_mms{int(detect_mms)}_invoice{int(detect_invoice)}"
        cache_base = Path(cache_path) / "classification_cache" / "usd_sofr_swaps" / curve_source / cache_flags
        cache_base.mkdir(parents=True, exist_ok=True)

        cached_frames = []
        missing_dates = []
        for exec_date, count in raw_sdr_trades_df["_execution_date"].value_counts().items():
            if pd.isna(exec_date):
                continue
            date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
            cache_fp = date_dir / f"{count}.parquet"
            if cache_fp.exists() and (ignore_cache == False):
                try:
                    cached_frames.append(pd.read_parquet(cache_fp, engine="pyarrow"))
                    continue
                except Exception:
                    cache_fp.unlink(missing_ok=True)
            missing_dates.append(exec_date)

        if not missing_dates:
            if cached_frames:
                final_df = pd.concat(cached_frames, ignore_index=True)
                final_df = merge_package_legs_to_one_row(final_df)
                final_df["risk"] = final_df["estimated_pv01"].apply(lambda x: float(str(x).split("/")[0]) if type(x) == str else float(x))
                final_df["risk"] = (final_df["risk"] / 2500).round().mul(2500)
                return final_df
            return pd.DataFrame()

        built_frames = []
        for exec_date in missing_dates:
            # ignore dates falling outside of execution
            # consequence: will drop modifications
            if exec_date > end.date() or exec_date < start.date():
                continue

            day_df = raw_sdr_trades_df[raw_sdr_trades_df["_execution_date"] == exec_date]

            # classifications = [
            #     self.classify_trade(row, trade_id=row.get(TRADE_ID), curve=curve)
            #     for _, row in tqdm(day_df.iterrows(), total=day_df.shape[0], desc=f"Classifying Trades {exec_date}")
            # ]
            classifications = self.classify_messages(
                day_df,
            )
            classifications_df = classifications_to_dataframe(classifications)
            if not classifications_df.empty:
                classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
                day_df = day_df.copy()
                day_df[TRADE_ID] = day_df[TRADE_ID].astype("string")

            package_df = classifications_df.merge(
                day_df[
                    # this is temp
                    [
                        TRADE_ID,
                        "UPI Underlier Name",
                        "Unique Product Identifier",
                        "Platform identifier",
                        "Cleared",
                        "Prime brokerage transaction indicator",
                        "Block trade election indicator",
                        "Large notional off-facility swap election indicator",
                        "Other payment type",  # non-par
                        "Other payment amount",
                        "Package indicator",
                        "Package transaction spread",
                    ]
                ],
                on=TRADE_ID,
                how="left",
            )

            package_df = package_df.drop(columns=[TRADE_ID])
            package_df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_") for col in package_df.columns]

            if detect_fly:
                package_df = detect_fly_trades_df(package_df)
            if detect_curve:
                package_df = detect_curve_trades_df(package_df)
            if detect_mms:
                package_df = detect_mms_trades_df(package_df)
            if detect_invoice:
                package_df = detect_invoice_swaps(package_df)
            if detect_mac:
                package_df = detect_mac_swaps(package_df)
            if detect_spreadover:
                package_df = detect_spreadovers(package_df)

            count = len(day_df)
            date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
            date_dir.mkdir(parents=True, exist_ok=True)
            cache_fp = date_dir / f"{count}.parquet"
            tmp_fp = cache_fp.with_suffix(".parquet.tmp")
            table = pa.Table.from_pandas(package_df, preserve_index=False)
            pq.write_table(table, tmp_fp, compression="zstd")
            tmp_fp.replace(cache_fp)

            built_frames.append(package_df)

        all_frames = [*cached_frames, *built_frames]
        if not all_frames:
            return pd.DataFrame()

        final_df = pd.concat(all_frames, ignore_index=True)
        final_df = merge_package_legs_to_one_row(final_df)
        final_df["risk"] = final_df["estimated_pv01"].apply(lambda x: float(str(x).split("/")[0]) if type(x) == str else float(x))
        final_df["risk"] = (final_df["risk"] / 100).round().mul(100)

        return final_df
