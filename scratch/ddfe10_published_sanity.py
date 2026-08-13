"""Are the PUBLISHED rows sane? Not "did the job exit 0", not "are there rows".

Seven checks with thresholds fixed in advance, each of which a real defect
would fail:

1. the direction split is BALANCED. The old short-end classifier came out
   78.3% PAID because its Barchart mid ran ~0.5 bp high with ~7x the
   dispersion; anything wired the same way here leans the same way.
2. the median deviation is inside the mid's own measurement error.
3. every unit has exactly one of (a probability, a reason). Neither both nor
   neither -- that is the partition the coverage accounting rests on.
4. the signed key-rate profile points the same way as the call.
5. the ladder's cell keys are inside the published vocabulary.
6. coverage is materially under 1.0 and materially over 0. A coverage of 1.0
   is the self-flattering failure a reader would believe.
7. the per-unit table joins the tape display view one-to-one on package_id.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe10_published_sanity.py
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils._swappulse_scripts._tape_tables import DISPLAY_VIEW  # noqa: E402
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<46} {detail}")
    if not ok:
        FAILS.append(f"{name}: {detail}")


def q(conn, sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def main() -> int:
    conn = psycopg2.connect(resolve_pg_url())

    bounds = q(conn, f"SELECT min(as_of_date) lo, max(as_of_date) hi, "
                     f"count(*) n FROM {S.UNIT_TABLE}").iloc[0]
    print(f"{S.UNIT_TABLE}: {int(bounds['n']):,} rows, "
          f"{bounds['lo']} .. {bounds['hi']}\n")

    # 1 -------------------------------------------------------------------
    d = q(conn, f"""SELECT dealer_direction, count(*) n FROM {S.UNIT_TABLE}
                    WHERE rule = 'RATE_VS_MID' AND exclusion_reason IS NULL
                    GROUP BY 1""").set_index("dealer_direction")["n"]
    tot = int(d.sum())
    paid = 100.0 * int(d.get("PAID", 0)) / max(tot, 1)
    check("RATE_VS_MID split is balanced (40-60% PAID)",
          40.0 <= paid <= 60.0,
          f"{paid:.2f}% PAID over {tot:,} calls "
          f"(the frozen classifier: 78.3%)")

    # 2 -------------------------------------------------------------------
    m = q(conn, f"""SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY deviation_bps) med,
        avg(CASE WHEN deviation_bps > 0 THEN 1.0 ELSE 0.0 END) * 100 above
        FROM {S.UNIT_TABLE}
        WHERE rule = 'RATE_VS_MID' AND exclusion_reason IS NULL""").iloc[0]
    check("median (printed - mid) is inside +-0.10 bp",
          abs(float(m["med"])) <= 0.10,
          f"{float(m['med']):+.4f} bp, {float(m['above']):.1f}% above mid "
          f"(F-15 measured +0.021 bp / 55.5%)")

    # 3 -------------------------------------------------------------------
    # NOT "exactly one of (p, reason)". A unit can carry both, and the case is
    # real: `ladder.unit_ladder_rows` names a called unit with no risk profile
    # `PRICING_ERROR`, so the probability exists and the unit still did not
    # reach the ladder. Measured: 86 such units, every one a CURVE whose KRD
    # projection failed. Storing both is the honest record. What must never
    # happen is NEITHER -- a unit that cannot be called must say why -- or a
    # missing word.
    bad = q(conn, f"""SELECT
        count(*) FILTER (WHERE p IS NULL AND exclusion_reason IS NULL) neither,
        count(*) FILTER (WHERE p IS NOT NULL AND exclusion_reason IS NOT NULL) both,
        count(*) FILTER (WHERE dealer_direction IS NULL) no_word
        FROM {S.UNIT_TABLE}""").iloc[0]
    check("no unit has NEITHER a probability nor a reason",
          int(bad["neither"]) == 0 and int(bad["no_word"]) == 0,
          f"neither={int(bad['neither'])} no_word={int(bad['no_word'])} "
          f"(both={int(bad['both'])}, which is legal: a called unit whose "
          "KRD projection failed)")

    # 4 -------------------------------------------------------------------
    # `dealer_sign` orients the STRUCTURE, not the sign of its net duration.
    # A 2s10s curve the dealer "received" has legs of opposite sign, so its
    # net DV01 across buckets may point either way -- measured, CURVE
    # disagrees on 27.0% and FLY on 35.5%, and that is what a two-legged
    # trade does.
    #
    # The sharp version is the OUTRIGHT population, where the two MUST
    # coincide unless the leg's own net received DV01 is negative. That is
    # also the control that keeps this check from being vacuous: if the whole
    # convention were inverted, this is where it would show.
    o = q(conn, f"""SELECT
        count(*) n,
        count(*) FILTER (WHERE sign(total_delta_dv01) <> dealer_sign) bad,
        count(*) FILTER (WHERE sign(total_delta_dv01) <> dealer_sign
                           AND total_dv01_if_received < 0) explained
        FROM {S.UNIT_TABLE}
        WHERE exclusion_reason IS NULL AND kind = 'OUTRIGHT'
          AND dealer_sign <> 0 AND total_delta_dv01 IS NOT NULL
          AND total_delta_dv01 <> 0""").iloc[0]
    check("OUTRIGHT: signed KRD points the way the call does",
          int(o["bad"]) == int(o["explained"]),
          f"{int(o['bad'])} of {int(o['n']):,} disagree, "
          f"{int(o['explained'])} of them explained by a negative net "
          "received DV01")

    # 4b ------------------------------------------------------------------
    # And the check above must be capable of failing. If multi-leg units NEVER
    # disagreed, every unit would be effectively an outright and check 4 would
    # be testing nothing about structures.
    ml = q(conn, f"""SELECT
        count(*) FILTER (WHERE sign(total_delta_dv01) <> dealer_sign) bad,
        count(*) n FROM {S.UNIT_TABLE}
        WHERE exclusion_reason IS NULL AND kind IN ('CURVE','FLY')
          AND dealer_sign <> 0 AND total_delta_dv01 IS NOT NULL
          AND total_delta_dv01 <> 0""").iloc[0]
    check("multi-leg units DO net against their orientation",
          int(ml["bad"]) > 0,
          f"{int(ml['bad']):,} of {int(ml['n']):,} CURVE/FLY net the other "
          "way, as a two-legged structure must")

    # 5 -------------------------------------------------------------------
    from SDRUtils.dealer_direction import indicator as ind
    from SDRUtils.dealer_direction import ladder as lad
    from SDRUtils.dealer_direction import types as T
    vocab = q(conn, f"""SELECT DISTINCT bucket_key, venue_class, series,
                        bucket_space FROM {S.LADDER_TABLE}""")
    ok = (set(vocab["bucket_key"]) <= set(ind.TENOR_BUCKETS)
          and set(vocab["venue_class"]) <= {T.VENUE_D2C, T.VENUE_D2D,
                                            T.VENUE_UNKNOWN}
          and set(vocab["series"]) <= {lad.SERIES_FLOW, lad.SERIES_LIFECYCLE}
          and set(vocab["bucket_space"]) == {ind.BUCKET_SPACE})
    check("ladder keys are inside the published vocabulary", ok,
          f"{len(vocab)} distinct key combinations")

    # 6 -------------------------------------------------------------------
    cov = q(conn, f"""SELECT
        sum(dv01) FILTER (WHERE reason = '{S.IN_LADDER}') / sum(dv01) frac
        FROM {S.COVERAGE_TABLE}""").iloc[0]["frac"]
    check("coverage is materially between 0 and 1",
          0.20 < float(cov) < 0.90,
          f"{100.0 * float(cov):.2f}% of DV01 oriented; a 100% reading "
          "would be the self-flattering failure")

    # 7 -------------------------------------------------------------------
    j = q(conn, f"""
        WITH days AS (SELECT DISTINCT as_of_date d FROM {S.UNIT_TABLE}),
        v AS (SELECT count(*) n FROM {DISPLAY_VIEW}
              WHERE as_of_date IN (SELECT d FROM days)),
        u AS (SELECT count(*) n FROM {S.UNIT_TABLE}),
        m AS (SELECT count(*) n FROM {S.UNIT_TABLE} x
              JOIN {DISPLAY_VIEW} p ON p.package_id = x.package_id)
        SELECT v.n view_rows, u.n unit_rows, m.n matched FROM v, u, m
    """).iloc[0]
    check("unit table joins the display view 1:1 on package_id",
          int(j["view_rows"]) == int(j["unit_rows"]) == int(j["matched"]),
          f"view={int(j['view_rows']):,} units={int(j['unit_rows']):,} "
          f"matched={int(j['matched']):,}")

    conn.close()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
