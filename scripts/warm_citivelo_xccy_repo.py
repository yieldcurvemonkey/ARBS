"""Warm the Citi Velocity history the two new books need but ARBS does not yet cache.

Neither family is in the ARBS cache today. Measured 2026-08-12: of 14,438 parquets under
``citivelo_excel/DAILY/CLOSE``, **zero** match ``*XCCY*``, and the MONEY_MARKETS family carries
nine. So both the cross-currency basis book and the GSS repo hurdle are running on substitutes
until this has been run once.

    conda run -n stir python scripts/warm_citivelo_xccy_repo.py --what all --start 2010-01-01

REQUIREMENTS. The bridge attaches to a **human-authenticated Excel** with the Velocity add-in
signed in; it never spawns one, because spawned instances do not register the CV* UDFs. If Excel
is not up and signed in, this exits with a clear message rather than half a cache.

WHAT IT DOES NOT DO. It does not settle the three unverified cross-currency conventions -- which
currency ``SPREAD_LEG`` denotes, the collateral currency, and the sign. Those need a market
cross-check, and until they are settled the sign of the basis book is unproven; ``--probe`` prints
what is needed to do that by hand.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("warm_xccy_repo")

from BT.gss_fly.costs import REPO_COLLATERAL, REPO_TENORS, repo_tag_grid  # noqa: E402
from BT.xccy_rv.config import DEFAULT_PAIRS, DEFAULT_POINTS  # noqa: E402
from BT.xccy_rv.data import xccy_basis_tag  # noqa: E402

MONEY_MARKET_TAGS = [
    "RATES.MONEY_MARKETS.USD.BGCR",
    "RATES.MONEY_MARKETS.USD.TGCR",
    "RATES.MONEY_MARKETS.USD.SOFR.ON",
    "RATES.MONEY_MARKETS.USD.SOFR.1M",
    "RATES.MONEY_MARKETS.USD.SOFR.3M",
    "RATES.MONEY_MARKETS.USD.SOFR.6M",
    "RATES.MONEY_MARKETS.USD.SOFR.1Y",
]


def xccy_tags(pairs=DEFAULT_PAIRS, points=DEFAULT_POINTS, leg: str = "SPREAD_LEG"):
    """Every forward × tenor cell the book trades, plus the roll-down brackets around each."""
    out = []
    for pair in pairs:
        c1, c2 = pair[:3], pair[3:]
        if "USD" not in (c1, c2):
            # EURJPY and friends are synthesised from the two USD crosses, exactly as the
            # original does; there is no direct Citi cross for them.
            continue
        for fwd, mat in points.items():
            for f in {"SPOT", f"{fwd}Y", f"{max(fwd - 1, 0)}Y" if fwd > 1 else "6M"}:
                out.append(xccy_basis_tag(c1, c2, f"{mat}Y", f, leg))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--what", choices=["xccy", "repo", "mm", "all"], default="all")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=str(datetime.date.today()))
    ap.add_argument("--chunk", type=int, default=60, help="tags per fetch; the add-in wedges on very wide requests")
    ap.add_argument("--probe", action="store_true", help="resolve one tag and report depth, then stop")
    args = ap.parse_args()

    try:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()
    except Exception as exc:  # noqa: BLE001
        logger.error("cannot reach the Velocity bridge: %s: %s", type(exc).__name__, exc)
        logger.error("Open Excel, sign in to Velocity, and retry. This script cannot start one.")
        return 2

    if args.probe:
        tag = xccy_basis_tag("EUR", "USD", "5Y", "1Y")
        logger.info("probing %s at Period=MAX", tag)
        try:
            df = quotes.frame([tag], "DAILY", start=None, end=None)
        except Exception as exc:  # noqa: BLE001
            logger.error("probe failed: %s: %s", type(exc).__name__, exc)
            return 2
        if df is None or df.empty:
            logger.warning("probe returned nothing — the tag may not serve, or history is empty")
            return 1
        logger.info("depth: %d rows, %s .. %s", len(df), df.index.min(), df.index.max())
        logger.info(
            "STILL UNVERIFIED after this probe: which currency SPREAD_LEG denotes, the collateral "
            "currency, and the sign. Cross-check one tenor against a broker run before trading the sign."
        )
        return 0

    plan = []
    if args.what in ("xccy", "all"):
        plan.append(("xccy", xccy_tags()))
    if args.what in ("repo", "all"):
        plan.append(("repo", repo_tag_grid()))
    if args.what in ("mm", "all"):
        plan.append(("money_markets", MONEY_MARKET_TAGS))

    rc = 0
    for name, tags in plan:
        logger.info("%s: %d tags, %s .. %s", name, len(tags), args.start, args.end)
        got = 0
        for i in range(0, len(tags), args.chunk):
            block = tags[i : i + args.chunk]
            try:
                df = quotes.frame(block, "DAILY", start=args.start, end=args.end)
            except Exception as exc:  # noqa: BLE001 — one bad block must not lose the rest
                logger.warning("  block %d-%d failed: %s: %s", i, i + len(block), type(exc).__name__, exc)
                rc = 1
                continue
            n = 0 if df is None else int(df.notna().sum().sum())
            got += n
            logger.info("  block %3d-%3d: %6d values", i, i + len(block), n)
        logger.info("%s complete: %d values cached", name, got)
        if got == 0:
            logger.error("%s produced NOTHING — treat the family as unavailable, not as empty", name)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
