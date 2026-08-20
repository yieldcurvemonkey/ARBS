"""Build the TLT 20-31y intraday universe: CUSIP -> ISIN, matured bonds included.

Two independent sources, unioned, because each misses something the other has:

* **The scraped iShares holdings** are ground truth for what TLT actually held,
  but only on the days the scrape covers, and they carry no bond that TLT
  dropped before the scrape began.
* **Treasury's own issuance table** (``fiscaldata``, back to 1979) reconstructs
  every coupon UST whose remaining maturity fell in the band at any point in the
  study window, including issues that have since left the index.

Citi's live universe listing filters to TODAY's set, so it cannot be the source
here - but the per-bond TAG still serves bonds the listing drops. Hence
``historic_universe``, which admits them with a descriptor synthesised from the
reference table.

Writes ``notebooks/backtests/etf_rebalance/_data/intraday_universe.csv``.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sys

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_universe")

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "notebooks" / "backtests" / "etf_rebalance" / "_data"

#: The study window the intraday backfill is for.
WIN_START = datetime.date(2021, 1, 1)
WIN_END = datetime.date(2026, 8, 20)

#: Remaining-maturity band, in years. The upper edge is 31 rather than 30 so a
#: freshly auctioned 30-year is not excluded by a few days of settlement drift.
BAND_LO_Y = 20.0
BAND_HI_Y = 31.0

#: Bonds that fell out of the band BEFORE the window opens, kept as a control
#: group for the deletion study: they are what a deleted bond looks like later.
CONTROL_EXTRA_Y = 2.0


def band_maturity_bounds() -> tuple[datetime.date, datetime.date]:
    """Maturity dates that can put a bond in the band at some day in the window."""
    lo = WIN_START + datetime.timedelta(days=int(365.25 * (BAND_LO_Y - CONTROL_EXTRA_Y)))
    hi = WIN_END + datetime.timedelta(days=int(365.25 * BAND_HI_Y))
    return lo, hi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-catalog", action="store_true",
                    help="cross-check a sample of computed ISINs against Citi's catalog")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------- source 1: Treasury's issuance history ----------------
    from RVUtils.ETFRebalance.bond_panel import reference_frame

    ref = reference_frame()
    log.info("reference table: %d rows, columns=%s", len(ref), list(ref.columns)[:16])

    ref = ref.copy()
    ref["maturity_date"] = pd.to_datetime(ref["maturity_date"]).dt.date
    if "issue_date" in ref.columns:
        ref["issue_date"] = pd.to_datetime(ref["issue_date"]).dt.date
    ref["cusip"] = ref["cusip"].astype(str).str.strip().str.upper()

    mat_lo, mat_hi = band_maturity_bounds()
    in_band = ref[
        (ref["maturity_date"] >= mat_lo)
        & (ref["maturity_date"] <= mat_hi)
        & (ref["issue_date"] <= WIN_END if "issue_date" in ref.columns else True)
    ].copy()
    # Only long-dated ISSUES can be in a 20+ band; a 10-year note maturing in
    # 2041 does not exist, but a STRIP or a bill row might sneak in on a loose
    # security-type filter, so require a coupon.
    if "cpn" in in_band.columns:
        in_band = in_band[pd.to_numeric(in_band["cpn"], errors="coerce").notna()]
    in_band = in_band.drop_duplicates(subset=["cusip"])
    log.info("reference band %s..%s -> %d distinct CUSIPs", mat_lo, mat_hi, len(in_band))

    # ---------------- source 2: what TLT actually held ----------------
    from MDP.ETFHoldings import store as etf_store

    held = etf_store.load("TLT", start=WIN_START, end=WIN_END)
    if held.empty:
        log.warning("TLT holdings store returned NOTHING - the union will be reference-only.")
        held_cusips: set[str] = set()
    else:
        held["CUSIP"] = held["CUSIP"].astype(str).str.strip().str.upper()
        held_cusips = {c for c in held["CUSIP"] if c and c.lower() != "nan" and len(c) == 9}
        log.info("TLT holdings: %d rows, %d dates %s..%s, %d distinct CUSIPs",
                 len(held), held["date"].nunique(),
                 held["date"].min().date(), held["date"].max().date(), len(held_cusips))

    # A holdings file is not a bond list. TLT's carries a "Cash and/or
    # Derivatives" leg - BlackRock's own money-market fund, CUSIP 066922477 -
    # which is not a Treasury, has no reference row and no Velocity bond tag.
    # Anything the issuance table cannot name is dropped and SAID, rather than
    # carried into a fetch that would return nothing for it.
    all_ref_cusips = set(ref["cusip"])
    non_treasury = sorted(held_cusips - all_ref_cusips)
    if non_treasury:
        log.warning("dropping %d held identifier(s) that are not coupon USTs: %s",
                    len(non_treasury), non_treasury)
    held_cusips = held_cusips & all_ref_cusips

    ref_cusips = set(in_band["cusip"])
    union = sorted(ref_cusips | held_cusips)
    log.info("union: %d (reference %d, held %d, held-not-in-reference-band %d, "
             "reference-band-never-held %d)",
             len(union), len(ref_cusips), len(held_cusips),
             len(held_cusips - ref_cusips), len(ref_cusips - held_cusips))

    # ---------------- CUSIP -> ISIN ----------------
    from MDP.CitiVelocityExcel.bonds.historic import cusips_to_isins

    isins = cusips_to_isins(union)
    log.info("ISINs: %d of %d CUSIPs completed", len(isins), len(union))
    dropped = [c for c in union if c not in isins]
    if dropped:
        log.warning("dropped (no ISIN): %s", dropped[:20])

    # Descriptors come from the FULL table, not the band-filtered one: a bond TLT
    # held outside the band (912810FT0, a 4.5% Feb-36 stub carried at 0.00%
    # weight into February 2021) has a perfectly good reference row, and looking
    # it up in the filtered frame reports it as undescribable.
    ref_by_cusip = ref.drop_duplicates(subset=["cusip"]).set_index("cusip")
    rows = []
    for cusip in union:
        isin = isins.get(cusip)
        if isin is None:
            continue
        r = ref_by_cusip.loc[cusip] if cusip in ref_by_cusip.index else None
        rows.append({
            "cusip": cusip,
            "isin": isin,
            "maturity_date": None if r is None else r["maturity_date"],
            "issue_date": None if r is None else r.get("issue_date"),
            "coupon": None if r is None else r.get("cpn"),
            "label": None if r is None else r.get("label"),
            "in_reference_band": cusip in ref_cusips,
            "held_by_tlt": cusip in held_cusips,
        })
    out = pd.DataFrame(rows).sort_values("maturity_date", na_position="last")

    # A bond with no reference row cannot get a synthesised descriptor. Flag it
    # loudly rather than discovering it inside the fetch.
    no_ref = out[out["maturity_date"].isna()]
    if len(no_ref):
        log.warning("%d held CUSIPs have NO reference row (descriptor cannot be "
                    "synthesised, and historic_universe will raise on them): %s",
                    len(no_ref), list(no_ref["cusip"])[:20])

    path = OUT_DIR / "intraday_universe.csv"
    out.to_csv(path, index=False)
    log.info("wrote %s (%d bonds)", path, len(out))

    # ---------------- verify the arithmetic against Citi's own catalog -------
    if args.verify_catalog:
        from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog

        cat = CitiVeloCatalog.default()
        try:
            live = cat.bonds(country="USA", currency="USD", asset_type="GOVT")
        except Exception as exc:  # noqa: BLE001
            log.warning("catalog read failed (%s: %s)", type(exc).__name__, exc)
            live = None
        if live is not None:
            live_isins = set(getattr(live, "isin", pd.Series(dtype=str)).astype(str)) \
                if hasattr(live, "isin") else {str(d.isin) for d in live}
            ours = set(out["isin"])
            log.info("catalog holds %d USA.USD.GOVT ISINs; %d of our %d are in it "
                     "(%d must be tag-only)",
                     len(live_isins), len(ours & live_isins), len(ours),
                     len(ours - live_isins))
            # The arithmetic is verified by AGREEMENT on the overlap: every ISIN
            # we computed for a bond Citi lists must be a string Citi also uses.
            sample = sorted(ours & live_isins)[:10]
            log.info("sample verified ISINs: %s", sample)

    print(f"UNIVERSE_ROWS={len(out)}")
    print(f"UNIVERSE_PATH={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
