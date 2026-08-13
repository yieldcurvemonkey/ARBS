"""Can the chart's mid LINE come from arbs_dd_curve_mid_v1?

The chart currently reconstructs a mid per print:

    mid_pct = fixed_rate * 100 - deviation_bps / 100

which is exact for that print, but exists ONLY at print times. There is no line
between the marks -- and a scatter of mids is not a picture of where the market
was, it is a picture of where somebody traded.

arbs_dd_curve_mid_v1 now holds the continuous 1-minute par grid, priced by the
SAME SessionBranchPricer against the SAME curve. So the line can be real.

Before wiring it, four things have to be true, and each is a measurement rather
than an argument:

  1. The grid and the reconstruction AGREE where they should. If the line sits
     visibly off the marks, the reader learns that the market was somewhere the
     trades were not -- the exact inversion this whole panel exists to avoid.
  2. Where they DISAGREE, the reason is structural and nameable (a broken
     maturity, an IMM start), not unexplained.
  3. The grid COVERS the tenors the chart offers, per rate index.
  4. The join is an equality on a whole minute, not a nearest-neighbour search.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

warnings.simplefilter("ignore")
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 120)

PRINT_TENORS = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]


def main() -> int:
    conn = psycopg2.connect(resolve_pg_url())
    fail = []

    # -- 1. tenor coverage, per index, against what the chart offers -----------
    print("=" * 78)
    print("1. GRID COVERAGE vs the chart's tenor allow-list")
    print("=" * 78)
    have = pd.read_sql(
        "SELECT rate_index, tenor_label, count(*) n, min(grid_date) d0, max(grid_date) d1 "
        "FROM arbs_dd_curve_mid_v1 GROUP BY 1,2", conn)
    for idx in ("SOFR", "FED_FUNDS"):
        got = set(have.loc[have.rate_index == idx, "tenor_label"])
        missing = [t for t in PRINT_TENORS if t not in got]
        print(f"  {idx:<10} has {len(got)} tenors; chart offers 8; MISSING: {missing or 'none'}")
    print()
    print(have[have.tenor_label.isin(PRINT_TENORS)].sort_values(
        ["rate_index", "tenor_label"]).to_string(index=False))

    # -- 2. is ts always a whole minute? --------------------------------------
    print()
    print("=" * 78)
    print("2. IS THE JOIN AN EQUALITY? (every ts on a whole minute)")
    print("=" * 78)
    off = pd.read_sql(
        "SELECT count(*) n FROM arbs_dd_curve_mid_v1 WHERE EXTRACT(second FROM ts) <> 0", conn)
    n_off = int(off.n.iloc[0])
    print(f"  rows with a non-zero second: {n_off}")
    if n_off:
        fail.append(f"{n_off} grid rows are not on a whole minute")

    # -- 3. the residual, by structure type -----------------------------------
    # Join each OUTRIGHT print to the grid point at the minute of the curve
    # snapshot the print itself was repriced against. Same curve, same pricer,
    # same instant -- so anything left is the INSTRUMENT differing, not the mid.
    print()
    print("=" * 78)
    print("3. RECONSTRUCTED MID vs GRID MID, by special_tenor_type")
    print("=" * 78)
    q = """
      WITH p AS (
        SELECT u.package_id, u.rate_index, u.special_tenor_type,
               l.tenor_display,
               date_trunc('minute', u.curve_timestamp) AS minute,
               l.fixed_rate * 100.0 - u.deviation_bps / 100.0 AS recon_pct,
               l.effective_date, l.expiration_date
        FROM arbs_dd_unit_v1 u
        JOIN arbs_usd_swap_tape_legs_v3 l
          ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
        WHERE u.as_of_date = ANY(%(days)s::date[])
          AND u.kind = 'OUTRIGHT' AND u.n_legs = 1
          AND u.rule = 'RATE_VS_MID'
          AND u.exclusion_reason IS NULL
          AND u.deviation_bps IS NOT NULL
          AND u.curve_timestamp IS NOT NULL
          AND l.tenor_display = ANY(%(tenors)s::text[])
          AND COALESCE(l.forward_start_years, 0) <= 0.02
          AND COALESCE(l.is_off_market, false) = false
          AND COALESCE(l.other_payment_amount, 0) = 0
          AND COALESCE(l.other_payment_ufro, 0) = 0
          AND COALESCE(l.other_payment_uwin, 0) = 0
          AND COALESCE(l.other_payment_pexh, 0) = 0
      )
      SELECT p.rate_index, p.special_tenor_type, p.tenor_display,
             p.recon_pct, g.mid_pct AS grid_pct,
             (p.recon_pct - g.mid_pct) * 100.0 AS resid_bps,
             p.expiration_date, g.maturity_date, g.effective_date AS g_eff,
             p.effective_date AS p_eff
      FROM p
      LEFT JOIN arbs_dd_curve_mid_v1 g
        ON g.rate_index = p.rate_index
       AND g.tenor_label = p.tenor_display
       AND g.ts = p.minute
    """
    days = ["2026-08-07", "2026-07-15", "2026-05-20", "2026-02-11", "2025-11-05",
            "2025-06-17", "2024-10-08"]
    df = pd.read_sql(q, conn, params={"days": days, "tenors": PRINT_TENORS})
    print(f"  {len(df):,} OUTRIGHT prints over {len(days)} days spanning the window")
    matched = df[df.grid_pct.notna()]
    print(f"  grid point found for {len(matched):,} ({len(matched)/max(len(df),1)*100:.2f}%)")
    print()
    g = matched.groupby(["rate_index", "special_tenor_type"])["resid_bps"].agg(
        n="size", median="median", p95=lambda s: s.abs().quantile(0.95),
        maxabs=lambda s: s.abs().max())
    print(g.to_string())

    # STANDARD spot prints are the same instrument as the grid point. Anything
    # material there means the line and the marks disagree about the market.
    std = matched[(matched.special_tenor_type == "STANDARD")]
    if len(std):
        print()
        print(f"  STANDARD only: n={len(std):,} median={std.resid_bps.median():+.6f}bp "
              f"p95|.|={std.resid_bps.abs().quantile(.95):.6f}bp "
              f"max|.|={std.resid_bps.abs().max():.6f}bp")
        if std.resid_bps.abs().quantile(0.95) > 0.5:
            fail.append(
                f"STANDARD grid-vs-reconstructed p95 is "
                f"{std.resid_bps.abs().quantile(.95):.3f}bp -- the line would sit "
                f"visibly off the marks")

    # -- 4. does the maturity actually differ where the residual is big? -------
    print()
    print("=" * 78)
    print("4. IS THE RESIDUAL EXPLAINED BY THE INSTRUMENT, NOT THE MID?")
    print("=" * 78)
    matched = matched.copy()
    matched["mat_gap_days"] = (
        pd.to_datetime(matched.expiration_date) - pd.to_datetime(matched.maturity_date)
    ).dt.days.abs()
    matched["eff_gap_days"] = (
        pd.to_datetime(matched.p_eff) - pd.to_datetime(matched.g_eff)
    ).dt.days.abs()
    big = matched[matched.resid_bps.abs() > 0.5]
    small = matched[matched.resid_bps.abs() <= 0.5]
    for name, sub in (("resid >0.5bp", big), ("resid <=0.5bp", small)):
        if not len(sub):
            print(f"  {name:<14} n=0")
            continue
        print(f"  {name:<14} n={len(sub):>6,}  "
              f"median maturity gap {sub.mat_gap_days.median():>6.1f}d  "
              f"median effective gap {sub.eff_gap_days.median():>5.1f}d  "
              f"exact-instrument share "
              f"{((sub.mat_gap_days == 0) & (sub.eff_gap_days == 0)).mean()*100:5.1f}%")

    # -- 5. the nightly hole ---------------------------------------------------
    print()
    print("=" * 78)
    print("5. THE HOLE: prints at an hour the grid does not cover")
    print("=" * 78)
    hole = pd.read_sql("""
      SELECT EXTRACT(hour FROM u.execution_timestamp AT TIME ZONE 'America/New_York')::int AS et_hour,
             count(*) AS prints,
             count(g.mid_pct) AS with_grid
      FROM arbs_dd_unit_v1 u
      JOIN arbs_usd_swap_tape_legs_v3 l
        ON l.package_id = u.package_id AND l.as_of_date = u.as_of_date
      LEFT JOIN arbs_dd_curve_mid_v1 g
        ON g.rate_index = u.rate_index AND g.tenor_label = l.tenor_display
       AND g.ts = date_trunc('minute', u.execution_timestamp)
      WHERE u.as_of_date = ANY(%(days)s::date[])
        AND u.kind = 'OUTRIGHT' AND u.rule = 'RATE_VS_MID'
        AND u.exclusion_reason IS NULL
        AND l.tenor_display = ANY(%(tenors)s::text[])
      GROUP BY 1 ORDER BY 1
    """, conn, params={"days": days, "tenors": PRINT_TENORS})
    hole["cover_pct"] = hole.with_grid / hole.prints * 100
    print(hole.to_string(index=False))
    tot = hole.prints.sum()
    unc = tot - hole.with_grid.sum()
    print(f"\n  prints with NO grid point at their execution minute: "
          f"{unc:,} of {tot:,} ({unc/max(tot,1)*100:.2f}%)")

    conn.close()
    print()
    print("=" * 78)
    if fail:
        print(f"{len(fail)} BLOCKER(S):")
        for f in fail:
            print(f"  - {f}")
        return 1
    print("no blockers: the grid can carry the line")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
