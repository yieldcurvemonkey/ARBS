"""The known-answer gate for ``RULE_PACKAGE_PRICE``, computed and named.

``package_price.py``'s docstring quotes a table -- 94.70% on CURVE, 91.08% on
FLY, 45.95% agreement with the rate rule, 78.6/98.2% by solver tier -- measured
on "12 days spread across the pinned window". **The days were not named and no
script in the tree computed any of it**, so none of it was reproducible. This
is that script.

DAY SELECTION IS A RULE, NOT A CHOICE. The first tape day on or after the 15th
of every third month from 2024-03 to 2026-08. Written here, evaluated below,
and printed with the results -- so the population cannot be shopped toward a
number after the fact.

WHAT IS BEING TESTED. ``conventions.base_orientation`` fixes the answer for a
CURVE and a FLY by market convention. This rule derives the same object from
the legs' fees against the package price, which is a completely different
input. If the fee-derived orientation reproduces the convention, the
identification claim is evidence; if it reproduces it at chance, it is not.

THE CONDITIONING MATTERS AND IS REPORTED BOTH WAYS. ``universe.unit_frame``
names a unit CURVE on **leg count alone**, and a 2-leg package can be a strip,
a roll or a block split, for which "one payer, one receiver" is simply false.
So the run reports the unconditional number AND the number conditioned on the
tape's own ``package_type``, with the residue as the placebo: a 3-leg unit the
tape does not call a FLY should come in at 25%, and if it does not, the
conditioning is doing something other than what it claims.

AND THE ONE THE REVIEW ASKED FOR. Every unit carries ``margin_bps`` -- the
distance to the runner-up sign class -- so the table splits by whether the
orientation was IDENTIFIED. That is the transfer test: the gate was validated
on CURVE/FLY, the target population is PKG-4+, and the only thing that can
carry the validation across is a statistic that means the same thing in both.

Run::

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ppfix_known_answer.py price
    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ppfix_known_answer.py report
"""
from __future__ import annotations

import os
import pathlib
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

CACHE = pathlib.Path(os.environ.get("PPKA_CACHE", r"D:\ddfix3\ppka_cache"))
START, END = "2024-03-01", "2026-08-07"
SOURCE = "CITIVELO_EXCEL"        # must be the RL token; see scratch/dd_common.py


def day_rule(conn) -> list:
    """First tape day on or after the 15th of every third month in the window."""
    from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        days = pd.read_sql(
            f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} "
            "WHERE as_of_date BETWEEN %(a)s AND %(b)s ORDER BY 1",
            conn, params={"a": START, "b": END})["as_of_date"]
    days = pd.to_datetime(days).dt.date.tolist()
    out = []
    anchor = pd.Timestamp(START).normalize()
    while anchor <= pd.Timestamp(END):
        want = anchor.replace(day=15).date()
        nxt = [d for d in days if d >= want]
        if nxt and nxt[0] <= pd.Timestamp(END).date() and nxt[0] not in out:
            out.append(nxt[0])
        anchor = anchor + pd.DateOffset(months=3)
    return out


