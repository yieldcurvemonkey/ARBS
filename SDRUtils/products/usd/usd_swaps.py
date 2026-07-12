"""
USD swap product module.

Provides classification and analysis for USD OIS and USD fixed-float swaps
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
import pytz
import QuantLib as ql
import requests
from tqdm import tqdm

import Query.IRSwaps.adapter  # noqa: F401
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._CME_INVOICE_SWAP_TICKERS import _CME_INVOICE_SWAP_TICKERS, _INDICATOR_TO_TICKER
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from SDRUtils.config import PRODUCT_TYPES, TRADE_ID, USD_CONVENTIONS
from SDRUtils.core.classification import SwapTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, classify_intrinsic_special_tenor, forward_to_label, tenor_from_dates, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.fly import detect_fly_trades_df
from SDRUtils.packages.mms import detect_mms_trades_df
from SDRUtils.products._swaps._cme_mac import fetch_mac_ref_data
from SDRUtils.products._swaps.filters import (
    is_usd_swap,
    new_usd_swap_trades,
    usd_swap_trades,
)
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.packages.utils import merge_package_legs_to_one_row
from SDRUtils.products.usd.upi_classifier import classify_rate_index
from SDRUtils.products.usd.linear_base import LinearProductType
from SDRUtils.products.usd.sofr_ois import classify_sofr_ois_trade
from SDRUtils.products.usd.fed_funds_ois import classify_fed_funds_ois_trade
from SDRUtils.products.usd.basis_swaps import classify_basis_swap_trade


def classify_usd_swap_trade(
    row: pd.Series,
    trade_id: int,
    curve: _IRSwapGenericCurve,
) -> SwapTradeClassification:
    """
    Classify a single USD swap trade from SDR data.

    This function extracts all relevant trade characteristics:
    - Product type (OIS_SWAP, SWAPTION, etc.)
    - Tenor and forward start calculations
    - Special date detection (IMM/FOMC)
    - PV01 calculation (if curve provided)

    Args:
        row: SDR data row as pandas Series
        trade_id: Unique identifier for the trade
        curve: Optional curve object for PV01 calculation

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
    tenor_label = tenor_from_dates(effective_date, expiration_date)

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

    # Phase 1: intrinsic special tenor classification
    special_tenor_type, special_tenor_confidence, special_tenor_tags = classify_intrinsic_special_tenor(
        effective_date=effective_date,
        expiration_date=expiration_date,
        tenor_label=tenor_label,
        forward_label=forward_label,
        is_forward=is_forward,
    )

    # Extract notional and rate.
    # N3: Leg-1 is the fixed leg for USD OIS by convention; the Leg-2
    # fallback only fires on malformed rows where Leg-1 is empty. On an
    # IRS basis swap (both legs floating) this fallback silently swaps
    # to the wrong leg's notional. Upstream product classification gates
    # basis swaps out of this path — if that gating changes, revisit this
    # fallback.
    notional, is_notional_capped = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
    # Series.get only falls back when the KEY is absent — a present-but-NaN
    # Leg-1 rate must also fall through to Leg 2.
    fixed_rate = row.get("Fixed rate-Leg 1")
    if pd.isna(fixed_rate):
        fixed_rate = row.get("Fixed rate-Leg 2")
    # Keep the existing SOFR curve approximation for all USD swap underliers.
    pv01 = float("nan")
    if curve is not None and pd.notna(effective_date) and pd.notna(expiration_date):
        try:
            pkg, _ = IRSwapQuery(
                curve="USD-SOFR-1D",
                effective_date=effective_date.date(),
                maturity_date=expiration_date.date(),
                structure_kwargs={"notional": notional},
            ).resolve_package(pricer_or_curve=curve)
            if pkg:
                pv01 = curve.pv01(pkg[0])
        except Exception:
            pv01 = float("nan")

    return SwapTradeClassification(
        event_action=f"{row.get('Action type')}-{row.get('Event type')}",
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
        is_notional_capped=is_notional_capped,
        fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
        special_tenor_type=special_tenor_type,
        special_tenor_confidence=special_tenor_confidence,
        special_tenor_tags=special_tenor_tags,
    )


_INVOICE_LOOKUP_CACHE: dict[datetime.date, pd.DataFrame] = {}
_TRADE_CLASSIFICATION_CACHE: dict[str, dict] = {}
_PACKAGED_DAY_CACHE: dict[str, pd.DataFrame] = {}
_LIFECYCLE_DAY_CACHE: dict[str, tuple[int, pd.DataFrame]] = {}


def clear_service_caches() -> None:
    """Clear in-process caches. Called on hourly full reclassification."""
    _INVOICE_LOOKUP_CACHE.clear()
    _TRADE_CLASSIFICATION_CACHE.clear()
    _PACKAGED_DAY_CACHE.clear()
    _LIFECYCLE_DAY_CACHE.clear()


_SERVICE_CACHE_DIR_NAME = "service_caches"

# Bump on ANY change to detector output (new columns, changed values).
# Keys both the classification parquet day-cache directory and the
# packaged-day warm-start pickle, so stale-schema frames can never be
# served after a deploy (2026-07-01 audit, finding C4).
DETECTION_CACHE_VERSION = "ptp11-spreadover-curve-diff"


