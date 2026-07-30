"""Per-session coverage of the dealer-ladder dataset. READ-ONLY.

The Phase B deliverable: for every trading day in the window, how many units were
classified, how many reached the ladder, how many were marked, what share is UNKNOWN,
and whether the whole thing was written by ONE code vintage.

Three things this is built to make impossible to miss.

**A day that is absent is not a day with no flow.** A missing session and a genuinely
empty one are different failures, and only the trading calendar can tell them apart, so
days are enumerated from the calendar and joined against, never listed from the data.

**A vintage mixture is a silent corruption.** These tables are upserted in place, so a
backfill interrupted and resumed under changed code leaves a table that is part one
vintage and part another with nothing in any single row to say so. `--strict` exits
non-zero on more than one vintage, or on any NULL vintage (rows written before the
column existed).

**Projected-but-unmarked and classified-but-unprojected are different diagnoses.**
The first is a marks-phase gap; the second means the risk model failed for that day,
which is the failure that once collapsed projection coverage from 74% to 0% behind a
bare ``except: pass``. They are reported as separate columns, never summed.

    conda run -n stir python scripts/dealer_ladder_coverage.py \
        --start 2026-01-12 --end 2026-07-29 --out coverage.md --strict
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

DIRECTION_SQL = """
SELECT as_of_date::date              AS day,
       count(*)                      AS classified,
       count(*) FILTER (WHERE dealer_direction = 'PAID')     AS paid,
       count(*) FILTER (WHERE dealer_direction = 'RECEIVED') AS received,
       count(*) FILTER (WHERE dealer_direction = 'UNKNOWN')  AS unknown,
       count(*) FILTER (WHERE curve_suspect_trade)           AS curve_suspect,
       count(DISTINCT classification_method)                 AS n_methods
FROM arbs_stir_direction_v1
WHERE as_of_date BETWEEN %(start)s AND %(end)s
GROUP BY 1 ORDER BY 1
"""

LADDER_SQL = """
SELECT as_of_date::date              AS day,
       count(DISTINCT unit_key)      AS projected_units,
       count(*)                      AS ladder_rows,
       count(DISTINCT bucket_space)  AS n_spaces,
       count(*) FILTER (WHERE bucket_space = 'FUTURES')      AS futures_rows,
       count(*) FILTER (WHERE bucket_space = 'FED_FUNDS')    AS ff_rows,
       count(*) FILTER (WHERE bucket_space = 'MEETING')      AS meeting_rows,
       count(*) FILTER (WHERE bucket_space = 'SERFF_BASIS')  AS serff_rows,
       count(*) FILTER (WHERE p_flip IS NULL)                AS null_p_flip,
       count(*) FILTER (WHERE delta_dv01 IS NULL)            AS null_delta
FROM arbs_stir_ladder_prints_v1
WHERE as_of_date BETWEEN %(start)s AND %(end)s
GROUP BY 1 ORDER BY 1
"""

# Marks are keyed by MARK date; projections by TRADE date. Counting marks per mark-date
# and dividing by units projected that day mixes the two, because a unit from an earlier
# session still gets an EOD mark today -- which is how the first version of this report
# produced a "marked 107.8%" column. Coverage has to be asked per UNIT: of the units
# projected on day D, how many were ever marked?
MARKS_SQL = """
SELECT l.day                                                     AS day,
       count(DISTINCT l.unit_key)                                AS projected_units_j,
       count(DISTINCT m.unit_key)                                AS marked_units,
       count(DISTINCT CASE WHEN m.mark_kind = 'ENTRY'
                           THEN m.unit_key END)                  AS entry_marked_units,
       count(DISTINCT CASE WHEN m.mark_kind = 'EOD'
                           THEN m.unit_key END)                  AS eod_marked_units,
       count(m.*)                                                AS marks,
       count(*) FILTER (WHERE m.unit_key IS NOT NULL
                          AND m.npv_usd IS NULL)                 AS null_npv
FROM (SELECT DISTINCT unit_key, as_of_date::date AS day
      FROM arbs_stir_ladder_prints_v1
      WHERE as_of_date BETWEEN %(start)s AND %(end)s) l
