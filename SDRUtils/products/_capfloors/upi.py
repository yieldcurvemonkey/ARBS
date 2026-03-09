from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd


def _default_base_dir() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _load_capfloor_upis(csv_path: str) -> frozenset[str]:
    df = pd.read_csv(csv_path, dtype=str)

    currency = df.get("Attributes_NotionalCurrency", pd.Series(dtype="string")).astype("string").str.upper()
    underlier_cols = [
        "Derived_UnderlierName",
        "Attributes_UnderlyingInstrumentIndex",
        "Attributes_ReferenceRate",
        "Attributes_Underlying_ReferenceRate",
    ]
    underlier_text = pd.Series("", index=df.index, dtype="string")
    for col in underlier_cols:
        if col in df.columns:
            underlier_text = underlier_text + " " + df[col].fillna("").astype("string")

    mask = currency.eq("USD") & underlier_text.str.contains("SOFR", case=False, na=False)
    upis = (
        df.loc[mask, "Identifier_UPI"]
        .fillna("")
        .astype("string")
        .str.strip()
        .str.upper()
    )
    return frozenset(upi for upi in upis.tolist() if upi)


def build_capfloor_upi_set(base_dir: str | Path | None = None) -> set[str]:
    root = Path(base_dir) if base_dir is not None else _default_base_dir()
    csv_path = root / "anna_dsb_upis" / "Rates-Option-CapFloor.csv"
    return set(_load_capfloor_upis(str(csv_path)))
