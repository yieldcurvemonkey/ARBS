"""
USD SOFR OIS Swap product module.

Provides classification and analysis for USD SOFR-based OIS swaps
reported to the DTCC SDR.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import QuantLib as ql
from tqdm import tqdm

import Query.IRSwaps.adapter  # noqa: F401
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps._CME_INVOICE_SWAP_TICKERS import _CME_INVOICE_SWAP_TICKERS, _INDICATOR_TO_TICKER

from SDRUtils.config import PRODUCT_TYPES, TRADE_ID, USD_CONVENTIONS
from SDRUtils.core.classification import TradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages import detect_curve_trades_df, detect_fly_trades_df, detect_mms_trades_df, merge_package_legs_to_one_row
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products.usd.filters import new_sofr_swap_trades


def classify_sofr_swap_trade(
    row: pd.Series,
    trade_id: int,
    curve: _IRSwapGenericCurve,
) -> TradeClassification:
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
        TradeClassification object with all trade details
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
    notional = parse_notional(row.get("Notional amount-Leg 1", 0))
    fixed_rate = row.get("Fixed rate-Leg 1")
    strike = row.get("Strike Price")

    # Calculate PV01 if curve provided
    pkg, _ = IRSwapQuery(
        curve="USD-SOFR-1D", effective_date=effective_date.date(), maturity_date=expiration_date.date(), structure_kwargs={"notional": notional}
    ).resolve_package(pricer_or_curve=curve)
    pv01 = curve.pv01(pkg[0])

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
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
    )


def flag_invoice_swaps(
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
        except:
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


class USD_SOFR_SwapProduct(USDProductBase):
    """
    USD SOFR OIS Swap product implementation.

    This class implements the ProductModule interface for USD SOFR swaps,
    providing trade classification and product type inference.
    """

    name = "USD-SOFR-OIS"
    product_type = PRODUCT_TYPES.OIS_SWAP

    def classify_trade(self, row: pd.Series, trade_id: int, curve: _IRSwapGenericCurve) -> TradeClassification:
        """
        Classify a single USD SOFR swap trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments, including 'curve' for PV01

        Returns:
            TradeClassification object
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
        **kwargs: Any,
    ):
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=new_sofr_swap_trades,
        )

        if raw_sdr_trades_df.empty:
            return raw_sdr_trades_df

        exec_dates = pd.to_datetime(raw_sdr_trades_df["Execution Timestamp"], errors="coerce").dt.date
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
            if cache_fp.exists():
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
            day_df = raw_sdr_trades_df[raw_sdr_trades_df["_execution_date"] == exec_date]
            curve = IRSwapsMDP(kwargs.get("curve_source", "ERIS_EOD_LIVE-RL_BASIC")).get_pricer(request=dict(curve_name="USD-SOFR-1D", timestamp=exec_date))

            classifications = [
                self.classify_trade(row, trade_id=row.get(TRADE_ID), curve=curve)
                for _, row in tqdm(day_df.iterrows(), total=day_df.shape[0], desc=f"Classifying Trades {exec_date}")
            ]
            classifications_df = classifications_to_dataframe(classifications)

            package_df = classifications_df.merge(
                day_df[
                    [
                        TRADE_ID,
                        "UPI Underlier Name",
                        "Platform identifier",
                        "Cleared",
                    ]
                ],
                on=TRADE_ID,
                how="left",
            )
            package_df = package_df.drop(columns=[TRADE_ID])

            if detect_fly:
                package_df = detect_fly_trades_df(package_df)
            if detect_curve:
                package_df = detect_curve_trades_df(package_df)
            if detect_mms:
                package_df = detect_mms_trades_df(package_df)
            if detect_invoice:
                package_df = flag_invoice_swaps(package_df)

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
        final_df["risk"] = (final_df["risk"] / 2500).round().mul(2500)

        return final_df