LEFT JOIN arbs_stir_book_marks_v1 m ON m.unit_key = l.unit_key
GROUP BY 1 ORDER BY 1
"""

VINTAGE_SQL = """
SELECT '{table}' AS tbl, coalesce(code_vintage, '(null)') AS code_vintage,
       count(*) AS rows, min(as_of_date)::date AS first_day,
       max(as_of_date)::date AS last_day
FROM {table}
WHERE as_of_date BETWEEN %(start)s AND %(end)s
GROUP BY 2 ORDER BY 3 DESC
"""

# The vintages of rows the STUDY can actually reach. `_PRINTS_SQL` inner-joins the ladder to
# the direction table, so a direction row with no ladder row is invisible to every gate --
# and 147 such rows exist, left from before the code_vintage column, which July's purge can
# never remove because that purge is skipped whenever any day errored and 2026-07-03 is a
# market holiday that errors every time. Counting them would fail --strict for a benign
# reason, and a gate that fails for benign reasons is a gate that gets relaxed.
STUDY_VINTAGE_SQL = """
SELECT coalesce(l.code_vintage, '(null)') AS ladder_vintage,
       coalesce(d.code_vintage, '(null)') AS direction_vintage,
       count(*) AS rows
FROM arbs_stir_ladder_prints_v1 l
JOIN arbs_stir_direction_v1 d USING (unit_key)
WHERE l.as_of_date BETWEEN %(start)s AND %(end)s
GROUP BY 1, 2 ORDER BY 3 DESC
"""


def _connect():
    """The study's own connector, so this reads exactly the DB the gates read."""
    from BT.dealer_ladder import data
    return data.connect()


def _read(conn, sql, params):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)     # pandas/psycopg2 chatter
        return pd.read_sql(sql, conn, params=params)


def trading_days(start, end) -> list[datetime.date]:
    from BT.dealer_ladder import data
    return list(data.trading_days((start, end)))


def build(conn, start, end) -> dict:
    params = {"start": start, "end": end}

    def _days(frame):
        """One dtype for the join key. The calendar yields `datetime.date` and the
        driver yields object-dtype dates, which pandas refuses to merge."""
        frame = frame.copy()
        frame["day"] = pd.to_datetime(frame["day"])
        return frame

    days = _days(pd.DataFrame({"day": trading_days(start, end)}))
    direction = _days(_read(conn, DIRECTION_SQL, params))
    ladder = _days(_read(conn, LADDER_SQL, params))
    marks = _days(_read(conn, MARKS_SQL, params))

    # LEFT join from the CALENDAR: a session missing from the data must show as a row
    # of zeros, because "absent" and "no flow" are different failures.
    cov = days.merge(direction, on="day", how="left") \
              .merge(ladder, on="day", how="left") \
              .merge(marks, on="day", how="left")
    # A query that returned NO rows contributes no COLUMNS either, so every later
    # reference to e.g. `null_delta` would raise instead of reporting zero -- and an
    # empty window is exactly when this report is most needed.
    expected = ["classified", "paid", "received", "unknown", "curve_suspect",
                "n_methods", "projected_units", "ladder_rows", "n_spaces",
                "futures_rows", "ff_rows", "meeting_rows", "serff_rows",
                "null_p_flip", "null_delta", "marked_units", "entry_marked_units",
                "eod_marked_units", "marks", "null_npv"]
    for col in expected:
        if col not in cov.columns:
            cov[col] = 0
    counts = [c for c in cov.columns if c != "day"]
    cov[counts] = cov[counts].fillna(0).astype("int64")

    cov["unknown_pct"] = (100.0 * cov["unknown"]
                          / cov["classified"].replace(0, np.nan)).astype(float)
    cov["projected_pct"] = (100.0 * cov["projected_units"]
                            / cov["classified"].replace(0, np.nan)).astype(float)
    # marked_units now comes from a per-UNIT join against the units projected that
    # day, so this ratio cannot exceed 100% the way the mark-date version did
    cov["marked_pct"] = (100.0 * cov["marked_units"]
                         / cov["projected_units"].replace(0, np.nan)).astype(float)
    cov["eod_marked_pct"] = (100.0 * cov["eod_marked_units"]
                             / cov["projected_units"].replace(0, np.nan)).astype(float)
    if not (cov["marked_units"] <= cov["projected_units"]).all():
        raise AssertionError(
            "per-unit marks coverage exceeds the units projected, which means this "
            "reverted to counting marks by MARK date rather than per unit")
    if "projected_units_j" in cov.columns:
        both = cov[(cov["projected_units"] > 0) & (cov["projected_units_j"] > 0)]
        if not (both["projected_units"] == both["projected_units_j"]).all():
            raise AssertionError("the two projected-unit counts disagree; the marks "
                                 "join is not over the same unit set")
        cov = cov.drop(columns=["projected_units_j"])
    cov["paid_pct"] = (100.0 * cov["paid"]
                       / (cov["paid"] + cov["received"]).replace(0, np.nan)).astype(float)

    vint_parts = [_read(conn, VINTAGE_SQL.format(table=tbl), params)
                  for tbl in ("arbs_stir_direction_v1", "arbs_stir_ladder_prints_v1")
                  if _has_column(conn, tbl, "code_vintage")]
    vint = (pd.concat(vint_parts, ignore_index=True) if vint_parts
            else pd.DataFrame(columns=["tbl", "code_vintage", "rows"]))

    study_vint = _read(conn, STUDY_VINTAGE_SQL, params)
    return {"coverage": cov, "vintages": vint, "study_vintages": study_vint}