def price_day(conn, day, repricer) -> pd.DataFrame:
    from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE
    from SDRUtils.dealer_direction import conventions as conv
    from SDRUtils.dealer_direction import package_price as pp
    from SDRUtils.dealer_direction.universe import build_units, load_legs
    from SDRUtils.packages.opa_sign_solver import solve_opa_signs

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = load_legs(conn, str(day), str(day))
        ptypes = pd.read_sql(
            f"SELECT package_id, package_type, legs_count FROM {PACKAGES_TABLE} "
            "WHERE as_of_date = %(d)s", conn, params={"d": str(day)})
    if raw.empty:
        return pd.DataFrame()
    ptype = dict(zip(ptypes["package_id"], ptypes["package_type"]))

    rows = []
    with repricer.day_scope():
        for unit in build_units(raw):
            if unit.kind not in (conv.CURVE, conv.FLY):
                continue
            legs = unit.legs
            opas = pd.to_numeric(legs["other_payment_amount"],
                                 errors="coerce").abs().to_numpy(float)
            pv = pd.to_numeric(legs["package_transaction_price"],
                               errors="coerce").dropna()
            if not len(pv) or not np.isfinite(opas).all():
                continue
            ptp = float(pv.iloc[0])
            if abs(ptp) <= pp.PTP_USD_FLOOR:
                continue
            rep = repricer.price_unit(unit)
            if rep.failure is not None or rep.pricing.npv_pay is None:
                rows.append({"day": str(day), "kind": unit.kind,
                             "package_type": ptype.get(unit.package_id),
                             "priced": False,
                             "reason": rep.failure or "NO_NPV"})
                continue
            f = [q.npv_pay for q in rep.legs]
            pv01s = [q.pv01 for q in rep.legs]
            mids = [q.mid_pct for q in rep.legs]
            dv01 = rep.pricing.structure_dv01
            if (dv01 is None or not np.isfinite(dv01) or dv01 <= 0
                    or any(v is None or not np.isfinite(v) for v in f)
                    or any(v == 0.0 for v in f)):
                rows.append({"day": str(day), "kind": unit.kind,
                             "package_type": ptype.get(unit.package_id),
                             "priced": False, "reason": "BAD_MARKS"})
                continue

            n = len(f)
            cash = pp.solve_cash_signs(opas.tolist(), ptp)
            tie = cash.residual / dv01
            margin = cash.margin / dv01
            o = pp.orientation_from_cash(cash.signs, f)
            known = conv.base_orientation(unit.kind, n, conv.RULE_RATE)
            match = (tuple(o) == tuple(known)
                     or tuple(o) == tuple(-x for x in known))

            # the rate rule's own answer for the same unit
            rates = [float(r) * 100.0 for r in
                     pd.to_numeric(legs["fixed_rate"], errors="coerce")]
            dev_bp = (conv.structure_price(rates, unit.kind, n, conv.RULE_RATE)
                      - conv.structure_price(mids, unit.kind, n, conv.RULE_RATE))
            # `dealer_received_signs` raises on the zero branch, which is
            # correct -- a print exactly at mid has no side -- so it is not an
            # agreement observation and is recorded as missing, not as a
            # disagreement.
            rate_ans = (None if conv.dealer_side(dev_bp) == 0 else
                        conv.dealer_received_signs(unit.kind, n,
                                                   conv.RULE_RATE,
                                                   conv.dealer_side(dev_bp)))
            call = pp.classify(opas=opas.tolist(), package_price=ptp,
                               npv_pays=f, pv01s=pv01s, structure_dv01=dv01,
                               is_lifecycle=unit.is_lifecycle)
            agree = (None if (call.received_signs is None or rate_ans is None)
                     else bool(tuple(call.received_signs) == tuple(rate_ans)))
            worst = min(abs(fi) / abs(p) for fi, p in zip(f, pv01s) if p)
            rows.append({
                "day": str(day), "kind": unit.kind, "n_legs": n,
                "package_type": ptype.get(unit.package_id), "priced": True,
                "reason": None, "match": bool(match), "tieout_bps": tie,
                "margin_bps": margin,
                "identified": bool(tie + margin > pp.TIEOUT_MAX_BPS),
                "tie_ok": bool(tie <= pp.TIEOUT_MAX_BPS),
                "worst_leg_bp": float(worst), "dev_bp": float(dev_bp),
                "rate_agree": agree,
                "solver_tier": solve_opa_signs(opas.tolist(),
                                               ptp)["confidence"],
                "exclusion": call.exclusion, "is_lifecycle": unit.is_lifecycle,
            })
    return pd.DataFrame(rows)


def do_price() -> int:
    import psycopg2

    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
    from SDRUtils.dealer_direction.midprice import UnitRepricer

    CACHE.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(resolve_pg_url())
    try:
        days = day_rule(conn)
        print("DAY RULE -> " + ", ".join(str(d) for d in days), flush=True)
        (CACHE / "days.txt").write_text("\n".join(str(d) for d in days))
        repricer = UnitRepricer.for_source(SOURCE)
        for d in days:
            out = CACHE / f"ka_{d}.parquet"
            if out.exists():
                print(f"{d}: cached", flush=True)
                continue
            got = price_day(conn, d, repricer)
            got.to_parquet(out, index=False)
            ok = int(got["priced"].sum()) if len(got) else 0
            print(f"{d}: {len(got)} fee-bearing CURVE/FLY units, {ok} priced",
                  flush=True)
    finally:
        conn.close()
    return 0


def pctf(mask) -> str:
    m = np.asarray(mask, dtype=bool)
    return f"{100.0 * m.mean():6.2f}%" if len(m) else "     --"


