from __future__ import annotations
import os
import re
from typing import Any, Dict, Optional, Tuple
import pandas as pd

_DEFAULT_GS_CLIENT_ID = "2eb2f48872304c1d94fa1642fa691afe"
_DEFAULT_GS_SECRET_KEY = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"

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
    if "x" not in tenor.lower():
        fwd_tenor = "0b"
    else:
        fwd_tenor = tenor.split("x")[0]
        tenor = tenor.split("x")[1]

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
        # if parsed["tenor"].lower() != tenor.lower():
        #     continue
        if fwd_tenor.lower() not in str(row["name"]).lower():
            continue
        if str(tenor).lower() not in str(row["name"]).lower():
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


def _resolve_gs_credentials(gs_client_id: Optional[str], gs_secret_key: Optional[str]) -> Tuple[str, str]:
    client_id = (gs_client_id or os.getenv("GS_CLIENT_ID") or _DEFAULT_GS_CLIENT_ID).strip()
    secret_key = (gs_secret_key or os.getenv("GS_CLIENT_SECRET") or _DEFAULT_GS_SECRET_KEY).strip()
    if not client_id or not secret_key:
        raise ValueError("Missing GS credentials. Set GS_CLIENT_ID and GS_CLIENT_SECRET or pass them explicitly.")
    return client_id, secret_key


def fetch_clearing_house_basis(
    asset_id_a: str, asset_id_b: str,
    start: Any, end: Any,
    gs_client_id: str, gs_secret_key: str,
) -> pd.DataFrame:
    from gs_quant.data import Dataset
    from gs_quant.session import GsSession

    client_id, secret_key = _resolve_gs_credentials(gs_client_id, gs_secret_key)
    GsSession.use(client_id=client_id, client_secret=secret_key, scopes=GsSession.Scopes.get_default())

    df = Dataset("IR_SWAP_RATES_V1_STANDARD").get_data(start, end, assetId=[asset_id_a, asset_id_b]).reset_index()

    df_a = (
        df[df["assetId"] == asset_id_a][["date", "rate"]]
        .rename(columns={"rate": "rate_a"})
        .set_index("date")
        .sort_index()
    )
    df_b = (
        df[df["assetId"] == asset_id_b][["date", "rate"]]
        .rename(columns={"rate": "rate_b"})
        .set_index("date")
        .sort_index()
    )
    merged = df_a.join(df_b, how="inner")
    merged["basis_bps"] = (merged["rate_a"] - merged["rate_b"]) * 10_000
    merged.index.name = "date"
    return merged
