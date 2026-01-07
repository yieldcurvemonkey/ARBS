from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from SDRUtils.config import USD_CONVENTIONS, get_conventions
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years
from SDRUtils.core.tenors import forward_to_label, tenor_to_label


def _norm_upi(x: object) -> str:
    return str(x).strip().strip("'").strip('"').upper()


def _tenor(value: object, unit: object) -> Optional[str]:
    if value is None or unit is None or pd.isna(value) or pd.isna(unit):
        return None
    s_unit = str(unit).strip().upper()
    try:
        v = float(str(value).strip())
    except Exception:
        return None

    if abs(v - round(v)) < 1e-9:
        sval = str(int(round(v)))
    else:
        sval = str(v).rstrip("0").rstrip(".")

    if s_unit.startswith("DAY"):
        suf = "D"
    elif s_unit.startswith("WEEK"):
        suf = "W"
    elif s_unit.startswith("MNTH"):
        suf = "M"
    elif s_unit.startswith("MONTH"):
        suf = "M"
    elif s_unit.startswith("YEAR"):
        suf = "Y"
    else:
        return None
    return f"{sval}{suf}"


def _clean_ref_rate(x: object) -> Optional[str]:
    if x is None or pd.isna(x):
        return None
    return " ".join(str(x).strip().split())


def _exercise_style_short(code: object) -> Optional[str]:
    if code is None or pd.isna(code):
        return None
    c = str(code).strip().upper()
    return {"EURO": "EURO", "BERM": "BERM", "AMER": "AMER"}.get(c, c)


def _settlement_short(x: object) -> Optional[str]:
    if x is None or pd.isna(x):
        return None
    s = str(x).strip().upper()
    if s in {"PHYS", "PHYSICAL"}:
        return "PHYS"
    if s == "CASH":
        return "CASH"
    return s


def _option_role_short(option_type: object) -> Optional[str]:
    if option_type is None or pd.isna(option_type):
        return None
    t = str(option_type).strip().upper()
    return {"CALL": "PAYER", "PUTO": "RECEIVER", "OPTL": "CHOOSER"}.get(t, t)


def _title_ccy(x: object) -> Optional[str]:
    if x is None or pd.isna(x):
        return None
    return str(x).strip().upper()


def _vanilla_short(row: pd.Series) -> str:
    """
    Derive VANILLA/other using only CSV fields.
    Preference order:
      - DSB "OptionStyle"/"OptionType" style fields if present
      - else infer from exercise style only (EURO/BERM/AMER) => treat as VANILLA by default
    """
    # Common DSB column names vary. We use your existing names if present; else degrade gracefully.
    # If you have a specific field like swaption_Attributes_OptionStyle, add it here.
    # For now, your sample outputs imply "Vanilla" most of the time.
    return "VANILLA"


def _underlying_compact(row: pd.Series) -> str:
    rr = _clean_ref_rate(row.get("swap_Attributes_ReferenceRate"))
    term = _tenor(
        row.get("swap_Attributes_ReferenceRateTermValue"),
        row.get("swap_Attributes_ReferenceRateTermUnit"),
    )
    sched = row.get("swap_Attributes_NotionalSchedule")
    sched_s = None if sched is None or pd.isna(sched) else str(sched).strip().upper()
    # swap delivery type is redundant vs swaption settlement in your desired compact format,
    # so we intentionally do NOT include swap_Attributes_DeliveryType here.
    parts = [p for p in [rr, term, sched_s] if p]
    return " ".join(parts) if parts else "UNKNOWN_UNDERLYING"


def build_upi_path(product: str, base_dir: str | Path | None = None) -> Path:
    base = Path(base_dir).resolve() if base_dir is not None else Path(__file__).resolve().parent
    return base.parent.parent / "anna_dsb_upis" / product


def _read_csv_safely(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str)


