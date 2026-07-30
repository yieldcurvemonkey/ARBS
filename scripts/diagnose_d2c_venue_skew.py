"""Skew diagnostic for the D2C platform whitelist (Task A2, audit follow-up).

The 2026-07-15 feasibility audit flagged the ~67/33 PAID/RECEIVED split
reported by the STIR dealer-direction POC as "a warning, not evidence": with
venue computed by the old classify_venue heuristic (D2D for six known IDB
codes, D2C for literally everything else -- including unknown/missing
platform IDs), the split could be real signed client flow, or it could be
contamination from misclassified D2D/unknown-venue prints, curve-suspect
mid bias, or off-market (NPV_VS_UPFRONT) prints where the classification
rule imposes non-negative dealer edge by construction.

This script recomputes the PAID/RECEIVED split from ``arbs_stir_direction_v1``
joined (via unit_key -> trade_id for OUTRIGHT units, unit_key -> package_id
for CURVE/FLY/PKG units, first leg by expiration_date/trade_id) with
``arbs_usd_swap_tape_legs_v2.platform_identifier``, stratified by:

  (a) venue_status (SDRUtils.stir_flow.trade_selection.venue_status):
      D2C_WHITELISTED vs VENUE_UNKNOWN (D2D reported too, as a sanity check --
      it should be ~empty since arbs_usd_swap_tape_legs_v2.venue = 'D2C' is
      already an eligibility filter upstream in ELIGIBLE_LEGS_SQL).
  (b) curve_suspect_trade: curve-clean vs curve-suspect.
  (c) is_off_market: on-market vs off-market.

Reference: docs/superpowers/audits/2026-07-15-sdr-dealer-positioning-feasibility-audit.md
Plan item: docs/superpowers/plans/2026-07-14-dealer-ladder-infrastructure.md, Task A2.

Usage:
    conda run -n stir python scripts/diagnose_d2c_venue_skew.py [--out-dir DIR]

If --out-dir is given, writes:
    <out-dir>/d2c_skew_diagnostic_breakdown.csv   (all strata, long format)
    <out-dir>/d2c_skew_diagnostic_summary.txt     (stdout report, duplicated)
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import pandas as pd

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils.stir_flow.trade_selection import venue_status

DIRECTION_SQL = """
SELECT unit_key, trade_id, package_id, as_of_date, dealer_direction,
       classification_method, is_off_market, curve_suspect_trade,
       direction_confidence, structure_dv01, notional, dv01