def _has_column(conn, table, column) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s", (table, column))
        return cur.fetchone() is not None


def problems(res: dict) -> list[str]:
    """Everything a reader must not be allowed to skim past."""
    out = []
    cov, vint = res["coverage"], res["vintages"]
    empty = cov[cov["classified"] == 0]
    if len(empty):
        out.append(f"{len(empty)} trading sessions with ZERO classified units: "
                   + ", ".join(str(d) for d in pd.to_datetime(empty['day']).dt.strftime('%Y-%m-%d').head(12)))
    unproj = cov[(cov["classified"] > 0) & (cov["projected_units"] == 0)]
    if len(unproj):
        out.append(f"{len(unproj)} sessions classified but NEVER PROJECTED (the risk "
                   f"model failed for the whole day): "
                   + ", ".join(str(d) for d in pd.to_datetime(unproj['day']).dt.strftime('%Y-%m-%d').head(12)))
    unmarked = cov[(cov["projected_units"] > 0) & (cov["marked_units"] == 0)]
    if len(unmarked):
        out.append(f"{len(unmarked)} sessions projected but never marked: "
                   + ", ".join(str(d) for d in pd.to_datetime(unmarked['day']).dt.strftime('%Y-%m-%d').head(12)))
    if (cov["null_delta"] > 0).any():
        bad = cov[cov["null_delta"] > 0]
        out.append(f"{len(bad)} sessions with NULL delta_dv01 in the ladder — the "
                   f"all-NaN-risk hazard, published as success (07/06 incident)")
    hi = cov["unknown_pct"].fillna(0)
    if (hi > 5.0).any():
        worst = cov.loc[hi.idxmax()]
        out.append(f"{int((hi > 5.0).sum())} sessions above 5% UNKNOWN "
                   f"(worst {pd.Timestamp(worst['day']).date()} at {worst['unknown_pct']:.1f}%)")
    # --strict keys on the STUDY-VISIBLE rows. A vintage that appears only in rows no gate
    # can reach is reported below as context, not as a failure.
    sv = res.get("study_vintages")
    if sv is not None and len(sv):
        pairs = {(r.ladder_vintage, r.direction_vintage) for r in sv.itertuples()}
        if len(pairs) > 1:
            out.append("the STUDY-VISIBLE rows span "
                       + f"{len(pairs)} (ladder, direction) vintage pairs: "
                       + ", ".join(f"{a}/{b}" for a, b in sorted(pairs)))
        nulls = sv[(sv["ladder_vintage"] == "(null)")
                   | (sv["direction_vintage"] == "(null)")]
        if len(nulls):
            out.append(f"{int(nulls['rows'].sum())} STUDY-VISIBLE rows have a NULL "
                       f"code_vintage")
    return out