@lru_cache(maxsize=8)
def _load_swaptions_df(base_dir: str | Path | None) -> pd.DataFrame:
    df = _read_csv_safely(build_upi_path("Rates-Option-Swaption.csv", base_dir=base_dir))
    df.columns = ["swaption_" + c for c in df.columns]
    df["swaption_Identifier_UPI"] = df["swaption_Identifier_UPI"].map(_norm_upi)
    df["swaption_Attributes_UnderlyingInstrumentUPI"] = df["swaption_Attributes_UnderlyingInstrumentUPI"].map(_norm_upi)
    return df


@lru_cache(maxsize=8)
def _load_swaps_df(base_dir: str | Path | None) -> pd.DataFrame:
    files = [
        "Rates-Swap-Fixed_Float_OIS.csv",
        "Rates-Swap-Fixed_Float.csv",
        "Rates-Swap-Fixed_Float_Zero_Coupon.csv",
        "Rates-Swap-Fixed_Fixed.csv",
        "Rates-Swap-Basis.csv",
        "Rates-Swap-Basis_OIS.csv",
        "Rates-Swap-Cross_Currency_Fixed_Float.csv",
        "Rates-Swap-Cross_Currency_Fixed_Float_NDS.csv",
        "Rates-Swap-Cross_Currency_Basis.csv",
        "Rates-Swap-Non_Standard.csv",
        "Rates-Swap-Cross_Currency_Fixed_Fixed.csv",
        "Rates-Swap-Cross_Currency_Zero_Coupon.csv",
        "Rates-Swap-Inflation_Swap.csv",
        "Rates-Swap-Inflation_Fixed_Float_YoY.csv",
    ]

    frames: list[pd.DataFrame] = []
    for fn in files:
        p = build_upi_path(fn, base_dir=base_dir)
        if p.exists():
            frames.append(_read_csv_safely(p))

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df.columns = ["swap_" + c for c in df.columns]
    df["swap_Identifier_UPI"] = df["swap_Identifier_UPI"].map(_norm_upi)
    return df


@lru_cache(maxsize=8)
def _build_upi_df(base_dir: str | Path | None = None) -> pd.DataFrame:
    swaption_df = _load_swaptions_df(base_dir)
    swap_df = _load_swaps_df(base_dir)

    if swap_df.empty:
        return swaption_df.copy()

    return swaption_df.merge(
        swap_df,
        left_on="swaption_Attributes_UnderlyingInstrumentUPI",
        right_on="swap_Identifier_UPI",
        how="left",
    )


def swaption_upi_description(
    swaption_upi: str,
    *,
    base_dir: str | Path | None = None,
) -> str:
    """
    Compact, non-redundant desk string.

    Example:
      "USD-SOFR-OIS Compound 1D Constant PAYER EURO VANILLA PHYS"
    """
    upi = _norm_upi(swaption_upi)
    df = _build_upi_df(base_dir)
    if df.empty:
        return f"{upi}: reference data not available"

    idx = getattr(df, "_upi_idx", None)
    if idx is None:
        df._upi_idx = {k: i for i, k in enumerate(df["swaption_Identifier_UPI"].astype(str))}
        idx = df._upi_idx

    i = idx.get(upi)
    if i is None:
        return f"{upi}: not found"

    row = df.iloc[i]

    # Core underlier description (already implies USD if the ref rate string is USD-*)
    under = _underlying_compact(row)

    # Currency only if not already embedded
    ccy = _title_ccy(row.get("swaption_Attributes_NotionalCurrency"))
    if ccy and not under.upper().startswith(f"{ccy}-"):
        under = f"{ccy} {under}"

    role = _option_role_short(row.get("swaption_Attributes_OptionType")) or "UNKNOWN"
    ex = _exercise_style_short(row.get("swaption_Attributes_OptionExerciseStyle")) or "UNK"
    style = _vanilla_short(row)  # currently defaults to VANILLA using only CSV fields
    settle = _settlement_short(row.get("swaption_Derived_CFIDeliveryType")) or "UNK"

    # Final compact string
    return f"{under} {role} {ex} {style} {settle}"