def save_service_caches(cache_dir: str) -> None:
    """Persist in-process caches to disk for warm-start optimization.

    Atomic writes (tmp + rename) prevent corruption from mid-write crashes.
    Lifecycle cache excluded — keyed on event count, stales across restarts.
    """
    import pickle
    from pathlib import Path

    cache_path = Path(cache_dir) / _SERVICE_CACHE_DIR_NAME
    cache_path.mkdir(parents=True, exist_ok=True)

    for filename, data in (
        ("trade_classification.pkl", _TRADE_CLASSIFICATION_CACHE),
        # DETECTION_CACHE_VERSION suffix: packaged-day frames cached before a detector
        # output change have a different schema; renaming orphans them.
        (f"packaged_day_{DETECTION_CACHE_VERSION}.pkl", _PACKAGED_DAY_CACHE),
    ):
        if not data:
            continue
        fp = cache_path / filename
        tmp = fp.with_suffix(".pkl.tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump(dict(data), f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(fp)
        except Exception as e:
            print(f"  [WARM] Failed to save {filename}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def load_service_caches(cache_dir: str) -> bool:
    """Load persisted caches from a prior process run.

    Returns True if any cache was successfully loaded (warm start).
    """
    import pickle
    from pathlib import Path

    cache_path = Path(cache_dir) / _SERVICE_CACHE_DIR_NAME
    if not cache_path.exists():
        return False

    loaded = False
    for filename, target in (
        ("trade_classification.pkl", _TRADE_CLASSIFICATION_CACHE),
        (f"packaged_day_{DETECTION_CACHE_VERSION}.pkl", _PACKAGED_DAY_CACHE),
    ):
        fp = cache_path / filename
        if not fp.exists():
            continue
        try:
            with open(fp, "rb") as f:
                data = pickle.load(f)
            target.update(data)
            loaded = True
            print(f"  [WARM] Loaded {len(data)} entries from {filename}")
        except Exception as e:
            print(f"  [WARM] Failed to load {filename}: {e}")
    return loaded


def detect_invoice_swaps(
    package_df: pd.DataFrame,
    execution_col: str = "execution_timestamp",
    effective_col: str = "effective_date",
    maturity_col: str = "expiration_date",
    confidence_col: Optional[str] = "matched_ust_maturity_trade_confidence",
    require_high_confidence: bool = True,
    output_col: str = "invoice_swap_ticker",
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """
    Match trades against CME invoice-swap CTD specs and annotate with ticker.

    Defaults are the USD swap mapping keys:
    - start date: effective_date
    - maturity date: expiration_date

    Callers can override these keys for other products (for example swaptions
    where maturity matching is done on underlying_expiration_date).
    """
    if package_df.empty:
        return package_df

    out = package_df.copy()
    if execution_col not in out.columns:
        if output_col not in out.columns:
            out[output_col] = None
        return out

    exec_dates = pd.to_datetime(out[execution_col], errors="coerce")
    if exec_dates.isna().all():
        if output_col not in out.columns:
            out[output_col] = None
        return out

    as_of = exec_dates.dt.date.value_counts().index[0]
    lookup = _build_invoice_swap_lookup(as_of=as_of, show_tqdm=show_tqdm)
    return _apply_invoice_swap_lookup(
        out,
        lookup,
        effective_col=effective_col,
        maturity_col=maturity_col,
        confidence_col=confidence_col,
        require_high_confidence=require_high_confidence,
        output_col=output_col,
    )


def _build_invoice_swap_lookup(
    *,
    as_of: datetime.date,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Build a unique lookup table: (delivery_date, ctd_maturity) -> invoice ticker."""
    cache_key = as_of if isinstance(as_of, datetime.date) else pd.Timestamp(as_of).date()
    if cache_key in _INVOICE_LOOKUP_CACHE:
        print(f"  [CACHE HIT] Invoice swap lookup for {cache_key}")
        return _INVOICE_LOOKUP_CACHE[cache_key]

    from definitions.USTFutures import back_months, front_month
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
    from MDP.USTFutures.treasury_conversion_factors import (
        build_delivery_basket_frame,
        delivery_calendar_window,
        resolve_delivery_contract,
    )

    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    roots = sorted({spec["root"] for spec in _CME_INVOICE_SWAP_TICKERS.values()})
    invoice_specs = []

    contract_root_pairs: list[tuple[str, str]] = []
    for root in roots:
        fm = front_month(as_of, root)
        contract_root_pairs.append((root, fm))
        try:
            bm_list = back_months(as_of, root, count=1)
            if bm_list:
                contract_root_pairs.append((root, bm_list[0]))
        except Exception:
            pass

    # Batch all contracts into ONE get_pricer call so the shared FixedRateBondsMDP
    # instance inside get_pricer reuses disk-cached CUSIPs across overlapping baskets.
    # If the batch fails (one bad contract poisons the whole call), fall back to
    # per-contract calls so working contracts still get pricers.
    all_contracts = [contract for _, contract in contract_root_pairs]
    contract_to_root = {contract: root for root, contract in contract_root_pairs}
    all_pricers: dict = {}
    for usts_src in ("USTS_FEDINVEST_WSJ_LIVE-RL", "USTS_TRADINGVIEW_LIVE-RL"):
        remaining = [c for c in all_contracts if c not in all_pricers]
        if not remaining:
            break
        try:
            batch = ustf_mdp.get_pricer(
                request={
                    "symbols": remaining,
                    "timestamp": as_of,
                    "usts_mdp_source": usts_src,
                    "include_basket": True,
                    "show_tqdm": show_tqdm,
                }
            )
            all_pricers.update(batch)
        except Exception:
            for sym in remaining:
                try:
                    single = ustf_mdp.get_pricer(
                        request={
                            "symbols": [sym],
                            "timestamp": as_of,
                            "usts_mdp_source": usts_src,
                            "include_basket": True,
                            "show_tqdm": False,
                        }
                    )
                    all_pricers.update(single)
                except Exception:
                    pass

    for root, contract in contract_root_pairs:
        pricer = all_pricers.get(contract)
        if pricer is None:
            continue

        try:
            delivery_start, delivery_end = pricer.delivery_dates()
        except Exception:
            continue

        for indicator in "ABCDEF":
            ticker = _INDICATOR_TO_TICKER.get(root, {}).get(indicator)
            if not ticker:
                continue
            delivery_date = delivery_end if _CME_INVOICE_SWAP_TICKERS[ticker]["delivery"] == "last" else delivery_start
            try:
                ctd_pricer = pricer.ctd(indicator)
            except Exception:
                continue
            if ctd_pricer is None:
                continue
            invoice_specs.append(
                {
                    "invoice_swap_delivery_date": delivery_date,
                    "invoice_swap_ctd_maturity": ctd_pricer.maturity_date(),
                    "invoice_swap_ticker": ticker,
                    "invoice_swap_contract": contract,
                    "invoice_swap_root": root,
                }
            )

        # Full-basket expansion: invoice swaps can reference ANY
        # deliverable bond, not just the top-3 CTD candidates.
        # Use build_delivery_basket_frame (reference-data-only, no
        # price fetch needed) to get the complete eligible basket.
        ctd_mats = {s["invoice_swap_ctd_maturity"] for s in invoice_specs if s["invoice_swap_contract"] == contract}
        first_ticker = _INDICATOR_TO_TICKER.get(root, {}).get("D")
        last_ticker = _INDICATOR_TO_TICKER.get(root, {}).get("A")
        try:
            basket_df = build_delivery_basket_frame(as_of=as_of, symbol=contract)
            for mat in basket_df["maturity_date"].unique():
                if mat in ctd_mats:
                    continue
                for delivery_date, ticker in ((delivery_end, last_ticker), (delivery_start, first_ticker)):
                    if ticker is None:
                        continue
                    invoice_specs.append(
                        {
                            "invoice_swap_delivery_date": delivery_date,
                            "invoice_swap_ctd_maturity": mat,
                            "invoice_swap_ticker": ticker,
                            "invoice_swap_contract": contract,
                            "invoice_swap_root": root,
                        }
                    )
        except Exception:
            pass

    if not invoice_specs:
        empty = pd.DataFrame(columns=[
            "invoice_swap_delivery_date", "invoice_swap_ctd_maturity",
            "invoice_swap_ticker", "invoice_swap_contract", "invoice_swap_root",
        ])
        _INVOICE_LOOKUP_CACHE[cache_key] = empty
        return empty

    lookup = pd.DataFrame(invoice_specs).drop_duplicates(subset=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"], keep="first")
    lookup["invoice_swap_delivery_date"] = pd.to_datetime(lookup["invoice_swap_delivery_date"])
    lookup["invoice_swap_ctd_maturity"] = pd.to_datetime(lookup["invoice_swap_ctd_maturity"])
    _INVOICE_LOOKUP_CACHE[cache_key] = lookup
    return lookup


def _apply_invoice_swap_lookup(
    package_df: pd.DataFrame,
    lookup: pd.DataFrame,
    *,
    effective_col: str,
    maturity_col: str,
    confidence_col: Optional[str],
    require_high_confidence: bool,
    output_col: str,
) -> pd.DataFrame:
    """Merge the (delivery_date, ctd_maturity) -> ticker lookup onto trades.

    A hit on this lookup is by itself definitive: the trade's (eff, mat)
    pair matches a published CBOT Treasury Invoice Swap specification
    exactly. Therefore:

    * The ticker is always written when the merge matches.
    * The matched-maturity confidence is *upgraded* to "high" on a hit
      (an invoice-spec match promotes the MMS confidence rather than
      being gated by it — otherwise the spot/MM-DD heuristic would
      block legitimate invoice swaps whose eff/mat happens to satisfy
      the heuristic).
    * ``matched_ust_maturity`` is set to True on a hit (invoice-spec
      match implies the swap lands on a UST coupon maturity by
      construction).

    ``require_high_confidence`` is kept for backward compatibility but
    is ignored when set to the default ``True`` — the semantics above
    supersede it. Callers passing ``False`` see the same behaviour.
    """
    out = package_df.copy()

    if output_col not in out.columns:
        out[output_col] = None

    if lookup.empty:
        return out
    if effective_col not in out.columns or maturity_col not in out.columns:
        return out

    out[effective_col] = pd.to_datetime(out[effective_col], errors="coerce")
    out[maturity_col] = pd.to_datetime(out[maturity_col], errors="coerce")

    maturity_norm_col = f"__{maturity_col}_norm"
    out[maturity_norm_col] = out[maturity_col].dt.normalize()

    rename_map = {"invoice_swap_ticker": "__invoice_swap_ticker_new"}
    subset_cols = ["invoice_swap_delivery_date", "invoice_swap_ctd_maturity", "invoice_swap_ticker"]
    if "invoice_swap_contract" in lookup.columns:
        subset_cols.append("invoice_swap_contract")
        rename_map["invoice_swap_contract"] = "__invoice_swap_contract_new"
    if "invoice_swap_root" in lookup.columns:
        subset_cols.append("invoice_swap_root")
        rename_map["invoice_swap_root"] = "__invoice_swap_root_new"

    # Expand lookup with ±1 day tolerance on both delivery date and CTD
    # maturity.  SDR effective dates can lag the exact CBOT delivery date
    # by a day (T+1 settlement, weekend adjustment, etc.).  The lookup is
    # small (~72 rows) so the 9x expansion is negligible.
    _one_day = pd.Timedelta(days=1)
    expanded_rows: list[dict] = []
    for _, row in lookup[subset_cols].iterrows():
        base = row.to_dict()
        for d_off in (-1, 0, 1):
            for m_off in (-1, 0, 1):
                r = base.copy()
                r["invoice_swap_delivery_date"] = row["invoice_swap_delivery_date"] + d_off * _one_day
                r["invoice_swap_ctd_maturity"] = row["invoice_swap_ctd_maturity"] + m_off * _one_day
                r["_offset_days"] = abs(d_off) + abs(m_off)
                expanded_rows.append(r)
    expanded = pd.DataFrame(expanded_rows)
    expanded = expanded.sort_values("_offset_days", kind="mergesort")
    expanded = expanded.drop_duplicates(
        subset=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"],
        keep="first",
    )
    expanded = expanded.drop(columns=["_offset_days"])

    df_invoice_subset = expanded.rename(columns=rename_map)
    df_merged = out.merge(
        df_invoice_subset,
        left_on=[effective_col, maturity_norm_col],
        right_on=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"],
        how="left",
    )

    hit_mask = df_merged["__invoice_swap_ticker_new"].notna()

    # End-of-month edge case: a spot-starting swap with a clean benchmark
    # tenor (e.g., eff=5/31/2026, mat=5/31/2031 = 5Y) can coincide with a
    # CTD maturity purely by calendar accident.  Suppress the invoice label
    # for these trades — the benchmark tenor match is more informative.
    _BENCHMARK_YEARS = {1, 2, 3, 4, 5, 7, 10, 15, 20, 25, 30}
    if hit_mask.any() and "tenor_years" in df_merged.columns and "forward_start_years" in df_merged.columns:
        fwd_yrs = pd.to_numeric(df_merged["forward_start_years"], errors="coerce").fillna(0.0)
        tenor_yrs = pd.to_numeric(df_merged["tenor_years"], errors="coerce")
        is_spot = fwd_yrs <= 0.02
        is_benchmark = tenor_yrs.apply(
            lambda t: (not pd.isna(t)) and (round(t) in _BENCHMARK_YEARS) and (abs(t - round(t)) < 0.05)
        )
        suppress = hit_mask & is_spot & is_benchmark
        if suppress.any():
            hit_mask = hit_mask & ~suppress

    # Write ticker on every merge hit — the spec match itself is the signal.
    df_merged.loc[hit_mask, output_col] = df_merged.loc[hit_mask, "__invoice_swap_ticker_new"]

    # Propagate contract symbol and root for downstream package detection.
    if "__invoice_swap_contract_new" in df_merged.columns:
        if "invoice_swap_contract" not in df_merged.columns:
            df_merged["invoice_swap_contract"] = None
        df_merged.loc[hit_mask, "invoice_swap_contract"] = df_merged.loc[hit_mask, "__invoice_swap_contract_new"]
    if "__invoice_swap_root_new" in df_merged.columns:
        if "invoice_swap_root" not in df_merged.columns:
            df_merged["invoice_swap_root"] = None
        df_merged.loc[hit_mask, "invoice_swap_root"] = df_merged.loc[hit_mask, "__invoice_swap_root_new"]

    # Promote matched-maturity confidence + flag to HIGH / True on ticker hit.
    if hit_mask.any():
        if confidence_col and confidence_col in df_merged.columns:
            df_merged.loc[hit_mask, confidence_col] = "high"
        if "matched_ust_maturity" in df_merged.columns:
            df_merged.loc[hit_mask, "matched_ust_maturity"] = True
        else:
            df_merged["matched_ust_maturity"] = False
            df_merged.loc[hit_mask, "matched_ust_maturity"] = True
        # PKG flag: invoice swap is its own package type. Distinct from
        # OUTRIGHT (single-leg SDR report) and from CURVE/FLY/BASIS
        # (multi-leg SDR-internal packages). Surfaces in the dashboard
        # PKG column so invoice swaps are filterable as a group.
        if "package_type" not in df_merged.columns:
            df_merged["package_type"] = "OUTRIGHT"
        df_merged.loc[hit_mask, "package_type"] = "INVOICE"
        if "trade_type" not in df_merged.columns:
            df_merged["trade_type"] = "OUTRIGHT"
        df_merged.loc[hit_mask, "trade_type"] = "INVOICE"
        # Clear stale package assignments from prior detectors (curve/fly)
        # so detect_invoice_packages can re-pair these trades.
        if "package_id" in df_merged.columns:
            df_merged.loc[hit_mask, "package_id"] = None
        if "package_legs" in df_merged.columns:
            df_merged.loc[hit_mask, "package_legs"] = None

    cols_to_drop = [
        maturity_norm_col,
        "__invoice_swap_ticker_new",
        "__invoice_swap_contract_new",
        "__invoice_swap_root_new",
        "invoice_swap_delivery_date",
        "invoice_swap_ctd_maturity",
        "invoice_swap_delivery_date_y",
        "invoice_swap_ctd_maturity_y",
    ]
    existing_cols_to_drop = [c for c in df_merged.columns if c in cols_to_drop]
    return df_merged.drop(columns=existing_cols_to_drop, errors="ignore")


#: Coupon-match precision for MAC swap detection. MAC swaps use strictly
#: standardized coupons (e.g. 3.00%, 3.25%, 3.50%), so the reported fixed
#: rate must match the MAC coupon exactly — no basis-point tolerance. We
#: scale both sides to integer "hundred-thousandths of a percent" (0.00001%)
#: before comparing, which tolerates harmless IEEE-754 round-trip noise
#: (e.g. a 4.00% coupon coming back as 0.0399999999) but will NOT collapse
#: 3.999% onto 4.000%.
_MAC_COUPON_SCALE = 10_000_000  # rate * 10^7  (7 decimals on the decimal
#                                 fraction = 5 decimals on the percentage)


def _coupon_scaled(rate: float) -> Optional[int]:
    """Scale a decimal-fraction rate (0.04 == 4%) to an integer key for
    exact-match MAC coupon comparison. Returns None on NaN."""
    if rate is None or (isinstance(rate, float) and pd.isna(rate)):
        return None
    try:
        return int(round(float(rate) * _MAC_COUPON_SCALE))
    except (TypeError, ValueError):
        return None


def detect_mac_swaps(package_df: pd.DataFrame) -> pd.DataFrame:
    out = package_df.copy()

    out["_mac_eff"] = pd.to_datetime(out.get("effective_date"), errors="coerce").dt.normalize()
    out["_mac_exp"] = pd.to_datetime(out.get("expiration_date"), errors="coerce").dt.normalize()
    out["_fixed_rate"] = pd.to_numeric(out.get("fixed_rate"), errors="coerce")
    # EXACT coupon match only (no bp-tolerance). See _MAC_COUPON_SCALE
    # comment for the precision rationale.
    out["_fixed_rate_key"] = out["_fixed_rate"].map(_coupon_scaled).astype("Int64")

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
        return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_key"], errors="ignore")

    mac_lookup = pd.concat(mac_lookup_frames, ignore_index=True)
    mac_lookup = mac_lookup.dropna(subset=["imm_start_date", "expiration_date", "coupon"]).copy()

    mac_lookup["_mac_eff"] = pd.to_datetime(mac_lookup["imm_start_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_exp"] = pd.to_datetime(mac_lookup["expiration_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_coupon"] = pd.to_numeric(mac_lookup["coupon"], errors="coerce") / 100.0
    mac_lookup["_mac_coupon_key"] = mac_lookup["_mac_coupon"].map(_coupon_scaled).astype("Int64")

    mac_lookup = mac_lookup[["_mac_eff", "_mac_exp", "_mac_coupon_key"]].drop_duplicates()

    tol_days = 5
    exp_lists = mac_lookup.groupby(["_mac_eff", "_mac_coupon_key"])["_mac_exp"].apply(
        lambda s: tuple(pd.Series(s).dropna().unique())
    ).to_dict()

    def _row_is_mac(eff, exp, coupon_key) -> bool:
        if pd.isna(eff) or pd.isna(exp) or pd.isna(coupon_key):
            return False
        exps = exp_lists.get((eff, int(coupon_key)))
        if not exps:
            return False
        exp = pd.Timestamp(exp)
        for mexp in exps:
            if abs((exp - pd.Timestamp(mexp)).days) <= tol_days:
                return True
        return False

    out["is_mac"] = [
        _row_is_mac(eff, exp, cpn)
        for eff, exp, cpn in tqdm(
            zip(out["_mac_eff"].values, out["_mac_exp"].values, out["_fixed_rate_key"].values),
            total=len(out),
            desc="Detecting MAC swaps",
            leave=False,
        )
    ]

    return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_key"], errors="ignore")


#: Upper bound on a plausible swap-vs-UST spreadover in decimal rate terms.
#: ``0.01`` = 1% = 100 bps. Any CFTC-reported spread above this is a scale
#: error or a non-spread field leaking into the column; real USD spreadovers
#: rarely exceed -80 bps in magnitude even on the long end.
_SPREADOVER_SPREAD_ABS_CEILING: float = 0.01

#: Percent-scale band. Some venues mis-report the spread in PERCENT rather than
#: decimal (e.g. ``-0.422`` meaning ``-42.2 bps`` instead of ``-0.00422``). A
#: magnitude clearly outside the decimal band but within ``[0.10, 1.0]`` (=10-100
#: bps once ÷100) is a percent-scaled spreadover. The gap ``(0.01, 0.10)`` is
#: left rejected — a value there (e.g. ``0.015`` = 150 bps decimal) reads as a
#: mis-scaled decimal, not a plausible spread on either interpretation.
_SPREADOVER_PERCENT_LO: float = 0.10
_SPREADOVER_PERCENT_HI: float = 1.0

#: Spreadovers only trade at benchmark tenors. A trade at e.g. 8Y or
#: 4Y with a spread is not a spreadover — it's a misparse or a
#: matched-maturity swap. Tolerance ±0.1y around each benchmark.
_SPREADOVER_VALID_TENORS: tuple[float, ...] = (2, 3, 5, 7, 10, 20, 30)


#: Spread magnitude band for SPREADOVER qualification at the per-leg
#: level. Mirrors the tight gate in ``detect_spreadovers`` — a leg only
#: counts as spreadover-eligible if its package_transaction_spread is a
#: genuine basis-point spread (non-zero, within 100 bps).
_SPREADOVER_LEG_SPREAD_CEILING: float = 0.01


def detect_sub_package_curve_fly(
    package_df: pd.DataFrame,
    *,
    # Accept detector_kwargs for forward-compat but ignore — this post-
    # pass doesn't re-run detectors.
    detector_kwargs: dict | None = None,  # noqa: ARG001
) -> pd.DataFrame:
    """Upgrade existing CURVE / FLY packages to composite package types
    when ALL legs individually qualify as MATCHED_MATURITY or SPREADOVER.

    Runs AFTER the primary ``detect_curve`` / ``detect_fly`` pass so any
    curve- or fly-shaped pair that was already matched stays paired. The
    composite labelling captures the economic intent for downstream
    consumers (e.g. the desk PKG filter):

    * A curve whose two legs each mature on a UST coupon  -> MATCHED_MATURITY_CURVE
    * A curve whose two legs each carry a broker spread    -> SPREADOVER_CURVE
    * Same logic for FLY.

    When both criteria apply to every leg, SPREADOVER wins (more
    specific — a broker-reported spread implies a UST cash leg, which
    matched-maturity only infers).

    No re-detection: the existing CURVE / FLY package_id + package_legs
    are preserved.
    """
    out = package_df.copy()
    if "package_type" not in out.columns:
        return out

    # Only CURVE / FLY packages are candidates for Phase 1 upgrade.
    # Composite types ("..._CURVE", "..._FLY") are NOT re-upgraded.
    base = out["package_type"].astype(str).str.upper()
    curvey_mask = (base == "CURVE") | (base == "FLY")
    has_pkg_id = "package_id" in out.columns

    _skip_phase1 = not bool(curvey_mask.any()) or not has_pkg_id

    # Walk each CURVE / FLY package_id group (Phase 1).
    if not _skip_phase1:
        leg_mms = (
            out["matched_ust_maturity"].astype(str).str.lower().isin({"true", "t", "1"})
            if "matched_ust_maturity" in out.columns
            else pd.Series(False, index=out.index)
        )

        spread_num = pd.to_numeric(
            out.get("package_transaction_spread"), errors="coerce"
        )
        pkg_ind = out.get("package_indicator")
        if pkg_ind is None:
            pkg_ind = pd.Series(False, index=out.index)
        pkg_ind_bool = pkg_ind.astype(str).str.lower().isin({"true", "t", "1"})
        fwd = out.get("forward_label")
        if fwd is None:
            fwd_spot = pd.Series(True, index=out.index)
        else:
            fwd_spot = fwd.astype(str).str.lower().eq("spot")

        leg_spreadover = (
            pkg_ind_bool
            & spread_num.notna()
            & (spread_num != 0)
            & (spread_num.abs() <= _SPREADOVER_LEG_SPREAD_CEILING)
            & fwd_spot
        )

    if not _skip_phase1:
        for pkg_id, group_idx in out.loc[curvey_mask].groupby("package_id").groups.items():
            if pkg_id is None or (isinstance(pkg_id, float) and pd.isna(pkg_id)):
                continue
            idx = list(group_idx)
            if not idx:
                continue
            base_type = str(out.loc[idx[0], "package_type"]).upper()
            all_mms = bool(leg_mms.loc[idx].all())
            all_spreadover = bool(leg_spreadover.loc[idx].all())

            if all_spreadover:
                new_type = f"SPREADOVER_{base_type}"
            elif all_mms:
                new_type = f"MATCHED_MATURITY_{base_type}"
            else:
                continue

            out.loc[idx, "package_type"] = new_type
            if "trade_type" in out.columns:
                out.loc[idx, "trade_type"] = new_type

    # --- Phase 2: pair un-paired SPREADOVER trades into SPREADOVER_CURVE/FLY ---
    # Trades tagged SPREADOVER by detect_spreadovers() but not yet paired
    # by any detector (package_legs is NaN). Group by (PTS, exec timestamp
    # rounded to 2min, platform) — matching PTS is the strongest signal
    # that two spreadovers are legs of the same package.
    _so_base = out["package_type"].astype(str).str.upper()
    _so_mask = (
        (_so_base == "SPREADOVER")
        & (out.get("package_legs", pd.Series(dtype="object")).isna())
    )
    if _so_mask.any():
        _so = out.loc[_so_mask].copy()
        _so_spread = pd.to_numeric(
            _so.get("package_transaction_spread"), errors="coerce"
        )
        _so_ts = pd.to_datetime(_so.get("execution_timestamp"), errors="coerce", utc=True)
        _so_ts_bin = _so_ts.dt.floor("2min")
        _so_plat = _so.get("platform_identifier", pd.Series("", index=_so.index)).fillna("")
        _so["_grp"] = (
            _so_spread.round(8).astype(str)
            + "|" + _so_ts_bin.astype(str)
            + "|" + _so_plat.astype(str)
        )
        _paired = 0
        for _gk, _gidx in _so.groupby("_grp").groups.items():
            _gidx = list(_gidx)
            if len(_gidx) < 2:
                continue
            # A spreadover curve/fly needs DISTINCT benchmark tenors. Two
            # (or three) same-tenor spreadovers at the same spread are
            # separate asset-swap prints, not legs of one structure —
            # pairing them produced bogus "30Y/30Y CURVE" / "10Y/10Y/10Y
            # FLY" rows on the tape.
            _tenor_buckets = pd.to_numeric(
                out.loc[_gidx, "tenor_years"], errors="coerce"
            ).round(1)
            if _tenor_buckets.nunique(dropna=True) < len(_gidx):
                continue
            _g = out.loc[_gidx].sort_values("tenor_years")
            _tids = _g["trade_id"].astype(str).tolist()
            _pkg_id = f"SOCRV_{_tids[0]}"
            if len(_gidx) == 2:
                _new_type = "SPREADOVER_CURVE"
            elif len(_gidx) == 3:
                _new_type = "SPREADOVER_FLY"
            else:
                _new_type = "SPREADOVER_CURVE"
            out.loc[_gidx, "package_type"] = _new_type
            out.loc[_gidx, "package_id"] = _pkg_id
            for _ix in _gidx:
                out.at[_ix, "package_legs"] = _tids
            if "trade_type" in out.columns:
                out.loc[_gidx, "trade_type"] = _new_type
            _paired += len(_gidx)
        if _paired:
            print(f"    [DETECT] Paired {_paired} SPREADOVER trades into composite packages")

    return out


# Residual-group plausibility guard. UPI is tenor-agnostic for OIS, so the
# (second, platform, UPI) key alone merges unrelated same-second flow. Only
# accept a group as one package when it looks like a structure rather than
# coincidental co-execution or a block-split.
_RESID_MAX_TENOR_SPAN_Y = 8.0
_RESID_DV01_DOMINANCE_TOL = 0.25


def _residual_group_is_plausible(
    tenor_years: list, dv01s: list
) -> bool:
    """True when a co-executed residual group plausibly IS one package.

    Guards against the (second, platform, UPI)-key over-grouping:

    * **Duplicate tenor** among legs → a block-split (e.g. 30Y/30Y/30Y), not
      a multi-leg structure. Reject.
    * **Wide tenor span** (> ~8y) is only accepted when the legs are
      **DV01-balanced** — no single leg's |DV01| dominates the rest, i.e. the
      package is roughly hedge-able. A lopsided wide group (one dominant leg
      + unrelated tails) is coincidental flow. Reject.
    * Narrow-span groups with distinct tenors (adjacent-benchmark curves the
      shape detectors missed) are accepted.
    """
    tys = [float(t) for t in tenor_years if t is not None and not pd.isna(t)]
    if len(tys) < 2:
        return False
    rounded = [round(t, 1) for t in tys]
    if len(set(rounded)) < len(rounded):
        return False  # duplicate tenor -> block-split, not a structure
    if (max(tys) - min(tys)) <= _RESID_MAX_TENOR_SPAN_Y:
        return True
    # Wide span: require DV01 balance (largest leg offset-able by the rest).
    rs = [abs(float(r)) for r in dv01s if r is not None and not pd.isna(r)]
    if len(rs) < 2:
        return False  # no DV01 evidence for a wide span -> don't group
    mx = max(rs)
    rest = sum(rs) - mx
    return mx <= rest * (1.0 + _RESID_DV01_DOMINANCE_TOL)


def group_residual_package_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Group co-executed SDR-package legs that no detector paired.

    SDR packages whose ``Package transaction price`` is unusable (missing,
    zero, or non-monetary notation) never reach the PTP grouper, and legs
    that fail the curve/fly DV01 shape tests are left behind as single-leg
    "Package" rows. When several such legs share the same execution second,
    platform, and UPI AND form a plausible structure
    (:func:`_residual_group_is_plausible`), they were executed as one package
    — group them into PKG-N so the tape shows one structure instead of N
    orphan rows.

    Spreadover and invoice legs are excluded: same-tenor spreadovers are
    intentionally separate prints, and invoice swaps have their own pairing.
    Block-splits (duplicate tenor) and lopsided wide-span groups are left as
    separate rows — the co-execution key is too coarse to call them packages.
    """
    if df.empty or "package_type" not in df.columns or "trade_id" not in df.columns:
        return df
    out = df.copy()

    pkg_ind = out.get("package_indicator")
    if pkg_ind is None:
        return out
    pkg_ind_bool = pkg_ind.astype(str).str.lower().isin({"true", "t", "1", "1.0", "yes"})

    base_type = out["package_type"].fillna("OUTRIGHT").astype(str).str.upper()
    legs_col = out.get("package_legs", pd.Series(index=out.index, dtype="object"))
    unpaired = legs_col.apply(
        lambda v: v is None
        or (isinstance(v, float) and pd.isna(v))
        or (isinstance(v, (list, tuple)) and len(v) <= 1)
    )

    invoice_col = out.get("invoice_swap_ticker", pd.Series(index=out.index, dtype="object"))
    no_invoice = invoice_col.isna() | (
        invoice_col.astype(str).str.strip().str.lower().isin({"", "nan", "none"})
    )

    ts = pd.to_datetime(out.get("execution_timestamp"), errors="coerce", utc=True)

    eligible = (
        pkg_ind_bool
        & unpaired
        & base_type.isin({"OUTRIGHT", "MATCHED_MATURITY"})
        & no_invoice
        & ts.notna()
    )
    if not eligible.any():
        return out

    plat = out.get("platform_identifier", pd.Series("", index=out.index)).fillna("_NONE_").astype(str)
    upi = out.get("unique_product_identifier", pd.Series("", index=out.index)).fillna("_NONE_").astype(str)
    grp_key = (
        ts.dt.floor("s").astype(str) + "|" + plat + "|" + upi
    )[eligible]

    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None

    _dv01_col = "estimated_pv01" if "estimated_pv01" in out.columns else "risk"
    n_grouped = 0
    n_skipped = 0
    for _key, gidx in grp_key.groupby(grp_key).groups.items():
        gidx = list(gidx)
        if len(gidx) < 2:
            continue
        _tys = pd.to_numeric(out.loc[gidx, "tenor_years"], errors="coerce").tolist()
        _dv = (
            pd.to_numeric(out.loc[gidx, _dv01_col], errors="coerce").tolist()
            if _dv01_col in out.columns else [None] * len(gidx)
        )
        if not _residual_group_is_plausible(_tys, _dv):
            n_skipped += len(gidx)
            continue
        tids = sorted(out.loc[gidx, "trade_id"].astype(str).tolist())
        out.loc[gidx, "package_type"] = f"PKG-{len(gidx)}"
        out.loc[gidx, "package_id"] = f"TSPKG_{tids[0]}"
        for ix in gidx:
            out.at[ix, "package_legs"] = tids
        n_grouped += len(gidx)
    if n_grouped or n_skipped:
        print(
            f"    [DETECT] Grouped {n_grouped} residual package legs by "
            f"timestamp ({n_skipped} left ungrouped by plausibility guard)"
        )
    return out


def _rollup_matched_maturity_packages(df: pd.DataFrame) -> pd.DataFrame:
    """Full-scope, idempotent package-level matched-maturity rollup.

    Runs post-concat over the whole (PTP + non-PTP) frame. For every
    package_id whose legs are ALL matched_ust_maturity, promote a base
    CURVE/FLY to MATCHED_MATURITY_CURVE/_FLY. PKG-N keeps its type (the
    package-level MMS signal surfaces via per-leg special_tenor_type at
    ingest). Already-composite / SPREADOVER_* / INVOICE* / BASIS_* packages
    are skipped so SPREADOVER-wins and INVOICE-wins precedence hold. Idempotent:
    a no-op over anything detect_sub_package_curve_fly already promoted.
    """
    if df.empty or "package_id" not in df.columns or "package_type" not in df.columns:
        return df
    out = df.copy()
    if "matched_ust_maturity" not in out.columns:
        return out
    leg_mms = out["matched_ust_maturity"].astype(str).str.lower().isin({"true", "t", "1"})
    base = out["package_type"].astype(str).str.upper()
    promotable = base.isin({"CURVE", "FLY"}) & out["package_id"].notna()
    if not promotable.any():
        return out
    for pkg_id, group_idx in out.loc[promotable].groupby("package_id").groups.items():
        idx = list(group_idx)
        if len(idx) < 2:
            continue
        if not bool(leg_mms.loc[idx].all()):
            continue
        base_type = str(out.loc[idx[0], "package_type"]).upper()
        new_type = f"MATCHED_MATURITY_{base_type}"
        out.loc[idx, "package_type"] = new_type
        if "trade_type" in out.columns:
            out.loc[idx, "trade_type"] = new_type
    return out


def detect_spreadovers(package_df: pd.DataFrame):
    """Detect broker-reported swap-vs-UST spreadovers.

    Tight gate — all conditions must hold:

    * ``package_legs`` is NaN (not already paired by curve/fly/basis detectors)
    * ``package_indicator == True`` (CFTC package flag)
    * ``forward_label == "spot"``
    * ``package_transaction_spread`` coerces to a non-zero float
    * ``|package_transaction_spread| <= 0.01`` (100 bps; rejects reporting errors)
    * ``invoice_swap_ticker`` is empty (mutual exclusion — invoice swaps also
      carry ``package_indicator=True`` but belong to their own bucket)

    The previous gate flagged any row with a non-null spread, which pulled
    in exact-zero routing tags, orders of magnitude scale-error outliers,
    and invoice-swap rows. The tight version reduces false positives
    without depending on matched-maturity signals (spreadovers are DV01-
    matched hedges; the IRS maturity typically does NOT land on a UST
    coupon date, so ``matched_ust_maturity`` is orthogonal).
    """
    from SDRUtils.core.parsing import mask_sentinels, parse_notation_scalar

    copy_df = package_df.copy()

    # B4 — apply notation code ([#105]: 1=monetary, 3=decimal, 4=bps) BEFORE
    # comparing to the bps-ceiling gate. Also mask the 9.9999999999 "unknown"
    # sentinel (B5) so it does not parade as a real wide spread.
    raw_spread = pd.to_numeric(
        copy_df.get("package_transaction_spread"), errors="coerce"
    )
    raw_spread = mask_sentinels(raw_spread, "spread_decimal")
    notation_col = copy_df.get(
        "package_transaction_spread_notation",
        pd.Series([None] * len(copy_df), index=copy_df.index),
    )
    spread_num = pd.Series(
        [parse_notation_scalar(v, n) for v, n in zip(raw_spread, notation_col)],
        index=copy_df.index,
        dtype="float64",
    )
    invoice_ticker_col = copy_df.get(
        "invoice_swap_ticker", pd.Series([None] * len(copy_df), index=copy_df.index)
    )
    has_invoice_ticker = (
        invoice_ticker_col.notna()
        & (invoice_ticker_col.astype(str).str.strip() != "")
        & (invoice_ticker_col.astype(str).str.strip().str.lower() != "nan")
    )

    tenor_y = pd.to_numeric(
        copy_df.get("tenor_years", pd.Series([None] * len(copy_df), index=copy_df.index)),
        errors="coerce",
    )
    is_spreadover_tenor = pd.Series(False, index=copy_df.index)
    for std_t in _SPREADOVER_VALID_TENORS:
        is_spreadover_tenor |= (tenor_y - std_t).abs() <= 0.1
    package_legs_col = copy_df.get(
        "package_legs", pd.Series([None] * len(copy_df), index=copy_df.index)
    )
    package_ind_col = copy_df.get(
        "package_indicator", pd.Series([False] * len(copy_df), index=copy_df.index)
    )
    forward_label_col = copy_df.get(
        "forward_label", pd.Series(["spot"] * len(copy_df), index=copy_df.index)
    )
    _abs_spread = spread_num.abs()
    _in_spread_band = (_abs_spread <= _SPREADOVER_SPREAD_ABS_CEILING) | (
        (_abs_spread >= _SPREADOVER_PERCENT_LO) & (_abs_spread <= _SPREADOVER_PERCENT_HI)
    )
    broker_spreadover_mask = (
        (package_legs_col.isna())
        & (package_ind_col == True)
        & (forward_label_col == "spot")
        & spread_num.notna()
        & (spread_num != 0)
        & _in_spread_band
        & (~has_invoice_ticker)
        & is_spreadover_tenor
    )
    copy_df["is_spreadover"] = False
    copy_df.loc[broker_spreadover_mask, "is_spreadover"] = True
    # PKG flag: surface SPREADOVER in the package_type column so the
    # dashboard PKG bucket groups them alongside CURVE/FLY/INVOICE/OUTRIGHT.
    if "package_type" not in copy_df.columns:
        copy_df["package_type"] = "OUTRIGHT"
    copy_df.loc[broker_spreadover_mask, "package_type"] = "SPREADOVER"

    asset_swap_mask = (
        broker_spreadover_mask
        & (copy_df.get("other_payment_type") == "UFRO")
    )
    copy_df["is_asset_swap"] = False
    copy_df.loc[asset_swap_mask, "is_asset_swap"] = True

    return copy_df


def detect_invoice_packages(
    package_df: pd.DataFrame,
    *,
    time_window_seconds: int = 120,
    pv01_tolerance: float = 0.20,
) -> pd.DataFrame:
    """Detect INVOICE_CALENDAR and INVOICE_SWITCH multi-leg packages.

    Runs after detect_invoice_swaps has tagged individual trades.

    INVOICE_CALENDAR: same futures root, different contract months (roll trade).
    INVOICE_SWITCH: different futures roots, same contract month (tenor switch).

    Per CME spec, calendar spreads roll invoice exposure in a given tenor from
    one contract month to the next; switch spreads combine invoice exposure
    across Treasury curve points within the same contract month.
    """
    out = package_df.copy()

    if "invoice_swap_root" not in out.columns or "invoice_swap_contract" not in out.columns:
        return out

    is_invoice = out.get("package_type", pd.Series(dtype=str)).astype(str).str.upper() == "INVOICE"
    not_paired = out.get("package_legs", pd.Series(dtype=object)).isna()
    pv01_vals = pd.to_numeric(out.get("estimated_pv01"), errors="coerce").fillna(0)
    has_pv01 = pv01_vals > 0

    cand_mask = is_invoice & not_paired & has_pv01
    if cand_mask.sum() < 2:
        return out

    cand = out.loc[cand_mask].copy()
    cand["_ts"] = pd.to_datetime(cand["execution_timestamp"], errors="coerce", utc=True)
    cand = cand.sort_values("_ts", kind="mergesort")

    def _contract_month(root, contract):
        c, r = str(contract).upper(), str(root).upper()
        return c[len(r):] if c.startswith(r) else c

    cand["_contract_month"] = [
        _contract_month(r, c)
        for r, c in zip(cand["invoice_swap_root"], cand["invoice_swap_contract"])
    ]

    indices = cand.index.tolist()
    n = len(indices)
    matched: set = set()
    td_window = pd.Timedelta(seconds=time_window_seconds)

    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None

    pkg_counter = 0

    for ii in range(n):
        idx_i = indices[ii]
        if idx_i in matched:
            continue

        ts_i = cand.at[idx_i, "_ts"]
        pv01_i = float(pv01_vals.at[idx_i])
        root_i = str(cand.at[idx_i, "invoice_swap_root"])
        contract_i = str(cand.at[idx_i, "invoice_swap_contract"])
        month_i = cand.at[idx_i, "_contract_month"]
        plat_i = str(cand.at[idx_i, "platform_identifier"]) if "platform_identifier" in cand.columns else ""
        clr_i = str(cand.at[idx_i, "cleared"]) if "cleared" in cand.columns else ""
        tid_i = str(cand.at[idx_i, "trade_id"])

        best_j = None
        best_type: Optional[str] = None
        best_rel = 1e9

        for jj in range(ii + 1, n):
            idx_j = indices[jj]
            if idx_j in matched:
                continue

            ts_j = cand.at[idx_j, "_ts"]
            if (ts_j - ts_i) > td_window:
                break

            if "platform_identifier" in cand.columns and plat_i != str(cand.at[idx_j, "platform_identifier"]):
                continue
            if "cleared" in cand.columns and clr_i != str(cand.at[idx_j, "cleared"]):
                continue

            pv01_j = float(pv01_vals.at[idx_j])
            avg = 0.5 * (pv01_i + pv01_j)
            if avg <= 0:
                continue
            rel = abs(pv01_i - pv01_j) / avg
            if rel > pv01_tolerance:
                continue

            root_j = str(cand.at[idx_j, "invoice_swap_root"])
            contract_j = str(cand.at[idx_j, "invoice_swap_contract"])
            month_j = cand.at[idx_j, "_contract_month"]

            pkg_type: Optional[str] = None
            if root_i == root_j and contract_i != contract_j:
                pkg_type = "INVOICE_CALENDAR"
            elif root_i != root_j and month_i == month_j:
                pkg_type = "INVOICE_SWITCH"

            if pkg_type is not None and rel < best_rel:
                best_j = idx_j
                best_type = pkg_type
                best_rel = rel

        if best_j is not None and best_type is not None:
            matched.add(idx_i)
            matched.add(best_j)
            pkg_counter += 1
            tid_j = str(cand.at[best_j, "trade_id"])
            legs = sorted([tid_i, tid_j])
            pid = f"{best_type}_{pkg_counter}_{min(legs)}"

            for idx in (idx_i, best_j):
                out.at[idx, "package_type"] = best_type
                out.at[idx, "package_id"] = pid
                out.at[idx, "package_legs"] = legs
                if "trade_type" in out.columns:
                    out.at[idx, "trade_type"] = best_type

    return out


def _coerce_numeric_like(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    normalized = (
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    normalized = normalized.where(~normalized.isin(["", "None", "none", "nan", "NaN"]), other=pd.NA)
    return pd.to_numeric(normalized, errors="coerce")


def _is_round_notional(notional: float, threshold: float = 5_000_000) -> bool:
    """True if notional is a 'round' number (divisible by threshold with no remainder)."""
    if pd.isna(notional) or notional <= 0:
        return False
    return (notional % threshold) == 0


def _expand_hood_for_ptp_keys(
    df: pd.DataFrame,
    hood_mask: pd.Series,
    *,
    tolerance_seconds: int = 5,
) -> pd.Series:
    """Widen a neighborhood mask so PTP/PTS groups are never split.

    Incremental cycles re-detect only trades near new prints; a package
    group straddling the window edge would otherwise be re-grouped from a
    subset of its legs while the cached remainder keeps the old package_id.
    Any out-of-window candidate sharing the exact grouping key with an
    in-window candidate, within the group time tolerance of the window, is
    pulled in.

    The key mirrors ``group_by_ptp`` exactly: package price (any non-zero
    sign) when usable, else sentinel-masked package spread, plus platform.
    UPI is NOT part of the key — the grouper deliberately excludes it
    because multi-tenor/multi-forward packages carry different UPIs per
    leg, so keying the hood on UPI would split exactly those groups.
    """
    from SDRUtils.core.parsing import mask_sentinels
    from SDRUtils.packages.ptp_grouper import numeric_like

    ptp = numeric_like(df.get("package_transaction_price",
                              pd.Series(index=df.index, dtype=object)))
    pts = mask_sentinels(
        numeric_like(df.get("package_transaction_spread",
                            pd.Series(index=df.index, dtype=object))),
        "spread_decimal",
    )
    ind = (
        df.get("package_indicator", pd.Series(False, index=df.index))
        .astype(str).str.lower().isin({"true", "t", "1", "1.0", "yes"})
    )
    ts = pd.to_datetime(
        df.get("execution_timestamp", pd.Series(pd.NaT, index=df.index)),
        errors="coerce", utc=True,
    )
    ptp_usable = ptp.notna() & (ptp != 0)
    pts_usable = pts.notna() & (pts != 0)
    cand = ind & (ptp_usable | pts_usable) & ts.notna()
    hood_cand = hood_mask & cand
    if not hood_cand.any():
        return hood_mask

    plat = df.get("platform_identifier", pd.Series("", index=df.index)).astype(str)
    val_key = ("P:" + ptp.astype(str)).where(ptp_usable.to_numpy(), "S:" + pts.astype(str))
    key = val_key + "|" + plat

    in_keys = set(key[hood_cand])
    lo = ts[hood_cand].min() - pd.Timedelta(seconds=tolerance_seconds)
    hi = ts[hood_cand].max() + pd.Timedelta(seconds=tolerance_seconds)
    pulled = cand & key.isin(in_keys) & ts.between(lo, hi)
    return hood_mask | pulled


def _resolve_special_tenor_priority(df: pd.DataFrame) -> pd.DataFrame:
    """
    After all detectors have run, resolve unified special_tenor fields.

    Reads existing detection columns (matched_ust_maturity, invoice_swap_ticker,
    is_mac) and merges them with Phase 1 intrinsic tags. Applies priority
    hierarchy and round-notional confidence adjustment.

    Priority (lowest to highest):
        STANDARD < IMM < FOMC < MAC < MATCHED_MATURITY < INVOICE_SWAP
    """
    from SDRUtils.config import SPECIAL_TENOR_PRIORITY

    out = df.copy()

    if out.empty:
        return out

    priority_map = {t: i for i, t in enumerate(SPECIAL_TENOR_PRIORITY)}

    def _parse_tags(val) -> list[str]:
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    return []
                return [t.strip().strip("'\"") for t in inner.split(",")]
            return [val] if val else []
        return []

    def _resolve_row(row):
        tags = list(_parse_tags(row.get("special_tenor_tags", [])))
        intrinsic_type = str(row.get("special_tenor_type", "STANDARD"))

        # Collect Phase 2 detections
        if row.get("matched_ust_maturity") is True or str(row.get("matched_ust_maturity")).lower() == "true":
            if "MATCHED_MATURITY" not in tags:
                tags.append("MATCHED_MATURITY")

        if pd.notna(row.get("invoice_swap_ticker")) and str(row.get("invoice_swap_ticker")).strip():
            if "INVOICE_SWAP" not in tags:
                tags.append("INVOICE_SWAP")

        if row.get("is_mac") is True or str(row.get("is_mac")).lower() == "true":
            if "MAC" not in tags:
                tags.append("MAC")

        # Determine primary type by priority
        if not tags:
            return "STANDARD", "high", []

        primary = max(tags, key=lambda t: priority_map.get(t, -1))

        # Confidence scoring for MATCHED_MATURITY
        conf = "high"
        if primary in ("MATCHED_MATURITY", "INVOICE_SWAP"):
            fwd = str(row.get("forward_label", "spot")).strip().lower()
            is_spot = fwd == "spot"
            notional = pd.to_numeric(row.get("notional"), errors="coerce")
            tenor_y = pd.to_numeric(row.get("tenor_years"), errors="coerce")

            if pd.notna(tenor_y) and tenor_y < 1.0:
                conf = "low"
            elif is_spot:
                if _is_round_notional(notional if pd.notna(notional) else 0):
                    conf = "low"
                else:
                    conf = "medium"
            # Forward-starting or invoice: keep "high"

        return primary, conf, tags

    results = out.apply(_resolve_row, axis=1, result_type="expand")
    results.columns = ["special_tenor_type", "special_tenor_confidence", "special_tenor_tags"]
    out["special_tenor_type"] = results["special_tenor_type"]
    out["special_tenor_confidence"] = results["special_tenor_confidence"]
    out["special_tenor_tags"] = results["special_tenor_tags"]

    return out


def _prepare_cache_dataframe_for_arrow(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_columns = [
        "notional",
        "tenor_years",
        "forward_start_years",
        "fixed_rate",
        "estimated_pv01",
        "package_transaction_spread",
        "package_transaction_price",
        "other_payment_amount",
    ]
    for col in numeric_columns:
        if col in out.columns:
            out[col] = _coerce_numeric_like(out[col])
    for col in ("invoice_swap_contract", "invoice_swap_root"):
        if col in out.columns:
            out[col] = out[col].where(out[col].notna(), other=None).astype("object")
    return out


def _risk_from_estimated_pv01(value: Any) -> float:
    try:
        if isinstance(value, str):
            return float(value.split("/")[0])
        return float(value)
    except Exception:
        return float("nan")


def _classify_messages_v2(
    messages: pd.DataFrame,
    exec_date=None,
    curve_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    **kwargs,
):
    """
    V2 classification: routes trades through SOFR/FF/basis classifiers.
    All segments use the MEDIUM curve (ERIS_EOD_LIVE-RL_BASIC) for PV01.
    """
    import logging

    logger = logging.getLogger(__name__)

    filtered = messages[
        (messages["Action type"] == "NEWT") & (messages["Event type"] == "TRAD")
    ].copy()

    if filtered.empty:
        return []

    # Lazy-load curves per segment (only when needed)
    _curves = {}

    def _get_curve(segment_key: str):
        if segment_key not in _curves:
            try:
                src = kwargs.get("medium_curve_source", curve_source)
                mdp = IRSwapsMDP(source=src)
                cn = "USD-SOFR-1D"
                _curves[segment_key] = mdp.get_pricer(dict(
                    curve_name=cn, timestamp=exec_date,
                ))
            except Exception as e:
                logger.warning(f"Failed to load {segment_key} curve: {e}")
                _curves[segment_key] = None
        return _curves[segment_key]

    classifications = []

    for _, row in tqdm(filtered.iterrows(), desc="V2 Classifying", unit="trade", total=len(filtered)):
        trade_id = row.get(TRADE_ID)
        try:
            upi = classify_rate_index(
                row.get("UPI Underlier Name"),
                row.get("UPI FISN"),
            )

            if upi.product_type == LinearProductType.BASIS:
                c = classify_basis_swap_trade(row, trade_id=trade_id)
            elif upi.rate_index is not None and "FED_FUNDS" in upi.rate_index.value:
                c = classify_fed_funds_ois_trade(row, trade_id=trade_id)
            elif upi.rate_index is not None:
                c = classify_sofr_ois_trade(row, trade_id=trade_id)
            else:
                # Fallback to V1 classifier
                curve = _get_curve("MEDIUM")
                c = classify_usd_swap_trade(row, trade_id=trade_id, curve=curve)

            curve = _get_curve("MEDIUM")

            if curve is not None and c.estimated_pv01 is None:
                try:
                    pkg, _ = IRSwapQuery(
                        curve="USD-SOFR-1D",
                        effective_date=c.effective_date.date() if hasattr(c.effective_date, 'date') else c.effective_date,
                        maturity_date=c.expiration_date.date() if hasattr(c.expiration_date, 'date') else c.expiration_date,
                        structure_kwargs={"notional": c.notional or 1_000_000},
                    ).resolve_package(pricer_or_curve=curve)
                    if pkg:
                        c.estimated_pv01 = curve.pv01(pkg[0])
                except Exception:
                    pass

            classifications.append(c)
        except Exception as e:
            logger.error(f"V2 classification failed for {trade_id}: {e}")

    return classifications


class USD_SwapProduct(USDProductBase):
    """
    USD swap product implementation.

    This class implements the ProductModule interface for USD swaps,
    providing trade classification and product type inference.
    """

    name = "USD-SWAPS"
    product_type = PRODUCT_TYPES.OIS_SWAP

    def classify_trade(self, row: pd.Series, trade_id: int, curve: _IRSwapGenericCurve) -> SwapTradeClassification:
        """
        Classify a single USD swap trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments, including 'curve' for PV01

        Returns:
            SwapTradeClassification object
        """
        return classify_usd_swap_trade(
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
        detect_basis=True,
        ignore_cache: bool = False,
        merge_package_legs: bool = False,
        use_v2_classification: bool = False,
        return_raw: bool = False,
        use_incremental: bool = False,
        **kwargs: Any,
    ):
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=usd_swap_trades,
            ignore_cache=ignore_cache,
        )

        # When return_raw requested, grab unfiltered RATES data for cross-day
        # lifecycle resolution.  Lifecycle events (MODI, TERM, CORR) often lack
        # UPI metadata and would be dropped by the product filter.  The
        # unfiltered pass hits the same cached parquet slices — negligible cost.
        # Extend end by +1 day to capture follow-up events that arrive after
        # the user's end timestamp (e.g. TERM at 11:36 AM on end date).
        unfiltered_raw_df = pd.DataFrame()
        if return_raw:
            from datetime import timedelta as _td
            unfiltered_end = end + _td(days=1)
            unfiltered_raw_df = sdr.grab_sdr_trades(
                start_timestamp=start,
                end_timestamp=unfiltered_end,
                agency="CFTC",
                asset_class="RATES",
                ignore_cache=ignore_cache,
            )

        if raw_sdr_trades_df.empty:
            if return_raw:
                return pd.DataFrame(), unfiltered_raw_df
            return pd.DataFrame()

        # §43.3(a)(4), §43.5: Execution Timestamp is the event-study timing
        # anchor; Event timestamp lags by 15min–24 business hours for
        # post-priced and block trades. See audit finding B3.
        exec_dates = pd.to_datetime(raw_sdr_trades_df["Execution Timestamp"], errors="coerce").dt.date
        raw_sdr_trades_df = raw_sdr_trades_df.assign(_execution_date=exec_dates)

        curve_source = str(kwargs.get("curve_source", "ERIS_EOD_LIVE-RL_BASIC")).replace("/", "_")
        mdp = IRSwapsMDP(source=curve_source)

        # DETECTION_CACHE_VERSION: PTP pre-grouper + OPA sign solver added to _run_all_detectors.
        # Cached day frames from before that change lack ptp_group_id /
        # opa_* columns and carry different package assignments, so they
        # must miss. Bump the version on any future detector-output change.
        cache_flags = f"curve{int(detect_curve)}_fly{int(detect_fly)}_mms{int(detect_mms)}_invoice{int(detect_invoice)}_mac{int(detect_mac)}_spreadover{int(detect_spreadover)}_basis{int(detect_basis)}_{DETECTION_CACHE_VERSION}"
        cache_base = Path(cache_path) / "classification_cache" / "usd_swaps" / curve_source / cache_flags
        legacy_cache_base = Path(cache_path) / "classification_cache" / "usd_sofr_swaps" / curve_source / cache_flags
        cache_base.mkdir(parents=True, exist_ok=True)

        cached_frames = []
        missing_dates = []
        for exec_date, count in raw_sdr_trades_df["_execution_date"].value_counts().items():
            if pd.isna(exec_date):
                continue
            found_cache = False
            if ignore_cache is False:
                date_dirs = [
                    cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}",
                    legacy_cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}",
                ]
                for date_dir in date_dirs:
                    if not date_dir.exists():
                        continue
                    cache_candidates = []
                    for fp in date_dir.glob("*.parquet"):
                        if fp.stem.isdigit():
                            cache_candidates.append((int(fp.stem), fp))

                    if not cache_candidates:
                        continue
                    max_cached_count, best_cache_fp = max(cache_candidates, key=lambda x: x[0])
                    if max_cached_count >= count:
                        try:
                            cached_frames.append(pd.read_parquet(best_cache_fp, engine="pyarrow"))
                            found_cache = True
                            break
                        except Exception:
                            best_cache_fp.unlink(missing_ok=True)

            if not found_cache:
                missing_dates.append(exec_date)

        if not missing_dates:
            if cached_frames:
                final_df = pd.concat(cached_frames, ignore_index=True)
                final_df = final_df[(final_df["execution_timestamp"] >= start.astimezone(pytz.utc)) & (final_df["execution_timestamp"] <= end.astimezone(pytz.utc))]
                if merge_package_legs:
                    final_df = merge_package_legs_to_one_row(final_df)
                final_df["risk"] = final_df["estimated_pv01"].apply(_risk_from_estimated_pv01)
                final_df["risk"] = (final_df["risk"] / 100).round().mul(100)
                if return_raw:
                    return final_df, unfiltered_raw_df
                return final_df

            if return_raw:
                return pd.DataFrame(), unfiltered_raw_df
            return pd.DataFrame()

        built_frames = []
        for exec_date in missing_dates:
            try:
                # ignore dates falling outside of execution
                # consequence: will drop modifications
                if exec_date > end.date() or exec_date < start.date():
                    continue

                day_df = raw_sdr_trades_df[raw_sdr_trades_df["_execution_date"] == exec_date]

                # --- Incremental classification: reuse cached per-trade results ---
                all_trade_ids = set(day_df[TRADE_ID].astype(str))
                cached_ids = all_trade_ids & set(_TRADE_CLASSIFICATION_CACHE.keys()) if use_incremental else set()
                new_ids = all_trade_ids - cached_ids

                if use_incremental and not new_ids:
                    classifications_df = pd.DataFrame([
                        _TRADE_CLASSIFICATION_CACHE[tid]
                        for tid in day_df[TRADE_ID].astype(str)
                        if tid in _TRADE_CLASSIFICATION_CACHE
                    ])
                    print(f"  Incremental: {len(cached_ids)} cached, 0 new trades for {exec_date}")
                else:
                    if use_incremental and cached_ids:
                        classify_df = day_df[day_df[TRADE_ID].astype(str).isin(new_ids)]
                        print(f"  Incremental: {len(cached_ids)} cached, {len(new_ids)} new trades for {exec_date}")
                    else:
                        classify_df = day_df

                    if use_v2_classification:
                        classifications = _classify_messages_v2(
                            classify_df, exec_date=exec_date, curve_source=curve_source, **kwargs,
                        )
                    else:
                        classifications = self.classify_messages(
                            classify_df,
                            curve=mdp.get_pricer(dict(curve_name="USD-SOFR-1D", timestamp=exec_date)),
                        )
                    new_classifications_df = classifications_to_dataframe(classifications)

                    if not new_classifications_df.empty:
                        for _, row in new_classifications_df.iterrows():
                            _TRADE_CLASSIFICATION_CACHE[str(row["trade_id"])] = row.to_dict()

                    if use_incremental and cached_ids:
                        cached_rows = [
                            _TRADE_CLASSIFICATION_CACHE[tid]
                            for tid in day_df[TRADE_ID].astype(str)
                            if tid in _TRADE_CLASSIFICATION_CACHE
                        ]
                        classifications_df = pd.DataFrame(cached_rows) if cached_rows else new_classifications_df
                    else:
                        classifications_df = new_classifications_df
                if not classifications_df.empty:
                    classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
                    if "execution_timestamp" in classifications_df.columns:
                        classifications_df["execution_timestamp"] = pd.to_datetime(
                            classifications_df["execution_timestamp"], errors="coerce", utc=True
                        )
                    day_df = day_df.copy()
                    day_df[TRADE_ID] = day_df[TRADE_ID].astype("string")

                # --- Incremental fast-path: skip lifecycle + package detection ---
                # When no new NEWT/TRAD classifications were produced (only
                # lifecycle events arrived) and we have a cached packaged
                # result, reuse it directly. The per-trade classification
                # cache already has updated lifecycle columns from the
                # hourly full reclassify; the expensive O(n²) package
                # detection doesn't need to re-run.
                import time as _time

                _day_cache_key = str(exec_date)
                _ncdf = locals().get("new_classifications_df")
                _have_new_classifications = (
                    _ncdf is not None and not _ncdf.empty
                )
                if (
                    use_incremental
                    and not _have_new_classifications
                    and _day_cache_key in _PACKAGED_DAY_CACHE
                ):
                    package_df = _PACKAGED_DAY_CACHE[_day_cache_key]
                    print(
                        f"    [FAST] Reusing cached packaged result "
                        f"({len(package_df)} trades, no new NEWT/TRAD)"
                    )
                    package_df = _prepare_cache_dataframe_for_arrow(package_df)

                    count = len(day_df)
                    date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
                    date_dir.mkdir(parents=True, exist_ok=True)
                    cache_fp = date_dir / f"{count}.parquet"
                    tmp_fp = cache_fp.with_suffix(".parquet.tmp")
                    table = pa.Table.from_pandas(package_df, preserve_index=False)
                    pq.write_table(table, tmp_fp, compression="zstd")
                    tmp_fp.replace(cache_fp)

                    built_frames.append(package_df)
                    continue

                # --- Lifecycle V2 resolution (incremental) ---
                from SDRUtils.core.lifecycle import (
                    group_by_uti,
                    resolve_lifecycle_for_day,
                )

                _t_lc = _time.monotonic()
                _lc_key = str(exec_date)
                _lc_n_events = len(day_df)
                _lc_cached = _LIFECYCLE_DAY_CACHE.get(_lc_key)
                if (
                    use_incremental
                    and _lc_cached is not None
                    and _lc_cached[0] == _lc_n_events
                ):
                    lifecycle_df = _lc_cached[1]
                    print(
                        f"    [TIMING] Lifecycle resolution (cached): "
                        f"{_time.monotonic() - _t_lc:.3f}s "
                        f"({_lc_n_events} events, unchanged)"
                    )
                elif (
                    use_incremental
                    and _lc_cached is not None
                    and _lc_cached[0] < _lc_n_events
                ):
                    _old_n, _old_lc = _lc_cached
                    _old_dissem_ids = set(_old_lc.index.astype(str))
                    _all_dissem = day_df[
                        "Dissemination Identifier"
                    ].astype(str)
                    _new_dissem = set(_all_dissem) - _old_dissem_ids
                    if not _new_dissem:
                        lifecycle_df = resolve_lifecycle_for_day(day_df)
                    else:
                        _uti_groups = group_by_uti(day_df)
                        _affected_utis = {
                            uti
                            for uti, grp in _uti_groups.items()
                            if grp[
                                "Dissemination Identifier"
                            ].astype(str).isin(_new_dissem).any()
                        }
                        _affected_dissem_ids = set()
                        for uti in _affected_utis:
                            _affected_dissem_ids.update(
                                _uti_groups[uti][
                                    "Dissemination Identifier"
                                ].astype(str)
                            )
                        _affected_df = day_df[
                            _all_dissem.isin(_affected_dissem_ids)
                        ]
                        _new_lc = resolve_lifecycle_for_day(
                            _affected_df
                        )
                        _kept = _old_lc[
                            ~_old_lc.index.astype(str).isin(
                                set(_new_lc.index.astype(str))
                            )
                        ]
                        lifecycle_df = pd.concat(
                            [_kept, _new_lc]
                        )
                    _LIFECYCLE_DAY_CACHE[_lc_key] = (
                        _lc_n_events,
                        lifecycle_df,
                    )
                    _n_affected = _lc_n_events - _old_n
                    print(
                        f"    [TIMING] Lifecycle resolution "
                        f"(incremental): "
                        f"{_time.monotonic() - _t_lc:.1f}s "
                        f"({_n_affected} new / {_lc_n_events} total)"
                    )
                else:
                    lifecycle_df = resolve_lifecycle_for_day(day_df)
                    _LIFECYCLE_DAY_CACHE[_lc_key] = (_lc_n_events, lifecycle_df)
                    print(
                        f"    [TIMING] Lifecycle resolution: "
                        f"{_time.monotonic() - _t_lc:.1f}s "
                        f"({_lc_n_events} events)"
                    )
                if not lifecycle_df.empty and not classifications_df.empty:
                    lifecycle_df.index = lifecycle_df.index.astype("string")
                    classifications_df = classifications_df.merge(
                        lifecycle_df,
                        left_on=TRADE_ID,
                        right_index=True,
                        how="left",
                    )

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
                            "Package transaction spread notation",
                            "Package transaction price",
                            "Package transaction price notation",
                            "Event type",
                            "Non-standardized term indicator",
                        ]
                    ],
                    on=TRADE_ID,
                    how="left",
                )

                package_df = package_df.drop(columns=[TRADE_ID])
                package_df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_") for col in package_df.columns]

                _snake_detector_cols = dict(
                    underlier_col="upi_underlier_name",
                    platform_col="platform_identifier",
                    cleared_col="cleared",
                    upi_col="unique_product_identifier",
                )

                def _run_all_detectors(df):
                    from SDRUtils.packages.ptp_grouper import group_by_ptp, classify_ptp_groups
                    from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

                    ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)

                    if not ptp_df.empty:
                        ptp_df = classify_ptp_groups(ptp_df)
                        ptp_df = detect_mms_trades_df(ptp_df)
                        # Composite labels for grouped curves/flies: a
                        # CURVE/FLY whose legs all carry broker spreads (or
                        # all sit on UST coupons) upgrades to SPREADOVER_* /
                        # MATCHED_MATURITY_*, matching the detector-paired
                        # path below. Without this, spread-keyed groups that
                        # the curve/fly detectors used to pair (and Phase 1
                        # then upgraded) would lose their composite label.
                        if detect_curve or detect_fly:
                            ptp_df = detect_sub_package_curve_fly(
                                ptp_df, detector_kwargs=_snake_detector_cols
                            )
                            from SDRUtils.packages.spreadover_curve import (
                                detect_spreadover_curves_df,
                            )
                            ptp_df = detect_spreadover_curves_df(ptp_df)

                    df = non_ptp_df

                    if detect_invoice:
                        df = detect_invoice_swaps(df)
                        df = detect_invoice_packages(df)
                    if detect_fly:
                        df = detect_fly_trades_df(df, **_snake_detector_cols)
                    if detect_curve:
                        df = detect_curve_trades_df(df, **_snake_detector_cols)
                    if detect_mms:
                        df = detect_mms_trades_df(df)
                    if detect_mac:
                        df = detect_mac_swaps(df)
                    if detect_spreadover:
                        df = detect_spreadovers(df)
                    if detect_basis:
                        from SDRUtils.packages.basis import detect_basis_packages_df
                        df = detect_basis_packages_df(
                            df,
                            platform_col="platform_identifier",
                            cleared_col="cleared",
                            upi_col="unique_product_identifier",
                        )
                    if detect_curve or detect_fly:
                        df = detect_sub_package_curve_fly(
                            df, detector_kwargs=_snake_detector_cols
                        )
                        from SDRUtils.packages.spreadover_curve import (
                            detect_spreadover_curves_df,
                        )
                        df = detect_spreadover_curves_df(df)
                    # Residual pass: co-executed package legs that every
                    # detector above declined (no usable PTP, no DV01 shape)
                    # still group into PKG-N on (second, platform, UPI).
                    df = group_residual_package_trades(df)

                    df = pd.concat([ptp_df, df], ignore_index=True)
                    df = _rollup_matched_maturity_packages(df)
                    df = solve_all_opa_signs(df)
                    return df

                _t_pkg = _time.monotonic()

                # --- Neighborhood-scoped detection ---
                # On incremental cycles, run detectors only on trades
                # within ±10 min of new trades. Carry forward cached
                # detection results for everything else.
                _NEIGHBORHOOD_MINUTES = 10
                _cached_pkg = _PACKAGED_DAY_CACHE.get(_day_cache_key)
                if (
                    use_incremental
                    and _have_new_classifications
                    and _cached_pkg is not None
                    and not _cached_pkg.empty
                ):
                    _new_tids = set(
                        new_classifications_df["trade_id"].astype(str)
                    )
                    _exec_ts = pd.to_datetime(
                        package_df["execution_timestamp"], utc=True
                    )
                    _new_mask = package_df["trade_id"].astype(str).isin(
                        _new_tids
                    )
                    if _new_mask.any():
                        _new_ts = _exec_ts[_new_mask]
                        _win_lo = _new_ts.min() - pd.Timedelta(
                            minutes=_NEIGHBORHOOD_MINUTES
                        )
                        _win_hi = _new_ts.max() + pd.Timedelta(
                            minutes=_NEIGHBORHOOD_MINUTES
                        )
                        _hood_mask = (_exec_ts >= _win_lo) & (
                            _exec_ts <= _win_hi
                        )
                    else:
                        _hood_mask = pd.Series(True, index=package_df.index)

                    _hood_mask = _expand_hood_for_ptp_keys(
                        package_df, _hood_mask, tolerance_seconds=5
                    )
                    _hood_df = package_df[_hood_mask].copy()
                    _n_hood = len(_hood_df)

                    _hood_df = _run_all_detectors(_hood_df)

                    # Outside neighborhood: take from cached result
                    _hood_tids = set(_hood_df["trade_id"].astype(str))
                    _outside = _cached_pkg[
                        ~_cached_pkg["trade_id"].astype(str).isin(
                            _hood_tids
                        )
                    ].copy()
                    package_df = pd.concat(
                        [_outside, _hood_df], ignore_index=True
                    )
                    print(
                        f"    [TIMING] Package detection (neighborhood): "
                        f"{_time.monotonic() - _t_pkg:.1f}s "
                        f"({_n_hood} hood / {len(package_df)} total)"
                    )
                else:
                    package_df = _run_all_detectors(package_df)
                    print(
                        f"    [TIMING] Package detection (full): "
                        f"{_time.monotonic() - _t_pkg:.1f}s "
                        f"({len(package_df)} trades)"
                    )

                package_df = _resolve_special_tenor_priority(package_df)

                package_df = _prepare_cache_dataframe_for_arrow(package_df)

                count = len(day_df)
                date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
                date_dir.mkdir(parents=True, exist_ok=True)
                cache_fp = date_dir / f"{count}.parquet"
                tmp_fp = cache_fp.with_suffix(".parquet.tmp")
                table = pa.Table.from_pandas(package_df, preserve_index=False)
                pq.write_table(table, tmp_fp, compression="zstd")
                tmp_fp.replace(cache_fp)

                built_frames.append(package_df)
                _PACKAGED_DAY_CACHE[_day_cache_key] = package_df

            except Exception as e:
                print(f"  [WARN] Classification failed for {exec_date}: {e}")

        all_frames = [*cached_frames, *built_frames]
        if not all_frames:
            if return_raw:
                return pd.DataFrame(), unfiltered_raw_df
            return pd.DataFrame()

        final_df = pd.concat(all_frames, ignore_index=True)
        final_df = final_df[(final_df["execution_timestamp"] >= start.astimezone(pytz.utc)) & (final_df["execution_timestamp"] <= end.astimezone(pytz.utc))]
        if merge_package_legs:
            final_df = merge_package_legs_to_one_row(final_df)
        final_df["risk"] = final_df["estimated_pv01"].apply(_risk_from_estimated_pv01)
        final_df["risk"] = (final_df["risk"] / 100).round().mul(100)
        if return_raw:
            return final_df, unfiltered_raw_df
        return final_df


__all__ = [
    "USD_SwapProduct",
    "classify_usd_swap_trade",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "detect_invoice_swaps",
    "detect_invoice_packages",
    "detect_mac_swaps",
    "detect_spreadovers",
    "group_residual_package_trades",
    "_is_round_notional",
    "_resolve_special_tenor_priority",
    "_rollup_matched_maturity_packages",
]