FROM arbs_stir_direction_v1
"""

_OUTRIGHT_PLATFORM_SQL = """
SELECT trade_id AS unit_key, platform_identifier
FROM arbs_usd_swap_tape_legs_v2
WHERE trade_id = ANY(%(ids)s)
"""

_PKG_PLATFORM_SQL = """
SELECT package_id, platform_identifier, expiration_date, trade_id
FROM arbs_usd_swap_tape_legs_v2
WHERE package_id = ANY(%(ids)s)
"""


def load_direction(engine) -> pd.DataFrame:
    """Pull every classified unit from arbs_stir_direction_v1."""
    return pd.read_sql(DIRECTION_SQL, engine)


def load_platform_ids(engine, direction: pd.DataFrame) -> pd.DataFrame:
    """Resolve one platform_identifier per unit_key from the tape.

    OUTRIGHT units (package_id IS NULL): unit_key == trade_id, direct match.
    CURVE/FLY/PKG units (package_id IS NOT NULL): unit_key == package_id;
    pick the anchor leg (earliest expiration_date, tie-broken by trade_id) --
    the same convention used for other per-unit tape metadata (Task A1's
    visibility_timestamp backfix).
    """
    outright_keys = sorted(
        direction.loc[direction["package_id"].isna(), "unit_key"].dropna().unique().tolist()
    )
    pkg_keys = sorted(
        direction.loc[direction["package_id"].notna(), "package_id"].dropna().unique().tolist()
    )

    frames = []
    if outright_keys:
        df = pd.read_sql(_OUTRIGHT_PLATFORM_SQL, engine, params={"ids": outright_keys})
        frames.append(df.drop_duplicates(subset=["unit_key"], keep="first"))
    if pkg_keys:
        raw = pd.read_sql(_PKG_PLATFORM_SQL, engine, params={"ids": pkg_keys})
        if not raw.empty:
            raw = raw.sort_values(["package_id", "expiration_date", "trade_id"])
            first_leg = raw.groupby("package_id", as_index=False).first()
            frames.append(
                first_leg.rename(columns={"package_id": "unit_key"})[
                    ["unit_key", "platform_identifier"]
                ]
            )

    if not frames:
        return pd.DataFrame(columns=["unit_key", "platform_identifier"])
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["unit_key"], keep="first")


def enrich(direction: pd.DataFrame, platforms: pd.DataFrame) -> pd.DataFrame:
    """Attach venue_bucket / curve_bucket / market_bucket strata columns."""
    df = direction.merge(platforms, on="unit_key", how="left", validate="one_to_one")
    df["venue_bucket"] = df["platform_identifier"].apply(venue_status)
    df["curve_bucket"] = df["curve_suspect_trade"].map(
        {True: "CURVE_SUSPECT", False: "CURVE_CLEAN"}
    )
    df["curve_bucket"] = df["curve_bucket"].fillna("N/A")
    df["market_bucket"] = df["is_off_market"].map({True: "OFF_MARKET", False: "ON_MARKET"})
    df["market_bucket"] = df["market_bucket"].fillna("N/A")
    return df


def summarize(df: pd.DataFrame, group_cols: list[str], dimension: str) -> pd.DataFrame:
    """PAID/RECEIVED split (count- and dv01-weighted) for one grouping."""
    if group_cols:
        groups = df.groupby(group_cols, dropna=False)
    else:
        groups = [((), df)]

    rows = []
    for key, sub in groups:
        key_tuple = key if isinstance(key, tuple) else (key,)
        n_total = len(sub)
        n_paid = int((sub["dealer_direction"] == "PAID").sum())
        n_received = int((sub["dealer_direction"] == "RECEIVED").sum())
        n_unknown = int((sub["dealer_direction"] == "UNKNOWN").sum())
        n_classified = n_paid + n_received
        pct_paid = 100.0 * n_paid / n_classified if n_classified else float("nan")

        paid_dv01 = float(sub.loc[sub["dealer_direction"] == "PAID", "dv01"].fillna(0).sum())
        recv_dv01 = float(sub.loc[sub["dealer_direction"] == "RECEIVED", "dv01"].fillna(0).sum())
        dv01_classified = paid_dv01 + recv_dv01
        dv01_pct_paid = 100.0 * paid_dv01 / dv01_classified if dv01_classified else float("nan")

        row = dict(zip(group_cols, key_tuple))
        row.update(
            dimension=dimension,
            n_total=n_total,
            n_paid=n_paid,
            n_received=n_received,
            n_unknown=n_unknown,
            n_classified=n_classified,
            pct_paid=round(pct_paid, 1) if n_classified else None,
            pct_received=round(100.0 - pct_paid, 1) if n_classified else None,
            dv01_paid=round(paid_dv01, 1),
            dv01_received=round(recv_dv01, 1),
            dv01_pct_paid=round(dv01_pct_paid, 1) if dv01_classified else None,
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_report(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    pieces = [
        summarize(df, [], "OVERALL"),
        summarize(df, ["venue_bucket"], "VENUE"),
        summarize(df, ["curve_bucket"], "CURVE"),
        summarize(df, ["market_bucket"], "MARKET"),
        summarize(df, ["venue_bucket", "curve_bucket"], "VENUE_x_CURVE"),
        summarize(df, ["venue_bucket", "market_bucket"], "VENUE_x_MARKET"),
        summarize(df, ["venue_bucket", "curve_bucket", "market_bucket"], "VENUE_x_CURVE_x_MARKET"),
    ]
    breakdown = pd.concat(pieces, ignore_index=True)
    strata_cols = ["venue_bucket", "curve_bucket", "market_bucket"]
    other_cols = [c for c in breakdown.columns if c not in strata_cols and c != "dimension"]
    breakdown = breakdown[["dimension"] + strata_cols + other_cols]

    lines = []
    lines.append("=" * 78)
    lines.append("D2C VENUE-WHITELIST SKEW DIAGNOSTIC (Task A2)")
    lines.append("=" * 78)
    lines.append(
        "Row counts (n_total) below are unit-count; dv01_pct_paid weights each\n"
        "unit by its total leg DV01 instead of counting it once."
    )
    lines.append("")

    with pd.option_context("display.max_columns", None, "display.width", 160):
        for dim in [
            "OVERALL", "VENUE", "CURVE", "MARKET",
            "VENUE_x_CURVE", "VENUE_x_MARKET", "VENUE_x_CURVE_x_MARKET",
        ]:
            sub = breakdown[breakdown["dimension"] == dim].drop(columns=["dimension"])
            sub = sub.dropna(axis=1, how="all")
            lines.append(f"--- {dim} ---")
            lines.append(sub.to_string(index=False))
            lines.append("")

    # Headline comparison: cleanest stratum vs dirtiest stratum vs overall.
    def _lookup(venue, curve, market):
        m = (
            (breakdown["dimension"] == "VENUE_x_CURVE_x_MARKET")
            & (breakdown["venue_bucket"] == venue)
            & (breakdown["curve_bucket"] == curve)
            & (breakdown["market_bucket"] == market)
        )
        hit = breakdown[m]
        if hit.empty:
            return None
        r = hit.iloc[0]
        return r["n_classified"], r["pct_paid"], r["dv01_pct_paid"]

    overall_row = breakdown[breakdown["dimension"] == "OVERALL"].iloc[0]
    clean = _lookup("D2C_WHITELISTED", "CURVE_CLEAN", "ON_MARKET")
    dirty = _lookup("VENUE_UNKNOWN", "CURVE_SUSPECT", "OFF_MARKET")

    lines.append("=" * 78)
    lines.append("HEADLINE: is the skew concentrated in the contaminated strata?")
    lines.append("=" * 78)
    lines.append(
        f"OVERALL (all units):                 n_classified={int(overall_row['n_classified'])}, "
        f"pct_paid={overall_row['pct_paid']}, dv01_pct_paid={overall_row['dv01_pct_paid']}"
    )
    if clean is not None:
        n, p, dv = clean
        lines.append(
            f"CLEANEST (whitelisted, curve-clean,   n_classified={n}, pct_paid={p}, dv01_pct_paid={dv}"
        )
        lines.append("  on-market):")
    else:
        lines.append("CLEANEST (whitelisted, curve-clean, on-market): no rows in this cell.")
    if dirty is not None:
        n, p, dv = dirty
        lines.append(
            f"DIRTIEST (unknown-venue, curve-susp., n_classified={n}, pct_paid={p}, dv01_pct_paid={dv}"
        )
        lines.append("  off-market):")
    else:
        lines.append("DIRTIEST (unknown-venue, curve-suspect, off-market): no rows in this cell.")
    lines.append("")
    lines.append(
        "If pct_paid in the CLEANEST cell is materially closer to 50/50 than\n"
        "OVERALL/DIRTIEST, the ~67/33 skew is at least partly an artifact of\n"
        "unvalidated venue / curve-suspect / off-market contamination. If the\n"
        "CLEANEST cell still shows a comparable skew, the skew survives the\n"
        "cleanest-available stratification and is more likely real flow (still\n"
        "not proof -- see the audit's h/sigma discussion; direction accuracy\n"
        "remains uncertified without external truth labels)."
    )

    report_text = "\n".join(str(l) for l in lines)
    return breakdown, report_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", default=None,
        help="If given, write d2c_skew_diagnostic_breakdown.csv and "
             "d2c_skew_diagnostic_summary.txt into this directory.",
    )
    args = parser.parse_args()

    engine = create_db_engine()
    direction = load_direction(engine)
    if direction.empty:
        print("arbs_stir_direction_v1 is empty -- nothing to diagnose.", file=sys.stderr)
        return 1
    platforms = load_platform_ids(engine, direction)
    df = enrich(direction, platforms)

    n_missing_platform = int(df["platform_identifier"].isna().sum())
    breakdown, report_text = build_report(df)

    header = (
        f"Loaded {len(direction)} classified units from arbs_stir_direction_v1 "
        f"spanning as_of_date {direction['as_of_date'].min()} -> {direction['as_of_date'].max()}.\n"
        f"Resolved platform_identifier for {len(direction) - n_missing_platform}/{len(direction)} "
        f"units ({n_missing_platform} unmatched against arbs_usd_swap_tape_legs_v2).\n"
    )
    full_text = header + "\n" + report_text
    print(full_text)

    if args.out_dir:
        out_dir = pathlib.Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        breakdown.to_csv(out_dir / "d2c_skew_diagnostic_breakdown.csv", index=False)
        (out_dir / "d2c_skew_diagnostic_summary.txt").write_text(full_text, encoding="utf-8")
        print(f"\nWrote {out_dir / 'd2c_skew_diagnostic_breakdown.csv'}")
        print(f"Wrote {out_dir / 'd2c_skew_diagnostic_summary.txt'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
