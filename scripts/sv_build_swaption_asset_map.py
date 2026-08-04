"""Print ASSET_IDS_MAP entries for EUR/GBP/JPY from the GS swaption coverage.

Run this, paste the printed dict literals into definitions/IRSwaptions.py.
Generated rather than hand-typed: 240 assetIds are not worth transcribing.
"""
import os
import re
import sys
from collections import defaultdict

from gs_quant.data import Dataset
from gs_quant.session import GsSession

CURVE_BY_CCY = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "GBP": "GBP-SONIA",
    "JPY": "JPY-TONAR",
}

NAME_RE = re.compile(
    r"^Swaption (?P<ccy>[A-Z]{3})-\S+ Payer (?P<expiry>\S+) (?P<tail>\S+) ATM"
)


def _ensure_gs_session() -> None:
    """Env-var creds with a working fallback -- see ``_ensure_gs_session`` in
    ``MDP/IRSwaptions/GSQUANT/ql/grid.py``. ``os.environ["GS_CLIENT_ID"]``
    raises ``KeyError`` when unset; ``os.getenv`` with a default does not.
    """
    client_id = os.getenv("GS_CLIENT_ID", "2eb2f48872304c1d94fa1642fa691afe").strip()
    client_secret = os.getenv(
        "GS_CLIENT_SECRET",
        "91cb9c89110495d1f62d0ab0c4014555c992c2509de8f5ae2b8bf1a2d3c86bd4",
    ).strip()
    if not client_id or not client_secret:
        raise ValueError(
            "Missing GS credentials. Set GS_CLIENT_ID and GS_CLIENT_SECRET "
            "environment variables."
        )

    GsSession.use(
        client_id=client_id,
        client_secret=client_secret,
        scopes=GsSession.Scopes.get_default(),
    )


def main() -> None:
    _ensure_gs_session()
    cov = Dataset("IR_SWAPTION_VOLS_V1_STANDARD").get_coverage()
    out = defaultdict(dict)
    for _, row in cov.iterrows():
        m = NAME_RE.match(str(row["name"]))
        if not m:
            continue
        curve = CURVE_BY_CCY.get(m.group("ccy"))
        if curve is None:
            continue
        out[curve][row["assetId"]] = f"{m.group('expiry')} {m.group('tail')}"

    for curve, mapping in sorted(out.items()):
        print(f'    "{curve}": {{')
        for aid, struct in sorted(mapping.items(), key=lambda kv: kv[1]):
            print(f'        "{aid}": "{struct}",')
        print("    },")
        print(f"    # {curve}: {len(mapping)} structures", file=sys.stderr)


if __name__ == "__main__":
    main()