def do_report() -> int:
    from SDRUtils.dealer_direction import package_price as pp

    parts = [pd.read_parquet(f) for f in sorted(CACHE.glob("ka_*.parquet"))]
    parts = [p for p in parts if len(p)]
    d = pd.concat(parts, ignore_index=True)
    # `priced=False` rows leave the bool columns as object, and `~col` on an
    # object column is a bitwise negation of ints -- which silently indexes by
    # -1/-2 instead of masking. Coerce before any of them is used.
    for c in ("priced", "match", "identified", "tie_ok", "is_lifecycle"):
        d[c] = d[c].fillna(False).astype(bool)
    days = sorted(d["day"].unique())
    print(f"DAYS ({len(days)}): " + ", ".join(days))
    print(f"fee-bearing CURVE/FLY units with a usable package price: {len(d):,}")
    npriced = int(d["priced"].sum())
    print(f"priced: {npriced:,}   unpriced: {len(d) - npriced:,}")
    if len(d) - npriced:
        print(d.loc[~d["priced"], "reason"].value_counts().to_string())
    p = d[d["priced"]].copy()
    print()

    print("=== A. does the fee-derived orientation reproduce the market "
          "convention? ===")
    for kind, chance in (("CURVE", "50%"), ("FLY", "25%")):
        sub = p[p["kind"] == kind]
        tape = sub[sub["package_type"] == kind]
        print(f"  {kind:<6s} by leg count           n={len(sub):>5}  "
              f"match {pctf(sub['match'])}   (chance {chance})")
        print(f"    ... tape package_type={kind:<6s} n={len(tape):>5}  "
              f"match {pctf(tape['match'])}")
        for thr in (0.25, 1.0):
            w = tape[tape["worst_leg_bp"] >= thr]
            print(f"        ... worst leg >= {thr:<4} bp from mid  "
                  f"n={len(w):>5}  match {pctf(w['match'])}")
        res = sub[sub["package_type"] != kind]
        print(f"    PLACEBO: same leg count, tape does NOT call it {kind}  "
              f"n={len(res):>5}  match {pctf(res['match'])}   "
              f"(chance {chance})")
    print()

    print("=== B. the transfer test -- does the margin separate the hits from "
          "the misses? ===")
    print("    (this is what has to be true for a gate validated on CURVE/FLY "
          "to mean anything on a PKG-4+)")
    for kind in ("CURVE", "FLY"):
        tape = p[(p["kind"] == kind) & (p["package_type"] == kind)
                 & p["tie_ok"]]
        for lab, sel in (("IDENTIFIED", tape[tape["identified"]]),
                         ("AMBIGUOUS ", tape[~tape["identified"]])):
            print(f"  {kind:<6s} {lab}  n={len(sel):>5}  "
                  f"match {pctf(sel['match'])}")
    print()
    print("  match rate by margin band (tape CURVE+FLY, tie-out passed):")
    tape = p[(p["package_type"] == p["kind"]) & p["tie_ok"]]
    bands = [(0.0, 0.05), (0.05, 0.25), (0.25, 1.0), (1.0, 5.0),
             (5.0, np.inf)]
    for lo, hi in bands:
        s = tape[(tape["margin_bps"] >= lo) & (tape["margin_bps"] < hi)]
        print(f"    margin [{lo:>5}, {hi:>5})  n={len(s):>5}  "
              f"match {pctf(s['match'])}")
    print()
    print("  and the CONTROL -- the same split on the tie-out residual, which "
          "is the statistic")
    print("  that was already there. If it separated hits from misses the "
          "margin would be redundant:")
    for lo, hi in [(0.0, 1e-9), (1e-9, 0.05), (0.05, 0.25), (0.25, 0.5),
                   (0.5, 1.0)]:
        s = tape[(tape["tieout_bps"] >= lo) & (tape["tieout_bps"] < hi)]
        print(f"    tieout [{lo:g}, {hi:g})  n={len(s):>5}  "
              f"match {pctf(s['match'])}   identified-share "
              f"{pctf(s['identified'])}")
    print()

    print("=== C. the misses are the near-mid legs, not a second failure "
          "mode ===")
    tape = p[(p["package_type"] == p["kind"])]
    hit, miss = tape[tape["match"]], tape[~tape["match"]]
    print(f"  median worst-leg distance from mid: hits "
          f"{hit['worst_leg_bp'].median():.3f} bp, misses "
          f"{miss['worst_leg_bp'].median():.3f} bp   "
          f"(n hits {len(hit)}, n misses {len(miss)})")
    print()

    print("=== D. the solver's own confidence tiers are anti-informative ===")
    for tier, g in tape.groupby("solver_tier"):
        print(f"  {str(tier):<10s} n={len(g):>5}  match {pctf(g['match'])}")
    print()

    print("=== E. agreement with the RATE rule -- 50% is the expected number ===")
    ag = tape[tape["rate_agree"].notna()]
    print(f"  overall n={len(ag):>5}  agree {pctf(ag['rate_agree'].astype(bool))}")
    ab = ag["dev_bp"].abs()
    for lo, hi in [(0, 1), (1, 5), (5, 20), (20, 1e9)]:
        s = ag[(ab >= lo) & (ab < hi)]
        print(f"    |dev| in [{lo:>3}, {hi:>5}) bp  n={len(s):>5}  "
              f"agree {pctf(s['rate_agree'].astype(bool))}")
    print("  (a gradient with |dev| would be a sign bug; a flat line is two "
          "correct rules disagreeing about where the fee sits)")
    print()

    print("=== F. what the gate does to this population ===")
    tape2 = p[p["package_type"] == p["kind"]]
    print(tape2["exclusion"].fillna("(accepted)").value_counts().to_string())
    print()
    print(f"TIEOUT_MAX_BPS={pp.TIEOUT_MAX_BPS}  "
          f"LEG_SIGN_RESOLUTION_BPS={pp.LEG_SIGN_RESOLUTION_BPS}  "
          f"MARGIN_MAX_LEGS={pp.MARGIN_MAX_LEGS}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    raise SystemExit(do_price() if cmd == "price" else do_report())