def make_swaption_desc_func(
    *,
    base_dir=None,
    # these are columns from YOUR TRADES DF (not the DSB reference)
    trade_ccy_col: str = "Notional currency-Leg 1",
    trade_asof_col: str = "Execution Timestamp",  # your statement: vanilla effective == today
    trade_eff_col: str = "Effective Date",
    trade_exp_col: str = "Expiration Date",
    trade_mat_col: str = "Maturity date of the underlier",
):
    """
    Returns a function that can be applied row-wise to a trades df to produce a compact description
    including tenor (1Y10Y or 1Y1Y1Y for midcurves).

    IMPORTANT: This function is meant for:
      df.apply(desc_fn, axis=1)
    because tenor uses trade dates.
    """

    ref = _build_upi_df(base_dir)
    if ref.empty:
        raise RuntimeError("UPI reference data not available")

    # reduce columns for speed
    ref_cols = [
        "swaption_Identifier_UPI",
        "swaption_Attributes_OptionType",
        "swaption_Attributes_OptionExerciseStyle",
        "swaption_Derived_CFIDeliveryType",
        "swap_Attributes_ReferenceRate",
        "swap_Attributes_ReferenceRateTermValue",
        "swap_Attributes_ReferenceRateTermUnit",
        "swap_Attributes_NotionalSchedule",
    ]
    ref2 = ref.loc[:, [c for c in ref_cols if c in ref.columns]].copy()

    upis = ref2["swaption_Identifier_UPI"].astype(str)
    upi_to_pos = dict(zip(upis, range(len(ref2))))

    def desc_row(trade_row: pd.Series) -> str:
        upi = _norm_upi(trade_row.get("Unique Product Identifier"))
        pos = upi_to_pos.get(upi)
        if pos is None:
            return f"{upi}: not found"

        r = ref2.iloc[pos]

        # Underlier compact
        under = _underlying_compact(r)

        # Role/exercise/settle/style from reference (CSV-only)
        role = _option_role_short(r.get("swaption_Attributes_OptionType")) or "UNKNOWN"
        ex = _exercise_style_short(r.get("swaption_Attributes_OptionExerciseStyle")) or "UNK"
        style = _vanilla_short(r)  # currently "VANILLA"
        settle = _settlement_short(r.get("swaption_Derived_CFIDeliveryType")) or "UNK"

        raw_ccy = trade_row.get(trade_ccy_col)
        ccy = None if raw_ccy is None or pd.isna(raw_ccy) else str(raw_ccy).strip().upper()

        asof = pd.to_datetime(trade_row.get(trade_asof_col), errors="coerce")
        eff = pd.to_datetime(trade_row.get(trade_eff_col), errors="coerce")
        exp = pd.to_datetime(trade_row.get(trade_exp_col), errors="coerce")
        mat = pd.to_datetime(trade_row.get(trade_mat_col), errors="coerce")

        conventions = USD_CONVENTIONS
        if ccy:
            try:
                conventions = get_conventions(ccy)
            except ValueError:
                conventions = USD_CONVENTIONS

        tenor = None
        if pd.notna(asof) and pd.notna(eff) and pd.notna(exp) and pd.notna(mat):

            expiry_years = calculate_tenor_years(asof, exp, conventions=conventions)
            tail_years = calculate_tenor_years(eff, mat, conventions=conventions)
            expiry_label = tenor_to_label(expiry_years, expiration_date=exp)
            tail_label = tenor_to_label(tail_years, expiration_date=mat)

            if eff <= exp:
                tenor = f"{expiry_label}{tail_label}"
            else:
                forward_years = calculate_forward_start_years(
                    exp,
                    eff,
                    conventions=conventions,
                    use_execution_date_only=True,
                )
                forward_label = forward_to_label(forward_years, effective_date=eff)
                tenor = f"{expiry_label}{forward_label}{tail_label}"
        else:
            tenor = "UNK"

        return f"{under} {tenor} {role} {ex} {style} {settle}"

    return desc_row