def render(res: dict, start, end) -> str:
    cov, vint = res["coverage"], res["vintages"]
    cols = ["day", "classified", "paid", "received", "unknown", "unknown_pct",
            "curve_suspect", "projected_units", "projected_pct", "ladder_rows",
            "futures_rows", "ff_rows", "meeting_rows", "serff_rows",
            "marked_units", "marked_pct", "eod_marked_units", "eod_marked_pct",
            "paid_pct"]
    show = cov[[c for c in cols if c in cov.columns]].copy()
    show["day"] = pd.to_datetime(show["day"]).dt.strftime("%Y-%m-%d")
    for c in ("unknown_pct", "projected_pct", "marked_pct", "eod_marked_pct",
              "paid_pct"):
        if c in show.columns:
            show[c] = show[c].map(lambda v: "" if pd.isna(v) else f"{v:.1f}")

    lines = [f"# Dealer-ladder dataset coverage, {start} → {end}", "",
             "<!-- GENERATED by scripts/dealer_ladder_coverage.py — re-run, do not "
             "edit. Days come from the TRADING CALENDAR, so an absent session shows "
             "as a row of zeros rather than vanishing. -->", ""]

    tot = cov.sum(numeric_only=True)
    lines += ["## Totals", "",
              f"- **{len(cov)} trading sessions** in the window",
              f"- **{int(tot['classified']):,} units classified**, of which "
              f"{int(tot['paid']):,} PAID / {int(tot['received']):,} RECEIVED / "
              f"{int(tot['unknown']):,} UNKNOWN "
              f"({100.0 * tot['unknown'] / max(tot['classified'], 1):.2f}%)",
              f"- **{int(tot['projected_units']):,} units projected** onto "
              f"{int(tot['ladder_rows']):,} ladder rows "
              f"({100.0 * tot['projected_units'] / max(tot['classified'], 1):.1f}% of "
              f"classified)",
              f"- **{int(tot['marked_units']):,} of those units carry a mark** "
              f"({100.0 * tot['marked_units'] / max(tot['projected_units'], 1):.1f}%), "
              f"{int(tot['eod_marked_units']):,} with an EOD mark, across "
              f"{int(tot['marks']):,} marks in total",
              f"- PAID share of signed units: "
              f"**{100.0 * tot['paid'] / max(tot['paid'] + tot['received'], 1):.1f}%**",
              ""]

    probs = problems(res)
    lines += ["## Anomalies", ""]
    if probs:
        lines += [f"- **{p}**" for p in probs]
    else:
        lines.append("- None: every session classified, projected, marked, under a "
                     "single code vintage.")
    lines.append("")

    sv = res.get("study_vintages")
    if sv is not None and len(sv):
        lines += ["## Code vintages, STUDY-VISIBLE rows only", "",
                  "Rows reachable through the ladder-to-direction join, which is what every "
                  "gate reads. `--strict` keys on this table.", "",
                  sv.to_markdown(index=False), ""]
    if len(vint):
        lines += ["## Code vintages, every row in each table", "",
                  "Includes rows no gate can reach \u2014 notably direction rows with no ladder "
                  "row, which predate the `code_vintage` column and which July's purge can "
                  "never remove, because that purge is skipped whenever any day errored and "
                  "2026-07-03 is a market holiday that errors every time.", "",
                  vint.to_markdown(index=False), ""]

    lines += ["## Per-session", "", show.to_markdown(index=False), ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--end", type=lambda s: datetime.date.fromisoformat(s),
                    required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any anomaly is present")
    args = ap.parse_args(argv)

    # This prints markdown with arrows and en-dashes; a Windows console defaults to
    # cp1252 and would die on them mid-report rather than at the start.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    conn = _connect()
    try:
        res = build(conn, args.start, args.end)
    finally:
        conn.close()

    md = render(res, args.start, args.end)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md + "\n")
        print(f"wrote {args.out}")
    else:
        print(md)

    probs = problems(res)
    for p in probs:
        print(f"ANOMALY: {p}", file=sys.stderr)
    return 1 if (args.strict and probs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
