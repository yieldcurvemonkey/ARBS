from __future__ import annotations
import os
import re
from typing import Any, Dict, Optional, Tuple
import pandas as pd

_DEFAULT_GS_CLIENT_ID = "2eb2f48872304c1d94fa1642fa691afe"
_DEFAULT_GS_SECRET_KEY = "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4"

_NAME_PATTERN = re.compile(
    # "USD Swap SOFR 1y ATM 0b to 10y LCH Cleared"
    #                    ^freq   ^start  ^tenor
    r"^(?P<ccy>\w+)\s+Swap\s+(?P<index>\S+)\s+(?P<freq>\S+)\s+ATM\s+(?P<start>\S+)"
    r"\s+to\s+(?P<tenor>\S+)\s+(?P<clearing_house>\w+)\s+Cleared$"
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
    """Resolve one asset id per clearing house.  ``asset_id_a`` is ``clearing_house_a``.

    Matching is EXACT on the forward-start token and the maturity token, and
    ambiguity raises.  The predecessor tested both tokens as substrings of the
    asset name and let the last matching row win, which resolved
    ``tenor="5y"`` to the 15y asset on both legs and ``tenor="1y"`` to
    LCH-30y against CME-12y -- a curve spread served as a CCP basis.  Only 10y
    and 30y happened to be correct, and 10y is the tenor that had been spot
    checked.  See tests/test_convexity_rv_ccp_basis.py.
    """
    from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import find_asset_pair as _exact

    if "ccy" not in getattr(coverage, "columns", []):
        coverage = _parse_frame(coverage)
    return _exact(
        coverage,
        ccy=ccy,
        index=index,
        tenor=tenor,
        clearing_house_a=clearing_house_a,
        clearing_house_b=clearing_house_b,
    )


def _parse_frame(coverage: pd.DataFrame) -> pd.DataFrame:
    """Parse a raw ``assetId``/``name`` coverage frame into labelled columns."""
    recs = []
    for asset_id, name in zip(coverage["assetId"], coverage["name"]):
        parsed = parse_coverage_name(str(name))
        if parsed is None:
            continue
        recs.append(
            {
                "assetId": asset_id,
                "name": name,
                "ccy": parsed["ccy"].upper(),
                "index": parsed["index"].upper(),
                "start": parsed["start"],
                "tenor": parsed["tenor"],
                "clearing_house": parsed["clearing_house"].upper(),
            }
        )
    return pd.DataFrame.from_records(recs)


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
