from __future__ import annotations
import re
from typing import Any, Dict, Optional
import pandas as pd

_NAME_PATTERN = re.compile(
    r"^(?P<ccy>\w+)\s+Swap\s+(?P<index>\S+)\s+\S+\s+ATM\s+\S+\s+to\s+(?P<tenor>\S+)\s+(?P<clearing_house>\w+)\s+Cleared$"
)


def parse_coverage_name(name: str) -> Optional[Dict[str, str]]:
    m = _NAME_PATTERN.match(name)
    if not m:
        return None
    return m.groupdict()


def find_asset_pair(
    coverage: pd.DataFrame,
    ccy: str, index: str, tenor: str,
    clearing_house_a: str = "LCH", clearing_house_b: str = "CME",
) -> Dict[str, str]:
    asset_id_a = None
    asset_id_b = None
    for _, row in coverage.iterrows():
        parsed = parse_coverage_name(row["name"])
        if parsed is None:
            continue
        if parsed["ccy"].upper() != ccy.upper():
            continue
        if parsed["index"].upper() != index.upper():
            continue
        if parsed["tenor"].lower() != tenor.lower():
            continue
        if parsed["clearing_house"].upper() == clearing_house_a.upper():
            asset_id_a = row["assetId"]
        elif parsed["clearing_house"].upper() == clearing_house_b.upper():
            asset_id_b = row["assetId"]
    if asset_id_a is None or asset_id_b is None:
        raise ValueError(
            f"Could not find asset pair for {ccy} {index} {tenor} "
            f"{clearing_house_a}/{clearing_house_b}"
        )
    return {"asset_id_a": asset_id_a, "asset_id_b": asset_id_b}


def fetch_clearing_house_basis(
    asset_id_a: str, asset_id_b: str,
    start: Any, end: Any,
    gs_client_id: str, gs_secret_key: str,
) -> pd.DataFrame:
    from gs_quant.data import Dataset
    from gs_quant.session import GsSession
    GsSession.use(client_id=gs_client_id, client_secret=gs_secret_key, scopes=GsSession.Scopes.get_default())
    df = Dataset("IR_SWAP_RATES_V1_STANDARD").get_data(start, end, assetId=[asset_id_a, asset_id_b])
    df_a = df[df["assetId"] == asset_id_a][["date", "rate"]].set_index("date").rename(columns={"rate": "rate_a"})
    df_b = df[df["assetId"] == asset_id_b][["date", "rate"]].set_index("date").rename(columns={"rate": "rate_b"})
    merged = df_a.join(df_b, how="inner")
    merged["basis_bps"] = (merged["rate_a"] - merged["rate_b"]) * 10_000
    return merged
